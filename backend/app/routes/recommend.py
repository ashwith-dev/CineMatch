"""
app/routes/recommend.py
GET /recommend?q=<query>&page=<page>&sort=<sort>

Language logic:
  When user says "in Telugu" (or any language), we do TWO TMDB fetches:
    1. Telugu originals with genre filter
    2. Tamil + Hindi + Malayalam + Kannada films with same genre filter
       (these are commonly dubbed into Telugu)
  Results are merged and deduplicated — so user gets both originals AND dubbed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.parse_query import parse_query

logger = logging.getLogger(__name__)
router = APIRouter()

TMDB_BASE       = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_API_KEY    = os.getenv("TMDB_API_KEY", "")
REDIS_URL       = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL       = 60 * 30

GENRE_NAME_TO_ID: dict = {
    "action": 28, "adventure": 12, "animation": 16, "comedy": 35,
    "crime": 80, "documentary": 99, "drama": 18, "family": 10751,
    "fantasy": 14, "history": 36, "horror": 27, "music": 10402,
    "mystery": 9648, "romance": 10749, "science fiction": 878,
    "sci-fi": 878, "sci fi": 878, "thriller": 53, "war": 10752, "western": 37,
    "romantic": 10749, "romantic comedy": 10749, "rom-com": 10749,
    "romcom": 10749, "rom com": 10749, "feel-good": 35,
    "superhero": 28, "martial arts": 28, "suspense": 53, "spy": 53,
}

LANGUAGE_NAME_TO_CODE: dict = {
    # English names
    "english": "en", "hindi": "hi", "telugu": "te", "tamil": "ta",
    "kannada": "kn", "malayalam": "ml", "bengali": "bn", "marathi": "mr",
    "punjabi": "pa", "french": "fr", "spanish": "es", "german": "de",
    "japanese": "ja", "korean": "ko", "chinese": "zh", "italian": "it",
    "portuguese": "pt", "russian": "ru", "arabic": "ar", "turkish": "tr",
    # Native script names (fallback if AI returns in native language)
    "తెలుగు": "te", "हिंदी": "hi", "தமிழ்": "ta", "മലയാളം": "ml",
    "ಕನ್ನಡ": "kn", "বাংলা": "bn", "मराठी": "mr", "ਪੰਜਾਬੀ": "pa",
    "français": "fr", "español": "es", "deutsch": "de", "日本語": "ja",
    "한국어": "ko", "中文": "zh", "italiano": "it", "português": "pt",
    "русский": "ru", "عربي": "ar", "türkçe": "tr",
}

# Languages whose films are commonly dubbed into the key language
DUBBED_SOURCE_LANGS: dict = {
    "te": ["ta", "hi", "ml", "kn"],
    "ta": ["te", "hi", "ml"],
    "hi": ["en", "te", "ta"],
    "ml": ["ta", "te", "hi"],
    "kn": ["te", "ta", "hi"],
    "en": ["hi", "fr", "es", "de", "ja", "ko"],
}

MOOD_TO_GENRES: dict = {
    "feel-good":         [35, 10749, 10751],
    "happy":             [35, 10751, 16],
    "sad":               [18, 10749],
    "scary":             [27, 9648],
    "thrilling":         [28, 53, 80],
    "romantic":          [10749, 35],
    "inspiring":         [18, 36, 99],
    "funny":             [35, 16],
    "dark":              [53, 80, 27],
    "epic":              [28, 12, 14, 878],
    "relaxing":          [10751, 99, 10402],
    "thought-provoking": [18, 878, 36],
}

SORT_OPTIONS: dict = {
    "recent":  "primary_release_date.desc",
    "popular": "popularity.desc",
    "rated":   "vote_average.desc",
    "oldest":  "primary_release_date.asc",
    "revenue": "revenue.desc",
}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class Movie(BaseModel):
    id: int
    title: str
    overview: str
    release_year: Optional[int]
    release_date: Optional[str]
    genres: list
    language: str
    rating: float
    vote_count: int
    poster_url: Optional[str]
    popularity: float


class RecommendResponse(BaseModel):
    query: str
    filters: dict
    sort: str
    page: int
    total_pages: int
    total_results: int
    movies: list


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

async def _get_redis():
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        await client.ping()
        return client
    except Exception as exc:
        logger.debug("[cache] Redis unavailable: %s", exc)
        return None


def _cache_key(query: str, sort: str, page: int) -> str:
    raw = f"{query.strip().lower()}|{sort}|{page}"
    return "recommend:" + hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# TMDB helpers
# ---------------------------------------------------------------------------

async def _tmdb_get(path: str, params: dict) -> dict:
    if not TMDB_API_KEY:
        raise HTTPException(status_code=503, detail="TMDB_API_KEY is not configured.")
    params["api_key"] = TMDB_API_KEY
    url = f"{TMDB_BASE}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
    if resp.status_code != 200:
        logger.warning("[TMDB] %s → HTTP %s: %s", url, resp.status_code, resp.text[:400])
        raise HTTPException(status_code=502, detail=f"TMDB error {resp.status_code}")
    return resp.json()


async def _fetch_genre_map() -> dict:
    try:
        data = await _tmdb_get("/genre/movie/list", {"language": "en-US"})
        return {g["id"]: g["name"] for g in data.get("genres", [])}
    except Exception:
        return {}


def _explicit_genre_ids(filters: dict) -> list:
    ids: set = set()
    for g in filters.get("genres", []):
        gid = GENRE_NAME_TO_ID.get(g.lower())
        if gid:
            ids.add(gid)
    return list(ids)


def _mood_genre_ids(filters: dict) -> list:
    mood = (filters.get("mood") or "").lower()
    return list(MOOD_TO_GENRES.get(mood, []))


def _language_code(filters: dict) -> Optional[str]:
    for lang in filters.get("languages", []):
        code = LANGUAGE_NAME_TO_CODE.get(lang.lower())
        if code:
            return code
    return None


def _build_genre_param(genre_ids: list, use_and: bool = False) -> str:
    sep = "," if use_and else "|"
    return sep.join(str(i) for i in genre_ids)


async def _fetch_person_id(name: str) -> Optional[int]:
    try:
        data = await _tmdb_get("/search/person", {"query": name})
        results = data.get("results", [])
        return results[0]["id"] if results else None
    except Exception:
        return None


async def _resolve_reference_movie(title: str) -> tuple:
    """
    Search TMDB for the reference film.
    Returns (genre_ids, original_language).
    Language from the reference is returned raw — the caller decides whether
    to use it or override with the user's explicit language preference.
    """
    try:
        data = await _tmdb_get("/search/movie", {"query": title, "language": "en-US"})
        results = data.get("results", [])
        if not results:
            logger.warning("[resolve_ref] No TMDB results for %r", title)
            return [], None
        ref = results[0]
        ref_genre_ids = ref.get("genre_ids", [])
        ref_lang      = ref.get("original_language", "")
        logger.info("[resolve_ref] %r → genres=%s lang=%s", title, ref_genre_ids, ref_lang)
        return ref_genre_ids, ref_lang
    except Exception as exc:
        logger.warning("[resolve_ref] Failed for %r: %s", title, exc)
        return [], None


async def _fetch_with_language(base_params: dict, user_lang: str) -> dict:
    """
    Execute TWO TMDB discover calls for a given language and merge results:
      Call 1 — original language = user_lang (e.g. Telugu originals)
      Call 2 — source languages commonly dubbed into user_lang
               (e.g. Tamil/Hindi/Malayalam for Telugu)

    This ensures "movies like Dhurandhar in Telugu" returns:
      - Telugu-original action/thriller/crime films
      - Tamil/Hindi action/thriller/crime films that are dubbed in Telugu

    Results are deduplicated by movie id, then re-sorted.
    """
    # Call 1: originals in user language
    params1  = {**base_params, "with_original_language": user_lang}
    data1    = await _tmdb_get("/discover/movie", params1)
    results1 = data1.get("results", [])

    # Call 2: dubbed source languages
    source_langs = DUBBED_SOURCE_LANGS.get(user_lang, [])
    results2: list = []
    data2: dict = {}
    if source_langs:
        params2  = {**base_params, "with_original_language": "|".join(source_langs)}
        data2    = await _tmdb_get("/discover/movie", params2)
        results2 = data2.get("results", [])

    # Merge — originals come first, then dubbed sources, dedup by id
    seen: set = set()
    merged: list = []
    for m in results1 + results2:
        if m["id"] not in seen:
            seen.add(m["id"])
            merged.append(m)

    # Re-sort merged list by the same field TMDB used
    sort_key = base_params.get("sort_by", "popularity.desc")
    field, direction = sort_key.rsplit(".", 1)
    field_map = {
        "primary_release_date": "release_date",
        "popularity":           "popularity",
        "vote_average":         "vote_average",
        "revenue":              "revenue",
    }
    sort_field = field_map.get(field, "popularity")
    reverse    = direction == "desc"
    merged.sort(key=lambda m: m.get(sort_field) or "", reverse=reverse)

    total1 = data1.get("total_results", 0)
    total2 = data2.get("total_results", 0) if data2 else 0
    pages1 = data1.get("total_pages", 1)
    pages2 = data2.get("total_pages", 1) if data2 else 1

    return {
        "results":       merged[:20],
        "total_results": total1 + total2,
        "total_pages":   max(pages1, pages2),
    }


async def _apply_cast_director_filter(filters: dict, params: dict) -> dict:
    people_ids: list = []
    for actor in filters.get("cast", []):
        pid = await _fetch_person_id(actor)
        if pid:
            people_ids.append(pid)
    if "director" in filters:
        pid = await _fetch_person_id(filters["director"])
        if pid:
            params["with_crew"] = str(pid)
    if people_ids:
        params["with_cast"] = ",".join(str(i) for i in people_ids)
    return params


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def _format_movie(raw: dict, genre_map: dict) -> Movie:
    genre_names  = [genre_map[gid] for gid in raw.get("genre_ids", []) if gid in genre_map]
    release_date = raw.get("release_date") or ""
    year_raw     = release_date[:4]
    year         = int(year_raw) if year_raw.isdigit() else None
    poster       = raw.get("poster_path")
    return Movie(
        id           = raw["id"],
        title        = raw.get("title", "Unknown"),
        overview     = raw.get("overview", ""),
        release_year = year,
        release_date = release_date or None,
        genres       = genre_names,
        language     = raw.get("original_language", ""),
        rating       = round(raw.get("vote_average", 0.0), 1),
        vote_count   = raw.get("vote_count", 0),
        poster_url   = f"{TMDB_IMAGE_BASE}{poster}" if poster else None,
        popularity   = round(raw.get("popularity", 0.0), 2),
    )


# ---------------------------------------------------------------------------
# Main route
# ---------------------------------------------------------------------------

@router.get("/recommend", response_model=RecommendResponse)
async def recommend(
    q:    str = Query(default="popular movies", description="Free-text movie query"),
    page: int = Query(default=1, ge=1, le=500),
    sort: str = Query(default="recent", description="recent|popular|rated|oldest|revenue"),
):
    sort_by = SORT_OPTIONS.get(sort, SORT_OPTIONS["recent"])

    # 1. Redis cache
    redis     = await _get_redis()
    cache_key = _cache_key(q, sort, page)
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                logger.info("[recommend] Cache HIT %s", cache_key)
                return RecommendResponse(**json.loads(cached))
        except Exception as exc:
            logger.warning("[recommend] Cache read: %s", exc)

    # 2. AI parse
    logger.info("[recommend] Parsing: %r", q)
    filters = await parse_query(q)
    logger.info("[recommend] Filters: %s", filters)

    genre_map = await _fetch_genre_map()

    try:
        # Base TMDB params — language is NOT set here, handled separately below
        params: dict[str, Any] = {
            "page":            page,
            "sort_by":         sort_by,
            "include_adult":   "false",
            "include_video":   "false",
            "vote_count.gte":  5,
            "with_release_type": "1|2|3|4|5|6",
        }

        # No future movies
        today = date.today().isoformat()
        if "era_end" not in filters:
            params["primary_release_date.lte"] = today

        # Era
        if "era_start" in filters:
            params["primary_release_date.gte"] = f"{filters['era_start']}-01-01"
        if "era_end" in filters:
            params["primary_release_date.lte"] = f"{filters['era_end']}-12-31"

        # Min rating
        if "min_rating" in filters:
            params["vote_average.gte"] = filters["min_rating"]
            params["vote_count.gte"]   = 50

        # Cast / Director
        if filters.get("cast") or filters.get("director"):
            params = await _apply_cast_director_filter(filters, params)

        # ── Direct movie title search ─────────────────────────────────────
        # When user types a movie title (e.g. "Hari Hara Veera Mallu"),
        # search TMDB for exact match, pin it at top, then show similar movies below
        direct_search = filters.get("direct_search")
        exact_movie: Optional[dict] = None

        if direct_search:
            try:
                search_data    = await _tmdb_get("/search/movie", {
                    "query": direct_search, "language": "en-US", "page": 1,
                })
                search_results = search_data.get("results", [])
                if search_results:
                    exact_movie    = search_results[0]
                    ref_genre_ids  = exact_movie.get("genre_ids", [])
                    if ref_genre_ids:
                        params["with_genres"] = _build_genre_param(ref_genre_ids, use_and=False)
                    logger.info("[recommend] Direct match: %s (id=%s)",
                                exact_movie.get("title"), exact_movie.get("id"))
            except Exception as exc:
                logger.warning("[recommend] Direct search error: %s", exc)

        # ── Genres (non-direct searches) ───────────────────────────────
        if not direct_search:
            explicit_ids = _explicit_genre_ids(filters)
            mood_ids     = _mood_genre_ids(filters)
            if "similar_to" in filters:
                ref_genre_ids, _ref_lang = await _resolve_reference_movie(filters["similar_to"])
                if explicit_ids:
                    params["with_genres"] = _build_genre_param(explicit_ids, use_and=False)
                elif ref_genre_ids:
                    params["with_genres"] = _build_genre_param(ref_genre_ids, use_and=False)
            else:
                if explicit_ids:
                    params["with_genres"] = _build_genre_param(explicit_ids, use_and=False)
                elif mood_ids:
                    params["with_genres"] = _build_genre_param(mood_ids, use_and=False)

        # ── Language (always last, always wins) ───────────────────────────
        explicit_lang    = _language_code(filters)
        dubbed_requested = filters.get("dubbed", False)

        logger.info("[recommend] Final TMDB params (pre-lang): %s", params)

        if explicit_lang:
            tmdb_data = await _fetch_with_language(params, explicit_lang)
        elif dubbed_requested:
            tmdb_data = await _fetch_with_language(params, "te")
        else:
            tmdb_data = await _tmdb_get("/discover/movie", params)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[recommend] TMDB fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to fetch movies from TMDB.")

    # 4. Format
    raw_results   = tmdb_data.get("results", [])
    total_results = tmdb_data.get("total_results", len(raw_results))
    total_pages   = tmdb_data.get("total_pages", 1)

    # Pin exact movie at top, remove it from discover results to avoid duplicate
    if exact_movie:
        exact_id  = exact_movie["id"]
        raw_results = [r for r in raw_results if r["id"] != exact_id]
        raw_results = [exact_movie] + raw_results  # exact match first!

    movies = [_format_movie(r, genre_map) for r in raw_results]

    # Local post-filter (belt-and-suspenders)
    min_rating = filters.get("min_rating")
    era_start  = filters.get("era_start")
    era_end    = filters.get("era_end")
    if min_rating or era_start or era_end:
        movies = [
            m for m in movies
            if (not min_rating or m.rating >= min_rating)
            and (not era_start or not m.release_year or m.release_year >= era_start)
            and (not era_end   or not m.release_year or m.release_year <= era_end)
        ]

    response = RecommendResponse(
        query=q, filters=filters, sort=sort, page=page,
        total_pages=total_pages, total_results=total_results, movies=movies,
    )

    if redis:
        try:
            await redis.set(cache_key, json.dumps(response.model_dump()), ex=CACHE_TTL)
        except Exception as exc:
            logger.warning("[recommend] Cache write: %s", exc)

    return response

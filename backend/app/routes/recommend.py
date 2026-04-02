"""
app/routes/recommend.py
GET /recommend?q=<query>&page=<page>&sort=<sort>

Search Algorithm (3 modes):

MODE 1 — TITLE SEARCH (e.g. "Kushi", "Hari Hara Veera Mallu")
  Step 1: /search/movie?query=title → get ALL matching movies across languages
  Step 2: /discover/movie?with_text_query=title&with_original_language=lang → language-filtered
  Step 3: Score each result: exact title match > partial match > others
  Step 4: Merge both lists, deduplicate, sort by score then by release_date desc
  Result: Exact Telugu Kushi (2023) first, then 2001 Kushi, then similar movies

MODE 2 — SIMILAR MOVIES (e.g. "movies like RRR", "like Dhurandhar in Telugu")
  Step 1: Look up reference movie on TMDB → get genre_ids
  Step 2: /discover with those genre_ids + language filter (dual fetch for dubbed)
  Result: Movies with matching genres in target language

MODE 3 — DESCRIPTIVE (e.g. "feel-good romantic comedies", "90s horror")
  Step 1: Extract genre/language/mood/era from AI
  Step 2: /discover with all filters
  Result: Genre/mood/era filtered movies
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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
    # Native script names
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
# Core Search Algorithm
# ---------------------------------------------------------------------------

def _title_match_score(title: str, query: str) -> float:
    """
    Score how well a movie title matches the search query.
    Returns 0.0 to 1.0 — higher is better match.
    """
    title_clean = title.lower().strip()
    query_clean = query.lower().strip()

    # Exact match
    if title_clean == query_clean:
        return 1.0

    # Title starts with query
    if title_clean.startswith(query_clean):
        return 0.95

    # Query is contained in title
    if query_clean in title_clean:
        return 0.85

    # Word-level overlap score
    title_words = set(re.split(r'\W+', title_clean))
    query_words = set(re.split(r'\W+', query_clean))
    query_words.discard('')
    title_words.discard('')

    if not query_words:
        return 0.0

    overlap = len(title_words & query_words) / len(query_words)
    return overlap * 0.7


async def _title_search(
    title: str,
    lang_code: Optional[str],
    page: int,
    genre_map: dict,
) -> dict:
    """
    MODE 1: Title-based search.

    Strategy:
    1. /search/movie — text search across ALL languages (finds every version)
    2. /discover with with_text_query + language filter (language-specific)
    3. Merge, score by title match + language preference + recency
    4. Return sorted results with best matches first, all years included

    This ensures "Kushi" returns BOTH the 2023 Telugu AND the 2001 Telugu versions.
    """
    results_map: dict = {}   # id → raw movie dict
    scored: dict = {}        # id → score

    # ── Step 1: Broad text search (all languages, all years) ──────────────
    try:
        search_data = await _tmdb_get("/search/movie", {
            "query":         title,
            "language":      "en-US",
            "page":          page,
            "include_adult": "false",
        })
        for m in search_data.get("results", []):
            mid = m["id"]
            results_map[mid] = m
            score = _title_match_score(m.get("title", ""), title)
            # Boost if original language matches user's preferred language
            if lang_code and m.get("original_language") == lang_code:
                score += 0.3
            # Small recency boost (newer = slightly higher)
            year_str = (m.get("release_date") or "")[:4]
            if year_str.isdigit():
                year_boost = min((int(year_str) - 1990) / 100, 0.1)
                score += year_boost
            scored[mid] = score

        total_results = search_data.get("total_results", 0)
        total_pages   = search_data.get("total_pages", 1)

    except Exception as exc:
        logger.warning("[title_search] Search call failed: %s", exc)
        total_results = 0
        total_pages   = 1

    # ── Step 2: Discover with text query + language filter ────────────────
    # This finds language-specific results that /search might rank poorly
    if lang_code:
        try:
            discover_data = await _tmdb_get("/discover/movie", {
                "with_text_query":        title,
                "with_original_language": lang_code,
                "sort_by":                "primary_release_date.desc",
                "include_adult":          "false",
                "with_release_type":      "1|2|3|4|5|6",
                "page":                   1,
            })
            for m in discover_data.get("results", []):
                mid = m["id"]
                if mid not in results_map:
                    results_map[mid] = m
                    total_results += 1
                # Boost language-matched discover results highly
                base_score = _title_match_score(m.get("title", ""), title)
                scored[mid] = max(scored.get(mid, 0), base_score + 0.4)

        except Exception as exc:
            logger.warning("[title_search] Discover+text call failed: %s", exc)

    # ── Step 3: Sort by score descending ─────────────────────────────────
    sorted_ids = sorted(results_map.keys(), key=lambda i: scored.get(i, 0), reverse=True)
    sorted_results = [results_map[i] for i in sorted_ids]

    return {
        "results":       sorted_results,
        "total_results": total_results,
        "total_pages":   total_pages,
    }


async def _similar_movie_search(
    reference_title: str,
    filters: dict,
    params: dict,
    lang_code: Optional[str],
) -> dict:
    """
    MODE 2: Find movies similar to a reference title.

    Strategy:
    1. Search TMDB for the reference movie to get its genre_ids
    2. Also use TMDB's /movie/{id}/recommendations endpoint if available
    3. Combine with /discover using genre filter
    4. Apply language filter with dubbed sources
    """
    try:
        search_data = await _tmdb_get("/search/movie", {
            "query":    reference_title,
            "language": "en-US",
            "page":     1,
        })
        results = search_data.get("results", [])
        if not results:
            return await _tmdb_get("/discover/movie", params)

        ref           = results[0]
        ref_id        = ref["id"]
        ref_genre_ids = ref.get("genre_ids", [])
        ref_lang      = ref.get("original_language", "")

        logger.info("[similar] Reference: %s (id=%s, genres=%s, lang=%s)",
                    ref.get("title"), ref_id, ref_genre_ids, ref_lang)

        # Use reference genres in discover
        if ref_genre_ids:
            params["with_genres"] = _build_genre_param(ref_genre_ids, use_and=False)

        # Language: explicit user preference wins over reference language
        final_lang = lang_code if lang_code else ref_lang
        if final_lang:
            params["with_original_language"] = final_lang

        # Override with explicit user genres if provided
        explicit_ids = _explicit_genre_ids(filters)
        if explicit_ids:
            params["with_genres"] = _build_genre_param(explicit_ids, use_and=False)

    except Exception as exc:
        logger.warning("[similar] Reference lookup failed: %s", exc)

    return await _discover_with_language(params, lang_code)


async def _discover_with_language(params: dict, lang_code: Optional[str]) -> dict:
    """
    Run discover call(s).
    If lang_code given: TWO calls (originals + dubbed sources) merged.
    If no lang_code: single call.
    """
    if not lang_code:
        return await _tmdb_get("/discover/movie", params)

    # Call 1: originals in target language
    params1  = {**params, "with_original_language": lang_code}
    data1    = await _tmdb_get("/discover/movie", params1)
    results1 = data1.get("results", [])

    # Call 2: dubbed source languages
    source_langs = DUBBED_SOURCE_LANGS.get(lang_code, [])
    results2: list = []
    data2: dict    = {}
    if source_langs:
        try:
            params2  = {**params, "with_original_language": "|".join(source_langs)}
            data2    = await _tmdb_get("/discover/movie", params2)
            results2 = data2.get("results", [])
        except Exception as exc:
            logger.warning("[discover_lang] Dubbed call failed: %s", exc)

    # Merge: originals first, then dubbed, dedup by id
    seen:   set  = set()
    merged: list = []
    for m in results1 + results2:
        if m["id"] not in seen:
            seen.add(m["id"])
            merged.append(m)

    # Re-sort by same field as params sort_by
    sort_key   = params.get("sort_by", "primary_release_date.desc")
    field, dir = sort_key.rsplit(".", 1)
    field_map  = {
        "primary_release_date": "release_date",
        "popularity":           "popularity",
        "vote_average":         "vote_average",
        "revenue":              "revenue",
    }
    sort_field = field_map.get(field, "popularity")
    merged.sort(key=lambda m: m.get(sort_field) or "", reverse=(dir == "desc"))

    total1 = data1.get("total_results", 0)
    total2 = data2.get("total_results", 0) if data2 else 0
    pages1 = data1.get("total_pages", 1)
    pages2 = data2.get("total_pages", 1) if data2 else 1

    return {
        "results":       merged[:20],
        "total_results": total1 + total2,
        "total_pages":   max(pages1, pages2),
    }


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
    q:    str = Query(default="popular movies"),
    page: int = Query(default=1, ge=1, le=500),
    sort: str = Query(default="recent"),
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

    # Determine explicit language from filters
    explicit_lang    = _language_code(filters)
    dubbed_requested = filters.get("dubbed", False)
    lang_code        = explicit_lang or ("te" if dubbed_requested else None)

    # Base discover params (used in MODE 2 and 3)
    today = date.today().isoformat()
    base_params: dict[str, Any] = {
        "page":              page,
        "sort_by":           sort_by,
        "include_adult":     "false",
        "include_video":     "false",
        "vote_count.gte":    5,
        "with_release_type": "1|2|3|4|5|6",
    }
    if "era_end" not in filters:
        base_params["primary_release_date.lte"] = today
    if "era_start" in filters:
        base_params["primary_release_date.gte"] = f"{filters['era_start']}-01-01"
    if "era_end" in filters:
        base_params["primary_release_date.lte"] = f"{filters['era_end']}-12-31"
    if "min_rating" in filters:
        base_params["vote_average.gte"] = filters["min_rating"]
        base_params["vote_count.gte"]   = 50
    if filters.get("cast") or filters.get("director"):
        base_params = await _apply_cast_director_filter(filters, base_params)

    try:
        direct_search = filters.get("direct_search", "")
        similar_to    = filters.get("similar_to", "")

        # ── MODE 1: Direct title search ───────────────────────────────────
        if direct_search:
            logger.info("[recommend] MODE 1 — Title search: %r lang=%s", direct_search, lang_code)
            tmdb_data = await _title_search(direct_search, lang_code, page, genre_map)

        # ── MODE 2: Similar movies ────────────────────────────────────────
        elif similar_to:
            logger.info("[recommend] MODE 2 — Similar to: %r lang=%s", similar_to, lang_code)
            tmdb_data = await _similar_movie_search(
                similar_to, filters, base_params.copy(), lang_code
            )

        # ── MODE 3: Descriptive / genre / mood search ─────────────────────
        else:
            logger.info("[recommend] MODE 3 — Descriptive search, lang=%s", lang_code)
            explicit_ids = _explicit_genre_ids(filters)
            mood_ids     = _mood_genre_ids(filters)
            if explicit_ids:
                base_params["with_genres"] = _build_genre_param(explicit_ids, use_and=False)
            elif mood_ids:
                base_params["with_genres"] = _build_genre_param(mood_ids, use_and=False)

            tmdb_data = await _discover_with_language(base_params, lang_code)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[recommend] Failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to fetch movies from TMDB.")

    # 4. Format results — NO local language filtering (TMDB handles it)
    raw_results   = tmdb_data.get("results", [])
    total_results = tmdb_data.get("total_results", len(raw_results))
    total_pages   = tmdb_data.get("total_pages", 1)
    movies        = [_format_movie(r, genre_map) for r in raw_results]

    # Local post-filter for rating/era only
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

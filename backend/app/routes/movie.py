"""
app/routes/movie.py

GET /movie/{movie_id}  — full movie details + YouTube trailer from TMDB
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

TMDB_BASE       = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_BACKDROP   = "https://image.tmdb.org/t/p/w1280"
TMDB_API_KEY    = os.getenv("TMDB_API_KEY", "")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CastMember(BaseModel):
    name: str
    character: str
    profile_url: Optional[str]

class MovieDetail(BaseModel):
    id: int
    title: str
    tagline: Optional[str]
    overview: str
    release_date: Optional[str]
    release_year: Optional[int]
    runtime: Optional[int]          # minutes
    genres: list
    language: str
    spoken_languages: list
    rating: float
    vote_count: int
    popularity: float
    poster_url: Optional[str]
    backdrop_url: Optional[str]
    trailer_key: Optional[str]      # YouTube video key
    cast: list                      # top 10 cast members
    director: Optional[str]
    budget: Optional[int]
    revenue: Optional[int]
    status: Optional[str]
    homepage: Optional[str]
    tmdb_url: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _tmdb_get(path: str, params: dict) -> dict:
    if not TMDB_API_KEY:
        raise HTTPException(status_code=503, detail="TMDB_API_KEY is not configured.")
    params["api_key"] = TMDB_API_KEY
    url = f"{TMDB_BASE}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Movie not found.")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"TMDB error {resp.status_code}")
    return resp.json()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/movie/{movie_id}", response_model=MovieDetail)
async def get_movie(movie_id: int):
    """
    Fetch full movie details + trailer + cast for a given TMDB movie ID.
    Uses append_to_response to get videos + credits in one API call.
    """
    data = await _tmdb_get(
        f"/movie/{movie_id}",
        {"append_to_response": "videos,credits", "language": "en-US"},
    )

    # ── Trailer ──────────────────────────────────────────────────────────────
    # Find the first official YouTube trailer; fall back to any YouTube video
    videos = data.get("videos", {}).get("results", [])
    trailer_key = None
    for v in videos:
        if v.get("site") == "YouTube" and v.get("type") == "Trailer" and v.get("official"):
            trailer_key = v["key"]
            break
    if not trailer_key:
        for v in videos:
            if v.get("site") == "YouTube" and v.get("type") == "Trailer":
                trailer_key = v["key"]
                break
    if not trailer_key:
        for v in videos:
            if v.get("site") == "YouTube":
                trailer_key = v["key"]
                break

    # ── Cast (top 10) ─────────────────────────────────────────────────────────
    credits = data.get("credits", {})
    cast_raw = credits.get("cast", [])[:10]
    cast = [
        CastMember(
            name=m.get("name", ""),
            character=m.get("character", ""),
            profile_url=(
                f"{TMDB_IMAGE_BASE}{m['profile_path']}"
                if m.get("profile_path") else None
            ),
        )
        for m in cast_raw
    ]

    # ── Director ──────────────────────────────────────────────────────────────
    crew = credits.get("crew", [])
    director = next(
        (m["name"] for m in crew if m.get("job") == "Director"), None
    )

    # ── Basics ────────────────────────────────────────────────────────────────
    genres       = [g["name"] for g in data.get("genres", [])]
    spoken_langs = [l.get("english_name", "") for l in data.get("spoken_languages", [])]
    release_date = data.get("release_date") or ""
    year_raw     = release_date[:4]
    year         = int(year_raw) if year_raw.isdigit() else None
    poster       = data.get("poster_path")
    backdrop     = data.get("backdrop_path")

    return MovieDetail(
        id              = data["id"],
        title           = data.get("title", "Unknown"),
        tagline         = data.get("tagline") or None,
        overview        = data.get("overview", ""),
        release_date    = release_date or None,
        release_year    = year,
        runtime         = data.get("runtime") or None,
        genres          = genres,
        language        = data.get("original_language", ""),
        spoken_languages= spoken_langs,
        rating          = round(data.get("vote_average", 0.0), 1),
        vote_count      = data.get("vote_count", 0),
        popularity      = round(data.get("popularity", 0.0), 2),
        poster_url      = f"{TMDB_IMAGE_BASE}{poster}" if poster else None,
        backdrop_url    = f"{TMDB_BACKDROP}{backdrop}" if backdrop else None,
        trailer_key     = trailer_key,
        cast            = [c.model_dump() for c in cast],
        director        = director,
        budget          = data.get("budget") or None,
        revenue         = data.get("revenue") or None,
        status          = data.get("status") or None,
        homepage        = data.get("homepage") or None,
        tmdb_url        = f"https://www.themoviedb.org/movie/{data['id']}",
    )

import logging
import os

# Must be first — loads .env so all os.getenv() calls in other modules work
from app.core import config  # noqa: F401

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import recommend, movie

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)

app = FastAPI(
    title="Movie Recommender API",
    description="AI-powered movie recommendations using TMDB",
    version="0.1.0",
)

# CORS — allow all origins (no credentials needed for this public API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(recommend.router, tags=["recommendations"])
app.include_router(movie.router, tags=["movies"])


@app.get("/health")
async def health():
    return {"status": "ok"}

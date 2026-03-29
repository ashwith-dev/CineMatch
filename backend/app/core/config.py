from dotenv import load_dotenv
import os
from pathlib import Path

# Load .env if it exists (local dev only — on Render, env vars are set in dashboard)
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# All values fall back to "" if not set — no errors thrown
DATABASE_URL       = os.getenv("DATABASE_URL", "")
TMDB_API_KEY       = os.getenv("TMDB_API_KEY", "")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
REDIS_URL          = os.getenv("REDIS_URL", "redis://localhost:6379")

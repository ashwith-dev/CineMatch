from dotenv import load_dotenv
import os
from pathlib import Path

# Load .env from backend folder — must happen before any os.getenv() calls
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv("DATABASE_URL", "")  # Optional — only needed for user auth features

# Expose all other keys so importing this module triggers .env load
TMDB_API_KEY    = os.getenv("TMDB_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
REDIS_URL       = os.getenv("REDIS_URL", "redis://localhost:6379")

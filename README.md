# 🎬 CineMatch — AI-Powered Movie Recommender

![CineMatch Logo](frontend/public/logo.png)

> Describe any movie you're in the mood for — in any language — and CineMatch finds the perfect match using AI.

**Live Site:** [cinematch-one-pi.vercel.app](https://cinematch-one-pi.vercel.app)

---

## 📌 What is CineMatch?

CineMatch is an AI-powered movie recommendation website that understands natural language queries in any language. Instead of browsing through categories, just describe what you want:

- *"Telugu action movies like RRR"*
- *"Feel-good romantic comedies from 2020s"*
- *"Christopher Nolan sci-fi films"*
- *"90s horror with good ratings"*
- *"Movies like Dhurandhar in Telugu"*

CineMatch parses your query using AI, extracts filters (genre, language, mood, era, rating), fetches matching movies from TMDB, and returns results with posters, trailers, ratings, and cast info.

---

## ✨ Features

- 🔍 **Natural language search** — search in English, Telugu, Hindi, or any language
- 🤖 **AI query parsing** — extracts genres, language, mood, era, rating from your text
- 🎬 **Movie detail modal** — click any movie to see full info + YouTube trailer
- 🎛️ **Smart filters** — genres, language, year range, min rating (auto-filled from AI)
- 🌍 **Dubbed movie support** — shows Telugu originals + dubbed Tamil/Hindi films
- 📄 **Pagination** — browse all results page by page
- 🔄 **Sort options** — recent, popular, highest rated, top grossing, oldest
- 🎨 **Dark navy theme** — cinematic high-tech UI with cyan accents
- ⚡ **Redis caching** — fast repeated searches

---

## 🛠️ Tech Stack

### Backend
| Technology | Purpose |
|---|---|
| **FastAPI** | Python web framework for the REST API |
| **Uvicorn** | ASGI server to run FastAPI |
| **Groq API** | AI query parsing (llama-3.3-70b-versatile) — fastest LLM |
| **Gemini 2.5 Flash** | Fallback AI provider |
| **OpenRouter** | Second fallback AI provider |
| **TMDB API** | Movie database — posters, trailers, cast, ratings |
| **SQLAlchemy** | ORM for PostgreSQL |
| **Redis** | Caching search results (30 min TTL) |
| **httpx** | Async HTTP client for TMDB calls |
| **python-dotenv** | Environment variable management |

### Frontend
| Technology | Purpose |
|---|---|
| **Next.js 14** | React framework with App Router |
| **TypeScript** | Type-safe frontend code |
| **Tailwind CSS** | Utility-first styling |
| **next/image** | Optimised movie poster images |

### Deployment
| Service | Purpose |
|---|---|
| **Vercel** | Frontend hosting (free) |
| **Render** | Backend hosting (free tier) |

---

## 🔑 APIs Used

| API | What it does | Get Key |
|---|---|---|
| **TMDB** | Movie data, posters, trailers, cast | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) |
| **Groq** | AI query parsing (primary) | [console.groq.com](https://console.groq.com/keys) |
| **Gemini** | AI fallback #1 | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| **OpenRouter** | AI fallback #2 | [openrouter.ai/keys](https://openrouter.ai/keys) |

---

## 📁 Project Structure

```
movie-recommender/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + CORS
│   │   ├── database.py          # SQLAlchemy engine setup
│   │   ├── models.py            # DB models (User, Preferences, WatchHistory)
│   │   ├── schemas.py           # Pydantic schemas
│   │   ├── create_tables.py     # Script to create DB tables
│   │   ├── core/
│   │   │   ├── config.py        # Loads .env, exposes all keys
│   │   │   ├── ai_client.py     # call_ai() — Groq → Gemini → OpenRouter fallback
│   │   │   └── parse_query.py   # parse_query() — AI extracts filters from text
│   │   └── routes/
│   │       ├── recommend.py     # GET /recommend — main search endpoint
│   │       └── movie.py         # GET /movie/{id} — full movie details + trailer
│   ├── requirements.txt
│   ├── runtime.txt              # Python 3.11.0
│   └── .env                    # Local env vars (not committed)
├── frontend/
│   ├── app/
│   │   ├── layout.tsx           # Root layout + metadata
│   │   └── page.tsx             # Main page — search, filters, movie grid, modal
│   ├── public/
│   │   └── logo.png             # CineMatch logo
│   ├── styles/
│   │   └── globals.css          # Global CSS + theme variables
│   ├── next.config.js           # Next.js config (TMDB image domain)
│   └── package.json
├── render.yaml                  # Render deployment config
├── docker-compose.yml
└── README.md
```

---

## 🚀 Running Locally

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL (optional — only needed for user features)
- Redis (optional — caching works without it)

### 1. Clone the repo

```bash
git clone https://github.com/ashwith-dev/CineMatch.git
cd CineMatch
```

### 2. Backend setup

```bash
cd backend

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env             # or create manually
```

Edit `backend/.env`:

```env
TMDB_API_KEY=your_tmdb_key_here
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=                  # optional
OPENROUTER_API_KEY=              # optional
DATABASE_URL=postgresql://app_user:password@localhost:5432/movies
REDIS_URL=redis://localhost:6379
```

```bash
# Start the backend server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend runs at: **http://localhost:8000**
Swagger docs at: **http://localhost:8000/docs**

### 3. Frontend setup

```bash
cd frontend

# Install dependencies
npm install

# Create .env.local
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Start the dev server
npm run dev
```

Frontend runs at: **http://localhost:3000**

### 4. PostgreSQL setup (optional)

Run these in psql or pgAdmin:

```sql
CREATE DATABASE movies;
CREATE USER app_user WITH PASSWORD 'password';
GRANT ALL PRIVILEGES ON DATABASE movies TO app_user;
GRANT ALL ON SCHEMA public TO app_user;
ALTER SCHEMA public OWNER TO app_user;
```

Then create tables:

```bash
cd backend
source .venv/bin/activate
python -m app.create_tables
```

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/recommend?q=...&sort=...&page=...` | Get movie recommendations |
| `GET` | `/movie/{id}` | Full movie details + trailer + cast |

### `/recommend` query params

| Param | Default | Options |
|---|---|---|
| `q` | `popular movies` | Any natural language query |
| `sort` | `recent` | `recent`, `popular`, `rated`, `oldest`, `revenue` |
| `page` | `1` | 1–500 |

### Example requests

```bash
# Telugu action movies like RRR
curl "http://localhost:8000/recommend?q=Telugu+action+movies+like+RRR"

# 90s horror with good ratings
curl "http://localhost:8000/recommend?q=90s+horror+with+good+ratings&sort=rated"

# Movie detail with trailer
curl "http://localhost:8000/movie/99861"
```

---

## 🤖 How the AI Query Parsing Works

```
User types: "Telugu action movies like RRR"
                    │
                    ▼
          parse_query() calls Groq AI
                    │
                    ▼
        AI returns structured JSON:
        {
          "genres": ["action"],
          "languages": ["Telugu"],
          "similar_to": "RRR"
        }
                    │
                    ▼
    _resolve_reference_movie("RRR")
    → fetches RRR from TMDB
    → extracts genre_ids: [28, 12, 18]
                    │
                    ▼
    TWO TMDB calls (for dubbed support):
    Call 1: Telugu originals + genre filter
    Call 2: Tamil/Hindi/Malayalam + genre filter
    (commonly dubbed into Telugu)
                    │
                    ▼
    Merge + deduplicate + sort → results
```

### AI Fallback Chain

```
Groq (fastest) → Gemini → OpenRouter → empty {}
```

If Groq API key is set, it's always used. Others activate automatically when their key is added to `.env`.

---

## 🚢 Deployment

### Backend → Render (free)

1. Push code to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Set:
   - **Root Directory:** *(leave empty)*
   - **Build Command:** `cd backend && pip install -r requirements.txt`
   - **Start Command:** `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables (TMDB_API_KEY, GROQ_API_KEY, etc.)
6. Deploy

### Frontend → Vercel (free)

1. Go to [vercel.com](https://vercel.com) → New Project
2. Import your GitHub repo
3. Set **Root Directory** to `frontend`
4. Add environment variable:
   ```
   NEXT_PUBLIC_API_URL=https://your-render-url.onrender.com
   ```
5. Deploy

> ⚠️ **Note:** Render free tier sleeps after 15 minutes of inactivity. First request after sleep takes ~50 seconds to wake up.

---

## 📝 Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `TMDB_API_KEY` | ✅ Yes | TMDB movie database API key |
| `GROQ_API_KEY` | ✅ Yes | Groq LLM API key (primary AI) |
| `GEMINI_API_KEY` | ❌ Optional | Google Gemini API key (fallback) |
| `OPENROUTER_API_KEY` | ❌ Optional | OpenRouter API key (fallback) |
| `DATABASE_URL` | ❌ Optional | PostgreSQL connection string |
| `REDIS_URL` | ❌ Optional | Redis connection string for caching |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | ✅ Yes | Backend API URL |

---

## 🙏 Credits

- Movie data provided by [TMDB](https://www.themoviedb.org/)
- AI powered by [Groq](https://groq.com/) (llama-3.3-70b-versatile)
- Built with [FastAPI](https://fastapi.tiangolo.com/) + [Next.js](https://nextjs.org/)

---

*This product uses the TMDB API but is not endorsed or certified by TMDB.*

'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import Image from 'next/image'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Movie {
  id: number
  title: string
  overview: string
  release_year: number | null
  release_date: string | null
  genres: string[]
  language: string
  rating: number
  vote_count: number
  poster_url: string | null
  popularity: number
}

interface CastMember {
  name: string
  character: string
  profile_url: string | null
}

interface MovieDetail extends Movie {
  tagline: string | null
  runtime: number | null
  spoken_languages: string[]
  backdrop_url: string | null
  trailer_key: string | null
  cast: CastMember[]
  director: string | null
  budget: number | null
  revenue: number | null
  status: string | null
  homepage: string | null
  tmdb_url: string
}

interface RecommendResponse {
  query: string
  filters: Record<string, unknown>
  sort: string
  page: number
  total_pages: number
  total_results: number
  movies: Movie[]
}

interface ActiveFilters {
  genres: string[]
  languages: string[]
  yearFrom: string
  yearTo: string
  minRating: number
}

// ─── Constants ────────────────────────────────────────────────────────────────

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const ALL_GENRES = [
  'Action','Adventure','Animation','Comedy','Crime','Documentary',
  'Drama','Family','Fantasy','History','Horror','Music',
  'Mystery','Romance','Science Fiction','Thriller','War','Western',
]

const ALL_LANGUAGES = [
  { code: 'te', label: 'Telugu' },
  { code: 'ta', label: 'Tamil' },
  { code: 'hi', label: 'Hindi' },
  { code: 'ml', label: 'Malayalam' },
  { code: 'kn', label: 'Kannada' },
  { code: 'en', label: 'English' },
  { code: 'ko', label: 'Korean' },
  { code: 'ja', label: 'Japanese' },
  { code: 'fr', label: 'French' },
  { code: 'es', label: 'Spanish' },
  { code: 'de', label: 'German' },
  { code: 'zh', label: 'Chinese' },
]

const LANG_NAME_TO_CODE: Record<string, string> = {
  // English names
  telugu: 'te', tamil: 'ta', hindi: 'hi', malayalam: 'ml',
  kannada: 'kn', english: 'en', korean: 'ko', japanese: 'ja',
  french: 'fr', spanish: 'es', german: 'de', chinese: 'zh',
  // Native script names
  'తెలుగు': 'te', 'हिंदी': 'hi', 'தமிழ்': 'ta', 'മലയാളം': 'ml',
  'ಕನ್ನಡ': 'kn', '한국어': 'ko', '日本語': 'ja', '中文': 'zh',
  'français': 'fr', 'español': 'es', 'deutsch': 'de',
}

const TMDB_GENRE_MAP: Record<number, string> = {
  28: 'Action', 12: 'Adventure', 16: 'Animation', 35: 'Comedy',
  80: 'Crime', 99: 'Documentary', 18: 'Drama', 10751: 'Family',
  14: 'Fantasy', 36: 'History', 27: 'Horror', 10402: 'Music',
  9648: 'Mystery', 10749: 'Romance', 878: 'Science Fiction',
  53: 'Thriller', 10752: 'War', 37: 'Western',
}

const SUGGESTIONS = [
  'Telugu action movies like RRR',
  '90s horror with good ratings',
  'Feel-good romantic comedies',
  'Christopher Nolan sci-fi films',
  'Korean thrillers',
  'Inspiring true story dramas',
  'Animated family movies',
  'Dark psychological thrillers',
]

const CURRENT_YEAR = new Date().getFullYear()
const EMPTY_FILTERS: ActiveFilters = { genres: [], languages: [], yearFrom: '', yearTo: '', minRating: 0 }

// ─── Theme tokens ─────────────────────────────────────────────────────────────
// bg=#0B1020  surface=#111827  surface2=#1a2236
// border=#1e2d4a  border2=#243352
// accent=cyan-400 (#00c2ff)  accent2=sky-500

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined) {
  if (!n) return '—'
  return n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M` : `$${(n / 1_000).toFixed(0)}K`
}
function fmtRuntime(mins: number | null) {
  if (!mins) return null
  const h = Math.floor(mins / 60), m = mins % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}
function filtersToQuerySuffix(f: ActiveFilters): string {
  const parts: string[] = []
  if (f.genres.length)    parts.push(f.genres.join(' '))
  if (f.languages.length) {
    const names = f.languages.map(code => ALL_LANGUAGES.find(l => l.code === code)?.label ?? code)
    parts.push(`in ${names.join(' or ')}`)
  }
  if (f.yearFrom && f.yearTo) parts.push(`from ${f.yearFrom} to ${f.yearTo}`)
  else if (f.yearFrom)        parts.push(`from ${f.yearFrom}`)
  else if (f.yearTo)          parts.push(`before ${f.yearTo}`)
  if (f.minRating > 0)        parts.push(`with rating above ${f.minRating}`)
  return parts.join(', ')
}
async function fetchMovieGenres(title: string): Promise<string[]> {
  try {
    const res  = await fetch(`https://api.themoviedb.org/3/search/movie?api_key=2e29a61173b8d52a1b5328c5ee5c7f6e&query=${encodeURIComponent(title)}&language=en-US`)
    const data = await res.json()
    const top  = data.results?.[0]
    if (!top) return []
    return (top.genre_ids as number[]).map((id: number) => TMDB_GENRE_MAP[id]).filter(Boolean)
  } catch { return [] }
}
async function parseAiFilters(aiFilters: Record<string, unknown>): Promise<ActiveFilters> {
  const genres: string[] = []
  ;(aiFilters.genres as string[] ?? []).forEach(g => {
    const m = ALL_GENRES.find(ag => ag.toLowerCase() === g.toLowerCase())
    if (m) genres.push(m)
  })
  if (genres.length === 0 && aiFilters.similar_to)
    genres.push(...await fetchMovieGenres(aiFilters.similar_to as string))

  const languages: string[] = []
  ;(aiFilters.languages as string[] ?? []).forEach(l => {
    const code = LANG_NAME_TO_CODE[l.toLowerCase()]
    if (code) languages.push(code)
  })
  return {
    genres, languages,
    yearFrom:  aiFilters.era_start  ? String(aiFilters.era_start)  : '',
    yearTo:    aiFilters.era_end    ? String(aiFilters.era_end)    : '',
    minRating: typeof aiFilters.min_rating === 'number' ? aiFilters.min_rating : 0,
  }
}

// ─── Star Rating ──────────────────────────────────────────────────────────────

function StarRating({ rating }: { rating: number }) {
  const pct = (rating / 10) * 100
  return (
    <div className="flex items-center gap-1.5">
      <div className="relative inline-block text-lg leading-none">
        <span style={{ color: '#1e2d4a' }}>★★★★★</span>
        <span className="absolute inset-0 overflow-hidden" style={{ width: `${pct}%`, color: '#facc15' }}>★★★★★</span>
      </div>
      <span className="text-sm font-semibold" style={{ color: '#facc15' }}>{rating.toFixed(1)}</span>
    </div>
  )
}

// ─── Filter Panel ─────────────────────────────────────────────────────────────

function FilterPanel({ filters, onChange, onApply, onClear }: {
  filters: ActiveFilters
  onChange: (f: ActiveFilters) => void
  onApply: () => void
  onClear: () => void
}) {
  const toggle = (arr: string[], val: string) =>
    arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val]

  const hasAny = filters.genres.length > 0 || filters.languages.length > 0 ||
    !!filters.yearFrom || !!filters.yearTo || filters.minRating > 0

  const activeBtn  = 'text-[#0B1020] font-semibold'
  const inactiveBtn = 'text-[#7a8fb5] hover:text-[#00c2ff]'

  return (
    <div className="w-full rounded-xl p-5 flex flex-col gap-5"
      style={{ background: '#111827', border: '1px solid #1e2d4a' }}>

      {/* Genres */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest mb-3" style={{ color: '#7a8fb5' }}>Genres</p>
        <div className="flex flex-wrap gap-2">
          {ALL_GENRES.map(g => {
            const on = filters.genres.includes(g)
            return (
              <button key={g} onClick={() => onChange({ ...filters, genres: toggle(filters.genres, g) })}
                className={`rounded-full px-3 py-1 text-xs font-medium border transition-all ${on ? activeBtn : inactiveBtn}`}
                style={on
                  ? { background: '#00c2ff', borderColor: '#00c2ff' }
                  : { background: 'transparent', borderColor: '#1e2d4a' }}>
                {g}
              </button>
            )
          })}
        </div>
      </div>

      {/* Languages */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest mb-3" style={{ color: '#7a8fb5' }}>Language</p>
        <div className="flex flex-wrap gap-2">
          {ALL_LANGUAGES.map(l => {
            const on = filters.languages.includes(l.code)
            return (
              <button key={l.code} onClick={() => onChange({ ...filters, languages: toggle(filters.languages, l.code) })}
                className={`rounded-full px-3 py-1 text-xs font-medium border transition-all ${on ? activeBtn : inactiveBtn}`}
                style={on
                  ? { background: '#00c2ff', borderColor: '#00c2ff' }
                  : { background: 'transparent', borderColor: '#1e2d4a' }}>
                {l.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Year + Rating */}
      <div className="flex flex-wrap gap-6 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#7a8fb5' }}>Year From</label>
          <input type="number" min={1900} max={CURRENT_YEAR} placeholder="1990"
            value={filters.yearFrom}
            onChange={e => onChange({ ...filters, yearFrom: e.target.value })}
            className="w-28 rounded-lg px-3 py-2 text-sm text-white outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
            style={{ background: '#0B1020', border: '1px solid #1e2d4a' }} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#7a8fb5' }}>Year To</label>
          <input type="number" min={1900} max={CURRENT_YEAR} placeholder={String(CURRENT_YEAR)}
            value={filters.yearTo}
            onChange={e => onChange({ ...filters, yearTo: e.target.value })}
            className="w-28 rounded-lg px-3 py-2 text-sm text-white outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
            style={{ background: '#0B1020', border: '1px solid #1e2d4a' }} />
        </div>
        <div className="flex flex-col gap-1 flex-1 min-w-[180px]">
          <label className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#7a8fb5' }}>
            Min Rating — <span style={{ color: '#00c2ff' }}>{filters.minRating > 0 ? `${filters.minRating}+` : 'Any'}</span>
          </label>
          <div className="flex items-center gap-3">
            <input type="range" min={0} max={9} step={0.5}
              value={filters.minRating}
              onChange={e => onChange({ ...filters, minRating: parseFloat(e.target.value) })}
              className="flex-1 h-1.5 cursor-pointer" style={{ accentColor: '#00c2ff' }} />
            <div className="flex gap-1">
              {[0, 5, 6, 7, 8].map(v => {
                const on = filters.minRating === v
                return (
                  <button key={v} onClick={() => onChange({ ...filters, minRating: v })}
                    className={`rounded px-2 py-0.5 text-xs border transition-all ${on ? 'text-[#0B1020] font-semibold' : 'text-[#7a8fb5] hover:text-[#00c2ff]'}`}
                    style={on
                      ? { background: '#00c2ff', borderColor: '#00c2ff' }
                      : { background: 'transparent', borderColor: '#1e2d4a' }}>
                    {v === 0 ? 'Any' : `${v}+`}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2" style={{ borderTop: '1px solid #1e2d4a' }}>
        <button onClick={onApply}
          className="rounded-lg px-5 py-2 text-sm font-semibold text-[#0B1020] transition-all active:scale-95"
          style={{ background: '#00c2ff' }}>
          Apply Filters
        </button>
        {hasAny && (
          <button onClick={onClear}
            className="rounded-lg px-4 py-2 text-sm transition-all"
            style={{ border: '1px solid #1e2d4a', color: '#7a8fb5' }}
            onMouseEnter={e => { (e.target as HTMLElement).style.color = '#f87171'; (e.target as HTMLElement).style.borderColor = '#f8717166' }}
            onMouseLeave={e => { (e.target as HTMLElement).style.color = '#7a8fb5'; (e.target as HTMLElement).style.borderColor = '#1e2d4a' }}>
            Clear All
          </button>
        )}
        {hasAny && (
          <span className="ml-auto text-xs" style={{ color: '#00c2ff' }}>
            {[
              filters.genres.length    ? `${filters.genres.length} genre${filters.genres.length > 1 ? 's' : ''}` : '',
              filters.languages.length ? `${filters.languages.length} lang`  : '',
              (filters.yearFrom || filters.yearTo) ? 'year range' : '',
              filters.minRating > 0   ? `${filters.minRating}+ rating` : '',
            ].filter(Boolean).join(' · ')}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Movie Detail Modal ───────────────────────────────────────────────────────

function MovieModal({ movieId, onClose }: { movieId: number; onClose: () => void }) {
  const [detail, setDetail] = useState<MovieDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [imgErr, setImgErr]   = useState(false)
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setLoading(true); setError(null)
    fetch(`${API}/movie/${movieId}`)
      .then(r => { if (!r.ok) throw new Error(`Error ${r.status}`); return r.json() })
      .then(setDetail).catch(e => setError(e.message)).finally(() => setLoading(false))
  }, [movieId])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  useEffect(() => { document.body.style.overflow = 'hidden'; return () => { document.body.style.overflow = '' } }, [])

  return (
    <div ref={overlayRef} onClick={e => { if (e.target === overlayRef.current) onClose() }}
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
      style={{ background: 'rgba(11,16,32,0.92)', backdropFilter: 'blur(8px)' }}>
      <div className="relative w-full sm:max-w-4xl max-h-[95vh] sm:max-h-[90vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl shadow-2xl"
        style={{ background: '#111827', border: '1px solid #1e2d4a' }}>

        <button onClick={onClose}
          className="absolute top-4 right-4 z-10 rounded-full p-2 transition-all"
          style={{ background: 'rgba(11,16,32,0.8)', color: '#7a8fb5' }}
          onMouseEnter={e => (e.currentTarget.style.color = '#f0f4ff')}
          onMouseLeave={e => (e.currentTarget.style.color = '#7a8fb5')}>
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {loading && (
          <div className="flex items-center justify-center h-80">
            <svg className="animate-spin h-8 w-8" style={{ color: '#00c2ff' }} viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
          </div>
        )}
        {error && !loading && (
          <div className="flex items-center justify-center h-80">
            <p className="text-sm" style={{ color: '#f87171' }}>⚠ {error}</p>
          </div>
        )}

        {detail && !loading && (
          <>
            <div className="relative w-full aspect-video rounded-t-2xl overflow-hidden" style={{ background: '#0B1020' }}>
              {detail.trailer_key ? (
                <iframe src={`https://www.youtube.com/embed/${detail.trailer_key}?autoplay=1&mute=0&rel=0&modestbranding=1`}
                  title={`${detail.title} trailer`}
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen className="absolute inset-0 w-full h-full" />
              ) : detail.backdrop_url && !imgErr ? (
                <>
                  <Image src={detail.backdrop_url} alt={detail.title} fill className="object-cover opacity-50" onError={() => setImgErr(true)} />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className="rounded-full px-4 py-2 text-sm" style={{ background: 'rgba(11,16,32,0.7)', color: '#7a8fb5', border: '1px solid #1e2d4a' }}>No trailer available</span>
                  </div>
                </>
              ) : (
                <div className="absolute inset-0 flex items-center justify-center text-7xl" style={{ color: '#1e2d4a' }}>🎬</div>
              )}
            </div>

            <div className="flex flex-col sm:flex-row gap-6 p-5 sm:p-7">
              <div className="hidden sm:block flex-shrink-0 w-36">
                <div className="relative w-36 aspect-[2/3] rounded-lg overflow-hidden" style={{ background: '#1a2236', border: '1px solid #1e2d4a' }}>
                  {detail.poster_url
                    ? <Image src={detail.poster_url} alt={detail.title} fill className="object-cover" />
                    : <div className="flex h-full items-center justify-center text-4xl" style={{ color: '#1e2d4a' }}>🎬</div>}
                </div>
              </div>

              <div className="flex-1 min-w-0 flex flex-col gap-4">
                <div>
                  <h2 className="text-2xl sm:text-3xl font-bold leading-tight" style={{ color: '#f0f4ff' }}>{detail.title}</h2>
                  {detail.tagline && <p className="mt-1 text-sm italic" style={{ color: '#00c2ff', opacity: 0.8 }}>{detail.tagline}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-3 text-sm" style={{ color: '#7a8fb5' }}>
                  {detail.release_date && <span>{detail.release_date}</span>}
                  {detail.runtime && <><span style={{ color: '#1e2d4a' }}>·</span><span>{fmtRuntime(detail.runtime)}</span></>}
                  <span style={{ color: '#1e2d4a' }}>·</span>
                  <span className="uppercase tracking-widest text-xs rounded px-2 py-0.5" style={{ border: '1px solid #1e2d4a' }}>{detail.language}</span>
                  {detail.status && detail.status !== 'Released' && (
                    <span className="rounded-full px-2 py-0.5 text-xs" style={{ background: 'rgba(0,194,255,0.15)', color: '#00c2ff' }}>{detail.status}</span>
                  )}
                </div>
                <div className="flex items-center gap-4">
                  <StarRating rating={detail.rating} />
                  <span className="text-xs" style={{ color: '#7a8fb5' }}>{detail.vote_count.toLocaleString()} votes</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {detail.genres.map(g => (
                    <span key={g} className="rounded-full px-3 py-1 text-xs" style={{ background: '#1a2236', border: '1px solid #1e2d4a', color: '#a0b4d0' }}>{g}</span>
                  ))}
                </div>
                <p className="text-sm leading-relaxed" style={{ color: '#a0b4d0' }}>{detail.overview || 'No overview available.'}</p>
                {detail.director && (
                  <p className="text-sm" style={{ color: '#7a8fb5' }}>
                    Director: <span className="font-medium" style={{ color: '#f0f4ff' }}>{detail.director}</span>
                  </p>
                )}
                {(detail.budget || detail.revenue) && (
                  <div className="flex gap-6 text-sm">
                    {detail.budget  && <div><span className="text-xs block" style={{ color: '#7a8fb5' }}>Budget</span><span className="font-medium" style={{ color: '#f0f4ff' }}>{fmt(detail.budget)}</span></div>}
                    {detail.revenue && <div><span className="text-xs block" style={{ color: '#7a8fb5' }}>Revenue</span><span className="font-medium" style={{ color: '#f0f4ff' }}>{fmt(detail.revenue)}</span></div>}
                  </div>
                )}
                <div className="flex gap-3 pt-1">
                  <a href={detail.tmdb_url} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm transition-all"
                    style={{ background: '#1a2236', border: '1px solid #1e2d4a', color: '#a0b4d0' }}>TMDB ↗</a>
                  {detail.homepage && (
                    <a href={detail.homepage} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm transition-all"
                      style={{ background: '#1a2236', border: '1px solid #1e2d4a', color: '#a0b4d0' }}>Official Site ↗</a>
                  )}
                </div>
              </div>
            </div>

            {detail.cast.length > 0 && (
              <div className="px-5 sm:px-7 pb-7">
                <h3 className="text-sm font-semibold uppercase tracking-widest mb-4" style={{ color: '#7a8fb5' }}>Cast</h3>
                <div className="flex gap-3 overflow-x-auto pb-2">
                  {detail.cast.map((m, i) => (
                    <div key={i} className="flex-shrink-0 w-20 text-center">
                      <div className="relative w-20 h-20 rounded-full overflow-hidden mx-auto mb-2" style={{ background: '#1a2236', border: '1px solid #1e2d4a' }}>
                        {m.profile_url
                          ? <Image src={m.profile_url} alt={m.name} fill className="object-cover" />
                          : <div className="flex h-full items-center justify-center text-2xl" style={{ color: '#1e2d4a' }}>👤</div>}
                      </div>
                      <p className="text-xs font-medium leading-tight line-clamp-2" style={{ color: '#f0f4ff' }}>{m.name}</p>
                      <p className="text-xs leading-tight line-clamp-1 mt-0.5" style={{ color: '#7a8fb5' }}>{m.character}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ─── Movie Card ───────────────────────────────────────────────────────────────

function MovieCard({ movie, onClick }: { movie: Movie; onClick: () => void }) {
  const [imgErr, setImgErr] = useState(false)
  return (
    <div onClick={onClick} className="group flex flex-col rounded-xl overflow-hidden cursor-pointer transition-all duration-300 hover:-translate-y-1"
      style={{ background: '#111827', border: '1px solid #1e2d4a' }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = '#00c2ff66')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = '#1e2d4a')}>
      <div className="relative w-full aspect-[2/3] overflow-hidden" style={{ background: '#1a2236' }}>
        {movie.poster_url && !imgErr
          ? <Image src={movie.poster_url} alt={movie.title} fill
              sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 20vw"
              className="object-cover transition-transform duration-500 group-hover:scale-105"
              onError={() => setImgErr(true)} />
          : <div className="flex h-full items-center justify-center text-5xl" style={{ color: '#1e2d4a' }}>🎬</div>}

        {/* Play overlay */}
        <div className="absolute inset-0 flex items-center justify-center transition-all duration-300"
          style={{ background: 'rgba(0,0,0,0)', opacity: 0 }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(0,0,0,0.45)'; e.currentTarget.style.opacity = '1' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'rgba(0,0,0,0)'; e.currentTarget.style.opacity = '0' }}>
        </div>
        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300">
          <div className="rounded-full p-3 shadow-lg" style={{ background: 'rgba(0,194,255,0.9)' }}>
            <svg className="w-6 h-6 translate-x-0.5" fill="#0B1020" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
          </div>
        </div>

        <span className="absolute top-2 right-2 rounded-md px-2 py-0.5 text-[10px] uppercase tracking-widest backdrop-blur-sm"
          style={{ background: 'rgba(11,16,32,0.8)', color: '#a0b4d0' }}>{movie.language}</span>
        {movie.release_date && (
          <span className="absolute top-2 left-2 rounded-md px-2 py-0.5 text-[10px] backdrop-blur-sm"
            style={{ background: 'rgba(11,16,32,0.8)', color: '#a0b4d0' }}>{movie.release_date}</span>
        )}
      </div>

      <div className="flex flex-col gap-2 p-3 flex-1">
        <h3 className="font-semibold text-sm leading-snug line-clamp-2 transition-colors group-hover:text-[#00c2ff]"
          style={{ color: '#f0f4ff' }}>{movie.title}</h3>
        <div className="flex items-center gap-1.5">
          <span style={{ color: '#facc15', fontSize: '0.875rem' }}>★</span>
          <span className="text-sm font-semibold" style={{ color: '#facc15' }}>{movie.rating.toFixed(1)}</span>
        </div>
        {movie.genres.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {movie.genres.slice(0, 3).map(g => (
              <span key={g} className="rounded-sm px-1.5 py-0.5 text-[10px]"
                style={{ background: '#1a2236', color: '#7a8fb5' }}>{g}</span>
            ))}
          </div>
        )}
        <p className="text-xs line-clamp-2 leading-relaxed mt-auto" style={{ color: '#4a5f80' }}>{movie.overview || 'No description available.'}</p>
      </div>
    </div>
  )
}

function SkeletonCard() {
  return (
    <div className="flex flex-col rounded-xl overflow-hidden animate-pulse" style={{ background: '#111827', border: '1px solid #1e2d4a' }}>
      <div className="w-full aspect-[2/3]" style={{ background: '#1a2236' }} />
      <div className="p-3 flex flex-col gap-2">
        <div className="h-4 rounded w-3/4" style={{ background: '#1a2236' }} />
        <div className="h-3 rounded w-1/2" style={{ background: '#1a2236' }} />
        <div className="h-3 rounded w-full" style={{ background: '#1a2236' }} />
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [query, setQuery]                     = useState('')
  const [result, setResult]                   = useState<RecommendResponse | null>(null)
  const [loading, setLoading]                 = useState(false)
  const [error, setError]                     = useState<string | null>(null)
  const [page, setPage]                       = useState(1)
  const [sort, setSort]                       = useState('recent')
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [selectedMovieId, setSelectedMovieId] = useState<number | null>(null)
  const [showFilters, setShowFilters]         = useState(false)
  const [activeFilters, setActiveFilters]     = useState<ActiveFilters>(EMPTY_FILTERS)
  const [pendingFilters, setPendingFilters]   = useState<ActiveFilters>(EMPTY_FILTERS)

  const inputRef   = useRef<HTMLInputElement>(null)
  const resultsRef = useRef<HTMLDivElement>(null)

  async function fetchMovies(q: string, p = 1, s = sort, af = activeFilters) {
    if (!q.trim()) return
    setLoading(true); setError(null)
    try {
      const suffix = filtersToQuerySuffix(af)
      const fullQ  = suffix ? `${q}, ${suffix}` : q
      const res    = await fetch(`${API}/recommend?q=${encodeURIComponent(fullQ)}&page=${p}&sort=${s}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail ?? `Server error ${res.status}`)
      }
      const data: RecommendResponse = await res.json()
      setResult(data); setPage(p); setSort(s)
      const derived = await parseAiFilters(data.filters)
      setPendingFilters(derived); setActiveFilters(derived)
      setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
    } finally { setLoading(false) }
  }

  function handleSubmit(e: React.FormEvent) { e.preventDefault(); setShowSuggestions(false); fetchMovies(query, 1, sort, EMPTY_FILTERS) }
  function handleSuggestion(s: string)      { setQuery(s); setShowSuggestions(false); fetchMovies(s, 1, sort, EMPTY_FILTERS) }
  function handleSortChange(ns: string)     { setSort(ns); if (result) fetchMovies(result.query, 1, ns, activeFilters) }
  function handleApplyFilters()             { setActiveFilters(pendingFilters); if (result) fetchMovies(result.query, 1, sort, pendingFilters) }
  function handleClearFilters()             { setPendingFilters(EMPTY_FILTERS); setActiveFilters(EMPTY_FILTERS); if (result) fetchMovies(result.query, 1, sort, EMPTY_FILTERS) }

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (inputRef.current && !inputRef.current.closest('form')?.contains(e.target as Node))
        setShowSuggestions(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const handleClose = useCallback(() => setSelectedMovieId(null), [])

  const filterCount = [
    activeFilters.genres.length > 0,
    activeFilters.languages.length > 0,
    !!(activeFilters.yearFrom || activeFilters.yearTo),
    activeFilters.minRating > 0,
  ].filter(Boolean).length

  return (
    <main className="min-h-screen" style={{ background: '#0B1020' }}>

      {selectedMovieId !== null && <MovieModal movieId={selectedMovieId} onClose={handleClose} />}

      {/* ── Hero ── */}
      <section className="relative flex flex-col items-center justify-center px-4 pt-20 pb-10 text-center">
        {/* Glow */}
        <div className="pointer-events-none absolute inset-0 opacity-30"
          style={{ background: 'radial-gradient(ellipse 70% 45% at 50% 0%, #00c2ff 0%, transparent 65%)' }} />

        <div className="relative z-10 flex flex-col items-center gap-6 w-full max-w-2xl">
          {/* Logo */}
          <div className="flex items-center justify-center">
            <Image
              src="/logo.png"
              alt="CineMatch"
              width={320}
              height={160}
              priority
              className="object-contain drop-shadow-[0_0_18px_rgba(0,194,255,0.4)]"
            />
          </div>
          <p className="text-base" style={{ color: '#7a8fb5' }}>Describe any movie you&apos;re in the mood for — in any language</p>

          {/* Search */}
          <form onSubmit={handleSubmit} className="relative w-full">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input ref={inputRef} type="text" value={query}
                  onChange={e => setQuery(e.target.value)}
                  onFocus={() => setShowSuggestions(true)}
                  placeholder="Telugu action movies like RRR…"
                  className="w-full rounded-xl px-5 py-4 text-base outline-none transition-all"
                  style={{ background: '#111827', border: '1px solid #1e2d4a', color: '#f0f4ff' }}
                  onFocusCapture={e => (e.target as HTMLInputElement).style.borderColor = '#00c2ff66'}
                  onBlurCapture={e  => (e.target as HTMLInputElement).style.borderColor = '#1e2d4a'}
                  autoComplete="off" />

                {showSuggestions && !query && (
                  <div className="absolute top-full left-0 right-0 z-50 mt-2 rounded-xl overflow-hidden shadow-2xl"
                    style={{ background: '#111827', border: '1px solid #1e2d4a' }}>
                    <p className="px-4 py-2 text-xs uppercase tracking-widest" style={{ color: '#4a5f80' }}>Try these</p>
                    {SUGGESTIONS.map(s => (
                      <button key={s} type="button" onClick={() => handleSuggestion(s)}
                        className="w-full text-left px-4 py-2.5 text-sm transition-colors"
                        style={{ color: '#a0b4d0' }}
                        onMouseEnter={e => { (e.target as HTMLElement).style.background = '#1a2236'; (e.target as HTMLElement).style.color = '#00c2ff' }}
                        onMouseLeave={e => { (e.target as HTMLElement).style.background = 'transparent'; (e.target as HTMLElement).style.color = '#a0b4d0' }}>
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Filter btn */}
              <button type="button" onClick={() => setShowFilters(p => !p)}
                className="relative rounded-xl px-4 py-4 transition-all"
                style={{
                  background: showFilters || filterCount > 0 ? 'rgba(0,194,255,0.1)' : '#111827',
                  border: `1px solid ${showFilters || filterCount > 0 ? '#00c2ff66' : '#1e2d4a'}`,
                  color: showFilters || filterCount > 0 ? '#00c2ff' : '#7a8fb5',
                }}>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4h18M6 8h12M9 12h6M11 16h2" />
                </svg>
                {filterCount > 0 && (
                  <span className="absolute -top-1.5 -right-1.5 rounded-full text-[10px] font-bold w-4 h-4 flex items-center justify-center"
                    style={{ background: '#00c2ff', color: '#0B1020' }}>{filterCount}</span>
                )}
              </button>

              {/* Search btn */}
              <button type="submit" disabled={loading || !query.trim()}
                className="rounded-xl px-6 py-4 font-semibold transition-all active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ background: '#00c2ff', color: '#0B1020' }}>
                {loading
                  ? <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                  : 'Search'}
              </button>
            </div>
          </form>

          {/* Filter panel */}
          {showFilters && (
            <div className="w-full">
              <FilterPanel filters={pendingFilters} onChange={setPendingFilters} onApply={handleApplyFilters} onClear={handleClearFilters} />
            </div>
          )}

          {/* Suggestion pills */}
          {!showFilters && (
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.slice(0, 4).map(s => (
                <button key={s} onClick={() => handleSuggestion(s)}
                  className="rounded-full px-3 py-1.5 text-xs transition-all"
                  style={{ border: '1px solid #1e2d4a', background: 'transparent', color: '#7a8fb5' }}
                  onMouseEnter={e => { (e.currentTarget).style.borderColor = '#00c2ff66'; (e.currentTarget).style.color = '#00c2ff' }}
                  onMouseLeave={e => { (e.currentTarget).style.borderColor = '#1e2d4a';   (e.currentTarget).style.color = '#7a8fb5' }}>
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Error */}
      {error && (
        <div className="mx-auto max-w-2xl px-4 mb-6">
          <div className="rounded-xl px-5 py-4 text-sm" style={{ border: '1px solid rgba(248,113,113,0.2)', background: 'rgba(248,113,113,0.08)', color: '#f87171' }}>⚠ {error}</div>
        </div>
      )}

      {/* Results */}
      <div ref={resultsRef}>
        {(result || loading) && (
          <section className="mx-auto max-w-7xl px-4 pb-20">
            {result && !loading && (
              <div className="mb-6 flex flex-col gap-3">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <h2 className="text-lg font-semibold" style={{ color: '#f0f4ff' }}>
                    Results for{' '}
                    <span style={{ color: '#00c2ff' }}>&ldquo;{result.query}&rdquo;</span>
                  </h2>
                  <div className="flex items-center gap-3">
                    <span className="text-sm" style={{ color: '#7a8fb5' }}>
                      {result.total_results.toLocaleString()} matches · page {result.page}/{result.total_pages}
                    </span>
                    <select value={sort} onChange={e => handleSortChange(e.target.value)}
                      className="rounded-lg px-3 py-1.5 text-sm outline-none cursor-pointer"
                      style={{ background: '#111827', border: '1px solid #1e2d4a', color: '#a0b4d0' }}>
                      <option value="recent">🕐 Recent first</option>
                      <option value="popular">🔥 Most popular</option>
                      <option value="rated">⭐ Highest rated</option>
                      <option value="revenue">💰 Top grossing</option>
                      <option value="oldest">📅 Oldest first</option>
                    </select>
                  </div>
                </div>
              </div>
            )}

            <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
              {loading
                ? Array.from({ length: 20 }).map((_, i) => <SkeletonCard key={i} />)
                : result?.movies.map(m => <MovieCard key={m.id} movie={m} onClick={() => setSelectedMovieId(m.id)} />)}
            </div>

            {!loading && result && result.movies.length === 0 && (
              <div className="mt-16 flex flex-col items-center gap-3 text-center" style={{ color: '#4a5f80' }}>
                <span className="text-5xl">🎭</span>
                <p className="text-lg">No movies found.</p>
                <p className="text-sm">Try different keywords or broaden your search.</p>
              </div>
            )}

            {!loading && result && result.movies.length > 0 && (
              <div className="mt-10 flex items-center justify-center gap-3">
                {[
                  { label: '← Prev', action: () => fetchMovies(result.query, page - 1, sort), disabled: page <= 1 },
                  { label: 'Next →', action: () => fetchMovies(result.query, page + 1, sort), disabled: page >= result.total_pages },
                ].map(btn => (
                  <button key={btn.label} onClick={btn.action} disabled={btn.disabled}
                    className="rounded-lg px-5 py-2.5 text-sm transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                    style={{ border: '1px solid #1e2d4a', background: '#111827', color: '#a0b4d0' }}
                    onMouseEnter={e => { if (!btn.disabled) { (e.currentTarget).style.borderColor = '#00c2ff66'; (e.currentTarget).style.color = '#00c2ff' }}}
                    onMouseLeave={e => { (e.currentTarget).style.borderColor = '#1e2d4a'; (e.currentTarget).style.color = '#a0b4d0' }}>
                    {btn.label}
                  </button>
                ))}
                <span className="text-sm" style={{ color: '#4a5f80' }}>Page {page} of {result.total_pages}</span>
              </div>
            )}
          </section>
        )}
      </div>

      {!result && !loading && !error && (
        <section className="flex flex-col items-center gap-4 pb-20" style={{ color: '#1e2d4a' }}>
          <span className="text-6xl opacity-40">🍿</span>
          <p className="text-sm" style={{ color: '#4a5f80' }}>Start searching to discover movies</p>
        </section>
      )}
    </main>
  )
}

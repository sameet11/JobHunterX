# JobHunterX — Architecture Reference

**Status:** Phase 1 + Review Queue complete · Manual outreach via scripts
**Stack:** Python 3.12 · Playwright · Gemini API (scoring/resume only) · SQLite · Google Sheets
**Mode:** Human-in-the-loop — bot scrapes + ranks, you apply + send outreach

---

## 1. SYSTEM OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────┐
│                   JOBHUNTERX — JOB SEARCH ASSISTANT                  │
│                                                                      │
│  python main.py                                                      │
│    Scrape (10 sources) → Score → Legitimacy Check → review_queue.md │
│                                                                      │
│  You apply manually → mark_applied.py → outreach.py                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. PIPELINE

```
┌──────────────────────────────────────────────────────────────────────┐
│                           python main.py                             │
│                                                                      │
│  scrape_all()                                                        │
│    • Greenhouse  : boards-api.greenhouse.io/v1/boards/{slug}/jobs    │
│    • Lever       : api.lever.co/v0/postings/{slug}?mode=json         │
│    • Ashby       : api.ashbyhq.com/posting-api/job-board/{slug}      │
│    • RemoteOK    : remoteok.com/api  (no auth)                       │
│    • Remotive    : remotive.com/api/remote-jobs  (no auth)           │
│    • HN Hiring   : hn.algolia.com/api/v1/search (current month)      │
│    • Naukri      : naukri.com/jobapi/v3/search  (gated by flag)      │
│    • Adzuna      : api.adzuna.com  (optional, requires API key)      │
│    • Apify LI    : Apify actor  (optional, requires token)           │
│    • Within-source dedup: source:id                                  │
│    • Cross-source dedup: (company, title) — first source wins        │
│                                                                      │
│  filter_and_rank()                                                   │
│    • Skip: blocked companies, already seen, applied recently,        │
│            salary below min                                          │
│    • MatchScorer: keyword overlap + recency boost + India boost      │
│    • Drop below min_match_score threshold                            │
│    • Write all passing jobs to SQLite                                │
│                                                                      │
│  ReviewQueue.build()                                                 │
│    • LegitimacyChecker per job:                                      │
│        posting age, JD length, repost detection, title red-flags     │
│        → high_confidence ✓ | caution ⚠ | suspicious 🚫              │
│    • Writes data/review_queue.md (top N, ranked + flagged)           │
│                                                                      │
│  FollowupTracker                                                     │
│    • Sweeps Applied/Responded/Interview jobs by cadence              │
│    • Writes data/follow_ups.md (URGENT / OVERDUE / WAITING / COLD)  │
└──────────────────────────────────────────────────────────────────────┘
                          ▼  (you take over)
┌──────────────────────────────────────────────────────────────────────┐
│  Manual workflow                                                     │
│                                                                      │
│  1. Open data/review_queue.md                                        │
│  2. Apply manually on company sites                                  │
│  3. python scripts/mark_applied.py <dedup_key>  → records in SQLite  │
│  4. python scripts/generate_resume.py 1 3 5     → tailored PDFs     │
│  5. python scripts/outreach.py 1 3 5            → finds recruiters  │
│       opens real browser (your LinkedIn session) → linkedin_targets.md│
│       copy-paste notes manually on LinkedIn                          │
│  6. python scripts/analyze_patterns.py          → funnel + ROI      │
└──────────────────────────────────────────────────────────────────────┘
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Persistent state                                                    │
│                                                                      │
│  data/applied.sqlite    — jobs table (status, score, timestamps)     │
│  data/review_queue.md   — regenerated each run                       │
│  data/follow_ups.md     — regenerated each run                       │
│  data/linkedin_targets.md — written by scripts/outreach.py           │
│  output/{Co}_{Role}.pdf — tailored resumes (generate_resume.py)     │
│  Google Sheets:                                                      │
│    Tab 1: Applications  (mark_applied.py syncs here)                 │
│    Tab 2: Connect Queue (outreach.py syncs here)                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. PROJECT STRUCTURE

```
JobHunterX/
├── config/
│   ├── user_config.py          # All knobs (gitignored — edit freely)
│   ├── user_config.example.py  # Template — copy to user_config.py
│   └── platform_config.py      # Reads API keys from .env
│
├── src/
│   ├── models.py               # Pydantic: Job, ScoredJob, Recruiter, enums
│   │
│   ├── scraper/                # All API-based, no browser
│   │   ├── greenhouse_scraper.py   # boards-api.greenhouse.io (cached)
│   │   ├── lever_scraper.py        # api.lever.co (cached)
│   │   ├── ashby_scraper.py        # api.ashbyhq.com (cached)
│   │   ├── remoteok_scraper.py     # remoteok.com/api (no auth)
│   │   ├── remotive_scraper.py     # remotive.com/api (no auth)
│   │   ├── hn_scraper.py           # Algolia HN (current-month thread)
│   │   ├── naukri_scraper.py       # curl_cffi Chrome impersonation
│   │   ├── adzuna_scraper.py       # api.adzuna.com (optional)
│   │   ├── apify_scraper.py        # Apify LinkedIn (optional)
│   │   ├── indeed_scraper.py       # SerpAPI (registered, not default)
│   │   ├── base_scraper.py
│   │   └── scraper_factory.py
│   │
│   ├── analyzer/
│   │   ├── match_scorer.py         # Keyword overlap + recency + India boost
│   │   └── legitimacy_checker.py   # Ghost-job heuristics
│   │
│   ├── apply/
│   │   └── review_queue.py         # Builds data/review_queue.md
│   │
│   ├── resume/
│   │   ├── resume_tailor.py        # Reorders skills by JD keywords → PDF
│   │   └── templates/
│   │       └── resume_template.html  # (gitignored)
│   │
│   ├── outreach/
│   │   ├── browser_finder.py       # Playwright LinkedIn people search
│   │   └── browser_cookies.py      # LinkedIn cookie extraction helper
│   │
│   ├── tracker/
│   │   ├── local_db.py             # SQLite: jobs + outreach tables
│   │   ├── google_sheets.py        # Applications + Connect Queue tabs
│   │   ├── followup_tracker.py     # URGENT/OVERDUE/WAITING/COLD cadence
│   │   └── schema.py               # Column definitions + Status enum
│   │
│   └── utils/
│       ├── logger.py               # loguru
│       ├── retry.py                # tenacity decorator
│       └── human_behavior.py       # Random delays / typing simulation
│
├── tests/
│   ├── test_resume_tailor.py       # 18 tests
│   ├── test_multi_source_scrape.py # Cross-source dedup
│   └── conftest.py
│
├── scripts/
│   ├── mark_applied.py     # Record manual application: mark_applied.py <dedup_key>
│   ├── generate_resume.py  # Tailor PDFs: generate_resume.py 1 3 5
│   ├── outreach.py         # Find LinkedIn recruiters: outreach.py 1 3 5
│   ├── analyze_patterns.py # Funnel + source ROI + recommendations
│   └── export_tracker.py   # Export SQLite to CSV/JSON
│
├── main.py                  # Single entrypoint
├── {your_resume}.pdf        # Static resume (gitignored)
├── requirements.txt
├── .env                     # Not in git
├── .env.example
└── SETUP.md
```

---

## 4. MODULE DETAIL

### 4.1 Scrapers (`src/scraper/`)

| Class | Endpoint | Auth | Caching |
|---|---|---|---|
| `GreenhouseScraper` | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | None | All companies fetched once; filtered per search() |
| `LeverScraper` | `api.lever.co/v0/postings/{slug}?mode=json` | None | Same pattern |
| `AshbyScraper` | `api.ashbyhq.com/posting-api/job-board/{slug}` | None | Same pattern |
| `RemoteOKScraper` | `remoteok.com/api` | None | Single fetch per run |
| `RemotiveScraper` | `remotive.com/api/remote-jobs` | None | Single fetch per run |
| `HNScraper` | `hn.algolia.com/api/v1/search_by_date` | None | Current-month thread cached |
| `NaukriScraper` | `naukri.com/jobapi/v3/search` | None (TLS fingerprint) | None |
| `AdzunaScraper` | `api.adzuna.com/v1/api/jobs/in/search` | `ADZUNA_APP_ID/KEY` | None |
| `ApifyLinkedInScraper` | Apify cloud actor | `APIFY_API_TOKEN` | None |

Dedup: within-source by `source:id`; cross-source by `(company.lower(), title.lower())` — first source wins.

### 4.2 Scorer + Legitimacy (`src/analyzer/`)

**`MatchScorer`:**
- Tokenizes `job.description + job.title` vs candidate skills list
- Denominator capped at 15
- Recency boost: jobs < 24h old get up to 20% extra (linear decay)
- India location boost: Mumbai/Bangalore/Hyderabad/Pune/Delhi get up to 45% extra
- Returns `int 0–100`

**`LegitimacyChecker`:**
- Posting age vs `legitimacy_max_age_days` / `legitimacy_stale_age_days`
- JD length vs `legitimacy_min_description_chars`
- Repost detection (same company+title in DB recently)
- Title red-flags (`talent pool`, `general application`, `evergreen`, ...)
- Returns tier: `high_confidence` ✓ | `caution` ⚠ | `suspicious` 🚫

### 4.3 Review Queue (`src/apply/review_queue.py`)

Writes `data/review_queue.md` — ranked Markdown with company, title, score, location, posting age, apply URL, legitimacy tier, dedup_key, JD preview. High-confidence first; suspicious at the bottom but still visible.

### 4.4 Resume Tailor (`src/resume/resume_tailor.py`)

Used by `scripts/generate_resume.py`. Reorders `<div class="skill-row">` blocks inside `SKILLS_BLOCK_START/END` markers by scoring each skill category against JD-matched keywords. Renders to PDF via Playwright. Falls back to static resume on failure.

### 4.5 LinkedIn Recruiter Finder (`src/outreach/browser_finder.py`)

Used by `scripts/outreach.py`. Opens a real Playwright browser with a persistent profile (`data/linkedin_browser_session/`). First run prompts you to log in; session is reused thereafter. Searches LinkedIn people search for `{company} recruiter` and scrapes profile cards. Returns `Recruiter` objects (name, title, LinkedIn URL). Nothing is sent automatically.

### 4.6 Tracker (`src/tracker/`)

**`LocalDB` (`data/applied.sqlite`):**
- `jobs` table — dedup_key (PK), status, match_score, timestamps
- `outreach` table — message log for reference
- Key methods: `already_seen()`, `applied_recently()`, `already_contacted()`

**`GoogleSheets`:** Applications tab (synced by `mark_applied.py`) + Connect Queue tab (synced by `outreach.py`)

**`FollowupTracker`:** Sweeps Applied/Responded/Interview rows by cadence → writes `data/follow_ups.md`

---

## 5. CONFIG (`config/user_config.py`)

```python
# Search
job_title: str = "Software Engineer"
alternative_titles: tuple = ("SDE-1", "SDE-2", ..., "AI Engineer", ...)
salary_min: int = 1_200_000
locations: tuple = ("Mumbai", "Bangalore", "Hyderabad", "Remote")
skills: tuple = (~70 entries)

# Scrape
scrape_on_platforms: tuple = ("adzuna", "apify_linkedin",
                               "greenhouse", "lever", "ashby",
                               "remoteok", "remotive", "hn", "naukri")
naukri_search_enabled: bool = True

# Review queue
use_review_queue: bool = True   # always True now
review_queue_top_n: int = 30

# Legitimacy
legitimacy_check_enabled: bool = True
legitimacy_max_age_days: int = 60
legitimacy_stale_age_days: int = 120
legitimacy_min_description_chars: int = 200

# ATS company lists
greenhouse_companies: tuple = (("Stripe", "stripe"), ...)
lever_companies: tuple = ()
ashby_companies: tuple = (("Notion", "notion"), ...)

# Scoring weights
job_recency_weight: float = 0.2
job_recency_hours_threshold: int = 24
india_location_boost: float = 0.45
min_match_score: int = 40         # = MIN_MATCH_SCORE from .env

# Resume
resume_path: Path = "sameet_sabu_resume.pdf"
use_tailored_resume: bool = True  # used by scripts/generate_resume.py

# LinkedIn outreach pacing (scripts/outreach.py)
linkedin_jitter_min_seconds: int = 30
linkedin_jitter_max_seconds: int = 120
max_linkedin_people_per_company: int = 3
```

---

## 6. ENVIRONMENT (`.env`)

```
# Gemini API (used by scripts/generate_resume.py ScreeningQA)
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash

# Optional scrapers
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
APIFY_API_TOKEN=
APIFY_PER_SOURCE_LIMIT=100

# Google Sheets sync (optional)
GOOGLE_SHEET_ID=

# Settings
MIN_MATCH_SCORE=40
LOG_LEVEL=INFO
```

---

## 7. GOOGLE SHEETS SCHEMA

### Tab 1: `Applications`
Synced by `scripts/mark_applied.py` when you record a manual application.

`Date Applied | Company | Role | Location | Source | Apply URL | Status | Match Score | Notes | ...`

### Tab 2: `Connect Queue`
Synced by `scripts/outreach.py` — people found on LinkedIn for manual connection requests.

`Date | Name | LinkedIn URL | Company | Job Title | Job URL`

### Status enum
`Scraped · Skipped · Applied · Responded · Interview Scheduled · Rejected · Ghosted · Offer`

---

## 8. SCRIPTS

| Command | What it does |
|---------|-------------|
| `python main.py` | Scrape → score → write `data/review_queue.md` + `data/follow_ups.md` |
| `python scripts/mark_applied.py <key>` | Record a manual application (SQLite + Sheets) |
| `python scripts/mark_applied.py <key> --skip` | Permanently dismiss a job |
| `python scripts/generate_resume.py 1 3 5` | Tailor + generate PDFs for queue positions |
| `python scripts/outreach.py 1 3 5` | Find LinkedIn recruiters → `data/linkedin_targets.md` |
| `python scripts/analyze_patterns.py` | Funnel + source ROI + recommendations |
| `python scripts/export_tracker.py` | Export SQLite to CSV/JSON |

---

## 9. ANTI-DETECTION (scripts/outreach.py browser)

| Action | Delay |
|--------|-------|
| Between LinkedIn company searches | 30–120s (configurable jitter) |
| Human-like scroll per results page | 2–4 random scrolls |
| Wait for lazy-loaded subtitles | up to 8s networkidle |

Browser: Playwright persistent context (`data/linkedin_browser_session/`); `playwright-stealth` applied.

---

## 10. TESTING

```powershell
pytest tests/ -v
```

| File | Tests | Covers |
|---|---|---|
| `test_resume_tailor.py` | 18 | Keyword reordering, filename safety, fallbacks |
| `test_multi_source_scrape.py` | — | Cross-source dedup, per-source counts |

---

## 11. PHASE STATUS

```
✓ Scrape + Score + Legitimacy
    ✓ 9 scrapers (Greenhouse, Lever, Ashby, RemoteOK, Remotive, HN,
                  Naukri, Adzuna, Apify LinkedIn)
    ✓ Cross-source dedup
    ✓ MatchScorer (keyword overlap + recency + India boost)
    ✓ LegitimacyChecker (ghost-job heuristics)

✓ Human-in-the-Loop Review Queue
    ✓ ReviewQueue: ranked Markdown with legitimacy tiers
    ✓ FollowupTracker: URGENT/OVERDUE/WAITING/COLD cadence report
    ✓ mark_applied.py: record manual applications
    ✓ generate_resume.py: tailor PDFs for selected positions
    ✓ outreach.py: browser-based LinkedIn recruiter finder

⏳ Pending
    □ Web UI / dashboard
    □ JDAnalyzer (Gemini) wired into scoring pipeline
    □ Gmail inbox watch for response tracking
```

---

*Architecture v5.0 · Python 3.12 · Human-in-the-loop · SQLite*

# JobHunterX — Architecture Reference

**Status:** Phases 1–3b complete · Phase 4 (dashboard) pending
**Stack:** Python 3.12 · Playwright · Gemini on Vertex AI · SQLite · Google Sheets
**Daily limit:** `DAILY_LIMIT` apps (default 15) · 20 outreach messages
**Mode:** Human-speed automation with anti-detection

---

## 1. SYSTEM OVERVIEW

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    JOBHUNTERX — AUTOMATED JOB AGENT                      │
│                                                                          │
│  Scrape (4 sources) → Score → Apply (Naukri) →                          │
│  Find Recruiters → Compose → Approve → Send Email + LinkedIn             │
└──────────────────────────────────────────────────────────────────────────┘
```

Single entrypoint: `python main.py` runs Phase 1 → 2 → 3 → 3b sequentially.

---

## 2. HIGH-LEVEL DESIGN

### 2.1 Pipeline Stages

```
┌────────────────────────────────────────────────────────────────────────┐
│                              PHASE 1                                   │
│  scrape_all()                                                          │
│    • Greenhouse  : boards-api.greenhouse.io/v1/boards/{slug}/jobs      │
│    • Lever       : api.lever.co/v0/postings/{slug}?mode=json           │
│    • HN Hiring   : hn.algolia.com/api/v1/search (3000 comments cached) │
│    • Naukri      : naukri.com/jobapi/v3/search (per title/location)    │
│    • Within-source dedup: source:id                                    │
│    • Cross-source dedup: (company, title) — first source wins          │
│  → filter_and_rank() → MatchScorer (keyword overlap + recency boost)   │
│    → top N jobs by match_score (threshold: MIN_MATCH_SCORE from .env)  │
│  → ScoredJob[]  (analysis=None — Gemini not called in Phase 1)         │
└────────────────────────┬───────────────────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                              PHASE 2                                   │
│  apply_to_jobs(): per ScoredJob (apply_on_platforms=["naukri"] only):  │
│    1. ResumeTailor.generate() → reorder skills by JD keywords          │
│       (analysis=None so keywords=[]; static template order kept)       │
│    2. get_applier("naukri") → NaukriApplier                            │
│    3. applier.apply():                                                 │
│         - Open persistent Playwright profile (data/naukri_profile/)    │
│         - Login to Naukri (cookies cached across runs)                 │
│         - Navigate to job.apply_url                                    │
│         - Detect CAPTCHA → screenshot + console confirm (no polling)   │
│         - Quick Apply: FormFiller per step + ScreeningQA (Gemini)      │
│         - Company Site redirect: mark REDIRECT, skip                   │
│         - Submit → capture confirmation text + screenshot              │
│    4. DailyLimiter: cap at DAILY_LIMIT · gap 5–15min · 10–20min/3rd   │
└────────────────────────┬───────────────────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                              PHASE 3  (email outreach)                 │
│  outreach_phase(): per applied job:                                    │
│    1. RecruiterFinder.find() → up to 3 recruiters per company          │
│         mock          : deterministic dummies (testing / dry-run)      │
│         hunter        : Hunter.io domain search API                    │
│         google_search : Google site:linkedin.com/in → slug → email     │
│                         guess → optional Hunter.io verify (FAANG only) │
│    2. Compose:                                                         │
│         ReferralTemplate (static, includes job link + LTM)             │
│         | ColdEmailComposer (Gemini on Vertex, fallback to referral)   │
│    3. ApprovalEngine.review() → APPROVED | EDITED | REJECTED          │
│    4. EmailSender.send(attachment=static sameet_sabu_resume.pdf)       │
│    5. 90-day cooldown per recruiter email                              │
└────────────────────────┬───────────────────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                              PHASE 3b (LinkedIn outreach)              │
│  linkedin_phase(): per applied job:                                    │
│    1. backend.find_company_people() → up to 3 people                  │
│         mock         : deterministic dummies                           │
│         linkedin_api : GoogleSearchRecruiterFinder (Google search →    │
│                        LinkedIn profiles) → linkedin-api library       │
│    2. is_connection(person)?                                           │
│         YES (DISTANCE_1) → LinkedInDMTemplate → send_dm()             │
│                            api.send_message(body, recipients=[urn])    │
│         NO               → LinkedInInviteTemplate (≤300 chars)         │
│                            → send_connection_request()                 │
│                            api.add_connection(slug, message=note[:300])│
│    3. ApprovalEngine.review() → same gate as email                    │
│    4. Jitter 30–120s between connection requests (safety)             │
│    5. 90-day cooldown keyed on email or linkedin_url                  │
│    6. Both paths log to Outreach tab (channel=linkedin_msg/invite)    │
└────────────────────────┬───────────────────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       PERSISTENT STATE                                 │
│  data/applied.sqlite        — jobs + outreach (email + LinkedIn) tables│
│  output/{company}_{role}.pdf — JD-tailored resumes (Phase 2 apply)    │
│  sameet_sabu_resume.pdf     — static resume attached to outreach email │
│  logs/applications/*.png    — confirmation screenshots                 │
│  Google Sheets:                                                        │
│    Tab 1: Applications  · 20 columns                                   │
│    Tab 2: Outreach      · 16 columns (channel: email/LI_msg/LI_invite) │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow Through Models

```
Job (Pydantic)
    │ id, title, company, location, salary, description, apply_url,
    │ easy_apply, posted_date, source
    ▼
MatchScorer → match_score (int 0–100)
    │ skill overlap + recency boost; no LLM cost
    ▼
ScoredJob = Job + analysis=None
    │ (JDAnalyzer/Gemini is NOT called in the current pipeline)
    │
    ├──► Phase 2: ResumeTailor reorders skills (no-op when analysis=None)
    │             → NaukriApplier.apply(scored)
    │
    └──► Phase 3: For each job → Recruiter[] → OutreachMessage[]
                  (recruiter, job, channel, style, subject, body, status)
```

---

## 3. PROJECT STRUCTURE (actual)

```
JobHunterX/
├── config/
│   ├── user_config.py          # All knobs: titles, skills, salary, limits, flags
│   │                           # greenhouse_companies + lever_companies lists
│   ├── platform_config.py      # API keys + creds (loaded from .env)
│   └── gcp-service-account.json
│
├── src/
│   ├── models.py               # Pydantic: Job, JDAnalysis, ScoredJob,
│   │                           #          Recruiter, OutreachMessage, enums
│   │
│   ├── scraper/                # Phase 1 — all API-based, no browser
│   │   ├── base_scraper.py     # Abstract search(title, location) -> list[Job]
│   │   ├── greenhouse_scraper.py  # boards-api.greenhouse.io — cached per instance
│   │   ├── lever_scraper.py       # api.lever.co — cached per instance
│   │   ├── hn_scraper.py          # Algolia HN — cached per instance (3000 comments)
│   │   ├── naukri_scraper.py      # Public JSON API (curl_cffi Chrome impersonation)
│   │   ├── indeed_scraper.py      # SerpAPI (registered but not in scrape_on_platforms)
│   │   └── scraper_factory.py
│   │
│   ├── analyzer/               # Phase 1
│   │   ├── match_scorer.py     # Lightweight skill-overlap + recency scorer (used)
│   │   └── jd_analyzer.py      # Gemini on Vertex full JD analysis (exists, not wired in)
│   │
│   ├── apply/                  # Phase 2
│   │   ├── base_applier.py     # ApplyStatus, ApplyResult
│   │   ├── naukri_applier.py   # Naukri quick apply (only active applier)
│   │   ├── form_filler.py      # Heuristic field classifier
│   │   ├── screening_qa.py     # Gemini answers free-text screening questions
│   │   ├── captcha_detector.py # Selectors + winsound.Beep alert
│   │   ├── daily_limiter.py    # Max N/day cap
│   │   └── applier_factory.py  # Registry: {"naukri": NaukriApplier}
│   │
│   ├── resume/                 # Phase 2
│   │   ├── resume_tailor.py    # Reorder skills by JD keywords + Playwright PDF
│   │   └── templates/
│   │       ├── resume_template.html  # SKILLS_BLOCK_START/END markers
│   │       └── base_resume.json
│   │
│   ├── outreach/               # Phase 3 + 3b
│   │   ├── recruiter_finder.py     # Mock + Hunter + GoogleSearch finders
│   │   ├── referral_template.py    # Static email + LinkedIn DM + LinkedIn invite
│   │   ├── cold_email_composer.py  # Gemini on Vertex personalized email
│   │   ├── approval_engine.py      # CLI: interactive | auto_approve | auto_reject
│   │   ├── email_sender.py         # DryRunEmailSender + SMTPEmailSender (Gmail)
│   │   ├── orchestrator.py         # Phase 3: email outreach pipeline
│   │   ├── linkedin_outreach.py    # Mock + LinkedInApiOutreach backends
│   │   └── linkedin_orchestrator.py # Phase 3b: LinkedIn DM/invite pipeline
│   │
│   ├── tracker/
│   │   ├── local_db.py         # SQLite: jobs + outreach tables
│   │   ├── google_sheets.py    # Applications + Outreach tabs
│   │   └── schema.py           # SHEET_COLUMNS + OUTREACH_COLUMNS + Status enum
│   │
│   └── utils/
│       ├── logger.py           # loguru
│       ├── retry.py            # tenacity decorator
│       └── human_behavior.py   # Random delays / typing simulation
│
├── data/applied.sqlite          # Auto-created
├── output/*.pdf                 # Tailored resumes per job
├── logs/applications/*.png      # Submission screenshots
│
├── tests/                       # pytest
│   ├── conftest.py
│   ├── test_resume_tailor.py        # 18 tests
│   ├── test_referral_template.py    # 25 tests
│   ├── test_recruiter_finder.py     # 32 tests (Mock + Hunter + GoogleSearch)
│   ├── test_approval_engine.py      # 11 tests
│   ├── test_email_sender.py         # 14 tests
│   ├── test_outreach_orchestrator.py # 10 tests
│   ├── test_linkedin_outreach.py    # 36 tests (Mock + LinkedInApiOutreach)
│   ├── test_captcha_confirm.py      # captcha wait flow
│   └── test_multi_source_scrape.py  # cross-source dedup
│
├── scripts/
│   └── test_phase3_dry_run.py   # Smoke test: MockFinder + AUTO_APPROVE + DryRun
│
├── main.py                      # Single entrypoint
├── sameet_sabu_resume.pdf       # Static resume for outreach attachments
├── requirements.txt
├── .env                         # Not in git
├── SETUP.md                     # Onboarding + runbook
└── job-agent-architecture.{md,html}  # This file
```

---

## 4. MODULE-BY-MODULE LLD

### 4.1 Scrapers (`src/scraper/`)

| Class | Endpoint | Mechanism | Caching |
|---|---|---|---|
| `GreenhouseScraper` | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | httpx GET, public no-auth | All companies fetched once; filtered locally per search() |
| `LeverScraper` | `api.lever.co/v0/postings/{slug}?mode=json` | httpx GET, public no-auth | Same pattern as Greenhouse |
| `HNScraper` | `hn.algolia.com/api/v1/search` | httpx GET, Algolia | Hiring story ID cached; up to 3000 comments cached; search() filters in-memory |
| `NaukriScraper` | `naukri.com/jobapi/v3/search` | curl_cffi Chrome impersonation, RSA nkparam | No cache — one request per (title, location) |
| `IndeedScraper` | SerpAPI `google_jobs` | httpx | Registered but not in `scrape_on_platforms` |

Dedup flow: `_absorb_jobs()` in `main.py` — within-source by `source:id`, cross-source by `(company.lower(), title.lower())` first-source-wins.

**Greenhouse / Lever caching detail:** `_fetch_all()` iterates all configured companies (15 Greenhouse + 7 Lever) on first call, stores jobs in `self._cache`. All subsequent `search(title, location)` calls within the same run filter `self._cache` locally — 28 titles × 4 locations = 112 combinations produce only 1 set of API calls per scraper instance.

### 4.2 Scorer / Analyzer (`src/analyzer/`)

**`MatchScorer` (used):**
- Tokenizes `job.description + job.title` and finds overlap with 120+ candidate skills
- Denominator capped at 15 (typical JD mentions 10–15 skills)
- Recency boost: jobs < 24h old get up to 20% extra (linear decay)
- Returns `int 0–100`

**`JDAnalyzer` (exists, not called in main.py):**
- Uses Gemini on Vertex AI via `google-cloud-aiplatform`
- Would return full `JDAnalysis`: match_score, required_skills, missing_skills, keywords_to_include, should_apply, etc.
- File is complete and tested but not wired into the pipeline; `ScoredJob.analysis` is always `None`

### 4.3 Resume Tailor (`src/resume/resume_tailor.py`)

Reorders `<div class="skill-row">` blocks inside `SKILLS_BLOCK_START`/`END` markers by scoring each skill category against `analysis.keywords_to_include`. Since `analysis` is `None` in the current flow, `keywords=[]` and the template order is preserved. Falls back to static `sameet_sabu_resume.pdf` on Playwright failure.

### 4.4 Application Engine (`src/apply/`)

`apply_to_jobs()` in `main.py`:

1. Only processes `job.source == "naukri"` (sole entry in `apply_on_platforms`)
2. `ResumeTailor.generate()` called but no-ops on ordering (analysis=None)
3. `NaukriApplier.apply(scored)` runs full Playwright flow:
   - Persistent Chrome profile at `data/naukri_profile/` (cookies survive runs)
   - Login check → navigate to job URL → CAPTCHA gate → Apply button detect
   - Quick Apply: `FormFiller` fills each form step; `ScreeningQA` (Gemini) handles unmapped fields
   - Company-site redirect → `ApplyStatus.REDIRECT`
   - Confirmation text scan → `ApplyStatus.SUBMITTED`
4. `DailyLimiter` caps at DAILY_LIMIT; gap 5–15 min; 10–20 min every 3rd app
5. CAPTCHA policy: screenshot → console block — no DOM polling during challenge

### 4.5 Outreach — Email (`src/outreach/orchestrator.py`)

```
recruiter_finder.find(company, max_results=3)
  → for each recruiter:
      if already_contacted(email, within=90 days): skip
      compose:
        REFERRAL → ReferralTemplate.render(person_name, company, role,
                       job_link, current_company="Lucid Motors (LTM)",
                       sender_name, sender_email, sender_phone)
        COLD     → ColdEmailComposer.compose() via Gemini
                   (falls back to ReferralTemplate on failure)
      db.upsert_outreach(draft)
      approval.review(draft)     → APPROVED | EDITED | REJECTED
      if approved/edited:
        sender.send(message, attachment=static sameet_sabu_resume.pdf)
        → SENT | FAILED
      db.upsert_outreach(final)
      sheets.append_outreach(final)
```

**Recruiter Finders:**

| Source | Class | How it works |
|---|---|---|
| `mock` | `MockRecruiterFinder` | Returns hardcoded dummies; synthesizes one for unknown companies |
| `hunter` | `HunterRecruiterFinder` | Hunter.io `/domain-search` API; filters by recruiter/hr/talent titles |
| `google_search` | `GoogleSearchRecruiterFinder` | GET google.com `site:linkedin.com/in "{company}" "software engineer" "India"` → BeautifulSoup → slug → email guesses (`firstname@`, `first.last@`, `flast@`) → optional Hunter.io verify for FAANG (25 free calls/month) |

### 4.5b Outreach — LinkedIn (`src/outreach/linkedin_orchestrator.py`)

```
backend.find_company_people(company, max_results=3)
  → for each person:
      if already_contacted(within=90 days): skip
      is_conn = backend.is_connection(person)

      if NOT is_conn:
          → status = MANUAL_CONNECT (no message sent)
          db.upsert_outreach(manual_connect record)    ← enables 90-day cooldown
          sheets.append_connect_queue(person, job)     ← "Connect Queue" tab:
                                                          Date | Name | LinkedIn URL |
                                                          Company | Job Title | Job URL
          continue  ← no approval prompt, no API call

      if is_conn (1st-degree):
          compose → LinkedInDMTemplate (includes job link + LTM)
          channel = LINKEDIN_MSG
          db.upsert_outreach(draft)
          approval.review(draft)   → APPROVED | EDITED | REJECTED
          if approved/edited:
              send_dm() → api.send_message(body, recipients=[urn])
              → SENT | FAILED
          db.upsert_outreach(final)
          sheets.append_outreach(final)
```

**LinkedIn Backends:**

| Backend | Class | How it works |
|---|---|---|
| `mock` | `MockLinkedInOutreach` | Deterministic; is_connection checks against explicit email/url sets |
| `linkedin_api` | `LinkedInApiOutreach` | `linkedin-api` library (unofficial API); `get_profile(slug)` → `distance.value == "DISTANCE_1"`; `send_message(body, recipients=[urn])` for DMs only |

`find_company_people()` on the `linkedin_api` backend delegates to `GoogleSearchRecruiterFinder`.

**Connection request policy:** Connection requests are never sent automatically. Non-connections are written to the **"Connect Queue"** Google Sheets tab (Name + LinkedIn URL + Company + Job Title + Job URL) for manual follow-up. A `MANUAL_CONNECT` record is also saved to SQLite so the 90-day cooldown prevents re-queuing the same person.

### 4.6 Referral Templates (`src/outreach/referral_template.py`)

| Class | Output | Notes |
|---|---|---|
| `ReferralTemplate` | `ReferralEmail(subject, body)` | Multi-sentence referral email; `.format()` only; 0 LLM cost |
| `LinkedInDMTemplate` | `LinkedInDM(subject, body)` | DM to 1st-degree connections; shorter, includes job link |
| `LinkedInInviteTemplate` | `LinkedInInvite(note)` | ≤300 chars hard-capped; first name only; mentions current company + role |
| `ColdEmailComposer` | `ColdEmail(subject, body)` | Gemini on Vertex; strict JSON output; ≤80 word body; falls back to referral |

### 4.7 Approval Engine (`src/outreach/approval_engine.py`)

- `INTERACTIVE` — CLI `[A]pprove / [E]dit / [R]eject / [S]kip`; Edit opens `$EDITOR` (notepad on Windows)
- `AUTO_APPROVE` — Marks all APPROVED (CI / scheduled runs)
- `AUTO_REJECT` — Marks all REJECTED (dry-run testing)

### 4.8 Email Sender (`src/outreach/email_sender.py`)

| Mode | Class | Notes |
|---|---|---|
| `dry_run` | `DryRunEmailSender` | Logs only; accumulates in `.sent` list |
| `smtp` | `SMTPEmailSender` | Gmail SMTP SSL port 465; requires `GMAIL_APP_PASSWORD` |

### 4.9 Tracker (`src/tracker/`)

**`LocalDB` — `data/applied.sqlite`:**
- `jobs` table — dedup_key (PK), status, match_score, timestamps
- `outreach` table — full message log (channel, style, subject, body, status, sent_at, error)
- Key methods: `already_seen()`, `applied_recently()`, `already_contacted()`, `outreach_count_today()`

**`GoogleSheets`:**
- Tab 1 `Applications` — 20 columns
- Tab 2 `Outreach` — 16 columns (channel field distinguishes email / linkedin_msg / linkedin_invite)
- OAuth user auth (no service account needed)

---

## 5. CONFIG (`config/user_config.py`)

```python
@dataclass(frozen=True)
class UserConfig:
    # Search
    job_title: str = "Software Engineer"
    alternative_titles: tuple = ("SDE-1", "SDE-2", ..., "Backend Engineer", ...)
    salary_min: int = 1_200_000
    salary_max: int = 6_000_000
    locations: tuple = ("Mumbai", "Bangalore", "Hyderabad", "Remote")
    experience_years: int = 3
    skills: tuple = (~120 entries: Python, FastAPI, React, AWS, GCP, …)

    # Phase 1 — Scrape
    scrape_on_platforms: tuple = ("greenhouse", "lever", "hn", "naukri")
    apply_on_platforms: tuple = ("naukri",)   # platforms where we auto-submit

    # Greenhouse company list — (display_name, board_slug) pairs
    greenhouse_companies: tuple = (
        ("Stripe", "stripe"), ("Airbnb", "airbnb"), ("Anthropic", "anthropic"), ...
    )
    # Lever company list — (display_name, board_slug) pairs
    lever_companies: tuple = (
        ("Netlify", "netlify"), ("Intercom", "intercom"), ("Linear", "linear"), ...
    )

    # Phase 1 — Scoring
    job_recency_weight: float = 0.2           # 20% boost for fresh jobs
    job_recency_hours_threshold: int = 24
    min_match_score: int = 40                 # = MIN_MATCH_SCORE from .env

    # Phase 2 — Apply
    daily_application_limit: int = 15         # = DAILY_LIMIT from .env
    apply_gap_min_seconds: int = 300          # 5 min
    apply_gap_max_seconds: int = 900          # 15 min
    apply_long_break_every: int = 3
    apply_long_break_min_seconds: int = 600
    apply_long_break_max_seconds: int = 1200

    # Phase 2 — Resume
    resume_path: Path = "sameet_sabu_resume.pdf"   # static resume for outreach
    use_tailored_resume: bool = True                # reorder skills per job (Phase 2)

    # Phase 3 — Email Outreach
    outreach_enabled: bool = True
    recruiter_finder_source: str = "mock"       # 'mock' | 'hunter' | 'google_search'
    email_style: str = "referral"               # 'referral' | 'cold'
    email_sender_mode: str = "dry_run"          # 'dry_run' | 'smtp'
    approval_mode: str = "interactive"          # interactive | auto_approve | auto_reject
    daily_outreach_limit: int = 20
    outreach_cooldown_days: int = 90
    attach_resume_to_outreach: bool = True
    max_recruiters_per_company: int = 3

    # Phase 3b — LinkedIn Outreach
    linkedin_outreach_enabled: bool = True
    linkedin_outreach_backend: str = "mock"     # 'mock' | 'linkedin_api'
    max_linkedin_people_per_company: int = 3
    linkedin_jitter_min_seconds: int = 30       # safety delay between connection requests
    linkedin_jitter_max_seconds: int = 120
```

---

## 6. ENVIRONMENT (`.env`)

```
# Vertex AI (Gemini — used in ScreeningQA + ColdEmailComposer)
GOOGLE_CLOUD_PROJECT=...
GOOGLE_CLOUD_REGION=us-central1
GEMINI_MODEL=gemini-2.0-flash-001

# Recruiter finding (optional)
HUNTER_API_KEY=        # Phase 3 recruiter finding + FAANG email verify

# Apply credentials (Phase 2)
NAUKRI_EMAIL=
NAUKRI_PASSWORD=

# LinkedIn outreach (Phase 3b — only if linkedin_outreach_backend=linkedin_api)
LINKEDIN_EMAIL=
LINKEDIN_PASSWORD=

# Email send (Phase 3 — only if email_sender_mode=smtp)
GMAIL_SENDER_EMAIL=
GMAIL_APP_PASSWORD=

# Tracking
GOOGLE_SHEET_ID=

# Settings
DAILY_LIMIT=15
MIN_MATCH_SCORE=40
LOG_LEVEL=INFO
```

---

## 7. GOOGLE SHEETS SCHEMA

### Tab 1: `Applications` (20 columns — see `src/tracker/schema.py:SHEET_COLUMNS`)

`Date Applied | Company | Role | Salary Offered | Location | Source | Apply URL | Status | Match Score (%) | Missing Skills | Resume Used | Recruiters Found | Recruiter Emails | Recruiter LinkedIn | LinkedIn Msg Sent | Email Sent | Referral Status | Response Received | Interview Date | Notes`

### Tab 2: `Outreach` (16 columns — see `src/tracker/schema.py:OUTREACH_COLUMNS`)

`Date | Recruiter | Title | Company | Email | LinkedIn | Source | Channel | Style | Job Title | Subject | Body Preview | Status | Message Approved | Sent At | Error`

### Tab 3: `Connect Queue` (6 columns — see `src/tracker/schema.py:CONNECT_QUEUE_COLUMNS`)

`Date | Name | LinkedIn URL | Company | Job Title | Job URL`

People surfaced by Phase 3b who are not 1st-degree connections. Open this tab, visit their LinkedIn profile, and send a connection request manually.

### Status enum
`Scraped · Skipped · Applied · Recruiter Found · Responded · Interview Scheduled · Rejected · Ghosted · Offer`

### OutreachStatus enum
`drafted · approved · edited · rejected · sent · failed`

---

## 8. ANTI-DETECTION & PACING

| Action | Delay |
|---|---|
| Between keystrokes (typeText) | 50–150ms (Gaussian) |
| After click | 500ms–2s |
| Reading JD before apply | 2–5s |
| Between form fields | 1–4s |
| Between applications | 5–15 min |
| Long break every 3rd application | 10–20 min |
| Between LinkedIn connection requests | 30–120s (jitter) |

Browser uses Playwright with persistent context (cookies survive runs); Naukri applier uses `playwright-stealth` to mask `navigator.webdriver`.

**CAPTCHA policy:** When detected, one screenshot is saved and the bot goes completely idle — no further `page.*` calls (DOM probing during a challenge compounds the platform's trust-score hit). A console `input()` prompt blocks until the human confirms the challenge is solved. Then the bot resumes with human-speed pacing. On timeout (30 min), `CaptchaDetected` is raised and the run stops cleanly.

---

## 9. TESTING

Run all: `pytest tests/ -v`

| File | Tests | Covers |
|---|---|---|
| `test_resume_tailor.py` | 18 | Keyword reordering, filename safety, fallbacks, perf |
| `test_referral_template.py` | 25 | Email + DM + invite template rendering, edge cases |
| `test_recruiter_finder.py` | 32 | Mock + Hunter + GoogleSearch: slug parsing, email guesses, domain guess, URL extraction, Hunter verify, factory |
| `test_approval_engine.py` | 11 | Interactive prompts, auto modes, render output |
| `test_email_sender.py` | 14 | DryRun, SMTP config validation, factory |
| `test_outreach_orchestrator.py` | 10 | End-to-end pipeline with stubs, cooldown, daily limit |
| `test_linkedin_outreach.py` | 36 | MockBackend + LinkedInApiOutreach: slug extraction, is_connection, send_dm, send_connection_request, find_people |
| `test_captcha_confirm.py` | — | Console-confirm flow, timeout → CaptchaDetected |
| `test_multi_source_scrape.py` | — | Cross-source dedup, per-source counts |

`scripts/test_phase3_dry_run.py` — full Phase 3 smoke test with MockFinder + AUTO_APPROVE + DryRunEmailSender.

---

## 10. PHASE STATUS

```
✓ Phase 1 — Scrape · Score
    ✓ GreenhouseScraper  (boards-api.greenhouse.io, 15 companies, cached)
    ✓ LeverScraper       (api.lever.co, 7 companies, cached)
    ✓ HNScraper          (Algolia, 3000 comments cached per run)
    ✓ NaukriScraper      (curl_cffi Chrome impersonation + RSA nkparam)
    ✓ Cross-source dedup by (company, title) — first source wins
    ✓ MatchScorer (keyword overlap + recency boost, no LLM cost)
    ✓ LocalDB + GoogleSheets

    ⚠ JDAnalyzer (Gemini) exists but NOT called in main.py;
      ScoredJob.analysis is always None

✓ Phase 2 — Apply Engine
    ✓ ResumeTailor (keyword-reorder + Playwright PDF)
      — no-ops on ordering when analysis=None
    ✓ NaukriApplier (Quick Apply — only active applier)
    ✓ FormFiller + ScreeningQA (Gemini)
    ✓ DailyLimiter + human pacing
    ✓ CAPTCHA: screenshot → console confirm → resume (no DOM polling)
    ✗ LinkedIn applier removed (no LinkedIn job links in pipeline)

✓ Phase 3 — Email Outreach + Approval
    ✓ MockRecruiterFinder (dummies)
    ✓ HunterRecruiterFinder (Hunter.io domain search)
    ✓ GoogleSearchRecruiterFinder (Google → LinkedIn slugs → email guesses → Hunter verify)
    ✓ ReferralTemplate (static email, includes job link + LTM)
    ✓ ColdEmailComposer (Gemini on Vertex, falls back to referral)
    ✓ ApprovalEngine (interactive + auto modes)
    ✓ EmailSender (DryRun + SMTP) — attaches static sameet_sabu_resume.pdf
    ✓ OutreachOrchestrator + LocalDB.outreach + GoogleSheets.Outreach tab

✓ Phase 3b — LinkedIn Outreach
    ✓ MockLinkedInOutreach (deterministic, for tests + dry-run)
    ✓ LinkedInApiOutreach (linkedin-api library, unofficial API)
         is_connection: get_profile(slug) → distance.value == "DISTANCE_1"
         send_dm: send_message(body, recipients=[urn])  ← 1st-degree only
    ✓ find_company_people: delegates to GoogleSearchRecruiterFinder
    ✓ 1st-degree connection → DM via LinkedInDMTemplate → approval → send
    ✓ Not connected → "Connect Queue" Google Sheets tab (manual follow-up)
         no connection request sent automatically
         MANUAL_CONNECT status in SQLite for 90-day cooldown
    ✓ LinkedInDMTemplate (existing connection, includes job link + LTM)
    ✓ LinkedInOutreachOrchestrator (approval gate + tracker writes)

⏳ Phase 4 — Dashboard + Polish (pending)
    □ Web UI for live monitoring
    □ APScheduler cron runs
    □ JDAnalyzer (Gemini) wired back into main.py pipeline
    □ Apollo.io recruiter finder adapter
    □ Response tracking (Gmail inbox watch)
```

---

## 11. RISKS & MITIGATIONS

| Risk | Mitigation |
|---|---|
| Naukri IP block | curl_cffi Chrome impersonation; rate limiting via DailyLimiter |
| Google CAPTCHA on recruiter search | GoogleSearchRecruiterFinder detects and returns empty; reduce frequency |
| LinkedIn account block (outreach) | Only DMs to existing connections are sent automatically; connection requests are never auto-sent (queued for manual action instead) |
| linkedin-api unofficial API breaks | Mock backend fallback; connection requests are manual so a library outage only affects DMs |
| Gemini hallucinates skills | ResumeTailor never adds skills (only reorders); strict JSON schema for ColdEmail |
| Sheets API quota | LocalDB is primary; Sheets is async sync layer |
| Hunter.io quota (25/month free) | FAANG-only verification; skips for all other companies |
| CAPTCHA on Naukri apply | Screenshot → console confirm → resume (no DOM polling) |
| Already applied to job | `LocalDB.already_seen()` + `applied_recently()` checks |
| Already contacted recruiter | `LocalDB.already_contacted()` 90-day cooldown |
| SMTP send failure | `FAILED` status logged to DB + Sheets with error field |

---

## 12. COSTS (estimated)

| Item | Free tier | Paid |
|---|---|---|
| Gemini on Vertex (ScreeningQA + ColdEmailComposer) | — | ~$0.05–0.20/day |
| Hunter.io (FAANG email verify only) | 25/mo | $49/mo (500) |
| Gmail SMTP | $0 | $0 |
| Google Sheets | $0 | $0 |
| Greenhouse / Lever / HN APIs | $0 (public) | $0 |

**Minimum monthly:** ~$1–6 (Vertex only, cold email off) · `email_style="referral"` + `recruiter_finder_source="mock"` = $0 incremental Phase 3 cost.

---

*Architecture v3.0 · Python 3.12 · Phases 1–3b complete*

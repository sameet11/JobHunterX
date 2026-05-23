# JobHunterX Setup & Runbook

## Status

**Phase 1** ✓ Complete — Scrape (7 sources: Greenhouse, Lever, **Ashby**, **RemoteOK**, **Remotive**, HN, Naukri) → Score → Filter → **Legitimacy check (ghost-job detection)**
**Phase 2** ✓ Complete — **Human-in-the-loop review queue** (default) OR legacy auto-apply (opt-in)
**Phase 3** ✓ Complete — Email Outreach + Approval (runs only for jobs you manually marked Applied)
**Phase 3b** ✓ Complete — LinkedIn DM / Connection-request Outreach
**Follow-up tracker** ✓ Sweeps Applied/Responded/Interview jobs by cadence
**Pattern analyzer** ✓ `python scripts/analyze_patterns.py` for funnel & ROI insights

---

## Human-in-the-Loop Workflow (Default)

JobHunterX no longer auto-submits applications by default. The pipeline now:

1. **Scrapes** 7 sources for jobs matching your titles + locations
2. **Scores** each job (skill overlap + recency boost)
3. **Flags ghost jobs** via legitimacy heuristics (age, repost detection, vague JDs)
4. **Writes a ranked review queue** to `data/review_queue.md` — you open it, pick jobs to apply to, and **submit manually on the company site**
5. After applying, run `python scripts/mark_applied.py <dedup_key>` to record it
6. **Outreach (Phase 3)** runs only for jobs you've manually marked Applied — never for raw scraped jobs

**Why this changed:** auto-submission on Naukri introduced CAPTCHA breakage, ban risk, and false-positive "wrong job applied" errors. Drafting + approval mirrors how serious candidates actually job hunt.

**Daily cycle:**
```powershell
python main.py
# → writes data/review_queue.md (top 30 jobs, ghost flags, apply URLs)
# → writes data/follow_ups.md (URGENT/OVERDUE jobs you applied to earlier)
# → runs outreach for previously-Applied jobs not yet contacted
```

Then open `data/review_queue.md`, manually apply to the ones you like, and:
```powershell
python scripts/mark_applied.py greenhouse:1234567   # mark applied
python scripts/mark_applied.py remotive:88991 --skip  # skip permanently
```

**To revert to legacy auto-apply** (not recommended — only if you want Naukri bot back):
```python
# config/user_config.py
use_review_queue: bool = False
naukri_apply_enabled: bool = True
```

---

## Running with Docker

### Option 1: Run Full Application + Database via Docker (Recommended)

**Prerequisites:** Docker and Docker Compose installed

```powershell
# Start all services (App + PostgreSQL + pgAdmin)
docker-compose up -d

# Verify services are running
docker-compose ps

# View application logs
docker-compose logs -f app

# Stop all services
docker-compose down
```

**Access points:**
- **JobHunterX App**: Runs in container `jobhunterx-app` (logs via `docker-compose logs -f app`)
- **PostgreSQL**: `localhost:5432` (user: `jobhunter`, password: `jobhunter_dev_password`)
- **pgAdmin**: http://localhost:5050 (email: `admin@jobhunterx.local`, password: `admin_password`)

**Configuration via .env:**
```env
# Required for Vertex AI (ScreeningQA + cold email)
GOOGLE_CLOUD_PROJECT=your-gcp-project

# Required for Phase 2 apply
NAUKRI_EMAIL=your-naukri-email
NAUKRI_PASSWORD=your-naukri-password

# Required for Phase 3b LinkedIn outreach (only if linkedin_outreach_backend=linkedin_api)
LINKEDIN_EMAIL=your-email
LINKEDIN_PASSWORD=your-password

# Optional
GOOGLE_SHEET_ID=...
HUNTER_API_KEY=...    # Phase 3 recruiter finding + FAANG email verify
GMAIL_APP_PASSWORD=...  # Phase 3 email sending
```

**Stop and clean up:**
```powershell
docker-compose down          # stop services
docker-compose down -v       # stop + remove volumes (clears all data)
```

---

### Option 2: Database Only (PostgreSQL via Docker)

```powershell
docker-compose up -d postgres pgadmin
```

Then add to `.env`:
```env
DATABASE_URL=postgresql://jobhunter:jobhunter_dev_password@localhost:5432/jobhunterx
```

Schema (jobs, outreach tables) auto-initializes via `scripts/init_db.sql`.

---

### Option 3: SQLite (Default, No Docker)

```powershell
pip install -r requirements.txt
python main.py
```

SQLite at `data/applied.sqlite` is auto-created on first run.

---

## Quick Start

### Option A: Run via Docker

```powershell
# 1. Authenticate with Google Cloud (ADC — once)
gcloud auth application-default login

# 2. Copy and fill in .env
cp .env.example .env

# 3. Start all services
docker-compose up -d

# 4. Watch logs
docker-compose logs -f app

# 5. Stop
docker-compose down
```

---

### Option B: Run Locally (Python venv)

#### 1. Create Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# If execution policy error: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
python --version
```

#### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

#### 3. Configure GCP
```powershell
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT_ID
```

#### 4. Edit `.env`
```env
# REQUIRED for Phase 2 (ScreeningQA uses Gemini):
GOOGLE_CLOUD_PROJECT=your-gcp-project
GOOGLE_CLOUD_REGION=us-central1
GEMINI_MODEL=gemini-2.0-flash-001

# REQUIRED for Phase 2 (Naukri Apply):
NAUKRI_EMAIL=your-naukri-email@example.com
NAUKRI_PASSWORD=your-naukri-password

# OPTIONAL — Phase 3b LinkedIn outreach (real mode):
LINKEDIN_EMAIL=your-linkedin-email@example.com
LINKEDIN_PASSWORD=your-linkedin-password

# OPTIONAL:
GOOGLE_SHEET_ID=...           # Sync results to Google Sheets
HUNTER_API_KEY=...            # Recruiter finding + FAANG email verify
GMAIL_APP_PASSWORD=...        # Phase 3 real email sending
```

#### 4b. Google Sheets Setup (Optional)

1. Go to [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials)
2. Create **OAuth 2.0 Desktop Application** → download JSON → save as `credentials.json` in repo root
3. Get Sheet ID from `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`
4. Add `GOOGLE_SHEET_ID={SHEET_ID}` to `.env`
5. On first run, a browser OAuth prompt will appear — grant access; token saved to `data/google_sheets_token.json`

#### 5. Customize `config/user_config.py`

```python
# Personal Info (ApplicantProfile)
full_name: str = "Your Name"
email: str = "your-email@example.com"
phone: str = "+91-0000000000"
linkedin_url: str = "https://www.linkedin.com/in/your-handle"
current_company: str = "Your Company"
current_role: str = "Your Role"
expected_ctc_lpa: int = 60
current_ctc_lpa: int = 25

# Job Search
job_title: str = "Software Engineer"
locations: tuple = ("Mumbai", "Bangalore", "Remote")
skills: tuple = (...)                  # 120+ pre-configured

# Automation
daily_application_limit: int = 15     # Max applications per day
apply_on_platforms: tuple = ("naukri",)

# Target companies for API scrapers
greenhouse_companies: tuple = (
    ("Stripe", "stripe"), ("Airbnb", "airbnb"), ...
)  # Verify slugs at boards.greenhouse.io/{slug}

lever_companies: tuple = (
    ("Netlify", "netlify"), ("Intercom", "intercom"), ...
)  # Verify slugs at jobs.lever.co/{slug}
```

`config/user_config.py` is in `.gitignore` — stays private.

#### 6. Run
```powershell
python main.py
```

---

## Resume Setup & Configuration

### Where to Place Your Resume

1. **Create/update resume PDF**
   - File name: `sameet_sabu_resume.pdf` (or customize in config)
   - Location: **Project root** (same directory as `main.py`)
   ```
   JobHunterX/
   ├── sameet_sabu_resume.pdf    ← Place your resume here
   ├── main.py
   ├── config/
   └── ...
   ```

2. **Update resume path in `config/user_config.py`** (if using different filename):
   ```python
   resume_path: Path = field(
       default_factory=lambda: Path(__file__).resolve().parents[1] / "your_resume_name.pdf"
   )
   ```

### Resume Usage in Pipeline

**Phase 2 (Job Applications):**
- Resume attached to every Naukri application submission
- By default, skill categories are **reordered by JD keyword match** before each application (keyword reordering, no content changes)
- Control with:
  ```python
  use_tailored_resume: bool = True   # Enable tailoring (reorder skills)
  # Set to False to always send unmodified static resume
  ```

**Phase 3 (Recruiter Email Outreach):**
- Always uses the **static resume** (never tailored)
- Attached to referral + cold emails if `attach_resume_to_outreach: bool = True`

**Troubleshooting:**
- If resume file missing: app logs warning, continues (Phase 2 may fail on submission)
- If tailoring fails: automatically falls back to static `resume_path`
- Tailored PDFs saved to `output/{company}_{role}.pdf` (Phase 2 only)

---

## Gmail Setup for Phase 3 Email Outreach

### Prerequisites

Phase 3 email sending requires:
- **Gmail account** with App Passwords enabled
- **2-factor authentication enabled** on the Gmail account (required for App Passwords)

### Step-by-Step Setup

#### 1. Enable 2-Factor Authentication (if not already done)
1. Go to https://myaccount.google.com/security
2. Click **2-Step Verification**
3. Follow prompts to enable 2FA on your Gmail account

#### 2. Generate Gmail App Password

1. Go to https://myaccount.google.com/apppasswords
2. Select **App**: `Mail`
3. Select **Device**: `Windows Computer` (or your device)
4. Click **Generate**
5. Google displays a **16-character password** (e.g., `abcd efgh ijkl mnop`)
6. **Copy this password** — you'll only see it once

#### 3. Add to `.env` File

```env
# Gmail sender configuration
GMAIL_SENDER_EMAIL=your-email@gmail.com        # Your Gmail address (from/reply-to)
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop          # 16-char app password (no spaces needed)
```

#### 4. Enable Email Sending in `config/user_config.py`

```python
# Phase 3: Email Outreach
outreach_enabled: bool = True                   # Enable Phase 3
email_sender_mode: str = "smtp"                 # "smtp" = real send | "dry_run" = test only
recruiter_finder_source: str = "mock"           # "mock" | "hunter" | "google_search"
email_style: str = "referral"                   # "referral" (static) | "cold" (AI)
approval_mode: str = "interactive"              # "interactive" | "auto_approve" | "auto_reject"
daily_outreach_limit: int = 20                  # Max emails + LinkedIn DMs per day
attach_resume_to_outreach: bool = True          # Attach resume to recruiter emails
```

### Email Sending Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| **dry_run** | Logs what would be sent (no real emails) | Testing, development |
| **smtp** | Sends real emails via Gmail SMTP | Production |

**To test without sending real emails:**
```python
email_sender_mode: str = "dry_run"  # Safe for testing
```

Then check logs to see what would be sent.

### Email Approval Workflow

Before any email is sent, the `ApprovalEngine` gates it based on `approval_mode`:

```python
approval_mode: str = "interactive"   # [A]pprove / [E]dit / [R]eject / [S]kip in console
# OR
approval_mode: str = "auto_approve"  # Skip approval, send all
# OR
approval_mode: str = "auto_reject"   # Dry-run only (never send)
```

### Phase 3 Flow (Email Outreach)

```
For each applied job (Phase 2):
  1. Find recruiters (mock / Hunter.io / Google Search)
  2. Compose email (referral template / Gemini cold email)
  3. ApprovalEngine.review():
     - interactive: CLI prompt [A/E/R/S]
     - auto_approve: skip prompt, approve
     - auto_reject: skip prompt, reject (dry-run)
  4. If approved + email_sender_mode="smtp":
     → Send via Gmail SMTP (GMAIL_SENDER_EMAIL + GMAIL_APP_PASSWORD)
  5. Record to SQLite + Google Sheets
```

### Troubleshooting Email Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `GMAIL_SENDER_EMAIL not set` | Missing env var | Add to `.env`: `GMAIL_SENDER_EMAIL=your-email@gmail.com` |
| `GMAIL_APP_PASSWORD not set` | Missing env var | Go to myaccount.google.com/apppasswords, generate 16-char password, add to `.env` |
| `SMTP authentication failed` | Wrong password or email | Verify `.env` values match Gmail account; regenerate app password if unsure |
| `2-factor authentication required` | App password not enabled | Enable 2FA first: myaccount.google.com/security |
| No emails sent in production | `email_sender_mode` still set to `"dry_run"` | Change to `"smtp"` in `config/user_config.py` |
| "Recruiter has no email" | Finder returned invalid email | Check `recruiter_finder_source` (mock always works) |
| `approval_mode interactive but no TTY` | Non-interactive environment (Docker, CI/CD) | Use `"auto_approve"` or `"auto_reject"` instead |

### Email Outreach Optional Dependencies

To use advanced recruiter finding:

```python
recruiter_finder_source: str = "mock"           # Always available, deterministic
# OR
recruiter_finder_source: str = "hunter"         # Requires HUNTER_API_KEY in .env
# OR  
recruiter_finder_source: str = "google_search"  # Uses Google Search (free, but slower)
```

---

## What Happens Step by Step

### Phase 1: Scrape → Score → Filter (5–10 min)

**Step 1 — Scrape** (`scrape_all()`):

| Source | API | How |
|--------|-----|-----|
| **Greenhouse** | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | Fetches configured `greenhouse_companies` once → cached. Pruned to verified-working slugs. |
| **Lever** | `api.lever.co/v0/postings/{slug}?mode=json` | Empty by default (May 2026: most companies migrated to Ashby). Add verified slugs manually. |
| **Ashby** | `api.ashbyhq.com/posting-api/job-board/{slug}` | New. Picks up Notion, Linear, Vercel, Replit, Mercury, PostHog, Modal, Hex (and any other Ashby-hosted company you add). |
| **RemoteOK** | `remoteok.com/api` | New. **No auth, no key.** Single fetch returns ~300 remote jobs, all date-stamped. |
| **Remotive** | `remotive.com/api/remote-jobs?category=software-dev` | New. **No auth, no key.** Returns ~500 software-engineering remote jobs with `publication_date`. |
| **HN Who's Hiring** | `hn.algolia.com/api/v1/search_by_date` | **Fixed** — restricts to stories created in last 45 days + sorts by date, so we always grab the current month's thread (was picking the 2020 thread). |
| **Naukri** | `naukri.com/jobapi/v3/search` | Gated by `naukri_search_enabled` (default False). Chrome TLS fingerprint + RSA nkparam token. |

Deduplication: within-source by `source:id`; cross-source by `(company, title)` — first source wins.

**Step 2 — Score** (`filter_and_rank()`):
- Skip companies in `skip_companies` list
- Skip jobs already acted on in SQLite (status ≠ Scraped)
- Skip jobs applied to within `skip_if_applied_in_days` (180 days)
- `MatchScorer`: skill-keyword overlap (denominator capped at 15) + up to 20% recency boost for jobs < 24h old
- Drop jobs below `min_match_score`
- Write passing jobs to SQLite; return sorted descending by score

**Output:**
- `data/applied.sqlite` — jobs with `status=Scraped` and `match_score`
- `logs/` — scrape + filter breakdown

---

### Phase 2 (Review Queue Mode — Default)

For each scored job in the top-N (default 30), the **`ReviewQueue`** module:

1. **Legitimacy check** (`LegitimacyChecker`, career-ops Block G inspired):
   - Posting age (`legitimacy_max_age_days` / `legitimacy_stale_age_days`)
   - JD specificity (`legitimacy_min_description_chars`)
   - Repost detection (same company+title seen recently in DB)
   - Title red flags (`talent pool`, `general application`, `evergreen`...)
   - Returns tier: `high_confidence` ✓ | `caution` ⚠ | `suspicious` 🚫
2. **Writes `data/review_queue.md`** — ranked markdown with company, title, score, location, age, apply URL, flags, dedup_key, JD preview. High-confidence jobs surface first; suspicious ones sink to the bottom but stay visible.
3. **You manually apply** to the ones you like (on the actual company site).
4. After applying, you mark it in the tracker:
   ```powershell
   python scripts/mark_applied.py <dedup_key>
   python scripts/mark_applied.py <dedup_key> --skip   # dismiss without applying
   ```

**No PDF resume tailoring or browser automation** runs in this mode — the apply page is yours to open.

---

### Phase 2 (Legacy Auto-Apply Mode — Opt-In)

Enable with `use_review_queue=False` + `naukri_apply_enabled=True` in `config/user_config.py`. Then for each scored Naukri job:

1. **Resume Tailor** generates a PDF (reorders skill categories by JD keywords). Falls back to static `sameet_sabu_resume.pdf` on error.
2. **NaukriApplier** (Playwright, headless=False):
   - Opens persistent Chrome profile at `data/naukri_profile/`
   - Logs in if not already (credentials from `.env`)
   - Navigates to `job.apply_url`
   - CAPTCHA check → screenshot + console confirm prompt
   - Quick Apply button → form loop with `FormFiller` + `ScreeningQA` (Gemini on Vertex)
3. Update SQLite to `Applied` + sync to Google Sheets
4. Sleep 5–15 min between apps; 10–20 min every 3rd

---

### Follow-up Tracker

Runs automatically as part of `main.py` (review-queue mode). Sweeps every Applied / Responded / Interview job and classifies by cadence:

| Status | Overdue at | Urgent at | Cold at |
|--------|-----------|----------|---------|
| Applied | 7d | 14d | 30d |
| Responded | 3d | 7d | 21d |
| Interview | 1d | 3d | 14d |

Writes `data/follow_ups.md` grouped by URGENT / OVERDUE / WAITING / COLD with company, role, days-since, and apply URL.

---

### Pattern Analyzer

Run standalone any time after you have ≥10 applications:

```powershell
python scripts/analyze_patterns.py
# Or JSON for scripting:
python scripts/analyze_patterns.py --json
```

Outputs:
- **Funnel**: counts at each stage (Scraped → Applied → Responded → Interview → Offer)
- **Source ROI**: scraped → applied → responded_or_better per source (which sources are worth your time)
- **Score by Outcome**: median/min/max match score per outcome (so you can tune `min_match_score`)
- **Recommendations**: concrete suggestions (e.g., "Source X produced 50 jobs but 0 applies — consider removing it")

**CAPTCHA handling:** Screenshot saved → Windows beep → `input()` blocks the bot. No DOM interaction during challenge. Resume only after you press Enter to confirm it's solved.

**Output:**
- `output/{company}_{role}.pdf` — tailored resumes
- `logs/applications/*.png` — submission screenshots
- `data/applied.sqlite` — status updated to `Applied`

---

### Phase 3: Email Outreach (per applied job)

1. `RecruiterFinder.find(company, max_results=3)` — source controlled by `recruiter_finder_source`:
   - `"mock"` — deterministic dummies (no API)
   - `"hunter"` — Hunter.io domain search (requires `HUNTER_API_KEY`)
   - `"google_search"` — Google `site:linkedin.com/in` → slug → 3 email guesses → optional Hunter.io verify for FAANG
2. For each recruiter (skip if contacted within `outreach_cooldown_days`):
3. Compose email:
   - `"referral"` — static `ReferralTemplate` (0 LLM cost, <10ms)
   - `"cold"` — Gemini on Vertex via `ColdEmailComposer` (falls back to referral on failure)
4. `ApprovalEngine.review()`:
   - `"interactive"` — CLI prompt `[A]pprove / [E]dit / [R]eject / [S]kip`
   - `"auto_approve"` — skip prompt, mark APPROVED
   - `"auto_reject"` — skip prompt, mark REJECTED (dry-run)
5. If approved: `EmailSender.send()` with static `sameet_sabu_resume.pdf` attached:
   - `"dry_run"` — logs only, no real send
   - `"smtp"` — Gmail SMTP SSL (requires `GMAIL_APP_PASSWORD`)
6. Record to SQLite `outreach` table + Google Sheets Outreach tab

---

### Phase 3b: LinkedIn Outreach (per applied job)

Runs after email outreach if `linkedin_outreach_enabled=True` and daily budget remains.

Backend controlled by `linkedin_outreach_backend`:
- `"mock"` — deterministic, no credentials needed (default, safe for testing)
- `"linkedin_api"` — real LinkedIn via `linkedin-api` library (requires `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` in `.env`)

For each job → up to `max_linkedin_people_per_company` (default 3) people:

1. `find_company_people()`:
   - mock: returns dummy recruiters
   - linkedin_api: runs `GoogleSearchRecruiterFinder` (Google search → LinkedIn profiles)
2. Check `is_connection()`:
   - mock: checks against explicit connection_emails/urls sets
   - linkedin_api: `api.get_profile(slug)` → `distance.value == "DISTANCE_1"`
3. If 1st-degree connection → `LinkedInDMTemplate` → `send_dm()` (sends via `api.send_message()`)
4. If not connected → `LinkedInInviteTemplate` (≤300 chars) → `send_connection_request()` (via `api.add_connection()`)
5. Same `ApprovalEngine` gate before sending
6. Safety jitter 30–120s between connection requests
7. 90-day cooldown per person (keyed on email or linkedin_url)

---

## Configuration Reference (New)

```python
# config/user_config.py

# Sources to scrape (Phase 1)
scrape_on_platforms: tuple[str, ...] = (
    "greenhouse", "lever", "ashby", "remoteok", "remotive", "hn", "naukri",
)

# Toggle Naukri (off by default — ban risk)
naukri_search_enabled: bool = False    # include Naukri in scraping
naukri_apply_enabled:  bool = False    # legacy auto-apply (ignored if use_review_queue=True)

# Human-in-the-loop apply (default — bot drafts, you submit)
use_review_queue:    bool = True
review_queue_top_n:  int  = 30        # how many top-ranked jobs to surface

# Ghost-job detection
legitimacy_check_enabled:           bool = True
legitimacy_max_age_days:            int  = 60     # older → caution
legitimacy_stale_age_days:          int  = 120    # older → suspicious
legitimacy_min_description_chars:   int  = 200    # vague JDs → caution

# Per-ATS company lists (slugs only — verify at the corresponding board URL)
greenhouse_companies: tuple[tuple[str, str], ...] = (...)   # boards.greenhouse.io/{slug}
lever_companies:      tuple[tuple[str, str], ...] = ()      # jobs.lever.co/{slug}
ashby_companies:      tuple[tuple[str, str], ...] = (...)   # jobs.ashbyhq.com/{slug}
```

### Verifying ATS Slugs

When adding a company, verify the slug by opening the public board URL:

- Greenhouse: `https://boards.greenhouse.io/{slug}` → should show their job listings
- Lever: `https://jobs.lever.co/{slug}` → should show their job listings
- Ashby: `https://jobs.ashbyhq.com/{slug}` → should show their job listings

If the URL 404s, that company isn't on that ATS — try the other two.

---

## Skip Phase 2 Entirely (Scrape + Score Only)

```python
# In config/user_config.py:
use_review_queue: bool = False     # disable review queue
apply_on_platforms: tuple[str, ...] = ()  # disable legacy auto-apply
```

---

## Testing

### Run All Tests
```powershell
pytest tests/ -v
```

### Run Phase 3 Tests
```powershell
pytest tests/test_recruiter_finder.py tests/test_approval_engine.py tests/test_email_sender.py tests/test_outreach_orchestrator.py tests/test_linkedin_outreach.py -v
```

### Smoke Test Phase 3 (Full Dry-Run)
```powershell
python scripts/test_phase3_dry_run.py
```
Expected: 3 mock recruiters → 3 referral emails → auto-approved → DryRunEmailSender logs them → cooldown prevents re-send.

### Manual Template Test
```python
from src.outreach.referral_template import ReferralTemplate, LinkedInInviteTemplate

email = ReferralTemplate().render(
    person_name="Priya Kumar", company="Google", role="Senior Engineer",
    job_link="https://example.com/job", current_company="Acme", sender_name="Sam"
)
print(email.subject)

invite = LinkedInInviteTemplate().render(
    person_name="Raj Patel", company="Stripe", role="Backend Engineer"
)
print(len(invite.note), invite.note)  # <= 300 chars
```

---

## Troubleshooting

### Phase 1 Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `Naukri returns 0 jobs` | 406 CAPTCHA / schema change | Try again later; broaden title/location |
| `Greenhouse returns 0 jobs` | Wrong slug or no open roles | Verify at `boards.greenhouse.io/{slug}` |
| `Lever returns 0 jobs` | Wrong slug | Verify at `jobs.lever.co/{slug}` |
| `HN returns 0 jobs` | No thread found or no keyword matches | Check Algolia reachable; broaden job title |

### Phase 2 Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `CAPTCHA detected` | Naukri anti-bot check | Solve manually in browser window, press Enter in console |
| `Daily limit reached` | Hit daily_application_limit | Adjust limit or wait until next day |
| `Playwright browser not found` | Chromium not installed | `playwright install chromium` |
| `Naukri login failed` | Wrong credentials or 2FA | Verify `.env`; 2FA not supported |
| `Form field not recognized` | FormFiller missing mapping | ScreeningQA (Gemini) handles it |

### Phase 3 Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `Unknown recruiter finder source` | Invalid `recruiter_finder_source` | Set to `"mock"`, `"hunter"`, or `"google_search"` |
| `HUNTER_API_KEY not set` | Missing key | Set `HUNTER_API_KEY` in `.env` |
| `GMAIL_SENDER_EMAIL not set` | Missing env var | Add to `.env`: `GMAIL_SENDER_EMAIL=your-gmail@gmail.com` |
| `GMAIL_APP_PASSWORD not set` | Missing Gmail app password | See [Gmail Setup section](#gmail-setup-for-phase-3-email-outreach) above |
| `SMTP authentication failed` | Wrong email or app password | Verify in `.env`; regenerate app password at myaccount.google.com/apppasswords |
| `2-factor authentication required` | Gmail security issue | Enable 2FA first: myaccount.google.com/security → 2-Step Verification |
| No emails sent despite `email_sender_mode="smtp"` | Approval rejected all emails | Check approval mode: use `"auto_approve"` to skip manual review |
| "Recruiter has no email" | Finder returned invalid recruiter | Try different `recruiter_finder_source`; `"mock"` always returns valid emails |
| `approval_mode interactive but no TTY` | Non-interactive environment (Docker, CI/CD) | Use `"auto_approve"` or `"auto_reject"` in config |
| Cooldown skips all recruiters | 90-day cooldown | Set `outreach_cooldown_days: 0` in config for testing |
| Google CAPTCHA in google_search finder | Too many search requests | Reduce frequency; use `"mock"` or `"hunter"` instead |
| Resume not attached to emails | Missing resume file | Ensure `sameet_sabu_resume.pdf` exists in project root, or update `resume_path` in `config/user_config.py` |

### Phase 3b Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `LINKEDIN_EMAIL / LINKEDIN_PASSWORD must be set` | Missing credentials | Set in `.env`; or use `linkedin_outreach_backend: "mock"` |
| `LinkedIn API: connection check failed` | Network error / rate limit | Logged as warning; returns False (safe default) |
| `LinkedIn invite failed: blocked` | Account rate-limited | Increase jitter; reduce `max_linkedin_people_per_company` |

---

## Directory Structure

```
JobHunterX/
├── config/
│   ├── user_config.py          # Your preferences (titles, skills, salary, limits, company lists)
│   ├── platform_config.py      # API keys from .env
│   └── gcp-service-account.json # GCP credentials (optional)
├── src/
│   ├── models.py               # Pydantic: Job, ScoredJob, Recruiter, OutreachMessage, enums
│   ├── scraper/                # Phase 1 — all API-based (no browser)
│   │   ├── greenhouse_scraper.py  # Greenhouse Boards API (cached, per-company)
│   │   ├── lever_scraper.py       # Lever Postings API (cached, per-company)
│   │   ├── ashby_scraper.py       # Ashby Job Board API (cached, per-company)  NEW
│   │   ├── remoteok_scraper.py    # RemoteOK public API (single fetch)  NEW
│   │   ├── remotive_scraper.py    # Remotive remote-jobs API (single fetch)  NEW
│   │   ├── hn_scraper.py          # HN Who's Hiring via Algolia (current month, fixed)
│   │   ├── naukri_scraper.py      # Naukri internal API (curl_cffi)
│   │   └── scraper_factory.py
│   ├── analyzer/               # Phase 1
│   │   ├── match_scorer.py     # Keyword overlap + recency scorer
│   │   ├── legitimacy_checker.py  # Ghost-job heuristics (career-ops Block G)  NEW
│   │   └── jd_analyzer.py      # Gemini JD analysis (not wired into default flow)
│   ├── apply/                  # Phase 2
│   │   ├── review_queue.py     # Human-in-the-loop markdown queue builder  NEW
│   │   ├── naukri_applier.py   # Legacy auto-apply (only when use_review_queue=False)
│   │   ├── form_filler.py      # Heuristic field classifier
│   │   ├── screening_qa.py     # Gemini answers screening questions
│   │   ├── captcha_detector.py # Screenshot + console confirm (no polling)
│   │   ├── daily_limiter.py    # Max N/day cap
│   │   └── applier_factory.py
│   ├── resume/                 # Phase 2
│   │   ├── resume_tailor.py    # Reorder skill categories + Playwright PDF
│   │   └── templates/
│   ├── outreach/               # Phase 3 + 3b
│   │   ├── recruiter_finder.py     # Mock + Hunter + GoogleSearch finders
│   │   ├── referral_template.py    # Static email + LinkedIn DM + invite
│   │   ├── cold_email_composer.py  # Gemini personalized email
│   │   ├── approval_engine.py      # CLI approval: interactive / auto modes
│   │   ├── email_sender.py         # DryRun + Gmail SMTP
│   │   ├── orchestrator.py         # Phase 3 email pipeline
│   │   ├── linkedin_outreach.py    # Mock + LinkedInApiOutreach backends
│   │   └── linkedin_orchestrator.py # Phase 3b LinkedIn DM/invite pipeline
│   └── tracker/                # SQLite + Google Sheets
│       ├── local_db.py         # SQLite jobs + outreach tables
│       ├── google_sheets.py    # Optional GSheets sync (OAuth)
│       ├── followup_tracker.py # Cadence classifier: URGENT/OVERDUE/WAITING/COLD  NEW
│       └── schema.py
├── data/
│   ├── applied.sqlite          # Job + outreach database (auto-created)
│   ├── review_queue.md         # Daily review queue (regenerated each run)  NEW
│   └── follow_ups.md           # Follow-up cadence report (regenerated each run)  NEW
├── output/
│   └── *.pdf                   # Tailored resumes
├── logs/
│   └── applications/*.png      # Submission screenshots
├── tests/                      # pytest
├── scripts/
│   ├── test_phase3_dry_run.py  # End-to-end smoke test
│   ├── mark_applied.py         # Mark a queue entry as Applied/Skipped  NEW
│   └── analyze_patterns.py     # Funnel + source ROI + recommendations  NEW
├── main.py                     # Single entrypoint
├── sameet_sabu_resume.pdf      # Static resume for outreach attachments
├── requirements.txt
├── .env                        # Not in git
└── job-agent-architecture.md   # Full architecture reference
```

---

## Phase 3 Configuration Reference

```python
# config/user_config.py — Phase 3 knobs

# Email outreach
outreach_enabled: bool = True
recruiter_finder_source: str = "mock"   # "mock" | "hunter" | "google_search"
email_style: str = "referral"           # "referral" | "cold"
email_sender_mode: str = "dry_run"      # "dry_run" | "smtp"
approval_mode: str = "interactive"      # "interactive" | "auto_approve" | "auto_reject"
daily_outreach_limit: int = 20          # combined email + LinkedIn budget
outreach_cooldown_days: int = 90
attach_resume_to_outreach: bool = True
max_recruiters_per_company: int = 3

# LinkedIn outreach (Phase 3b)
linkedin_outreach_enabled: bool = True
linkedin_outreach_backend: str = "mock"  # "mock" | "linkedin_api"
max_linkedin_people_per_company: int = 3
linkedin_jitter_min_seconds: int = 30    # delay between connection requests
linkedin_jitter_max_seconds: int = 120
```

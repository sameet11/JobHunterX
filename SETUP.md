# JobHunterX Setup & Runbook

## What it does

JobHunterX is a **scrape + rank + review** tool. It finds jobs, scores them, and surfaces the best ones for you to act on manually.

**`python main.py`** does three things:
1. Scrapes jobs from up to 10 sources
2. Scores + filters by skill match, recency, salary, and legitimacy
3. Writes `data/review_queue.md` — ranked list with apply URLs, scores, ghost-job flags, and follow-up reminders

Everything after that is you: apply manually, run outreach scripts when ready.

---

## Quick Start

### 1. Virtual environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\.venv\Scripts\playwright.exe install chromium   # one-time browser binary download
```

### 2. GCP authentication (for Gemini / resume tailoring)
```powershell
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT_ID
```

### 3. Configure `.env`
```powershell
cp .env.example .env
```

Minimum required (Vertex AI for resume tailoring):
```env
GOOGLE_CLOUD_PROJECT=your-gcp-project
GOOGLE_CLOUD_REGION=us-central1
GEMINI_MODEL=gemini-2.0-flash-001
```

Add as needed:
```env
GOOGLE_SHEET_ID=...       # sync applications to Google Sheets
ADZUNA_APP_ID=...         # Adzuna scraper (India jobs)
ADZUNA_APP_KEY=...
APIFY_API_TOKEN=...       # Apify LinkedIn scraper
MIN_MATCH_SCORE=40        # pre-filter threshold (default 40)
LOG_LEVEL=INFO
```

### 4. Configure `config/user_config.py`
```powershell
cp config/user_config.example.py config/user_config.py
# Edit config/user_config.py — fill in your name, email, skills, company lists
```

Key fields:
```python
applicant: ApplicantProfile = field(default_factory=lambda: ApplicantProfile(
    full_name="Your Name",
    email="your@email.com",
    current_company="Your Company",
    expected_ctc_lpa=60,
))
job_title: str = "Software Engineer"
locations: tuple = ("Mumbai", "Bangalore", "Remote")
salary_min: int = 1_200_000
greenhouse_companies: tuple = (("Stripe", "stripe"), ...)
ashby_companies: tuple = (("Notion", "notion"), ...)
```

### 5. Place your resume
```
JobHunterX/
├── your_resume.pdf    ← here (update resume_path in user_config.py if filename differs)
├── main.py
└── ...
```

### 6. Run
```powershell
python main.py
# → data/review_queue.md
# → data/follow_ups.md  (if you have prior applications)
```

---

## Daily Workflow

```
python main.py
  → open data/review_queue.md
  → apply manually on company sites
  → python scripts/mark_applied.py <dedup_key>

python scripts/generate_resume.py 1 3 5   # tailor PDFs for those positions
python scripts/outreach.py 1 3 5          # find LinkedIn recruiters
  → open data/linkedin_targets.md
  → send connection requests / DMs manually on LinkedIn
```

---

## Scripts Reference

| Script | Usage | What it does |
|--------|-------|-------------|
| `main.py` | `python main.py` | Scrape → score → write review queue + follow-ups |
| `mark_applied.py` | `python scripts/mark_applied.py <dedup_key>` | Record a manual application |
| `mark_applied.py` | `python scripts/mark_applied.py <dedup_key> --skip` | Permanently dismiss a job |
| `generate_resume.py` | `python scripts/generate_resume.py 1 3 5` | Tailor + generate PDFs for queue positions |
| `outreach.py` | `python scripts/outreach.py 1 3 5` | Find LinkedIn recruiters → `data/linkedin_targets.md` |
| `analyze_patterns.py` | `python scripts/analyze_patterns.py` | Funnel + source ROI + recommendations |
| `export_tracker.py` | `python scripts/export_tracker.py` | Export SQLite to CSV/JSON |

`<dedup_key>` comes from the `**dedup_key:**` field in `data/review_queue.md`. You can also use the position number (e.g. `1`) for `generate_resume.py` and `outreach.py`.

---

## Scrape Sources

| Source | Notes |
|--------|-------|
| **Greenhouse** | Configured via `greenhouse_companies` in `user_config.py`. Verify slugs at `boards.greenhouse.io/{slug}` |
| **Lever** | Empty by default — most companies migrated to Ashby. Add verified slugs only. |
| **Ashby** | Configured via `ashby_companies`. Verify at `jobs.ashbyhq.com/{slug}` |
| **RemoteOK** | No auth, no config needed. ~300 remote jobs per run |
| **Remotive** | No auth, no config needed. ~500 software jobs per run |
| **HN Who's Hiring** | Algolia — current month's thread auto-detected |
| **Naukri** | Gated by `naukri_search_enabled` (default `False` — ban risk) |
| **Adzuna** | Requires `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` in `.env` |
| **Apify LinkedIn** | Requires `APIFY_API_TOKEN` in `.env` |

Enable/disable per source in `scrape_on_platforms` in `user_config.py`.

---

## Google Sheets Setup (Optional)

1. [Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials) → Create **OAuth 2.0 Desktop Application** → download JSON → save as `credentials.json` in repo root
2. Enable **Google Sheets API** and **Google Drive API** in your project
3. Add yourself as a test user: [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) → Test users → add your email
4. Get Sheet ID from `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`
5. Add `GOOGLE_SHEET_ID={SHEET_ID}` to `.env`
6. On first run, a browser OAuth prompt appears — grant access; token saved to `data/google_sheets_token.json`

---

## LinkedIn Recruiter Finder (scripts/outreach.py)

Uses a real Playwright browser with your LinkedIn session — no API, no cookie copying.

**First run:** Opens a visible browser. If not logged in, you'll be prompted to log in manually, then press Enter. Session is saved to `data/linkedin_browser_session/` and reused.

**What it does:**
- Searches LinkedIn people search for `{company} recruiter`
- Extracts recruiter names, titles, and profile URLs
- Writes pre-drafted connection notes + DMs to `data/linkedin_targets.md`
- Syncs recruiter list to Google Sheets "Connect Queue" tab (if configured)
- **Nothing is sent — you send manually**

```powershell
python scripts/outreach.py 1 3 5   # positions from review_queue.md
# or raw dedup keys:
python scripts/outreach.py greenhouse:12345 ashby:67890
```

---

## Resume Tailoring (scripts/generate_resume.py)

Reorders the Technical Skills section of your resume to match JD keywords, then renders to PDF via Playwright.

**Setup:** Your `resume_template.html` must be at `src/resume/templates/resume_template.html` (gitignored — keep locally). The template uses `<!-- SKILLS_BLOCK_START -->` / `<!-- SKILLS_BLOCK_END -->` markers.

```powershell
python scripts/generate_resume.py 1 3 5
# → output/Stripe_BackendEngineer.pdf
# → output/Anthropic_SoftwareEngineer.pdf
```

Set `use_tailored_resume: bool = False` in `user_config.py` to always use the static PDF.

---

## Follow-up Tracker

Runs automatically at the end of `main.py`. Sweeps all Applied / Responded / Interview jobs:

| Status | Overdue at | Urgent at | Cold at |
|--------|-----------|----------|---------|
| Applied | 7d | 14d | 30d |
| Responded | 3d | 7d | 21d |
| Interview | 1d | 3d | 14d |

Writes `data/follow_ups.md` grouped by URGENT / OVERDUE / WAITING / COLD.

---

## Pattern Analyzer

```powershell
python scripts/analyze_patterns.py
python scripts/analyze_patterns.py --json   # JSON output
```

Shows:
- **Funnel** — Scraped → Applied → Responded → Interview → Offer counts
- **Source ROI** — which job boards produce interviews vs noise
- **Score by outcome** — helps tune `min_match_score`
- **Recommendations** — e.g. "Source X: 50 scraped, 0 applied — consider removing"

---

## Legitimacy Tiers

Jobs in `review_queue.md` are flagged by `LegitimacyChecker`:

| Tier | Indicator | Meaning |
|------|-----------|---------|
| ✓ `high_confidence` | Fresh, specific JD, no repost | Safe to apply |
| ⚠ `caution` | Older posting or vague JD | Check carefully |
| 🚫 `suspicious` | Very old, repost detected, or red-flag title | Likely ghost job |

Suspicious jobs appear at the bottom of the queue — visible but ranked low.

Tune thresholds in `user_config.py`:
```python
legitimacy_max_age_days: int = 60       # older → caution
legitimacy_stale_age_days: int = 120    # older → suspicious
legitimacy_min_description_chars: int = 200
```

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `Greenhouse returns 0 jobs` | Wrong slug | Verify at `boards.greenhouse.io/{slug}` |
| `Lever returns 0 jobs` | Company migrated to Ashby | Try Ashby slug |
| `Ashby returns 0 jobs` | Wrong slug | Verify at `jobs.ashbyhq.com/{slug}` |
| `Naukri returns 0 jobs` | 406 / schema change | Enable `naukri_search_enabled=True`, try later |
| `HN returns 0 jobs` | No current-month thread | Check Algolia reachable |
| `Google Sheets 403` | API not enabled | Enable Sheets + Drive API in GCP console |
| `Google Sheets access_denied` | Not a test user | Add your email in OAuth consent screen → Test users |
| `Playwright browser not found` | Chromium not installed | `.\.venv\Scripts\playwright.exe install chromium` |
| `linkedin_browser_session login loop` | Session expired | Delete `data/linkedin_browser_session/` and re-run |

---

## Directory Structure

```
JobHunterX/
├── config/
│   ├── user_config.py          # Your preferences (gitignored)
│   ├── user_config.example.py  # Template
│   └── platform_config.py      # Reads from .env
├── src/
│   ├── scraper/                # 10 job-board scrapers
│   ├── analyzer/               # MatchScorer + LegitimacyChecker
│   ├── apply/                  # ReviewQueue (review_queue.py)
│   ├── resume/                 # ResumeTailor + templates
│   ├── outreach/               # browser_finder.py (Playwright LinkedIn)
│   ├── tracker/                # SQLite + Google Sheets + FollowupTracker
│   └── utils/                  # logger, retry, human_behavior
├── data/
│   ├── applied.sqlite          # Auto-created
│   ├── review_queue.md         # Regenerated each run
│   ├── follow_ups.md           # Regenerated each run
│   └── linkedin_targets.md     # Written by scripts/outreach.py
├── output/
│   └── *.pdf                   # Tailored resumes
├── tests/
├── scripts/
│   ├── mark_applied.py
│   ├── generate_resume.py
│   ├── outreach.py
│   ├── analyze_patterns.py
│   └── export_tracker.py
├── main.py
├── {your_resume}.pdf           # Gitignored
├── credentials.json            # Google Sheets OAuth (gitignored)
├── requirements.txt
├── .env
└── .env.example
```

"""User-facing job search preferences. Edit this file to tune the pipeline.

HOW TO USE:
1. Copy to user_config.py:  cp config/user_config.example.py config/user_config.py
2. Fill in YOUR personal details (name, email, salary, skills, company lists, etc.)
3. config/user_config.py is in .gitignore — your personal config stays private
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from config.platform_config import platform as _platform


@dataclass(frozen=True)
class HumanSpeed:
    """Delay timings to simulate human-like behavior and avoid detection."""
    min_delay_ms: int = 3000
    max_delay_ms: int = 8000
    typing_wpm: int = 80
    reading_pause_ms: int = 2000


@dataclass(frozen=True)
class ApplicantProfile:
    """Personal info used by FormFiller and ScreeningQA when applying."""

    full_name: str = "Your Full Name"
    email: str = "your-email@example.com"
    phone: str = "+91-0000000000"
    linkedin_url: str = "https://www.linkedin.com/in/your-handle"
    github_url: str = "https://github.com/your-handle"
    portfolio_url: str = ""

    current_company: str = "Your Current Company"
    current_role: str = "Your Current Job Title"
    current_location: str = "Your City"
    notice_period_days: int = 30
    expected_ctc_lpa: int = 60
    current_ctc_lpa: int = 25

    work_authorization: str = "Indian citizen"
    willing_to_relocate: bool = True
    open_to_remote: bool = True


@dataclass(frozen=True)
class UserConfig:

    # ───── Primary search keyword ─────
    job_title: str = "Software Engineer"

    alternative_titles: tuple[str, ...] = (
        "SDE-1",
        "SDE-2",
        "SDE-3",
        "Software Development Engineer",
        "Senior Software Engineer",
        "Backend Engineer",
        "Full Stack Engineer",
        "AI Engineer",
        "GenAI Engineer",
        "Platform Engineer",
        "Cloud Engineer",
        "Founding Engineer",
        # Add / remove titles as needed
    )

    # ───── Salary range (rupees) ─────
    salary_min: int = 1_200_000   # Filter out jobs with disclosed salary below this
    salary_max: int = 6_000_000

    # ───── Preferred locations ─────
    locations: tuple[str, ...] = ("Mumbai", "Bangalore", "Hyderabad", "Remote")

    experience_years: int = 3
    job_type: str = "full-time"

    # ───── Technical skills — used for keyword matching and resume reordering ─────
    skills: tuple[str, ...] = (
        # Languages
        "Python",
        "Java",
        "TypeScript",
        "JavaScript",
        "SQL",
        # Backend
        "FastAPI",
        "Spring Boot",
        "Express.js",
        "Node.js",
        "REST API",
        "GraphQL",
        # Frontend
        "React",
        "Next.js",
        # GenAI & ML
        "LangChain",
        "RAG",
        "Vertex AI",
        "LLM",
        # Cloud
        "AWS",
        "GCP",
        "Docker",
        "Kubernetes",
        # Databases
        "PostgreSQL",
        "MongoDB",
        "Redis",
        # DevOps
        "CI/CD",
        "GitHub Actions",
        "Terraform",
        # Messaging
        "Kafka",
        # Architecture
        "Microservices",
        "Distributed Systems",
        # Add your own skills here
    )

    # ───── Daily cap (read from .env DAILY_LIMIT) ─────
    daily_application_limit: int = field(default_factory=lambda: _platform.daily_limit)

    # ───── Platforms to scrape ─────
    # All options: "greenhouse", "lever", "ashby", "remoteok", "remotive", "hn",
    #              "naukri" (gated by naukri_search_enabled),
    #              "adzuna" (requires ADZUNA_APP_ID + ADZUNA_APP_KEY in .env),
    #              "apify_linkedin" (requires APIFY_API_TOKEN in .env)
    scrape_on_platforms: tuple[str, ...] = (
        "greenhouse",
        "lever",
        "ashby",
        "remoteok",
        "remotive",
        "hn",
        "naukri",
    )

    # ───── Naukri on/off switches ─────
    # naukri_search_enabled: include Naukri in Phase 1 scraping
    # naukri_apply_enabled:  include Naukri in legacy Phase 2 auto-apply
    #                        (only relevant when use_review_queue=False)
    naukri_search_enabled: bool = False   # Off by default — ban risk
    naukri_apply_enabled: bool = False

    # apply_on_platforms controls legacy auto-apply (Phase 2).
    # Has no effect in default human-in-the-loop mode (use_review_queue=True).
    apply_on_platforms: tuple[str, ...] = ("naukri",)

    # ───── Human-in-the-loop mode (default) ─────
    # When True, Phase 2 writes data/review_queue.md instead of auto-submitting.
    # You review, manually apply, then: python scripts/mark_applied.py <dedup_key>
    # Set False to revert to legacy Naukri auto-apply (not recommended).
    use_review_queue: bool = True
    review_queue_top_n: int = 30

    # ───── Ghost-job legitimacy detection ─────
    legitimacy_check_enabled: bool = True
    legitimacy_max_age_days: int = 60        # older → caution flag
    legitimacy_stale_age_days: int = 120     # older → suspicious flag
    legitimacy_min_description_chars: int = 200  # vague JDs → caution flag

    # ───── ATS company lists ─────
    # Add companies you want to track. Verify slugs at the board URL before adding.
    # Greenhouse: boards.greenhouse.io/{slug}
    greenhouse_companies: tuple[tuple[str, str], ...] = (
        ("Stripe", "stripe"),
        ("Airbnb", "airbnb"),
        ("Figma", "figma"),
        ("Anthropic", "anthropic"),
        ("Brex", "brex"),
        ("Asana", "asana"),
        # Add more (display_name, board_slug) pairs
    )

    # Lever: jobs.lever.co/{slug}
    # Note: many companies migrated from Lever to Ashby. Verify slugs before adding.
    lever_companies: tuple[tuple[str, str], ...] = ()

    # Ashby: jobs.ashbyhq.com/{slug}
    ashby_companies: tuple[tuple[str, str], ...] = (
        ("Notion", "notion"),
        ("Linear", "linear"),
        ("Vercel", "vercel"),
        ("Replit", "replit"),
        ("Mercury", "mercury"),
        # Add more (display_name, board_slug) pairs
    )

    human_speed: HumanSpeed = field(default_factory=HumanSpeed)
    applicant: ApplicantProfile = field(default_factory=ApplicantProfile)

    # Static resume PDF — used for outreach attachments and as fallback
    resume_path: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "your_resume.pdf"
    )

    # Reorder Technical Skills section by JD keywords before applying (zero hallucination)
    use_tailored_resume: bool = True

    find_recruiters_per_job: bool = True
    max_recruiters_per_company: int = 3
    send_linkedin_request: bool = True
    send_email: bool = True

    # ───── Phase 3: Email outreach ─────
    outreach_enabled: bool = True
    recruiter_finder_source: str = "mock"    # "mock" | "hunter" | "google_search"
    email_style: str = "referral"            # "referral" (static, free) | "cold" (Gemini)
    email_sender_mode: str = "dry_run"       # "dry_run" (test) | "smtp" (real send)
    approval_mode: str = "interactive"       # "interactive" | "auto_approve" | "auto_reject"
    daily_outreach_limit: int = 20
    outreach_cooldown_days: int = 90
    attach_resume_to_outreach: bool = True

    # ───── Phase 3b: LinkedIn DM / connection outreach ─────
    linkedin_outreach_enabled: bool = True
    linkedin_outreach_backend: str = "mock"  # "mock" | "linkedin_api"
    max_linkedin_people_per_company: int = 3
    linkedin_jitter_min_seconds: int = 30    # Safety delay between requests
    linkedin_jitter_max_seconds: int = 120

    # ───── Scoring weights ─────
    job_recency_weight: float = 0.2           # Score boost for jobs posted < recency_hours_threshold
    job_recency_hours_threshold: int = 24
    india_location_boost: float = 0.45        # Score boost for India-located jobs

    # ───── Filtering ─────
    skip_companies: tuple[str, ...] = ()      # Exact company names to skip
    skip_if_applied_in_days: int = 180        # Re-apply cooldown
    min_match_score: int = field(default_factory=lambda: _platform.min_match_score)

    # ───── Anti-detection timing (legacy auto-apply) ─────
    apply_gap_min_seconds: int = 300          # 5 min
    apply_gap_max_seconds: int = 900          # 15 min
    apply_long_break_every: int = 3
    apply_long_break_min_seconds: int = 600   # 10 min
    apply_long_break_max_seconds: int = 1200  # 20 min


config = UserConfig()

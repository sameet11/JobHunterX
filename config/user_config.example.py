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
class ApplicantProfile:
    """Personal info used by outreach scripts (scripts/outreach.py)."""

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

    # ───── Salary filter (rupees) ─────
    salary_min: int = 1_200_000   # Filtered only when salary is disclosed in the JD

    # ───── Preferred locations ─────
    locations: tuple[str, ...] = ("Mumbai", "Bangalore", "Hyderabad", "Remote")

    experience_years: int = 3

    # ───── Technical skills — keyword matching + resume reordering ─────
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

    # ───── Platforms to scrape ─────
    # Options: "greenhouse", "lever", "ashby", "remoteok", "remotive", "hn",
    #          "naukri" (gated by naukri_search_enabled),
    #          "adzuna" (requires ADZUNA_APP_ID + ADZUNA_APP_KEY in .env),
    #          "apify_linkedin" (requires APIFY_API_TOKEN in .env)
    scrape_on_platforms: tuple[str, ...] = (
        "greenhouse",
        "lever",
        "ashby",
        "remoteok",
        "remotive",
        "hn",
        "naukri",
    )

    naukri_search_enabled: bool = False   # Off by default — ban risk

    # ───── Review queue ─────
    review_queue_top_n: int = 30   # Top N scored jobs written to data/review_queue.md

    # ───── Ghost-job legitimacy detection ─────
    legitimacy_check_enabled: bool = True
    legitimacy_max_age_days: int = 60        # older → caution flag
    legitimacy_stale_age_days: int = 120     # older → suspicious flag
    legitimacy_min_description_chars: int = 200

    # ───── Greenhouse company list (display_name, board_slug) ─────
    # Verify slugs at boards.greenhouse.io/{slug}
    greenhouse_companies: tuple[tuple[str, str], ...] = (
        ("Stripe", "stripe"),
        ("Airbnb", "airbnb"),
        ("Figma", "figma"),
        ("Anthropic", "anthropic"),
        ("Brex", "brex"),
        ("Asana", "asana"),
        # Add more (display_name, board_slug) pairs
    )

    # ───── Lever company list (display_name, board_slug) ─────
    # Verify slugs at jobs.lever.co/{slug}
    # Note: most companies migrated from Lever to Ashby — verify before adding
    lever_companies: tuple[tuple[str, str], ...] = ()

    # ───── Ashby company list (display_name, board_slug) ─────
    # Verify slugs at jobs.ashbyhq.com/{slug}
    ashby_companies: tuple[tuple[str, str], ...] = (
        ("Notion", "notion"),
        ("Linear", "linear"),
        ("Vercel", "vercel"),
        ("Replit", "replit"),
        ("Mercury", "mercury"),
        # Add more (display_name, board_slug) pairs
    )

    applicant: ApplicantProfile = field(default_factory=ApplicantProfile)

    # Static resume PDF — fallback when Playwright fails or use_tailored_resume=False
    resume_path: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "your_resume.pdf"
    )

    # Reorder skills + tailor summary via Gemini before generating PDF
    use_tailored_resume: bool = True

    # ───── LinkedIn recruiter search (scripts/outreach.py) ─────
    max_linkedin_people_per_company: int = 3
    linkedin_jitter_min_seconds: int = 30    # delay between connection requests
    linkedin_jitter_max_seconds: int = 120

    # ───── Scoring weights ─────
    job_recency_weight: float = 0.2           # boost for jobs posted < recency_hours_threshold
    job_recency_hours_threshold: int = 24
    india_location_boost: float = 0.45        # India jobs rank above non-India

    # ───── Filtering ─────
    skip_companies: tuple[str, ...] = ()      # exact company names to skip
    skip_if_applied_in_days: int = 180        # re-apply cooldown
    min_match_score: int = field(default_factory=lambda: _platform.min_match_score)


config = UserConfig()

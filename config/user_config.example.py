"""User-facing job search preferences. Edit this file to tune the pipeline.

HOW TO USE:
1. Copy this file to user_config.py: cp config/user_config.example.py config/user_config.py
2. Edit config/user_config.py with YOUR personal details (name, email, salary, skills, etc.)
3. config/user_config.py is in .gitignore — your personal config stays private
4. Each team member can have their own customized user_config.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from config.platform_config import platform as _platform


@dataclass(frozen=True)
class HumanSpeed:
    """Delay timings to simulate human-like behavior and avoid detection."""
    min_delay_ms: int = 3000          # Minimum pause between actions (ms)
    max_delay_ms: int = 8000          # Maximum pause between actions (ms)
    typing_wpm: int = 80              # Typing speed (words per minute)
    reading_pause_ms: int = 2000      # Pause when "reading" content (ms)


@dataclass(frozen=True)
class ApplicantProfile:
    """Personal info used in job applications. CUSTOMIZE WITH YOUR DETAILS."""

    # ───── Contact Information ─────
    full_name: str = "Your Full Name"
    email: str = "your-email@example.com"
    phone: str = "+91-0000000000"
    linkedin_url: str = "https://www.linkedin.com/in/your-handle"
    github_url: str = "https://github.com/your-handle"
    portfolio_url: str = ""  # Optional: your portfolio website

    # ───── Current Employment ─────
    current_company: str = "Your Current Company"
    current_role: str = "Your Current Job Title"
    current_location: str = "Your City, State"
    notice_period_days: int = 30

    # ───── Salary Expectations (in Lakhs per annum) ─────
    expected_ctc_lpa: int = 60        # Your expected salary (LPA)
    current_ctc_lpa: int = 25         # Your current salary (LPA)

    # ───── Work Authorization ─────
    work_authorization: str = "Indian citizen"  # Your citizenship/visa status
    willing_to_relocate: bool = True
    open_to_remote: bool = True


@dataclass(frozen=True)
class UserConfig:
    # ───── PRIMARY JOB SEARCH KEYWORDS ─────
    job_title: str = "Software Engineer"  # Main role you're searching for

    # ───── ALTERNATIVE JOB TITLES ─────
    # Include all job titles you're open to. These are used as search keywords.
    alternative_titles: tuple[str, ...] = (
        "SDE-1",
        "SDE-2",
        "SDE-3",
        "Software Development Engineer",
        "Senior Software Engineer",
        "Backend Engineer",
        "Full Stack Engineer",
        "DevOps Engineer",
        "Cloud Engineer",
        # Add more as needed...
    )

    # ───── SALARY RANGE (in rupees) ─────
    salary_min: int = 1_200_000   # Minimum annual salary
    salary_max: int = 6_000_000   # Maximum annual salary

    # ───── PREFERRED LOCATIONS ─────
    locations: tuple[str, ...] = (
        "Mumbai",
        "Bangalore",
        "Hyderabad",
        "Remote"
    )

    # ───── EXPERIENCE LEVEL ─────
    experience_years: int = 3     # Years of experience
    job_type: str = "full-time"   # "full-time" | "contract" | "part-time"

    # ───── TECHNICAL SKILLS ─────
    # List ALL your relevant technical skills here. These are used for job matching.
    # The system reorders skills in your resume based on job description matches.
    skills: tuple[str, ...] = (
        # ───── LANGUAGES ─────
        "Python",
        "JavaScript",
        "TypeScript",
        "Java",
        "Go",
        "Rust",

        # ───── BACKEND FRAMEWORKS ─────
        "FastAPI",
        "Django",
        "Flask",
        "Spring Boot",
        "Node.js",
        "Express.js",

        # ───── FRONTEND FRAMEWORKS ─────
        "React",
        "React.js",
        "Next.js",
        "Vue.js",
        "Angular",

        # ───── CLOUD & INFRASTRUCTURE ─────
        "AWS",
        "Google Cloud Platform",
        "GCP",
        "Azure",
        "Docker",
        "Kubernetes",

        # ───── DATABASES ─────
        "PostgreSQL",
        "MongoDB",
        "Redis",
        "Elasticsearch",
        "DynamoDB",

        # ───── MESSAGE QUEUES & STREAMING ─────
        "Kafka",
        "RabbitMQ",
        "Apache Kafka",

        # ───── AI/ML & LLM ─────
        "Claude",
        "ChatGPT",
        "Vertex AI",
        "LangChain",
        "RAG",

        # ───── DEVOPS & CI/CD ─────
        "GitHub Actions",
        "Jenkins",
        "GitLab CI",
        "Docker",
        "Kubernetes",

        # ───── ADD YOUR SKILLS HERE ─────
        # Remove defaults above and add your actual skills
    )

    # ───── PHASE 1: SCRAPING & ANALYSIS ─────
    daily_application_limit: int = field(default_factory=lambda: _platform.daily_limit)

    # Which job boards to scrape jobs from
    scrape_on_platforms: tuple[str, ...] = ("linkedin", "naukri")

    # Which job boards to auto-apply to
    apply_on_platforms: tuple[str, ...] = ("naukri",)

    # ───── PHASE 2: APPLICATION SETTINGS ─────
    linkedin_enabled: bool = True
    linkedin_job_titles: tuple[str, ...] = ("SDE-1", "SDE-2")

    human_speed: HumanSpeed = field(default_factory=HumanSpeed)
    applicant: ApplicantProfile = field(default_factory=ApplicantProfile)

    # Static resume file path (fallback if tailoring fails)
    resume_path: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "sameet_sabu_resume.pdf"
    )

    # Auto-reorder resume skills based on job description (recommended: True)
    use_tailored_resume: bool = True

    # ───── PHASE 3: RECRUITER OUTREACH ─────
    outreach_enabled: bool = True

    find_recruiters_per_job: bool = True
    max_recruiters_per_company: int = 3
    send_linkedin_request: bool = True
    send_email: bool = True

    # Recruiter finder source: "mock" (testing) | "hunter" (production, requires HUNTER_API_KEY)
    recruiter_finder_source: str = "mock"

    # Email style: "referral" (static, fast) | "cold" (AI-generated, slower)
    email_style: str = "referral"

    # Email sender: "dry_run" (logs only) | "smtp" (actually sends)
    email_sender_mode: str = "dry_run"

    # Approval mode: "interactive" (ask before sending) | "auto_approve" | "auto_reject"
    approval_mode: str = "interactive"

    daily_outreach_limit: int = 20
    outreach_cooldown_days: int = 90  # Skip recruiter if contacted within N days
    attach_resume_to_outreach: bool = True

    # ───── LINKEDIN DM/CONNECTION OUTREACH ─────
    linkedin_outreach_enabled: bool = True
    linkedin_outreach_backend: str = "mock"  # "mock" | "playwright"
    max_linkedin_people_per_company: int = 3
    linkedin_jitter_min_seconds: int = 30
    linkedin_jitter_max_seconds: int = 120

    # ───── JOB RECENCY PREFERENCE ─────
    # Boost score for recently posted jobs
    job_recency_weight: float = 0.2           # 20% boost if recent
    job_recency_hours_threshold: int = 24     # Jobs posted within 24 hours get boost

    # ───── FILTERING & MATCHING ─────
    skip_companies: tuple[str, ...] = ()      # Companies to skip (e.g., "Company X")
    skip_if_applied_in_days: int = 180        # Don't apply if already applied within N days
    min_match_score: int = field(default_factory=lambda: _platform.min_match_score)

    # ───── TIMING & PACING (Anti-Detection) ─────
    # Pause between applications to avoid detection
    apply_gap_min_seconds: int = 300          # 5 minutes
    apply_gap_max_seconds: int = 900          # 15 minutes
    apply_long_break_every: int = 3           # Take long break every N applications
    apply_long_break_min_seconds: int = 600   # 10 minutes
    apply_long_break_max_seconds: int = 1200  # 20 minutes


# ═══════════════════════════════════════════════════════════════════════════════
# INSTANTIATE CONFIG
# This creates the global config object used by the rest of the application.
# ═══════════════════════════════════════════════════════════════════════════════

config = UserConfig()

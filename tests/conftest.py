"""Shared test fixtures and configuration."""

from pathlib import Path

import pytest

from src.models import JDAnalysis, Job, ScoredJob


@pytest.fixture
def sample_job_backend():
    """A real-world backend engineer job posting."""
    return Job(
        id="job-001",
        title="Senior Backend Engineer",
        company="TechCorp",
        location="Bangalore",
        salary="₹80L - ₹120L",
        description="Looking for a senior backend engineer with FastAPI, PostgreSQL, AWS experience...",
        apply_url="https://techcorp.com/jobs/backend-001",
        easy_apply=True,
        source="naukri",
    )


@pytest.fixture
def sample_job_fullstack():
    """A full-stack role with mixed backend/frontend requirements."""
    return Job(
        id="job-002",
        title="Full Stack Engineer",
        company="StartupXYZ",
        location="Remote",
        salary="₹60L - ₹90L",
        description="React + Next.js frontend, Python FastAPI backend, GCP Cloud Run deployment...",
        apply_url="https://startup.com/jobs/fullstack",
        easy_apply=False,
        source="greenhouse",
    )


@pytest.fixture
def sample_job_infra():
    """An infrastructure/DevOps focused role."""
    return Job(
        id="job-003",
        title="Cloud Infrastructure Engineer",
        company="CloudSystems Inc",
        location="Mumbai",
        salary="₹75L - ₹110L",
        description="Kubernetes, Docker, Terraform, CI/CD, AWS, monitoring with Prometheus/Grafana...",
        apply_url="https://cloudsys.com/jobs/infra",
        easy_apply=False,
        source="greenhouse",
    )


@pytest.fixture
def analysis_backend_match():
    """JD analysis for a well-matched backend role."""
    return JDAnalysis(
        match_score=92,
        required_skills=["Python", "FastAPI", "PostgreSQL", "REST API"],
        preferred_skills=["AWS", "Docker", "Kubernetes"],
        candidate_has_skills=["Python", "FastAPI", "PostgreSQL", "REST API", "AWS", "Docker"],
        missing_skills=["Kubernetes"],
        keywords_to_include=[
            "FastAPI",
            "Python",
            "PostgreSQL",
            "AWS",
            "Docker",
            "REST API",
            "Microservices",
        ],
        key_responsibilities=[
            "Design and build scalable microservices",
            "Optimize database queries",
            "Lead code reviews",
        ],
        company_culture="Fast-paced, collaborative, ownership-driven",
        summary="Strong match. You have most required skills. Kubernetes is missing but learnable.",
        should_apply=True,
        reason="Excellent technical match with 92% score",
    )


@pytest.fixture
def analysis_fullstack_moderate():
    """JD analysis for a moderate match full-stack role."""
    return JDAnalysis(
        match_score=68,
        required_skills=["React", "Python", "JavaScript", "PostgreSQL"],
        preferred_skills=["Next.js", "TypeScript", "GCP"],
        candidate_has_skills=["React", "Python", "JavaScript", "PostgreSQL"],
        missing_skills=["Next.js", "TypeScript", "GCP"],
        keywords_to_include=[
            "React",
            "Next.js",
            "Python",
            "FastAPI",
            "JavaScript",
            "TypeScript",
            "GCP",
            "Cloud Run",
        ],
        key_responsibilities=["Build React UI components", "Implement Python APIs", "Deploy to GCP"],
        company_culture="Startup energy, lean teams, rapid iteration",
        summary="Moderate match. Core skills present but missing some modern tooling.",
        should_apply=True,
        reason="Borderline but worth applying given startup growth potential",
    )


@pytest.fixture
def analysis_no_match():
    """JD analysis for a poor match role (should skip)."""
    return JDAnalysis(
        match_score=35,
        required_skills=["Go", "Rust", "C++", "Kubernetes"],
        preferred_skills=["WebAssembly", "LLVM"],
        candidate_has_skills=[],
        missing_skills=["Go", "Rust", "C++", "Kubernetes", "WebAssembly", "LLVM"],
        keywords_to_include=["Go", "Rust", "C++", "Kubernetes", "Systems Programming"],
        key_responsibilities=["Build low-level systems", "Performance optimization"],
        company_culture="Research-focused, deeply technical",
        summary="Poor match. Your skills are web/backend focused; this role needs systems programming.",
        should_apply=False,
        reason="Skill mismatch (35% score) — insufficient background in required languages",
    )


@pytest.fixture
def scored_job_backend(sample_job_backend, analysis_backend_match):
    """A ScoredJob combining job and analysis."""
    return ScoredJob(job=sample_job_backend, analysis=analysis_backend_match)


@pytest.fixture
def scored_job_fullstack(sample_job_fullstack, analysis_fullstack_moderate):
    """A ScoredJob for full-stack role."""
    return ScoredJob(job=sample_job_fullstack, analysis=analysis_fullstack_moderate)


@pytest.fixture
def scored_job_no_match(sample_job_infra, analysis_no_match):
    """A ScoredJob that should be skipped (poor match)."""
    return ScoredJob(job=sample_job_infra, analysis=analysis_no_match)


@pytest.fixture
def output_dir(tmp_path):
    """Temporary output directory for generated PDFs."""
    return tmp_path / "output"


# ───── Phase 3 fixtures ─────


@pytest.fixture
def sample_recruiter_recruiter():
    """A typical talent acquisition recruiter."""
    from src.models import Recruiter

    return Recruiter(
        name="Priya Sharma",
        title="Senior Technical Recruiter",
        email="priya.sharma@google.com",
        company="Google",
        linkedin_url="https://www.linkedin.com/in/priya-sharma",
        source="mock",
        confidence=85,
    )


@pytest.fixture
def sample_recruiter_engineer():
    """An engineering hiring manager — better for cold outreach."""
    from src.models import Recruiter

    return Recruiter(
        name="Rajesh Kumar",
        title="Engineering Manager",
        email="rajesh.k@google.com",
        company="Google",
        linkedin_url="https://www.linkedin.com/in/rajesh-kumar",
        source="hunter",
        confidence=92,
    )


@pytest.fixture
def sample_recruiter_no_email():
    """Recruiter found via LinkedIn but no email yet — channel=LINKEDIN_MSG."""
    from src.models import Recruiter

    return Recruiter(
        name="Anita Desai",
        title="HR Business Partner",
        email="",
        company="StartupXYZ",
        linkedin_url="https://www.linkedin.com/in/anita-desai",
        source="linkedin",
        confidence=70,
    )


@pytest.fixture
def drafted_outreach_message(sample_recruiter_recruiter, sample_job_backend):
    """A drafted email ready for approval."""
    from src.models import OutreachChannel, OutreachMessage, OutreachStatus, OutreachStyle

    return OutreachMessage(
        recruiter=sample_recruiter_recruiter,
        job=sample_job_backend,
        channel=OutreachChannel.EMAIL,
        style=OutreachStyle.REFERRAL,
        subject="Referral Request — Senior Backend Engineer at TechCorp",
        body="Hi Priya Sharma,\n\nI came across the Senior Backend Engineer opening...\n\nBest,\nSameet",
        status=OutreachStatus.DRAFTED,
    )


@pytest.fixture
def temp_db(tmp_path):
    """Temporary LocalDB for test isolation."""
    from src.tracker.local_db import LocalDB

    db_path = tmp_path / "test.sqlite"
    db = LocalDB(db_path)
    yield db
    db.close()

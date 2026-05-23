"""Tests for cross-source scrape dedup (Greenhouse / Lever / HN / Naukri).

Rules:
- Same job id on same source → deduped by source:id key (existing).
- Same (company, title) on different sources → keep first source, drop duplicate.
- Different (company, title) even if same source → both kept.
- Dedup is case-insensitive and strips whitespace.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.models import Job


def _job(id_: str, company: str, title: str, source: str) -> Job:
    return Job(
        id=id_,
        title=title,
        company=company,
        location="Bangalore",
        apply_url=f"https://example.com/{id_}",
        source=source,
    )


def _cross_source_key(job: Job) -> tuple[str, str]:
    return (job.company.strip().lower(), job.title.strip().lower())


def dedupe_jobs(raw: list[Job]) -> list[Job]:
    """Mirror of the logic in main.scrape_all()."""
    found: dict[str, Job] = {}
    cross_seen: dict[tuple[str, str], str] = {}
    for job in raw:
        if job.dedup_key() in found:
            continue
        ck = _cross_source_key(job)
        first_source = cross_seen.get(ck)
        if first_source and first_source != job.source:
            continue
        cross_seen[ck] = job.source
        found[job.dedup_key()] = job
    return list(found.values())


class TestWithinSourceDedup:
    def test_same_id_same_source_deduped(self):
        jobs = [
            _job("j1", "Acme", "SWE", "naukri"),
            _job("j1", "Acme", "SWE", "naukri"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 1

    def test_different_ids_same_source_both_kept(self):
        jobs = [
            _job("j1", "Acme", "SWE", "naukri"),
            _job("j2", "Acme", "Backend Engineer", "naukri"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 2


class TestCrossSourceDedup:
    def test_same_company_title_different_source_drops_second(self):
        """Greenhouse and Naukri both show same job — only first is kept."""
        jobs = [
            _job("gh-001", "Google", "Software Engineer", "greenhouse"),
            _job("nk-001", "Google", "Software Engineer", "naukri"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 1
        assert result[0].source == "greenhouse"  # first one wins

    def test_different_companies_both_kept(self):
        jobs = [
            _job("gh-001", "Google", "Software Engineer", "greenhouse"),
            _job("nk-001", "Microsoft", "Software Engineer", "naukri"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 2

    def test_different_titles_same_company_both_kept(self):
        jobs = [
            _job("gh-001", "Google", "Software Engineer", "greenhouse"),
            _job("nk-001", "Google", "Senior Software Engineer", "naukri"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 2

    def test_cross_dedup_case_insensitive(self):
        """Company/title matching must be case-insensitive."""
        jobs = [
            _job("gh-001", "GOOGLE", "Software Engineer", "greenhouse"),
            _job("nk-001", "google", "software engineer", "naukri"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 1

    def test_cross_dedup_strips_whitespace(self):
        jobs = [
            _job("gh-001", "  Google  ", "Software Engineer", "greenhouse"),
            _job("nk-001", "Google", "Software Engineer", "naukri"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 1

    def test_three_sources_same_job_only_first_kept(self):
        jobs = [
            _job("gh-001", "Meta", "Backend Engineer", "greenhouse"),
            _job("nk-001", "Meta", "Backend Engineer", "naukri"),
            _job("lv-001", "Meta", "Backend Engineer", "lever"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 1
        assert result[0].source == "greenhouse"

    def test_mixed_dupes_and_unique(self):
        jobs = [
            _job("gh-001", "Google", "SWE", "greenhouse"),
            _job("nk-001", "Google", "SWE", "naukri"),      # cross-source dupe
            _job("lv-001", "Meta", "SWE", "lever"),
            _job("nk-002", "Stripe", "Platform Engineer", "naukri"),
        ]
        result = dedupe_jobs(jobs)
        assert len(result) == 3
        sources = {j.source for j in result}
        companies = {j.company for j in result}
        assert "Google" in companies
        assert "Meta" in companies
        assert "Stripe" in companies

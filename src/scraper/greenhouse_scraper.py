"""Fetches jobs from Greenhouse Boards API (public, no auth required).

Endpoint: https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true

Companies are configured in user_config.greenhouse_companies as (display_name, slug) pairs.
All companies are fetched once per scraper instance and cached; subsequent search() calls
filter the cache locally — no repeated API calls.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from config.user_config import UserConfig
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseScraper(BaseScraper):
    source = "greenhouse"

    def __init__(self, user_config: UserConfig) -> None:
        super().__init__(user_config)
        self._cache: dict[str, list[dict]] | None = None

    def _fetch_all(self) -> dict[str, list[dict]]:
        """Fetch and cache all jobs per company (API hit once per run)."""
        if self._cache is not None:
            return self._cache
        result: dict[str, list[dict]] = {}
        for name, slug in self.user_config.greenhouse_companies:
            try:
                resp = httpx.get(
                    f"{_BASE}/{slug}/jobs",
                    params={"content": "true"},
                    timeout=15,
                )
                if resp.status_code == 200:
                    jobs = resp.json().get("jobs", [])
                    for j in jobs:
                        j["_company_name"] = name
                    result[slug] = jobs
                    logger.debug(f"Greenhouse {name}: {len(jobs)} jobs")
                else:
                    logger.warning(f"Greenhouse {name} ({slug}): HTTP {resp.status_code}")
                    result[slug] = []
            except Exception as exc:
                logger.warning(f"Greenhouse {name} ({slug}): {exc}")
                result[slug] = []
        self._cache = result
        return result

    @staticmethod
    def _title_match(job_title: str, search_title: str) -> bool:
        jt = job_title.lower()
        return any(w in jt for w in search_title.lower().split() if len(w) > 2)

    @staticmethod
    def _location_match(job_location: str, search_location: str) -> bool:
        jl = (job_location or "").lower()
        sl = search_location.lower()
        if sl == "remote":
            return "remote" in jl
        # Non-remote search: include city match, fully-remote postings, or unspecified location.
        return sl in jl or "remote" in jl or not jl

    @staticmethod
    def _to_job(raw: dict) -> Job:
        posted = None
        raw_date = raw.get("updated_at") or raw.get("created_at")
        if raw_date:
            try:
                posted = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        location = (raw.get("location") or {}).get("name") or ""
        return Job(
            id=str(raw["id"]),
            title=raw.get("title", ""),
            company=raw.get("_company_name", ""),
            location=location,
            apply_url=raw.get("absolute_url", ""),
            source="greenhouse",
            posted_date=posted,
            description=(raw.get("content") or "")[:2000],
        )

    def search(self, title: str, location: str) -> list[Job]:
        matches: list[Job] = []
        for _slug, raw_jobs in self._fetch_all().items():
            for raw in raw_jobs:
                if not self._title_match(raw.get("title", ""), title):
                    continue
                job_location = (raw.get("location") or {}).get("name", "")
                if not self._location_match(job_location, location):
                    continue
                matches.append(self._to_job(raw))
        return matches

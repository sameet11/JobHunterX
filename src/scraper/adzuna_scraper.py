"""Fetches jobs from Adzuna's India Jobs API.

Endpoint: https://api.adzuna.com/v1/api/jobs/in/search/{page}
Requires: ADZUNA_APP_ID and ADZUNA_APP_KEY (free at developer.adzuna.com, 250 req/day).

Fetches up to _MAX_PAGES × 50 = 250 results in one run, cached once per instance.
search() filters the cache locally — no repeated API calls across the title × location loop.
"""
from __future__ import annotations

import time
from datetime import datetime

import httpx

from config.platform_config import platform
from config.user_config import UserConfig
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_BASE = "https://api.adzuna.com/v1/api/jobs/in/search"
_PAGE_SIZE = 50
_MAX_PAGES = 5  # 250 jobs max — well inside the 250 req/day free tier

_INDIA_LOCATIONS = {
    "mumbai", "bangalore", "bengaluru", "hyderabad", "pune",
    "delhi", "noida", "gurugram", "gurgaon", "chennai", "kolkata",
    "india", "ncr",
}


class AdzunaScraper(BaseScraper):
    source = "adzuna"

    def __init__(self, user_config: UserConfig) -> None:
        super().__init__(user_config)
        self._cache: list[dict] | None = None

    def _fetch_all(self) -> list[dict]:
        if self._cache is not None:
            return self._cache

        if not platform.adzuna_app_id or not platform.adzuna_app_key:
            logger.warning("Adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not set — skipping")
            self._cache = []
            return self._cache

        results: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            try:
                resp = httpx.get(
                    f"{_BASE}/{page}",
                    params={
                        "app_id": platform.adzuna_app_id,
                        "app_key": platform.adzuna_app_key,
                        "results_per_page": _PAGE_SIZE,
                        "what": self.user_config.job_title,
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                page_jobs = resp.json().get("results", [])
                if not page_jobs:
                    break
                results.extend(page_jobs)
                logger.info(f"Adzuna: page {page} → {len(page_jobs)} jobs (total {len(results)})")
                if len(page_jobs) < _PAGE_SIZE:
                    break
                time.sleep(0.5)
            except Exception as exc:
                logger.warning(f"Adzuna: page {page} fetch failed: {exc}")
                break

        self._cache = results
        logger.info(f"Adzuna: cached {len(results)} India jobs")
        return self._cache

    @staticmethod
    def _title_match(raw_title: str, search_title: str) -> bool:
        tt = (raw_title or "").lower()
        return any(w in tt for w in search_title.lower().split() if len(w) > 2)

    @staticmethod
    def _location_match(raw_location: str, search_location: str) -> bool:
        sl = search_location.lower()
        rl = (raw_location or "").lower()
        # "Remote" search → accept all Adzuna India jobs.
        if sl == "remote":
            return True
        # If job has no location info → keep it (Adzuna India endpoint only returns IN jobs).
        if not rl:
            return True
        return sl in rl or any(city in rl for city in _INDIA_LOCATIONS)

    @staticmethod
    def _parse_date(raw: dict) -> datetime | None:
        val = raw.get("created")
        if not val:
            return None
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _salary(raw: dict) -> str | None:
        lo = raw.get("salary_min")
        hi = raw.get("salary_max")
        if lo and hi:
            return f"₹{int(lo):,} – ₹{int(hi):,}"
        if lo:
            return f"₹{int(lo):,}+"
        return None

    @classmethod
    def _to_job(cls, raw: dict) -> Job:
        loc_obj = raw.get("location") or {}
        location = (
            loc_obj.get("display_name")
            or (loc_obj.get("area") or ["India"])[-1]
        )
        return Job(
            id=str(raw.get("id", "")),
            title=raw.get("title", ""),
            company=(raw.get("company") or {}).get("display_name", ""),
            location=location,
            salary=cls._salary(raw),
            apply_url=raw.get("redirect_url", ""),
            source="adzuna",
            posted_date=cls._parse_date(raw),
            description=(raw.get("description") or "")[:2000],
        )

    def search(self, title: str, location: str) -> list[Job]:
        matches: list[Job] = []
        for raw in self._fetch_all():
            if not self._title_match(raw.get("title", ""), title):
                continue
            raw_location = (raw.get("location") or {}).get("display_name", "")
            if not self._location_match(raw_location, location):
                continue
            matches.append(self._to_job(raw))
        return matches

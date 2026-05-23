"""Apify-backed LinkedIn scraper.

Makes ONE broad fetch per process (not per title × location), capped at
apify_per_source_limit jobs (default 100). The title × location loop in
main.scrape_all filters the cached results locally — no extra Apify credits.

Actor default (override via env): curious_coder~linkedin-jobs-scraper
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import ClassVar
from urllib.parse import quote_plus

import httpx

from config.platform_config import platform
from config.user_config import UserConfig
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_BASE = "https://api.apify.com/v2/acts"
_RUN_TIMEOUT_SECONDS = 240

_INDIA_LOCATIONS = {
    "mumbai", "bangalore", "bengaluru", "hyderabad", "pune",
    "delhi", "noida", "gurugram", "gurgaon", "chennai", "kolkata",
    "india", "ncr",
}


class _BaseApifyScraper(BaseScraper):
    """Shared logic: one broad Apify run per process, then local filtering.

    Subclasses set source, actor_id_attr (which platform_config field holds the
    actor ID), and build_input() (the actor-specific JSON input).
    """

    source: ClassVar[str] = "apify"
    actor_id_attr: ClassVar[str] = ""

    def __init__(self, user_config: UserConfig) -> None:
        super().__init__(user_config)
        self._cache: list[dict] | None = None

    def _actor_id(self) -> str:
        return getattr(platform, self.actor_id_attr, "")

    def build_input(self) -> dict:
        """Actor-specific input payload — subclasses override."""
        raise NotImplementedError

    def _fetch_all(self) -> list[dict]:
        if self._cache is not None:
            return self._cache

        if not platform.apify_api_token:
            logger.warning(f"{self.source}: APIFY_API_TOKEN not set — skipping")
            self._cache = []
            return self._cache

        actor_id = self._actor_id()
        if not actor_id:
            logger.warning(f"{self.source}: actor ID not configured — skipping")
            self._cache = []
            return self._cache

        url = f"{_BASE}/{actor_id}/run-sync-get-dataset-items"
        try:
            resp = httpx.post(
                url,
                params={"token": platform.apify_api_token},
                json=self.build_input(),
                timeout=_RUN_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else []
            logger.info(
                f"{self.source}: actor {actor_id} returned {len(items)} jobs "
                f"(cap {platform.apify_per_source_limit})"
            )
        except Exception as exc:
            logger.warning(f"{self.source}: Apify run failed: {exc}")
            items = []

        self._cache = items
        return self._cache

    @staticmethod
    def _parse_date(raw: dict) -> datetime | None:
        for key in ("postedAt", "publishedAt", "publishedDate", "datePosted", "postDate"):
            val = raw.get(key)
            if not val:
                continue
            val_str = str(val).strip().lower()
            # Handle relative strings: "2 days ago", "1 week ago", "3 hours ago"
            m = re.match(r"(\d+)\s+(hour|day|week|month)s?\s+ago", val_str)
            if m:
                n, unit = int(m.group(1)), m.group(2)
                now = datetime.now(tz=timezone.utc)
                if unit == "hour":
                    return now - timedelta(hours=n)
                if unit == "day":
                    return now - timedelta(days=n)
                if unit == "week":
                    return now - timedelta(weeks=n)
                if unit == "month":
                    return now - timedelta(days=n * 30)
            try:
                return datetime.fromisoformat(val_str.replace("z", "+00:00"))
            except (ValueError, TypeError):
                continue
        return None

    def _to_job(self, raw: dict) -> Job | None:
        """Subclasses override to handle their actor's response shape."""
        raise NotImplementedError

    @staticmethod
    def _title_match(raw_title: str, search_title: str) -> bool:
        tt = (raw_title or "").lower()
        return any(w in tt for w in search_title.lower().split() if len(w) > 2)

    @staticmethod
    def _location_match(raw_location: str, search_location: str) -> bool:
        sl = search_location.lower()
        rl = (raw_location or "").lower()
        if sl == "remote":
            return True
        if not rl:
            return True
        return sl in rl or any(city in rl for city in _INDIA_LOCATIONS)

    def search(self, title: str, location: str) -> list[Job]:
        matches: list[Job] = []
        for raw in self._fetch_all():
            job = self._to_job(raw)
            if job is None:
                continue
            if not self._title_match(job.title, title):
                continue
            if not self._location_match(job.location or "", location):
                continue
            matches.append(job)
        return matches


class ApifyLinkedInScraper(_BaseApifyScraper):
    source = "apify_linkedin"
    actor_id_attr = "apify_linkedin_actor"

    def build_input(self) -> dict:
        keywords = quote_plus(self.user_config.job_title)
        search_url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={keywords}&location=India&f_TPR=r604800&f_JT=F"
        )
        return {
            "urls": [search_url],
            "count": platform.apify_per_source_limit,
            "scrapeCompany": False,
        }

    def _to_job(self, raw: dict) -> Job | None:
        job_id = str(raw.get("id") or raw.get("link") or "").strip()
        if not job_id:
            return None
        salary_info = raw.get("salaryInfo")
        salary = salary_info[0] if isinstance(salary_info, list) and salary_info else None
        return Job(
            id=job_id,
            title=raw.get("title", ""),
            company=raw.get("companyName", ""),
            location=raw.get("location", ""),
            salary=salary,
            apply_url=raw.get("applyUrl") or raw.get("link", ""),
            source=self.source,
            posted_date=self._parse_date(raw),
            description=(raw.get("descriptionText") or raw.get("descriptionHtml") or "")[:2000],
        )



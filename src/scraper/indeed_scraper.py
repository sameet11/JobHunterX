"""Indeed scraper backed by SerpAPI's google_jobs engine.

SerpAPI is the most reliable way to fetch Indeed/Google Jobs results
without browser automation. Requires SERPAPI_KEY in .env.
"""

from __future__ import annotations

from typing import Any

import httpx

from config.platform_config import platform
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger
from src.utils.retry import with_retry

_SERPAPI_URL = "https://serpapi.com/search"


class IndeedScraper(BaseScraper):
    source = "indeed"
    engine = "google_jobs"

    def __init__(self, user_config, *, timeout: float = 30.0) -> None:
        super().__init__(user_config)
        self._client = httpx.Client(timeout=timeout)

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    @with_retry(httpx.HTTPError, attempts=3, initial_wait=1.0, max_wait=15.0)
    def search(self, title: str, location: str) -> list[Job]:
        if not platform.serpapi_key:
            logger.warning(f"SERPAPI_KEY missing — skipping {self.source} search")
            return []
        params = {
            "engine": self.engine,
            "q": f"{title} {self._site_filter()}",
            "location": location,
            "hl": "en",
            "api_key": platform.serpapi_key,
        }
        logger.info(f"SerpAPI ({self.engine}) search: {title!r} in {location!r}")
        response = self._client.get(_SERPAPI_URL, params=params)
        response.raise_for_status()
        body = response.json()
        listings = body.get("jobs_results", [])
        jobs = [self._to_job(item) for item in listings]
        logger.info(f"{self.source} returned {len(jobs)} jobs")
        return jobs

    def _site_filter(self) -> str:
        return "site:indeed.com"

    def _to_job(self, item: dict[str, Any]) -> Job:
        related = item.get("related_links") or []
        apply_url = ""
        for link in related:
            if "indeed" in (link.get("link") or "").lower():
                apply_url = link["link"]
                break
        if not apply_url:
            apply_options = item.get("apply_options") or []
            if apply_options:
                apply_url = apply_options[0].get("link", "")
        if not apply_url:
            apply_url = item.get("share_link", "")

        salary = None
        for ext in item.get("detected_extensions", {}).values():
            if isinstance(ext, str) and ("$" in ext or "₹" in ext or "LPA" in ext):
                salary = ext
                break

        return Job(
            id=str(item.get("job_id") or item.get("job_highlights", [{}])[0].get("title") or apply_url),
            title=item.get("title", ""),
            company=item.get("company_name", ""),
            location=item.get("location"),
            salary=salary,
            description=item.get("description", ""),
            apply_url=apply_url or "",
            easy_apply=False,
            posted_date=None,
            source=self.source,
        )


class GoogleJobsScraper(IndeedScraper):
    """Same SerpAPI engine; returns aggregated Google Jobs (not Indeed-restricted)."""

    source = "google_jobs"

    def _site_filter(self) -> str:
        return ""

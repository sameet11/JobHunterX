"""Fetches jobs from Lever's public posting API (no auth required).

Endpoint: https://api.lever.co/v0/postings/{company}?mode=json

Companies are configured in user_config.lever_companies as (display_name, slug) pairs.
All companies are fetched once per scraper instance and cached; subsequent search() calls
filter the cache locally.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from config.user_config import UserConfig
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_BASE = "https://api.lever.co/v0/postings"


class LeverScraper(BaseScraper):
    source = "lever"

    def __init__(self, user_config: UserConfig) -> None:
        super().__init__(user_config)
        self._cache: dict[str, list[dict]] | None = None

    def _fetch_all(self) -> dict[str, list[dict]]:
        """Fetch and cache all postings per company (API hit once per run)."""
        if self._cache is not None:
            return self._cache
        result: dict[str, list[dict]] = {}
        for name, slug in self.user_config.lever_companies:
            try:
                resp = httpx.get(
                    f"{_BASE}/{slug}",
                    params={"mode": "json"},
                    timeout=15,
                )
                if resp.status_code == 200:
                    raw = resp.json()
                    postings = raw if isinstance(raw, list) else []
                    for p in postings:
                        p["_company_name"] = name
                    result[slug] = postings
                    logger.debug(f"Lever {name}: {len(postings)} postings")
                else:
                    logger.warning(f"Lever {name} ({slug}): HTTP {resp.status_code}")
                    result[slug] = []
            except Exception as exc:
                logger.warning(f"Lever {name} ({slug}): {exc}")
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
        return sl in jl or "remote" in jl or not jl

    @staticmethod
    def _to_job(raw: dict) -> Job:
        posted = None
        created_ms = raw.get("createdAt")
        if created_ms:
            try:
                posted = datetime.fromtimestamp(int(created_ms) / 1000, tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass
        categories = raw.get("categories") or {}
        location = categories.get("location") or ""
        if isinstance(location, list):
            location = location[0] if location else ""
        return Job(
            id=raw.get("id", ""),
            title=raw.get("text", ""),
            company=raw.get("_company_name", ""),
            location=str(location),
            apply_url=raw.get("hostedUrl", ""),
            source="lever",
            posted_date=posted,
            description=(raw.get("descriptionPlain") or raw.get("description") or "")[:2000],
        )

    def search(self, title: str, location: str) -> list[Job]:
        matches: list[Job] = []
        for _slug, postings in self._fetch_all().items():
            for raw in postings:
                if not self._title_match(raw.get("text", ""), title):
                    continue
                categories = raw.get("categories") or {}
                job_location = categories.get("location") or ""
                if isinstance(job_location, list):
                    job_location = job_location[0] if job_location else ""
                if not self._location_match(str(job_location), location):
                    continue
                matches.append(self._to_job(raw))
        return matches

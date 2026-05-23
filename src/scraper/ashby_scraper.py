"""Fetches jobs from Ashby's public Job Board API (no auth required).

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}

Many companies that used to be on Greenhouse/Lever migrated to Ashby — including
Notion, Linear, Retool, Netlify, and many AI startups. Companies are configured
in user_config.ashby_companies as (display_name, board_slug) pairs.

All companies are fetched once per scraper instance and cached; subsequent
search() calls filter the cache locally.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from config.user_config import UserConfig
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_BASE = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyScraper(BaseScraper):
    source = "ashby"

    def __init__(self, user_config: UserConfig) -> None:
        super().__init__(user_config)
        self._cache: dict[str, list[dict]] | None = None

    def _fetch_all(self) -> dict[str, list[dict]]:
        if self._cache is not None:
            return self._cache
        result: dict[str, list[dict]] = {}
        companies = getattr(self.user_config, "ashby_companies", ())
        for name, slug in companies:
            try:
                resp = httpx.get(
                    f"{_BASE}/{slug}",
                    params={"includeCompensation": "true"},
                    timeout=15,
                )
                if resp.status_code == 200:
                    jobs = resp.json().get("jobs", [])
                    for j in jobs:
                        j["_company_name"] = name
                    result[slug] = jobs
                    logger.debug(f"Ashby {name}: {len(jobs)} jobs")
                else:
                    logger.warning(f"Ashby {name} ({slug}): HTTP {resp.status_code}")
                    result[slug] = []
            except Exception as exc:
                logger.warning(f"Ashby {name} ({slug}): {exc}")
                result[slug] = []
        self._cache = result
        return result

    @staticmethod
    def _title_match(job_title: str, search_title: str) -> bool:
        jt = (job_title or "").lower()
        return any(w in jt for w in search_title.lower().split() if len(w) > 2)

    @staticmethod
    def _location_match(job: dict, search_location: str) -> bool:
        sl = search_location.lower()
        is_remote = bool(job.get("isRemote"))
        location_str = (job.get("location") or job.get("locationName") or "").lower()
        if sl == "remote":
            return is_remote or "remote" in location_str
        return sl in location_str or is_remote or "remote" in location_str or not location_str

    @staticmethod
    def _parse_published(raw: dict) -> datetime | None:
        for key in ("publishedAt", "publishedDate", "updatedAt"):
            val = raw.get(key)
            if not val:
                continue
            try:
                return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
        return None

    @classmethod
    def _to_job(cls, raw: dict) -> Job:
        comp = raw.get("compensation") or {}
        salary = ""
        ranges = comp.get("compensationTierSummary") or comp.get("summary") or ""
        if isinstance(ranges, str):
            salary = ranges
        return Job(
            id=str(raw.get("id", "")),
            title=raw.get("title", ""),
            company=raw.get("_company_name", ""),
            location=raw.get("location") or raw.get("locationName") or "",
            salary=salary or None,
            apply_url=raw.get("applyUrl") or raw.get("jobUrl", ""),
            source="ashby",
            posted_date=cls._parse_published(raw),
            description=(raw.get("descriptionPlain") or raw.get("descriptionHtml") or "")[:2000],
        )

    def search(self, title: str, location: str) -> list[Job]:
        matches: list[Job] = []
        for _slug, raw_jobs in self._fetch_all().items():
            for raw in raw_jobs:
                if not self._title_match(raw.get("title", ""), title):
                    continue
                if not self._location_match(raw, location):
                    continue
                matches.append(self._to_job(raw))
        return matches

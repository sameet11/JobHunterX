"""Fetches jobs from Remotive's public Remote Jobs API (no auth required).

Endpoint: https://remotive.com/api/remote-jobs?category=software-dev&limit=500

Returns a JSON object with a 'jobs' array. Each job has publication_date so we
get accurate recency for prioritization. All-remote by definition.

Fetched once per scraper instance and cached; search() filters the cache.
"""
from __future__ import annotations

import html
import re
from datetime import datetime

import httpx

from config.user_config import UserConfig
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_ENDPOINT = "https://remotive.com/api/remote-jobs"
# Remotive uses its own category slugs. "software-dev" is the umbrella for engineers;
# we don't pass `search` so we can filter locally for all our title variants in one fetch.
_CATEGORY = "software-dev"
_LIMIT = 500


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(text).strip()


class RemotiveScraper(BaseScraper):
    source = "remotive"

    def __init__(self, user_config: UserConfig) -> None:
        super().__init__(user_config)
        self._cache: list[dict] | None = None

    def _fetch_all(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        try:
            resp = httpx.get(
                _ENDPOINT,
                params={"category": _CATEGORY, "limit": _LIMIT},
                timeout=20,
            )
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
            self._cache = jobs
            logger.info(f"Remotive: cached {len(jobs)} jobs")
        except Exception as exc:
            logger.warning(f"Remotive fetch failed: {exc}")
            self._cache = []
        return self._cache

    @staticmethod
    def _title_match(title: str, search_title: str) -> bool:
        tt = (title or "").lower()
        return any(w in tt for w in search_title.lower().split() if len(w) > 2)

    @staticmethod
    def _location_match(job: dict, search_location: str) -> bool:
        sl = search_location.lower()
        # All Remotive jobs are remote — treat "remote" search as match-all.
        if sl == "remote":
            return True
        req_loc = (job.get("candidate_required_location") or "").lower()
        if not req_loc or req_loc in ("worldwide", "anywhere"):
            return True
        return sl in req_loc

    @staticmethod
    def _parse_date(raw: dict) -> datetime | None:
        for key in ("publication_date", "created_at"):
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
        return Job(
            id=str(raw.get("id", "")),
            title=raw.get("title", ""),
            company=raw.get("company_name", ""),
            location=raw.get("candidate_required_location") or "Remote",
            salary=raw.get("salary") or None,
            apply_url=raw.get("url", ""),
            source="remotive",
            posted_date=cls._parse_date(raw),
            description=_strip_html(raw.get("description", ""))[:2000],
        )

    def search(self, title: str, location: str) -> list[Job]:
        matches: list[Job] = []
        for raw in self._fetch_all():
            if not self._title_match(raw.get("title", ""), title):
                continue
            if not self._location_match(raw, location):
                continue
            matches.append(self._to_job(raw))
        return matches

"""Fetches jobs from RemoteOK's public JSON API (no auth required).

Endpoint: https://remoteok.com/api

The response is a JSON array; the first element is legal/metadata and the rest
are job objects. RemoteOK requires a real-looking User-Agent — it returns 403
for default httpx headers.

Jobs are fetched once per scraper instance and cached; subsequent search()
calls filter the cache locally.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from config.user_config import UserConfig
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_ENDPOINT = "https://remoteok.com/api"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class RemoteOKScraper(BaseScraper):
    source = "remoteok"

    def __init__(self, user_config: UserConfig) -> None:
        super().__init__(user_config)
        self._cache: list[dict] | None = None

    def _fetch_all(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        try:
            resp = httpx.get(_ENDPOINT, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            # First element is legal/metadata — drop it.
            jobs = [item for item in data if isinstance(item, dict) and item.get("id")]
            self._cache = jobs
            logger.info(f"RemoteOK: cached {len(jobs)} jobs")
        except Exception as exc:
            logger.warning(f"RemoteOK fetch failed: {exc}")
            self._cache = []
        return self._cache

    @staticmethod
    def _title_match(position: str, search_title: str) -> bool:
        pt = (position or "").lower()
        return any(w in pt for w in search_title.lower().split() if len(w) > 2)

    @staticmethod
    def _location_match(job: dict, search_location: str) -> bool:
        # RemoteOK is by definition remote — every job qualifies for "remote" search.
        sl = search_location.lower()
        if sl == "remote":
            return True
        location = (job.get("location") or "").lower()
        # "Worldwide" and empty/global locations accept any city; otherwise require substring.
        if not location or location in ("worldwide", "anywhere", "global", "remote"):
            return True
        return sl in location

    @staticmethod
    def _parse_date(raw: dict) -> datetime | None:
        # Prefer epoch (integer seconds); fall back to ISO date string.
        epoch = raw.get("epoch")
        if epoch:
            try:
                return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass
        date_str = raw.get("date")
        if date_str:
            try:
                return datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        return None

    @classmethod
    def _to_job(cls, raw: dict) -> Job:
        salary = ""
        smin, smax = raw.get("salary_min"), raw.get("salary_max")
        if smin and smax:
            salary = f"${int(smin):,} - ${int(smax):,}"
        elif smin:
            salary = f"${int(smin):,}+"
        apply_url = raw.get("apply_url") or raw.get("url") or ""
        return Job(
            id=str(raw.get("id", "")),
            title=raw.get("position", ""),
            company=raw.get("company", ""),
            location=raw.get("location") or "Remote",
            salary=salary or None,
            apply_url=apply_url,
            source="remoteok",
            posted_date=cls._parse_date(raw),
            description=(raw.get("description") or "")[:2000],
        )

    def search(self, title: str, location: str) -> list[Job]:
        matches: list[Job] = []
        for raw in self._fetch_all():
            if not self._title_match(raw.get("position", ""), title):
                continue
            if not self._location_match(raw, location):
                continue
            matches.append(self._to_job(raw))
        return matches

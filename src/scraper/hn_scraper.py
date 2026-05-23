"""Scrapes job listings from "Ask HN: Who is Hiring?" threads via Algolia API.

Strategy:
  1. Find the most recent "Ask HN: Who is Hiring?" story via Algolia search.
  2. Fetch ALL comments from that story once and cache them.
  3. search(title, location) filters the cache locally — no repeated network calls.

Each comment is parsed best-effort: HN job posts typically start with
    Company | Role | Location | Remote/Onsite
The apply_url is the HN comment permalink.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from config.user_config import UserConfig
from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_ALGOLIA = "https://hn.algolia.com/api/v1"
_HN_ITEM = "https://news.ycombinator.com/item?id={}"
_HITS_PER_PAGE = 1000
_MAX_PAGES = 3  # fetch at most 3000 comments per thread
_RECENT_WINDOW_DAYS = 45  # only consider hiring stories posted in the last 45 days


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text).strip()


class HNScraper(BaseScraper):
    source = "hn"

    def __init__(self, user_config: UserConfig) -> None:
        super().__init__(user_config)
        self._story_id: Optional[str] = None
        self._all_comments: Optional[list[dict]] = None

    def _get_hiring_story_id(self) -> Optional[str]:
        """Return the objectID of the CURRENT month's 'Ask HN: Who is Hiring?' story.

        Algolia ranks the all-time most popular hiring story (March 2020, ~22665398)
        highest by default, so we restrict to stories created in the last 45 days
        AND sort by date so the freshest monthly thread wins.
        """
        if self._story_id:
            return self._story_id
        cutoff_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=_RECENT_WINDOW_DAYS)).timestamp())
        # search_by_date sorts results by created_at desc — the latest thread first.
        try:
            resp = httpx.get(
                f"{_ALGOLIA}/search_by_date",
                params={
                    "query": "Ask HN: Who is hiring",
                    "tags": "story,author_whoishiring",
                    "numericFilters": f"created_at_i>{cutoff_ts}",
                    "hitsPerPage": 5,
                },
                timeout=10,
            )
            resp.raise_for_status()
            for hit in resp.json().get("hits", []):
                title = hit.get("title") or hit.get("story_title") or ""
                if "who is hiring" in title.lower() and hit.get("objectID"):
                    self._story_id = hit["objectID"]
                    logger.info(f"HN: using story {self._story_id} — {title!r}")
                    return self._story_id
        except Exception as exc:
            logger.warning(f"HN: could not find hiring story: {exc}")
        return None

    def _fetch_all_comments(self) -> list[dict]:
        """Fetch and cache all comments from the current hiring thread."""
        if self._all_comments is not None:
            return self._all_comments
        story_id = self._get_hiring_story_id()
        if not story_id:
            self._all_comments = []
            return []
        comments: list[dict] = []
        for page in range(_MAX_PAGES):
            try:
                resp = httpx.get(
                    f"{_ALGOLIA}/search",
                    params={
                        "tags": f"comment,story_{story_id}",
                        "hitsPerPage": _HITS_PER_PAGE,
                        "page": page,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                hits = data.get("hits", [])
                comments.extend(hits)
                if data.get("nbPages", 1) <= page + 1:
                    break
            except Exception as exc:
                logger.warning(f"HN: failed to fetch comments page {page}: {exc}")
                break
        self._all_comments = comments
        logger.info(f"HN: cached {len(comments)} comments from story {story_id}")
        return self._all_comments

    @staticmethod
    def _parse_first_line(text: str) -> tuple[str, str, str]:
        """Extract (company, role, location) from the first line of a comment.

        HN job comments typically look like:
            Company | Role | Location | Remote | Salary
        """
        first_line = text.split("\n")[0].strip()
        parts = [p.strip() for p in first_line.split("|")]
        company = parts[0] if parts else "Unknown"
        role = parts[1] if len(parts) > 1 else ""
        location = parts[2] if len(parts) > 2 else ""
        return company, role, location

    def _to_job(self, hit: dict, fallback_title: str, fallback_location: str) -> Optional[Job]:
        raw_html = hit.get("comment_text") or ""
        text = _strip_html(raw_html)
        if len(text) < 20:
            return None
        company, role, location = self._parse_first_line(text)
        if not role:
            role = fallback_title
        if not location:
            location = fallback_location
        posted = None
        ts = hit.get("created_at_i")
        if ts:
            try:
                posted = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass
        return Job(
            id=hit["objectID"],
            title=role,
            company=company,
            location=location,
            apply_url=_HN_ITEM.format(hit["objectID"]),
            source=self.source,
            posted_date=posted,
            description=text[:2000],
        )

    def search(self, title: str, location: str) -> list[Job]:
        all_comments = self._fetch_all_comments()
        title_keywords = [w.lower() for w in title.split() if len(w) > 2]
        location_lower = location.lower()
        jobs: list[Job] = []
        for hit in all_comments:
            text = _strip_html(hit.get("comment_text") or "").lower()
            if not any(kw in text for kw in title_keywords):
                continue
            if location_lower != "remote" and location_lower not in text and "remote" not in text:
                continue
            job = self._to_job(hit, title, location)
            if job:
                jobs.append(job)
        return jobs

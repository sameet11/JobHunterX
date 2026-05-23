"""LinkedIn-side outreach: DM existing 1st-degree connections OR send connection requests.

For each applied company:

  1. `find_company_people(company)` → list of employees found via Google
     search (site:linkedin.com/in). Uses GoogleSearchRecruiterFinder internally.
  2. For each person:
       - `is_connection(person)` True  → send DM via LinkedIn API (LINKEDIN_MSG).
       - `is_connection(person)` False → send connection request with a short
         note (LINKEDIN_INVITE).

Backends:
  * `MockLinkedInOutreach`     : deterministic, used by tests and dry-runs.
  * `LinkedInApiOutreach`      : real LinkedIn via linkedin-api (unofficial API).
                                 Requires LINKEDIN_EMAIL + LINKEDIN_PASSWORD.

Set `linkedin_outreach_backend: "linkedin_api"` in user_config.py to use the
real backend.
"""

from __future__ import annotations

import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from config.platform_config import platform
from src.models import Recruiter
from src.utils.logger import logger

if TYPE_CHECKING:
    from src.outreach.recruiter_finder import GoogleSearchRecruiterFinder

_SLUG_RE = re.compile(r"linkedin\.com/in/([^/?#]+)")


@dataclass(frozen=True)
class LinkedInActionResult:
    success: bool
    action: str  # "dm" | "invite"
    detail: str = ""
    error: str = ""


class BaseLinkedInOutreach(ABC):
    """Shared interface so the orchestrator can stay agnostic of the backend."""

    @abstractmethod
    def find_company_people(
        self, company: str, *, max_results: int = 5
    ) -> list[Recruiter]:
        """Return up to N people surfaced from the company's LinkedIn page."""

    @abstractmethod
    def is_connection(self, person: Recruiter) -> bool:
        """True if `person` is already a 1st-degree connection."""

    @abstractmethod
    def send_dm(self, person: Recruiter, *, subject: str, body: str) -> LinkedInActionResult:
        """Send a LinkedIn DM. `subject` is informational (LinkedIn DMs are subject-less)."""

    @abstractmethod
    def send_connection_request(
        self, person: Recruiter, *, note: str
    ) -> LinkedInActionResult:
        """Send a connection request with a custom note (≤300 chars)."""


# ───── Mock backend (tests + dry-run) ─────


class MockLinkedInOutreach(BaseLinkedInOutreach):
    """Deterministic fixture data so the pipeline can be exercised offline."""

    _RECRUITER_TITLES = ("Recruiter", "Talent", "HR", "People", "Hiring")

    def __init__(
        self,
        *,
        people_by_company: Optional[dict[str, list[Recruiter]]] = None,
        connection_emails: Optional[set[str]] = None,
        connection_urls: Optional[set[str]] = None,
        record: bool = True,
    ) -> None:
        self._people_by_company = people_by_company or {}
        self._connection_emails = {e.lower() for e in (connection_emails or set())}
        self._connection_urls = {u.lower() for u in (connection_urls or set())}
        self.record = record
        self.dms_sent: list[Recruiter] = []
        self.invites_sent: list[Recruiter] = []

    def find_company_people(
        self, company: str, *, max_results: int = 5
    ) -> list[Recruiter]:
        people = list(self._people_by_company.get(company.lower(), ()))
        if not people:
            # Synthesize one recruiter per unknown company so tests can run.
            slug = company.lower().replace(" ", "")
            people = [
                Recruiter(
                    name=f"Recruiter at {company}",
                    title="Talent Acquisition",
                    email=f"recruiter@{slug}.com",
                    company=company,
                    source="linkedin",
                    confidence=70,
                    linkedin_url=f"https://www.linkedin.com/in/{slug}-recruiter",
                )
            ]
        # Recruiter-ish titles first.
        people.sort(
            key=lambda r: 0 if any(k in r.title for k in self._RECRUITER_TITLES) else 1
        )
        return people[:max_results]

    def is_connection(self, person: Recruiter) -> bool:
        if person.email and person.email.lower() in self._connection_emails:
            return True
        if person.linkedin_url and person.linkedin_url.lower() in self._connection_urls:
            return True
        return False

    def send_dm(self, person: Recruiter, *, subject: str, body: str) -> LinkedInActionResult:
        if self.record:
            self.dms_sent.append(person)
        logger.info(f"[mock-linkedin] DM to {person.name} @ {person.company}")
        return LinkedInActionResult(success=True, action="dm", detail="mock-dm-sent")

    def send_connection_request(
        self, person: Recruiter, *, note: str
    ) -> LinkedInActionResult:
        if self.record:
            self.invites_sent.append(person)
        logger.info(
            f"[mock-linkedin] connection request to {person.name} @ {person.company}"
        )
        return LinkedInActionResult(
            success=True, action="invite", detail="mock-invite-sent"
        )


# ───── linkedin-api backend (real LinkedIn) ─────


class LinkedInApiOutreach(BaseLinkedInOutreach):
    """Real LinkedIn outreach via the linkedin-api library (unofficial API).

    Flow per person:
      1. find_company_people  → Google site:linkedin.com/in search (GoogleSearchRecruiterFinder).
      2. is_connection        → api.get_profile(slug) + distance.value == "DISTANCE_1".
      3. send_dm              → api.send_message(body, recipients=[entity_urn]).  1st-degree only.
      4. send_connection_request → api.add_connection(slug, message=note[:300]).

    Constructor accepts `_api` for dependency injection in tests (avoids real credentials).
    """

    _RECRUITER_KEYWORDS = ("recruiter", "talent", "hiring", "hr", "people", "sourcer")
    _SEARCH_TITLE_QUERY = "recruiter OR talent OR hiring"

    def __init__(
        self,
        *,
        _api=None,
        recruiter_finder: Optional["GoogleSearchRecruiterFinder"] = None,
        min_delay_seconds: int = 30,
        max_delay_seconds: int = 120,
    ) -> None:
        if _api is not None:
            self._api = _api
        else:
            from linkedin_api import Linkedin  # deferred — not installed in test envs without venv
            from src.outreach.browser_cookies import extract_linkedin_cookies

            li_at, jsess = extract_linkedin_cookies()
            if not li_at:
                raise RuntimeError(
                    "Could not read LinkedIn session from any browser. "
                    "Log into linkedin.com in Chrome/Edge/Firefox and retry."
                )

            from requests.cookies import RequestsCookieJar
            jar = RequestsCookieJar()
            jar.set("li_at", li_at, domain=".www.linkedin.com")
            if jsess:
                jar.set("JSESSIONID", jsess.strip('"'), domain=".www.linkedin.com")
            self._api = Linkedin("", "", cookies=jar)
            logger.info("LinkedIn API: authenticated via browser session cookies")

        self._finder = recruiter_finder
        self._min_delay = min_delay_seconds
        self._max_delay = max_delay_seconds
        self._first_search = True

    # ── interface ────────────────────────────────────────────────────────────

    def find_company_people(self, company: str, *, max_results: int = 5) -> list[Recruiter]:
        """Find recruiters at `company` via LinkedIn search using session cookies.

        Human-like behaviour:
          * Random 30–120s delay between successive company searches
          * Single broad search per company (no pagination)
          * Returns at most max_results matches
        """
        # Pace ourselves between companies to avoid LinkedIn's bot detection.
        if not self._first_search:
            delay = random.uniform(self._min_delay, self._max_delay)
            logger.info(f"LinkedIn: pacing {delay:.0f}s before searching {company}")
            time.sleep(delay)
        self._first_search = False

        try:
            results = self._api.search_people(
                keywords=company,
                keyword_title=self._SEARCH_TITLE_QUERY,
                limit=max_results * 4,
            )
        except Exception as exc:
            logger.warning(f"LinkedIn search failed for {company}: {exc}")
            return []

        recruiters: list[Recruiter] = []
        for entry in results or []:
            title = (entry.get("jobtitle") or entry.get("subtitle") or "").strip()
            title_l = title.lower()
            if title_l and not any(kw in title_l for kw in self._RECRUITER_KEYWORDS):
                continue
            slug = entry.get("public_id") or ""
            name = entry.get("name") or slug or "Unknown"
            if not slug:
                continue
            recruiters.append(Recruiter(
                name=name,
                title=title,
                email="",  # LinkedIn does not expose emails
                company=company,
                source="linkedin_cookies",
                confidence=80,
                linkedin_url=f"https://www.linkedin.com/in/{slug}",
            ))
            if len(recruiters) >= max_results:
                break

        logger.info(f"LinkedIn: found {len(recruiters)} recruiter(s) at {company}")
        return recruiters

    def is_connection(self, person: Recruiter) -> bool:
        """Return True if `person` is a 1st-degree LinkedIn connection."""
        slug = self._slug(person.linkedin_url)
        if not slug:
            return False
        try:
            profile = self._api.get_profile(slug)
            return (profile.get("distance") or {}).get("value") == "DISTANCE_1"
        except Exception as exc:
            logger.warning(f"LinkedIn API: connection check failed for {slug!r}: {exc}")
            return False

    def send_dm(self, person: Recruiter, *, subject: str, body: str) -> LinkedInActionResult:
        """Send a LinkedIn DM to a 1st-degree connection."""
        slug = self._slug(person.linkedin_url)
        if not slug:
            return LinkedInActionResult(success=False, action="dm", error="no_linkedin_url")
        try:
            profile = self._api.get_profile(slug)
            urn = profile.get("entityUrn") or profile.get("member_urn", "")
            if not urn:
                return LinkedInActionResult(success=False, action="dm", error="no_entity_urn")
            self._api.send_message(body, recipients=[urn])
            logger.info(f"LinkedIn DM sent → {person.name} ({slug})")
            return LinkedInActionResult(success=True, action="dm", detail=f"dm:{slug}")
        except Exception as exc:
            logger.warning(f"LinkedIn DM failed for {person.name}: {exc}")
            return LinkedInActionResult(success=False, action="dm", error=str(exc))

    def send_connection_request(self, person: Recruiter, *, note: str) -> LinkedInActionResult:
        """Send a LinkedIn connection request (note ≤ 300 chars)."""
        slug = self._slug(person.linkedin_url)
        if not slug:
            return LinkedInActionResult(success=False, action="invite", error="no_linkedin_url")
        try:
            self._api.add_connection(profile_public_id=slug, message=note[:300])
            logger.info(f"LinkedIn invite sent → {person.name} ({slug})")
            return LinkedInActionResult(success=True, action="invite", detail=f"invite:{slug}")
        except Exception as exc:
            logger.warning(f"LinkedIn invite failed for {person.name}: {exc}")
            return LinkedInActionResult(success=False, action="invite", error=str(exc))

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _slug(linkedin_url: str) -> Optional[str]:
        if not linkedin_url:
            return None
        m = _SLUG_RE.search(linkedin_url)
        return m.group(1).rstrip("/") if m else None

    def _get_finder(self) -> "GoogleSearchRecruiterFinder":
        if self._finder is None:
            from src.outreach.recruiter_finder import GoogleSearchRecruiterFinder
            self._finder = GoogleSearchRecruiterFinder()
        return self._finder


def get_linkedin_outreach(source: str = "mock") -> BaseLinkedInOutreach:
    """Factory — 'mock' (offline / tests) or 'linkedin_api' (real LinkedIn)."""
    key = source.lower()
    if key == "mock":
        return MockLinkedInOutreach()
    if key == "linkedin_api":
        return LinkedInApiOutreach()
    raise ValueError(f"Unknown linkedin outreach backend: {source}")

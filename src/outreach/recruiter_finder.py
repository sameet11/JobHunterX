"""Find recruiters / HRs / hiring managers for a target company.

Sources:
- mock:          deterministic dummy data (for testing + dry-run)
- hunter:        Hunter.io domain search API
- google_search: Google site:linkedin.com/in search → name slug → email guess → optional
                 Hunter.io verification for FAANG (25 free calls/month)

Returns up to N candidates per company, ranked by confidence.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from config.platform_config import platform
from src.models import Recruiter
from src.utils.logger import logger


class BaseRecruiterFinder(ABC):
    """Abstract finder. Subclasses implement find()."""

    @abstractmethod
    def find(self, company: str, max_results: int = 3) -> list[Recruiter]:
        """Return up to max_results recruiters for the given company."""


class MockRecruiterFinder(BaseRecruiterFinder):
    """Returns deterministic dummy recruiters per company. Used for tests + dry-run."""

    _DUMMY = {
        "google": [
            ("Priya Sharma", "Senior Technical Recruiter", "priya.sharma@google.com"),
            ("Rajesh Kumar", "Engineering Manager", "rajesh.k@google.com"),
            ("Anita Desai", "HR Business Partner", "anita.d@google.com"),
        ],
        "techcorp": [
            ("Maya Patel", "Talent Acquisition Lead", "maya@techcorp.com"),
            ("Arjun Singh", "VP Engineering", "arjun@techcorp.com"),
        ],
        "startupxyz": [
            ("Sneha Iyer", "Founding Recruiter", "sneha@startupxyz.com"),
        ],
    }

    def find(self, company: str, max_results: int = 3) -> list[Recruiter]:
        key = company.lower().strip()
        # Generic fallback: synthesize one recruiter per unknown company
        people = self._DUMMY.get(key) or [
            (f"Hiring Manager {company}", "Talent Acquisition", f"careers@{key.replace(' ', '')}.com")
        ]
        return [
            Recruiter(
                name=name,
                title=title,
                email=email,
                company=company,
                source="mock",
                confidence=85,
                linkedin_url=f"https://www.linkedin.com/in/{name.lower().replace(' ', '-')}",
            )
            for name, title, email in people[:max_results]
        ]


class HunterRecruiterFinder(BaseRecruiterFinder):
    """Uses Hunter.io domain search. Requires HUNTER_API_KEY."""

    _BASE_URL = "https://api.hunter.io/v2/domain-search"
    _RECRUITER_TITLES = (
        "recruiter",
        "talent",
        "hr",
        "hiring",
        "people",
        "engineering manager",
        "head of",
    )

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or platform.hunter_api_key
        if not self.api_key:
            raise RuntimeError("HUNTER_API_KEY not set in .env")

    def find(self, company: str, max_results: int = 3) -> list[Recruiter]:
        domain = self._guess_domain(company)
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    self._BASE_URL,
                    params={
                        "domain": domain,
                        "api_key": self.api_key,
                        "department": "hr,management,executive",
                        "limit": max_results * 3,
                    },
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
        except Exception as exc:
            logger.warning(f"Hunter.io lookup failed for {company}: {exc}")
            return []

        emails = data.get("emails", [])
        ranked: list[Recruiter] = []
        for entry in emails:
            position = (entry.get("position") or "").lower()
            if not any(kw in position for kw in self._RECRUITER_TITLES):
                continue
            full_name = " ".join(filter(None, [entry.get("first_name"), entry.get("last_name")]))
            if not full_name:
                continue
            ranked.append(
                Recruiter(
                    name=full_name,
                    title=entry.get("position") or "",
                    email=entry.get("value") or "",
                    company=company,
                    source="hunter",
                    confidence=int(entry.get("confidence") or 0),
                    linkedin_url=entry.get("linkedin") or "",
                )
            )
        ranked.sort(key=lambda r: -r.confidence)
        return ranked[:max_results]

    @staticmethod
    def _guess_domain(company: str) -> str:
        slug = company.lower().strip().replace(" ", "").replace(",", "").replace(".", "")
        return f"{slug}.com"


class GoogleSearchRecruiterFinder(BaseRecruiterFinder):
    """Finds people via Google search → LinkedIn slug → email guess → optional Hunter verify.

    Flow per company:
      1. GET google.com/search?q=site:linkedin.com/in "{company}" "software engineer" "India"
      2. Parse top LinkedIn profile URLs from the result HTML (requests + BeautifulSoup).
      3. Extract first/last name from the URL slug.
      4. Generate email candidates: firstname@, firstname.lastname@, flastname@.
      5. For FAANG companies: verify the top guess via Hunter.io free API (25 calls/month).
      6. Return one Recruiter per profile with the best email guess.
    """

    _SEARCH_URL = "https://www.google.com/search"
    _VERIFY_URL = "https://api.hunter.io/v2/email-verifier"
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Spend the 25 free Hunter.io verifications/month only on these companies.
    HUNTER_VERIFY_COMPANIES: frozenset[str] = frozenset({
        "google", "meta", "amazon", "apple", "microsoft",
        "stripe", "airbnb", "uber", "netflix", "openai", "anthropic",
    })

    _KNOWN_DOMAINS: dict[str, str] = {
        "google": "google.com",
        "meta": "meta.com",
        "amazon": "amazon.com",
        "apple": "apple.com",
        "microsoft": "microsoft.com",
        "stripe": "stripe.com",
        "airbnb": "airbnb.com",
        "uber": "uber.com",
        "netflix": "netflix.com",
        "openai": "openai.com",
        "anthropic": "anthropic.com",
        "linkedin": "linkedin.com",
        "flipkart": "flipkart.com",
        "razorpay": "razorpay.com",
        "swiggy": "swiggy.in",
        "zomato": "zomato.com",
        "meesho": "meesho.com",
        "cred": "cred.club",
        "zepto": "zepto.com",
        "phonepe": "phonepe.com",
        "paytm": "paytm.com",
    }

    def __init__(self, hunter_api_key: Optional[str] = None) -> None:
        self.hunter_api_key = hunter_api_key or platform.hunter_api_key

    # ── public ──────────────────────────────────────────────────────────────

    def find(self, company: str, max_results: int = 3) -> list[Recruiter]:
        linkedin_urls = self._google_search(company, limit=10)
        if not linkedin_urls:
            logger.info(f"GoogleSearch: no LinkedIn profiles found for {company!r}")
            return []

        domain = self._guess_domain(company)
        do_verify = bool(
            self.hunter_api_key
            and company.lower().strip() in self.HUNTER_VERIFY_COMPANIES
        )

        results: list[Recruiter] = []
        for url in linkedin_urls[:max_results]:
            profile = self._parse_slug(url)
            if not profile:
                continue
            first, last = profile
            guesses = self._email_guesses(first, last, domain)
            top_email = guesses[0]
            confidence = 0

            if do_verify:
                ok, score = self._hunter_verify(top_email)
                if ok:
                    confidence = score
                    logger.debug(f"Hunter verified {top_email}: score={score}")
                else:
                    # Try next guess if top didn't verify
                    for alt in guesses[1:]:
                        ok, score = self._hunter_verify(alt)
                        if ok:
                            top_email = alt
                            confidence = score
                            break
                time.sleep(1)  # stay well under Hunter.io rate limit

            results.append(Recruiter(
                name=f"{first.title()} {last.title()}",
                title="",
                email=top_email,
                company=company,
                linkedin_url=url,
                source="google_search",
                confidence=confidence,
            ))

        logger.info(
            f"GoogleSearch: found {len(results)} profile(s) for {company!r} "
            f"(domain={domain}, hunter_verify={do_verify})"
        )
        return results

    # ── helpers ─────────────────────────────────────────────────────────────

    def _google_search(self, company: str, limit: int = 10) -> list[str]:
        query = f'site:linkedin.com/in "{company}" "software engineer" "India"'
        try:
            resp = httpx.get(
                self._SEARCH_URL,
                params={"q": query, "num": limit},
                headers=self._HEADERS,
                timeout=15,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.warning(f"Google search HTTP {resp.status_code} for {company!r}")
                return []
            if "unusual traffic" in resp.text.lower() or "captcha" in resp.text.lower():
                logger.warning("Google returned CAPTCHA — reduce search frequency")
                return []
            return self._extract_linkedin_urls(resp.text, limit)
        except Exception as exc:
            logger.warning(f"Google search failed for {company!r}: {exc}")
            return []

    @staticmethod
    def _extract_linkedin_urls(html: str, limit: int) -> list[str]:
        """Pull unique linkedin.com/in/ URLs from Google result HTML."""
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        urls: list[str] = []
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            # Google wraps links as /url?q=https://www.linkedin.com/in/...
            if "linkedin.com/in/" not in href:
                continue
            m = re.search(r"(https?://(?:www\.)?linkedin\.com/in/[^&\s\"'?#]+)", href)
            if not m:
                continue
            url = m.group(1).rstrip("/")
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    @staticmethod
    def _parse_slug(linkedin_url: str) -> Optional[tuple[str, str]]:
        """Return (first, last) extracted from a LinkedIn URL slug, or None.

        linkedin.com/in/priya-sharma-a1b2c3 → ("priya", "sharma")
        linkedin.com/in/rajesh-kumar-123456 → ("rajesh", "kumar")
        """
        m = re.search(r"linkedin\.com/in/([^/?#]+)", linkedin_url)
        if not m:
            return None
        slug = m.group(1).lower()
        # Keep only purely alphabetic parts — filters numeric IDs and alphanumeric hashes.
        parts = [p for p in slug.split("-") if p.isalpha()]
        if len(parts) < 2:
            return None
        return parts[0], parts[1]  # first, last (ignore credentials/suffixes)

    @staticmethod
    def _email_guesses(first: str, last: str, domain: str) -> list[str]:
        """Return email candidates in priority order."""
        return [
            f"{first}@{domain}",
            f"{first}.{last}@{domain}",
            f"{first[0]}{last}@{domain}",
        ]

    def _guess_domain(self, company: str) -> str:
        key = company.lower().strip()
        if key in self._KNOWN_DOMAINS:
            return self._KNOWN_DOMAINS[key]
        slug = "".join(c for c in key if c.isalnum())
        return f"{slug}.com"

    def _hunter_verify(self, email: str) -> tuple[bool, int]:
        """Verify one email via Hunter.io. Returns (deliverable, score)."""
        try:
            resp = httpx.get(
                self._VERIFY_URL,
                params={"email": email, "api_key": self.hunter_api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return data.get("result") == "deliverable", int(data.get("score") or 0)
        except Exception as exc:
            logger.warning(f"Hunter.io verify failed for {email}: {exc}")
            return False, 0


def get_recruiter_finder(source: str = "mock") -> BaseRecruiterFinder:
    """Factory: returns finder for given source ('mock' | 'hunter' | 'google_search')."""
    key = source.lower()
    if key == "mock":
        return MockRecruiterFinder()
    if key == "hunter":
        return HunterRecruiterFinder()
    if key == "google_search":
        return GoogleSearchRecruiterFinder()
    raise ValueError(f"Unknown recruiter finder source: {source}")

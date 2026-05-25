"""Heuristic resume↔JD match scoring used as a cheap pre-filter before Claude.

Boosts (stack additively, final score capped at 100):
  * recency       — exponential decay over `recency_hours_threshold` (default 168h).
                    Full boost at 0h, half at ~24h, ~3% at 72h, 0 past threshold.
  * india         — flat bump for jobs located in Indian cities.
  * priority co.  — flat bump for jobs at big/famous companies the user cares about.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Iterable

from src.models import Job

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#\-]*")

_INDIA_LOCATIONS = {
    "mumbai", "bangalore", "bengaluru", "hyderabad", "pune",
    "delhi", "noida", "gurugram", "gurgaon", "chennai", "kolkata",
    "india", "ncr",
}


def _tokens(text: str) -> set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(text or "")}


def _normalize_company(name: str) -> str:
    """Lowercase, strip suffixes/punctuation so 'Razorpay Pvt. Ltd.' == 'Razorpay'."""
    s = name.lower()
    s = re.sub(r"[.,&]", " ", s)
    s = re.sub(
        r"\b(pvt|private|ltd|limited|inc|incorporated|llc|corp|corporation|"
        r"co|company|gmbh|technologies|technology|tech|solutions|software|"
        r"india|labs|systems|services)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


class MatchScorer:
    """Lightweight overlap-based scoring. Use BEFORE the LLM for cost control."""

    def __init__(
        self,
        candidate_skills: Iterable[str],
        *,
        recency_weight: float = 0.2,
        recency_hours_threshold: int = 168,
        india_location_boost: float = 0.45,
        priority_companies: Iterable[str] = (),
        priority_company_boost: float = 0.35,
    ) -> None:
        self.candidate_skill_tokens = {s.lower() for s in candidate_skills}
        self.recency_weight = recency_weight
        self.recency_hours_threshold = recency_hours_threshold
        self.india_location_boost = india_location_boost
        self.priority_company_boost = priority_company_boost
        self.priority_companies = {_normalize_company(c) for c in priority_companies if c}

    def score(self, job: Job) -> int:
        if not self.candidate_skill_tokens:
            return 0
        jd_tokens = _tokens(job.description) | _tokens(job.title)
        if not jd_tokens:
            return 0
        overlap = self.candidate_skill_tokens & jd_tokens
        denom = min(len(self.candidate_skill_tokens), 15)
        ratio = len(overlap) / max(1, denom)
        base_score = min(100, int(ratio * 100))

        recency_boost = self._recency_boost(job)
        india_boost = self.india_location_boost if self._is_india_location(job) else 0.0
        priority_boost = self.priority_company_boost if self._is_priority_company(job) else 0.0

        final_score = int(
            base_score
            + (100 * recency_boost)
            + (100 * india_boost)
            + (100 * priority_boost)
        )
        return min(100, final_score)

    def _recency_boost(self, job: Job) -> float:
        """Exponential decay across the recency window.

        At hours_old == 0    → full `recency_weight`
        At hours_old == 24   → ~50% of `recency_weight`
        At hours_old == 72   → ~3% of `recency_weight`
        At hours_old >= threshold → 0
        """
        if not job.posted_date:
            return 0.0
        now = datetime.now(timezone.utc)
        posted = job.posted_date
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        hours_old = (now - posted).total_seconds() / 3600
        if hours_old < 0 or hours_old >= self.recency_hours_threshold:
            return 0.0
        # half-life of 24h => decay constant ln(2)/24
        return self.recency_weight * math.exp(-math.log(2) * hours_old / 24.0)

    @staticmethod
    def _is_india_location(job: Job) -> bool:
        loc = (job.location or "").lower()
        return any(city in loc for city in _INDIA_LOCATIONS)

    def _is_priority_company(self, job: Job) -> bool:
        if not self.priority_companies:
            return False
        norm = _normalize_company(job.company)
        if norm in self.priority_companies:
            return True
        # Allow partial match either way (e.g. config has "Microsoft", JD has "Microsoft India")
        return any(p and (p in norm or norm in p) for p in self.priority_companies if len(p) >= 4)

    def matched_skills(self, job: Job) -> list[str]:
        jd_tokens = _tokens(job.description) | _tokens(job.title)
        return sorted(self.candidate_skill_tokens & jd_tokens)

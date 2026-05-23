"""Heuristic resume↔JD match scoring used as a cheap pre-filter before Claude.

Includes job recency boost: recently posted jobs (within threshold) get a score bump
to prioritize applying to fresh postings.

Includes India location boost: jobs located in Indian cities rank higher than
remote-worldwide or non-India postings.
"""

from __future__ import annotations

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


class MatchScorer:
    """Lightweight overlap-based scoring. Use BEFORE the LLM for cost control.

    Boosts:
      - recency: jobs posted within recency_hours_threshold get up to +recency_weight
      - india location: jobs in Indian cities get +india_location_boost
    """

    def __init__(
        self,
        candidate_skills: Iterable[str],
        *,
        recency_weight: float = 0.2,
        recency_hours_threshold: int = 24,
        india_location_boost: float = 0.15,
    ) -> None:
        self.candidate_skill_tokens = {s.lower() for s in candidate_skills}
        self.recency_weight = recency_weight
        self.recency_hours_threshold = recency_hours_threshold
        self.india_location_boost = india_location_boost

    def score(self, job: Job) -> int:
        if not self.candidate_skill_tokens:
            return 0
        jd_tokens = _tokens(job.description) | _tokens(job.title)
        if not jd_tokens:
            return 0
        overlap = self.candidate_skill_tokens & jd_tokens
        # Score = overlap relative to what a "full-match" JD would require.
        # Dividing by all candidate skills (120+) makes scores impossibly low.
        # A typical JD mentions 10-15 relevant skills; cap denominator at 15.
        denom = min(len(self.candidate_skill_tokens), 15)
        ratio = len(overlap) / max(1, denom)
        base_score = min(100, int(ratio * 100))

        # Recency boost: jobs posted within threshold get a bump
        recency_boost = self._recency_boost(job)
        # India location boost: jobs in Indian cities rank above non-India postings
        india_boost = self.india_location_boost if self._is_india_location(job) else 0.0
        final_score = int(base_score + (100 * recency_boost) + (100 * india_boost))
        return min(100, final_score)

    def _recency_boost(self, job: Job) -> float:
        """Return boost amount (0.0–recency_weight) based on posted_date."""
        if not job.posted_date:
            return 0.0
        # Handle both aware and naive datetimes
        now = datetime.now(timezone.utc)
        posted = job.posted_date
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        age = now - posted
        hours_old = age.total_seconds() / 3600
        if hours_old < self.recency_hours_threshold:
            # Linear boost: 1.0 at age 0, 0.0 at threshold
            factor = 1.0 - (hours_old / self.recency_hours_threshold)
            return self.recency_weight * factor
        return 0.0

    @staticmethod
    def _is_india_location(job: Job) -> bool:
        loc = (job.location or "").lower()
        return any(city in loc for city in _INDIA_LOCATIONS)

    def matched_skills(self, job: Job) -> list[str]:
        jd_tokens = _tokens(job.description) | _tokens(job.title)
        return sorted(self.candidate_skill_tokens & jd_tokens)

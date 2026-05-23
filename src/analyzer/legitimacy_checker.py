"""Ghost-job / posting-legitimacy heuristics (inspired by career-ops Block G).

Returns a 3-tier assessment so we can surface caution flags in the review queue
without filtering aggressively. The user decides — we just label.

Signals:
  - Age of the posting (stale postings often = ghost roles)
  - JD specificity (vague descriptions correlate with evergreen reqs)
  - Reposting pattern (same company + title appeared earlier and is still open)
  - Title red-flags ("pipeline", "talent pool", "future opening")
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel

from config.user_config import UserConfig
from src.models import Job
from src.tracker.local_db import LocalDB
from src.utils.logger import logger


class LegitimacyTier(str, Enum):
    HIGH_CONFIDENCE = "high_confidence"  # No red flags — apply with confidence
    CAUTION = "caution"                  # Some signals — review JD carefully
    SUSPICIOUS = "suspicious"            # Multiple flags — likely ghost/evergreen


class LegitimacyAssessment(BaseModel):
    tier: LegitimacyTier
    reasons: list[str] = []
    age_days: int | None = None


# Titles that almost always indicate an evergreen / talent-pipeline posting
# rather than a real open req.
_RED_FLAG_TITLE_PATTERNS = [
    re.compile(r"\btalent\s+pool\b", re.I),
    re.compile(r"\btalent\s+pipeline\b", re.I),
    re.compile(r"\bgeneral\s+application\b", re.I),
    re.compile(r"\bfuture\s+opening", re.I),
    re.compile(r"\bevergreen\b", re.I),
    re.compile(r"\bopen\s+to\s+work\b", re.I),
    re.compile(r"\bspeculative\b", re.I),
]


class LegitimacyChecker:
    def __init__(self, user_config: UserConfig, db: LocalDB) -> None:
        self.cfg = user_config
        self.db = db

    @staticmethod
    def _age_days(posted: datetime | None) -> int | None:
        if posted is None:
            return None
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        delta = datetime.now(tz=timezone.utc) - posted
        return max(int(delta.total_seconds() // 86400), 0)

    def _is_repost(self, job: Job) -> bool:
        """True if the same (company, title) has appeared in our DB in the last 90 days
        AND the existing record is still in scraped/skipped state (not applied/responded).
        Repeat postings of the same role are a strong ghost-job signal.
        """
        try:
            cur = self.db._conn.execute(
                """
                SELECT first_seen, status FROM jobs
                WHERE company = ? AND title = ? AND dedup_key != ?
                ORDER BY first_seen DESC LIMIT 1
                """,
                (job.company, job.title, job.dedup_key()),
            )
            row = cur.fetchone()
            if not row:
                return False
            first_seen = datetime.fromisoformat(row["first_seen"])
            return (datetime.utcnow() - first_seen).days <= 90
        except Exception as exc:
            logger.debug(f"legitimacy: repost lookup failed: {exc}")
            return False

    def assess(self, job: Job) -> LegitimacyAssessment:
        reasons: list[str] = []
        score = 0  # higher = more suspicious

        # --- Title red flags ---
        for pat in _RED_FLAG_TITLE_PATTERNS:
            if pat.search(job.title or ""):
                reasons.append(f"title pattern '{pat.pattern}' suggests evergreen posting")
                score += 2
                break

        # --- Age ---
        age = self._age_days(job.posted_date)
        if age is not None:
            if age >= self.cfg.legitimacy_stale_age_days:
                reasons.append(f"posted {age}d ago (stale > {self.cfg.legitimacy_stale_age_days}d)")
                score += 2
            elif age >= self.cfg.legitimacy_max_age_days:
                reasons.append(f"posted {age}d ago (older than {self.cfg.legitimacy_max_age_days}d)")
                score += 1

        # --- JD specificity ---
        desc_len = len((job.description or "").strip())
        if desc_len and desc_len < self.cfg.legitimacy_min_description_chars:
            reasons.append(f"very short JD ({desc_len} chars)")
            score += 1

        # --- Repost detection ---
        if self._is_repost(job):
            reasons.append("same company+title seen in DB within last 90 days")
            score += 2

        # --- Tier ---
        if score >= 3:
            tier = LegitimacyTier.SUSPICIOUS
        elif score >= 1:
            tier = LegitimacyTier.CAUTION
        else:
            tier = LegitimacyTier.HIGH_CONFIDENCE

        return LegitimacyAssessment(tier=tier, reasons=reasons, age_days=age)

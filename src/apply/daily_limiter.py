"""Enforces the per-day application cap.

The single source of truth is LocalDB.daily_applied_count() — counts rows
whose status is APPLIED and last_updated is on/after midnight UTC.
"""

from __future__ import annotations

from src.tracker.local_db import LocalDB
from src.utils.logger import logger


class DailyLimitReached(RuntimeError):
    """Raised when the daily quota of applications is exhausted."""


class DailyLimiter:
    def __init__(self, db: LocalDB, daily_limit: int) -> None:
        self.db = db
        self.daily_limit = max(0, int(daily_limit))

    def remaining(self) -> int:
        applied = self.db.daily_applied_count()
        return max(0, self.daily_limit - applied)

    def is_exhausted(self) -> bool:
        return self.remaining() <= 0

    def assert_can_apply(self) -> None:
        rem = self.remaining()
        if rem <= 0:
            raise DailyLimitReached(
                f"Daily limit of {self.daily_limit} applications reached"
            )
        logger.debug(f"DailyLimiter: {rem} application(s) remaining today")

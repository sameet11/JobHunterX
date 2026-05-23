"""Abstract base for all platform-specific appliers.

Every applier implements `.apply(scored_job) -> ApplyResult`.

The orchestrator (main.py) owns scheduling, daily limits, and tracker writes;
appliers are responsible only for the platform-specific submit flow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from config.user_config import UserConfig
from src.models import ScoredJob


class ApplyStatus(str, Enum):
    SUBMITTED = "submitted"
    SKIPPED = "skipped"
    FAILED = "failed"
    CAPTCHA = "captcha"
    REDIRECT = "redirect"  # platform handed off to an external company URL


class ApplyResult(BaseModel):
    status: ApplyStatus
    reason: str = ""
    screenshot_path: Optional[str] = None
    confirmation_text: str = ""

    @property
    def applied(self) -> bool:
        return self.status is ApplyStatus.SUBMITTED


class BaseApplier(ABC):
    """One instance per platform. Stateless across jobs except for config."""

    source: str = "unknown"

    def __init__(self, user_config: UserConfig) -> None:
        self.user_config = user_config

    @abstractmethod
    def apply(self, scored: ScoredJob) -> ApplyResult:
        """Submit the application for the given job. Must be sync; can wrap async internally."""

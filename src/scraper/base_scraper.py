"""Abstract base for all job scrapers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from config.user_config import UserConfig
from src.models import Job


class BaseScraper(ABC):
    source: str = "unknown"

    def __init__(self, user_config: UserConfig) -> None:
        self.user_config = user_config

    @abstractmethod
    def search(self, title: str, location: str) -> list[Job]:
        """Return job listings for the given title + location."""

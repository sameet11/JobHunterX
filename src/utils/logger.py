"""Loguru-backed logger with sensible defaults."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from config.platform_config import platform

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(sys.stderr, level=platform.log_level, backtrace=False, diagnose=False)
logger.add(
    _LOG_DIR / "jobhunter.log",
    level=platform.log_level,
    rotation="10 MB",
    retention="14 days",
    enqueue=True,
)

__all__ = ["logger"]

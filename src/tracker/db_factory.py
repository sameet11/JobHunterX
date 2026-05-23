"""Database factory — supports SQLite (default) or PostgreSQL (Docker)."""

from __future__ import annotations

from pathlib import Path

from config.platform_config import platform
from src.tracker.local_db import LocalDB
from src.utils.logger import logger


def get_db() -> LocalDB:
    """
    Returns a LocalDB instance using either PostgreSQL (if DATABASE_URL set)
    or SQLite (default).

    Set DATABASE_URL in .env to use PostgreSQL:
      DATABASE_URL=postgresql://jobhunter:password@localhost:5432/jobhunterx
    """
    if platform.database_url:
        logger.info(f"Using PostgreSQL: {platform.database_url.split('@')[0]}@...")
        return LocalDB(database_url=platform.database_url)
    else:
        db_path = Path(__file__).resolve().parents[2] / "data" / "applied.sqlite"
        logger.info(f"Using SQLite: {db_path}")
        return LocalDB(path=db_path)

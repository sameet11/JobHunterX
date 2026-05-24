"""Loads platform credentials and API keys from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class PlatformConfig:
    gcp_project: str = _get("GOOGLE_CLOUD_PROJECT")
    gcp_region: str = _get("GOOGLE_CLOUD_REGION", "us-central1")
    gemini_model: str = _get("GEMINI_MODEL", "gemini-2.0-flash-001")
    google_application_credentials: str = _get("GOOGLE_APPLICATION_CREDENTIALS")

    adzuna_app_id: str = _get("ADZUNA_APP_ID")
    adzuna_app_key: str = _get("ADZUNA_APP_KEY")
    apify_api_token: str = _get("APIFY_API_TOKEN")
    apify_linkedin_actor: str = _get("APIFY_LINKEDIN_ACTOR", "curious_coder~linkedin-jobs-scraper")
    apify_per_source_limit: int = _get_int("APIFY_PER_SOURCE_LIMIT", 100)

    hunter_api_key: str = _get("HUNTER_API_KEY")

    linkedin_email: str = _get("LINKEDIN_EMAIL")
    linkedin_password: str = _get("LINKEDIN_PASSWORD")
    naukri_email: str = _get("NAUKRI_EMAIL")
    naukri_password: str = _get("NAUKRI_PASSWORD")

    google_sheet_id: str = _get("GOOGLE_SHEET_ID")

    min_match_score: int = _get_int("MIN_MATCH_SCORE", 60)
    log_level: str = _get("LOG_LEVEL", "INFO")


platform = PlatformConfig()

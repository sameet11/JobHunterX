"""Returns the right scraper instance for a given platform name."""

from __future__ import annotations

from config.user_config import UserConfig
from src.scraper.adzuna_scraper import AdzunaScraper
from src.scraper.apify_scraper import ApifyIndeedScraper, ApifyLinkedInScraper
from src.scraper.ashby_scraper import AshbyScraper
from src.scraper.base_scraper import BaseScraper
from src.scraper.greenhouse_scraper import GreenhouseScraper
from src.scraper.hn_scraper import HNScraper
from src.scraper.indeed_scraper import GoogleJobsScraper, IndeedScraper
from src.scraper.lever_scraper import LeverScraper
from src.scraper.naukri_scraper import NaukriScraper
from src.scraper.remoteok_scraper import RemoteOKScraper
from src.scraper.remotive_scraper import RemotiveScraper

_REGISTRY: dict[str, type[BaseScraper]] = {
    "naukri": NaukriScraper,
    "indeed": IndeedScraper,
    "google_jobs": GoogleJobsScraper,
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "ashby": AshbyScraper,
    "remoteok": RemoteOKScraper,
    "remotive": RemotiveScraper,
    "hn": HNScraper,
    "adzuna": AdzunaScraper,
    "apify_linkedin": ApifyLinkedInScraper,
    "apify_indeed": ApifyIndeedScraper,
}


def get_scraper(platform_name: str, user_config: UserConfig) -> BaseScraper:
    key = platform_name.lower()
    if key not in _REGISTRY:
        raise ValueError(f"Unknown platform: {platform_name}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[key](user_config)

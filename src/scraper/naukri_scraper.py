"""Naukri scraper using their internal JSON search API.

Naukri's `/jobapi/v3/search` endpoint requires:
  - `nkparam` header: RSA-encrypted token of `v0|<timestamp_ms>|121_srp`
  - `appid: 109`, `gid: LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE`
  - A `seoKey` URL slug that mirrors how Naukri builds search-result URLs
  - Chrome TLS fingerprint (curl_cffi impersonation) to pass bot detection

Reverse-engineered from the NopeRi project (github.com/Traverser25/NopeRi).
The public key + algorithm are public-facing in Naukri's web bundle.
"""

from __future__ import annotations

import base64
import re
import time
from datetime import datetime
from typing import Any

from curl_cffi import requests as curl_requests
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from src.models import Job
from src.scraper.base_scraper import BaseScraper
from src.utils.logger import logger

_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"
_DETAIL_URL = "https://www.naukri.com/jobapi/v3/jobs/{job_id}"

# Public key Naukri's web bundle uses to encrypt nkparam.
_NAUKRI_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBALrlQ+djR0RjJwBF1xuisHmdFv334MIm
K6LgzJhmLhN7B5yuEyaKoasgXQk3+OQglsOaBxEJ0j5PcTL3nbOvt80CAwEAAQ==
-----END PUBLIC KEY-----"""

_RSA_CIPHER = PKCS1_v1_5.new(RSA.import_key(_NAUKRI_PUBLIC_KEY))


def _generate_nkparam(page_type: str = "srp") -> str:
    """Build the encrypted token Naukri's search API requires."""
    timestamp_ms = int(time.time() * 1000)
    plaintext = f"v0|{timestamp_ms}|121_{page_type}".encode("utf-8")
    encrypted = _RSA_CIPHER.encrypt(plaintext)
    return base64.b64encode(encrypted).decode("utf-8")


def _slugify(text: str) -> str:
    """Naukri seoKey style: lowercase, hyphen-separated, alnum only."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _seo_key(title: str, location: str | None) -> str:
    title_slug = _slugify(title)
    if location:
        return f"{title_slug}-jobs-in-{_slugify(location)}"
    return f"{title_slug}-jobs"


def _base_headers() -> dict[str, str]:
    return {
        "authority": "www.naukri.com",
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "appid": "109",
        "systemid": "Naukri",
        "gid": "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
        "clientid": "d3skt0p",
        "referer": "https://www.naukri.com/",
    }


class NaukriScraper(BaseScraper):
    source = "naukri"

    def __init__(self, user_config, *, timeout: float = 20.0) -> None:
        super().__init__(user_config)
        # curl_cffi impersonates Chrome's TLS fingerprint — bypasses Naukri bot detection
        self._session = curl_requests.Session(impersonate="chrome124")
        self._timeout = timeout

    def __del__(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    def _get(self, url: str, params: dict, page_type: str = "srp") -> curl_requests.Response | None:
        """Make a GET request with full headers. Returns None on 406 (CAPTCHA signal)."""
        headers = _base_headers().copy()
        headers["nkparam"] = _generate_nkparam(page_type)
        try:
            response = self._session.get(url, params=params, headers=headers, timeout=self._timeout)
        except Exception as exc:
            logger.warning(f"Naukri request failed: {exc}")
            return None

        if response.status_code == 406:
            logger.warning(
                f"Naukri 406 (recaptcha) for {url}; returning empty — will retry next run"
            )
            return None

        if response.status_code != 200:
            logger.error(
                f"Naukri {response.status_code}; "
                f"response: {response.text[:300] if response.text else '(empty)'}"
            )
            response.raise_for_status()

        return response

    def search(self, title: str, location: str) -> list[Job]:
        params = {
            "noOfResults": 20,
            "urlType": "search_by_keyword",
            "searchType": "adv",
            "keyword": title,
            "k": title,
            "pageNo": 1,
            "experience": str(self.user_config.experience_years),
            "jobAge": 7,
            "seoKey": _seo_key(title, location),
            "src": "jobsearchDesk",
            "latLong": "",
            "nignbevent_src": "jobsearchDeskGNB",
        }
        if location:
            params["location"] = location
            params["l"] = location

        logger.info(f"Naukri search: {title!r} in {location!r}")
        response = self._get(_SEARCH_URL, params)

        if response is None:
            return []

        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError) as e:
            logger.warning(f"Naukri JSON decode failed: {e}; returning empty")
            return []

        listings = payload.get("jobDetails") or payload.get("jobs") or []
        jobs = [self._to_job(item) for item in listings if item.get("jobId") or item.get("id")]
        logger.info(f"Naukri returned {len(jobs)} jobs for {title!r}/{location!r}")
        return jobs

    def get_job_detail(self, job_id: str) -> str:
        response = self._get(_DETAIL_URL.format(job_id=job_id), params={}, page_type="jd")
        if response is None:
            return ""
        body = response.json()
        return body.get("jobDescription") or body.get("description") or ""

    def _to_job(self, item: dict[str, Any]) -> Job:
        job_id = str(item.get("jobId") or item.get("id"))
        apply_url = item.get("jdURL") or item.get("staticUrl") or ""
        if apply_url and not apply_url.startswith("http"):
            apply_url = f"https://www.naukri.com{apply_url}"

        posted_raw = item.get("createdDate") or item.get("footerPlaceholderLabel")
        posted_date: datetime | None = None
        if isinstance(posted_raw, (int, float)):
            try:
                posted_date = datetime.fromtimestamp(posted_raw / 1000)
            except (OSError, ValueError):
                posted_date = None

        placeholders = item.get("placeholders", []) or []
        location_str = ", ".join(
            p.get("label", "") for p in placeholders if p.get("type") == "location"
        ) or None
        salary_str = next(
            (p.get("label") for p in placeholders if p.get("type") == "salary"),
            None,
        )

        return Job(
            id=job_id,
            title=item.get("title", ""),
            company=item.get("companyName", ""),
            location=location_str,
            salary=salary_str,
            description=item.get("jobDescription", "") or "",
            apply_url=apply_url,
            easy_apply=False,
            posted_date=posted_date,
            source=self.source,
        )

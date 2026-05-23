"""Auto-extract LinkedIn session cookies from the user's installed browser.

Reads Chrome / Edge / Firefox cookie stores directly (decrypts on Windows via
DPAPI) so the user doesn't have to copy-paste li_at from DevTools.

Returns (li_at, jsessionid) or (None, None) if extraction fails.
"""
from __future__ import annotations

from typing import Optional

from src.utils.logger import logger


def extract_linkedin_cookies() -> tuple[Optional[str], Optional[str]]:
    """Try Chrome → Edge → Firefox in order; return first match."""
    try:
        import browser_cookie3
    except ImportError:
        logger.warning("browser-cookie3 not installed — falling back to env vars")
        return None, None

    for browser_name, loader in (
        ("Chrome", browser_cookie3.chrome),
        ("Edge", browser_cookie3.edge),
        ("Firefox", browser_cookie3.firefox),
    ):
        try:
            jar = loader(domain_name="linkedin.com")
        except Exception as exc:
            logger.debug(f"{browser_name} cookie read failed: {exc}")
            continue

        li_at = None
        jsess = None
        for cookie in jar:
            if cookie.name == "li_at" and cookie.value:
                li_at = cookie.value
            elif cookie.name == "JSESSIONID" and cookie.value:
                jsess = cookie.value.strip('"')
        if li_at:
            logger.info(f"LinkedIn cookies auto-loaded from {browser_name}")
            return li_at, jsess

    logger.warning(
        "No LinkedIn session found in Chrome/Edge/Firefox — "
        "log into linkedin.com in your browser, or set LINKEDIN_LI_AT_COOKIE in .env"
    )
    return None, None

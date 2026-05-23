"""Playwright-driven LinkedIn recruiter finder.

Opens a real visible browser, navigates to LinkedIn's people search for each
company, and scrapes recruiter cards. First run prompts you to log in; the
session is saved to data/linkedin_browser_session/ and reused thereafter.

No LinkedIn API, no cookie reading from Chrome — just a real browser doing
exactly what you'd do manually.
"""
from __future__ import annotations

import random
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from src.models import Job, Recruiter
from src.utils.logger import logger

_PROFILE_DIR = Path(__file__).resolve().parents[2] / "data" / "linkedin_browser_session"
_RECRUITER_KEYWORDS = ("recruiter", "talent", "hiring", "hr", "people", "sourcer", "acquisition")


def find_linkedin_recruiters(
    jobs: list[Job],
    *,
    max_per_company: int = 3,
    min_delay_seconds: int = 30,
    max_delay_seconds: int = 120,
    headless: bool = False,
) -> dict[str, list[Recruiter]]:
    """For each job, search LinkedIn for recruiters at that company.

    Returns {job.dedup_key(): [Recruiter, ...]}.
    """
    from playwright.sync_api import sync_playwright

    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[Recruiter]] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(_PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        _apply_stealth(page)

        _ensure_logged_in(page)

        for idx, job in enumerate(jobs):
            if idx > 0:
                delay = random.uniform(min_delay_seconds, max_delay_seconds)
                logger.info(f"Pacing {delay:.0f}s before next search ({job.company})")
                time.sleep(delay)

            recruiters = _search_company(page, job.company, max_results=max_per_company)
            results[job.dedup_key()] = recruiters

        browser.close()

    return results


def _apply_stealth(page) -> None:
    """Hide Playwright automation flags (navigator.webdriver, etc.) via playwright-stealth.

    Falls back to a manual init_script if the library isn't available or its
    API doesn't match the installed version.
    """
    try:
        from playwright_stealth import stealth_sync  # type: ignore
        stealth_sync(page)
        logger.info("Stealth applied (playwright-stealth)")
        return
    except Exception as exc:
        logger.debug(f"playwright-stealth unavailable ({exc}) — applying manual patches")

    # Minimal manual fallback: hide the most obvious automation tells.
    try:
        page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = window.chrome || { runtime: {} };
            """
        )
        logger.info("Stealth applied (manual fallback)")
    except Exception as exc:
        logger.warning(f"Could not apply stealth patches: {exc}")


def _ensure_logged_in(page) -> None:
    """Navigate to feed and prompt the user to log in if needed."""
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        logger.warning(f"Couldn't reach LinkedIn feed: {exc}")

    time.sleep(2)
    if any(x in page.url for x in ("/login", "/checkpoint", "/uas/login")):
        print("\n" + "=" * 70)
        print("  Please log into LinkedIn in the browser window that just opened.")
        print("  After you see your LinkedIn feed, come back here and press Enter.")
        print("=" * 70 + "\n")
        input("  Press Enter once logged in... ")
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        time.sleep(2)
        if any(x in page.url for x in ("/login", "/checkpoint")):
            raise RuntimeError("Still not logged into LinkedIn — aborting.")
    logger.info("LinkedIn session active — proceeding with searches")


def _search_company(page, company: str, *, max_results: int) -> list[Recruiter]:
    """Navigate to LinkedIn people search for `company recruiter` and extract cards.

    Strategy:
      1. Isolate actual search-result cards (not sidebar / connections of a result)
      2. Within each card find the primary /in/ link + subtitle text
      3. Require a recruiter-ish title — never keep empty-title results, which
         are usually connection suggestions shown below the first result's profile
    """
    url = (
        "https://www.linkedin.com/search/results/people/"
        f"?keywords={quote_plus(company + ' recruiter')}"
        "&origin=GLOBAL_SEARCH_HEADER"
    )
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        logger.warning(f"Failed to load search for {company}: {exc}")
        return []

    if any(x in page.url for x in ("/login", "/checkpoint", "/uas/login")):
        logger.warning("LinkedIn requires re-auth — visit linkedin.com and log in, then retry")
        return []

    # Wait for result cards to appear
    _CARD_SELECTORS = [
        "li.reusable-search__result-container",
        "div.reusable-search__result-container",
        "li[data-view-name='search-entity-result-universal-template']",
    ]
    card_selector = None
    for sel in _CARD_SELECTORS:
        try:
            page.wait_for_selector(sel, timeout=12000)
            card_selector = sel
            break
        except Exception:
            pass

    if card_selector is None:
        # Fall back to waiting for any /in/ link (older LinkedIn layout)
        try:
            page.wait_for_selector("a[href*='/in/']", timeout=8000)
        except Exception:
            logger.warning(f"No search result cards found for {company}")
            return []

    # Let lazy-loaded subtitles finish rendering
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    time.sleep(random.uniform(1.5, 3.0))

    # Human-like scroll
    try:
        for _ in range(random.randint(2, 4)):
            page.mouse.wheel(0, random.randint(200, 500))
            time.sleep(random.uniform(0.4, 1.1))
    except Exception:
        pass

    seen_slugs: set[str] = set()
    recruiters: list[Recruiter] = []

    if card_selector:
        cards = page.query_selector_all(card_selector)
    else:
        # No card selector found — scope to the main search results list only,
        # NOT the full page (avoids picking up sidebar/connection links)
        cards = page.query_selector_all(
            "main a[href*='/in/'], "
            "[data-test-search-result] a[href*='/in/'], "
            ".search-results-container a[href*='/in/']"
        )

    for card in cards:
        try:
            # Get the primary profile link within this card
            link = (
                card.query_selector("a[href*='/in/']")
                if card_selector
                else card  # already a link in fallback path
            )
            if link is None:
                continue

            href = (link.get_attribute("href") or "").split("?")[0].split("#")[0]
            slug_m = re.search(r"/in/([^/]+)/?$", href)
            if not slug_m:
                continue
            slug = slug_m.group(1).lower()
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            profile_url = f"https://www.linkedin.com/in/{slug}"

            # Name from the card
            name = (link.get_attribute("aria-label") or "").strip()
            if not name or name.lower().startswith(("view ", "see ")):
                txt = (link.inner_text() or "").strip()
                name = next((ln.strip() for ln in txt.splitlines() if ln.strip()), "")
            name = re.sub(r"\s*[–—-]\s*\d+(?:st|nd|rd)?\b.*$", "", name).strip()
            if not name or name.lower() in ("linkedin member", "linkedin"):
                continue

            # Title: read from the card container's subtitle element
            title = ""
            try:
                container = card if card_selector else link
                title = container.evaluate(
                    """el => {
                        const sels = [
                            "div.entity-result__primary-subtitle",
                            "div[class*='primary-subtitle']",
                            "div[class*='subtitle']",
                            "div.t-14.t-normal",
                            "div.t-14:not(.t-bold)"
                        ];
                        for (const s of sels) {
                            const node = el.querySelector(s);
                            if (node && node.innerText && node.innerText.trim())
                                return node.innerText.trim();
                        }
                        return "";
                    }"""
                )
            except Exception:
                pass

            # Strictly require a recruiter-ish title — empty title means we
            # picked up a connection card or sidebar suggestion, skip it
            if not title or not any(kw in title.lower() for kw in _RECRUITER_KEYWORDS):
                continue

            recruiters.append(Recruiter(
                name=name,
                title=title,
                email="",
                company=company,
                source="linkedin_browser",
                confidence=85,
                linkedin_url=profile_url,
            ))
            if len(recruiters) >= max_results:
                break
        except Exception as exc:
            logger.debug(f"Failed to parse a result card for {company}: {exc}")
            continue

    logger.info(f"Found {len(recruiters)} recruiter(s) at {company}")
    return recruiters

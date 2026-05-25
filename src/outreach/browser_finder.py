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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_DIR = _REPO_ROOT / "data" / "linkedin_browser_session"
_DEBUG_DIR = _REPO_ROOT / "data" / "debug"
_RECRUITER_KEYWORDS = ("recruiter", "talent", "hiring", "hr", "people", "sourcer", "acquisition", "ta ")
_NOISE_NAMES = {"linkedin member", "linkedin", ""}


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
    """Navigate to LinkedIn people search and extract profiles at the company.

    Strategy (resilient to LinkedIn DOM churn):
      1. Scope to <main> so sidebar suggestions are excluded.
      2. Collect every unique /in/ profile inside <main>; pull each one's
         nearest container for name + subtitle extraction.
      3. Score by recruiter-ish keywords in title — recruiters first, then
         anyone else at the company. Empty titles are kept but ranked last.
      4. On 0 results, dump page HTML to data/debug/ for inspection.
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

    # Wait for any profile link to materialize inside main content
    try:
        page.wait_for_selector("main a[href*='/in/']", timeout=15000)
    except Exception:
        logger.warning(f"No profile links found for {company} (selector timeout)")
        _dump_debug_html(page, company)
        return []

    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    time.sleep(random.uniform(1.5, 3.0))

    # Human-like scroll so lazy subtitles render
    try:
        for _ in range(random.randint(3, 5)):
            page.mouse.wheel(0, random.randint(300, 700))
            time.sleep(random.uniform(0.4, 1.1))
    except Exception:
        pass

    # Pull all candidate people via JS — one round-trip, no per-card RPCs.
    # For each /in/ link inside <main>, walk up to a sensible container
    # (li/div with role=listitem or with multiple text rows) and extract
    # the name and the first non-name visible text line as title.
    candidates: list[dict] = page.evaluate(
        """
        () => {
            const main = document.querySelector('main') || document.body;
            const links = Array.from(main.querySelectorAll("a[href*='/in/']"));
            const out = [];
            const seen = new Set();
            for (const a of links) {
                const href = (a.getAttribute('href') || '').split('?')[0].split('#')[0];
                const m = href.match(/\\/in\\/([^/]+)\\/?$/);
                if (!m) continue;
                const slug = m[1].toLowerCase();
                if (seen.has(slug)) continue;

                // Walk up to a container that includes more than just the link
                let container = a;
                for (let i = 0; i < 6; i++) {
                    const p = container.parentElement;
                    if (!p) break;
                    container = p;
                    const txt = (container.innerText || '').trim();
                    if (txt.split('\\n').length >= 2) break;
                }

                // Name candidates: aria-label, link inner text, then container heading
                let name = (a.getAttribute('aria-label') || '').trim();
                if (!name || /^(view|see)\\s/i.test(name)) {
                    name = (a.innerText || '').trim().split('\\n')[0].trim();
                }
                if (!name) {
                    const span = container.querySelector("span[aria-hidden='true']");
                    if (span) name = (span.innerText || '').trim();
                }

                // Clean trailing " · 2nd" / "— 3rd+" connection markers
                name = name.replace(/\\s*[\\u2013\\u2014\\-·]\\s*\\d+(?:st|nd|rd|th)?\\+?\\b.*$/, '').trim();

                // Title: first visible text row in the container that isn't the name
                let title = '';
                const nameLower = name.toLowerCase();
                const lines = (container.innerText || '')
                    .split('\\n').map(s => s.trim()).filter(Boolean);
                for (let ln of lines) {
                    // Strip trailing connection marker " · 2nd", "— 3rd+", etc.
                    ln = ln.replace(/\\s*[\\u2013\\u2014\\-·•]\\s*\\d+(?:st|nd|rd|th)?\\+?\\s*.*$/i, '').trim();
                    if (!ln) continue;
                    if (nameLower && ln.toLowerCase().startsWith(nameLower)) continue;
                    if (/^\\d+(st|nd|rd|th)?\\s*\\+?\\s*$/i.test(ln)) continue;
                    if (/^(connect|message|follow|view profile|status is|\\*\\s)/i.test(ln)) continue;
                    title = ln;
                    break;
                }

                seen.add(slug);
                out.push({ slug, name, title });
            }
            return out;
        }
        """
    )

    cleaned: list[Recruiter] = []
    for c in candidates:
        name = (c.get("name") or "").strip()
        title = (c.get("title") or "").strip()
        slug = c.get("slug") or ""
        if not slug or name.lower() in _NOISE_NAMES:
            continue
        # Drop UI strings that occasionally leak through as names
        if re.search(r"(open menu|connections|premium|saved searches)", name, re.I):
            continue
        cleaned.append(Recruiter(
            name=name,
            title=title,
            email="",
            company=company,
            source="linkedin_browser",
            confidence=80,
            linkedin_url=f"https://www.linkedin.com/in/{slug}",
        ))

    # Sort: recruiter-ish titles first, then anyone else, empty titles last
    def _rank(r: Recruiter) -> tuple[int, int]:
        t = (r.title or "").lower()
        is_recruiter = any(kw in t for kw in _RECRUITER_KEYWORDS)
        has_title = bool(t)
        return (0 if is_recruiter else (1 if has_title else 2), 0)

    cleaned.sort(key=_rank)
    result = cleaned[:max_results]

    if not result:
        _dump_debug_html(page, company)
        logger.warning(f"0 recruiters parsed for {company} — HTML dumped to {_DEBUG_DIR}")
    else:
        logger.info(f"Found {len(result)} person(s) at {company} (from {len(cleaned)} candidates)")
    return result


def _dump_debug_html(page, company: str) -> None:
    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]+", "_", company)[:40]
        path = _DEBUG_DIR / f"linkedin_search_{safe}.html"
        path.write_text(page.content(), encoding="utf-8")
        logger.warning(f"Saved page HTML for inspection: {path}")
    except Exception as exc:
        logger.debug(f"Could not dump debug HTML: {exc}")

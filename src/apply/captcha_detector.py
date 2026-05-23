"""CAPTCHA / security-challenge detection on a Playwright page.

Policy: when a challenge is detected, the bot NEVER polls the page or
issues any further Playwright calls until the human explicitly
confirms via the console. DOM probes during a challenge can themselves
raise the platform's trust-quality score against the account.

`wait_for_human()` therefore blocks on stdin only — it does not
touch `page` at all. After confirmation, the caller resumes with
normal human-speed pacing.

Only when the human doesn't confirm within the timeout do we raise
`CaptchaDetected`, which the caller treats as a hard pause.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.utils.logger import logger

if TYPE_CHECKING:
    from playwright.async_api import Page

_SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "logs" / "captcha"
_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

_CAPTCHA_SELECTORS: tuple[str, ...] = (
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[title*='captcha' i]",
    "div.g-recaptcha",
    "div#captcha",
    "div[data-test-id*='captcha' i]",
    "input[name*='captcha' i]",
    "img[alt*='captcha' i]",
)

_TEXT_HINTS: tuple[str, ...] = (
    "verify you are human",
    "security check",
    "are you a robot",
    "unusual activity",
    "let's confirm",
    "complete the challenge",
)


class CaptchaDetected(RuntimeError):
    """Raised when a CAPTCHA / security challenge blocks the apply flow."""

    def __init__(self, where: str, screenshot: Path | None = None) -> None:
        super().__init__(f"CAPTCHA detected at {where}")
        self.where = where
        self.screenshot = screenshot


async def detect(page: "Page") -> bool:
    """Return True if the current page seems to host a CAPTCHA or challenge."""
    for sel in _CAPTCHA_SELECTORS:
        try:
            if await page.query_selector(sel):
                logger.warning(f"CAPTCHA selector matched: {sel}")
                return True
        except Exception:
            continue
    try:
        text = (await page.content()).lower()
    except Exception:
        return False
    for hint in _TEXT_HINTS:
        if hint in text:
            logger.warning(f"CAPTCHA text hint matched: {hint!r}")
            return True
    return False


async def screenshot(page: "Page", *, label: str) -> Path:
    safe_label = "".join(c if c.isalnum() else "_" for c in label)[:40]
    fname = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_label}.png"
    path = _SCREENSHOT_DIR / fname
    try:
        await page.screenshot(path=str(path), full_page=True)
    except Exception as exc:
        logger.warning(f"Failed to capture CAPTCHA screenshot: {exc}")
        return path
    return path


def notify_user(message: str) -> None:
    """Loud cross-platform alert. On Windows, also beep."""
    banner = "!" * 60
    logger.error(f"\n{banner}\nCAPTCHA / HUMAN ACTION REQUIRED:\n  {message}\n{banner}")
    if sys.platform.startswith("win"):
        try:
            import winsound  # stdlib on Windows
            for _ in range(3):
                winsound.Beep(880, 250)
        except Exception:
            pass


_CONFIRM_PROMPT = (
    "\n>>> CAPTCHA at {label}. Solve it in the open browser, then press ENTER here to resume. <<<\n"
)


def _blocking_confirm(prompt: str, timeout_seconds: int) -> bool:
    """Block on stdin until the user presses Enter or the timeout elapses.

    Runs only in a worker thread (via asyncio.to_thread); never touches the
    Playwright page. Returns True on confirmation, False on timeout / EOF.
    """
    if sys.stdin is None or not sys.stdin.isatty():
        # No interactive console — fall back to a simple sleep so unattended
        # runs don't deadlock; the caller will still raise on timeout.
        time.sleep(timeout_seconds)
        return False
    deadline = time.monotonic() + timeout_seconds
    try:
        # Single blocking read; the timeout is enforced by the caller's
        # asyncio.wait_for, so we don't need select() here.
        sys.stdout.write(prompt)
        sys.stdout.flush()
        line = sys.stdin.readline()
    except Exception:
        return False
    if line == "":
        return False
    if time.monotonic() > deadline:
        return False
    return True


async def wait_for_human(
    *,
    label: str,
    timeout_seconds: int = 1800,
) -> bool:
    """Block (asynchronously) until the human confirms via stdin.

    Crucially this function does NOT touch the Playwright page. The agent
    notifies the user, then waits silently for an Enter keypress on the
    console. Returns True on confirmation, False on timeout.
    """
    notify_user(
        f"Waiting for human to solve CAPTCHA at: {label}. "
        f"Solve it in the open browser, then press ENTER in the console to resume "
        f"(timeout {timeout_seconds // 60} min)."
    )
    prompt = _CONFIRM_PROMPT.format(label=label)
    try:
        confirmed = await asyncio.wait_for(
            asyncio.to_thread(_blocking_confirm, prompt, timeout_seconds),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.error(f"CAPTCHA at {label} not confirmed within {timeout_seconds}s")
        return False
    if confirmed:
        logger.info(
            f"Human confirmed CAPTCHA cleared at {label} — resuming with human pacing"
        )
    return confirmed

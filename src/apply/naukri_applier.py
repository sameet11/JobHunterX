"""Naukri quick-apply automation.

Naukri's "Apply" button has two variants:
  - Quick Apply (in-place): the candidate's profile + on-file resume are
    submitted directly. Sometimes a small modal shows screening questions.
  - Company Site (redirect): opens an external careers page. We mark these
    as REDIRECT and let the user finish manually.

Uses a persistent Playwright profile keyed off Naukri credentials. The
candidate's resume on Naukri must already be set to sameet_sabu_resume.pdf
(per the static-resume rule).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    ElementHandle,
    Page,
    TimeoutError as PWTimeout,
    async_playwright,
)

try:
    from playwright_stealth import stealth_async  # type: ignore
except ImportError:
    stealth_async = None

from config.platform_config import platform as platform_cfg
from config.user_config import UserConfig
from src.apply import captcha_detector
from src.apply.base_applier import ApplyResult, ApplyStatus, BaseApplier
from src.apply.captcha_detector import CaptchaDetected
from src.apply.form_filler import FormFiller
from src.apply.screening_qa import ScreeningQA
from src.models import ScoredJob
from src.utils.human_behavior import HumanBehavior
from src.utils.logger import logger

_LOGIN_URL = "https://www.naukri.com/nlogin/login"
_HOMEPAGE = "https://www.naukri.com/"
_PROFILE_DIR = Path(__file__).resolve().parents[2] / "data" / "naukri_profile"
_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
_SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "logs" / "applications"
_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

_APPLY_BUTTONS = (
    "button#apply-button",
    "button:has-text('Apply')",
    "a:has-text('Apply')",
    "button.apply-button",
)
_COMPANY_SITE_HINTS = (
    "Apply on company site",
    "company website",
    "company site",
)
_SUBMIT_BUTTONS = (
    "button:has-text('Submit')",
    "button:has-text('Save and Continue')",
    "button:has-text('Continue')",
    "button.btn-primary",
)
_CONFIRM_HINTS = (
    "successfully applied",
    "application sent",
    "thank you for applying",
    "you have applied",
)


class NaukriApplier(BaseApplier):
    source = "naukri"

    def __init__(self, user_config: UserConfig, *, headless: bool = False) -> None:
        super().__init__(user_config)
        self.headless = headless
        self.human = HumanBehavior(user_config.human_speed)
        self._screening: Optional[ScreeningQA] = None
        if platform_cfg.gcp_project:
            try:
                self._screening = ScreeningQA(user_config)
            except Exception as exc:
                logger.warning(f"ScreeningQA disabled: {exc}")

    def apply(self, scored: ScoredJob) -> ApplyResult:
        if not (platform_cfg.naukri_email and platform_cfg.naukri_password):
            return ApplyResult(
                status=ApplyStatus.SKIPPED,
                reason="NAUKRI_EMAIL / NAUKRI_PASSWORD not configured",
            )
        try:
            return asyncio.run(self._apply_async(scored))
        except CaptchaDetected as exc:
            return ApplyResult(
                status=ApplyStatus.CAPTCHA,
                reason=str(exc),
                screenshot_path=str(exc.screenshot) if exc.screenshot else None,
            )
        except Exception as exc:
            logger.exception(
                f"NaukriApplier failed for {scored.job.company}/{scored.job.title}: {exc}"
            )
            return ApplyResult(status=ApplyStatus.FAILED, reason=str(exc))

    async def _apply_async(self, scored: ScoredJob) -> ApplyResult:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(_PROFILE_DIR),
                headless=self.headless,
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            if stealth_async:
                await stealth_async(page)
            try:
                await self._ensure_logged_in(page)
                return await self._do_apply(page, scored)
            finally:
                await context.close()

    async def _ensure_logged_in(self, page: Page) -> None:
        await page.goto(_HOMEPAGE, wait_until="domcontentloaded")
        await self.human.pause(1500, 3000)
        if await self._is_logged_in(page):
            return

        logger.info("Naukri (apply): logging in…")
        await page.goto(_LOGIN_URL, wait_until="domcontentloaded")
        await self.human.pause(1500, 3000)

        try:
            await self.human.type_text(page, "input[placeholder*='Email'], input#usernameField", platform_cfg.naukri_email)
        except Exception:
            await self.human.type_text(page, "input[type='text']", platform_cfg.naukri_email)
        await self.human.short_pause()
        try:
            await self.human.type_text(page, "input[placeholder*='password'], input#passwordField", platform_cfg.naukri_password)
        except Exception:
            await self.human.type_text(page, "input[type='password']", platform_cfg.naukri_password)
        await self.human.short_pause()

        try:
            await self.human.human_click(page, "button[type='submit']")
        except Exception:
            await self.human.human_click(page, "button:has-text('Login')")

        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except PWTimeout:
            pass

        if await captcha_detector.detect(page):
            shot = await captcha_detector.screenshot(page, label="naukri_login")
            cleared = await captcha_detector.wait_for_human(label="naukri_login")
            if not cleared:
                raise CaptchaDetected("naukri_login", shot)
            await self.human.pause(2000, 5000)

        if not await self._is_logged_in(page):
            raise RuntimeError("Naukri login appeared to fail (no profile element found)")
        logger.info("Naukri login OK")

    @staticmethod
    async def _is_logged_in(page: Page) -> bool:
        for sel in (
            "div.nI-gNb-drawer__icon",
            "div.user-name",
            "a[href*='mnjuser/profile']",
        ):
            try:
                if await page.query_selector(sel):
                    return True
            except Exception:
                continue
        return False

    async def _do_apply(self, page: Page, scored: ScoredJob) -> ApplyResult:
        job = scored.job
        await page.goto(job.apply_url, wait_until="domcontentloaded")
        await self.human.reading_pause(job.description or job.title)

        if await captcha_detector.detect(page):
            shot = await captcha_detector.screenshot(page, label=f"naukri_{job.id}")
            cleared = await captcha_detector.wait_for_human(label=f"naukri_job_{job.id}")
            if not cleared:
                raise CaptchaDetected(f"naukri_job_{job.id}", shot)
            await self.human.pause(2000, 5000)

        button = await self._first_visible(page, _APPLY_BUTTONS)
        if not button:
            return ApplyResult(
                status=ApplyStatus.SKIPPED,
                reason="Apply button not found on Naukri job page",
            )

        button_text = ((await button.inner_text()) or "").lower()
        if any(hint.lower() in button_text for hint in _COMPANY_SITE_HINTS):
            shot_path = await self._save_screenshot(page, job.id, "redirect")
            return ApplyResult(
                status=ApplyStatus.REDIRECT,
                reason="Naukri 'Apply on company site' — manual follow-up needed",
                screenshot_path=str(shot_path),
            )

        await button.click()
        await self.human.pause(1500, 3000)

        # If a chatbot / multi-step Q&A modal opens, fill what we can.
        filler = FormFiller(
            self.user_config,
            self.human,
            ask_screening=self._screening.answer if self._screening else None,
        )

        for step in range(1, 8):
            if await captcha_detector.detect(page):
                shot = await captcha_detector.screenshot(page, label=f"naukri_apply_{job.id}")
                cleared = await captcha_detector.wait_for_human(
                    label=f"naukri_apply_{job.id} ({job.company}/{job.title})"
                )
                if not cleared:
                    raise CaptchaDetected(f"naukri_apply_{job.id}", shot)
                await self.human.pause(2000, 5000)

            confirmation = await self._confirmation_text(page)
            if confirmation:
                shot_path = await self._save_screenshot(page, job.id, "submitted")
                return ApplyResult(
                    status=ApplyStatus.SUBMITTED,
                    reason="Naukri quick apply submitted",
                    screenshot_path=str(shot_path),
                    confirmation_text=confirmation,
                )

            try:
                await filler.fill_visible_fields(page, scored)
            except Exception as exc:
                logger.warning(f"FormFiller error on Naukri step {step}: {exc}")

            submit = await self._first_visible(page, _SUBMIT_BUTTONS)
            if not submit:
                # No further action means the click already submitted.
                confirmation = await self._confirmation_text(page)
                shot_path = await self._save_screenshot(
                    page, job.id, "submitted" if confirmation else "no_button"
                )
                if confirmation:
                    return ApplyResult(
                        status=ApplyStatus.SUBMITTED,
                        reason="Naukri quick apply submitted",
                        screenshot_path=str(shot_path),
                        confirmation_text=confirmation,
                    )
                return ApplyResult(
                    status=ApplyStatus.FAILED,
                    reason=f"No submit button on Naukri step {step}",
                    screenshot_path=str(shot_path),
                )
            await submit.click()
            await self.human.pause(1500, 3500)

        shot_path = await self._save_screenshot(page, job.id, "too_many_steps")
        return ApplyResult(
            status=ApplyStatus.FAILED,
            reason="Naukri apply exceeded step cap",
            screenshot_path=str(shot_path),
        )

    @staticmethod
    async def _first_visible(page: Page, selectors) -> Optional[ElementHandle]:
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible() and await el.is_enabled():
                    return el
            except Exception:
                continue
        return None

    @staticmethod
    async def _confirmation_text(page: Page) -> str:
        try:
            body = (await page.content()).lower()
        except Exception:
            return ""
        for hint in _CONFIRM_HINTS:
            if hint in body:
                return hint
        return ""

    @staticmethod
    async def _save_screenshot(page: Page, job_id: str, label: str) -> Path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = _SCREENSHOT_DIR / f"naukri_{ts}_{job_id}_{label}.png"
        try:
            await page.screenshot(path=str(path), full_page=True)
        except Exception as exc:
            logger.warning(f"Could not save screenshot: {exc}")
        return path

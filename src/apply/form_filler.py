"""Heuristic form-field filler.

Given a Playwright page that's currently showing form inputs, FormFiller
inspects every visible input/select/textarea, classifies it by label or
attribute keywords, and fills it from the ApplicantProfile + ScoredJob.

Anything it can't classify is handed to ScreeningQA (Claude) so the
applier doesn't get stuck on long-tail screening questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from config.user_config import ApplicantProfile, UserConfig
from src.models import ScoredJob
from src.utils.human_behavior import HumanBehavior
from src.utils.logger import logger

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page

# Map keyword set -> attribute on ApplicantProfile (or callable returning string).
_KEYWORD_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("first name", "given name", "firstname"), "_first_name"),
    (("last name", "surname", "family name", "lastname"), "_last_name"),
    (("full name", "your name", "candidate name", "name"), "full_name"),
    (("email", "e-mail"), "email"),
    (("phone", "mobile", "contact number", "telephone"), "phone"),
    (("linkedin",), "linkedin_url"),
    (("github",), "github_url"),
    (("portfolio", "website", "personal site"), "portfolio_url"),
    (("current company", "present company", "employer"), "current_company"),
    (("current role", "current title", "designation", "current position"), "current_role"),
    (("current location", "city", "location"), "current_location"),
    (("notice period",), "_notice_period_str"),
    (("expected ctc", "expected salary", "expected compensation"), "_expected_ctc_str"),
    (("current ctc", "current salary", "current compensation"), "_current_ctc_str"),
    (("years of experience", "total experience", "experience"), "_experience_str"),
    (("authorization", "right to work", "work permit", "visa"), "work_authorization"),
)

# Yes/no questions handled deterministically before falling back to Claude.
_YES_HINTS: tuple[tuple[str, str], ...] = (
    ("relocate", "willing_to_relocate"),
    ("remote", "open_to_remote"),
)


@dataclass
class FieldContext:
    label: str
    input_type: str
    name: str
    placeholder: str
    options: tuple[str, ...] = ()


def _profile_value(profile: ApplicantProfile, key: str, user_config: UserConfig) -> Optional[str]:
    if key == "_first_name":
        return profile.full_name.split(" ", 1)[0] if profile.full_name else ""
    if key == "_last_name":
        parts = profile.full_name.split(" ", 1)
        return parts[1] if len(parts) > 1 else ""
    if key == "_notice_period_str":
        return str(profile.notice_period_days)
    if key == "_expected_ctc_str":
        return str(profile.expected_ctc_lpa)
    if key == "_current_ctc_str":
        return str(profile.current_ctc_lpa)
    if key == "_experience_str":
        return str(user_config.experience_years)
    if hasattr(profile, key):
        val = getattr(profile, key)
        return str(val) if val is not None and val != "" else None
    return None


def _classify(label: str) -> Optional[str]:
    lo = label.lower()
    for keywords, attr in _KEYWORD_MAP:
        if any(k in lo for k in keywords):
            return attr
    return None


def _is_yes_no(label: str) -> Optional[bool]:
    lo = label.lower()
    for hint, attr in _YES_HINTS:
        if hint in lo:
            return None  # caller resolves via profile attr
    return None


class FormFiller:
    """Stateless except for config & helpers; safe to instantiate per-job."""

    def __init__(
        self,
        user_config: UserConfig,
        human: HumanBehavior,
        *,
        ask_screening: Optional[Callable[[FieldContext, ScoredJob], Awaitable[str]]] = None,
    ) -> None:
        self.user_config = user_config
        self.profile = user_config.applicant
        self.human = human
        self.ask_screening = ask_screening

    async def fill_visible_fields(self, page: "Page", scored: ScoredJob) -> int:
        """Fill every visible input/select/textarea on the page. Returns count filled."""
        filled = 0
        elements = await page.query_selector_all(
            "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]),"
            " textarea, select"
        )
        for el in elements:
            try:
                if not await el.is_visible():
                    continue
                if not await el.is_editable():
                    continue
                ctx = await self._context_for(page, el)
                if not ctx.label and not ctx.placeholder and not ctx.name:
                    continue
                value = self._resolve(ctx)
                if value is None and self.ask_screening:
                    try:
                        value = await self.ask_screening(ctx, scored)
                    except Exception as exc:
                        logger.warning(f"Screening Q&A failed for {ctx.label!r}: {exc}")
                        value = None
                if value is None or value == "":
                    continue
                ok = await self._set(page, el, ctx, value)
                if ok:
                    filled += 1
                    logger.debug(f"Filled field {ctx.label!r} = {value!r}")
                    await self.human.short_pause()
            except Exception as exc:
                logger.debug(f"Skipped a field due to error: {exc}")
                continue
        return filled

    async def _context_for(self, page: "Page", el: "ElementHandle") -> FieldContext:
        tag = (await el.evaluate("e => e.tagName")).lower()
        input_type = (await el.get_attribute("type")) or tag
        name = (await el.get_attribute("name")) or ""
        placeholder = (await el.get_attribute("placeholder")) or ""
        aria = (await el.get_attribute("aria-label")) or ""

        label_text = aria
        if not label_text:
            label_text = await el.evaluate(
                """e => {
                    const id = e.getAttribute('id');
                    if (id) {
                        const lbl = document.querySelector(`label[for='${id}']`);
                        if (lbl && lbl.innerText) return lbl.innerText;
                    }
                    let p = e.parentElement;
                    while (p) {
                        if (p.tagName === 'LABEL' && p.innerText) return p.innerText;
                        p = p.parentElement;
                    }
                    return '';
                }"""
            )
        label = (label_text or "").strip() or placeholder or name

        options: tuple[str, ...] = ()
        if tag == "select":
            opts = await el.query_selector_all("option")
            opt_texts: list[str] = []
            for opt in opts:
                txt = ((await opt.inner_text()) or "").strip()
                if txt:
                    opt_texts.append(txt)
            options = tuple(opt_texts)

        return FieldContext(
            label=label,
            input_type=input_type,
            name=name,
            placeholder=placeholder,
            options=options,
        )

    def _resolve(self, ctx: FieldContext) -> Optional[str]:
        # Yes/no boolean profile fields.
        lo = ctx.label.lower()
        for hint, attr in _YES_HINTS:
            if hint in lo and hasattr(self.profile, attr):
                return "Yes" if getattr(self.profile, attr) else "No"

        attr = _classify(ctx.label) or _classify(ctx.placeholder) or _classify(ctx.name)
        if attr:
            return _profile_value(self.profile, attr, self.user_config)
        return None

    async def _set(
        self, page: "Page", el: "ElementHandle", ctx: FieldContext, value: str
    ) -> bool:
        tag = (await el.evaluate("e => e.tagName")).lower()
        if tag == "select":
            return await self._select_option(el, ctx, value)
        if ctx.input_type in {"checkbox", "radio"}:
            wants_yes = value.strip().lower() in {"yes", "true", "1", "y"}
            if wants_yes and not await el.is_checked():
                await el.check()
            return True
        # type-able input
        try:
            await el.click()
        except Exception:
            pass
        try:
            await el.fill("")
        except Exception:
            pass
        await self.human.type_text_via_handle(el, value) if hasattr(
            self.human, "type_text_via_handle"
        ) else await el.type(value, delay=40)
        return True

    @staticmethod
    async def _select_option(el: "ElementHandle", ctx: FieldContext, value: str) -> bool:
        target = value.strip().lower()
        best: Optional[str] = None
        for opt in ctx.options:
            if opt.strip().lower() == target:
                best = opt
                break
        if best is None:
            for opt in ctx.options:
                if target and target in opt.strip().lower():
                    best = opt
                    break
        if best is None:
            # numeric match (e.g. "30 LPA" vs "30")
            digits = re.sub(r"\D", "", value)
            if digits:
                for opt in ctx.options:
                    if digits in re.sub(r"\D", "", opt):
                        best = opt
                        break
        if best is None:
            return False
        try:
            await el.select_option(label=best)
            return True
        except Exception:
            return False

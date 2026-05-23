"""Gemini-on-Vertex helper that answers screening questions.

Used by FormFiller as a fallback when a field can't be matched against
the ApplicantProfile. Keeps a tight system prompt: 1-line answers, never
fabricates qualifications.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from config.platform_config import platform
from config.user_config import UserConfig
from src.models import ScoredJob
from src.utils.gemini_client import get_model, text_generation_config
from src.utils.logger import logger
from src.utils.retry import with_retry

if TYPE_CHECKING:
    from src.apply.form_filler import FieldContext

_SYSTEM_PROMPT = (
    "You are filling out a job application form on behalf of a candidate. "
    "Given a single field's label and the candidate's profile + job context, "
    "respond with the EXACT VALUE to type into the field — nothing else. "
    "For yes/no questions answer 'Yes' or 'No'. For numeric fields return only digits. "
    "Never invent qualifications the candidate doesn't have. If unsure, return an empty string."
)

_USER_TEMPLATE = """Field label: {label}
Field type: {input_type}
Allowed options: {options}

Candidate profile:
{profile}

Job:
{job}

Answer (the exact value to fill in):"""


class ScreeningQA:
    def __init__(self, user_config: UserConfig, model: str | None = None) -> None:
        if not platform.gcp_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT not set — cannot use ScreeningQA")
        self.user_config = user_config
        self._gemini = get_model(_SYSTEM_PROMPT, model)

    async def answer(self, ctx: "FieldContext", scored: ScoredJob) -> str:
        return self._answer_sync(ctx, scored)

    @with_retry(Exception, attempts=2, initial_wait=1.0, max_wait=10.0)
    def _answer_sync(self, ctx: "FieldContext", scored: ScoredJob) -> str:
        profile = self.user_config.applicant
        profile_dict = {
            "full_name": profile.full_name,
            "email": profile.email,
            "phone": profile.phone,
            "current_company": profile.current_company,
            "current_role": profile.current_role,
            "current_location": profile.current_location,
            "expected_ctc_lpa": profile.expected_ctc_lpa,
            "current_ctc_lpa": profile.current_ctc_lpa,
            "notice_period_days": profile.notice_period_days,
            "experience_years": self.user_config.experience_years,
            "skills": list(self.user_config.skills),
            "willing_to_relocate": profile.willing_to_relocate,
            "open_to_remote": profile.open_to_remote,
            "work_authorization": profile.work_authorization,
        }
        job = scored.job
        prompt = _USER_TEMPLATE.format(
            label=ctx.label or ctx.placeholder or ctx.name,
            input_type=ctx.input_type,
            options=", ".join(ctx.options) if ctx.options else "(free text)",
            profile=json.dumps(profile_dict, indent=2),
            job=f"{job.company} — {job.title} ({job.location or 'unspecified'})",
        )
        response = self._gemini.generate_content(
            prompt,
            generation_config=text_generation_config(max_tokens=64),
        )
        text = response.text.strip()
        # Strip surrounding quotes Gemini sometimes adds for short answers.
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            text = text[1:-1].strip()
        logger.debug(f"ScreeningQA[{ctx.label!r}] -> {text!r}")
        return text

"""AI-generated cold outreach emails to recruiters using Gemini on Vertex.

For static templated referral emails, use ReferralTemplate instead.
This module is for personalized cold outreach where personalization moves the needle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from config.platform_config import platform
from src.models import JDAnalysis, Job, Recruiter
from src.utils.gemini_client import get_model, json_generation_config
from src.utils.logger import logger
from src.utils.retry import with_retry

_SYSTEM_PROMPT = (
    "You write concise, professional cold outreach emails for a job seeker. "
    "Output strict JSON with exactly two keys: subject, body. No prose, no fences."
)

_USER_TEMPLATE = """Compose a cold outreach email.

Recruiter:
  Name: {recruiter_name}
  Title: {recruiter_title}
  Company: {recruiter_company}

Job:
  Title: {job_title}
  Company: {job_company}
  Description (excerpt): {job_desc}

Sender:
  Name: {sender_name}
  Current role: 3 years software engineer at Lucid Motors (Python, FastAPI, AWS, GCP)
  Top matching skills for this JD: {top_skills}

Constraints:
- Subject: under 70 chars, mention the role and a hook (no clickbait).
- Body: 3-4 sentences max, ~80 words. Personalize ONE thing (skill, project area, or company focus).
- Open with first name, end with the sender's first name + "Best,"
- No emojis, no buzzwords ("rockstar", "ninja"), no flattery.
- Do NOT fabricate skills the sender doesn't have.

Return ONLY this JSON:
{{"subject": "...", "body": "..."}}"""


@dataclass(frozen=True)
class ColdEmail:
    subject: str
    body: str


class ColdEmailComposer:
    """Generates personalized cold outreach via Gemini on Vertex AI."""

    def __init__(self, model: str | None = None, sender_name: str = "Sameet Sabu") -> None:
        if not platform.gcp_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT not set — cannot compose AI emails")
        self._gemini = get_model(_SYSTEM_PROMPT, model)
        self.sender_name = sender_name

    @with_retry(Exception, attempts=2, initial_wait=2.0, max_wait=10.0)
    def compose(
        self,
        recruiter: Recruiter,
        job: Job,
        analysis: JDAnalysis | None = None,
    ) -> ColdEmail:
        top_skills = ", ".join(
            (analysis.candidate_has_skills[:5] if analysis else ["Python", "FastAPI", "AWS"])
        )
        prompt = _USER_TEMPLATE.format(
            recruiter_name=recruiter.name,
            recruiter_title=recruiter.title or "Recruiter",
            recruiter_company=recruiter.company,
            job_title=job.title,
            job_company=job.company,
            job_desc=(job.description or "")[:600],
            sender_name=self.sender_name,
            top_skills=top_skills,
        )
        logger.debug(f"Composing cold email for {recruiter.name} @ {recruiter.company}")
        response = self._gemini.generate_content(
            prompt,
            generation_config=json_generation_config(max_tokens=400),
        )
        parsed = self._parse(response.text)
        return ColdEmail(subject=parsed["subject"].strip(), body=parsed["body"].strip())

    @staticmethod
    def _parse(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"No JSON object found in cold email output: {text[:200]}")
        return json.loads(text[start : end + 1])

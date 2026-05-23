"""Gemini-on-Vertex JD analyzer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from config.platform_config import platform
from src.models import JDAnalysis, Job
from src.utils.gemini_client import get_model, json_generation_config
from src.utils.logger import logger
from src.utils.retry import with_retry

_SYSTEM_PROMPT = (
    "You are an experienced technical recruiter. You analyze job descriptions "
    "against a candidate's resume. Return ONLY valid JSON, no markdown, no prose, no explanations."
)

_USER_TEMPLATE = """Job description:
---
{jd}
---

Candidate resume (JSON):
---
{resume}
---

Respond with ONLY valid JSON (no markdown, no prose, no explanation). Use exactly these keys:
{{
  "match_score": <int 0-100>,
  "required_skills": <array of strings>,
  "preferred_skills": <array of strings>,
  "candidate_has_skills": <array of strings>,
  "missing_skills": <array of strings>,
  "key_responsibilities": <array of strings>,
  "keywords_to_include": <array of strings>,
  "company_culture": <string>,
  "summary": <string>,
  "should_apply": <boolean>,
  "reason": <string>
}}

IMPORTANT:
- Return ONLY the JSON object, nothing else
- Ensure all strings are valid JSON (escape quotes if needed)
- Be strict on match_score: 90+ only if candidate clearly meets all required skills
- Set should_apply=false if missing 3+ required skills
- DO NOT include markdown fences or explanatory text"""


# USD per 1M tokens (Gemini pricing as of 2026; update if rates change).
_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash": (0.075, 0.30),
    "gemini-2.0-pro": (1.25, 5.00),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
}


def _lookup_rates(model_id: str) -> tuple[float, float]:
    bare = model_id.split("-0")[0].lower()  # strip version suffix like -001
    for key, rates in _PRICING.items():
        if bare.startswith(key) or key in bare:
            return rates
    logger.warning(f"No pricing entry for {model_id!r}; assuming Flash rates")
    return (0.075, 0.30)


@dataclass
class UsageStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    per_call: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def summary(self) -> str:
        return (
            f"Gemini usage — {self.calls} calls, "
            f"{self.input_tokens:,} input + {self.output_tokens:,} output "
            f"= {self.total_tokens:,} tokens, "
            f"${self.cost_usd:.4f}"
        )


class JDAnalyzer:
    def __init__(self, model: str | None = None) -> None:
        if not platform.gcp_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT not set in .env")
        self.model_name = model or platform.gemini_model
        self._gemini = get_model(_SYSTEM_PROMPT, self.model_name)
        self.input_rate, self.output_rate = _lookup_rates(self.model_name)
        self.usage = UsageStats()

    @with_retry(Exception, attempts=3, initial_wait=2.0, max_wait=20.0)
    def analyze(self, job: Job, base_resume: dict[str, Any]) -> JDAnalysis:
        prompt = _USER_TEMPLATE.format(
            jd=job.description or job.title,
            resume=json.dumps(base_resume, indent=2),
        )
        logger.debug(f"Analyzing {job.company} / {job.title} via {self.model_name}")
        response = self._gemini.generate_content(
            prompt,
            generation_config=json_generation_config(max_tokens=4096),
        )
        self._record_usage(response, label=f"{job.company} / {job.title}")
        parsed = self._parse(response.text)
        return JDAnalysis(**parsed)

    def _record_usage(self, response: Any, *, label: str) -> None:
        meta = getattr(response, "usage_metadata", None)
        in_tok = getattr(meta, "prompt_token_count", 0) or 0
        out_tok = getattr(meta, "candidates_token_count", 0) or 0
        cost = (in_tok / 1_000_000) * self.input_rate + (out_tok / 1_000_000) * self.output_rate

        self.usage.calls += 1
        self.usage.input_tokens += in_tok
        self.usage.output_tokens += out_tok
        self.usage.cost_usd += cost
        self.usage.per_call.append(
            {"label": label, "input": in_tok, "output": out_tok, "cost_usd": cost}
        )
        logger.info(
            f"Gemini [{label}] {in_tok} in + {out_tok} out tokens "
            f"(${cost:.4f}) | running total: ${self.usage.cost_usd:.4f}"
        )

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].lstrip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1:
            logger.error(f"Failed to parse Gemini response: {text[:300]!r}")
            raise ValueError(f"No JSON object found in model output: {text[:200]!r}")

        json_str = cleaned[start : end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.error(f"JSON parse error: {exc}")
            logger.error(f"Attempted to parse: {json_str[:300]!r}")
            raise ValueError(f"Invalid JSON in model output: {exc}") from exc

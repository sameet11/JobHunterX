"""Shared Gemini (Vertex AI) client factory."""

from __future__ import annotations

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from config.platform_config import platform

_initialized = False


def _ensure_init() -> None:
    global _initialized
    if not _initialized:
        vertexai.init(project=platform.gcp_project, location=platform.gcp_region)
        _initialized = True


def get_model(system_instruction: str, model: str | None = None) -> GenerativeModel:
    _ensure_init()
    return GenerativeModel(
        model_name=model or platform.gemini_model,
        system_instruction=system_instruction,
    )


def json_generation_config(max_tokens: int = 4096) -> GenerationConfig:
    return GenerationConfig(
        temperature=0.0,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
    )


def text_generation_config(max_tokens: int = 128) -> GenerationConfig:
    return GenerationConfig(
        temperature=0.0,
        max_output_tokens=max_tokens,
    )

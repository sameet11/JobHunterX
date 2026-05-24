"""Shared Gemini client (google-genai SDK with GEMINI_API_KEY)."""

from __future__ import annotations

from google import genai
from google.genai import types

from config.platform_config import platform

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not platform.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in environment")
        _client = genai.Client(api_key=platform.gemini_api_key)
    return _client


def generate_text(
    prompt: str,
    system_instruction: str,
    max_tokens: int = 128,
    json_mode: bool = False,
    model: str | None = None,
) -> str:
    config_kwargs: dict = {
        "system_instruction": system_instruction,
        "temperature": 0.0,
        "max_output_tokens": max_tokens,
    }
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"
    response = _get_client().models.generate_content(
        model=model or platform.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return response.text or ""

"""Tenacity-based retry helper with exponential backoff."""

from __future__ import annotations

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def with_retry(
    *exception_types: type[BaseException],
    attempts: int = 3,
    initial_wait: float = 1.0,
    max_wait: float = 30.0,
):
    """Decorator: retry on the listed exception types with exponential backoff."""
    if not exception_types:
        exception_types = (Exception,)
    return retry(
        retry=retry_if_exception_type(exception_types),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=initial_wait, max=max_wait),
        reraise=True,
    )

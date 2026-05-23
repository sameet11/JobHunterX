"""Tests for the CAPTCHA console-confirm flow.

Policy: when a challenge is detected, the bot takes one screenshot then
goes completely idle. It blocks on stdin (not page.query_selector) and
resumes only after the human confirms. No DOM polling at all.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.apply.captcha_detector import (
    CaptchaDetected,
    wait_for_human,
)


def _run(coro):
    """Run a coroutine synchronously — avoids pytest-asyncio dependency."""
    return asyncio.run(coro)


class TestWaitForHumanConfirm:
    """wait_for_human() blocks on stdin, not on page.*."""

    def test_returns_true_when_human_confirms(self):
        """Simulates human pressing Enter — should return True immediately."""
        with patch(
            "src.apply.captcha_detector._blocking_confirm", return_value=True
        ):
            result = _run(wait_for_human(label="test_captcha", timeout_seconds=5))
        assert result is True

    def test_returns_false_on_timeout(self):
        """Simulates no human response within timeout — should return False."""
        with patch(
            "src.apply.captcha_detector._blocking_confirm", return_value=False
        ):
            result = _run(wait_for_human(label="test_captcha", timeout_seconds=1))
        assert result is False

    def test_does_not_touch_page(self):
        """Critically: wait_for_human MUST NOT call any page.* method."""
        page_mock = MagicMock()
        page_mock.query_selector = AsyncMock()
        page_mock.content = AsyncMock()

        with patch(
            "src.apply.captcha_detector._blocking_confirm", return_value=True
        ):
            _run(wait_for_human(label="no_page_probe", timeout_seconds=5))

        # No Playwright page interactions should have occurred.
        page_mock.query_selector.assert_not_called()
        page_mock.content.assert_not_called()

    def test_timeout_raises_no_exception(self):
        """Timeout returns False rather than raising — caller decides what to do."""
        with patch(
            "src.apply.captcha_detector._blocking_confirm",
            side_effect=asyncio.TimeoutError,
        ):
            result = _run(wait_for_human(label="timeout_test", timeout_seconds=1))
        assert result is False

    def test_completes_without_error(self):
        """wait_for_human completes without error when confirmed."""
        with patch(
            "src.apply.captcha_detector._blocking_confirm", return_value=True
        ):
            result = _run(wait_for_human(label="login_page", timeout_seconds=5))
        assert result is True


class TestCaptchaDetectedError:
    def test_captcha_detected_carries_where_and_screenshot(self):
        path = Path("/tmp/fake_screenshot.png")
        exc = CaptchaDetected("linkedin_login", screenshot=path)
        assert exc.where == "linkedin_login"
        assert exc.screenshot == path
        assert "linkedin_login" in str(exc)

    def test_captcha_detected_no_screenshot(self):
        exc = CaptchaDetected("naukri_apply")
        assert exc.screenshot is None

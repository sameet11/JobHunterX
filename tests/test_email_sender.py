"""Tests for the email sender (Phase 3)."""

import pytest

from src.models import OutreachStatus
from src.outreach.email_sender import (
    DryRunEmailSender,
    SendResult,
    SMTPEmailSender,
    get_email_sender,
)


class TestDryRunEmailSender:
    def test_send_returns_success(self, drafted_outreach_message):
        sender = DryRunEmailSender()
        drafted_outreach_message.status = OutreachStatus.APPROVED
        result = sender.send(drafted_outreach_message)
        assert result.success is True
        assert result.message_id.startswith("dry-run-")

    def test_send_records_message(self, drafted_outreach_message):
        sender = DryRunEmailSender()
        drafted_outreach_message.status = OutreachStatus.APPROVED
        sender.send(drafted_outreach_message)
        assert len(sender.sent) == 1
        assert sender.sent[0].recruiter.email == "priya.sharma@google.com"

    def test_send_multiple_messages(self, drafted_outreach_message):
        sender = DryRunEmailSender()
        drafted_outreach_message.status = OutreachStatus.APPROVED
        for _ in range(3):
            sender.send(drafted_outreach_message)
        assert len(sender.sent) == 3

    def test_dry_run_does_not_check_status(self, drafted_outreach_message):
        """DryRun is a black-box test stub — it just records, no validation."""
        sender = DryRunEmailSender()
        # Even if status is DRAFTED (not approved), dry-run captures it
        result = sender.send(drafted_outreach_message)
        assert result.success is True

    def test_unique_message_ids(self, drafted_outreach_message):
        sender = DryRunEmailSender()
        drafted_outreach_message.status = OutreachStatus.APPROVED
        ids = {sender.send(drafted_outreach_message).message_id for _ in range(5)}
        assert len(ids) == 5, "Each dry-run send should get a unique ID"


class TestSMTPSenderConfig:
    def test_smtp_requires_password(self, monkeypatch):
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
        with pytest.raises(RuntimeError, match="GMAIL_APP_PASSWORD"):
            SMTPEmailSender(sender_email="x@y.com", sender_password="")

    def test_smtp_accepts_password_from_env(self, monkeypatch):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-password-12345")
        sender = SMTPEmailSender(sender_email="x@y.com")
        assert sender.sender_password == "test-password-12345"


class TestSMTPSenderValidation:
    def test_send_rejects_recruiter_without_email(
        self, drafted_outreach_message, sample_recruiter_no_email, monkeypatch
    ):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-password")
        sender = SMTPEmailSender(sender_email="me@gmail.com")
        drafted_outreach_message.recruiter = sample_recruiter_no_email
        drafted_outreach_message.status = OutreachStatus.APPROVED
        result = sender.send(drafted_outreach_message)
        assert result.success is False
        assert "no email" in result.error.lower()

    def test_send_rejects_unapproved_status(
        self, drafted_outreach_message, monkeypatch
    ):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-password")
        sender = SMTPEmailSender(sender_email="me@gmail.com")
        # status is DRAFTED, not APPROVED/EDITED — should refuse
        result = sender.send(drafted_outreach_message)
        assert result.success is False
        assert "not sendable" in result.error.lower() or "drafted" in result.error.lower()


class TestEmailSenderFactory:
    def test_dry_run_factory(self):
        sender = get_email_sender("dry_run")
        assert isinstance(sender, DryRunEmailSender)

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown email sender mode"):
            get_email_sender("nonexistent")

    def test_smtp_factory_requires_email(self, monkeypatch):
        monkeypatch.delenv("GMAIL_SENDER_EMAIL", raising=False)
        with pytest.raises(RuntimeError, match="sender_email required"):
            get_email_sender("smtp")


class TestSendResult:
    def test_success_with_message_id(self):
        r = SendResult(success=True, message_id="abc123")
        assert r.success
        assert r.message_id == "abc123"
        assert r.error == ""

    def test_failure_with_error(self):
        r = SendResult(success=False, error="SMTP timeout")
        assert not r.success
        assert r.error == "SMTP timeout"

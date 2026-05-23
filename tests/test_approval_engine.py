"""Tests for the approval engine (Phase 3)."""

from src.models import OutreachStatus
from src.outreach.approval_engine import ApprovalEngine, ApprovalMode


class TestAutoApprove:
    def test_auto_approve_marks_drafted_as_approved(self, drafted_outreach_message):
        engine = ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE)
        result = engine.review(drafted_outreach_message)
        assert result.status == OutreachStatus.APPROVED

    def test_auto_approve_does_not_change_subject_body(self, drafted_outreach_message):
        original_subject = drafted_outreach_message.subject
        original_body = drafted_outreach_message.body
        engine = ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE)
        engine.review(drafted_outreach_message)
        assert drafted_outreach_message.subject == original_subject
        assert drafted_outreach_message.body == original_body


class TestAutoReject:
    def test_auto_reject_marks_as_rejected(self, drafted_outreach_message):
        engine = ApprovalEngine(mode=ApprovalMode.AUTO_REJECT)
        result = engine.review(drafted_outreach_message)
        assert result.status == OutreachStatus.REJECTED


class TestInteractiveMode:
    def test_approve_choice(self, drafted_outreach_message):
        engine = ApprovalEngine(
            mode=ApprovalMode.INTERACTIVE,
            prompt_fn=lambda _: "a",
        )
        result = engine.review(drafted_outreach_message)
        assert result.status == OutreachStatus.APPROVED

    def test_reject_choice(self, drafted_outreach_message):
        engine = ApprovalEngine(
            mode=ApprovalMode.INTERACTIVE,
            prompt_fn=lambda _: "r",
        )
        result = engine.review(drafted_outreach_message)
        assert result.status == OutreachStatus.REJECTED

    def test_skip_choice_treated_as_reject(self, drafted_outreach_message):
        engine = ApprovalEngine(
            mode=ApprovalMode.INTERACTIVE,
            prompt_fn=lambda _: "s",
        )
        result = engine.review(drafted_outreach_message)
        assert result.status == OutreachStatus.REJECTED

    def test_invalid_then_approve(self, drafted_outreach_message):
        """Invalid input should re-prompt; eventually accept valid input."""
        responses = iter(["x", "  ", "approve"])
        engine = ApprovalEngine(
            mode=ApprovalMode.INTERACTIVE,
            prompt_fn=lambda _: next(responses),
        )
        result = engine.review(drafted_outreach_message)
        assert result.status == OutreachStatus.APPROVED

    def test_full_word_choices_work(self, drafted_outreach_message):
        engine = ApprovalEngine(
            mode=ApprovalMode.INTERACTIVE,
            prompt_fn=lambda _: "REJECT",
        )
        result = engine.review(drafted_outreach_message)
        assert result.status == OutreachStatus.REJECTED


class TestApprovalEngineRendering:
    def test_render_does_not_raise(self, drafted_outreach_message, capsys):
        ApprovalEngine._render(drafted_outreach_message)
        captured = capsys.readouterr()
        assert "Priya Sharma" in captured.out
        assert "TechCorp" in captured.out
        assert drafted_outreach_message.subject in captured.out

    def test_render_shows_recipient_email(self, drafted_outreach_message, capsys):
        ApprovalEngine._render(drafted_outreach_message)
        captured = capsys.readouterr()
        assert "priya.sharma@google.com" in captured.out

    def test_render_shows_channel_and_style(self, drafted_outreach_message, capsys):
        ApprovalEngine._render(drafted_outreach_message)
        captured = capsys.readouterr()
        assert "email" in captured.out
        assert "referral" in captured.out

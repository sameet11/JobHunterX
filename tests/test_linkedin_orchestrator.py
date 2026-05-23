"""Tests for LinkedInOutreachOrchestrator.

Verifies DM vs invite routing, approval gate, tracker writes, and cooldown.
Uses MockLinkedInOutreach so no browser is needed.
"""

from __future__ import annotations

import pytest

from src.models import OutreachChannel, OutreachStatus, OutreachStyle
from src.outreach.approval_engine import ApprovalEngine, ApprovalMode
from src.outreach.linkedin_orchestrator import LinkedInOutreachOrchestrator
from src.outreach.linkedin_outreach import MockLinkedInOutreach


def _make_orch(
    backend: MockLinkedInOutreach,
    mode: ApprovalMode = ApprovalMode.AUTO_APPROVE,
    db=None,
    sheets=None,
) -> LinkedInOutreachOrchestrator:
    return LinkedInOutreachOrchestrator(
        backend=backend,
        approval=ApprovalEngine(mode=mode),
        db=db,
        sheets=sheets,
        max_people_per_company=3,
        cooldown_days=90,
        current_company="Lucid Motors (LTM)",
        sender_name="Sameet Sabu",
    )


class TestDMVsInviteRouting:
    def test_connection_gets_dm(self, scored_job_backend, temp_db):
        # Mark the first mock recruiter (Hiring Manager TechCorp) as a connection
        backend = MockLinkedInOutreach(
            connection_emails={"recruiter@techcorp.com"}
        )
        orch = _make_orch(backend, db=temp_db)
        results = orch.reach_out_for_job(scored_job_backend)

        dms = [m for m in results if m.channel == OutreachChannel.LINKEDIN_MSG]
        assert len(dms) >= 1

    def test_non_connection_gets_invite(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach(connection_emails=set())
        orch = _make_orch(backend, db=temp_db)
        results = orch.reach_out_for_job(scored_job_backend)

        invites = [m for m in results if m.channel == OutreachChannel.LINKEDIN_INVITE]
        assert len(invites) >= 1

    def test_dm_body_includes_job_link(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach(
            connection_emails={"recruiter@techcorp.com"}
        )
        orch = _make_orch(backend, db=temp_db)
        results = orch.reach_out_for_job(scored_job_backend)

        dms = [m for m in results if m.channel == OutreachChannel.LINKEDIN_MSG]
        for dm in dms:
            assert scored_job_backend.job.apply_url in dm.body

    def test_dm_body_includes_ltm(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach(
            connection_emails={"recruiter@techcorp.com"}
        )
        orch = _make_orch(backend, db=temp_db)
        results = orch.reach_out_for_job(scored_job_backend)

        dms = [m for m in results if m.channel == OutreachChannel.LINKEDIN_MSG]
        for dm in dms:
            assert "Lucid Motors (LTM)" in dm.body

    def test_invite_note_within_300_chars(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach(connection_emails=set())
        orch = _make_orch(backend, db=temp_db)
        results = orch.reach_out_for_job(scored_job_backend)

        invites = [m for m in results if m.channel == OutreachChannel.LINKEDIN_INVITE]
        for inv in invites:
            assert len(inv.body) <= 300


class TestApprovalGate:
    def test_rejected_messages_not_sent(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach()
        orch = _make_orch(backend, mode=ApprovalMode.AUTO_REJECT, db=temp_db)
        results = orch.reach_out_for_job(scored_job_backend)

        assert all(m.status == OutreachStatus.REJECTED for m in results)
        assert len(backend.dms_sent) == 0
        assert len(backend.invites_sent) == 0

    def test_approved_messages_are_sent(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach()
        orch = _make_orch(backend, mode=ApprovalMode.AUTO_APPROVE, db=temp_db)
        results = orch.reach_out_for_job(scored_job_backend)

        sent = [m for m in results if m.status == OutreachStatus.SENT]
        assert len(sent) >= 1


class TestTrackerWrites:
    def test_writes_to_db(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach()
        orch = _make_orch(backend, db=temp_db)
        orch.reach_out_for_job(scored_job_backend)

        cur = temp_db._conn.execute("SELECT COUNT(*) FROM outreach")
        assert cur.fetchone()[0] >= 1

    def test_channel_stored_in_db(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach(connection_emails=set())  # all invites
        orch = _make_orch(backend, db=temp_db)
        orch.reach_out_for_job(scored_job_backend)

        cur = temp_db._conn.execute(
            "SELECT DISTINCT channel FROM outreach"
        )
        channels = {row[0] for row in cur.fetchall()}
        assert "linkedin_invite" in channels


class TestCooldown:
    def test_cooldown_skips_already_contacted(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach()
        orch = _make_orch(backend, db=temp_db)

        # First run — should send
        first = orch.reach_out_for_job(scored_job_backend)
        assert any(m.status == OutreachStatus.SENT for m in first)

        # Second run — all within cooldown, nothing sent
        second = orch.reach_out_for_job(scored_job_backend)
        assert all(m.status == OutreachStatus.SENT for m in first)  # first still sent
        assert len(second) == 0  # second skipped

    def test_daily_remaining_zero_returns_empty(self, scored_job_backend, temp_db):
        backend = MockLinkedInOutreach()
        orch = _make_orch(backend, db=temp_db)
        results = orch.reach_out_for_job(scored_job_backend, daily_remaining=0)
        assert results == []


class TestReferralEmailJobLink:
    """Regression: referral email now includes job link + Lucid Motors (LTM)."""

    def test_referral_email_contains_job_link(self, scored_job_backend, temp_db):
        from src.outreach.approval_engine import ApprovalEngine, ApprovalMode
        from src.outreach.email_sender import DryRunEmailSender
        from src.outreach.orchestrator import OutreachOrchestrator
        from src.outreach.recruiter_finder import MockRecruiterFinder

        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
            current_company="Lucid Motors (LTM)",
        )
        results = orch.reach_out_for_job(scored_job_backend)
        for msg in results:
            assert scored_job_backend.job.apply_url in msg.body
            assert "Lucid Motors (LTM)" in msg.body

    def test_referral_email_contains_ltm(self, scored_job_backend, temp_db):
        from src.outreach.approval_engine import ApprovalEngine, ApprovalMode
        from src.outreach.email_sender import DryRunEmailSender
        from src.outreach.orchestrator import OutreachOrchestrator
        from src.outreach.recruiter_finder import MockRecruiterFinder

        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
        )
        results = orch.reach_out_for_job(scored_job_backend)
        for msg in results:
            assert "Lucid Motors" in msg.body

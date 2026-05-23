"""End-to-end orchestrator tests using all stubs (Phase 3)."""

from src.models import OutreachStatus, OutreachStyle
from src.outreach.approval_engine import ApprovalEngine, ApprovalMode
from src.outreach.email_sender import DryRunEmailSender
from src.outreach.orchestrator import OutreachOrchestrator
from src.outreach.recruiter_finder import MockRecruiterFinder


class TestOrchestratorEndToEnd:
    """Verify the full pipeline: find → compose → approve → send → track."""

    def test_referral_pipeline_auto_approve_dry_run(self, scored_job_backend, temp_db):
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
            style=OutreachStyle.REFERRAL,
            attach_resume=False,
            max_recruiters_per_company=2,
        )
        results = orch.reach_out_for_job(scored_job_backend)
        assert len(results) == 2  # MockRecruiterFinder returns 1 for unknown TechCorp+max_results=2
        # All should be SENT after AUTO_APPROVE + DryRun
        for msg in results:
            assert msg.status == OutreachStatus.SENT
            assert msg.message_id.startswith("dry-run-")
            assert msg.sent_at is not None

    def test_auto_reject_skips_sending(self, scored_job_backend, temp_db):
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_REJECT),
            sender=DryRunEmailSender(),
            db=temp_db,
            style=OutreachStyle.REFERRAL,
        )
        results = orch.reach_out_for_job(scored_job_backend)
        assert len(results) >= 1
        for msg in results:
            assert msg.status == OutreachStatus.REJECTED

    def test_orchestrator_writes_to_db(self, scored_job_backend, temp_db):
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
            style=OutreachStyle.REFERRAL,
        )
        orch.reach_out_for_job(scored_job_backend)
        # Each draft AND each sent message updates the same row
        cur = temp_db._conn.execute("SELECT COUNT(*) FROM outreach")
        count = cur.fetchone()[0]
        assert count >= 1

    def test_cooldown_skips_recently_contacted(self, scored_job_backend, temp_db):
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
            style=OutreachStyle.REFERRAL,
            cooldown_days=90,
        )
        first_run = orch.reach_out_for_job(scored_job_backend)
        # Mark all as SENT (already done by orch)
        sent_count_first = sum(1 for m in first_run if m.status == OutreachStatus.SENT)
        assert sent_count_first > 0

        # Second run should skip everyone (cooldown)
        second_run = orch.reach_out_for_job(scored_job_backend)
        assert len(second_run) == 0, "All recruiters should be skipped within cooldown"

    def test_daily_remaining_zero_returns_empty(self, scored_job_backend, temp_db):
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
        )
        results = orch.reach_out_for_job(scored_job_backend, daily_remaining=0)
        assert results == []

    def test_daily_limit_partial(self, scored_job_backend, temp_db):
        """If only 1 message can be sent, stop after the first."""
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
            max_recruiters_per_company=3,
        )
        results = orch.reach_out_for_job(scored_job_backend, daily_remaining=1)
        sent = [m for m in results if m.status == OutreachStatus.SENT]
        assert len(sent) == 1


class TestOrchestratorReferralStyle:
    def test_referral_template_used_when_style_is_referral(
        self, scored_job_backend, temp_db
    ):
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
            style=OutreachStyle.REFERRAL,
        )
        results = orch.reach_out_for_job(scored_job_backend)
        assert all(m.style == OutreachStyle.REFERRAL for m in results)
        assert all("Referral Request" in m.subject for m in results)

    def test_subject_contains_company_and_role(self, scored_job_backend, temp_db):
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
            style=OutreachStyle.REFERRAL,
        )
        results = orch.reach_out_for_job(scored_job_backend)
        for msg in results:
            assert msg.job.company in msg.subject
            assert msg.job.title in msg.subject
            assert msg.recruiter.name in msg.body


class TestOrchestratorColdStyleFallback:
    def test_cold_falls_back_to_referral_when_composer_missing(
        self, scored_job_backend, temp_db
    ):
        """If style=COLD but no composer provided, gracefully falls back to referral template."""
        orch = OutreachOrchestrator(
            finder=MockRecruiterFinder(),
            approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
            sender=DryRunEmailSender(),
            db=temp_db,
            style=OutreachStyle.COLD,
            cold_composer=None,  # no composer available
        )
        results = orch.reach_out_for_job(scored_job_backend)
        # Should still produce results using referral template fallback
        assert len(results) > 0
        for msg in results:
            assert msg.style == OutreachStyle.REFERRAL  # fell back

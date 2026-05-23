"""Phase 3 orchestrator: find recruiters → compose email → approve → send → track.

Tied together so main.py can call a single function per applied job.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models import (
    Job,
    JDAnalysis,
    OutreachChannel,
    OutreachMessage,
    OutreachStatus,
    OutreachStyle,
    Recruiter,
    ScoredJob,
)
from src.outreach.approval_engine import ApprovalEngine, ApprovalMode
from src.outreach.cold_email_composer import ColdEmail, ColdEmailComposer
from src.outreach.email_sender import BaseEmailSender, get_email_sender
from src.outreach.recruiter_finder import BaseRecruiterFinder, get_recruiter_finder
from src.outreach.referral_template import ReferralTemplate
from src.tracker.google_sheets import GoogleSheets
from src.tracker.local_db import LocalDB
from src.utils.logger import logger


class OutreachOrchestrator:
    """Wires recruiter finding + email drafting + approval + sending + tracking."""

    def __init__(
        self,
        finder: BaseRecruiterFinder,
        approval: ApprovalEngine,
        sender: BaseEmailSender,
        db: LocalDB,
        sheets: Optional[GoogleSheets] = None,
        *,
        style: OutreachStyle = OutreachStyle.REFERRAL,
        attach_resume: bool = True,
        cold_composer: Optional[ColdEmailComposer] = None,
        referral_template: Optional[ReferralTemplate] = None,
        max_recruiters_per_company: int = 3,
        cooldown_days: int = 90,
        current_company: str = "",
        sender_name: str = "",
        sender_email: str = "",
        sender_phone: str = "",
    ) -> None:
        self.finder = finder
        self.approval = approval
        self.sender = sender
        self.db = db
        self.sheets = sheets
        self.style = style
        self.attach_resume = attach_resume
        self.cold_composer = cold_composer
        self.referral_template = referral_template or ReferralTemplate()
        self.max_recruiters = max_recruiters_per_company
        self.cooldown_days = cooldown_days
        self.current_company = current_company
        self.sender_name = sender_name
        self.sender_email = sender_email
        self.sender_phone = sender_phone

    def reach_out_for_job(
        self,
        scored: ScoredJob,
        resume_path: Optional[Path] = None,
        daily_remaining: int = 999,
    ) -> list[OutreachMessage]:
        """Run the full outreach pipeline for one job. Returns sent/drafted messages."""
        if daily_remaining <= 0:
            logger.info("Daily outreach limit hit — skipping further outreach")
            return []

        job = scored.job
        analysis = scored.analysis

        recruiters = self.finder.find(job.company, max_results=self.max_recruiters)
        logger.info(f"Found {len(recruiters)} recruiter(s) at {job.company}")

        results: list[OutreachMessage] = []
        for recruiter in recruiters:
            if daily_remaining <= 0:
                break
            if self.db.already_contacted(recruiter.email, within_days=self.cooldown_days):
                logger.info(f"Skipping {recruiter.email} — contacted within {self.cooldown_days} days")
                continue

            draft = self._compose(recruiter, job, analysis)
            self.db.upsert_outreach(draft)

            reviewed = self.approval.review(draft)
            self.db.upsert_outreach(reviewed)

            if reviewed.status not in (OutreachStatus.APPROVED, OutreachStatus.EDITED):
                logger.info(f"Not sending to {recruiter.email}: status={reviewed.status.value}")
                if self.sheets is not None:
                    self.sheets.append_outreach(reviewed)
                results.append(reviewed)
                continue

            send_result = self.sender.send(
                reviewed,
                attachment=resume_path if self.attach_resume else None,
            )
            if send_result.success:
                reviewed.status = OutreachStatus.SENT
                reviewed.message_id = send_result.message_id
                reviewed.sent_at = datetime.utcnow()
                daily_remaining -= 1
            else:
                reviewed.status = OutreachStatus.FAILED
                reviewed.error = send_result.error

            self.db.upsert_outreach(reviewed)
            if self.sheets is not None:
                self.sheets.append_outreach(reviewed)
            results.append(reviewed)

        return results

    def _compose(
        self,
        recruiter: Recruiter,
        job: Job,
        analysis: Optional[JDAnalysis],
    ) -> OutreachMessage:
        if self.style == OutreachStyle.COLD and self.cold_composer is not None:
            try:
                cold = self.cold_composer.compose(recruiter, job, analysis)
                return OutreachMessage(
                    recruiter=recruiter,
                    job=job,
                    channel=OutreachChannel.EMAIL,
                    style=OutreachStyle.COLD,
                    subject=cold.subject,
                    body=cold.body,
                    status=OutreachStatus.DRAFTED,
                )
            except Exception as exc:
                logger.warning(f"Cold composer failed ({exc}); falling back to referral template")

        rendered = self.referral_template.render(
            person_name=recruiter.name,
            company=job.company,
            role=job.title,
            job_link=job.apply_url,
            current_company=self.current_company,
            sender_name=self.sender_name,
            sender_email=self.sender_email,
            sender_phone=self.sender_phone,
        )
        return OutreachMessage(
            recruiter=recruiter,
            job=job,
            channel=OutreachChannel.EMAIL,
            style=OutreachStyle.REFERRAL,
            subject=rendered.subject,
            body=rendered.body,
            status=OutreachStatus.DRAFTED,
        )


def build_orchestrator_from_config(
    user_config,
    db: LocalDB,
    sheets: Optional[GoogleSheets] = None,
) -> OutreachOrchestrator:
    """Construct an orchestrator from UserConfig flags. Convenience for main.py."""
    finder = get_recruiter_finder(user_config.recruiter_finder_source)
    approval = ApprovalEngine(mode=ApprovalMode(user_config.approval_mode))
    sender = get_email_sender(user_config.email_sender_mode, sender_email=user_config.applicant.email)

    style = OutreachStyle(user_config.email_style)
    cold_composer: Optional[ColdEmailComposer] = None
    if style == OutreachStyle.COLD:
        try:
            cold_composer = ColdEmailComposer(sender_name=user_config.applicant.full_name)
        except Exception as exc:
            logger.warning(f"Cold composer unavailable ({exc}); will fall back to referral template")

    return OutreachOrchestrator(
        finder=finder,
        approval=approval,
        sender=sender,
        db=db,
        sheets=sheets,
        style=style,
        attach_resume=user_config.attach_resume_to_outreach,
        cold_composer=cold_composer,
        max_recruiters_per_company=user_config.max_recruiters_per_company,
        cooldown_days=user_config.outreach_cooldown_days,
        current_company=user_config.applicant.current_company,
        sender_name=user_config.applicant.full_name,
        sender_email=user_config.applicant.email,
        sender_phone=user_config.applicant.phone,
    )

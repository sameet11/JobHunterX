"""Phase 3b — LinkedIn-side outreach per applied job.

For each applied company:

  1. Pull up to N people from LinkedIn (`find_company_people`).
  2. For each person:
       * if 1st-degree connection → render DM template, run through
         ApprovalEngine, then `send_dm`. Persist as channel=LINKEDIN_MSG.
       * else → render connection-request note (≤300 chars), approve,
         then `send_connection_request`. Add jitter (30s–2min) between
         requests for safety. Persist as channel=LINKEDIN_INVITE.
  3. Both branches write OutreachMessage rows to LocalDB and the Sheets
     "Outreach" tab so the user can audit DMs sent and connections sent.

Honours `daily_remaining` so the daily outreach budget covers email +
LinkedIn DMs + LinkedIn invites combined.

Safety: jitter between connection requests to avoid bot-pattern detection.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from src.models import (
    OutreachChannel,
    OutreachMessage,
    OutreachStatus,
    OutreachStyle,
    Recruiter,
    ScoredJob,
)
from src.outreach.approval_engine import ApprovalEngine
from src.outreach.linkedin_outreach import BaseLinkedInOutreach, LinkedInActionResult
from src.outreach.referral_template import LinkedInDMTemplate, LinkedInInviteTemplate
from src.tracker.google_sheets import GoogleSheets
from src.tracker.local_db import LocalDB
from src.utils.logger import logger


class LinkedInOutreachOrchestrator:
    """Drives the LinkedIn DM / connection-request flow for one job."""

    def __init__(
        self,
        backend: BaseLinkedInOutreach,
        approval: ApprovalEngine,
        db: LocalDB,
        sheets: Optional[GoogleSheets] = None,
        *,
        max_people_per_company: int = 3,
        cooldown_days: int = 90,
        current_company: str = "Lucid Motors (LTM)",
        sender_name: str = "Sameet Sabu",
        dm_template: Optional[LinkedInDMTemplate] = None,
        invite_template: Optional[LinkedInInviteTemplate] = None,
        jitter_min_seconds: int = 30,
        jitter_max_seconds: int = 120,
    ) -> None:
        self.backend = backend
        self.approval = approval
        self.db = db
        self.sheets = sheets
        self.max_people = max_people_per_company
        self.cooldown_days = cooldown_days
        self.current_company = current_company
        self.sender_name = sender_name
        self.dm_template = dm_template or LinkedInDMTemplate()
        self.invite_template = invite_template or LinkedInInviteTemplate()
        self.jitter_min_seconds = jitter_min_seconds
        self.jitter_max_seconds = jitter_max_seconds

    def reach_out_for_job(
        self,
        scored: ScoredJob,
        *,
        daily_remaining: int = 999,
    ) -> list[OutreachMessage]:
        """Sync wrapper around async _reach_out_for_job_async."""
        return asyncio.run(self._reach_out_for_job_async(scored, daily_remaining))

    async def _reach_out_for_job_async(
        self,
        scored: ScoredJob,
        daily_remaining: int = 999,
    ) -> list[OutreachMessage]:
        if daily_remaining <= 0:
            logger.info("LinkedIn outreach: daily limit hit — skipping")
            return []

        job = scored.job
        people = self.backend.find_company_people(
            job.company, max_results=self.max_people
        )
        logger.info(f"LinkedIn: {len(people)} people surfaced at {job.company}")

        results: list[OutreachMessage] = []
        for idx, person in enumerate(people):
            if daily_remaining <= 0:
                break

            is_conn = self.backend.is_connection(person)

            # Cooldown is keyed off email when present, falling back to
            # linkedin_url so connection-only people still de-dupe.
            cooldown_key = person.email or person.linkedin_url
            if cooldown_key and self.db.already_contacted(
                cooldown_key, within_days=self.cooldown_days
            ):
                logger.info(f"Skipping {person.name} — contacted within cooldown")
                continue

            if not is_conn:
                # Not a 1st-degree connection — queue for manual outreach instead of
                # auto-sending a connection request.
                queued = OutreachMessage(
                    recruiter=person,
                    job=job,
                    channel=OutreachChannel.LINKEDIN_INVITE,
                    style=OutreachStyle.REFERRAL,
                    subject="",
                    body="",
                    status=OutreachStatus.MANUAL_CONNECT,
                )
                self.db.upsert_outreach(queued)
                if self.sheets is not None:
                    self.sheets.append_connect_queue(person, job)
                logger.info(
                    f"LinkedIn: queued {person.name} ({person.linkedin_url}) "
                    f"for manual connection — added to Connect Queue sheet"
                )
                results.append(queued)
                continue

            # 1st-degree connection — send DM
            draft = self._compose(person, job, is_connection=True)
            self.db.upsert_outreach(draft)

            reviewed = self.approval.review(draft)
            self.db.upsert_outreach(reviewed)

            if reviewed.status not in (OutreachStatus.APPROVED, OutreachStatus.EDITED):
                if self.sheets is not None:
                    self.sheets.append_outreach(reviewed)
                results.append(reviewed)
                continue

            send_result = self._send(reviewed, is_connection=True)
            if send_result.success:
                reviewed.status = OutreachStatus.SENT
                reviewed.message_id = send_result.detail
                reviewed.sent_at = datetime.utcnow()
                daily_remaining -= 1
            else:
                reviewed.status = OutreachStatus.FAILED
                reviewed.error = send_result.error or "linkedin_send_failed"

            self.db.upsert_outreach(reviewed)
            if self.sheets is not None:
                self.sheets.append_outreach(reviewed)
            results.append(reviewed)

        return results

    # ───── helpers ─────

    def _compose(
        self,
        person: Recruiter,
        job,
        *,
        is_connection: bool,
    ) -> OutreachMessage:
        if is_connection:
            dm = self.dm_template.render(
                person_name=person.name,
                company=job.company,
                role=job.title,
                job_link=job.apply_url,
                current_company=self.current_company,
                sender_name=self.sender_name,
            )
            return OutreachMessage(
                recruiter=person,
                job=job,
                channel=OutreachChannel.LINKEDIN_MSG,
                style=OutreachStyle.REFERRAL,
                subject=dm.subject,
                body=dm.body,
                status=OutreachStatus.DRAFTED,
            )
        invite = self.invite_template.render(
            person_name=person.name,
            company=job.company,
            role=job.title,
            current_company=self.current_company,
            sender_name=self.sender_name,
        )
        return OutreachMessage(
            recruiter=person,
            job=job,
            channel=OutreachChannel.LINKEDIN_INVITE,
            style=OutreachStyle.REFERRAL,
            subject=f"Connection Request — {job.company}",
            body=invite.note,
            status=OutreachStatus.DRAFTED,
        )

    def _send(
        self, message: OutreachMessage, *, is_connection: bool
    ) -> LinkedInActionResult:
        if is_connection:
            return self.backend.send_dm(
                message.recruiter, subject=message.subject, body=message.body
            )
        return self.backend.send_connection_request(
            message.recruiter, note=message.body
        )

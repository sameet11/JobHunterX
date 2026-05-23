"""Email sender — Gmail SMTP with App Password.

Two implementations:
- SMTPEmailSender: real send via Gmail SMTP (requires GMAIL_APP_PASSWORD)
- DryRunEmailSender: prints what would be sent (testing + dry-run mode)
"""

from __future__ import annotations

import os
import smtplib
import ssl
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from src.models import OutreachMessage, OutreachStatus
from src.utils.logger import logger


@dataclass(frozen=True)
class SendResult:
    success: bool
    message_id: str = ""
    error: str = ""


class BaseEmailSender(ABC):
    @abstractmethod
    def send(self, message: OutreachMessage, attachment: Optional[Path] = None) -> SendResult:
        """Send email; returns success + message_id."""


class DryRunEmailSender(BaseEmailSender):
    """Prints emails to stdout/log instead of sending. For tests + dry-runs."""

    def __init__(self) -> None:
        self.sent: list[OutreachMessage] = []

    def send(self, message: OutreachMessage, attachment: Optional[Path] = None) -> SendResult:
        logger.info(
            f"[DRY-RUN] Would send to {message.recruiter.email} "
            f"({message.recruiter.name}): {message.subject}"
        )
        if attachment:
            logger.info(f"[DRY-RUN]   with attachment: {attachment}")
        self.sent.append(message)
        return SendResult(success=True, message_id=f"dry-run-{uuid.uuid4().hex[:12]}")


class SMTPEmailSender(BaseEmailSender):
    """Real Gmail SMTP sender. Requires GMAIL_APP_PASSWORD in env."""

    _SMTP_HOST = "smtp.gmail.com"
    _SMTP_PORT = 465  # SSL

    def __init__(
        self,
        sender_email: str,
        sender_password: Optional[str] = None,
        sender_name: str = "Sameet Sabu",
    ) -> None:
        self.sender_email = sender_email
        self.sender_password = sender_password or os.getenv("GMAIL_APP_PASSWORD", "")
        self.sender_name = sender_name
        if not self.sender_password:
            raise RuntimeError("GMAIL_APP_PASSWORD not set in env — cannot send real emails")

    def send(self, message: OutreachMessage, attachment: Optional[Path] = None) -> SendResult:
        if not message.recruiter.email:
            return SendResult(success=False, error="Recruiter has no email")
        if message.status not in (OutreachStatus.APPROVED, OutreachStatus.EDITED):
            return SendResult(success=False, error=f"Status {message.status} not sendable")

        msg = EmailMessage()
        msg["Subject"] = message.subject
        msg["From"] = f"{self.sender_name} <{self.sender_email}>"
        msg["To"] = message.recruiter.email
        msg.set_content(message.body)

        if attachment and attachment.exists():
            with attachment.open("rb") as fp:
                msg.add_attachment(
                    fp.read(),
                    maintype="application",
                    subtype="pdf",
                    filename=attachment.name,
                )

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(self._SMTP_HOST, self._SMTP_PORT, context=ctx) as server:
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            message_id = msg.get("Message-ID", "") or f"smtp-{datetime.utcnow().isoformat()}"
            logger.info(f"Sent email to {message.recruiter.email}: {message.subject}")
            return SendResult(success=True, message_id=message_id)
        except Exception as exc:
            logger.exception(f"SMTP send failed: {exc}")
            return SendResult(success=False, error=str(exc))


def get_email_sender(mode: str = "dry_run", **kwargs) -> BaseEmailSender:
    """Factory: 'dry_run' or 'smtp'."""
    key = mode.lower()
    if key == "dry_run":
        return DryRunEmailSender()
    if key == "smtp":
        sender_email = kwargs.get("sender_email") or os.getenv("GMAIL_SENDER_EMAIL", "")
        if not sender_email:
            raise RuntimeError("sender_email required for SMTP mode")
        return SMTPEmailSender(sender_email=sender_email, **{k: v for k, v in kwargs.items() if k != "sender_email"})
    raise ValueError(f"Unknown email sender mode: {mode}")

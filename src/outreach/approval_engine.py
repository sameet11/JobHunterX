"""Approval engine — shows draft email to user, gets approve/edit/reject decision.

Modes:
- interactive: prompts user via stdin (default)
- auto_approve: auto-marks all drafts as APPROVED (for non-interactive runs)
- auto_reject: auto-marks all drafts as REJECTED (dry-run testing)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from src.models import OutreachMessage, OutreachStatus
from src.utils.logger import logger


class ApprovalMode(str, Enum):
    INTERACTIVE = "interactive"
    AUTO_APPROVE = "auto_approve"
    AUTO_REJECT = "auto_reject"


class ApprovalEngine:
    """CLI approval workflow with optional auto modes for non-interactive use."""

    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.INTERACTIVE,
        prompt_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.mode = mode
        # Override-able for tests (default uses input())
        self._prompt = prompt_fn or input

    def review(self, message: OutreachMessage) -> OutreachMessage:
        """Returns the message with status updated based on user decision."""
        if self.mode == ApprovalMode.AUTO_APPROVE:
            logger.info(f"[auto-approve] {message.recruiter.name} @ {message.recruiter.company}")
            message.status = OutreachStatus.APPROVED
            return message
        if self.mode == ApprovalMode.AUTO_REJECT:
            logger.info(f"[auto-reject] {message.recruiter.name} @ {message.recruiter.company}")
            message.status = OutreachStatus.REJECTED
            return message

        return self._interactive_review(message)

    def _interactive_review(self, message: OutreachMessage) -> OutreachMessage:
        self._render(message)
        while True:
            choice = self._prompt("\n[A]pprove / [E]dit / [R]eject / [S]kip > ").strip().lower()
            if choice in ("a", "approve"):
                message.status = OutreachStatus.APPROVED
                logger.info(f"Approved: {message.recruiter.email}")
                return message
            if choice in ("r", "reject"):
                message.status = OutreachStatus.REJECTED
                logger.info(f"Rejected: {message.recruiter.email}")
                return message
            if choice in ("s", "skip"):
                message.status = OutreachStatus.REJECTED  # treat skip as reject
                logger.info(f"Skipped: {message.recruiter.email}")
                return message
            if choice in ("e", "edit"):
                edited = self._edit(message)
                if edited:
                    message.subject = edited["subject"]
                    message.body = edited["body"]
                    message.status = OutreachStatus.EDITED
                    logger.info(f"Edited: {message.recruiter.email}")
                    self._render(message)
                    # After editing, ask again if user wants to approve
                    continue
                else:
                    print("Edit cancelled.")
                    continue
            print("Invalid choice. Use A / E / R / S.")

    @staticmethod
    def _render(message: OutreachMessage) -> None:
        print()
        print("=" * 70)
        print(f"To:      {message.recruiter.name} <{message.recruiter.email}>")
        print(f"Title:   {message.recruiter.title}")
        print(f"Company: {message.recruiter.company}")
        print(f"Job:     {message.job.title}")
        print(f"Channel: {message.channel.value} | Style: {message.style.value}")
        print("-" * 70)
        print(f"Subject: {message.subject}")
        print()
        print(message.body)
        print("=" * 70)

    @staticmethod
    def _edit(message: OutreachMessage) -> Optional[dict]:
        """Open the user's $EDITOR (or notepad on Windows) for inline editing."""
        editor = os.environ.get("EDITOR") or ("notepad" if sys.platform == "win32" else "vi")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(f"SUBJECT: {message.subject}\n\n{message.body}\n")
            tmp_path = Path(tmp.name)
        try:
            subprocess.run([editor, str(tmp_path)], check=True)
            content = tmp_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Editor failed: {exc}")
            return None
        finally:
            tmp_path.unlink(missing_ok=True)

        # Parse: first line "SUBJECT: ..." then blank line then body
        lines = content.split("\n", 2)
        if len(lines) < 3 or not lines[0].startswith("SUBJECT:"):
            logger.warning("Edited content malformed; expected 'SUBJECT: ...' on first line")
            return None
        subject = lines[0][len("SUBJECT:"):].strip()
        body = lines[2].rstrip()
        return {"subject": subject, "body": body}

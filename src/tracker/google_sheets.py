"""Google Sheets tracker — appends and updates rows on the Applications tab."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config.platform_config import platform
from src.models import JDAnalysis, Job, OutreachMessage, Recruiter
from src.tracker.schema import CONNECT_QUEUE_COLUMNS, OUTREACH_COLUMNS, SHEET_COLUMNS, Status
from src.utils.logger import logger

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_TOKEN_PATH = Path(__file__).resolve().parents[2] / "data" / "google_sheets_token.json"

_APPLICATIONS_TAB = "Applications"
_OUTREACH_TAB = "Outreach"
_CONNECT_QUEUE_TAB = "Connect Queue"


class GoogleSheets:
    def __init__(self, sheet_id: str | None = None) -> None:
        self.sheet_id = sheet_id or platform.google_sheet_id
        self._sheet = None
        self._tab = None
        self._outreach_tab = None
        self._connect_queue_tab = None

    def init(self) -> None:
        if not self.sheet_id:
            raise RuntimeError("GOOGLE_SHEET_ID not set in .env")
        creds = self._get_or_create_credentials()
        client = gspread.authorize(creds)
        self._sheet = client.open_by_key(self.sheet_id)
        self._tab = self._ensure_tab(_APPLICATIONS_TAB, SHEET_COLUMNS)
        self._outreach_tab = self._ensure_tab(_OUTREACH_TAB, OUTREACH_COLUMNS)
        self._connect_queue_tab = self._ensure_tab(_CONNECT_QUEUE_TAB, CONNECT_QUEUE_COLUMNS)
        logger.info(
            f"Google Sheets ready: {self._sheet.title} / "
            f"{_APPLICATIONS_TAB}, {_OUTREACH_TAB}, {_CONNECT_QUEUE_TAB}"
        )

    def _get_or_create_credentials(self) -> Credentials:
        """Load cached token or run OAuth flow from credentials.json (first time only)."""
        if _TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), scopes=_SCOPES)
                if creds.valid:
                    return creds
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
                    return creds
            except Exception as exc:
                logger.warning(f"Cached token invalid ({exc}) — re-running OAuth flow")
                _TOKEN_PATH.unlink(missing_ok=True)

        logger.info("First-time setup: opening browser for Google authorization...")
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            scopes=_SCOPES,
        )
        creds = flow.run_local_server(port=0)

        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        logger.info(f"Token saved to {_TOKEN_PATH}")
        return creds

    def _ensure_tab(self, name: str, header: list[str]):
        try:
            ws = self._sheet.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = self._sheet.add_worksheet(title=name, rows=1000, cols=len(header))
            ws.append_row(header)
            return ws
        existing = ws.row_values(1)
        if existing != header:
            ws.update("A1", [header])
        return ws

    def append_scraped(self, job: Job, score: int) -> None:
        row = self._row_for(job, score, status=Status.SCRAPED)
        self._tab.append_row(row, value_input_option="USER_ENTERED")

    def append_application(
        self,
        job: Job,
        analysis: JDAnalysis | None,
        status: str,
        notes: str = "",
        resume_path: str = "",
    ) -> None:
        row = self._row_for(
            job,
            analysis.match_score if analysis else 0,
            status=status,
            missing=", ".join(analysis.missing_skills) if analysis else "",
            notes=notes,
            resume_path=resume_path,
        )
        self._tab.append_row(row, value_input_option="USER_ENTERED")

    def _row_for(
        self,
        job: Job,
        score: int,
        status: str,
        missing: str = "",
        notes: str = "",
        resume_path: str = "",
    ) -> list[Any]:
        return [
            datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            job.company,
            job.title,
            job.salary or "",
            job.location or "",
            job.source,
            job.apply_url,
            status,
            score,
            missing,
            resume_path,
            "", "", "", "", "", "", "", "",
            notes,
        ]

    def append_connect_queue(
        self, person: Recruiter, job: Job, connection_note: str = ""
    ) -> None:
        """Append a person to the Connect Queue tab for manual LinkedIn connection."""
        if self._connect_queue_tab is None:
            logger.warning("Connect Queue tab not initialized — skipping sheet write")
            return
        row = [
            datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            person.name,
            person.linkedin_url,
            person.company,
            job.title,
            job.apply_url,
            connection_note,
        ]
        self._connect_queue_tab.append_row(row, value_input_option="USER_ENTERED")

    def append_outreach(self, message: OutreachMessage) -> None:
        """Append outreach record to the Outreach tab."""
        if self._outreach_tab is None:
            logger.warning("Outreach tab not initialized — skipping sheet write")
            return
        sent_at = (
            message.sent_at.strftime("%Y-%m-%d %H:%M") if message.sent_at else ""
        )
        approved = "Yes" if message.status.value in ("approved", "edited", "sent") else "No"
        body_preview = (message.body or "")[:200].replace("\n", " ")
        row = [
            datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            message.recruiter.name,
            message.recruiter.title,
            message.recruiter.company,
            message.recruiter.email,
            message.recruiter.linkedin_url,
            message.recruiter.source,
            message.channel.value,
            message.style.value,
            message.job.title,
            message.subject,
            body_preview,
            message.status.value,
            approved,
            sent_at,
            message.error,
        ]
        self._outreach_tab.append_row(row, value_input_option="USER_ENTERED")

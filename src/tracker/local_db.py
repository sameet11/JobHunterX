"""SQLite-backed local store for dedup + offline backup of every scraped job."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from src.models import Job, OutreachMessage, OutreachStatus
from src.tracker.schema import Status

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "applied.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    dedup_key TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    salary TEXT,
    apply_url TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'Scraped',
    match_score INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_company_title ON jobs(company, title);
CREATE INDEX IF NOT EXISTS idx_status ON jobs(status);

CREATE TABLE IF NOT EXISTS outreach (
    dedup_key TEXT PRIMARY KEY,
    job_dedup_key TEXT NOT NULL,
    recruiter_name TEXT NOT NULL,
    recruiter_email TEXT,
    recruiter_title TEXT,
    recruiter_company TEXT NOT NULL,
    channel TEXT NOT NULL,
    style TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    status TEXT NOT NULL,
    message_id TEXT,
    error TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL,
    last_updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outreach_company ON outreach(recruiter_company);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);
CREATE INDEX IF NOT EXISTS idx_outreach_job ON outreach(job_dedup_key);

"""


class LocalDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "LocalDB":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def already_seen(self, job: Job) -> bool:
        """True if we've already acted on this job (applied, skipped, etc.).

        Jobs with status=SCRAPED return False so they can be retried on
        subsequent runs (e.g., if we hit daily_limit before reaching them).
        """
        cur = self._conn.execute(
            "SELECT 1 FROM jobs WHERE dedup_key = ? AND status != ?",
            (job.dedup_key(), Status.SCRAPED),
        )
        return cur.fetchone() is not None

    def applied_recently(self, company: str, title: str, within_days: int) -> bool:
        cutoff = (datetime.utcnow() - timedelta(days=within_days)).isoformat()
        cur = self._conn.execute(
            """
            SELECT 1 FROM jobs
            WHERE company = ? AND title = ?
              AND status IN (?, ?, ?)
              AND last_updated >= ?
            LIMIT 1
            """,
            (company, title, Status.APPLIED, Status.RECRUITER_FOUND, Status.RESPONDED, cutoff),
        )
        return cur.fetchone() is not None

    def upsert_jobs(self, jobs: Iterable[Job], match_scores: dict[str, int] | None = None) -> int:
        scores = match_scores or {}
        now = datetime.utcnow().isoformat()
        added = 0
        for job in jobs:
            cur = self._conn.execute(
                """
                INSERT INTO jobs (
                    dedup_key, job_id, source, company, title, location,
                    salary, apply_url, description, status, match_score,
                    first_seen, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedup_key) DO UPDATE SET
                    last_updated = excluded.last_updated,
                    match_score = excluded.match_score
                """,
                (
                    job.dedup_key(),
                    job.id,
                    job.source,
                    job.company,
                    job.title,
                    job.location,
                    job.salary,
                    job.apply_url,
                    job.description,
                    Status.SCRAPED,
                    int(scores.get(job.dedup_key(), 0)),
                    now,
                    now,
                ),
            )
            if cur.rowcount == 1:
                added += 1
        self._conn.commit()
        return added

    def update_status(self, dedup_key: str, status: str, match_score: int | None = None) -> None:
        if match_score is None:
            self._conn.execute(
                "UPDATE jobs SET status = ?, last_updated = ? WHERE dedup_key = ?",
                (status, datetime.utcnow().isoformat(), dedup_key),
            )
        else:
            self._conn.execute(
                "UPDATE jobs SET status = ?, match_score = ?, last_updated = ? WHERE dedup_key = ?",
                (status, int(match_score), datetime.utcnow().isoformat(), dedup_key),
            )
        self._conn.commit()

    def daily_applied_count(self) -> int:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = ? AND last_updated >= ?",
            (Status.APPLIED, today_start),
        )
        return int(cur.fetchone()[0])

    # ───── Outreach (Phase 3) ─────

    def upsert_outreach(self, message: OutreachMessage) -> bool:
        """Insert or update an outreach record. Returns True if new row."""
        now = datetime.utcnow().isoformat()
        sent_at = message.sent_at.isoformat() if message.sent_at else None
        cur = self._conn.execute(
            """
            INSERT INTO outreach (
                dedup_key, job_dedup_key, recruiter_name, recruiter_email,
                recruiter_title, recruiter_company, channel, style, subject, body,
                status, message_id, error, sent_at, created_at, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedup_key) DO UPDATE SET
                status = excluded.status,
                subject = excluded.subject,
                body = excluded.body,
                message_id = excluded.message_id,
                error = excluded.error,
                sent_at = excluded.sent_at,
                last_updated = excluded.last_updated
            """,
            (
                message.dedup_key(),
                message.job.dedup_key(),
                message.recruiter.name,
                message.recruiter.email,
                message.recruiter.title,
                message.recruiter.company,
                message.channel.value,
                message.style.value,
                message.subject,
                message.body,
                message.status.value,
                message.message_id,
                message.error,
                sent_at,
                now,
                now,
            ),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def already_contacted(self, recruiter_email: str, within_days: int = 90) -> bool:
        """Skip recruiters we already contacted recently."""
        if not recruiter_email:
            return False
        cutoff = (datetime.utcnow() - timedelta(days=within_days)).isoformat()
        cur = self._conn.execute(
            """
            SELECT 1 FROM outreach
            WHERE recruiter_email = ?
              AND status IN (?, ?, ?)
              AND last_updated >= ?
            LIMIT 1
            """,
            (
                recruiter_email,
                OutreachStatus.SENT.value,
                OutreachStatus.APPROVED.value,
                OutreachStatus.MANUAL_CONNECT.value,
                cutoff,
            ),
        )
        return cur.fetchone() is not None

    def outreach_count_today(self) -> int:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE status = ? AND last_updated >= ?",
            (OutreachStatus.SENT.value, today_start),
        )
        return int(cur.fetchone()[0])


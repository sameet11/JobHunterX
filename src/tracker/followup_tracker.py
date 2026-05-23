"""Follow-up cadence tracker (career-ops inspired).

Classifies jobs in Applied / Responded / Interview state into URGENT,
OVERDUE, WAITING, COLD buckets so the user knows where to nudge.

Cadence rules (in days since last status change):
  Applied      → 7d  cadence (nudge if 7-14d, urgent 14d+, cold 30d+)
  Responded    → 3d  cadence (nudge if 3-7d,  urgent 7d+,  cold 21d+)
  Interview    → 1d  cadence (nudge if 1-3d,  urgent 3d+,  cold 14d+)

No DB schema change required — uses jobs.last_updated as the timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterable

from src.tracker.local_db import LocalDB
from src.tracker.schema import Status
from src.utils.logger import logger

_REPORT_PATH = Path(__file__).resolve().parents[2] / "data" / "follow_ups.md"


class FollowUpTier(str, Enum):
    URGENT = "URGENT"
    OVERDUE = "OVERDUE"
    WAITING = "WAITING"
    COLD = "COLD"


# Per-status cadence: (overdue_days, urgent_days, cold_days)
_CADENCE: dict[str, tuple[int, int, int]] = {
    Status.APPLIED: (7, 14, 30),
    Status.RESPONDED: (3, 7, 21),
    Status.INTERVIEW: (1, 3, 14),
}


@dataclass
class FollowUp:
    dedup_key: str
    company: str
    title: str
    status: str
    apply_url: str
    days_since: int
    tier: FollowUpTier


def _classify(status: str, days: int) -> FollowUpTier:
    overdue, urgent, cold = _CADENCE[status]
    if days >= cold:
        return FollowUpTier.COLD
    if days >= urgent:
        return FollowUpTier.URGENT
    if days >= overdue:
        return FollowUpTier.OVERDUE
    return FollowUpTier.WAITING


def scan(db: LocalDB) -> list[FollowUp]:
    """Walk the DB and classify every Applied/Responded/Interview row."""
    now = datetime.utcnow()
    statuses = list(_CADENCE.keys())
    placeholders = ",".join(["?"] * len(statuses))
    cur = db._conn.execute(
        f"""
        SELECT dedup_key, company, title, status, apply_url, last_updated
        FROM jobs
        WHERE status IN ({placeholders})
        ORDER BY last_updated ASC
        """,
        statuses,
    )
    out: list[FollowUp] = []
    for row in cur.fetchall():
        try:
            last = datetime.fromisoformat(row["last_updated"])
        except (ValueError, TypeError):
            continue
        days = max((now - last).days, 0)
        tier = _classify(row["status"], days)
        out.append(
            FollowUp(
                dedup_key=row["dedup_key"],
                company=row["company"],
                title=row["title"],
                status=row["status"],
                apply_url=row["apply_url"] or "",
                days_since=days,
                tier=tier,
            )
        )
    return out


def write_report(items: Iterable[FollowUp], path: Path = _REPORT_PATH) -> Path:
    """Write a markdown follow-up report grouped by tier."""
    items = list(items)
    grouped: dict[FollowUpTier, list[FollowUp]] = {t: [] for t in FollowUpTier}
    for it in items:
        grouped[it.tier].append(it)

    lines: list[str] = []
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"# Follow-ups — {today}")
    lines.append("")
    summary = "  ".join(
        f"**{tier.value}**: {len(grouped[tier])}"
        for tier in (FollowUpTier.URGENT, FollowUpTier.OVERDUE, FollowUpTier.WAITING, FollowUpTier.COLD)
    )
    lines.append(summary)
    lines.append("")

    order = [FollowUpTier.URGENT, FollowUpTier.OVERDUE, FollowUpTier.WAITING, FollowUpTier.COLD]
    for tier in order:
        bucket = grouped[tier]
        if not bucket:
            continue
        lines.append(f"## {tier.value} ({len(bucket)})")
        lines.append("")
        if tier is FollowUpTier.COLD:
            lines.append("> These applications have been silent for a long time. "
                         "Consider closing them out or sending a final note.")
            lines.append("")
        bucket.sort(key=lambda x: -x.days_since)
        for fu in bucket:
            lines.append(
                f"- **{fu.company}** — {fu.title} "
                f"(`{fu.dedup_key}`, status: {fu.status}, {fu.days_since}d ago)"
            )
            if fu.apply_url:
                lines.append(f"  - {fu.apply_url}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    counts = {t.value: len(grouped[t]) for t in order}
    logger.info(f"Follow-up report written: {path} ({counts})")
    return path


def report_path() -> Path:
    return _REPORT_PATH

"""LinkedIn recruiter finder — discovers who to message, you send manually.

Takes the same position numbers used by mark_applied.py / generate_resume.py.
For each applied job, finds recruiters at the company via LinkedIn (using your
browser session cookies — no bot challenges) and writes them to a markdown
file with pre-drafted referral notes you can copy-paste.

Nothing is sent automatically. You stay in control.

Human-pacing:
  * Random 30–120s delay between companies (configurable in user_config.py)

Usage:
    python scripts/outreach.py 1 3 5          # positions from review_queue.md
    python scripts/outreach.py adzuna:abc123  # raw dedup_key also works

Requires you to be logged into linkedin.com in Chrome/Edge/Firefox — the
script auto-reads your session cookie from the browser.

Output: data/linkedin_targets.md
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config.user_config import config as user_config       # noqa: E402
from src.models import Job                                 # noqa: E402
from src.outreach.browser_finder import find_linkedin_recruiters  # noqa: E402
from src.tracker.google_sheets import GoogleSheets         # noqa: E402
from src.tracker.local_db import LocalDB                   # noqa: E402
from src.tracker.schema import Status                      # noqa: E402
from src.utils.logger import logger                        # noqa: E402

_QUEUE_PATH = _REPO_ROOT / "data" / "review_queue.md"
_TARGETS_PATH = _REPO_ROOT / "data" / "linkedin_targets.md"
_HEADING_RE = re.compile(r"^## #(\d+)\s+—")
_DEDUP_RE = re.compile(r"\*\*dedup_key:\*\*\s+`([^`]+)`")


def _load_queue() -> dict[int, str]:
    if not _QUEUE_PATH.exists():
        return {}
    text = _QUEUE_PATH.read_text(encoding="utf-8")
    mapping: dict[int, str] = {}
    current_rank: int | None = None
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            current_rank = int(m.group(1))
            continue
        if current_rank is not None:
            d = _DEDUP_RE.search(line)
            if d:
                mapping[current_rank] = d.group(1)
                current_rank = None
    return mapping


def _resolve(arg: str, queue: dict[int, str]) -> str | None:
    if arg.isdigit():
        pos = int(arg)
        key = queue.get(pos)
        if key is None:
            print(
                f"  ERROR: position {pos} not found in review_queue.md "
                f"(valid range: 1–{max(queue) if queue else 0})",
                file=sys.stderr,
            )
        return key
    return arg


def _load_jobs(db: LocalDB, keys: list[str]) -> list[Job]:
    jobs: list[Job] = []
    for key in keys:
        row = db._conn.execute(
            """
            SELECT job_id, source, company, title, location, salary,
                   apply_url, description, status
            FROM jobs WHERE dedup_key = ?
            """,
            (key,),
        ).fetchone()
        if not row:
            print(f"  ERROR: dedup_key not found: {key}", file=sys.stderr)
            continue
        if row["status"] != Status.APPLIED:
            print(
                f"  WARN: {row['company']} — {row['title']} status={row['status']} "
                f"(usually you'd mark_applied first)",
                file=sys.stderr,
            )
        jobs.append(Job(
            id=row["job_id"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            salary=row["salary"],
            apply_url=row["apply_url"] or "",
            description=row["description"] or "",
            source=row["source"],
        ))
    return jobs


def _connection_note(person_name: str, company: str, role: str) -> str:
    """Short (≤300 char) LinkedIn connection-request note."""
    first = person_name.split()[0] if person_name else "there"
    sender = user_config.applicant.full_name.split()[0]
    current = user_config.applicant.current_company
    note = (
        f"Hi {first}, I applied for the {role} role at {company} and would "
        f"love to connect. I'm {sender}, currently at {current} with "
        f"{user_config.experience_years}+ yrs in backend/GenAI. Any insights would mean a lot."
    )
    return note[:300]


def _dm_message(person_name: str, company: str, role: str, job_link: str) -> str:
    """Longer DM body for 1st-degree connections."""
    first = person_name.split()[0] if person_name else "there"
    sender = user_config.applicant.full_name
    current = user_config.applicant.current_company
    return (
        f"Hi {first},\n\n"
        f"Hope you're doing well! I recently applied for the {role} role at "
        f"{company} and wanted to reach out directly.\n\n"
        f"Quick context: I'm {sender}, currently at {current} with "
        f"{user_config.experience_years}+ years building backend systems and "
        f"GenAI platforms (Python, Java, AWS/GCP, LangChain/RAG).\n\n"
        f"If the role's still open, would you be open to a quick referral or "
        f"pointing me to the right person on the team?\n\n"
        f"Job link: {job_link}\n\n"
        f"Thanks for considering,\n{sender}"
    )


def _write_targets(rows: list[tuple[Job, list]]) -> Path:
    """Write a markdown report of found recruiters per job."""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        f"# LinkedIn Outreach Targets — {today}",
        "",
        "Open each profile manually, send the connection request (with the "
        "suggested note) or DM if you're already connected.",
        "",
        "---",
        "",
    ]
    total_people = 0
    for job, people in rows:
        lines.append(f"## {job.company} — {job.title}")
        if job.apply_url:
            lines.append(f"**Job:** {job.apply_url}")
        lines.append("")
        if not people:
            lines.append("_No recruiters found._")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue
        for p in people:
            total_people += 1
            lines.append(f"### {p.name} — {p.title or '(title unknown)'}")
            lines.append(f"- **Profile:** {p.linkedin_url}")
            lines.append("- **Connection-request note (≤300 chars):**")
            lines.append("  > " + _connection_note(p.name, job.company, job.title))
            lines.append("- **DM (if already connected):**")
            dm_body = _dm_message(p.name, job.company, job.title, job.apply_url)
            for ln in dm_body.splitlines():
                lines.append(f"  > {ln}" if ln else "  >")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.insert(4, f"**Summary:** {total_people} recruiter(s) across {len(rows)} job(s).")
    lines.insert(5, "")
    _TARGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TARGETS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return _TARGETS_PATH


def _append_to_sheets(rows: list[tuple[Job, list]]) -> None:
    """Append each recruiter to the Google Sheets Connect Queue tab."""
    try:
        gs = GoogleSheets()
        gs.init()
    except Exception as exc:
        logger.opt(exception=exc).warning(
            f"Google Sheets not available — skipping tracker update "
            f"[{type(exc).__name__}: {exc!r}]"
        )
        return

    added = 0
    for job, people in rows:
        for person in people:
            note = _connection_note(person.name, job.company, job.title)
            try:
                gs.append_connect_queue(person, job, connection_note=note)
                added += 1
            except Exception as exc:
                logger.warning(f"Failed to write {person.name} to sheet: {exc}")

    if added:
        logger.info(f"Google Sheets updated: +{added} row(s) in 'Connect Queue'")
        print(f"  Google Sheets updated: +{added} row(s) in 'Connect Queue'")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find LinkedIn recruiters for applied jobs (no auto-send — manual outreach)."
    )
    parser.add_argument(
        "jobs",
        nargs="+",
        metavar="JOB",
        help="Position numbers from review_queue.md (e.g. 1 3 5) or raw dedup_keys",
    )
    args = parser.parse_args()

    queue = _load_queue()
    if not queue and any(a.isdigit() for a in args.jobs):
        print(
            "ERROR: data/review_queue.md not found — run `python main.py` first.",
            file=sys.stderr,
        )
        return 2

    keys = [_resolve(a, queue) for a in args.jobs]
    keys = [k for k in keys if k is not None]
    if not keys:
        return 2

    with LocalDB() as db:
        jobs = _load_jobs(db, keys)
        if not jobs:
            return 2

    logger.info(
        f"Finding recruiters for {len(jobs)} job(s) — opens a real browser, "
        f"pacing {user_config.linkedin_jitter_min_seconds}-{user_config.linkedin_jitter_max_seconds}s between companies"
    )

    found = find_linkedin_recruiters(
        jobs,
        max_per_company=user_config.max_linkedin_people_per_company,
        min_delay_seconds=user_config.linkedin_jitter_min_seconds,
        max_delay_seconds=user_config.linkedin_jitter_max_seconds,
    )
    rows: list[tuple[Job, list]] = [(job, found.get(job.dedup_key(), [])) for job in jobs]

    out_path = _write_targets(rows)
    total = sum(len(p) for _, p in rows)
    logger.info(f"Wrote {total} recruiter(s) -> {out_path}")

    _append_to_sheets(rows)

    print()
    print(f"  Open {out_path} to send connections/DMs manually.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

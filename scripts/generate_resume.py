"""Generate ATS-friendly tailored resume PDFs for selected jobs in the review queue.

Reads positions from data/review_queue.md (same numbering as mark_applied.py),
loads each job's JD from SQLite, extracts matching keywords against your
user_config.skills, then renders a tailored PDF via ResumeTailor.

Usage:
    python scripts/generate_resume.py 1 3 5           # tailor resumes for positions 1, 3, 5
    python scripts/generate_resume.py adzuna:abc123   # raw dedup_key still works

PDFs land in output/<Company>_<Role>.pdf. Apply manually with the tailored file,
then run scripts/mark_applied.py to record the application.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config.user_config import config as user_config  # noqa: E402
from src.analyzer.match_scorer import MatchScorer     # noqa: E402
from src.models import JDAnalysis, Job                # noqa: E402
from src.resume.resume_tailor import ResumeTailor     # noqa: E402
from src.tracker.local_db import LocalDB              # noqa: E402

_QUEUE_PATH = _REPO_ROOT / "data" / "review_queue.md"
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


def _load_job(db: LocalDB, dedup_key: str) -> Job | None:
    row = db._conn.execute(
        """
        SELECT job_id, source, company, title, location, salary,
               apply_url, description
        FROM jobs
        WHERE dedup_key = ?
        """,
        (dedup_key,),
    ).fetchone()
    if not row:
        return None
    return Job(
        id=row["job_id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        salary=row["salary"],
        apply_url=row["apply_url"] or "",
        description=row["description"] or "",
        source=row["source"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate ATS-friendly tailored resume PDFs for selected review-queue jobs."
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
            "ERROR: data/review_queue.md not found or empty — run `python main.py` first.",
            file=sys.stderr,
        )
        return 2

    keys = [_resolve(a, queue) for a in args.jobs]
    keys = [k for k in keys if k is not None]
    if not keys:
        return 2

    scorer = MatchScorer(user_config.skills)
    tailor = ResumeTailor()

    with LocalDB() as db:
        for key in keys:
            job = _load_job(db, key)
            if job is None:
                print(f"  ERROR: dedup_key not found in DB: {key}", file=sys.stderr)
                continue

            matched = scorer.matched_skills(job)
            analysis = JDAnalysis(
                match_score=scorer.score(job),
                keywords_to_include=matched,
            )

            try:
                out_path = tailor.generate(
                    job.company,
                    job.title,
                    analysis,
                    static_fallback=user_config.resume_path,
                )
            except Exception as exc:
                print(f"  ERROR: tailoring failed for {key}: {exc}", file=sys.stderr)
                continue

            print(
                f"  Tailored: {job.company} — {job.title} "
                f"({len(matched)} JD keywords) -> {out_path}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())

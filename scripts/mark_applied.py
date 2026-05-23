"""Record manual applications against the SQLite job tracker.

Accepts position numbers from data/review_queue.md OR raw dedup_keys.
Marking writes data/follow_ups.md. Outreach is a separate step — run
`python scripts/outreach.py <positions>` afterwards.

Usage:
    python scripts/mark_applied.py 1 3 5          # mark positions 1, 3, 5 as Applied
    python scripts/mark_applied.py 1 2 --skip      # mark positions as Skipped
    python scripts/mark_applied.py adzuna:abc123   # raw dedup_key still works
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.tracker.local_db import LocalDB           # noqa: E402
from src.tracker.schema import Status              # noqa: E402

_QUEUE_PATH = _REPO_ROOT / "data" / "review_queue.md"

# Matches:  ## #3 — Company — Title (85% match) ✓
_HEADING_RE = re.compile(r"^## #(\d+)\s+—")
# Matches:  - **dedup_key:** `adzuna:12345678`
_DEDUP_RE = re.compile(r"\*\*dedup_key:\*\*\s+`([^`]+)`")


def _load_queue() -> dict[int, str]:
    """Return {position: dedup_key} from the current review_queue.md."""
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
    """Return dedup_key for a position number or a raw dedup_key."""
    if arg.isdigit():
        pos = int(arg)
        key = queue.get(pos)
        if key is None:
            print(f"  ERROR: position {pos} not found in review_queue.md "
                  f"(valid range: 1–{max(queue) if queue else 0})", file=sys.stderr)
        return key
    return arg  # already a dedup_key


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mark jobs as Applied or Skipped by position number or dedup_key."
    )
    parser.add_argument(
        "jobs",
        nargs="+",
        metavar="JOB",
        help="Position numbers from review_queue.md (e.g. 1 3 5) or raw dedup_keys",
    )
    parser.add_argument("--skip", action="store_true", help="Mark as Skipped instead of Applied")
    args = parser.parse_args()

    status = Status.SKIPPED if args.skip else Status.APPLIED
    action = "Skipped" if args.skip else "Applied"

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

    marked_keys: list[str] = []
    with LocalDB() as db:
        for key in keys:
            cur = db._conn.execute(
                "SELECT company, title, status FROM jobs WHERE dedup_key = ?", (key,)
            )
            row = cur.fetchone()
            if not row:
                print(f"  ERROR: dedup_key not found in DB: {key}", file=sys.stderr)
                continue
            prev = row["status"]
            db.update_status(key, status)
            print(f"  {action}: {row['company']} — {row['title']} ({key}) [was: {prev}]")
            if status == Status.APPLIED:
                marked_keys.append(key)

        if marked_keys:
            _write_followups(db)
            print()
            print(f"  Next: python scripts/outreach.py {' '.join(str(a) for a in args.jobs if a.isdigit())}")

    return 0


def _write_followups(db: LocalDB) -> None:
    """Regenerate data/follow_ups.md so it reflects the just-marked jobs."""
    from src.tracker.followup_tracker import scan, write_report  # noqa: PLC0415

    items = scan(db)
    if items:
        write_report(items)


if __name__ == "__main__":
    sys.exit(main())

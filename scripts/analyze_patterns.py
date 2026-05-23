"""Conversion-funnel and pattern analysis over the local SQLite job DB.

Surfaces signals the user actually needs to make decisions:
  - Funnel: Scraped → Applied → Responded → Interview → Offer
  - Source ROI: which sources convert best (Applied/Scraped)
  - Score-threshold analysis: median score per outcome bucket
  - Top companies by stage
  - Recommendations

Usage:
    python scripts/analyze_patterns.py
    python scripts/analyze_patterns.py --json   # JSON output for scripting
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.tracker.local_db import LocalDB  # noqa: E402
from src.tracker.schema import Status  # noqa: E402

# Pipeline stages in increasing order of "interest".
_FUNNEL: list[str] = [
    Status.SCRAPED,
    Status.APPLIED,
    Status.RECRUITER_FOUND,
    Status.RESPONDED,
    Status.INTERVIEW,
    Status.OFFER,
]
# Statuses that count as "downstream" (everything after Applied).
_DOWNSTREAM = {Status.RESPONDED, Status.INTERVIEW, Status.OFFER}


def _collect(db: LocalDB) -> list[dict]:
    cur = db._conn.execute(
        "SELECT source, company, title, status, match_score FROM jobs"
    )
    return [dict(row) for row in cur.fetchall()]


def _funnel(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {s: 0 for s in _FUNNEL}
    counts["Skipped"] = 0
    counts["Rejected"] = 0
    counts["Ghosted"] = 0
    for r in rows:
        s = r["status"]
        if s in counts:
            counts[s] += 1
    return counts


def _source_roi(rows: list[dict]) -> dict[str, dict[str, int]]:
    by_source: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_source[r["source"]][r["status"]] += 1
    out: dict[str, dict[str, int]] = {}
    for src, c in by_source.items():
        applied = c[Status.APPLIED] + sum(c[s] for s in _DOWNSTREAM)
        responded = sum(c[s] for s in _DOWNSTREAM)
        out[src] = {
            "scraped": sum(c.values()),
            "applied": applied,
            "responded_or_better": responded,
        }
    return out


def _score_by_outcome(rows: list[dict]) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        score = r.get("match_score") or 0
        buckets[r["status"]].append(int(score))
    out: dict[str, dict[str, float]] = {}
    for status, scores in buckets.items():
        if not scores:
            continue
        out[status] = {
            "n": len(scores),
            "median": float(median(scores)),
            "min": float(min(scores)),
            "max": float(max(scores)),
        }
    return out


def _recommend(funnel: dict[str, int], scores: dict[str, dict[str, float]],
               sources: dict[str, dict[str, int]]) -> list[str]:
    recs: list[str] = []
    applied = funnel.get(Status.APPLIED, 0) + sum(funnel.get(s, 0) for s in _DOWNSTREAM)
    responded = sum(funnel.get(s, 0) for s in _DOWNSTREAM)
    if applied >= 10 and responded == 0:
        recs.append("0% response rate after 10+ applications — review CV positioning + outreach quality.")
    if scores.get(Status.APPLIED) and scores.get(Status.SCRAPED):
        applied_med = scores[Status.APPLIED]["median"]
        scraped_med = scores[Status.SCRAPED]["median"]
        if applied_med > scraped_med + 5:
            recs.append(
                f"Applied jobs median score ({applied_med:.0f}) is well above scraped ({scraped_med:.0f}) "
                f"— consider raising min_match_score to skip the bottom tier."
            )
    # Identify low-ROI sources (high scraped, zero applied)
    for src, stats in sources.items():
        if stats["scraped"] >= 50 and stats["applied"] == 0:
            recs.append(f"Source '{src}' produced {stats['scraped']} jobs but 0 applies — "
                        f"is it a fit for your search? Consider removing it.")
    if not recs:
        recs.append("Not enough signal yet — keep applying and re-run after ~20 applications.")
    return recs


def _render_text(funnel, sources, scores, recs) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("Pipeline Funnel")
    lines.append("=" * 60)
    for stage in _FUNNEL:
        lines.append(f"  {stage:<22} {funnel.get(stage, 0)}")
    lines.append(f"  {'Skipped':<22} {funnel.get('Skipped', 0)}")
    lines.append(f"  {'Rejected':<22} {funnel.get('Rejected', 0)}")
    lines.append("")

    lines.append("=" * 60)
    lines.append("Source ROI (scraped → applied → responded_or_better)")
    lines.append("=" * 60)
    for src in sorted(sources, key=lambda s: -sources[s]["scraped"]):
        s = sources[src]
        lines.append(f"  {src:<14} {s['scraped']:>5}  →  {s['applied']:>4}  →  {s['responded_or_better']:>3}")
    lines.append("")

    lines.append("=" * 60)
    lines.append("Match Score by Outcome (median / min / max)")
    lines.append("=" * 60)
    for status, st in scores.items():
        lines.append(f"  {status:<22} n={int(st['n']):>4}  median={st['median']:.1f}  "
                     f"min={st['min']:.0f}  max={st['max']:.0f}")
    lines.append("")

    lines.append("=" * 60)
    lines.append("Recommendations")
    lines.append("=" * 60)
    for r in recs:
        lines.append(f"  • {r}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze conversion funnel and patterns.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    with LocalDB() as db:
        rows = _collect(db)
    if not rows:
        print("DB is empty — run `python main.py` to populate jobs first.")
        return 0

    funnel = _funnel(rows)
    sources = _source_roi(rows)
    scores = _score_by_outcome(rows)
    recs = _recommend(funnel, scores, sources)

    if args.json:
        print(json.dumps(
            {"funnel": funnel, "sources": sources, "scores": scores, "recommendations": recs},
            indent=2,
        ))
    else:
        print(_render_text(funnel, sources, scores, recs))
    return 0


if __name__ == "__main__":
    sys.exit(main())

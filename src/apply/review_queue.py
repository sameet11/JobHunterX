"""Human-in-the-loop review queue.

Replaces autonomous Phase 2 on Naukri. Writes a ranked markdown table to
data/review_queue.md that the user opens, picks jobs from, and applies to
manually via the apply_url. The companion script scripts/mark_applied.py
records the user's action back to SQLite.

Design:
  - We never click submit for the user.
  - Each row shows score, legitimacy flag, company, title, location, posted-age, URL.
  - The dedup_key is the canonical handle the user passes to mark_applied.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from config.user_config import UserConfig
from src.analyzer.legitimacy_checker import (
    LegitimacyAssessment,
    LegitimacyChecker,
    LegitimacyTier,
)
from src.models import ScoredJob
from src.tracker.local_db import LocalDB
from src.utils.logger import logger

_QUEUE_PATH = Path(__file__).resolve().parents[2] / "data" / "review_queue.md"

_TIER_ICON = {
    LegitimacyTier.HIGH_CONFIDENCE: "✓",
    LegitimacyTier.CAUTION: "⚠",
    LegitimacyTier.SUSPICIOUS: "🚫",
}


def _humanize_age(posted: datetime | None) -> str:
    if posted is None:
        return "unknown"
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - posted
    days = max(int(delta.total_seconds() // 86400), 0)
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    return f"{months}mo ago"


class ReviewQueue:
    def __init__(self, user_config: UserConfig, db: LocalDB) -> None:
        self.cfg = user_config
        self.db = db
        self.checker = (
            LegitimacyChecker(user_config, db) if user_config.legitimacy_check_enabled else None
        )

    def _assess(self, scored: ScoredJob) -> LegitimacyAssessment | None:
        if self.checker is None:
            return None
        try:
            return self.checker.assess(scored.job)
        except Exception as exc:
            logger.debug(f"legitimacy check failed for {scored.job.dedup_key()}: {exc}")
            return None

    def build(self, scored: list[ScoredJob], scores: dict[str, int]) -> Path:
        """Write the ranked review queue to data/review_queue.md.

        scored: jobs that passed the filter, already sorted desc by score.
        scores: dedup_key -> match_score, for display.
        Returns the path to the generated file.
        """
        top_n = self.cfg.review_queue_top_n
        items = scored[:top_n]

        rows: list[tuple[ScoredJob, int, LegitimacyAssessment | None]] = []
        suspicious_count = 0
        caution_count = 0
        for item in items:
            assessment = self._assess(item)
            if assessment is not None:
                if assessment.tier is LegitimacyTier.SUSPICIOUS:
                    suspicious_count += 1
                elif assessment.tier is LegitimacyTier.CAUTION:
                    caution_count += 1
            rows.append((item, scores.get(item.job.dedup_key(), 0), assessment))

        # Sort: high-confidence first, then caution, suspicious at the bottom —
        # within each tier preserve original score order.
        def _tier_rank(a: LegitimacyAssessment | None) -> int:
            if a is None:
                return 0
            return {
                LegitimacyTier.HIGH_CONFIDENCE: 0,
                LegitimacyTier.CAUTION: 1,
                LegitimacyTier.SUSPICIOUS: 2,
            }[a.tier]

        rows.sort(key=lambda r: (_tier_rank(r[2]), -r[1]))

        lines: list[str] = []
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines.append(f"# Job Review Queue — {today}")
        lines.append("")
        lines.append(f"**{len(rows)} jobs surfaced** "
                     f"(top {top_n} of {len(scored)} filtered)")
        lines.append("")
        lines.append("**How to use this queue:**")
        lines.append("")
        lines.append("1. Pick the jobs you plan to apply to and generate ATS-tailored resumes:")
        lines.append("   ```")
        lines.append("   python scripts/generate_resume.py 1 3 7")
        lines.append("   ```")
        lines.append("   PDFs land in `output/<Company>_<Role>.pdf` — use them when applying.")
        lines.append("2. Open the Apply URL for each job and submit manually with the tailored PDF.")
        lines.append("3. After applying, mark the jobs as applied:")
        lines.append("   ```")
        lines.append("   python scripts/mark_applied.py 1 3 7")
        lines.append("   ```")
        lines.append("4. Any jobs you leave untouched are auto-skipped on the next pipeline run.")
        lines.append("   To dismiss explicitly:")
        lines.append("   ```")
        lines.append("   python scripts/mark_applied.py 2 5 --skip")
        lines.append("   ```")
        lines.append("")
        lines.append("**Legitimacy legend:**  "
                     "✓ high confidence  ·  ⚠ caution (review JD carefully)  ·  "
                     "🚫 suspicious (likely ghost / evergreen)")
        lines.append("")
        if suspicious_count or caution_count:
            lines.append(f"> {caution_count} caution · {suspicious_count} suspicious "
                         "— see the per-job 'Flags' line for details.")
            lines.append("")
        lines.append("---")
        lines.append("")

        for rank, (item, score, assessment) in enumerate(rows, start=1):
            job = item.job
            icon = _TIER_ICON.get(assessment.tier, " ") if assessment else " "
            posted_str = _humanize_age(job.posted_date)
            location = job.location or "—"
            salary = f" · {job.salary}" if job.salary else ""

            lines.append(
                f"## #{rank} — {job.company} — {job.title} ({score}% match) {icon}"
            )
            lines.append("")
            lines.append(f"- **Location:** {location}")
            lines.append(f"- **Source:** {job.source}")
            lines.append(f"- **Posted:** {posted_str}{salary}")
            lines.append(f"- **Apply:** {job.apply_url}")
            lines.append(f"- **dedup_key:** `{job.dedup_key()}`")
            if assessment and assessment.reasons:
                flags = "; ".join(assessment.reasons)
                lines.append(f"- **Flags:** {flags}")
            if job.description:
                preview = (job.description or "").strip().replace("\n", " ")[:240]
                if preview:
                    lines.append(f"- **Preview:** {preview}…")
            lines.append("")

        _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _QUEUE_PATH.write_text("\n".join(lines), encoding="utf-8")
        logger.info(
            f"Review queue written: {_QUEUE_PATH} "
            f"({len(rows)} jobs · {caution_count} caution · {suspicious_count} suspicious)"
        )
        return _QUEUE_PATH

    @staticmethod
    def path() -> Path:
        return _QUEUE_PATH

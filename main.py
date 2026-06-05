"""End-to-end pipeline: scrape → dedup → score → legitimacy check → review queue.

Outputs:
  - data/applied.sqlite
  - data/review_queue.md  (ranked jobs for manual review)
  - data/follow_ups.md    (cadence report for previously applied jobs)
"""

from __future__ import annotations

import re
from typing import Iterable

from config.user_config import config as user_config
from src.analyzer.match_scorer import MatchScorer
from src.apply.review_queue import ReviewQueue
from src.models import Job, ScoredJob
from src.scraper.scraper_factory import get_scraper
from src.tracker.local_db import LocalDB
from src.tracker.schema import Status
from src.tracker.followup_tracker import scan as scan_followups, write_report as write_followup_report
from src.utils.logger import logger


def _cross_source_key(job: Job) -> tuple[str, str]:
    return (job.company.strip().lower(), job.title.strip().lower())


def _absorb_jobs(
    jobs: Iterable[Job],
    found: dict[str, Job],
    cross_seen: dict[tuple[str, str], str],
    per_source_counts: dict[str, int],
) -> int:
    """Apply within-source + cross-source dedup. Returns count of cross-source drops."""
    cross_dropped = 0
    for job in jobs:
        if job.dedup_key() in found:
            continue
        ck = _cross_source_key(job)
        first_source = cross_seen.get(ck)
        if first_source and first_source != job.source:
            cross_dropped += 1
            logger.info(
                f"Cross-source duplicate dropped: {job.company} / {job.title} "
                f"({job.source} — already kept from {first_source})"
            )
            continue
        cross_seen[ck] = job.source
        found[job.dedup_key()] = job
        per_source_counts[job.source] = per_source_counts.get(job.source, 0) + 1
    return cross_dropped


def scrape_all(db: LocalDB) -> list[Job]:
    """Scrape all platforms in user_config.scrape_on_platforms, deduping within
    a source by id and across sources by (company, title).
    """
    all_titles = (user_config.job_title, *user_config.alternative_titles)
    found: dict[str, Job] = {}
    cross_seen: dict[tuple[str, str], str] = {}
    cross_dropped = 0
    per_source_counts: dict[str, int] = {}

    active_platforms = [
        p for p in user_config.scrape_on_platforms
        if p.lower() != "naukri" or user_config.naukri_search_enabled
    ]
    if not user_config.naukri_search_enabled and "naukri" in user_config.scrape_on_platforms:
        logger.info("Naukri search skipped — naukri_search_enabled=False")

    for platform_name in active_platforms:
        try:
            scraper = get_scraper(platform_name, user_config)
        except ValueError as exc:
            logger.warning(str(exc))
            continue

        for title in all_titles:
            for location in user_config.locations:
                try:
                    batch = list(scraper.search(title, location))
                    cross_dropped += _absorb_jobs(
                        batch, found, cross_seen, per_source_counts
                    )
                except Exception as exc:
                    logger.exception(
                        f"{platform_name} search failed for {title}/{location}: {exc}"
                    )

    logger.info(
        f"Scrape summary — kept {len(found)} unique jobs "
        f"({per_source_counts}); cross-source duplicates dropped: {cross_dropped}"
    )
    return list(found.values())


def _salary_below_min(salary_str: str | None, min_salary: int) -> bool:
    """Return True only when salary is disclosed AND its max value is below min_salary."""
    if not salary_str:
        return False
    s = salary_str.lower().replace(",", "").replace("₹", "").replace("$", "").strip()
    numbers = re.findall(r"\d+(?:\.\d+)?", s)
    if not numbers:
        return False
    max_val = max(float(n) for n in numbers)
    if "cr" in s or "crore" in s:
        max_val *= 10_000_000
    elif "lac" in s or "lpa" in s or re.search(r"\bl\b", s):
        max_val *= 100_000
    elif "k" in s:
        max_val *= 1_000
    return int(max_val) < min_salary


def _compile_title_exclusions() -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in user_config.skip_title_patterns]


_TITLE_EXCLUSIONS = _compile_title_exclusions()


def filter_and_rank(jobs: list[Job], db: LocalDB) -> tuple[list[ScoredJob], dict[str, int]]:
    skip_companies = {c.lower() for c in user_config.skip_companies}
    scorer = MatchScorer(
        user_config.skills,
        recency_weight=user_config.job_recency_weight,
        recency_hours_threshold=user_config.job_recency_hours_threshold,
        india_location_boost=user_config.india_location_boost,
        priority_companies=user_config.priority_companies,
        priority_company_boost=user_config.priority_company_boost,
    )

    fresh: list[Job] = []
    scores: dict[str, int] = {}
    stats = {"skipped_company": 0, "skipped_title": 0, "already_seen": 0, "applied_recently": 0, "low_salary": 0, "low_score": 0, "passed": 0}
    score_samples: list[tuple[int, str, str]] = []

    for job in jobs:
        if job.company.lower() in skip_companies:
            stats["skipped_company"] += 1
            continue
        if any(rx.search(job.title) for rx in _TITLE_EXCLUSIONS):
            stats["skipped_title"] += 1
            logger.debug(f"Filtered (title too senior): {job.company} — {job.title}")
            continue
        if db.already_seen(job):
            stats["already_seen"] += 1
            continue
        if db.applied_recently(job.company, job.title, user_config.skip_if_applied_in_days):
            stats["applied_recently"] += 1
            continue
        if _salary_below_min(job.salary, user_config.salary_min):
            stats["low_salary"] += 1
            logger.debug(f"Filtered (salary below {user_config.salary_min}): {job.company} — {job.title} [{job.salary}]")
            continue
        score = scorer.score(job)
        score_samples.append((score, job.company, job.title))
        if score < user_config.min_match_score:
            stats["low_score"] += 1
            continue
        stats["passed"] += 1
        fresh.append(job)
        scores[job.dedup_key()] = score

    logger.info(
        f"Filter breakdown — skip_company: {stats['skipped_company']} | "
        f"skip_title: {stats['skipped_title']} | "
        f"already_seen: {stats['already_seen']} | "
        f"applied_recently: {stats['applied_recently']} | "
        f"low_salary: {stats['low_salary']} | "
        f"low_score (<{user_config.min_match_score}%): {stats['low_score']} | "
        f"passed: {stats['passed']}"
    )
    if score_samples:
        score_samples.sort(reverse=True)
        top5 = score_samples[:5]
        bottom5 = score_samples[-5:]
        logger.info(f"Top 5 scores: {[(s, c, t[:30]) for s, c, t in top5]}")
        logger.info(f"Bottom 5 scores: {[(s, c, t[:30]) for s, c, t in bottom5]}")
        avg = sum(s for s, _, _ in score_samples) / len(score_samples)
        logger.info(f"Score stats — avg: {avg:.1f} | min: {score_samples[-1][0]} | max: {score_samples[0][0]} | threshold: {user_config.min_match_score}")

    db.upsert_jobs(fresh, scores)
    fresh.sort(key=lambda j: scores[j.dedup_key()], reverse=True)
    logger.info(
        f"After filter+rank: {len(fresh)} jobs queued for review "
        f"(top {user_config.review_queue_top_n} will appear in queue)"
    )
    return [ScoredJob(job=j) for j in fresh], scores


_DEDUP_RE = re.compile(r"\*\*dedup_key:\*\*\s+`([^`]+)`")


def _auto_skip_previous_queue(db: LocalDB) -> int:
    """Mark any SCRAPED jobs left over from the previous review queue as SKIPPED."""
    queue_path = ReviewQueue.path()
    if not queue_path.exists():
        return 0
    text = queue_path.read_text(encoding="utf-8")
    keys = _DEDUP_RE.findall(text)
    skipped = 0
    for key in keys:
        row = db._conn.execute(
            "SELECT status FROM jobs WHERE dedup_key = ?", (key,)
        ).fetchone()
        if row and row["status"] == Status.SCRAPED:
            db.update_status(key, Status.SKIPPED)
            skipped += 1
    if skipped:
        logger.info(f"Auto-skipped {skipped} leftover job(s) from previous review queue")
    return skipped


def run() -> None:
    with LocalDB() as db:
        raw_jobs = scrape_all(db)
        if not raw_jobs:
            logger.warning("No jobs scraped. Check API keys and search params.")
            return
        scored, scores = filter_and_rank(raw_jobs, db)
        if not scored:
            logger.info("Nothing passed the filter today.")
            return

        _auto_skip_previous_queue(db)
        queue = ReviewQueue(user_config, db)
        queue_path = queue.build(scored, scores)
        logger.info("=" * 60)
        logger.info(f"Open {queue_path} to review and apply manually.")
        logger.info("After applying, run: python scripts/mark_applied.py <dedup_key>")
        logger.info("=" * 60)

        followups = scan_followups(db)
        if followups:
            write_followup_report(followups)


if __name__ == "__main__":
    run()

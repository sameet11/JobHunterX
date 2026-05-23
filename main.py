"""End-to-end pipeline: scrape → dedup → score → analyze → apply → log.

Phase 1 (scrape/score/analyze) and Phase 2 (apply) both run here. The
apply phase respects DailyLimiter and only fires for platforms listed
in user_config.apply_on_platforms.

Outputs:
  - data/applied.sqlite (always)
  - Google Sheets Applications tab (if GOOGLE_SHEET_ID configured)
  - logs/applications/*.png screenshots for every submission
"""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Iterable

from config.platform_config import platform
from config.user_config import config as user_config
from src.analyzer.match_scorer import MatchScorer
from src.apply.applier_factory import get_applier
from src.apply.base_applier import ApplyStatus
from src.apply.daily_limiter import DailyLimitReached, DailyLimiter
from src.apply.review_queue import ReviewQueue
from src.models import Job, ScoredJob
from src.scraper.scraper_factory import get_scraper
from src.tracker.google_sheets import GoogleSheets
from src.tracker.local_db import LocalDB
from src.tracker.schema import Status
import dataclasses

from src.outreach.approval_engine import ApprovalEngine, ApprovalMode
from src.outreach.linkedin_orchestrator import LinkedInOutreachOrchestrator
from src.outreach.linkedin_outreach import get_linkedin_outreach
from src.outreach.orchestrator import build_orchestrator_from_config
from src.resume.resume_tailor import ResumeTailor
from src.tracker.followup_tracker import scan as scan_followups, write_report as write_followup_report
from src.utils.logger import logger

_RESUME_PATH = Path(__file__).parent / "src" / "resume" / "templates" / "base_resume.json"


def load_resume() -> dict:
    with _RESUME_PATH.open("r", encoding="utf-8") as fp:
        return json.load(fp)


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

    Greenhouse, Lever, and HN scrapers fetch data once per instance and cache it;
    the title × location loop filters locally with no repeated API calls.
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
    """Return True only when salary is disclosed AND its max value is below min_salary.
    Returns False (keep the job) when salary is absent or unparseable.

    Handles Indian formats: "3-5 Lacs PA", "12 LPA", "₹3,00,000 – ₹5,00,000", "20-25L".
    """
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


def filter_and_rank(jobs: list[Job], db: LocalDB) -> tuple[list[ScoredJob], dict[str, int]]:
    skip_companies = {c.lower() for c in user_config.skip_companies}
    scorer = MatchScorer(
        user_config.skills,
        recency_weight=user_config.job_recency_weight,
        recency_hours_threshold=user_config.job_recency_hours_threshold,
        india_location_boost=user_config.india_location_boost,
    )

    fresh: list[Job] = []
    scores: dict[str, int] = {}
    stats = {"skipped_company": 0, "already_seen": 0, "applied_recently": 0, "low_salary": 0, "low_score": 0, "passed": 0}
    score_samples: list[tuple[int, str, str]] = []  # (score, company, title) for debug

    for job in jobs:
        if job.company.lower() in skip_companies:
            stats["skipped_company"] += 1
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
        f"(target: apply to {user_config.daily_application_limit})"
    )
    return [ScoredJob(job=j) for j in fresh], scores


def _open_sheets() -> GoogleSheets | None:
    if not platform.google_sheet_id:
        logger.info("Skipping Google Sheets sync — GOOGLE_SHEET_ID not set")
        return None
    sheets = GoogleSheets()
    sheets.init()
    return sheets


def _humanlike_apply_gap(idx: int) -> float:
    """Seconds to wait between successive applications (longer break every Nth)."""
    every = max(1, user_config.apply_long_break_every)
    if idx > 0 and idx % every == 0:
        lo, hi = user_config.apply_long_break_min_seconds, user_config.apply_long_break_max_seconds
    else:
        lo, hi = user_config.apply_gap_min_seconds, user_config.apply_gap_max_seconds
    if hi < lo:
        hi = lo
    return float(random.randint(lo, hi))


def apply_to_jobs(
    scored: list[ScoredJob],
    db: LocalDB,
    sheets: GoogleSheets | None,
    resume: dict,
) -> list[ScoredJob]:
    """Phase 2: apply directly to ranked jobs until daily_application_limit is hit.

    Walks the ranked job list in score order and attempts to apply to each.
    Stops once we've submitted daily_application_limit applications.

    Returns the list of jobs that were applied to (used by outreach phase).
    """
    enabled = {
        p.lower() for p in user_config.apply_on_platforms
        if p.lower() != "naukri" or user_config.naukri_apply_enabled
    }
    if not enabled:
        logger.info("apply_on_platforms is empty — skipping Phase 2 (apply)")
        return []

    limiter = DailyLimiter(db, user_config.daily_application_limit)
    if limiter.is_exhausted():
        logger.warning(
            f"Daily application limit ({limiter.daily_limit}) already reached — nothing to apply"
        )
        return []

    tailor = ResumeTailor() if user_config.use_tailored_resume else None

    applied_jobs: list[ScoredJob] = []
    submitted_count = 0

    for idx, item in enumerate(scored):
        if submitted_count >= limiter.daily_limit:
            logger.info(
                f"Daily limit reached ({submitted_count}/{limiter.daily_limit}) — stopping"
            )
            break

        job = item.job
        if job.source.lower() not in enabled:
            continue

        applied_jobs.append(item)

        try:
            limiter.assert_can_apply()
        except DailyLimitReached as exc:
            logger.warning(str(exc))
            break

        if tailor is not None:
            resume_path = tailor.generate(
                job.company, job.title, None, static_fallback=user_config.resume_path
            )
            job_config = dataclasses.replace(user_config, resume_path=resume_path)
        else:
            resume_path = user_config.resume_path
            job_config = user_config

        try:
            applier = get_applier(job.source, job_config)
        except ValueError as exc:
            logger.warning(str(exc))
            continue

        if submitted_count > 0:
            gap = _humanlike_apply_gap(submitted_count)
            logger.info(f"Sleeping {gap:.0f}s before next application (human pacing)")
            time.sleep(gap)

        logger.info(f"Applying to {job.company} — {job.title} via {job.source} (resume: {resume_path.name})")
        result = applier.apply(item)
        notes = (result.confirmation_text or result.reason or "").strip()
        if result.screenshot_path:
            notes = f"{notes} | screenshot: {result.screenshot_path}".strip(" |")

        if result.status is ApplyStatus.SUBMITTED:
            db.update_status(job.dedup_key(), Status.APPLIED)
            if sheets is not None:
                sheets.append_application(
                    job,
                    None,
                    status=Status.APPLIED,
                    notes=notes,
                    resume_path=str(resume_path),
                )
            submitted_count += 1
            logger.info(
                f"  -> SUBMITTED ({submitted_count}/{limiter.daily_limit}) "
                f"{job.company}/{job.title}"
            )
        elif result.status is ApplyStatus.CAPTCHA:
            logger.error(
                f"  -> CAPTCHA on {job.company}/{job.title} — pausing run; rerun after solving"
            )
            break
        elif result.status is ApplyStatus.REDIRECT:
            db.update_status(job.dedup_key(), Status.SKIPPED)
            logger.info(f"  -> REDIRECT {job.company}/{job.title}: {result.reason}")
        elif result.status is ApplyStatus.SKIPPED:
            logger.info(f"  -> SKIPPED {job.company}/{job.title}: {result.reason}")
        else:  # FAILED
            logger.warning(f"  -> FAILED {job.company}/{job.title}: {result.reason}")

    logger.info(
        f"Phase 2 done — submitted {submitted_count}/{limiter.daily_limit} | "
        f"pool size {len(scored)}"
    )
    return applied_jobs


def outreach_phase(
    scored: list[ScoredJob],
    db: LocalDB,
    sheets: GoogleSheets | None,
) -> None:
    """Phase 3: find recruiters per applied job, draft + approve + send outreach."""
    if not user_config.outreach_enabled:
        logger.info("outreach_enabled=False — skipping Phase 3")
        return

    # Only do outreach for jobs the analyzer flagged as worth applying to.
    targets = [s for s in scored if not (s.analysis and not s.analysis.should_apply)]
    if not targets:
        logger.info("No outreach targets — skipping Phase 3")
        return

    orchestrator = build_orchestrator_from_config(user_config, db, sheets)
    daily_remaining = user_config.daily_outreach_limit - db.outreach_count_today()
    if daily_remaining <= 0:
        logger.warning(f"Daily outreach limit ({user_config.daily_outreach_limit}) reached")
        return

    # Outreach (referral email + LinkedIn DM/invite) ALWAYS uses the static
    # sameet_sabu_resume.pdf — never the JD-tailored variant. The tailored
    # resume is only attached to job applications themselves (Phase 2).
    static_resume = user_config.resume_path

    total_sent = 0
    for item in targets:
        if daily_remaining <= 0:
            break
        results = orchestrator.reach_out_for_job(
            item,
            resume_path=static_resume,
            daily_remaining=daily_remaining,
        )
        sent_now = sum(1 for m in results if m.status.value == "sent")
        daily_remaining -= sent_now
        total_sent += sent_now

    logger.info(f"Phase 3 done — sent {total_sent} outreach message(s)")

    if user_config.linkedin_outreach_enabled and daily_remaining > 0:
        try:
            linkedin_phase(targets, db, sheets, daily_remaining)
        except Exception as exc:
            logger.warning(f"LinkedIn outreach skipped — {type(exc).__name__}: {exc}")


def linkedin_phase(
    targets: list[ScoredJob],
    db: LocalDB,
    sheets: GoogleSheets | None,
    daily_remaining: int,
) -> None:
    """Phase 3b: LinkedIn DM (connections) + connection-requests (non-connections)."""
    if not targets:
        return
    backend = get_linkedin_outreach(user_config.linkedin_outreach_backend)
    approval = ApprovalEngine(mode=ApprovalMode(user_config.approval_mode))
    orch = LinkedInOutreachOrchestrator(
        backend=backend,
        approval=approval,
        db=db,
        sheets=sheets,
        max_people_per_company=user_config.max_linkedin_people_per_company,
        cooldown_days=user_config.outreach_cooldown_days,
        current_company=user_config.applicant.current_company,
        sender_name=user_config.applicant.full_name,
        jitter_min_seconds=user_config.linkedin_jitter_min_seconds,
        jitter_max_seconds=user_config.linkedin_jitter_max_seconds,
    )
    sent = 0
    for item in targets:
        if daily_remaining <= 0:
            break
        results = orch.reach_out_for_job(item, daily_remaining=daily_remaining)
        sent_now = sum(1 for m in results if m.status.value == "sent")
        daily_remaining -= sent_now
        sent += sent_now
    logger.info(f"Phase 3b done — sent {sent} LinkedIn DM/invite(s)")


def _fetch_applied_for_outreach(db: LocalDB) -> list[ScoredJob]:
    """Pull jobs marked Applied in the DB so outreach can run for them.

    In review-queue mode we never call outreach for freshly-scraped jobs — only
    for ones the user manually applied to (via scripts/mark_applied.py). The
    orchestrator's per-recruiter cooldown handles outreach dedup across runs.
    """
    cur = db._conn.execute(
        """
        SELECT job_id, source, company, title, location, salary,
               apply_url, description
        FROM jobs
        WHERE status = ?
        ORDER BY last_updated DESC
        LIMIT 50
        """,
        (Status.APPLIED,),
    )
    items: list[ScoredJob] = []
    for row in cur.fetchall():
        job = Job(
            id=row["job_id"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            salary=row["salary"],
            apply_url=row["apply_url"] or "",
            description=row["description"] or "",
            source=row["source"],
        )
        items.append(ScoredJob(job=job))
    return items


_DEDUP_RE = re.compile(r"\*\*dedup_key:\*\*\s+`([^`]+)`")


def _auto_skip_previous_queue(db: LocalDB) -> int:
    """Mark any SCRAPED jobs left over from the previous review queue as SKIPPED.

    Runs at the start of each new pipeline run so yesterday's unseen jobs don't
    keep reappearing. Only affects jobs still in SCRAPED status — applied/skipped
    ones are untouched.
    """
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

        sheets = _open_sheets()

        if user_config.use_review_queue:
            # Human-in-the-loop: write a markdown queue; user applies manually.
            _auto_skip_previous_queue(db)
            queue = ReviewQueue(user_config, db)
            queue_path = queue.build(scored, scores)
            logger.info("=" * 60)
            logger.info(f"Open {queue_path} to review and apply manually.")
            logger.info("After applying, run: python scripts/mark_applied.py <dedup_key>")
            logger.info("=" * 60)
            # Follow-up sweep: classify Applied/Responded/Interview by cadence.
            followups = scan_followups(db)
            if followups:
                write_followup_report(followups)
        else:
            # Legacy auto-apply path.
            resume = load_resume()
            applied = apply_to_jobs(scored, db, sheets, resume)
            outreach_phase(applied, db, sheets)


if __name__ == "__main__":
    run()

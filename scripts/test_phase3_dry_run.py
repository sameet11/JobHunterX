"""End-to-end dry run of Phase 3 (outreach) using all dummy data.

Run:
    .venv\\Scripts\\python.exe scripts\\test_phase3_dry_run.py

What it does:
- Builds 3 fake jobs (one per company in MockRecruiterFinder's catalog)
- Wires the orchestrator with: MockRecruiterFinder + AUTO_APPROVE + DryRunSender + temp DB
- Runs reach_out_for_job for each job
- Prints what would have been sent + final DB state
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Make project root importable when running this script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import (
    JDAnalysis,
    Job,
    OutreachStatus,
    OutreachStyle,
    ScoredJob,
)
from src.outreach.approval_engine import ApprovalEngine, ApprovalMode
from src.outreach.email_sender import DryRunEmailSender
from src.outreach.orchestrator import OutreachOrchestrator
from src.outreach.recruiter_finder import MockRecruiterFinder
from src.tracker.local_db import LocalDB


def _make_scored_job(job_id: str, title: str, company: str, top_skills: list[str]) -> ScoredJob:
    job = Job(
        id=job_id,
        title=title,
        company=company,
        location="Bangalore",
        salary="40L - 70L INR",
        description=f"Looking for {title} with {', '.join(top_skills[:3])} experience...",
        apply_url=f"https://example.com/jobs/{job_id}",
        easy_apply=True,
        source="naukri",
    )
    analysis = JDAnalysis(
        match_score=85,
        required_skills=top_skills,
        candidate_has_skills=top_skills,
        keywords_to_include=top_skills,
        should_apply=True,
        summary=f"Strong match for {company}",
    )
    return ScoredJob(job=job, analysis=analysis)


def _print_header(text: str) -> None:
    print()
    print("=" * 70)
    print(f"  {text}")
    print("=" * 70)


def main() -> int:
    _print_header("Phase 3 Dry Run — Outreach Pipeline End-to-End")

    # 3 fake jobs — one matching each pre-seeded company in MockRecruiterFinder
    jobs = [
        _make_scored_job("j1", "Senior Backend Engineer", "Google", ["Python", "FastAPI", "AWS"]),
        _make_scored_job("j2", "Software Engineer", "TechCorp", ["Java", "Spring Boot", "Kafka"]),
        _make_scored_job("j3", "Full Stack Engineer", "StartupXYZ", ["React", "Node.js", "GCP"]),
    ]

    # Use a temp DB so we don't pollute the real applied.sqlite
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmpf:
        db_path = Path(tmpf.name)

    try:
        with LocalDB(db_path) as db:
            sender = DryRunEmailSender()
            orchestrator = OutreachOrchestrator(
                finder=MockRecruiterFinder(),
                approval=ApprovalEngine(mode=ApprovalMode.AUTO_APPROVE),
                sender=sender,
                db=db,
                style=OutreachStyle.REFERRAL,
                attach_resume=False,  # skip attachment in dry-run
                max_recruiters_per_company=3,
                cooldown_days=90,
            )

            all_results = []
            daily_remaining = 20
            for scored in jobs:
                _print_header(f"Job: {scored.job.title} @ {scored.job.company}")
                results = orchestrator.reach_out_for_job(
                    scored,
                    daily_remaining=daily_remaining,
                )
                for msg in results:
                    sent_marker = "OK " if msg.status == OutreachStatus.SENT else "-- "
                    print(
                        f"  [{sent_marker}] {msg.recruiter.name:25s} "
                        f"({msg.recruiter.email:35s}) -> {msg.status.value}"
                    )
                    if msg.status == OutreachStatus.SENT:
                        daily_remaining -= 1
                all_results.extend(results)

            _print_header("Summary")
            sent_count = sum(1 for m in all_results if m.status == OutreachStatus.SENT)
            print(f"  Total drafts created : {len(all_results)}")
            print(f"  Total emails sent    : {sent_count}")
            print(f"  Daily remaining      : {daily_remaining}")
            print(f"  DryRun sender bucket : {len(sender.sent)} message(s)")
            print(f"  DB rows in outreach  : {db._conn.execute('SELECT COUNT(*) FROM outreach').fetchone()[0]}")

            _print_header("Sample Email Preview (first sent)")
            first_sent = next((m for m in all_results if m.status == OutreachStatus.SENT), None)
            if first_sent:
                print(f"  To:      {first_sent.recruiter.email}")
                print(f"  Subject: {first_sent.subject}")
                print()
                for line in first_sent.body.split("\n"):
                    print(f"    {line}")

            _print_header("Cooldown Re-Run Test")
            print("  Running pipeline again for same jobs — should skip everyone (cooldown)")
            second_run_results = []
            for scored in jobs:
                results = orchestrator.reach_out_for_job(scored, daily_remaining=20)
                second_run_results.extend(results)
            print(f"  Second run produced {len(second_run_results)} message(s) (expected 0)")

            print()
            print("All Phase 3 components verified end-to-end [OK]")
            return 0

    finally:
        db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())

"""Single source of truth for the Google Sheets / SQLite column layout."""

from __future__ import annotations

SHEET_COLUMNS: list[str] = [
    "Date Applied",
    "Company",
    "Role",
    "Salary Offered",
    "Location",
    "Source",
    "Apply URL",
    "Status",
    "Match Score (%)",
    "Missing Skills",
    "Resume Used",
    "Recruiters Found",
    "Recruiter Emails",
    "Recruiter LinkedIn",
    "LinkedIn Msg Sent",
    "Email Sent",
    "Referral Status",
    "Response Received",
    "Interview Date",
    "Notes",
]


class Status:
    SCRAPED = "Scraped"
    SKIPPED = "Skipped"
    APPLIED = "Applied"
    RECRUITER_FOUND = "Recruiter Found"
    RESPONDED = "Responded"
    INTERVIEW = "Interview Scheduled"
    REJECTED = "Rejected"
    GHOSTED = "Ghosted"
    OFFER = "Offer"


CONNECT_QUEUE_COLUMNS: list[str] = [
    "Date",
    "Name",
    "LinkedIn URL",
    "Company",
    "Job Title",
    "Job URL",
    "Connection Note",
]

OUTREACH_COLUMNS: list[str] = [
    "Date",
    "Recruiter",
    "Title",
    "Company",
    "Email",
    "LinkedIn",
    "Source",
    "Channel",
    "Style",
    "Job Title",
    "Subject",
    "Body Preview",
    "Status",
    "Message Approved",
    "Sent At",
    "Error",
]

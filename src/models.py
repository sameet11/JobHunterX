"""Shared dataclasses passed between pipeline stages."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Job(BaseModel):
    id: str
    title: str
    company: str
    location: str | None = None
    salary: str | None = None
    description: str = ""
    apply_url: str
    easy_apply: bool = False
    posted_date: datetime | None = None
    source: str

    def dedup_key(self) -> str:
        return f"{self.source}:{self.id}"


class JDAnalysis(BaseModel):
    match_score: int = Field(ge=0, le=100)
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    candidate_has_skills: list[str] = []
    missing_skills: list[str] = []
    key_responsibilities: list[str] = []
    keywords_to_include: list[str] = []
    company_culture: str = ""
    summary: str = ""
    should_apply: bool = True
    reason: str = ""


class ScoredJob(BaseModel):
    job: Job
    analysis: Optional[JDAnalysis] = None

    @property
    def score(self) -> int:
        return self.analysis.match_score if self.analysis else 0


class Recruiter(BaseModel):
    """A person who may refer or hire — recruiter, HR, hiring manager, engineer."""

    name: str
    company: str
    title: str = ""
    email: str = ""
    linkedin_url: str = ""
    source: str = "mock"  # 'hunter', 'apollo', 'linkedin', 'mock'
    confidence: int = 0  # 0-100, how sure we are the email is correct

    def dedup_key(self) -> str:
        return f"{self.email or self.linkedin_url}:{self.company}".lower()


class OutreachStatus(str, Enum):
    DRAFTED = "drafted"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    SENT = "sent"
    FAILED = "failed"
    MANUAL_CONNECT = "manual_connect"  # queued for manual LinkedIn connection


class OutreachChannel(str, Enum):
    EMAIL = "email"
    LINKEDIN_MSG = "linkedin_msg"
    LINKEDIN_INVITE = "linkedin_invite"


class OutreachStyle(str, Enum):
    REFERRAL = "referral"  # Static template
    COLD = "cold"          # AI-generated personalized


class OutreachMessage(BaseModel):
    """A draft or sent outreach message tied to a recruiter + job."""

    recruiter: Recruiter
    job: Job
    channel: OutreachChannel
    style: OutreachStyle
    subject: str
    body: str
    status: OutreachStatus = OutreachStatus.DRAFTED
    sent_at: Optional[datetime] = None
    error: str = ""
    message_id: str = ""  # SMTP message-id or LinkedIn convo id

    def dedup_key(self) -> str:
        return f"{self.recruiter.dedup_key()}|{self.job.dedup_key()}|{self.channel.value}"

"""Static referral templates — no AI, no cost.

Three flavors share one rendering surface:
- ReferralTemplate.render(...)        : email referral request (long-form)
- LinkedInDMTemplate.render(...)      : DM to an existing connection (medium-form)
- LinkedInInviteTemplate.render(...)  : connection-request note (<=300 chars)

All include the live job link and mention the user's current company
("Lucid Motors (LTM)" by default — see ApplicantProfile.current_company).
"""

from __future__ import annotations

from dataclasses import dataclass

# ───── Email referral ─────

_SUBJECT = "Referral Request — {role} at {company}"

_BODY = """\
Hi {person_name},

I came across the {role} opening at {company} and would love to be considered.
Job link: {job_link}

I'm a Software Engineer with 3 years of experience in Python, FastAPI, and \
cloud-native systems (AWS/GCP), currently at {current_company}. My resume is \
attached.

Would you be open to referring me or sharing this with your team?
Appreciate your time — happy to connect.

Best,
{sender_name}
{sender_email} | {sender_phone}\
"""

# ───── LinkedIn DM (existing connection) ─────

_DM_SUBJECT = "Referral — {role} at {company}"

_DM_BODY = """\
Hi {person_name},

Hope you're doing well! I noticed {company} is hiring for {role} and it lines up \
well with what I'm working on at {current_company}.

Job link: {job_link}

Would you be open to referring me? Happy to share my resume if helpful.

Thanks,
{sender_name}\
"""

# ───── LinkedIn connection-request note (≤300 chars) ─────
# LinkedIn caps invite notes at 300 characters.

_INVITE_NOTE = (
    "Hi {first_name}, I'm {sender_name} from {current_company}. I'm exploring "
    "the {role} role at {company} and thought it'd be great to connect — would "
    "love to learn about your team. Thanks!"
)

_INVITE_NOTE_MAX = 300


@dataclass(frozen=True)
class ReferralEmail:
    subject: str
    body: str


@dataclass(frozen=True)
class LinkedInDM:
    subject: str  # informational only — LinkedIn DMs have no subject
    body: str


@dataclass(frozen=True)
class LinkedInInvite:
    note: str


class ReferralTemplate:
    """Renders an email referral request."""

    def render(
        self,
        *,
        person_name: str,
        company: str,
        role: str,
        job_link: str = "",
        current_company: str = "",
        sender_name: str = "",
        sender_email: str = "",
        sender_phone: str = "",
    ) -> ReferralEmail:
        ctx = dict(
            person_name=person_name,
            company=company,
            role=role,
            job_link=job_link or "(link not available)",
            current_company=current_company,
            sender_name=sender_name,
            sender_email=sender_email,
            sender_phone=sender_phone,
        )
        return ReferralEmail(
            subject=_SUBJECT.format(**ctx),
            body=_BODY.format(**ctx),
        )


class LinkedInDMTemplate:
    """Renders a LinkedIn DM body for an existing connection."""

    def render(
        self,
        *,
        person_name: str,
        company: str,
        role: str,
        job_link: str = "",
        current_company: str = "Lucid Motors (LTM)",
        sender_name: str = "Sameet Sabu",
    ) -> LinkedInDM:
        ctx = dict(
            person_name=person_name,
            company=company,
            role=role,
            job_link=job_link or "(link not available)",
            current_company=current_company,
            sender_name=sender_name,
        )
        return LinkedInDM(
            subject=_DM_SUBJECT.format(**ctx),
            body=_DM_BODY.format(**ctx),
        )


class LinkedInInviteTemplate:
    """Renders a connection-request note. Trims to LinkedIn's 300-char cap."""

    MAX_CHARS = _INVITE_NOTE_MAX

    def render(
        self,
        *,
        person_name: str,
        company: str,
        role: str,
        current_company: str = "Lucid Motors (LTM)",
        sender_name: str = "Sameet Sabu",
    ) -> LinkedInInvite:
        first_name = (person_name or "").strip().split(" ", 1)[0] or "there"
        note = _INVITE_NOTE.format(
            first_name=first_name,
            sender_name=sender_name,
            current_company=current_company,
            role=role,
            company=company,
        )
        if len(note) > self.MAX_CHARS:
            # Hard trim with ellipsis.
            note = note[: self.MAX_CHARS - 1].rstrip() + "…"
        return LinkedInInvite(note=note)

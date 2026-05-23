"""Tests for LinkedInOutreach backends and template rendering."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.models import Recruiter
from src.outreach.linkedin_outreach import (
    LinkedInApiOutreach,
    MockLinkedInOutreach,
    get_linkedin_outreach,
)
from src.outreach.referral_template import (
    LinkedInDMTemplate,
    LinkedInInviteTemplate,
)


# ───── fixtures ─────

@pytest.fixture
def connection_recruiter() -> Recruiter:
    return Recruiter(
        name="Priya Sharma",
        title="Senior Technical Recruiter",
        email="priya@acme.com",
        company="Acme",
        linkedin_url="https://www.linkedin.com/in/priya-sharma",
        source="linkedin",
        confidence=90,
    )


@pytest.fixture
def unknown_recruiter() -> Recruiter:
    return Recruiter(
        name="Raj Patel",
        title="Engineering Manager",
        email="raj@newco.com",
        company="NewCo",
        linkedin_url="https://www.linkedin.com/in/raj-patel",
        source="linkedin",
        confidence=75,
    )


# ───── MockLinkedInOutreach ─────

class TestMockBackend:
    def test_find_returns_people(self):
        backend = MockLinkedInOutreach()
        people = backend.find_company_people("Google", max_results=3)
        assert len(people) >= 1
        assert all(isinstance(p, Recruiter) for p in people)

    def test_find_respects_max_results(self):
        backend = MockLinkedInOutreach()
        people = backend.find_company_people("Google", max_results=1)
        assert len(people) == 1

    def test_find_unknown_company_returns_synthetic_recruiter(self):
        backend = MockLinkedInOutreach()
        people = backend.find_company_people("RandomCorp12345")
        assert len(people) == 1
        assert "RandomCorp12345" in people[0].company

    def test_is_connection_by_email(self, connection_recruiter):
        backend = MockLinkedInOutreach(
            connection_emails={"priya@acme.com"}
        )
        assert backend.is_connection(connection_recruiter) is True

    def test_is_connection_by_linkedin_url(self, connection_recruiter):
        backend = MockLinkedInOutreach(
            connection_urls={"https://www.linkedin.com/in/priya-sharma"}
        )
        assert backend.is_connection(connection_recruiter) is True

    def test_not_a_connection(self, unknown_recruiter):
        backend = MockLinkedInOutreach(
            connection_emails={"someone.else@example.com"}
        )
        assert backend.is_connection(unknown_recruiter) is False

    def test_send_dm_records_action(self, connection_recruiter):
        backend = MockLinkedInOutreach()
        result = backend.send_dm(
            connection_recruiter, subject="Referral", body="Hi Priya…"
        )
        assert result.success is True
        assert result.action == "dm"
        assert connection_recruiter in backend.dms_sent

    def test_send_invite_records_action(self, unknown_recruiter):
        backend = MockLinkedInOutreach()
        result = backend.send_connection_request(unknown_recruiter, note="Hi!")
        assert result.success is True
        assert result.action == "invite"
        assert unknown_recruiter in backend.invites_sent

    def test_factory_mock(self):
        backend = get_linkedin_outreach("mock")
        assert isinstance(backend, MockLinkedInOutreach)

    def test_factory_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            get_linkedin_outreach("carrier_pigeon")


# ───── LinkedInDMTemplate ─────

class TestLinkedInDMTemplate:
    def test_renders_all_fields(self):
        tpl = LinkedInDMTemplate()
        dm = tpl.render(
            person_name="Priya Sharma",
            company="Google",
            role="Senior SWE",
            job_link="https://linkedin.com/jobs/view/123",
        )
        assert "Priya Sharma" in dm.body
        assert "Google" in dm.body
        assert "Senior SWE" in dm.body
        assert "https://linkedin.com/jobs/view/123" in dm.body

    def test_includes_current_company_ltm(self):
        tpl = LinkedInDMTemplate()
        dm = tpl.render(
            person_name="Test",
            company="Stripe",
            role="SWE",
            job_link="https://example.com/job",
        )
        assert "Lucid Motors (LTM)" in dm.body

    def test_no_template_placeholders_remain(self):
        tpl = LinkedInDMTemplate()
        dm = tpl.render(
            person_name="X", company="Y", role="Z", job_link="http://j.link"
        )
        assert "{" not in dm.body and "}" not in dm.body


# ───── LinkedInInviteTemplate ─────

class TestLinkedInInviteTemplate:
    MAX = LinkedInInviteTemplate.MAX_CHARS

    def test_renders_correctly(self):
        tpl = LinkedInInviteTemplate()
        invite = tpl.render(
            person_name="Raj Patel",
            company="Stripe",
            role="Backend Engineer",
        )
        assert "Stripe" in invite.note
        assert "Backend Engineer" in invite.note
        assert "Raj" in invite.note  # first name only

    def test_within_300_chars(self):
        tpl = LinkedInInviteTemplate()
        invite = tpl.render(
            person_name="A" * 50,
            company="B" * 50,
            role="C" * 50,
        )
        assert len(invite.note) <= self.MAX

    def test_includes_ltm(self):
        tpl = LinkedInInviteTemplate()
        invite = tpl.render(
            person_name="Test Person",
            company="Acme",
            role="SWE",
        )
        assert "Lucid Motors (LTM)" in invite.note

    def test_trims_long_note_with_ellipsis(self):
        tpl = LinkedInInviteTemplate()
        invite = tpl.render(
            person_name="VeryLongPersonNameHere" * 3,
            company="VeryLongCompanyNameHere" * 3,
            role="Senior Principal Staff Distinguished Engineer III" * 2,
        )
        assert len(invite.note) <= self.MAX
        assert invite.note.endswith("…")

    def test_single_word_person_name(self):
        tpl = LinkedInInviteTemplate()
        invite = tpl.render(person_name="Priya", company="Google", role="SWE")
        assert "Priya" in invite.note


# ───── LinkedInApiOutreach ─────

@pytest.fixture
def mock_api():
    return MagicMock()


@pytest.fixture
def mock_finder():
    finder = MagicMock()
    finder.find.return_value = [
        Recruiter(name="Priya Sharma", company="Stripe",
                  linkedin_url="https://www.linkedin.com/in/priya-sharma-abc",
                  source="google_search")
    ]
    return finder


@pytest.fixture
def api_backend(mock_api, mock_finder):
    return LinkedInApiOutreach(_api=mock_api, recruiter_finder=mock_finder)


@pytest.fixture
def recruiter_with_url():
    return Recruiter(
        name="Priya Sharma",
        company="Stripe",
        linkedin_url="https://www.linkedin.com/in/priya-sharma-abc",
        source="google_search",
    )


@pytest.fixture
def recruiter_no_url():
    return Recruiter(name="No URL Person", company="Acme")


class TestLinkedInApiOutreachSlug:
    def test_slug_extracted_from_standard_url(self, api_backend):
        assert api_backend._slug("https://www.linkedin.com/in/priya-sharma-abc") == "priya-sharma-abc"

    def test_slug_strips_trailing_slash(self, api_backend):
        assert api_backend._slug("https://www.linkedin.com/in/priya-sharma/") == "priya-sharma"

    def test_slug_returns_none_for_empty(self, api_backend):
        assert api_backend._slug("") is None

    def test_slug_returns_none_for_non_linkedin(self, api_backend):
        assert api_backend._slug("https://example.com/priya") is None


class TestLinkedInApiOutreachIsConnection:
    def test_distance_1_returns_true(self, api_backend, mock_api, recruiter_with_url):
        mock_api.get_profile.return_value = {
            "entityUrn": "urn:li:member:123456",
            "distance": {"value": "DISTANCE_1"},
        }
        assert api_backend.is_connection(recruiter_with_url) is True

    def test_distance_2_returns_false(self, api_backend, mock_api, recruiter_with_url):
        mock_api.get_profile.return_value = {
            "entityUrn": "urn:li:member:123456",
            "distance": {"value": "DISTANCE_2"},
        }
        assert api_backend.is_connection(recruiter_with_url) is False

    def test_no_linkedin_url_returns_false(self, api_backend, recruiter_no_url):
        assert api_backend.is_connection(recruiter_no_url) is False

    def test_api_error_returns_false(self, api_backend, mock_api, recruiter_with_url):
        mock_api.get_profile.side_effect = RuntimeError("network error")
        assert api_backend.is_connection(recruiter_with_url) is False


class TestLinkedInApiOutreachSendDM:
    def test_dm_sent_to_correct_urn(self, api_backend, mock_api, recruiter_with_url):
        mock_api.get_profile.return_value = {"entityUrn": "urn:li:member:999"}
        result = api_backend.send_dm(recruiter_with_url, subject="Referral", body="Hi Priya!")
        mock_api.send_message.assert_called_once_with("Hi Priya!", recipients=["urn:li:member:999"])
        assert result.success is True
        assert result.action == "dm"

    def test_dm_fails_without_url(self, api_backend, mock_api, recruiter_no_url):
        result = api_backend.send_dm(recruiter_no_url, subject="Test", body="Hi!")
        mock_api.send_message.assert_not_called()
        assert result.success is False
        assert "no_linkedin_url" in result.error

    def test_dm_fails_when_no_urn_in_profile(self, api_backend, mock_api, recruiter_with_url):
        mock_api.get_profile.return_value = {}  # no entityUrn
        result = api_backend.send_dm(recruiter_with_url, subject="Test", body="Hi!")
        mock_api.send_message.assert_not_called()
        assert result.success is False

    def test_dm_fails_on_api_error(self, api_backend, mock_api, recruiter_with_url):
        mock_api.get_profile.return_value = {"entityUrn": "urn:li:member:123"}
        mock_api.send_message.side_effect = RuntimeError("rate limited")
        result = api_backend.send_dm(recruiter_with_url, subject="Test", body="Hi!")
        assert result.success is False
        assert "rate limited" in result.error


class TestLinkedInApiOutreachConnectionRequest:
    def test_invite_sent_with_correct_slug(self, api_backend, mock_api, recruiter_with_url):
        result = api_backend.send_connection_request(recruiter_with_url, note="Hi! Let's connect.")
        mock_api.add_connection.assert_called_once_with(
            profile_public_id="priya-sharma-abc",
            message="Hi! Let's connect.",
        )
        assert result.success is True
        assert result.action == "invite"

    def test_note_truncated_to_300_chars(self, api_backend, mock_api, recruiter_with_url):
        long_note = "x" * 500
        api_backend.send_connection_request(recruiter_with_url, note=long_note)
        _, kwargs = mock_api.add_connection.call_args
        assert len(kwargs["message"]) == 300

    def test_invite_fails_without_url(self, api_backend, mock_api, recruiter_no_url):
        result = api_backend.send_connection_request(recruiter_no_url, note="Hi!")
        mock_api.add_connection.assert_not_called()
        assert result.success is False

    def test_invite_fails_on_api_error(self, api_backend, mock_api, recruiter_with_url):
        mock_api.add_connection.side_effect = RuntimeError("blocked")
        result = api_backend.send_connection_request(recruiter_with_url, note="Hi!")
        assert result.success is False
        assert "blocked" in result.error


class TestLinkedInApiOutreachFindPeople:
    def test_delegates_to_finder(self, api_backend, mock_finder):
        people = api_backend.find_company_people("Stripe", max_results=3)
        mock_finder.find.assert_called_once_with("Stripe", max_results=3)
        assert len(people) == 1

    def test_factory_linkedin_api_with_injected_api(self):
        mock = MagicMock()
        backend = LinkedInApiOutreach(_api=mock)
        assert isinstance(backend, LinkedInApiOutreach)

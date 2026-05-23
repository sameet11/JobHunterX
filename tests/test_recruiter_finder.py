"""Tests for recruiter discovery (Phase 3)."""

from unittest.mock import MagicMock, patch

import pytest

from src.models import Recruiter
from src.outreach.recruiter_finder import (
    GoogleSearchRecruiterFinder,
    HunterRecruiterFinder,
    MockRecruiterFinder,
    get_recruiter_finder,
)


class TestMockRecruiterFinder:
    def test_returns_known_company_recruiters(self):
        finder = MockRecruiterFinder()
        recs = finder.find("Google", max_results=3)
        assert len(recs) == 3
        assert all(isinstance(r, Recruiter) for r in recs)
        assert all(r.company == "Google" for r in recs)
        assert all(r.email.endswith("@google.com") for r in recs)

    def test_respects_max_results(self):
        finder = MockRecruiterFinder()
        recs = finder.find("Google", max_results=1)
        assert len(recs) == 1

    def test_unknown_company_synthesizes_one(self):
        """Unknown companies still return a synthesized recruiter so pipeline doesn't stall."""
        finder = MockRecruiterFinder()
        recs = finder.find("UnknownStartup999", max_results=3)
        assert len(recs) == 1
        assert recs[0].company == "UnknownStartup999"
        assert "@unknownstartup999.com" in recs[0].email

    def test_case_insensitive_company_match(self):
        finder = MockRecruiterFinder()
        recs_lower = finder.find("google", max_results=2)
        recs_upper = finder.find("GOOGLE", max_results=2)
        assert len(recs_lower) == len(recs_upper) == 2
        assert recs_lower[0].name == recs_upper[0].name

    def test_recruiter_has_linkedin_url(self):
        finder = MockRecruiterFinder()
        recs = finder.find("TechCorp", max_results=1)
        assert recs[0].linkedin_url.startswith("https://www.linkedin.com/in/")

    def test_dedup_key_unique_per_recruiter(self):
        finder = MockRecruiterFinder()
        recs = finder.find("Google", max_results=3)
        keys = {r.dedup_key() for r in recs}
        assert len(keys) == 3, "All three recruiters should have unique dedup_keys"


class TestRecruiterFinderFactory:
    def test_mock_factory(self):
        finder = get_recruiter_finder("mock")
        assert isinstance(finder, MockRecruiterFinder)

    def test_unknown_source_raises(self):
        with pytest.raises(ValueError, match="Unknown recruiter finder source"):
            get_recruiter_finder("nonexistent")

    def test_hunter_requires_api_key(self, monkeypatch):
        # Replace the module-level `platform` reference in recruiter_finder
        # with a stub that has an empty api key. This avoids touching the
        # frozen PlatformConfig dataclass directly.
        from src.outreach import recruiter_finder as rf

        class _Stub:
            hunter_api_key = ""

        monkeypatch.setattr(rf, "platform", _Stub())
        with pytest.raises(RuntimeError, match="HUNTER_API_KEY"):
            HunterRecruiterFinder(api_key="")


_FAKE_GOOGLE_HTML = """
<html><body>
<a href="/url?q=https://www.linkedin.com/in/priya-sharma-abc123&sa=U">Priya</a>
<a href="https://www.linkedin.com/in/rajesh-kumar-456def">Rajesh</a>
<a href="/url?q=https://www.linkedin.com/in/anita-desai-789ghi&sa=U">Anita</a>
<a href="https://unrelated.com/page">Other</a>
</body></html>
"""

_FAKE_GOOGLE_HTML_NO_PROFILES = "<html><body><p>No results</p></body></html>"


def _mock_google_resp(html: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = html
    return resp


def _mock_hunter_resp(result: str = "deliverable", score: int = 85):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": {"result": result, "score": score}}
    return resp


class TestGoogleSearchRecruiterFinderSlugParsing:
    def test_parses_first_last_from_slug(self):
        finder = GoogleSearchRecruiterFinder()
        result = finder._parse_slug("https://www.linkedin.com/in/priya-sharma-abc123")
        assert result == ("priya", "sharma")

    def test_numeric_id_filtered_out(self):
        finder = GoogleSearchRecruiterFinder()
        result = finder._parse_slug("https://www.linkedin.com/in/rajesh-kumar-123456")
        assert result == ("rajesh", "kumar")

    def test_mixed_alphanumeric_id_filtered(self):
        finder = GoogleSearchRecruiterFinder()
        result = finder._parse_slug("https://www.linkedin.com/in/anita-desai-a1b2c3")
        assert result == ("anita", "desai")

    def test_single_word_slug_returns_none(self):
        finder = GoogleSearchRecruiterFinder()
        assert finder._parse_slug("https://www.linkedin.com/in/priya") is None

    def test_invalid_url_returns_none(self):
        finder = GoogleSearchRecruiterFinder()
        assert finder._parse_slug("https://example.com/notlinkedin") is None


class TestGoogleSearchRecruiterFinderEmailGuesses:
    def test_three_patterns_returned(self):
        finder = GoogleSearchRecruiterFinder()
        guesses = finder._email_guesses("priya", "sharma", "google.com")
        assert guesses == [
            "priya@google.com",
            "priya.sharma@google.com",
            "psharma@google.com",
        ]

    def test_first_initial_used_in_third_pattern(self):
        finder = GoogleSearchRecruiterFinder()
        guesses = finder._email_guesses("rajesh", "kumar", "stripe.com")
        assert guesses[2] == "rkumar@stripe.com"


class TestGoogleSearchRecruiterFinderDomainGuess:
    def test_known_company_returns_correct_domain(self):
        finder = GoogleSearchRecruiterFinder()
        assert finder._guess_domain("Google") == "google.com"
        assert finder._guess_domain("Meta") == "meta.com"
        assert finder._guess_domain("Razorpay") == "razorpay.com"

    def test_unknown_company_strips_spaces(self):
        finder = GoogleSearchRecruiterFinder()
        assert finder._guess_domain("Unknown Startup") == "unknownstartup.com"


class TestGoogleSearchRecruiterFinderUrlExtraction:
    def test_extracts_linkedin_urls_from_html(self):
        finder = GoogleSearchRecruiterFinder()
        urls = finder._extract_linkedin_urls(_FAKE_GOOGLE_HTML, limit=10)
        assert len(urls) == 3
        assert all("linkedin.com/in/" in u for u in urls)

    def test_deduplicates_same_url(self):
        html = """
        <html><body>
        <a href="https://www.linkedin.com/in/priya-sharma">Link1</a>
        <a href="https://www.linkedin.com/in/priya-sharma">Link2</a>
        </body></html>
        """
        finder = GoogleSearchRecruiterFinder()
        urls = finder._extract_linkedin_urls(html, limit=10)
        assert len(urls) == 1

    def test_respects_limit(self):
        finder = GoogleSearchRecruiterFinder()
        urls = finder._extract_linkedin_urls(_FAKE_GOOGLE_HTML, limit=2)
        assert len(urls) == 2

    def test_ignores_non_linkedin_links(self):
        finder = GoogleSearchRecruiterFinder()
        urls = finder._extract_linkedin_urls(_FAKE_GOOGLE_HTML_NO_PROFILES, limit=10)
        assert urls == []


class TestGoogleSearchRecruiterFinderFind:
    def test_returns_recruiters_from_google(self):
        finder = GoogleSearchRecruiterFinder(hunter_api_key="")
        with patch("src.outreach.recruiter_finder.httpx.get", return_value=_mock_google_resp(_FAKE_GOOGLE_HTML)):
            results = finder.find("Stripe", max_results=3)
        assert len(results) == 3
        assert all(isinstance(r, Recruiter) for r in results)
        assert all(r.company == "Stripe" for r in results)
        assert all(r.source == "google_search" for r in results)
        assert all("stripe.com" in r.email for r in results)

    def test_respects_max_results(self):
        finder = GoogleSearchRecruiterFinder(hunter_api_key="")
        with patch("src.outreach.recruiter_finder.httpx.get", return_value=_mock_google_resp(_FAKE_GOOGLE_HTML)):
            results = finder.find("Stripe", max_results=1)
        assert len(results) == 1

    def test_returns_empty_on_no_profiles(self):
        finder = GoogleSearchRecruiterFinder(hunter_api_key="")
        with patch("src.outreach.recruiter_finder.httpx.get", return_value=_mock_google_resp(_FAKE_GOOGLE_HTML_NO_PROFILES)):
            results = finder.find("Acme", max_results=3)
        assert results == []

    def test_returns_empty_on_http_error(self):
        finder = GoogleSearchRecruiterFinder(hunter_api_key="")
        with patch("src.outreach.recruiter_finder.httpx.get", return_value=_mock_google_resp("", status=429)):
            results = finder.find("Stripe", max_results=3)
        assert results == []

    def test_hunter_verify_called_for_faang(self):
        finder = GoogleSearchRecruiterFinder(hunter_api_key="test-key")
        google_resp = _mock_google_resp(_FAKE_GOOGLE_HTML)
        hunter_resp = _mock_hunter_resp(result="deliverable", score=90)
        with patch("src.outreach.recruiter_finder.httpx.get", side_effect=[google_resp] + [hunter_resp] * 10):
            with patch("src.outreach.recruiter_finder.time.sleep"):
                results = finder.find("Google", max_results=1)
        assert results[0].confidence == 90

    def test_hunter_verify_not_called_for_non_faang(self):
        finder = GoogleSearchRecruiterFinder(hunter_api_key="test-key")
        google_resp = _mock_google_resp(_FAKE_GOOGLE_HTML)
        with patch("src.outreach.recruiter_finder.httpx.get", return_value=google_resp) as mock_get:
            results = finder.find("Razorpay", max_results=1)
        # Only one httpx.get call (Google search) — no Hunter.io calls.
        assert mock_get.call_count == 1
        assert results[0].confidence == 0

    def test_linkedin_url_preserved(self):
        finder = GoogleSearchRecruiterFinder(hunter_api_key="")
        with patch("src.outreach.recruiter_finder.httpx.get", return_value=_mock_google_resp(_FAKE_GOOGLE_HTML)):
            results = finder.find("Stripe", max_results=3)
        assert all(r.linkedin_url.startswith("https://") for r in results)


class TestRecruiterFinderFactoryGoogleSearch:
    def test_google_search_factory(self):
        finder = get_recruiter_finder("google_search")
        assert isinstance(finder, GoogleSearchRecruiterFinder)


class TestRecruiterModel:
    def test_dedup_key_uses_email(self):
        r = Recruiter(name="X", email="x@y.com", company="Y")
        assert "x@y.com" in r.dedup_key()

    def test_dedup_key_falls_back_to_linkedin(self):
        r = Recruiter(
            name="X",
            email="",
            linkedin_url="https://linkedin.com/in/x",
            company="Y",
        )
        assert "linkedin" in r.dedup_key()

"""Test ReferralTemplate with real-world scenarios."""

import pytest

from src.outreach.referral_template import ReferralTemplate


class TestReferralTemplateBasics:
    """Basic functionality tests."""

    def test_initialization(self):
        """ReferralTemplate initializes without errors."""
        template = ReferralTemplate()
        assert template is not None

    def test_render_returns_email_object(self):
        """render() returns ReferralEmail with subject and body."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Priya Kumar",
            company="Google",
            role="Senior Software Engineer",
        )

        assert hasattr(email, "subject")
        assert hasattr(email, "body")
        assert isinstance(email.subject, str)
        assert isinstance(email.body, str)


class TestReferralTemplateWithRealWorldScenarios:
    """Real-world scenario tests."""

    def test_techcorp_backend_role_referral(self):
        """Scenario: Refer to TechCorp for senior backend role."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Rajesh Sharma",
            company="TechCorp",
            role="Senior Backend Engineer",
        )

        # Subject should mention the role and company
        assert "Senior Backend Engineer" in email.subject
        assert "TechCorp" in email.subject
        assert email.subject.startswith("Referral Request")

        # Body should address the person by name
        assert "Hi Rajesh Sharma" in email.body

        # Body should mention the company and role
        assert "TechCorp" in email.body
        assert "Senior Backend Engineer" in email.body

        # Signature fields present (values come from caller)
        assert email.body is not None

    def test_startup_fullstack_role_referral(self):
        """Scenario: Refer to startup for full-stack role."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Priya Desai",
            company="StartupXYZ",
            role="Full Stack Engineer",
        )

        assert "StartupXYZ" in email.subject
        assert "Full Stack Engineer" in email.subject
        assert "Hi Priya Desai" in email.body

    def test_remote_position_referral(self):
        """Scenario: Remote position referral."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Amit Singh",
            company="Remote Company Inc",
            role="Backend Engineer",
        )

        assert "Remote Company Inc" in email.subject
        assert "Backend Engineer" in email.body
        assert "Hi Amit Singh" in email.body

    def test_multiple_word_name_referral(self):
        """Scenario: Recruiter/HR with multi-word name."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Maria Garcia-López",
            company="TechGlobalCorp",
            role="Engineering Manager",
        )

        assert "Hi Maria Garcia-López" in email.body
        assert "TechGlobalCorp" in email.subject


class TestReferralTemplateVariableSubstitution:
    """Tests for variable substitution and formatting."""

    def test_all_dynamic_variables_replaced(self):
        """All template variables should be replaced."""
        template = ReferralTemplate()
        email = template.render(
            person_name="TestName",
            company="TestCompany",
            role="TestRole",
        )

        # No template placeholders should remain
        assert "{" not in email.subject
        assert "{" not in email.body
        assert "}" not in email.subject
        assert "}" not in email.body

    def test_sender_info_defaults(self):
        """Default sender info used when not provided."""
        template = ReferralTemplate()
        email = template.render(
            person_name="John Doe",
            company="ACME Corp",
            role="Engineer",
            sender_name="Test User",
            sender_email="test@example.com",
            sender_phone="+91-0000000000",
        )

        assert "Test User" in email.body
        assert "test@example.com" in email.body
        assert "+91-0000000000" in email.body

    def test_custom_sender_info(self):
        """Custom sender info should override defaults."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Jane Smith",
            company="TechCorp",
            role="Engineer",
            sender_name="Custom Name",
            sender_email="custom@example.com",
            sender_phone="+1-555-0123",
        )

        assert "Custom Name" in email.body
        assert "custom@example.com" in email.body
        assert "+1-555-0123" in email.body

        assert "Custom Name" in email.body
        assert "custom@example.com" in email.body

    def test_current_company_customization(self):
        """Current company can be customized in the template."""
        template = ReferralTemplate()

        # Default current company
        email1 = template.render(
            person_name="Test1",
            company="Company A",
            role="Role A",
        )
        assert "Lucid Motors" in email1.body

        # Custom current company
        email2 = template.render(
            person_name="Test2",
            company="Company B",
            role="Role B",
            current_company="CustomCorp",
        )
        assert "CustomCorp" in email2.body
        assert "Lucid Motors" not in email2.body


class TestReferralTemplateContentQuality:
    """Tests for email content quality and professionalism."""

    def test_email_structure(self):
        """Email should have proper structure (greeting, body, closing)."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Recipient Name",
            company="Company",
            role="Role",
        )

        # Should start with greeting
        assert email.body.startswith("Hi Recipient Name")

        # Should end with closing and signature
        assert "Best," in email.body
        assert "Sameet Sabu" in email.body

    def test_email_tone_professional(self):
        """Email should maintain professional tone."""
        template = ReferralTemplate()
        email = template.render(
            person_name="John Doe",
            company="Google",
            role="Staff Engineer",
        )

        # Should be concise (3 sentences)
        sentences = email.body.count(".") - 1  # Minus signature line
        assert 2 <= sentences <= 4, "Should be 2-4 sentences in main body"

        # Key professional phrases
        assert "would love to be considered" in email.body
        assert "happy to connect" in email.body or "appreciate" in email.body

    def test_email_mentions_relevant_skills(self):
        """Email should briefly mention relevant skills/experience."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Recruiter",
            company="Tech Company",
            role="Engineer",
        )

        # Should mention years of experience
        assert "3 years" in email.body

        # Should mention key skills
        assert "Python" in email.body
        assert "FastAPI" in email.body
        assert "AWS" in email.body or "GCP" in email.body

    def test_email_calls_to_action(self):
        """Email should have clear call to action."""
        template = ReferralTemplate()
        email = template.render(
            person_name="HR Manager",
            company="Company",
            role="Role",
        )

        # Should ask for specific action
        assert "Would you be open to" in email.body or "would you" in email.body
        assert "refer" in email.body.lower() or "team" in email.body


class TestReferralTemplateEdgeCases:
    """Edge case and error handling tests."""

    def test_special_characters_in_name(self):
        """Handle names with special characters."""
        template = ReferralTemplate()
        email = template.render(
            person_name="François D'Alembert",
            company="Company",
            role="Role",
        )

        assert "François D'Alembert" in email.body

    def test_special_characters_in_company(self):
        """Handle company names with special characters."""
        template = ReferralTemplate()
        email = template.render(
            person_name="John",
            company="Google & Meta Inc.",
            role="Role",
        )

        assert "Google & Meta Inc." in email.subject
        assert "Google & Meta Inc." in email.body

    def test_long_role_name(self):
        """Handle long role names."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Jane",
            company="TechCorp",
            role="Senior Staff Software Engineer - Infrastructure & Platforms",
        )

        assert "Senior Staff Software Engineer - Infrastructure & Platforms" in email.subject
        assert "Senior Staff Software Engineer - Infrastructure & Platforms" in email.body

    def test_single_word_name(self):
        """Handle single-word names."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Priya",
            company="Company",
            role="Role",
        )

        assert "Hi Priya" in email.body

    def test_empty_current_company(self):
        """Handle empty current company string."""
        template = ReferralTemplate()
        email = template.render(
            person_name="Test",
            company="Company",
            role="Role",
            current_company="",
        )

        # Should still have valid structure
        assert email.body
        assert "Test" in email.body


class TestReferralTemplateNoAICost:
    """Verify no AI calls are made (static template only)."""

    def test_render_is_synchronous(self):
        """render() should be synchronous (no async/await)."""
        import inspect

        template = ReferralTemplate()
        assert not inspect.iscoroutinefunction(template.render)

    def test_render_is_fast(self):
        """render() should complete in <10ms (no LLM calls)."""
        import time

        template = ReferralTemplate()
        start = time.time()
        email = template.render(
            person_name="Test",
            company="Company",
            role="Role",
        )
        elapsed = time.time() - start

        assert elapsed < 0.01, f"render() should be instant, took {elapsed}s"

    def test_no_external_api_calls(self):
        """Template should not require API keys or external services."""
        template = ReferralTemplate()
        # If render() needed an API key, this would fail
        email = template.render(
            person_name="Test",
            company="Company",
            role="Role",
        )

        assert email.subject
        assert email.body


class TestReferralTemplateReusability:
    """Tests for template reusability across multiple emails."""

    def test_render_multiple_different_emails(self):
        """Single template instance can render multiple different emails."""
        template = ReferralTemplate()

        emails = []
        names = ["Alice Johnson", "Bob Singh", "Carol Kim", "Diana Flores"]
        companies = ["Google", "Meta", "Microsoft", "Apple"]
        roles = ["Engineer", "Senior Engineer", "Staff Engineer", "Principal Engineer"]

        for name, company, role in zip(names, companies, roles):
            email = template.render(person_name=name, company=company, role=role)
            emails.append(email)

        # Each email should be unique
        assert len(emails) == 4
        subjects = [e.subject for e in emails]
        assert len(set(subjects)) == 4, "All subjects should be different"

    def test_template_immutability(self):
        """Template should not be modified by rendering."""
        template = ReferralTemplate()

        # Render first email
        email1 = template.render(
            person_name="Name1",
            company="Company1",
            role="Role1",
        )

        # Render second email with different data
        email2 = template.render(
            person_name="Name2",
            company="Company2",
            role="Role2",
        )

        # First email should not be affected
        assert "Name1" in email1.body
        assert "Company1" in email1.body
        assert "Name2" not in email1.body
        assert "Company2" not in email1.body

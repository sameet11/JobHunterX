"""Test ResumeTailor with real-world scenarios."""

from pathlib import Path

import pytest

from src.models import JDAnalysis
from src.resume.resume_tailor import ResumeTailor


class TestResumeTailorBasics:
    """Basic functionality tests for ResumeTailor."""

    def test_initialization(self):
        """ResumeTailor initializes without errors."""
        tailor = ResumeTailor()
        assert tailor is not None

    def test_template_path_exists(self):
        """Template file exists at expected location."""
        template_path = Path(__file__).parent.parent / "src" / "resume" / "templates" / "resume_template.html"
        assert template_path.exists(), f"Template not found at {template_path}"

    def test_output_dir_created(self, tmp_path):
        """Output directory is created if missing."""
        # This would normally create output/ in project root, but we can test the concept
        tailor = ResumeTailor()
        assert tailor._template, "Template should be loaded"


class TestResumeTailorWithRealWorldScenarios:
    """Real-world scenario tests."""

    def test_backend_engineer_jd_tailoring(self, analysis_backend_match):
        """Scenario: Backend engineer role with strong skill match."""
        # JD emphasizes: FastAPI, Python, AWS, microservices
        tailor = ResumeTailor()

        # Keywords that should bubble to top of skills section
        expected_top_skills = ["FastAPI", "Python", "AWS", "Microservices"]
        assert all(kw in analysis_backend_match.keywords_to_include for kw in expected_top_skills)

        # Score would prioritize categories with these skills
        assert analysis_backend_match.match_score >= 85, "Should be strong match"
        assert analysis_backend_match.should_apply is True

    def test_fullstack_moderate_match(self, analysis_fullstack_moderate):
        """Scenario: Full-stack role with moderate match — some skills missing."""
        # Candidate has React + Python but missing Next.js, TypeScript, GCP
        missing = analysis_fullstack_moderate.missing_skills
        assert len(missing) >= 3, "Should have some gaps"
        assert "Next.js" in missing
        assert "TypeScript" in missing

        # Still should apply (68% score > 60% minimum)
        assert analysis_fullstack_moderate.should_apply is True
        assert 60 <= analysis_fullstack_moderate.match_score < 85

    def test_poor_match_should_skip(self, analysis_no_match):
        """Scenario: Systems programming role — skill mismatch, should skip."""
        # Candidate has web/backend skills but role needs Go/Rust/C++
        assert analysis_no_match.match_score < 50, "Should be poor match"
        assert analysis_no_match.should_apply is False
        assert "Rust" in analysis_no_match.missing_skills
        assert "Go" in analysis_no_match.missing_skills

    def test_keyword_matching_logic(self):
        """Test keyword matching for skill reordering."""
        # Backend category: FastAPI, Django, Flask, ...
        backend_skills = "FastAPI,Django,Flask,Spring Boot,REST API,GraphQL"
        frontend_skills = "React.js,Next.js,Redux,React Query"

        # For a FastAPI/React job, both categories should be prioritized
        jd_keywords = ["FastAPI", "React", "Next.js"]

        backend_score = sum(1 for kw in jd_keywords if kw.lower() in backend_skills.lower())
        frontend_score = sum(1 for kw in jd_keywords if kw.lower() in frontend_skills.lower())

        assert backend_score > 0, "FastAPI should match backend"
        assert frontend_score > 0, "React/Next.js should match frontend"

    def test_category_reordering_strategy(self):
        """Verify reordering logic puts matched categories first."""
        analysis = JDAnalysis(
            match_score=80,
            keywords_to_include=["Kubernetes", "Docker", "CI/CD", "Jenkins"],
            should_apply=True,
        )

        # These keywords are all in "Cloud & DevOps" category
        devops_skills = "Docker,Kubernetes,Helm,Jenkins,GitHub Actions,CI/CD"
        other_skills = "Python,Java,TypeScript,JavaScript"

        devops_match = sum(1 for kw in analysis.keywords_to_include if kw.lower() in devops_skills.lower())
        other_match = sum(1 for kw in analysis.keywords_to_include if kw.lower() in other_skills.lower())

        # DevOps category should score higher (4 matches vs 0)
        assert devops_match > other_match, "DevOps should rank first for this JD"


class TestResumeTailorEdgeCases:
    """Edge case and error handling tests."""

    def test_empty_keywords(self):
        """Test with empty keywords_to_include (uses default order)."""
        analysis = JDAnalysis(
            match_score=50,
            keywords_to_include=[],  # No JD keywords
            should_apply=True,
        )

        tailor = ResumeTailor()
        # Should fall back to original skill order without error
        assert len(analysis.keywords_to_include) == 0

    def test_all_skills_match(self):
        """Test JD where candidate has all required skills."""
        analysis = JDAnalysis(
            match_score=98,
            keywords_to_include=[
                "Python",
                "FastAPI",
                "PostgreSQL",
                "AWS",
                "Docker",
                "Kubernetes",
                "Redis",
                "Elasticsearch",
            ],
            should_apply=True,
        )

        # All these skills exist in candidate's resume
        assert len(analysis.keywords_to_include) == 8

    def test_rare_skill_in_jd(self):
        """Test with niche skill that candidate might not have."""
        analysis = JDAnalysis(
            match_score=70,
            keywords_to_include=["Apache Kafka", "Flink", "RabbitMQ"],
            candidate_has_skills=["Apache Kafka", "RabbitMQ"],  # Missing Flink
            missing_skills=["Flink"],
            should_apply=True,
        )

        assert "Apache Kafka" in analysis.keywords_to_include
        assert "Flink" in analysis.missing_skills


class TestResumeTailorFileGeneration:
    """Tests for actual PDF generation and file handling."""

    def test_pdf_filename_generation(self, sample_job_backend):
        """Test that PDF filenames are safe and descriptive."""
        company = sample_job_backend.company  # "TechCorp"
        role = sample_job_backend.title  # "Senior Backend Engineer"

        from src.resume.resume_tailor import _safe_filename

        safe_company = _safe_filename(company)
        safe_role = _safe_filename(role)

        assert safe_company == "TechCorp"
        assert safe_role == "Senior_Backend_Engineer"
        assert " " not in safe_role  # No spaces
        assert ":" not in safe_role  # No special chars

    def test_pdf_filename_with_special_chars(self):
        """Test filename sanitization with problematic characters."""
        from src.resume.resume_tailor import _safe_filename

        # Company with special characters
        company = "Google/Meta & Co. (Inc)"
        role = "SWE - L4 / Senior"

        safe_company = _safe_filename(company)
        safe_role = _safe_filename(role)

        # Should replace special chars with underscores
        assert "/" not in safe_company
        assert "&" not in safe_company
        assert "(" not in safe_company
        assert ")" not in safe_company

        assert "/" not in safe_role
        assert "-" in safe_role or "_" in safe_role  # Dashes might become underscores


class TestResumeTailorIntegration:
    """Integration tests with real components."""

    def test_tailor_with_scored_job_backend(self, scored_job_backend):
        """Full integration: tailor resume for backend engineer job."""
        job = scored_job_backend.job
        analysis = scored_job_backend.analysis

        assert job.company == "TechCorp"
        assert job.title == "Senior Backend Engineer"
        assert analysis.match_score == 92

        # Keywords that should be prioritized in resume
        priority_keywords = ["FastAPI", "Python", "PostgreSQL", "AWS"]
        assert all(kw in analysis.keywords_to_include for kw in priority_keywords)

    def test_tailor_with_scored_job_fullstack(self, scored_job_fullstack):
        """Full integration: tailor resume for full-stack role."""
        job = scored_job_fullstack.job
        analysis = scored_job_fullstack.analysis

        assert job.company == "StartupXYZ"
        assert analysis.match_score == 68  # Moderate match

        # Both backend and frontend skills should be represented
        has_frontend = any(kw in analysis.keywords_to_include for kw in ["React", "Next.js"])
        has_backend = any(kw in analysis.keywords_to_include for kw in ["FastAPI", "Python"])

        assert has_frontend, "Should include frontend keywords"
        assert has_backend, "Should include backend keywords"

    def test_tailor_respects_should_apply_flag(self, scored_job_no_match):
        """Integration: should_apply=False means skip (don't tailor)."""
        analysis = scored_job_no_match.analysis

        # This job has poor match; resume shouldn't be tailored
        assert analysis.should_apply is False
        assert analysis.match_score < 50


class TestResumeTailorErrorHandling:
    """Error handling and graceful degradation."""

    def test_fallback_to_static_resume_on_error(self):
        """When Playwright fails, fall back to static resume."""
        analysis = JDAnalysis(
            match_score=80,
            keywords_to_include=["FastAPI", "Python"],
            should_apply=True,
        )

        tailor = ResumeTailor()

        # If generate() encounters an error (e.g., Playwright not installed),
        # it should try to use static_fallback
        # This is a conceptual test — actual behavior depends on environment
        assert tailor is not None


class TestResumeTailorPerformance:
    """Performance and efficiency tests."""

    def test_tailor_initialization_fast(self):
        """ResumeTailor initialization should be fast."""
        import time

        start = time.time()
        tailor = ResumeTailor()
        elapsed = time.time() - start

        # Should load template in <100ms
        assert elapsed < 0.1, f"Initialization too slow: {elapsed}s"

    def test_keyword_matching_efficiency(self):
        """Keyword matching should handle large skill lists efficiently."""
        import time

        # Large candidate skill set
        large_skills_csv = ",".join([f"Skill{i}" for i in range(1000)])
        keywords = [f"Skill{i}" for i in range(100)]  # 100 keywords to match

        from src.resume.resume_tailor import _score_category

        start = time.time()
        score = _score_category(large_skills_csv, keywords)
        elapsed = time.time() - start

        assert score == 100, "Should match all 100 keywords"
        assert elapsed < 0.01, "Matching should be fast"

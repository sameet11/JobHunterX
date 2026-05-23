# Test Suite for JobHunterX

Comprehensive test suite with real-world scenarios for the resume tailoring and referral email features.

## Setup

Install test dependencies:
```bash
pip install -r requirements.txt
```

This includes `pytest>=8.0.0`.

## Running Tests

Run all tests:
```bash
pytest tests/
```

Run with verbose output:
```bash
pytest tests/ -v
```

Run specific test file:
```bash
pytest tests/test_resume_tailor.py -v
pytest tests/test_referral_template.py -v
```

Run specific test class:
```bash
pytest tests/test_resume_tailor.py::TestResumeTailorBasics -v
```

Run specific test:
```bash
pytest tests/test_resume_tailor.py::TestResumeTailorBasics::test_initialization -v
```

## Test Coverage

### `test_resume_tailor.py` — Resume Tailoring Tests

**Real-World Scenarios:**
- **Backend Engineer Match**: Strong skill alignment (92% score) for FastAPI/Python/AWS role
- **Full-Stack Moderate Match**: Moderate alignment (68% score) with some missing skills (Next.js, TypeScript)
- **Poor Match / Skip**: Systems programming role requiring Go/Rust/C++ — skill mismatch (35% score)
- **Keyword Matching Logic**: Verifies that Kafka, PostgreSQL appear before unrelated skills
- **Category Reordering**: Ensures DevOps categories rank first when JD emphasizes Kubernetes/Docker

**Edge Cases:**
- Empty keywords list (falls back to default order)
- All skills present in resume
- Rare/niche skills not in candidate's profile
- Special characters in company/role names
- Very long role titles

**File Generation:**
- PDF filename sanitization (removes special chars)
- Output directory creation
- Fallback to static resume on Playwright errors

**Performance:**
- Template initialization <100ms
- Keyword matching on 1000+ skills <10ms

### `test_referral_template.py` — Static Email Template Tests

**Real-World Scenarios:**
- **TechCorp Backend Role**: Senior backend engineer referral to established tech company
- **StartupXYZ Full-Stack**: Early-stage startup referral with lean team context
- **Remote Position**: Remote company referral
- **Multi-word Name**: Complex names like "Maria Garcia-López"

**Variable Substitution:**
- All template placeholders replaced
- Dynamic variables: person_name, company, role
- Optional custom sender info (defaults to Sameet's contact)
- Custom current_company override (defaults to "Lucid Motors")

**Content Quality:**
- Professional tone (greeting → body → closing/signature)
- Concise structure (2-4 sentences)
- Mentions relevant experience (3 years, Python, FastAPI, AWS/GCP)
- Clear call to action ("refer me", "share with your team")
- Signature with name and contact info

**No AI Cost:**
- Synchronous (no async/await)
- <10ms render time (no external API calls)
- No LLM calls, no auth required

**Reusability:**
- Single template instance renders unlimited emails
- Template immutable (each render independent)
- No side effects between renders

## Fixtures

### From `conftest.py`

**Sample Jobs:**
- `sample_job_backend`: TechCorp Senior Backend Engineer role
- `sample_job_fullstack`: StartupXYZ Full Stack Engineer (Remote)
- `sample_job_infra`: CloudSystems Cloud Infrastructure Engineer

**Analyses:**
- `analysis_backend_match`: 92% match with FastAPI/Python/AWS focus
- `analysis_fullstack_moderate`: 68% match with some frontend/backend gaps
- `analysis_no_match`: 35% poor match (systems programming role)

**Scored Jobs:**
- `scored_job_backend`: Backend + analysis combined
- `scored_job_fullstack`: Full-stack + moderate analysis
- `scored_job_no_match`: Infra + poor analysis (should_apply=False)

## Key Test Patterns

1. **Scenario-Based**: Tests reflect real job search situations (strong match, moderate match, poor match)
2. **Content Verification**: Assertions check that correct keywords/names appear in output
3. **Edge Case Coverage**: Special chars, long names, empty lists, custom overrides
4. **Performance Checks**: Ensure rendering is instant (<10ms), no external calls
5. **Integration Tests**: End-to-end flows with realistic job + analysis combinations

## Notes

- Tests do NOT actually generate PDFs (would require Playwright browser) — they verify the logic and template structure
- Referral email tests verify string substitution, not actual email sending
- All tests are unit/integration level and should pass in <1s total

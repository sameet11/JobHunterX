-- JobHunterX PostgreSQL Schema Initialization

-- Jobs table (Phase 1-2)
CREATE TABLE IF NOT EXISTS jobs (
    dedup_key TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    salary TEXT,
    apply_url TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'Scraped',
    match_score INTEGER DEFAULT 0,
    first_seen TIMESTAMP NOT NULL,
    last_updated TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(company, title);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);

-- Outreach table (Phase 3)
CREATE TABLE IF NOT EXISTS outreach (
    dedup_key TEXT PRIMARY KEY,
    job_dedup_key TEXT NOT NULL REFERENCES jobs(dedup_key) ON DELETE CASCADE,
    recruiter_name TEXT NOT NULL,
    recruiter_email TEXT,
    recruiter_title TEXT,
    recruiter_company TEXT NOT NULL,
    recruiter_source TEXT,
    recruiter_linkedin_url TEXT,
    channel TEXT NOT NULL,
    style TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    status TEXT NOT NULL,
    message_id TEXT,
    error TEXT,
    sent_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    last_updated TIMESTAMP NOT NULL,
    created_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outreach_company ON outreach(recruiter_company);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);
CREATE INDEX IF NOT EXISTS idx_outreach_job ON outreach(job_dedup_key);
CREATE INDEX IF NOT EXISTS idx_outreach_email ON outreach(recruiter_email);
CREATE INDEX IF NOT EXISTS idx_outreach_sent_at ON outreach(sent_at);

-- Applications tracking table (Phase 2)
CREATE TABLE IF NOT EXISTS applications (
    id SERIAL PRIMARY KEY,
    job_dedup_key TEXT NOT NULL REFERENCES jobs(dedup_key) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    resume_path TEXT,
    screenshot_path TEXT,
    confirmation_text TEXT,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_dedup_key);
CREATE INDEX IF NOT EXISTS idx_applications_platform ON applications(platform);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO jobhunter;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO jobhunter;

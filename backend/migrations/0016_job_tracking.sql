-- Job tracking table for monitoring scheduler runs
CREATE TABLE IF NOT EXISTS job_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type TEXT NOT NULL, -- 'daily', 'fast_cycle', 'slow_cycle', etc.
    status TEXT NOT NULL DEFAULT 'running', -- 'running', 'completed', 'failed'
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_seconds NUMERIC(10, 2),
    result JSONB, -- Job-specific result data
    error TEXT, -- Error message if status='failed'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_job_runs_type_started 
    ON job_runs(job_type, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_runs_status 
    ON job_runs(status);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_job_runs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_job_runs_updated_at
    BEFORE UPDATE ON job_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_job_runs_updated_at();

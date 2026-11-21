-- Worker Pool Database Schema Migration
-- This migration adds support for the worker pool architecture.
-- It is idempotent and can be run multiple times safely.

BEGIN;

-- 1. Create the worker_pool table to track active workers
CREATE TABLE IF NOT EXISTS worker_pool (
    worker_id TEXT PRIMARY KEY,
    status INTEGER NOT NULL DEFAULT 0,        -- 0=Idle, 1=Busy, 2=Draining, 3=Exited
    registered_at TIMESTAMP NOT NULL DEFAULT NOW(),
    heartbeat_at TIMESTAMP NOT NULL DEFAULT NOW(),
    current_job TEXT,                          -- Current job key (session_id/owner/repo), NULL if idle
    jobs_completed INTEGER NOT NULL DEFAULT 0,
    argo_pod_name TEXT NOT NULL DEFAULT ''
);

-- 2. Add worker_id column to job_info (tracks which worker claimed a job)
DO $$ BEGIN
    ALTER TABLE job_info ADD COLUMN IF NOT EXISTS worker_id TEXT NOT NULL DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- 3. Add index on job_status for fast queued/pending job lookups
--    Status values: 0=Pending, 1=InProgress, 2=Succeeded, 3=Failed, 4=Canceled, 5=TimedOut, 6=Queued
CREATE INDEX IF NOT EXISTS idx_job_status_status_queued
    ON job_status(status) WHERE status IN (0, 6);

-- 4. Add index on worker_pool for heartbeat expiry checks
CREATE INDEX IF NOT EXISTS idx_worker_pool_heartbeat
    ON worker_pool(heartbeat_at) WHERE status IN (0, 1);

COMMIT;

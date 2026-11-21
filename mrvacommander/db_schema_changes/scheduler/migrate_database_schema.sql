-- Database Schema Migration Script for MRVA Commander
-- This script adds columns and tables for the fair scheduling implementation
--
-- Changes since main branch:
--   1. Added columns to job_info table (user_id, started_at, completed_at, argo_workflow_id)
--   2. Created scheduler_lock table for leader election
--   3. Added indices for performance
--
-- This script is idempotent - it can be run multiple times safely

BEGIN;

-- ==========================================
-- 1. Extend job_info table with new columns
-- ==========================================

-- Add user_id column for tracking which user submitted each job
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'job_info' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE job_info ADD COLUMN user_id TEXT NOT NULL DEFAULT '';
        RAISE NOTICE 'Added user_id column to job_info table';
    ELSE
        RAISE NOTICE 'Column user_id already exists in job_info table';
    END IF;
END $$;

-- Add started_at timestamp for tracking when job execution begins
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'job_info' AND column_name = 'started_at'
    ) THEN
        ALTER TABLE job_info ADD COLUMN started_at TIMESTAMP;
        RAISE NOTICE 'Added started_at column to job_info table';
    ELSE
        RAISE NOTICE 'Column started_at already exists in job_info table';
    END IF;
END $$;

-- Add completed_at timestamp for tracking when job execution completes
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'job_info' AND column_name = 'completed_at'
    ) THEN
        ALTER TABLE job_info ADD COLUMN completed_at TIMESTAMP;
        RAISE NOTICE 'Added completed_at column to job_info table';
    ELSE
        RAISE NOTICE 'Column completed_at already exists in job_info table';
    END IF;
END $$;

-- Add argo_workflow_id for tracking Argo Workflows execution
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'job_info' AND column_name = 'argo_workflow_id'
    ) THEN
        ALTER TABLE job_info ADD COLUMN argo_workflow_id TEXT NOT NULL DEFAULT '';
        RAISE NOTICE 'Added argo_workflow_id column to job_info table';
    ELSE
        RAISE NOTICE 'Column argo_workflow_id already exists in job_info table';
    END IF;
END $$;

-- ==========================================
-- 2. Create indices for scheduler queries
-- ==========================================

-- Index for user-based queries and fair scheduling
CREATE INDEX IF NOT EXISTS idx_job_info_user_started 
    ON job_info(user_id, started_at);

-- Index for workflow ID lookups
CREATE INDEX IF NOT EXISTS idx_job_info_workflow 
    ON job_info(argo_workflow_id) WHERE argo_workflow_id != '';

-- ==========================================
-- 3. Create scheduler_lock table for leader election
-- ==========================================

CREATE TABLE IF NOT EXISTS scheduler_lock (
    lock_name TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    acquired_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    heartbeat_at TIMESTAMP NOT NULL
);

-- ==========================================
-- 4. Verify migration
-- ==========================================

-- Count how many job_info records exist
DO $$ 
DECLARE
    record_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO record_count FROM job_info;
    RAISE NOTICE 'Total records in job_info table: %', record_count;
END $$;

-- Show column structure of job_info
DO $$
DECLARE
    col RECORD;
BEGIN
    RAISE NOTICE 'job_info table structure:';
    FOR col IN 
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'job_info'
        ORDER BY ordinal_position
    LOOP
        RAISE NOTICE '  % - % (nullable: %, default: %)', 
            col.column_name, col.data_type, col.is_nullable, col.column_default;
    END LOOP;
END $$;

-- Show scheduler_lock table info
DO $$
DECLARE
    table_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'scheduler_lock'
    ) INTO table_exists;
    
    IF table_exists THEN
        RAISE NOTICE 'scheduler_lock table created successfully';
    ELSE
        RAISE WARNING 'scheduler_lock table was not created!';
    END IF;
END $$;

COMMIT;

-- ==========================================
-- NOTES
-- ==========================================
-- 
-- After running this migration:
-- 
-- 1. Existing data is preserved:
--    - user_id defaults to '' (empty string)
--    - started_at and completed_at are NULL for existing jobs
--    - argo_workflow_id defaults to '' (empty string)
--
-- 2. The scheduler will populate these fields for new jobs:
--    - user_id is extracted from JWT token
--    - started_at is set when job begins execution
--    - completed_at is set when job finishes
--    - argo_workflow_id is set when job is submitted to Argo
--
-- 3. The scheduler_lock table enables leader election:
--    - Multiple server instances can run safely
--    - Only one instance acts as scheduler at a time
--    - Automatic failover if leader instance fails
--
-- 4. Performance indices improve query speed:
--    - User-based queries for fair scheduling
--    - Workflow ID lookups for status updates
--
-- 5. This script is safe to run on a production database:
--    - All operations use IF NOT EXISTS
--    - No data is deleted or modified
--    - Transaction ensures atomicity
--    - Helpful NOTICE messages show what happened

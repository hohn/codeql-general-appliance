# Database Schema Changes Summary

This document describes the database schema changes introduced to support the move to Argo Workflows, with fairer scheduling.

## Overview

The fair scheduling implementation requires additional columns in the `job_info` table and a new `scheduler_lock` table for leader election. These changes enable:

1. **User tracking** - Associate each job with the user who submitted it
2. **Timing metrics** - Track when jobs start and complete
3. **Workflow tracking** - Link jobs to Argo Workflow executions
4. **Leader election** - Enable high-availability multi-instance deployment

## Schema Changes

### 1. Extensions to `job_info` Table

The `job_info` table has been extended with four new columns:

| Column Name | Type | Nullable | Default | Purpose |
|-------------|------|----------|---------|---------|
| `user_id` | TEXT | NOT NULL | `''` | User who submitted the job (from JWT) |
| `started_at` | TIMESTAMP | YES | NULL | When job execution began |
| `completed_at` | TIMESTAMP | YES | NULL | When job execution finished |
| `argo_workflow_id` | TEXT | NOT NULL | `''` | Argo Workflows identifier |

**Existing schema** (main branch as of Jan 2026):
```sql
CREATE TABLE job_info (
    session_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (session_id, owner, repo)
);
```

**New schema** (proposed changes):
```sql
CREATE TABLE job_info (
    session_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    payload JSONB NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    argo_workflow_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (session_id, owner, repo)
);

-- New indices for performance
CREATE INDEX idx_job_info_user_started 
    ON job_info(user_id, started_at);
CREATE INDEX idx_job_info_workflow 
    ON job_info(argo_workflow_id) WHERE argo_workflow_id != '';
```

### 2. New `scheduler_lock` Table

A new table for database-based leader election:

```sql
CREATE TABLE scheduler_lock (
    lock_name TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    acquired_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    heartbeat_at TIMESTAMP NOT NULL
);
```

This table enables multiple server instances to coordinate safely, ensuring only one instance acts as the scheduler at any time.

## Migration

### Option 1 - run `psql` manually for schema change

`migrate_database_schema.sql` in this directory will perform the schema change:

   ```bash
   psql "postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB" -f migrate_database_schema.sql
   ```

The values for the variables above can be taken from BPV or e.g. a webshell of a running server instance (e.g. `export | grep -i postgres`).

### Option 2 - wipe database, let fresh server deployment staffold it at startup

The application automatically creates the correct schema on first run via `SetupSchemas()`. If migration doesn't work for some reason, it should be safe enough to wipe the database and have the server build it from scratch at startup.


## Migration Script Features

The provided `migrate_database_schema.sql` script is:

- **Idempotent** - Safe to run multiple times
- **Non-destructive** - Preserves all existing data
- **Transactional** - All changes in one atomic transaction
- **Informative** - Prints NOTICE messages showing what happened
- **Verified** - Includes verification checks at the end

**What it does:**
- Adds 4 new columns to `job_info` (only if they don't exist)
- Creates 2 new indices for performance
- Creates `scheduler_lock` table (only if it doesn't exist)
- Prints verification information

**What it does NOT do:**
- Delete or modify existing data
- Drop any tables or columns
- Require downtime (can run while app is running, but restart recommended)

## Impact on Existing Data

After migration, existing data will have these values for new columns:

| Column | Existing Records | New Records |
|--------|------------------|-------------|
| `user_id` | `''` (empty) | User from JWT token |
| `started_at` | `NULL` | Timestamp when job starts |
| `completed_at` | `NULL` | Timestamp when job completes |
| `argo_workflow_id` | `''` (empty) | Argo workflow ID |

**This should be safe because:**
- The application handles empty/NULL values correctly
- Only new jobs will populate these fields
- Existing jobs are considered complete (not managed by new scheduler)
- No queries break due to missing data

## Downtime Requirements

The database changes are intended to be backward-compatible. No downtime required.
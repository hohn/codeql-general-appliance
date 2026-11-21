# SQL Table Definitions and Database Setup Code

## Overview

This document provides a comprehensive overview of all SQL table definitions and database setup code in the MRVA Commander system. The system uses PostgreSQL as its primary database.

## File Locations

### 1. Main Database Initialization Code

**File:** [pkg/state/state_postgres.go](../pkg/state/state_postgres.go)

This is the primary file containing database schema definitions. The [SetupSchemas()](../pkg/state/state_postgres.go#L109-L213) function (lines 109-213) creates all database tables.

### 2. Database Migration Script

**File:** [db_schema_changes/scheduler/migrate_database_schema.sql](../db_schema_changes/scheduler/migrate_database_schema.sql)

Idempotent migration script for adding scheduler-related schema changes.

### 3. Schema Documentation

**File:** [db_schema_changes/scheduler/SCHEDULER_DB_SCHEMA_CHANGES.md](../db_schema_changes/scheduler/SCHEDULER_DB_SCHEMA_CHANGES.md)

Comprehensive documentation of schema changes for fair scheduling implementation.

---

## Table Definitions

### 1. job_repo_map

**Source:** [state_postgres.go:119-124](../pkg/state/state_postgres.go#L119-L124)

Maps job identifiers to repository information.

```sql
CREATE TABLE IF NOT EXISTS job_repo_map (
    job_repo_id SERIAL PRIMARY KEY,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    UNIQUE(owner, repo)
);
```

**Purpose:** Lookup table for mapping repository owners and names to unique identifiers.

**Columns:**
- `job_repo_id` - Auto-incrementing primary key
- `owner` - Repository owner (e.g., GitHub username or organization)
- `repo` - Repository name

**Constraints:**
- UNIQUE constraint on (owner, repo) combination

---

### 2. session_id_seq

**Source:** [state_postgres.go:130](../pkg/state/state_postgres.go#L130)

Sequence for generating unique session IDs.

```sql
CREATE SEQUENCE IF NOT EXISTS session_id_seq;
```

**Purpose:** Provides unique identifiers for analysis sessions.

---

### 3. analyze_results

**Source:** [state_postgres.go:136-142](../pkg/state/state_postgres.go#L136-L142)

Stores analysis results in JSON format.

```sql
CREATE TABLE IF NOT EXISTS analyze_results (
    session_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    result JSONB,
    PRIMARY KEY (session_id, owner, repo)
);
```

**Purpose:** Stores the output/results from analysis jobs.

**Columns:**
- `session_id` - Session identifier
- `owner` - Repository owner
- `repo` - Repository name
- `result` - JSON blob containing analysis results

**Primary Key:** Composite key on (session_id, owner, repo)

---

### 4. analyze_jobs

**Source:** [state_postgres.go:148-154](../pkg/state/state_postgres.go#L148-L154)

Stores job specifications and payloads.

```sql
CREATE TABLE IF NOT EXISTS analyze_jobs (
    session_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    payload JSONB,
    PRIMARY KEY (session_id, owner, repo)
);
```

**Purpose:** Stores the job definition/specification for analysis tasks.

**Columns:**
- `session_id` - Session identifier
- `owner` - Repository owner
- `repo` - Repository name
- `payload` - JSON blob containing job configuration and parameters

**Primary Key:** Composite key on (session_id, owner, repo)

---

### 5. job_info

**Source:** [state_postgres.go:160-176](../pkg/state/state_postgres.go#L160-L176)

Stores detailed job information with scheduling metadata.

```sql
CREATE TABLE IF NOT EXISTS job_info (
    session_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    payload JSONB,
    user_id TEXT DEFAULT '',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    argo_workflow_id TEXT DEFAULT '',
    PRIMARY KEY (session_id, owner, repo)
);

CREATE INDEX IF NOT EXISTS idx_job_info_user_started
    ON job_info(user_id, started_at);

CREATE INDEX IF NOT EXISTS idx_job_info_workflow
    ON job_info(argo_workflow_id)
    WHERE argo_workflow_id != '';
```

**Purpose:** Central table for job metadata, user tracking, timing information, and Argo Workflows integration.

**Columns:**
- `session_id` - Session identifier
- `owner` - Repository owner
- `repo` - Repository name
- `payload` - JSON blob containing job details
- `user_id` - User who submitted the job (defaults to empty string)
- `started_at` - Timestamp when job execution began
- `completed_at` - Timestamp when job execution finished
- `argo_workflow_id` - Argo Workflows execution identifier (defaults to empty string)

**Primary Key:** Composite key on (session_id, owner, repo)

**Indices:**
- `idx_job_info_user_started` - Optimizes queries for fair scheduling by user and start time
- `idx_job_info_workflow` - Optimizes lookups by Argo workflow ID (partial index, only non-empty IDs)

**Use Cases:**
- Fair scheduling: Uses `user_id` and `started_at` for round-robin scheduling
- Job tracking: Monitors job lifecycle from start to completion
- Argo integration: Links database records to Argo Workflows executions
- Metrics: Calculates job duration via `completed_at - started_at`

---

### 6. job_status

**Source:** [state_postgres.go:182-188](../pkg/state/state_postgres.go#L182-L188)

Tracks job execution status.

```sql
CREATE TABLE IF NOT EXISTS job_status (
    session_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    status INTEGER,
    PRIMARY KEY (session_id, owner, repo)
);
```

**Purpose:** Tracks the current execution status of jobs.

**Columns:**
- `session_id` - Session identifier
- `owner` - Repository owner
- `repo` - Repository name
- `status` - Integer status code representing job state

**Primary Key:** Composite key on (session_id, owner, repo)

**Status Values:** (Defined in application code)
- Typically represents states like: Pending, Running, Completed, Failed, etc.

---

### 7. scheduler_lock

**Source:** [state_postgres.go:194-200](../pkg/state/state_postgres.go#L194-L200)

Distributed lock table for scheduler leader election.

```sql
CREATE TABLE IF NOT EXISTS scheduler_lock (
    lock_name TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    acquired_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    heartbeat_at TIMESTAMP NOT NULL
);
```

**Purpose:** Implements distributed locking mechanism for high-availability scheduler coordination.

**Columns:**
- `lock_name` - Name of the lock (primary key)
- `instance_id` - Identifier of the scheduler instance holding the lock
- `acquired_at` - Timestamp when lock was first acquired
- `expires_at` - Timestamp when lock will expire (if not renewed)
- `heartbeat_at` - Timestamp of last heartbeat update

**Primary Key:** `lock_name`

**Use Cases:**
- Leader election: Ensures only one scheduler instance is active at a time
- High availability: Allows failover if leader instance crashes
- Heartbeat mechanism: Detects failed scheduler instances via stale heartbeats

---

## Database Migration

### Migration Script

The migration script at [migrate_database_schema.sql](../db_schema_changes/scheduler/migrate_database_schema.sql) provides idempotent schema updates.

**Features:**
- **Idempotent:** Safe to run multiple times without side effects
- **Transactional:** All operations wrapped in transactions
- **Non-destructive:** Preserves existing data
- **Backward compatible:** Uses DEFAULT values for new columns

**Changes Applied:**
1. Adds columns to `job_info` table:
   - `user_id TEXT DEFAULT ''`
   - `started_at TIMESTAMP`
   - `completed_at TIMESTAMP`
   - `argo_workflow_id TEXT DEFAULT ''`

2. Creates performance indices:
   - `idx_job_info_user_started`
   - `idx_job_info_workflow`

3. Creates `scheduler_lock` table

**Migration Options:**
- **Manual:** Run via `psql` command line
- **Automatic:** Application runs migration on startup via [SetupSchemas()](../pkg/state/state_postgres.go#L109-L213)

---

## Database Setup Flow

### Initialization Process

1. **Application Startup:**
   - Connects to PostgreSQL database
   - Calls [SetupSchemas()](../pkg/state/state_postgres.go#L109-L213) in [state_postgres.go](../pkg/state/state_postgres.go)

2. **Schema Creation:**
   - Creates all tables using `CREATE TABLE IF NOT EXISTS`
   - Creates sequences and indices
   - Idempotent operations allow safe re-runs

3. **Migration (if needed):**
   - Can be run manually via SQL script
   - Or automatically handled by [SetupSchemas()](../pkg/state/state_postgres.go#L109-L213)

### Connection Details

Database connection is configured via environment variables or configuration files (see application configuration documentation).

---

## Key Database Features

### 1. User-Based Fair Scheduling

**Implementation:**
- `job_info.user_id` tracks which user submitted each job
- `job_info.started_at` records when jobs begin execution
- `idx_job_info_user_started` index optimizes fair scheduling queries
- Scheduler uses round-robin algorithm based on user and timing

### 2. Argo Workflows Integration

**Implementation:**
- `job_info.argo_workflow_id` links database records to Argo executions
- Allows tracking job lifecycle across both systems
- Enables querying Argo API for detailed job status

### 3. Job Execution Metrics

**Implementation:**
- `started_at` and `completed_at` timestamps enable duration calculations
- Supports analytics and performance monitoring
- Helps identify slow or stuck jobs

### 4. High Availability Scheduler

**Implementation:**
- `scheduler_lock` table provides distributed locking
- Leader election ensures single active scheduler
- Heartbeat mechanism detects failed instances
- Automatic failover to standby instances

---

## Schema Evolution

### Version History

**Initial Schema:**
- Basic tables: `job_repo_map`, `analyze_results`, `analyze_jobs`, `job_status`
- Simple job tracking without user context or timing

**Scheduler Enhancement (Current):**
- Added `user_id`, `started_at`, `completed_at`, `argo_workflow_id` to `job_info`
- Added `scheduler_lock` table
- Created performance indices
- Enabled fair scheduling and HA capabilities

---

## Best Practices

### 1. Schema Changes

- Always write idempotent migrations
- Use `IF NOT EXISTS` and `IF EXISTS` clauses
- Provide DEFAULT values for backward compatibility
- Test migrations on development environment first
- Document all schema changes

### 2. Indexing Strategy

- Index columns used in WHERE clauses and JOINs
- Use partial indices for filtered queries
- Monitor index usage and performance
- Avoid over-indexing (impacts write performance)

### 3. Data Integrity

- Use appropriate PRIMARY KEY constraints
- Add UNIQUE constraints where needed
- Use FOREIGN KEY constraints (if implementing cross-table references)
- Validate data at application layer as well

---

## Related Documentation

- [SCHEDULER_DB_SCHEMA_CHANGES.md](../db_schema_changes/scheduler/SCHEDULER_DB_SCHEMA_CHANGES.md) - Scheduler schema changes
- [ARCHITECTURE_MIGRATION.md](ARCHITECTURE_MIGRATION.md) - Overall architecture including database design
- [state_postgres.go](../pkg/state/state_postgres.go) - Database access layer implementation

---

## Future Considerations

### Potential Enhancements

1. **Partitioning:** Consider table partitioning for high-volume tables
2. **Archival:** Implement data retention policies for old sessions
3. **Foreign Keys:** Add explicit foreign key constraints between tables
4. **Audit Trail:** Track schema version and migration history
5. **Monitoring:** Add database performance metrics and alerting

### Scalability Considerations

- Current schema supports horizontal scaling via multiple scheduler instances
- PostgreSQL connection pooling recommended for high concurrency
- Consider read replicas for analytics queries
- Monitor table growth and plan for archival strategy

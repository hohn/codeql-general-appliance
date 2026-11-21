# MRVA Architecture Migration: RabbitMQ to Argo Workflows

## Overview

This document describes the architectural evolution of the MRVA (Multi-Repository Variant Analysis) system from a RabbitMQ-based agent polling model to a centralized Argo Workflows scheduler with fair scheduling.

## Documentation Structure

The MRVA system has two mathematical specifications that correspond to different architectural generations:

1. **[mrva-overview-rabbitmq.tex](mrva-overview-rabbitmq.tex)** - Original specification for RabbitMQ-based architecture (historical reference)
2. **[mrva-overview-argo-scheduler.tex](mrva-overview-argo-scheduler.tex)** - Current specification for Argo Workflows architecture (active)

This migration guide provides context for understanding the differences between these two approaches.

## Why the Migration?

The migration from RabbitMQ agents to Argo Workflows was driven by several requirements:

### Problems with Old Architecture

1. **No fairness**: Jobs were processed first-come-first-served. A single user could monopolize all agent resources.
2. **No resource limits**: Agents had no per-job CPU/memory constraints, leading to resource contention.
3. **Static capacity**: Agent count was fixed; scaling required manual intervention.
4. **No user attribution**: Jobs were anonymous - couldn't track which user submitted which job.
5. **Limited visibility**: No built-in observability for job execution progress.

### Benefits of New Architecture

1. **Fair scheduling**: Round-robin allocation ensures users get equitable access to compute resources.
2. **Resource control**: Each job runs in a pod with explicit CPU (4 cores) and memory (16Gi) limits.
3. **Dynamic scaling**: Kubernetes can scale pod count based on demand.
4. **User tracking**: All jobs tagged with user ID from JWT token.
5. **High availability**: Leader election allows multiple scheduler instances for redundancy.
6. **Observability**: Argo Workflows UI provides real-time visibility into job execution.

## Architectural Comparison

### Old Architecture: RabbitMQ + Agent Polling

```
┌────────┐                   ┌──────────┐                 ┌───────┐
│ Client │─── submit ───────▶│  Server  │─── enqueue ────▶│ Queue │
└────────┘     (Q, R)        └──────────┘    (Q, Ri)      │ (MQ)  │
                                     ▲                    └───┬───┘
                                     │                         │
                                     │       ┌─────────────────┘
                                     │       │  poll (5s)
                                     │       ▼
                                     │    ┌───────┐
                                     │    │ Agent │─── execute ──▶ Results
                                     │    │ α     │
                                     │    └───────┘
                                     │
                                     └─── results ──
```

**Key characteristics:**
- Autonomous agents poll RabbitMQ every 5 seconds
- Agents are long-lived containers
- FIFO job ordering
- Stateless execution
- Direct queue communication

### New Architecture: Argo Workflows + Fair Scheduler

#### LaTeX Diagram

\\[\begin{array}{lclclclclclcl}
\text{Client} & \xrightarrow{\text{submit}} & \text{Server} & \xrightarrow{\text{store}} & \text{Database} & \xrightarrow{\text{poll (10s)}} & \text{Scheduler} & \xrightarrow{\text{fair select}} & \text{Argo} & \xrightarrow{\text{create pod}} & \text{K8s Pod} & \xrightarrow{\text{execute}} & \text{Results} \\\\
& (Q, R, u) & \Uparrow & (J\_i, u\_i) & \text{(PG)} & & (L) & & \text{Workflows} & & (\omega\_i) & & \\\\
& & \text{results} & & & & & & & & & & \\\\
\end{array}\\]

#### ASCII Diagram

```
┌────────┐                   ┌──────────┐                 ┌──────────┐
│ Client │─── submit ───────▶│  Server  │─── store ──────▶│ Database │
└────────┘     (Q, R, u)     └──────────┘    (Jᵢ, uᵢ)     │  (PG)    │
                                     ▲                    └────┬─────┘
                                     │                         │
                                     │       ┌─────────────────┘
                                     │       │  poll (10s)
                                     │       ▼
                                     │    ┌───────────┐
                                     │    │ Scheduler │─ fair    ┌─────────────┐
                                     │    │   (ℒ)     │─ select─▶│    Argo     │
                                     │    └───────────┘          │  Workflows  │
                                     │                           └──────┬──────┘
                                     │                                  │
                                     │       ┌──────────────────────────┘
                                     │       │  create pod
                                     │       ▼
                                     │    ┌─────────┐
                                     │    │ K8s Pod │─── execute ──▶ Results
                                     │    │  (ωᵢ)   │
                                     │    └─────────┘
                                     │
                                     └─── results ──
```

**Key characteristics:**
- Centralized scheduler with leader election
- Per-job Kubernetes pods (ephemeral)
- Fair scheduling algorithm
- Stateful tracking (PostgreSQL)
- Database-centric coordination

## Mathematical Representation Changes

### Old Model Symbols

| Symbol | Meaning |
|--------|---------|
| \\(Q\\) | RabbitMQ job queue |
| \\(\alpha\\) | Agent (autonomous worker) |
| \\(A\\) | Set of all agents |

**Old execution flow:**
```
C → S → Q → α → S → C
```

### New Model Symbols

| Symbol | Meaning |
|--------|---------|
| \\(D\\) | PostgreSQL database |
| \\(\Sigma\\) | Scheduler (centralized) |
| \\(L\\) or \\(\Sigma\_L\\) | Leader scheduler instance |
| \\(\Omega\\) | Argo Workflows |
| \\(\omega\_i\\) | Individual workflow (pod) for job \\(i\\) |
| \\(u\\) | User identifier |
| \\(n\_u^r\\) | Running job count for user \\(u\\) |
| \\(n\_u^p\\) | Pending job count for user \\(u\\) |
| \\(\tau\_u\\) | Recent runtime for user \\(u\\) |
| \\(W\\) | Max concurrent workers |
| \\(W\_a\\) | Available worker slots |
| \\(t\_i^s\\) | Job start timestamp |
| \\(t\_i^c\\) | Job completion timestamp |

**New execution flow:**

C → S → D → \\(Σ\_L\\) → Ω → \\(ω\_i\\) → S → C


## Database Schema Changes

### Extended `job_info` Table

Four new columns were added:

```sql
ALTER TABLE job_info ADD COLUMN user_id TEXT NOT NULL DEFAULT '';
ALTER TABLE job_info ADD COLUMN started_at TIMESTAMP;
ALTER TABLE job_info ADD COLUMN completed_at TIMESTAMP;
ALTER TABLE job_info ADD COLUMN argo_workflow_id TEXT NOT NULL DEFAULT '';
```

**Purpose:**
- `user_id`: Track job ownership for fair scheduling
- `started_at`: Measure job start time for runtime calculations
- `completed_at`: Measure job completion time for runtime calculations
- `argo_workflow_id`: Link to Argo Workflows for status polling

### New `scheduler_lock` Table

```sql
CREATE TABLE scheduler_lock (
    lock_name TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    acquired_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    heartbeat_at TIMESTAMP NOT NULL
);
```

**Purpose:** Database-based leader election for high-availability multi-instance deployments.

## Fair Scheduling Algorithm

The new scheduler implements a fair allocation policy based on three factors:

### Priority Function

Users are sorted by lexicographic ordering of:

\\(π(u) = (nᵤʳ, τᵤ, -nᵤᵖ)\\)


Where:
1. \\(nᵤʳ\\) - Running job count (ascending) - users with fewer running jobs get higher priority
2. \\(τᵤ\\) - Recent runtime (ascending) - users who have consumed less CPU time get higher priority
3. \\(-nᵤᵖ\\) - Pending job count (descending) - among ties, users with more pending jobs get priority

### Round-Robin Allocation

Once users are sorted by priority, available worker slots are distributed in round-robin fashion:

```
While slots available:
    For each user (in priority order):
        If user has pending jobs:
            Allocate 1 job to user
            Decrease available slots
```

### Example

Given:
- User A: 2 running, 100 pending, 3600s recent runtime
- User B: 0 running, 10 pending, 0s recent runtime
- User C: 1 running, 50 pending, 1800s recent runtime
- Available slots: 4

**Priority order:** B → C → A

**Allocation:** B gets 2 jobs, C gets 1 job, A gets 1 job

This ensures B (who has 0 running jobs) gets more slots than C and A.

## Leader Election

Multiple scheduler instances can run concurrently for high availability. They coordinate using a database lock:

### Lock Mechanism

- Lock name: `"mrva-scheduler"`
- Expiration: 30 seconds
- Renewal: Every 10 seconds
- Check interval: Every 10 seconds

### Lock Lifecycle

```
Instance A                    Database                   Instance B
    |                             |                            |
    |─── AcquireLock ───────────▶ |                            |
    |◀──── Success ───────────────│                            |
    |                             |                            |
    |  (becomes leader)           |                            |
    |                             |                            |
    |─── RenewLock (10s) ────────▶|                            |
    |◀──── Success ───────────────│                            |
    |                             |                            |
    |  (Instance A crashes)       |                            |
    |                             |                            |
    |                          (30s expiry)                    |
    |                             |                            |
    |                             |◀─── AcquireLock ───────────│
    |                             │──── Success ──────────────▶|
    |                             |                            |
    |                             |            (Instance B becomes leader)
```

If an instance crashes, its lock expires after 30 seconds and another instance can take over.

## Job Lifecycle Changes

### Old Lifecycle (RabbitMQ)

```
Created → Enqueued → Polling →   Executing →   Done
          (in MQ)    (by agent)  (by agent)
```

**States:**
- Pending: In RabbitMQ queue
- InProgress: Agent claimed job
- Succeeded/Failed: Agent reported result

**No timestamps tracked.**

### New Lifecycle (Argo Workflows)

\\[\begin{array}{lclclclcl}
\text{Created} & \rightarrow & \text{Pending} & \rightarrow & \text{Scheduled} & \rightarrow & \text{Running} & \rightarrow & \text{Completed} \\\\
& & \text{(in DB)} & & (\text{by } \Sigma\_L) & & \text{(in Argo)} & & \text{(pod done)} \\\\
& & \quad \downarrow & & \quad \downarrow & & \quad \downarrow & & \quad \downarrow \\\\
& & \sigma = \text{Pending} & & \sigma = \text{InProgress} & & \sigma = \text{InProgress} & & \sigma = \text{Succeeded} \\\\
& & & & t\_s \text{ set} & & \text{(polling)} & & t\_c \text{ set}
\end{array}\\]


**States:**
- Pending: Stored in database, not yet scheduled
- InProgress: Submitted to Argo, workflow created
- Succeeded: Argo workflow phase = "Succeeded"
- Failed: Argo workflow phase = "Failed" or "Error"

**Timestamps tracked:**
- `created_at`: When job was created
- `started_at`: When submitted to Argo
- `completed_at`: When Argo workflow finished

## Argo Workflows Integration

### Workflow Specification

Each job is submitted as an Argo Workflow with:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: mrva-agent-workflow-prod-go-
spec:
  entrypoint: mrva-agent
  templates:
    - name: mrva-agent
      script:
        image: agent-commander-argo:latest
        command: ["/layers/paketo-buildpacks_go-build/targets/bin/mrvaagent"]
        args: ["--job", "<job_json>"]
        env:
          - name: CODEQL_CLI_PATH
            value: "/workspace/codeql"
          # ... other env vars ...
        resources:
          requests:
            cpu: "4"
            memory: "16Gi"
          limits:
            cpu: "4"
            memory: "16Gi"
```

### Status Polling

The scheduler polls Argo every 10 seconds (configurable) to check workflow status:

| Argo Phase | Job Status | Action |
|------------|------------|--------|
| Pending | InProgress | Wait |
| Running | InProgress | Wait |
| Succeeded | Succeeded | Set `completed_at`, free slot |
| Failed | Failed | Set `completed_at`, free slot |
| Error | Failed | Set `completed_at`, free slot |

## Configuration Parameters

The new scheduler introduces several configurable parameters:

| Parameter | Environment Variable | Default | Description |
|-----------|---------------------|---------|-------------|
| Max Workers (W) | `MRVA_SCHEDULER_MAX_WORKERS` | 10 | Maximum concurrent jobs |
| Poll Interval (T_poll) | `MRVA_SCHEDULER_POLL_INTERVAL_SECONDS` | 10 | Scheduling cycle frequency |
| Runtime Window (T_w) | `MRVA_SCHEDULER_RECENT_RUNTIME_WINDOW_SECONDS` | 3600 | Time window for runtime tracking |
| Lock Expiration (T_exp) | (hardcoded) | 30 | Leader lock expiration time |
| Leader Check (T_check) | (hardcoded) | 10 | Leader election check interval |

## Migration Impact

### For Users

- **Fairness**: Users can no longer monopolize all compute resources
- **Visibility**: Job progress visible in Argo Workflows UI
- **Quotas**: Implicit fair-share quota based on running jobs and recent runtime

### For Operators

- **Scaling**: Can scale by adjusting `MRVA_SCHEDULER_MAX_WORKERS` instead of agent count
- **High Availability**: Can run multiple scheduler instances for redundancy
- **Observability**: Argo Workflows provides built-in metrics and dashboards
- **Resource Control**: Per-job resource limits prevent resource exhaustion

### For Developers

- **Database schema**: Four new columns in `job_info`, one new table `scheduler_lock`
- **New components**: Scheduler, Argo client, leader election
- **New queries**: Fair scheduling queries (`GetUserJobCounts`, `GetUserRecentRuntime`)
- **Workflow templates**: Argo Workflow spec generation

## Code References

### Scheduler Implementation

- Main loop with leader election: [pkg/scheduler/scheduler.go:116-196](../pkg/scheduler/scheduler.go)
- Fair scheduling algorithm: [pkg/scheduler/scheduler.go:302-395](../pkg/scheduler/scheduler.go)
- Job submission: [pkg/scheduler/scheduler.go:398-427](../pkg/scheduler/scheduler.go)
- Status polling: [pkg/scheduler/scheduler.go:431-470](../pkg/scheduler/scheduler.go)

### Argo Workflows Integration

- Argo client: [pkg/scheduler/argo_client.go](../pkg/scheduler/argo_client.go)
- Workflow submission: [pkg/scheduler/argo_client.go:420-533](../pkg/scheduler/argo_client.go)
- Token management: [pkg/scheduler/argo_client.go:169-245](../pkg/scheduler/argo_client.go)

### Database Layer

- Leader election: [pkg/state/state_postgres.go:770-853](../pkg/state/state_postgres.go)
- Fair scheduling queries: [pkg/state/state_postgres.go:604-663](../pkg/state/state_postgres.go)

### Schema Migration

- Documentation: [db_schema_changes/scheduler/SCHEDULER_DB_SCHEMA_CHANGES.md](../db_schema_changes/scheduler/SCHEDULER_DB_SCHEMA_CHANGES.md)
- Migration SQL: [db_schema_changes/scheduler/migrate_database_schema.sql](../db_schema_changes/scheduler/migrate_database_schema.sql)

## Summary

The migration from RabbitMQ to Argo Workflows represents a fundamental architectural shift:

**From:** Stateless, autonomous agent polling with FIFO ordering

**To:** Stateful, centralized fair scheduling with leader election and Kubernetes orchestration

This change enables:
- ✅ Fair resource distribution across users
- ✅ High availability through leader election
- ✅ Dynamic resource allocation in Kubernetes
- ✅ Comprehensive job tracking and observability
- ✅ Explicit resource limits per job

The mathematical specifications in [mrva-overview-argo-scheduler.tex](mrva-overview-argo-scheduler.tex) provide a rigorous foundation for understanding and extending the new scheduling system.

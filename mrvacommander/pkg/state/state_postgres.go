package state

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/hohn/mrvacommander/pkg/common"
	"github.com/hohn/mrvacommander/pkg/queue"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// ----- PGState holds the shared connection pool
type PGState struct {
	pool *pgxpool.Pool
}

func validateEnvVars(requiredEnvVars []string) {
	missing := false

	for _, envVar := range requiredEnvVars {
		if _, ok := os.LookupEnv(envVar); !ok {
			slog.Error("Missing required environment variable", "key", envVar)
			missing = true
		}
	}

	if missing {
		os.Exit(1)
	}
}

// NewPGState connects to Postgres and ensures the schema exists. Use this
// from the server, which owns schema lifecycle and runs SetupSchemas once
// at startup before any worker is spawned.
func NewPGState() *PGState {
	pool := newPGStatePool()
	SetupSchemas(pool)
	return &PGState{pool: pool}
}

// NewPGStateNoSchema connects to Postgres WITHOUT running schema setup.
// Use this from spawned workers: the server has already created the full
// schema before launching any worker, so a worker running DDL again only
// risks deadlocking its ALTER TABLE / CREATE INDEX against other workers'
// in-flight ClaimJob/CompleteJob UPDATEs on the same tables.
func NewPGStateNoSchema() *PGState {
	return &PGState{pool: newPGStatePool()}
}

func newPGStatePool() *pgxpool.Pool {
	ctx := context.Background()

	required := []string{
		"POSTGRES_USER",
		"POSTGRES_PASSWORD",
		"POSTGRES_DB",
		// Host & port may be omitted if you rely on Docker DNS, but list
		// them here to make the requirement explicit:
		"POSTGRES_HOST",
		"POSTGRES_PORT",
	}

	validateEnvVars(required)

	// Assemble from vars
	user := os.Getenv("POSTGRES_USER")
	pass := os.Getenv("POSTGRES_PASSWORD")
	host := os.Getenv("POSTGRES_HOST")
	port := os.Getenv("POSTGRES_PORT")
	db := os.Getenv("POSTGRES_DB")

	dbURL := fmt.Sprintf("postgres://%s:%s@%s:%s/%s", user, pass, host, port, db)
	redactedDbURL := fmt.Sprintf("postgres://%s:%s@%s:%s/%s", user, "<redacted>", host, port, db)
	slog.Info("Assembled Postgres connection URL from POSTGRES_* variables", "url", redactedDbURL)

	config, err := pgxpool.ParseConfig(dbURL)
	if err != nil {
		slog.Error("Failed to parse connection URL", "url", dbURL, "error", err)
		os.Exit(1)
	}

	// Configure custom CA certificate if specified.
	// Prefer POSTGRES_CA_CERT_FILE (path to file on disk).
	// Fall back to POSTGRES_CA_CERT (PEM content passed via env var).
	var caCert []byte
	if caCertFile := os.Getenv("POSTGRES_CA_CERT_FILE"); caCertFile != "" {
		slog.Info("Using CA certificate from file", "file", caCertFile)
		var err error
		caCert, err = os.ReadFile(caCertFile)
		if err != nil {
			slog.Error("Failed to read CA certificate file", "file", caCertFile, "error", err)
			os.Exit(1)
		}
	} else if certPEM := os.Getenv("POSTGRES_CA_CERT"); certPEM != "" {
		slog.Info("Using CA certificate from POSTGRES_CA_CERT env var")
		caCert = []byte(certPEM)
	}

	if len(caCert) > 0 {
		caCertPool := x509.NewCertPool()
		if !caCertPool.AppendCertsFromPEM(caCert) {
			slog.Error("Failed to parse CA certificate PEM")
			os.Exit(1)
		}

		config.ConnConfig.TLSConfig = &tls.Config{
			RootCAs:    caCertPool,
			ServerName: host,
		}
	}

	config.MaxConns = 10

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		slog.Error("Failed to create pgx pool", "error", err)
		os.Exit(1)
	}

	slog.Info("Connected to Postgres", "max_conns", config.MaxConns)

	return pool
}

func SetupSchemas(pool *pgxpool.Pool) {
	ctx := context.Background()

	// Every process that talks to Postgres (the server and each spawned
	// worker) runs SetupSchemas on startup. Concurrent `CREATE TABLE /
	// INDEX IF NOT EXISTS` statements take ShareUpdateExclusive locks that
	// conflict with each other, and when several workers start at once
	// (e.g. multiple users submitting simultaneously) they deadlock
	// (SQLSTATE 40P01) — which also collaterally deadlocks concurrent
	// ClaimJob UPDATEs on job_info. Serialize the whole DDL block behind a
	// session-level advisory lock so exactly one process runs it at a time;
	// the statements are all idempotent, so the rest become fast no-ops.
	//
	// The lock is session-scoped, so it must be taken, used, and released
	// on a single dedicated connection.
	const schemaLockKey int64 = 0x4D525641534d // "MRVAS" — arbitrary, stable

	conn, err := pool.Acquire(ctx)
	if err != nil {
		slog.Error("SetupSchemas: acquire connection", "error", err)
		os.Exit(1)
	}
	defer conn.Release()

	if _, err := conn.Exec(ctx, `SELECT pg_advisory_lock($1)`, schemaLockKey); err != nil {
		slog.Error("SetupSchemas: acquire advisory lock", "error", err)
		os.Exit(1)
	}
	defer func() {
		if _, err := conn.Exec(ctx, `SELECT pg_advisory_unlock($1)`, schemaLockKey); err != nil {
			slog.Warn("SetupSchemas: release advisory lock", "error", err)
		}
	}()

	schemas := []struct {
		name string
		sql  string
	}{
		{
			name: "job_repo_map",
			sql: `
				CREATE TABLE IF NOT EXISTS job_repo_map (
					job_repo_id SERIAL PRIMARY KEY,
					owner       TEXT NOT NULL,
					repo        TEXT NOT NULL,
					UNIQUE(owner, repo)
				);
			  `,
		},
		{
			name: "session_id_seq",
			sql: `
        		CREATE SEQUENCE IF NOT EXISTS session_id_seq;
	        `,
		},
		{
			name: "analyze_results",
			sql: `
				CREATE TABLE IF NOT EXISTS analyze_results (
					session_id INTEGER NOT NULL,
					owner TEXT NOT NULL,
					repo TEXT NOT NULL,
					result JSONB NOT NULL,
					PRIMARY KEY (session_id, owner, repo)
				);
			`,
		},
		{
			name: "analyze_jobs",
			sql: `
				CREATE TABLE IF NOT EXISTS analyze_jobs (
					session_id INTEGER NOT NULL,
					owner TEXT NOT NULL,
					repo TEXT NOT NULL,
					payload JSONB NOT NULL,
					PRIMARY KEY (session_id, owner, repo)
				);
			`,
		},
		{
			name: "job_info",
			sql: `
				CREATE TABLE IF NOT EXISTS job_info (
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

				-- Add indices for scheduler queries
				CREATE INDEX IF NOT EXISTS idx_job_info_user_started
					ON job_info(user_id, started_at);
				CREATE INDEX IF NOT EXISTS idx_job_info_workflow
					ON job_info(argo_workflow_id) WHERE argo_workflow_id != '';
			`,
		},
		{
			name: "job_status",
			sql: `
				CREATE TABLE IF NOT EXISTS job_status (
					session_id INTEGER NOT NULL,
					owner TEXT NOT NULL,
					repo TEXT NOT NULL,
					status INTEGER NOT NULL,
					PRIMARY KEY (session_id, owner, repo)
				);
			`,
		},
		{
			name: "scheduler_lock",
			sql: `
				CREATE TABLE IF NOT EXISTS scheduler_lock (
					lock_name TEXT PRIMARY KEY,
					instance_id TEXT NOT NULL,
					server_id TEXT NOT NULL DEFAULT '',
					acquired_at TIMESTAMP NOT NULL,
					expires_at TIMESTAMP NOT NULL,
					heartbeat_at TIMESTAMP NOT NULL
				);

				DO $$ BEGIN
					ALTER TABLE scheduler_lock ADD COLUMN IF NOT EXISTS server_id TEXT NOT NULL DEFAULT '';
				EXCEPTION WHEN duplicate_column THEN NULL;
				END $$;
			`,
		},
		{
			name: "server_registry",
			sql: `
				CREATE TABLE IF NOT EXISTS server_registry (
					lease_id TEXT PRIMARY KEY,
					server_id TEXT NOT NULL,
					started_at TIMESTAMP NOT NULL DEFAULT NOW(),
					heartbeat_at TIMESTAMP NOT NULL DEFAULT NOW()
				);

				CREATE INDEX IF NOT EXISTS idx_server_registry_heartbeat
					ON server_registry(heartbeat_at);
			`,
		},
		{
			name: "worker_pool",
			sql: `
				CREATE TABLE IF NOT EXISTS worker_pool (
					worker_id TEXT PRIMARY KEY,
					status INTEGER NOT NULL DEFAULT 0,
					registered_at TIMESTAMP NOT NULL DEFAULT NOW(),
					heartbeat_at TIMESTAMP NOT NULL DEFAULT NOW(),
					current_job TEXT,
					jobs_completed INTEGER NOT NULL DEFAULT 0,
					argo_pod_name TEXT NOT NULL DEFAULT ''
				);
			`,
		},
		{
			name: "job_info_worker_id",
			sql: `
				DO $$ BEGIN
					ALTER TABLE job_info ADD COLUMN IF NOT EXISTS worker_id TEXT NOT NULL DEFAULT '';
				EXCEPTION WHEN duplicate_column THEN NULL;
				END $$;

				CREATE INDEX IF NOT EXISTS idx_job_status_status_queued
					ON job_status(status) WHERE status IN (0, 6);

				CREATE INDEX IF NOT EXISTS idx_worker_pool_heartbeat
					ON worker_pool(heartbeat_at) WHERE status IN (0, 1);
			`,
		},
		{
			// pending_spawns records workers spawned by the pool manager that
			// have not yet registered in worker_pool (the startup lag). It makes
			// "starting" workers visible to the server/UI and survives pool
			// manager restarts, so the spawn accounting is no longer held only
			// in process memory.
			name: "pending_spawns",
			sql: `
				CREATE TABLE IF NOT EXISTS pending_spawns (
					workflow_uid TEXT PRIMARY KEY,
					language_hint TEXT NOT NULL DEFAULT '',
					spawned_at TIMESTAMP NOT NULL DEFAULT NOW()
				);

				CREATE INDEX IF NOT EXISTS idx_pending_spawns_spawned_at
					ON pending_spawns(spawned_at);
			`,
		},
		{
			// pack_sha1 is the SHA1 (hex) of the decoded query pack bytes,
			// computed by the server on submission. It gives each session's
			// pack a stable, shared identity (submissions carry no pack name)
			// and is surfaced in the sysview as "pack-<sha1>".
			name: "job_info_pack_sha1",
			sql: `
				DO $$ BEGIN
					ALTER TABLE job_info ADD COLUMN IF NOT EXISTS pack_sha1 TEXT NOT NULL DEFAULT '';
				EXCEPTION WHEN duplicate_column THEN NULL;
				END $$;
			`,
		},
	}

	for _, schema := range schemas {
		_, err := conn.Exec(ctx, schema.sql)
		if err != nil {
			slog.Error("Failed to create table", "table", schema.name, "error", err)
			os.Exit(1)
		}
		slog.Info("Schema initialized", "table", schema.name)
	}
}

// ----- Sequence-based NextID (implements ServerState)
func (s *PGState) NextID() int {
	ctx := context.Background()

	var id int
	err := s.pool.QueryRow(ctx, `SELECT nextval('session_id_seq')`).Scan(&id)
	if err != nil {
		slog.Error("NextID query failed", "error", err)
		panic("NextID(): " + err.Error()) // interface doesn't allow returning error
	}

	slog.Debug("NextID generated", "id", id)
	return id
}

func (s *PGState) SetResult(js common.JobSpec, ar queue.AnalyzeResult) {
	ctx := context.Background()

	ar.Spec = js // ensure internal consistency

	jsonBytes, err := json.Marshal(ar)
	if err != nil {
		slog.Error("SetResult: JSON marshal failed", "job", js, "error", err)
		panic("SetResult(): " + err.Error())
	}

	_, err = s.pool.Exec(ctx, `
		INSERT INTO analyze_results (session_id, owner, repo, result)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (session_id, owner, repo)
		DO UPDATE SET result = EXCLUDED.result
	`, js.SessionID, js.Owner, js.Repo, jsonBytes)

	if err != nil {
		slog.Error("SetResult: insert/update failed", "job", js, "error", err)
		panic("SetResult(): " + err.Error())
	}

	slog.Debug("state: set result",
		"session", js.SessionID, "owner", js.Owner, "repo", js.Repo,
		"result_key", ar.ResultLocation.Key, "result_count", ar.ResultCount,
		"status", ar.Status.ToExternalString())
}

func (s *PGState) SetResultAndStatus(js common.JobSpec, ar queue.AnalyzeResult, status common.Status) {
	ctx := context.Background()

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		slog.Error("SetResultAndStatus: begin tx failed", "job", js, "error", err)
		panic("SetResultAndStatus(): " + err.Error())
	}
	defer tx.Rollback(ctx)

	ar.Spec = js
	jsonBytes, err := json.Marshal(ar)
	if err != nil {
		slog.Error("SetResultAndStatus: JSON marshal failed", "job", js, "error", err)
		panic("SetResultAndStatus(): " + err.Error())
	}

	_, err = tx.Exec(ctx, `
		INSERT INTO analyze_results (session_id, owner, repo, result)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (session_id, owner, repo)
		DO UPDATE SET result = EXCLUDED.result
	`, js.SessionID, js.Owner, js.Repo, jsonBytes)
	if err != nil {
		slog.Error("SetResultAndStatus: insert result failed", "job", js, "error", err)
		panic("SetResultAndStatus(): " + err.Error())
	}

	_, err = tx.Exec(ctx, `
		INSERT INTO job_status (session_id, owner, repo, status)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (session_id, owner, repo)
		DO UPDATE SET status = EXCLUDED.status
	`, js.SessionID, js.Owner, js.Repo, status)
	if err != nil {
		slog.Error("SetResultAndStatus: insert status failed", "job", js, "error", err)
		panic("SetResultAndStatus(): " + err.Error())
	}

	if err := tx.Commit(ctx); err != nil {
		slog.Error("SetResultAndStatus: commit failed", "job", js, "error", err)
		panic("SetResultAndStatus(): " + err.Error())
	}

	slog.Debug("state: set result+status",
		"session", js.SessionID, "owner", js.Owner, "repo", js.Repo,
		"status", status.ToExternalString())
}

func (s *PGState) GetResult(js common.JobSpec) (queue.AnalyzeResult, error) {
	ctx := context.Background()

	var jsonBytes []byte
	err := s.pool.QueryRow(ctx, `
        SELECT result FROM analyze_results
        WHERE session_id = $1 AND owner = $2 AND repo = $3
    `, js.SessionID, js.Owner, js.Repo).Scan(&jsonBytes)
	if err != nil {
		return queue.AnalyzeResult{}, err
	}

	var ar queue.AnalyzeResult
	if err := json.Unmarshal(jsonBytes, &ar); err != nil {
		return queue.AnalyzeResult{}, fmt.Errorf("unmarshal AnalyzeResult: %w", err)
	}

	return ar, nil
}

func (s *PGState) SetJobInfo(js common.JobSpec, ji common.JobInfo) {
	ctx := context.Background()

	jiJSON, err := json.Marshal(ji)
	if err != nil {
		slog.Error("SetJobInfo: marshal failed", "job", js, "error", err)
		panic("SetJobInfo(): " + err.Error())
	}

	var startedAt, completedAt interface{}
	if ji.StartedAt != "" {
		startedAt = ji.StartedAt
	}
	if ji.CompletedAt != "" {
		completedAt = ji.CompletedAt
	}

	_, err = s.pool.Exec(ctx, `
		INSERT INTO job_info (session_id, owner, repo, payload, user_id, started_at, completed_at, argo_workflow_id, pack_sha1)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		ON CONFLICT (session_id, owner, repo)
		DO UPDATE SET
			payload = EXCLUDED.payload,
			user_id = EXCLUDED.user_id,
			started_at = EXCLUDED.started_at,
			completed_at = EXCLUDED.completed_at,
			argo_workflow_id = EXCLUDED.argo_workflow_id,
			pack_sha1 = EXCLUDED.pack_sha1
	`, js.SessionID, js.Owner, js.Repo, jiJSON, ji.User, startedAt, completedAt, ji.ArgoWorkflowID, ji.PackSHA1)

	if err != nil {
		slog.Error("SetJobInfo: insert/update failed", "job", js, "error", err)
		panic("SetJobInfo(): " + err.Error())
	}

	slog.Debug("state: set job info",
		"session", js.SessionID, "owner", js.Owner, "repo", js.Repo,
		"user", ji.User, "argo_wf", ji.ArgoWorkflowID,
		"started_at", ji.StartedAt, "completed_at", ji.CompletedAt)
}

func (s *PGState) GetJobInfo(js common.JobSpec) (common.JobInfo, error) {
	ctx := context.Background()

	var jsonBytes []byte
	var startedAt, completedAt *time.Time
	var userID, argoWorkflowID string

	err := s.pool.QueryRow(ctx, `
		SELECT payload, user_id, started_at, completed_at, argo_workflow_id
		FROM job_info
		WHERE session_id = $1 AND owner = $2 AND repo = $3
	`, js.SessionID, js.Owner, js.Repo).Scan(&jsonBytes, &userID, &startedAt, &completedAt, &argoWorkflowID)
	if err != nil {
		return common.JobInfo{}, err
	}

	var ji common.JobInfo
	if err := json.Unmarshal(jsonBytes, &ji); err != nil {
		return common.JobInfo{}, fmt.Errorf("unmarshal JobInfo: %w", err)
	}

	// Populate the additional fields from columns
	ji.User = userID
	ji.ArgoWorkflowID = argoWorkflowID
	if startedAt != nil {
		ji.StartedAt = startedAt.Format(time.RFC3339)
	}
	if completedAt != nil {
		ji.CompletedAt = completedAt.Format(time.RFC3339)
	}

	return ji, nil
}

func (s *PGState) SetStatus(js common.JobSpec, status common.Status) {
	ctx := context.Background()

	// Read old status for transition logging (cheap: single row by PK)
	var oldStr string
	if old, err := s.GetStatus(js); err != nil {
		oldStr = "(new)"
	} else {
		oldStr = old.ToExternalString()
	}

	_, err := s.pool.Exec(ctx, `
		INSERT INTO job_status (session_id, owner, repo, status)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (session_id, owner, repo)
		DO UPDATE SET status = EXCLUDED.status
	`, js.SessionID, js.Owner, js.Repo, status)

	if err != nil {
		slog.Error("SetStatus failed", "job", js, "status", status, "error", err)
		panic("SetStatus(): " + err.Error())
	}

	slog.Debug("state: job status",
		"session", js.SessionID, "owner", js.Owner, "repo", js.Repo,
		"old", oldStr, "new", status.ToExternalString())
}

func (s *PGState) GetSessionStatus(sessionID int) (common.StatusSummary, error) {
	ctx := context.Background()

	rows, err := s.pool.Query(ctx, `
        SELECT status
        FROM job_status
        WHERE session_id = $1
    `, sessionID)
	if err != nil {
		return common.StatusSummary{}, err
	}
	defer rows.Close()

	counts := map[common.Status]int{
		common.StatusPending:    0,
		common.StatusInProgress: 0,
		common.StatusSucceeded:  0,
		common.StatusFailed:     0,
		common.StatusCanceled:   0,
		common.StatusTimedOut:   0,
		common.StatusQueued:     0,
	}
	total := 0

	for rows.Next() {
		var st int
		if err := rows.Scan(&st); err != nil {
			return common.StatusSummary{}, err
		}
		counts[common.Status(st)]++
		total++
	}

	// apply deterministic rules
	var overall common.Status
	switch {
	case counts[common.StatusSucceeded] == total:
		overall = common.StatusSucceeded
	case counts[common.StatusFailed] == total:
		overall = common.StatusFailed
	case counts[common.StatusCanceled] == total:
		overall = common.StatusCanceled
	case counts[common.StatusTimedOut] == total:
		overall = common.StatusFailed
	case counts[common.StatusInProgress] > 0:
		overall = common.StatusPending
	case counts[common.StatusQueued] > 0:
		overall = common.StatusPending
	case counts[common.StatusPending] > 0:
		overall = common.StatusPending
	case counts[common.StatusPending] == 0 && counts[common.StatusInProgress] == 0:
		overall = common.StatusSucceeded // covers mixed complete
	default:
		overall = common.StatusPending
	}

	return common.StatusSummary{Overall: overall, Counts: counts}, nil
}

func (s *PGState) GetStatus(js common.JobSpec) (common.Status, error) {
	ctx := context.Background()

	var status int
	err := s.pool.QueryRow(ctx, `
		SELECT status
		FROM job_status
		WHERE session_id = $1 AND owner = $2 AND repo = $3
	`, js.SessionID, js.Owner, js.Repo).Scan(&status)
	if err != nil {
		return 0, err // caller must interpret not-found vs. real error
	}

	return common.Status(status), nil
}

// GetRepoId returns a stable unique ID for a given (owner, repo).
// If the pair doesn't exist, it is inserted atomically.
func (s *PGState) GetRepoId(cno common.NameWithOwner) int {
	ctx := context.Background()

	var jobRepoID int

	err := s.pool.QueryRow(ctx, `
			INSERT INTO job_repo_map (owner, repo)
			VALUES ($1, $2)
			ON CONFLICT (owner, repo) DO UPDATE SET owner = EXCLUDED.owner
			RETURNING job_repo_id
		`, cno.Owner, cno.Repo).Scan(&jobRepoID)
	if err != nil {
		slog.Error("GetRepoId failed", "NameWithOwner", cno, "error", err)
		panic("GetRepoId: " + err.Error())
	}

	return jobRepoID

}

func (s *PGState) AddJob(job queue.AnalyzeJob) {
	ctx := context.Background()
	js := job.Spec

	// Begin transaction for atomic operation
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		slog.Error("AddJob: failed to begin transaction", "job", js, "error", err)
		panic("AddJob(): " + err.Error())
	}
	defer tx.Rollback(ctx) // Will be ignored if tx.Commit() succeeds

	// 1. Store AnalyzeJob payload -------------------------------
	jb, err := json.Marshal(job)
	if err != nil {
		slog.Error("AddJob: marshal failed", "job", js, "error", err)
		panic("AddJob(): " + err.Error())
	}

	_, err = tx.Exec(ctx, `
		INSERT INTO analyze_jobs (session_id, owner, repo, payload)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT DO NOTHING
	`, js.SessionID, js.Owner, js.Repo, jb)
	if err != nil {
		slog.Error("AddJob: insert analyze_jobs failed", "job", js, "error", err)
		panic("AddJob(): " + err.Error())
	}

	// 2. Get job_repo_id
	jobRepoID := s.GetRepoId(job.Spec.NameWithOwner)

	// Commit the transaction
	if err = tx.Commit(ctx); err != nil {
		slog.Error("AddJob: failed to commit transaction", "job", js, "error", err)
		panic("AddJob(): " + err.Error())
	}

	slog.Debug("state: add job",
		"session", js.SessionID, "owner", js.Owner, "repo", js.Repo,
		"job_repo_id", jobRepoID, "language", job.QueryLanguage)
}

func (s *PGState) GetJobList(sessionId int) ([]queue.AnalyzeJob, error) {
	ctx := context.Background()

	rows, err := s.pool.Query(ctx, `
		SELECT payload FROM analyze_jobs
		WHERE session_id = $1
		ORDER BY owner, repo
	`, sessionId)
	if err != nil {
		slog.Error("GetJobList: query failed", "session_id", sessionId, "error", err)
		return nil, err
	}
	defer rows.Close()

	var jobs []queue.AnalyzeJob
	for rows.Next() {
		var jsonBytes []byte
		if err := rows.Scan(&jsonBytes); err != nil {
			slog.Error("GetJobList: scan failed", "error", err)
			return nil, err
		}
		var job queue.AnalyzeJob
		if err := json.Unmarshal(jsonBytes, &job); err != nil {
			slog.Error("GetJobList: unmarshal failed", "error", err)
			return nil, err
		}
		jobs = append(jobs, job)
	}

	if err := rows.Err(); err != nil {
		slog.Error("GetJobList: rows iteration failed", "error", err)
		return nil, err
	}

	return jobs, nil
}

func (s *PGState) GetJobSpecByRepoId(sessionId, jobRepoId int) (common.JobSpec, error) {
	ctx := context.Background()

	var owner, repo string
	err := s.pool.QueryRow(ctx, `
		SELECT owner, repo
		FROM job_repo_map
		WHERE job_repo_id = $1
	`, jobRepoId).Scan(&owner, &repo)
	if err != nil {
		return common.JobSpec{}, err
	}
	return common.JobSpec{
		SessionID: sessionId,
		NameWithOwner: common.NameWithOwner{
			Owner: owner,
			Repo:  repo,
		},
	}, nil
}

// ===== Scheduler-specific methods =====

func (s *PGState) GetPendingJobs() ([]queue.AnalyzeJob, error) {
	return s.GetJobsByStatus(common.StatusPending)
}

func (s *PGState) GetRunningJobs() ([]queue.AnalyzeJob, error) {
	return s.GetJobsByStatus(common.StatusInProgress)
}

func (s *PGState) GetJobsByStatus(status common.Status) ([]queue.AnalyzeJob, error) {
	ctx := context.Background()

	rows, err := s.pool.Query(ctx, `
		SELECT aj.payload
		FROM analyze_jobs aj
		JOIN job_status js ON
			aj.session_id = js.session_id AND
			aj.owner = js.owner AND
			aj.repo = js.repo
		WHERE js.status = $1
		ORDER BY aj.session_id, aj.owner, aj.repo
	`, status)
	if err != nil {
		slog.Error("GetJobsByStatus: query failed", "status", status, "error", err)
		return nil, err
	}
	defer rows.Close()

	var jobs []queue.AnalyzeJob
	for rows.Next() {
		var jsonBytes []byte
		if err := rows.Scan(&jsonBytes); err != nil {
			slog.Error("GetJobsByStatus: scan failed", "error", err)
			return nil, err
		}
		var job queue.AnalyzeJob
		if err := json.Unmarshal(jsonBytes, &job); err != nil {
			slog.Error("GetJobsByStatus: unmarshal failed", "error", err)
			return nil, err
		}
		jobs = append(jobs, job)
	}

	if err := rows.Err(); err != nil {
		slog.Error("GetJobsByStatus: rows iteration failed", "error", err)
		return nil, err
	}

	return jobs, nil
}

func (s *PGState) GetUserJobCounts() (map[string]int, error) {
	ctx := context.Background()

	rows, err := s.pool.Query(ctx, `
		SELECT ji.user_id, COUNT(*)
		FROM job_info ji
		JOIN job_status js ON
			ji.session_id = js.session_id AND
			ji.owner = js.owner AND
			ji.repo = js.repo
		WHERE js.status = $1 AND ji.user_id != ''
		GROUP BY ji.user_id
	`, common.StatusInProgress)
	if err != nil {
		slog.Error("GetUserJobCounts: query failed", "error", err)
		return nil, err
	}
	defer rows.Close()

	counts := make(map[string]int)
	for rows.Next() {
		var user string
		var count int
		if err := rows.Scan(&user, &count); err != nil {
			slog.Error("GetUserJobCounts: scan failed", "error", err)
			return nil, err
		}
		counts[user] = count
	}

	if err := rows.Err(); err != nil {
		slog.Error("GetUserJobCounts: rows iteration failed", "error", err)
		return nil, err
	}

	return counts, nil
}

func (s *PGState) GetUserRecentRuntime(user string, windowSeconds int) (float64, error) {
	ctx := context.Background()

	var totalSeconds float64
	err := s.pool.QueryRow(ctx, `
		SELECT COALESCE(SUM(
			EXTRACT(EPOCH FROM (completed_at - started_at))
		), 0)
		FROM job_info
		WHERE user_id = $1
			AND completed_at IS NOT NULL
			AND started_at IS NOT NULL
			AND completed_at > NOW() - INTERVAL '1 second' * $2
	`, user, windowSeconds).Scan(&totalSeconds)

	if err != nil {
		slog.Error("GetUserRecentRuntime: query failed", "user", user, "error", err)
		return 0, err
	}

	return totalSeconds, nil
}

func (s *PGState) GetRecentSessions(days int) ([]SessionSummary, error) {
	ctx := context.Background()

	// Get distinct sessions from the last N days
	rows, err := s.pool.Query(ctx, `
		SELECT DISTINCT
			ji.session_id,
			COALESCE(MAX(ji.user_id), '') as user_id,
			COALESCE(MAX(ji.payload->>'QueryLanguage'), '') as language,
			COALESCE(MAX(ji.payload->>'CreatedAt'), '') as created_at
		FROM job_info ji
		WHERE ji.payload->>'CreatedAt' IS NOT NULL
		  AND ji.payload->>'CreatedAt' != ''
		  AND (ji.payload->>'CreatedAt')::timestamp > NOW() - INTERVAL '1 day' * $1
		GROUP BY ji.session_id
		ORDER BY ji.session_id DESC
	`, days)
	if err != nil {
		slog.Error("GetRecentSessions: query failed", "error", err)
		return nil, err
	}
	defer rows.Close()

	var sessions []SessionSummary
	for rows.Next() {
		var sess SessionSummary
		if err := rows.Scan(&sess.SessionID, &sess.User, &sess.Language, &sess.CreatedAt); err != nil {
			slog.Error("GetRecentSessions: scan failed", "error", err)
			continue
		}

		// Get job counts for this session
		statusCounts, err := s.GetSessionStatus(sess.SessionID)
		if err != nil {
			slog.Warn("GetRecentSessions: could not get status", "session", sess.SessionID, "error", err)
			continue
		}

		sess.TotalJobs = 0
		for _, count := range statusCounts.Counts {
			sess.TotalJobs += count
		}
		sess.PendingJobs = statusCounts.Counts[common.StatusPending]
		sess.RunningJobs = statusCounts.Counts[common.StatusInProgress]
		sess.CompletedJobs = statusCounts.Counts[common.StatusSucceeded]
		sess.CancelledJobs = statusCounts.Counts[common.StatusCanceled]
		sess.FailedJobs = statusCounts.Counts[common.StatusFailed] +
			statusCounts.Counts[common.StatusTimedOut]

		avgSeconds := 0.0
		err = s.pool.QueryRow(ctx, `
			SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (ji.completed_at - ji.started_at))), 0)
			FROM job_info ji
			JOIN job_status js
			  ON js.session_id = ji.session_id
			 AND js.owner = ji.owner
			 AND js.repo = ji.repo
			WHERE ji.session_id = $1
			  AND ji.started_at IS NOT NULL
			  AND ji.completed_at IS NOT NULL
			  AND js.status = $2
		`, sess.SessionID, common.StatusSucceeded).Scan(&avgSeconds)
		if err != nil {
			slog.Warn("GetRecentSessions: avg duration query failed", "session", sess.SessionID, "error", err)
			avgSeconds = 0.0
		}
		sess.AvgCompletedJobSeconds = avgSeconds

		sessions = append(sessions, sess)
	}

	if err := rows.Err(); err != nil {
		slog.Error("GetRecentSessions: rows iteration failed", "error", err)
		return nil, err
	}

	return sessions, nil
}

func (s *PGState) CancelSession(sessionID int) (int, error) {
	ctx := context.Background()

	result, err := s.pool.Exec(ctx, `
		UPDATE job_status
		SET status = $1
		WHERE session_id = $2
		  AND (status = $3 OR status = $4 OR status = $5)
		`, common.StatusCanceled, sessionID, common.StatusPending, common.StatusInProgress,
		common.StatusQueued)

	if err != nil {
		slog.Error("CancelSession: update failed", "session", sessionID, "error", err)
		return 0, err
	}

	rowsAffected := result.RowsAffected()
	slog.Info("Session cancelled", "session", sessionID, "jobs_cancelled", rowsAffected)

	return int(rowsAffected), nil
}

func (s *PGState) GetSessionOwnerRepo(sessionID int) (string, string, error) {
	ctx := context.Background()

	// Since we don't currently store the controller repo, we'll use the first job's repo
	// as a proxy. In practice, you might want to add a sessions table to track this properly.
	var owner, repo string
	err := s.pool.QueryRow(ctx, `
		SELECT owner, repo
		FROM analyze_jobs
		WHERE session_id = $1
		ORDER BY owner, repo
		LIMIT 1
	`, sessionID).Scan(&owner, &repo)

	if err != nil {
		return "", "", err
	}

	return owner, repo, nil
}

// ----- Scheduler Lock Methods (for leader election)

func (s *PGState) AcquireSchedulerLock(lockName, leaseID, serverID string, expirationSeconds int, lastLogTime *time.Time, lastHolder *SchedulerLockHolder, throttle time.Duration) (bool, error) {
	ctx := context.Background()

	// Try to insert a new lock
	_, err := s.pool.Exec(ctx, `
		INSERT INTO scheduler_lock (lock_name, instance_id, server_id, acquired_at, expires_at, heartbeat_at)
		VALUES ($1, $2, $3, NOW(), NOW() + ($4 * INTERVAL '1 second'), NOW())
		ON CONFLICT (lock_name) DO UPDATE
		SET instance_id = EXCLUDED.instance_id,
		    server_id = EXCLUDED.server_id,
		    acquired_at = EXCLUDED.acquired_at,
		    expires_at = EXCLUDED.expires_at,
		    heartbeat_at = EXCLUDED.heartbeat_at
		WHERE scheduler_lock.expires_at < NOW()
		   OR scheduler_lock.instance_id = EXCLUDED.instance_id
	`, lockName, leaseID, serverID, expirationSeconds)

	if err != nil {
		slog.Error("AcquireSchedulerLock: failed", "lock", lockName, "server", serverID, "error", err)
		return false, err
	}

	// Check if we actually hold the lock now
	var currentHolder SchedulerLockHolder
	err = s.pool.QueryRow(ctx, `
		SELECT instance_id, server_id
		FROM scheduler_lock
		WHERE lock_name = $1 AND expires_at > NOW()
	`, lockName).Scan(&currentHolder.LeaseID, &currentHolder.ServerID)

	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			*lastHolder = SchedulerLockHolder{}
			return false, nil
		}
		slog.Error("AcquireSchedulerLock: query failed", "lock", lockName, "error", err)
		return false, err
	}

	acquired := currentHolder.LeaseID == leaseID
	if acquired {
		slog.Info("Scheduler lock acquired", "lock", lockName, "server", serverID, "lease_id", leaseID)
	} else {
		// Throttle debug logging: only log periodically or if holder changed
		shouldLog := time.Since(*lastLogTime) >= throttle || currentHolder != *lastHolder
		if shouldLog {
			slog.Debug("Scheduler lock held by another instance",
				"lock", lockName,
				"holder", currentHolder.ServerID,
				"holder_lease_id", currentHolder.LeaseID,
				"requestor", serverID,
				"requestor_lease_id", leaseID)
			*lastLogTime = time.Now()
		}
	}
	*lastHolder = currentHolder

	return acquired, nil
}

func (s *PGState) RenewSchedulerLock(lockName, leaseID string, expirationSeconds int, lastLogTime *time.Time, throttle time.Duration) (bool, error) {
	ctx := context.Background()

	result, err := s.pool.Exec(ctx, `
		UPDATE scheduler_lock
		SET heartbeat_at = NOW(),
		    expires_at = NOW() + ($3 * INTERVAL '1 second')
		WHERE lock_name = $1 AND instance_id = $2 AND expires_at > NOW()
	`, lockName, leaseID, expirationSeconds)

	if err != nil {
		slog.Error("RenewSchedulerLock: failed", "lock", lockName, "lease_id", leaseID, "error", err)
		return false, err
	}

	rowsAffected := result.RowsAffected()
	renewed := rowsAffected > 0

	if renewed {
		// Throttle debug logging: only log periodically
		if time.Since(*lastLogTime) >= throttle {
			slog.Debug("Scheduler lock renewed", "lock", lockName, "lease_id", leaseID)
			*lastLogTime = time.Now()
		}
	} else {
		slog.Warn("Failed to renew scheduler lock (not held)", "lock", lockName, "lease_id", leaseID)
	}

	return renewed, nil
}

func (s *PGState) ReleaseSchedulerLock(lockName, leaseID string) error {
	ctx := context.Background()

	result, err := s.pool.Exec(ctx, `
		DELETE FROM scheduler_lock
		WHERE lock_name = $1 AND instance_id = $2
	`, lockName, leaseID)

	if err != nil {
		slog.Error("ReleaseSchedulerLock: failed", "lock", lockName, "lease_id", leaseID, "error", err)
		return err
	}

	rowsAffected := result.RowsAffected()
	if rowsAffected > 0 {
		slog.Info("Scheduler lock released", "lock", lockName, "lease_id", leaseID)
	} else {
		slog.Warn("Scheduler lock not held during release", "lock", lockName, "lease_id", leaseID)
	}

	return nil
}

func (s *PGState) GetSchedulerLockHolder(lockName string) (SchedulerLockHolder, error) {
	ctx := context.Background()

	var holder SchedulerLockHolder
	err := s.pool.QueryRow(ctx, `
		SELECT instance_id, server_id
		FROM scheduler_lock
		WHERE lock_name = $1 AND expires_at > NOW()
	`, lockName).Scan(&holder.LeaseID, &holder.ServerID)

	if err != nil {
		// No lock holder (either doesn't exist or expired)
		return SchedulerLockHolder{}, err
	}

	return holder, nil
}

func (s *PGState) RegisterServer(leaseID, serverID string) error {
	ctx := context.Background()
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("RegisterServer: begin: %w", err)
	}
	defer tx.Rollback(ctx)

	if _, err := tx.Exec(ctx, `
		DELETE FROM server_registry
		WHERE server_id = $1 AND lease_id != $2
	`, serverID, leaseID); err != nil {
		return fmt.Errorf("RegisterServer: remove prior process: %w", err)
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO server_registry (lease_id, server_id, started_at, heartbeat_at)
		VALUES ($1, $2, NOW(), NOW())
		ON CONFLICT (lease_id) DO UPDATE
		SET server_id = EXCLUDED.server_id,
		    heartbeat_at = NOW()
	`, leaseID, serverID); err != nil {
		return fmt.Errorf("RegisterServer: upsert: %w", err)
	}
	return tx.Commit(ctx)
}

func (s *PGState) ServerHeartbeat(leaseID, serverID string) error {
	ctx := context.Background()
	_, err := s.pool.Exec(ctx, `
		INSERT INTO server_registry (lease_id, server_id, started_at, heartbeat_at)
		VALUES ($1, $2, NOW(), NOW())
		ON CONFLICT (lease_id) DO UPDATE
		SET server_id = EXCLUDED.server_id,
		    heartbeat_at = NOW()
	`, leaseID, serverID)
	if err != nil {
		return fmt.Errorf("ServerHeartbeat: %w", err)
	}
	return nil
}

// ===== Worker Pool Methods =====

func (s *PGState) RegisterWorker(workerID, podName string) error {
	ctx := context.Background()

	// (xmax = 0) is true only for a genuinely new INSERT, false when the
	// ON CONFLICT branch updated an existing row (a re-registration).
	var inserted bool
	err := s.pool.QueryRow(ctx, `
		INSERT INTO worker_pool (worker_id, status, registered_at, heartbeat_at, argo_pod_name)
		VALUES ($1, $2, NOW(), NOW(), $3)
		ON CONFLICT (worker_id) DO UPDATE SET
			status = EXCLUDED.status,
			heartbeat_at = EXCLUDED.heartbeat_at,
			argo_pod_name = EXCLUDED.argo_pod_name
		RETURNING (xmax = 0)
	`, workerID, common.WorkerIdle, podName).Scan(&inserted)

	if err != nil {
		slog.Error("RegisterWorker: failed", "worker_id", workerID, "error", err)
		return err
	}

	// A new worker just went from "starting" to registered: drop one pending
	// spawn so the starting count reflects reality. Best-effort; the time-based
	// prune is the backstop for spawns that never register.
	if inserted {
		if clearErr := s.ClearOnePendingSpawn(); clearErr != nil {
			slog.Warn("RegisterWorker: failed to clear pending spawn", "worker_id", workerID, "error", clearErr)
		}
	}

	slog.Info("Worker registered", "worker_id", workerID, "pod_name", podName)
	return nil
}

func (s *PGState) WorkerHeartbeat(workerID string) error {
	ctx := context.Background()

	result, err := s.pool.Exec(ctx, `
		UPDATE worker_pool SET heartbeat_at = NOW()
		WHERE worker_id = $1 AND status != $2
	`, workerID, common.WorkerExited)

	if err != nil {
		slog.Error("WorkerHeartbeat: update failed", "worker_id", workerID, "error", err)
		return err
	}

	if result.RowsAffected() == 0 {
		slog.Error("WorkerHeartbeat: worker not found or exited", "worker_id", workerID)
		return fmt.Errorf("worker %s not found or exited", workerID)
	}

	return nil
}

func (s *PGState) GetWorkerStatus(workerID string) (common.WorkerStatus, error) {
	ctx := context.Background()

	var status int
	err := s.pool.QueryRow(ctx, `
		SELECT status FROM worker_pool WHERE worker_id = $1
	`, workerID).Scan(&status)

	if err != nil {
		return 0, err
	}

	return common.WorkerStatus(status), nil
}

func (s *PGState) SetWorkerStatus(workerID string, status common.WorkerStatus) error {
	ctx := context.Background()

	_, err := s.pool.Exec(ctx, `
		UPDATE worker_pool SET status = $2 WHERE worker_id = $1
	`, workerID, status)
	if err != nil {
		slog.Error("SetWorkerStatus failed", "worker_id", workerID, "status", int(status), "error", err)
	} else {
		slog.Debug("state: worker status", "worker_id", workerID, "new", int(status))
	}
	return err
}

func (s *PGState) SetWorkerBusy(workerID string, jobKey string) error {
	ctx := context.Background()

	_, err := s.pool.Exec(ctx, `
		UPDATE worker_pool
		SET status = $2, current_job = $3, heartbeat_at = NOW()
		WHERE worker_id = $1
	`, workerID, common.WorkerBusy, jobKey)

	if err == nil {
		slog.Debug("state: worker busy", "worker_id", workerID, "job", jobKey)
	}
	return err
}

func (s *PGState) SetWorkerIdle(workerID string) error {
	ctx := context.Background()

	_, err := s.pool.Exec(ctx, `
		UPDATE worker_pool
		SET status = $2, current_job = NULL, jobs_completed = jobs_completed + 1, heartbeat_at = NOW()
		WHERE worker_id = $1
	`, workerID, common.WorkerIdle)

	if err == nil {
		slog.Debug("state: worker idle", "worker_id", workerID)
	}
	return err
}

// isRetryableTxErr reports whether err is a transient Postgres
// serialization/deadlock failure that is safe to retry: 40P01
// (deadlock_detected) or 40001 (serialization_failure).
func isRetryableTxErr(err error) bool {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		return pgErr.Code == "40P01" || pgErr.Code == "40001"
	}
	return false
}

// retryTx runs a self-contained transaction fn, retrying a bounded number
// of times when it fails with a transient serialization/deadlock error.
//
// Under concurrent multi-worker load, ClaimJob and CompleteJob touch the
// shared secondary indexes on job_info/job_status (e.g. many rows with an
// identical user_id and near-identical started_at land on the same btree
// leaf), which can deadlock even though each transaction locks rows in a
// consistent order. Postgres aborts one transaction with SQLSTATE 40P01;
// the documented remedy is for the loser to simply retry. fn must begin
// and commit/rollback its own transaction so each attempt is independent.
func retryTx(name string, fn func() error) error {
	const maxAttempts = 8
	var err error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		err = fn()
		if err == nil || !isRetryableTxErr(err) {
			return err
		}
		// Quadratic backoff with a little headroom; these transactions
		// are sub-millisecond, so the total wait stays small.
		backoff := time.Duration(attempt*attempt) * 5 * time.Millisecond
		slog.Warn("retryable tx conflict; retrying",
			"op", name, "attempt", attempt, "max_attempts", maxAttempts, "error", err)
		time.Sleep(backoff)
	}
	return err
}

func (s *PGState) ClaimJob(workerID string) (*queue.AnalyzeJob, error) {
	var job *queue.AnalyzeJob
	err := retryTx("ClaimJob", func() error {
		j, err := s.claimJobOnce(workerID)
		if err != nil {
			return err
		}
		job = j
		return nil
	})
	return job, err
}

func (s *PGState) claimJobOnce(workerID string) (*queue.AnalyzeJob, error) {
	ctx := context.Background()

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, fmt.Errorf("ClaimJob: begin tx: %w", err)
	}
	defer tx.Rollback(ctx)

	// Atomically claim the next queued job using FOR UPDATE SKIP LOCKED
	var sessionID int
	var owner, repo string
	err = tx.QueryRow(ctx, `
		SELECT js.session_id, js.owner, js.repo
		FROM job_status js
		JOIN analyze_jobs aj
		  ON aj.session_id = js.session_id
		 AND aj.owner = js.owner
		 AND aj.repo = js.repo
		WHERE js.status = $1
		ORDER BY js.session_id, js.owner, js.repo
		LIMIT 1
		FOR UPDATE SKIP LOCKED
	`, common.StatusQueued).Scan(&sessionID, &owner, &repo)

	if err != nil {
		// No queued jobs available (pgx returns ErrNoRows)
		return nil, nil
	}

	// Update the job status to InProgress
	_, err = tx.Exec(ctx, `
		UPDATE job_status
		SET status = $4
		WHERE session_id = $1 AND owner = $2 AND repo = $3
	`, sessionID, owner, repo, common.StatusInProgress)
	if err != nil {
		return nil, fmt.Errorf("ClaimJob: update job_status: %w", err)
	}

	// Update job_info with worker_id and started_at
	_, err = tx.Exec(ctx, `
		UPDATE job_info
		SET worker_id = $4, started_at = NOW()
		WHERE session_id = $1 AND owner = $2 AND repo = $3
	`, sessionID, owner, repo, workerID)
	if err != nil {
		return nil, fmt.Errorf("ClaimJob: update job_info: %w", err)
	}

	// Get the full AnalyzeJob payload
	var jsonBytes []byte
	err = tx.QueryRow(ctx, `
		SELECT payload FROM analyze_jobs
		WHERE session_id = $1 AND owner = $2 AND repo = $3
	`, sessionID, owner, repo).Scan(&jsonBytes)
	if err != nil {
		return nil, fmt.Errorf("ClaimJob: get analyze_job: %w", err)
	}

	if err = tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("ClaimJob: commit: %w", err)
	}

	var job queue.AnalyzeJob
	if err := json.Unmarshal(jsonBytes, &job); err != nil {
		return nil, fmt.Errorf("ClaimJob: unmarshal: %w", err)
	}

	slog.Info("Job claimed", "worker_id", workerID, "session_id", sessionID, "owner", owner, "repo", repo)
	return &job, nil
}

func (s *PGState) CompleteJob(workerID string, js common.JobSpec, status common.Status) error {
	return retryTx("CompleteJob", func() error {
		return s.completeJobOnce(workerID, js, status)
	})
}

func (s *PGState) completeJobOnce(workerID string, js common.JobSpec, status common.Status) error {
	ctx := context.Background()

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("CompleteJob: begin tx: %w", err)
	}
	defer tx.Rollback(ctx)

	// Update job status
	_, err = tx.Exec(ctx, `
		UPDATE job_status SET status = $4
		WHERE session_id = $1 AND owner = $2 AND repo = $3
	`, js.SessionID, js.Owner, js.Repo, status)
	if err != nil {
		return fmt.Errorf("CompleteJob: update job_status: %w", err)
	}

	// Update job_info completion time
	_, err = tx.Exec(ctx, `
		UPDATE job_info SET completed_at = NOW()
		WHERE session_id = $1 AND owner = $2 AND repo = $3
	`, js.SessionID, js.Owner, js.Repo)
	if err != nil {
		return fmt.Errorf("CompleteJob: update job_info: %w", err)
	}

	if err = tx.Commit(ctx); err != nil {
		return fmt.Errorf("CompleteJob: commit: %w", err)
	}

	slog.Info("Job completed", "worker_id", workerID, "job", js, "status", status)
	return nil
}

func (s *PGState) TryAdvisoryLock(lockID int64) (func(), bool, error) {
	ctx := context.Background()

	conn, err := s.pool.Acquire(ctx)
	if err != nil {
		return nil, false, err
	}

	var acquired bool
	err = conn.QueryRow(ctx, `SELECT pg_try_advisory_lock($1)`, lockID).Scan(&acquired)
	if err != nil {
		conn.Release()
		return nil, false, err
	}
	if !acquired {
		conn.Release()
		return nil, false, nil
	}

	unlock := func() {
		_, _ = conn.Exec(ctx, `SELECT pg_advisory_unlock($1)`, lockID)
		conn.Release()
	}
	return unlock, true, nil
}

func (s *PGState) TransitionJobsToQueued(specs []common.JobSpec) error {
	ctx := context.Background()

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("TransitionJobsToQueued: begin tx: %w", err)
	}
	defer tx.Rollback(ctx)

	for _, js := range specs {
		_, err := tx.Exec(ctx, `
			UPDATE job_status SET status = $4
			WHERE session_id = $1 AND owner = $2 AND repo = $3 AND status = $5
		`, js.SessionID, js.Owner, js.Repo, common.StatusQueued, common.StatusPending)
		if err != nil {
			slog.Error("TransitionJobsToQueued: failed", "job", js, "error", err)
			return err
		}
		slog.Debug("state: job status",
			"session", js.SessionID, "owner", js.Owner, "repo", js.Repo,
			"old", "pending", "new", "queued")
	}

	return tx.Commit(ctx)
}

func (s *PGState) GetQueuedJobCount() (int, error) {
	ctx := context.Background()

	var count int
	err := s.pool.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM job_status js
		JOIN analyze_jobs aj
		  ON aj.session_id = js.session_id
		 AND aj.owner = js.owner
		 AND aj.repo = js.repo
		WHERE js.status = $1
	`, common.StatusQueued).Scan(&count)

	return count, err
}

func (s *PGState) CountWorkersByStatus(statuses ...common.WorkerStatus) (int, error) {
	ctx := context.Background()

	if len(statuses) == 0 {
		return 0, nil
	}

	// Build IN clause
	args := make([]interface{}, len(statuses))
	placeholders := make([]string, len(statuses))
	for i, s := range statuses {
		args[i] = int(s)
		placeholders[i] = fmt.Sprintf("$%d", i+1)
	}

	query := fmt.Sprintf(`SELECT COUNT(*) FROM worker_pool WHERE status IN (%s)`,
		joinStrings(placeholders, ", "))

	var count int
	err := s.pool.QueryRow(ctx, query, args...).Scan(&count)

	return count, err
}

func (s *PGState) GetStaleWorkers(maxAge time.Duration) ([]string, error) {
	ctx := context.Background()

	rows, err := s.pool.Query(ctx, `
		SELECT worker_id FROM worker_pool
		WHERE heartbeat_at < NOW() - $1::interval
		  AND status IN ($2, $3)
	`, fmt.Sprintf("%d seconds", int(maxAge.Seconds())), common.WorkerIdle, common.WorkerBusy)
	if err != nil {
		slog.Error("GetStaleWorkers: query failed", "max_age", maxAge, "error", err)
		return nil, err
	}
	defer rows.Close()

	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			slog.Error("GetStaleWorkers: scan failed", "error", err)
			return nil, err
		}
		ids = append(ids, id)
	}

	return ids, rows.Err()
}

// ----- Pending spawn tracking ("starting" workers) -----

func (s *PGState) AddPendingSpawn(workflowUID, languageHint string) error {
	ctx := context.Background()
	_, err := s.pool.Exec(ctx, `
		INSERT INTO pending_spawns (workflow_uid, language_hint)
		VALUES ($1, $2)
		ON CONFLICT (workflow_uid) DO NOTHING
	`, workflowUID, languageHint)
	if err != nil {
		slog.Error("AddPendingSpawn: failed", "workflow_uid", workflowUID, "error", err)
	}
	return err
}

// ClearOnePendingSpawn deletes the oldest pending spawn (FIFO). Counts stay
// accurate even if the deleted row is not the exact one that registered: one
// registration removes one pending spawn.
func (s *PGState) ClearOnePendingSpawn() error {
	ctx := context.Background()
	_, err := s.pool.Exec(ctx, `
		DELETE FROM pending_spawns
		WHERE workflow_uid = (
			SELECT workflow_uid FROM pending_spawns
			ORDER BY spawned_at
			LIMIT 1
			FOR UPDATE SKIP LOCKED
		)
	`)
	if err != nil {
		slog.Error("ClearOnePendingSpawn: failed", "error", err)
	}
	return err
}

func (s *PGState) PrunePendingSpawns(maxAge time.Duration) error {
	ctx := context.Background()
	_, err := s.pool.Exec(ctx, `
		DELETE FROM pending_spawns WHERE spawned_at < NOW() - $1::interval
	`, fmt.Sprintf("%d seconds", int(maxAge.Seconds())))
	if err != nil {
		slog.Error("PrunePendingSpawns: failed", "max_age", maxAge, "error", err)
	}
	return err
}

func (s *PGState) CountPendingSpawns() (int, error) {
	ctx := context.Background()
	var count int
	err := s.pool.QueryRow(ctx, `SELECT COUNT(*) FROM pending_spawns`).Scan(&count)
	return count, err
}

func (s *PGState) GetPendingSpawns() ([]PendingSpawn, error) {
	ctx := context.Background()
	rows, err := s.pool.Query(ctx, `
		SELECT workflow_uid, language_hint, spawned_at
		FROM pending_spawns
		ORDER BY spawned_at
	`)
	if err != nil {
		slog.Error("GetPendingSpawns: query failed", "error", err)
		return nil, err
	}
	defer rows.Close()

	var spawns []PendingSpawn
	for rows.Next() {
		var ps PendingSpawn
		if err := rows.Scan(&ps.WorkflowUID, &ps.LanguageHint, &ps.SpawnedAt); err != nil {
			slog.Error("GetPendingSpawns: scan failed", "error", err)
			return nil, err
		}
		spawns = append(spawns, ps)
	}
	return spawns, rows.Err()
}

// ----- System-state view queries -----

func (s *PGState) SysViewServers(staleAfter time.Duration) ([]SysViewServer, error) {
	ctx := context.Background()
	staleSeconds := int(staleAfter / time.Second)
	if staleSeconds < 1 {
		staleSeconds = 1
	}
	rows, err := s.pool.Query(ctx, `
		SELECT sr.server_id,
		       CASE
		           WHEN sl.instance_id = sr.lease_id AND sl.expires_at > NOW()
		           THEN 'leader'
		           ELSE 'backup'
		       END AS role,
		       sr.heartbeat_at > NOW() - ($2 * INTERVAL '1 second') AS online,
		       EXTRACT(EPOCH FROM (NOW() - sr.heartbeat_at))::int AS hb_age_s
		FROM server_registry sr
		LEFT JOIN scheduler_lock sl
		  ON sl.lock_name = $1
		ORDER BY
		  CASE
		      WHEN sl.instance_id = sr.lease_id AND sl.expires_at > NOW() THEN 0
		      ELSE 1
		  END,
		  sr.server_id
	`, "mrva-scheduler", staleSeconds)
	if err != nil {
		slog.Error("SysViewServers: query failed", "error", err)
		return nil, err
	}
	defer rows.Close()

	var servers []SysViewServer
	for rows.Next() {
		var server SysViewServer
		if err := rows.Scan(&server.InstanceID, &server.Role, &server.Online,
			&server.HeartbeatAge); err != nil {
			slog.Error("SysViewServers: scan failed", "error", err)
			return nil, err
		}
		servers = append(servers, server)
	}
	return servers, rows.Err()
}

func (s *PGState) SysViewJobs() ([]SysViewJob, error) {
	ctx := context.Background()
	rows, err := s.pool.Query(ctx, `
		SELECT ji.session_id, ji.owner, ji.repo, ji.user_id,
		       COALESCE(js.status, -1) AS status,
		       ji.started_at, ji.completed_at,
		       ji.argo_workflow_id, ji.worker_id, ji.pack_sha1
		FROM job_info ji
		LEFT JOIN job_status js
		  ON js.session_id = ji.session_id AND js.owner = ji.owner AND js.repo = ji.repo
		ORDER BY ji.user_id, ji.session_id, ji.repo
	`)
	if err != nil {
		slog.Error("SysViewJobs: query failed", "error", err)
		return nil, err
	}
	defer rows.Close()

	var jobs []SysViewJob
	for rows.Next() {
		var j SysViewJob
		var started, completed *time.Time
		if err := rows.Scan(&j.SessionID, &j.Owner, &j.Repo, &j.UserID, &j.Status,
			&started, &completed, &j.ArgoWorkflowID, &j.WorkerID, &j.PackSHA1); err != nil {
			slog.Error("SysViewJobs: scan failed", "error", err)
			return nil, err
		}
		if started != nil {
			j.StartedAt = started.Format("2006-01-02 15:04:05")
		}
		if completed != nil {
			j.CompletedAt = completed.Format("2006-01-02 15:04:05")
		}
		jobs = append(jobs, j)
	}
	return jobs, rows.Err()
}

func (s *PGState) SysViewWorkers() ([]SysViewWorker, error) {
	ctx := context.Background()
	rows, err := s.pool.Query(ctx, `
		SELECT wp.worker_id, wp.status, COALESCE(wp.current_job, '') AS current_job,
		       COALESCE(ji.user_id, '') AS user_id,
		       wp.jobs_completed,
		       EXTRACT(EPOCH FROM (NOW() - wp.heartbeat_at))::int AS hb_age_s,
		       wp.argo_pod_name
		FROM worker_pool wp
		LEFT JOIN job_info ji
		  ON wp.current_job = ji.session_id || '/' || ji.owner || '/' || ji.repo
		ORDER BY wp.status, wp.worker_id
	`)
	if err != nil {
		slog.Error("SysViewWorkers: query failed", "error", err)
		return nil, err
	}
	defer rows.Close()

	var workers []SysViewWorker
	for rows.Next() {
		var w SysViewWorker
		if err := rows.Scan(&w.WorkerID, &w.Status, &w.CurrentJob, &w.UserID,
			&w.JobsCompleted, &w.HeartbeatAge, &w.ArgoPodName); err != nil {
			slog.Error("SysViewWorkers: scan failed", "error", err)
			return nil, err
		}
		workers = append(workers, w)
	}
	return workers, rows.Err()
}

func (s *PGState) GetWorkerArgoWorkflow(workerID string) (string, common.JobSpec, error) {
	ctx := context.Background()

	var argoWfID string
	var js common.JobSpec
	err := s.pool.QueryRow(ctx, `
		SELECT argo_workflow_id, session_id, owner, repo
		FROM job_info
		WHERE worker_id = $1
		LIMIT 1
	`, workerID).Scan(&argoWfID, &js.SessionID, &js.Owner, &js.Repo)

	if err != nil {
		return "", common.JobSpec{}, err
	}

	return argoWfID, js, nil
}

func (s *PGState) RequeueWorkerJob(workerID string) error {
	ctx := context.Background()

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("RequeueWorkerJob: begin tx: %w", err)
	}
	defer tx.Rollback(ctx)

	// Find and requeue any job held by this worker
	_, err = tx.Exec(ctx, `
		UPDATE job_status SET status = $1
		WHERE (session_id, owner, repo) IN (
			SELECT ji.session_id, ji.owner, ji.repo
			FROM job_info ji
			JOIN job_status js ON ji.session_id = js.session_id AND ji.owner = js.owner AND ji.repo = js.repo
			WHERE ji.worker_id = $2 AND js.status = $3
		)
	`, common.StatusQueued, workerID, common.StatusInProgress)

	if err != nil {
		slog.Error("RequeueWorkerJob: failed to requeue job_status", "worker_id", workerID, "error", err)
		return err
	}

	// Clear the worker_id on those jobs
	_, err = tx.Exec(ctx, `
		UPDATE job_info SET worker_id = '', started_at = NULL
		WHERE worker_id = $1
	`, workerID)

	if err != nil {
		slog.Error("RequeueWorkerJob: failed to clear job_info", "worker_id", workerID, "error", err)
		return err
	}

	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("RequeueWorkerJob: commit: %w", err)
	}

	slog.Debug("state: requeue worker job", "worker_id", workerID)
	return nil
}

func (s *PGState) CleanupExitedWorkers(maxAge time.Duration) error {
	ctx := context.Background()

	result, err := s.pool.Exec(ctx, `
		DELETE FROM worker_pool
		WHERE status = $1 AND heartbeat_at < NOW() - $2::interval
	`, common.WorkerExited, fmt.Sprintf("%d seconds", int(maxAge.Seconds())))

	if err != nil {
		return err
	}

	if n := result.RowsAffected(); n > 0 {
		slog.Info("Cleaned up exited workers", "count", n)
	}

	return nil
}

// joinStrings joins string slices (helper, avoids importing strings for this one use)
func joinStrings(elems []string, sep string) string {
	result := ""
	for i, e := range elems {
		if i > 0 {
			result += sep
		}
		result += e
	}
	return result
}

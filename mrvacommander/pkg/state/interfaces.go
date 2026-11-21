package state

import (
	"time"

	"github.com/hohn/mrvacommander/pkg/common"
	"github.com/hohn/mrvacommander/pkg/queue"
)

// StorageInterface defines the methods required for managing storage operations
// related to server state, e.g. job status, results, and artifacts.
type ServerState interface {
	// NextID increments and returns the next unique ID for a session.
	NextID() int

	// GetResult retrieves the analysis result for the specified job.
	GetResult(js common.JobSpec) (queue.AnalyzeResult, error)

	// GetJobSpecByRepoId retrieves the JobSpec for the specified job Repo ID.
	// TODO: fix this hacky logic
	GetJobSpecByRepoId(sessionId int, jobRepoId int) (common.JobSpec, error)

	// The repo id is uniquely determined by NameWithOwner
	GetRepoId(owner common.NameWithOwner) int

	// SetResult stores the analysis result for the specified session ID and repository.
	SetResult(js common.JobSpec, ar queue.AnalyzeResult)

	// SetResultAndStatus atomically stores the analysis result and updates job status
	// within a single transaction to prevent inconsistency on crash.
	SetResultAndStatus(js common.JobSpec, ar queue.AnalyzeResult, status common.Status)

	// GetJobList retrieves the list of analysis jobs for the specified session ID.
	GetJobList(sessionId int) ([]queue.AnalyzeJob, error)

	// GetJobInfo retrieves the job information for the specified job specification.
	GetJobInfo(js common.JobSpec) (common.JobInfo, error)

	// SetJobInfo stores the job information for the specified job specification.
	SetJobInfo(js common.JobSpec, ji common.JobInfo)

	// GetStatus retrieves the status of a job for the specified session ID and repository.
	GetStatus(js common.JobSpec) (common.Status, error)

	// GetSessionStatus retrieves the overall status summary for all jobs in a session.
	GetSessionStatus(sessionID int) (common.StatusSummary, error)

	// SetStatus stores the status of a job for the specified session ID and repository.
	SetStatus(js common.JobSpec, status common.Status)

	// AddJob adds an analysis job to the list of jobs for the specified session ID.
	AddJob(job queue.AnalyzeJob)

	// Scheduler-specific methods

	// GetPendingJobs retrieves all jobs with StatusPending across all sessions
	GetPendingJobs() ([]queue.AnalyzeJob, error)

	// GetRunningJobs retrieves all jobs with StatusInProgress across all sessions
	GetRunningJobs() ([]queue.AnalyzeJob, error)

	// GetJobsByStatus retrieves all jobs with the specified status
	GetJobsByStatus(status common.Status) ([]queue.AnalyzeJob, error)

	// GetUserJobCounts returns a map of user -> count of running jobs
	GetUserJobCounts() (map[string]int, error)

	// GetUserRecentRuntime returns the total runtime (in seconds) for jobs completed
	// by a user in the recent past (e.g., last hour or configurable window)
	GetUserRecentRuntime(user string, windowSeconds int) (float64, error)

	// GetRecentSessions retrieves session summaries for recent variant analysis requests
	// within the specified number of days
	GetRecentSessions(days int) ([]SessionSummary, error)

	// CancelSession cancels all jobs in a session
	// Returns the count of jobs that were cancelled
	CancelSession(sessionID int) (cancelledCount int, err error)

	// GetSessionOwnerRepo retrieves the controller repo owner/name for a session
	// This is used to validate cancel requests
	GetSessionOwnerRepo(sessionID int) (owner, repo string, err error)

	// Scheduler lock methods for leader election (kept for backward compat)

	// AcquireSchedulerLock attempts to acquire a named lock for the given instance.
	AcquireSchedulerLock(lockName, leaseID, serverID string, expirationSeconds int, lastLogTime *time.Time, lastHolder *SchedulerLockHolder, throttle time.Duration) (bool, error)

	// RenewSchedulerLock extends the expiration time of a lock held by the given instance.
	RenewSchedulerLock(lockName, leaseID string, expirationSeconds int, lastLogTime *time.Time, throttle time.Duration) (bool, error)

	// ReleaseSchedulerLock releases a lock held by the given instance.
	ReleaseSchedulerLock(lockName, leaseID string) error

	// GetSchedulerLockHolder returns the current lease and display identities.
	GetSchedulerLockHolder(lockName string) (SchedulerLockHolder, error)

	// RegisterServer records a server process for shared status display,
	// replacing any previous process with the same operator-facing server ID.
	RegisterServer(leaseID, serverID string) error

	// ServerHeartbeat marks a registered server process as alive.
	ServerHeartbeat(leaseID, serverID string) error

	// Worker pool methods

	// RegisterWorker registers a new worker in the worker_pool table.
	RegisterWorker(workerID, podName string) error

	// WorkerHeartbeat updates the worker's heartbeat timestamp.
	WorkerHeartbeat(workerID string) error

	// GetWorkerStatus returns the current status of a worker.
	GetWorkerStatus(workerID string) (common.WorkerStatus, error)

	// SetWorkerStatus updates a worker's status.
	SetWorkerStatus(workerID string, status common.WorkerStatus) error

	// SetWorkerBusy marks a worker as Busy with the given job key.
	SetWorkerBusy(workerID string, jobKey string) error

	// SetWorkerIdle marks a worker as Idle with no current job.
	SetWorkerIdle(workerID string) error

	// ClaimJob atomically claims the next available Queued job for a worker.
	// Uses FOR UPDATE SKIP LOCKED for safe concurrent claiming.
	// Returns nil, nil if no jobs available.
	ClaimJob(workerID string) (*queue.AnalyzeJob, error)

	// CompleteJob marks a job as completed and updates the worker to Idle.
	CompleteJob(workerID string, js common.JobSpec, status common.Status) error

	// TryAdvisoryLock attempts to acquire a PostgreSQL advisory lock.
	// Returns (unlock, true, nil) if the lock was acquired; the caller
	// must call unlock() to release the lock on the same connection.
	// Returns (nil, false, nil) if the lock is held by another session.
	TryAdvisoryLock(lockID int64) (unlock func(), acquired bool, err error)

	// TransitionJobsToQueued moves selected jobs from Pending to Queued status.
	TransitionJobsToQueued(specs []common.JobSpec) error

	// GetQueuedJobCount returns the number of Queued jobs backed by a payload.
	GetQueuedJobCount() (int, error)

	// CountWorkersByStatus counts active workers in the given statuses.
	CountWorkersByStatus(statuses ...common.WorkerStatus) (int, error)

	// GetStaleWorkers returns worker IDs whose heartbeat is older than maxAge.
	GetStaleWorkers(maxAge time.Duration) ([]string, error)

	// GetWorkerArgoWorkflow returns the ArgoWorkflowID and JobSpec for a worker's current job.
	// Must be called before RequeueWorkerJob, which clears the worker_id link.
	GetWorkerArgoWorkflow(workerID string) (string, common.JobSpec, error)

	// RequeueWorkerJob requeues any job held by a dead/draining worker back to Queued.
	RequeueWorkerJob(workerID string) error

	// CleanupExitedWorkers removes WorkerExited rows older than maxAge.
	CleanupExitedWorkers(maxAge time.Duration) error

	// Pending spawn methods ("starting" workers)

	// AddPendingSpawn records a worker spawn that has not yet registered in
	// worker_pool, so the startup lag is visible and counted against demand.
	AddPendingSpawn(workflowUID, languageHint string) error

	// ClearOnePendingSpawn removes the oldest pending spawn, called when a
	// worker registers so the "starting" count decrements accurately.
	ClearOnePendingSpawn() error

	// PrunePendingSpawns deletes spawn records older than maxAge (a straggler
	// that never registered, e.g. a failed start).
	PrunePendingSpawns(maxAge time.Duration) error

	// CountPendingSpawns returns the number of in-flight ("starting") spawns.
	CountPendingSpawns() (int, error)

	// GetPendingSpawns returns the current in-flight spawns for display.
	GetPendingSpawns() ([]PendingSpawn, error)

	// SysViewJobs returns every job_info row (joined with job_status) for the
	// system-state view, grouped client-side into users -> sessions -> jobs.
	SysViewJobs() ([]SysViewJob, error)

	// SysViewWorkers returns every worker_pool row, coupled to the user that
	// owns its current job, for the worker-pool grid.
	SysViewWorkers() ([]SysViewWorker, error)

	// SysViewServers returns the registered servers with roles derived from the
	// current scheduler lease and liveness derived from their heartbeats.
	SysViewServers(staleAfter time.Duration) ([]SysViewServer, error)
}

// SchedulerLockHolder separates the process-unique lease token from the
// operator-facing server identity. Multiple processes may be misconfigured
// with the same ServerID without sharing ownership of the lease.
type SchedulerLockHolder struct {
	LeaseID  string
	ServerID string
}

// SysViewServer is one registered server process and its elected role.
type SysViewServer struct {
	InstanceID   string `json:"instance_id"`
	Role         string `json:"role"`
	Online       bool   `json:"online"`
	HeartbeatAge int    `json:"hb_age_s"`
}

// SysViewJob is one job_info row (plus its job_status) for the system view.
type SysViewJob struct {
	SessionID      int    `json:"session_id"`
	Owner          string `json:"owner"`
	Repo           string `json:"repo"`
	UserID         string `json:"user"`
	Status         int    `json:"status"` // job_status.status, or -1 if absent
	StartedAt      string `json:"started_at"`
	CompletedAt    string `json:"completed_at"`
	ArgoWorkflowID string `json:"argo_workflow_id"`
	WorkerID       string `json:"worker_id"`
	PackSHA1       string `json:"pack_sha1"` // SHA1 (hex) of the query pack, or "" if unknown
}

// SysViewWorker is one worker_pool row, coupled to the user of its current job.
type SysViewWorker struct {
	WorkerID      string `json:"worker_id"`
	Status        int    `json:"status"` // common.WorkerStatus
	CurrentJob    string `json:"current_job"`
	UserID        string `json:"user_id"`
	JobsCompleted int    `json:"jobs_completed"`
	HeartbeatAge  int    `json:"hb_age_s"`
	ArgoPodName   string `json:"argo_pod_name"`
}

// PendingSpawn is a worker spawn that has not yet registered in worker_pool.
// It represents a "starting" worker during the certain-but-variable startup lag.
type PendingSpawn struct {
	WorkflowUID  string
	LanguageHint string
	SpawnedAt    time.Time
}

// SessionSummary provides an overview of a variant analysis session
type SessionSummary struct {
	SessionID     int
	User          string
	Language      string
	CreatedAt     string
	TotalJobs     int
	PendingJobs   int
	RunningJobs   int
	CompletedJobs int
	// AvgCompletedJobSeconds is the average runtime for completed jobs in the session.
	AvgCompletedJobSeconds float64
	FailedJobs             int
	CancelledJobs          int
}

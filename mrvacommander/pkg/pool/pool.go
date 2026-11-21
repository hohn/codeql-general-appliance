package pool

import (
	"fmt"
	"log/slog"
	"os"
	"sort"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/google/uuid"
	"github.com/hohn/mrvacommander/pkg/common"
	"github.com/hohn/mrvacommander/pkg/queue"
	"github.com/hohn/mrvacommander/pkg/scheduler"
	"github.com/hohn/mrvacommander/pkg/state"
)

const (
	// The lease gives one server ownership of the pool manager. The advisory
	// lock remains as fencing around queue/scale mutations during failover.
	leaderLockName            = "mrva-scheduler"
	queueAdvisoryLockID int64 = 73001
)

// Config holds the configuration for the pool manager.
type Config struct {
	MaxWorkers          int           // W_max: maximum concurrent workers
	IdleTimeout         time.Duration // T_idle: before idle worker exits (read by the worker itself)
	HeartbeatExpiry     time.Duration // T_hb_exp: dead worker threshold
	ScaleCheckInterval  time.Duration // T_scale: pool size evaluation period
	RecentRuntimeWindow int           // T_w: seconds for fairness runtime calculation
	LeaderLeaseDuration time.Duration // Lease lifetime before a backup may take over
	LeaderCheckInterval time.Duration // How often the leader renews / backups attempt acquisition
}

// NewConfigFromEnv creates a Config from environment variables with defaults.
func NewConfigFromEnv() Config {
	c := Config{
		MaxWorkers:          10,
		IdleTimeout:         300 * time.Second,
		HeartbeatExpiry:     120 * time.Second,
		ScaleCheckInterval:  15 * time.Second,
		RecentRuntimeWindow: 3600,
		LeaderLeaseDuration: 30 * time.Second,
		LeaderCheckInterval: 10 * time.Second,
	}

	if v := os.Getenv("MRVA_POOL_MAX_WORKERS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.MaxWorkers = n
		}
	}
	if v := os.Getenv("MRVA_POOL_IDLE_TIMEOUT_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.IdleTimeout = time.Duration(n) * time.Second
		}
	}
	if v := os.Getenv("MRVA_POOL_HEARTBEAT_EXPIRY_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.HeartbeatExpiry = time.Duration(n) * time.Second
		}
	}
	if v := os.Getenv("MRVA_POOL_SCALE_CHECK_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.ScaleCheckInterval = time.Duration(n) * time.Second
		}
	}
	if v := os.Getenv("MRVA_SCHEDULER_RECENT_RUNTIME_WINDOW_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.RecentRuntimeWindow = n
		}
	}
	if v := os.Getenv("MRVA_POOL_LEADER_LEASE_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 1 {
			c.LeaderLeaseDuration = time.Duration(n) * time.Second
		} else {
			slog.Warn("Invalid MRVA_POOL_LEADER_LEASE_SECONDS, using default",
				"value", v, "default", c.LeaderLeaseDuration)
		}
	}
	if v := os.Getenv("MRVA_POOL_LEADER_CHECK_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.LeaderCheckInterval = time.Duration(n) * time.Second
		} else {
			slog.Warn("Invalid MRVA_POOL_LEADER_CHECK_SECONDS, using default",
				"value", v, "default", c.LeaderCheckInterval)
		}
	}
	if c.LeaderCheckInterval >= c.LeaderLeaseDuration {
		safeCheck := c.LeaderLeaseDuration / 3
		if safeCheck < time.Second {
			safeCheck = time.Second
		}
		slog.Warn("Pool leader check interval must be shorter than its lease; using safe interval",
			"check_interval", c.LeaderCheckInterval,
			"lease_duration", c.LeaderLeaseDuration,
			"safe_check_interval", safeCheck)
		c.LeaderCheckInterval = safeCheck
	}

	return c
}

// ServerRole is this server's current pool-manager election role.
type ServerRole string

const (
	ServerRoleLeader ServerRole = "leader"
	ServerRoleBackup ServerRole = "backup"
)

// ServerStatus is the local server's view of the pool-manager election.
type ServerStatus struct {
	InstanceID string     `json:"instance_id"`
	Role       ServerRole `json:"role"`
	LeaderID   string     `json:"leader_id"`
	LockName   string     `json:"lock_name"`
}

type leaderState interface {
	AcquireSchedulerLock(lockName, leaseID, serverID string, expirationSeconds int, lastLogTime *time.Time, lastHolder *state.SchedulerLockHolder, throttle time.Duration) (bool, error)
	RenewSchedulerLock(lockName, leaseID string, expirationSeconds int, lastLogTime *time.Time, throttle time.Duration) (bool, error)
	ReleaseSchedulerLock(lockName, leaseID string) error
}

type serverRegistryState interface {
	RegisterServer(leaseID, serverID string) error
	ServerHeartbeat(leaseID, serverID string) error
}

// PoolManager owns fair job queueing (Pending -> Queued), demand-based worker
// spawning, and dead-worker reaping. Workers are long-lived: they claim queued
// jobs from Postgres, and self-terminate after an idle timeout when no work
// remains, so the pool scales down on its own without an explicit decay step.
type PoolManager struct {
	config      Config
	state       state.ServerState
	leaderState leaderState
	registry    serverRegistryState
	argo        scheduler.ArgoWorkflowClient
	serverID    string
	leaseID     string
	stopChan    chan struct{}
	doneChan    chan struct{}
	wakeChan    chan struct{}
	stopOnce    sync.Once
	stopping    atomic.Bool

	statusMu        sync.RWMutex
	status          ServerStatus
	leaseValidUntil time.Time
	electionMu      sync.Mutex

	lastLockHeldLog    time.Time
	lastLockHeldHolder state.SchedulerLockHolder
	lastLockRenewedLog time.Time

	// languageHint labels spawned worker pods; captured from the most recently
	// queued job. Purely cosmetic (pool-mode workers get no --job flag).
	languageHint string
}

// NewPoolManager creates a new pool manager.
func NewPoolManager(config Config, st state.ServerState, argo scheduler.ArgoWorkflowClient) *PoolManager {
	if config.LeaderLeaseDuration <= time.Second {
		config.LeaderLeaseDuration = 30 * time.Second
	}
	if config.LeaderCheckInterval <= 0 || config.LeaderCheckInterval >= config.LeaderLeaseDuration {
		config.LeaderCheckInterval = config.LeaderLeaseDuration / 3
	}

	serverID := os.Getenv("MRVA_SERVER_ID")
	if serverID == "" {
		hostname, err := os.Hostname()
		if err != nil {
			hostname = "unknown"
		}
		serverID = fmt.Sprintf("%s-%d", hostname, os.Getpid())
	}

	return &PoolManager{
		config:      config,
		state:       st,
		leaderState: st,
		registry:    st,
		argo:        argo,
		serverID:    serverID,
		leaseID:     uuid.NewString(),
		stopChan:    make(chan struct{}),
		doneChan:    make(chan struct{}),
		wakeChan:    make(chan struct{}, 1),
		status: ServerStatus{
			InstanceID: serverID,
			Role:       ServerRoleBackup,
			LockName:   leaderLockName,
		},
	}
}

// Start begins the leader election and pool manager loops. Only the elected
// leader performs pool cycles; backups keep renewing their view of the holder.
func (p *PoolManager) Start() {
	defer close(p.doneChan)

	if err := p.registry.RegisterServer(p.leaseID, p.serverID); err != nil {
		slog.Error("Failed to register pool manager server",
			"instance_id", p.serverID, "lease_id", p.leaseID, "error", err)
	}

	slog.Info("Starting pool manager with leader election",
		"instance_id", p.serverID,
		"lease_id", p.leaseID,
		"max_workers", p.config.MaxWorkers,
		"scale_check_interval", p.config.ScaleCheckInterval,
		"leader_lease", p.config.LeaderLeaseDuration,
		"leader_check_interval", p.config.LeaderCheckInterval)

	scaleTicker := time.NewTicker(p.config.ScaleCheckInterval)
	defer scaleTicker.Stop()

	leadershipDone := make(chan struct{})
	go p.leadershipLoop(leadershipDone)
	defer func() {
		<-leadershipDone
		p.releaseLeadership()
	}()

	// Elect immediately; the old scheduler waited for its first leader tick,
	// unnecessarily leaving every fresh deployment without a leader.
	if p.maintainLeadership() {
		p.cycle()
	}

	for {
		select {
		case <-p.stopChan:
			slog.Info("Pool manager stopping", "instance_id", p.serverID)
			return

		case <-scaleTicker.C:
			if p.maintainLeadership() {
				p.cycle()
			}

		case <-p.wakeChan:
			if p.maintainLeadership() {
				p.cycle()
			}
		}
	}
}

func (p *PoolManager) leadershipLoop(done chan<- struct{}) {
	defer close(done)
	ticker := time.NewTicker(p.config.LeaderCheckInterval)
	defer ticker.Stop()
	for {
		select {
		case <-p.stopChan:
			return
		case <-ticker.C:
			p.maintainLeadership()
		}
	}
}

// Stop signals the pool manager to shut down and waits a bounded time for
// lease release. The process may still exit and let the lease expire if an
// external dependency has blocked a pool operation.
func (p *PoolManager) Stop() {
	p.stopOnce.Do(func() {
		p.stopping.Store(true)
		p.setRole(ServerRoleBackup, "")
		close(p.stopChan)
	})
	timer := time.NewTimer(10 * time.Second)
	defer timer.Stop()
	select {
	case <-p.doneChan:
	case <-timer.C:
		slog.Warn("Timed out waiting for pool manager shutdown",
			"instance_id", p.serverID, "timeout", 10*time.Second)
	}
}

// TriggerScheduling wakes up the pool manager to run an immediate cycle.
func (p *PoolManager) TriggerScheduling() {
	select {
	case p.wakeChan <- struct{}{}:
	default:
	}
}

// Status returns a concurrency-safe snapshot of this server's election state.
func (p *PoolManager) Status() ServerStatus {
	p.statusMu.RLock()
	defer p.statusMu.RUnlock()
	status := p.status
	if status.Role == ServerRoleLeader &&
		(p.leaseValidUntil.IsZero() || !time.Now().Before(p.leaseValidUntil)) {
		status.Role = ServerRoleBackup
		status.LeaderID = ""
	}
	return status
}

// IsLeader reports whether this server currently owns the pool-manager lease.
func (p *PoolManager) IsLeader() bool {
	return p.Status().Role == ServerRoleLeader
}

// ServerStaleAfter is the heartbeat age after which sysview marks a registered
// server offline. It matches the lease duration used for failover.
func (p *PoolManager) ServerStaleAfter() time.Duration {
	return p.config.LeaderLeaseDuration
}

func (p *PoolManager) updateRole(role ServerRole, leaderID string, leaseValidUntil time.Time) {
	p.statusMu.Lock()
	previous := p.status
	p.status.Role = role
	p.status.LeaderID = leaderID
	p.leaseValidUntil = leaseValidUntil
	current := p.status
	p.statusMu.Unlock()

	if previous.Role != current.Role || previous.LeaderID != current.LeaderID {
		slog.Info("Pool manager election status changed",
			"instance_id", current.InstanceID,
			"role", current.Role,
			"leader_id", current.LeaderID)
	}
}

func (p *PoolManager) setRole(role ServerRole, leaderID string) {
	p.updateRole(role, leaderID, time.Time{})
}

func (p *PoolManager) setLeader(leaseValidUntil time.Time) {
	p.updateRole(ServerRoleLeader, p.serverID, leaseValidUntil)
}

// maintainLeadership acquires or renews the durable PostgreSQL lease and
// reports whether this process owns it. Calls are serialized so the periodic
// renewal loop can run independently from potentially slow pool cycles.
func (p *PoolManager) maintainLeadership() bool {
	p.electionMu.Lock()
	defer p.electionMu.Unlock()

	if p.stopping.Load() {
		return false
	}
	if err := p.registry.ServerHeartbeat(p.leaseID, p.serverID); err != nil {
		slog.Error("Failed to update server heartbeat",
			"instance_id", p.serverID, "lease_id", p.leaseID, "error", err)
	}

	const logThrottle = 5 * time.Minute
	leaseSeconds := int(p.config.LeaderLeaseDuration / time.Second)
	attemptStarted := time.Now()

	if p.IsLeader() {
		renewed, err := p.leaderState.RenewSchedulerLock(
			leaderLockName, p.leaseID, leaseSeconds,
			&p.lastLockRenewedLog, logThrottle)
		if err != nil {
			slog.Error("Failed to renew pool manager leadership",
				"instance_id", p.serverID, "lease_id", p.leaseID, "error", err)
			p.setRole(ServerRoleBackup, "")
			return false
		}
		if !renewed {
			slog.Warn("Lost pool manager leadership",
				"instance_id", p.serverID, "lease_id", p.leaseID)
			p.setRole(ServerRoleBackup, "")
			return false
		}
		if p.stopping.Load() {
			p.setRole(ServerRoleBackup, "")
			return false
		}
		// PostgreSQL computes expiry after this request starts, so using
		// request-start + duration is a conservative local deadline.
		p.setLeader(attemptStarted.Add(p.config.LeaderLeaseDuration))
		return true
	}

	acquired, err := p.leaderState.AcquireSchedulerLock(
		leaderLockName, p.leaseID, p.serverID, leaseSeconds,
		&p.lastLockHeldLog, &p.lastLockHeldHolder, logThrottle)
	if err != nil {
		slog.Error("Failed to acquire pool manager leadership",
			"instance_id", p.serverID, "lease_id", p.leaseID, "error", err)
		p.setRole(ServerRoleBackup, "")
		return false
	}
	if p.stopping.Load() {
		p.setRole(ServerRoleBackup, "")
		return false
	}
	if !acquired {
		p.setRole(ServerRoleBackup, p.lastLockHeldHolder.ServerID)
		return false
	}

	p.setLeader(attemptStarted.Add(p.config.LeaderLeaseDuration))
	return true
}

func (p *PoolManager) releaseLeadership() {
	p.electionMu.Lock()
	defer p.electionMu.Unlock()

	if err := p.leaderState.ReleaseSchedulerLock(leaderLockName, p.leaseID); err != nil {
		slog.Error("Failed to release pool manager leadership",
			"instance_id", p.serverID, "lease_id", p.leaseID, "error", err)
	}
	p.setRole(ServerRoleBackup, "")
}

// CancelRunningJobsForSession cancels all running jobs for a session.
// In the pool model, workers self-manage execution, so we cancel by
// updating job status to Canceled. Workers will see this on their next check.
func (p *PoolManager) CancelRunningJobsForSession(sessionID int) (int, error) {
	// Cancel pending/queued jobs in the database directly
	cancelledCount, err := p.state.CancelSession(sessionID)
	if err != nil {
		return 0, err
	}

	// Also try to cancel any Argo workflows (for jobs already submitted)
	allRunningJobs, err := p.state.GetRunningJobs()
	if err != nil {
		return cancelledCount, nil // already cancelled DB-side jobs
	}

	for _, job := range allRunningJobs {
		if job.Spec.SessionID != sessionID {
			continue
		}
		jobInfo, err := p.state.GetJobInfo(job.Spec)
		if err != nil || jobInfo.ArgoWorkflowID == "" {
			continue
		}
		_, _ = p.argo.CancelWorkflow(jobInfo.ArgoWorkflowID)
	}

	return cancelledCount, nil
}

// cycle runs one iteration of: reap dead workers, queue jobs (Pending->Queued),
// spawn workers to match demand, and clean up exited workers.
func (p *PoolManager) cycle() {
	if !p.IsLeader() {
		return
	}
	slog.Debug("Pool cycle start")
	if err := p.reapDeadWorkers(); err != nil {
		slog.Error("Pool cycle: reap dead workers failed", "error", err)
	}

	if !p.IsLeader() {
		return
	}
	if err := p.queueJobs(); err != nil {
		slog.Error("Pool cycle: queue jobs failed", "error", err)
	}

	if !p.IsLeader() {
		return
	}
	if err := p.scaleWorkers(); err != nil {
		slog.Error("Pool cycle: scale workers failed", "error", err)
	}

	if !p.IsLeader() {
		return
	}
	if err := p.cleanupExitedWorkers(); err != nil {
		slog.Error("Pool cycle: cleanup exited workers failed", "error", err)
	}
}

// queueJobs runs fair scheduling to transition Pending jobs to Queued,
// protected by a PostgreSQL advisory lock.
func (p *PoolManager) queueJobs() error {
	slog.Debug("Pool: queueing jobs")
	unlock, locked, err := p.state.TryAdvisoryLock(queueAdvisoryLockID)
	if err != nil {
		return fmt.Errorf("advisory lock: %w", err)
	}
	if !locked {
		slog.Debug("Pool: queueJobs skipped — advisory lock held by another replica")
		return nil
	}
	defer unlock()

	// Calculate available capacity
	busyCount, err := p.state.CountWorkersByStatus(common.WorkerBusy)
	if err != nil {
		return err
	}
	queuedCount, err := p.state.GetQueuedJobCount()
	if err != nil {
		return err
	}
	available := p.config.MaxWorkers - busyCount - queuedCount
	slog.Debug("Pool: capacity check",
		"busy_count", busyCount, "queued_count", queuedCount,
		"max_workers", p.config.MaxWorkers, "available", available)
	if available <= 0 {
		return nil
	}

	// Get pending jobs
	pendingJobs, err := p.state.GetPendingJobs()
	if err != nil {
		return err
	}
	if len(pendingJobs) == 0 {
		slog.Debug("Pool: no pending jobs found")
		return nil
	}

	slog.Debug("Pool: found jobs", "count", len(pendingJobs))

	// Group by user
	jobsByUser := make(map[string][]queue.AnalyzeJob)
	for _, job := range pendingJobs {
		jobInfo, err := p.state.GetJobInfo(job.Spec)
		if err != nil {
			continue
		}
		user := jobInfo.User
		if user == "" {
			user = "UNKNOWN"
		}
		jobsByUser[user] = append(jobsByUser[user], job)
	}

	// Get fairness metrics
	userCounts, err := p.state.GetUserJobCounts()
	if err != nil {
		userCounts = make(map[string]int)
	}

	userRuntimes := make(map[string]float64)
	for user := range jobsByUser {
		rt, err := p.state.GetUserRecentRuntime(user, p.config.RecentRuntimeWindow)
		if err != nil {
			rt = 0
		}
		userRuntimes[user] = rt
	}

	// Fair selection (same algorithm as the old scheduler)
	selected := selectJobsFairly(jobsByUser, userCounts, userRuntimes, available)

	if len(selected) == 0 {
		return nil
	}

	// Transition to Queued. Workers (spawned by scaleWorkers) claim these jobs
	// directly from Postgres via ClaimJob; the pool manager does not hand jobs
	// to specific workers.
	specs := make([]common.JobSpec, len(selected))
	for i, job := range selected {
		specs[i] = job.Spec
	}
	// Remember a language for labelling spawned worker pods (cosmetic).
	if len(selected) > 0 {
		p.languageHint = string(selected[len(selected)-1].QueryLanguage)
	}

	slog.Info("Queueing jobs", "count", len(specs), "available_slots", available)
	if err := p.state.TransitionJobsToQueued(specs); err != nil {
		return err
	}

	return nil
}

// scaleWorkers spawns long-lived workers to match outstanding demand. It is
// decoupled from individual jobs: rather than one worker per job, it targets
// one worker per unit of in-flight work (a busy worker for each running job, a
// fresh worker for each queued-but-unclaimed job), capped at MaxWorkers.
//
// Scale-down is implicit: idle workers self-terminate after their idle timeout,
// so no explicit decay step is needed.
//
// Guarded by the same advisory lock as queueJobs so that concurrent pool
// managers do not both spawn against the same demand snapshot.
func (p *PoolManager) scaleWorkers() error {
	unlock, locked, err := p.state.TryAdvisoryLock(queueAdvisoryLockID)
	if err != nil {
		return fmt.Errorf("advisory lock: %w", err)
	}
	if !locked {
		return nil // another replica is scaling
	}
	defer unlock()

	// Drop spawn records old enough that the worker has either registered
	// (already cleared on registration) or failed to start (a later cycle
	// re-spawns). This is the backstop for spawns that never registered.
	if err := p.state.PrunePendingSpawns(p.config.HeartbeatExpiry); err != nil {
		slog.Error("scaleWorkers: prune pending spawns failed", "error", err)
	}

	busy, err := p.state.CountWorkersByStatus(common.WorkerBusy)
	if err != nil {
		return err
	}
	idle, err := p.state.CountWorkersByStatus(common.WorkerIdle)
	if err != nil {
		return err
	}
	queued, err := p.state.GetQueuedJobCount()
	if err != nil {
		return err
	}

	alive := busy + idle
	pending, err := p.state.CountPendingSpawns()
	if err != nil {
		return err
	}

	// Demand = one worker per busy job + one per queued job, capped at MaxWorkers.
	target := busy + queued
	if target > p.config.MaxWorkers {
		target = p.config.MaxWorkers
	}

	// Idle workers and already-spawned-but-unregistered workers cover part of
	// the target; spawn only the remaining deficit.
	toSpawn := target - alive - pending
	slog.Debug("Pool: scale check",
		"busy", busy, "idle", idle, "queued", queued,
		"pending_spawns", pending, "max_workers", p.config.MaxWorkers,
		"target", target, "to_spawn", toSpawn)
	if toSpawn <= 0 {
		return nil
	}

	slog.Info("Scaling up workers", "to_spawn", toSpawn,
		"alive", alive, "pending", pending, "target", target)
	for i := 0; i < toSpawn; i++ {
		if !p.IsLeader() {
			return nil
		}
		if err := p.spawnWorker(); err != nil {
			slog.Error("Failed to spawn worker", "error", err)
			break
		}
	}
	return nil
}

// spawnWorker starts one long-lived pool worker (a local process in standalone
// mode, an Argo pod in production). The worker receives no specific job; it
// claims queued jobs from Postgres itself. The job argument only labels the
// spawned pod, so an empty job carrying just the language hint is sufficient.
func (p *PoolManager) spawnWorker() error {
	job := queue.AnalyzeJob{QueryLanguage: queue.QueryLanguage(p.languageHint)}
	workflowUID, err := p.argo.SubmitWorkflow(job)
	if err != nil {
		return fmt.Errorf("SubmitWorkflow: %w", err)
	}
	if !p.IsLeader() {
		if _, cancelErr := p.argo.CancelWorkflow(workflowUID); cancelErr != nil {
			slog.Warn("Failed to cancel worker spawned after leadership loss",
				"workflow_uid", workflowUID, "error", cancelErr)
		}
		return fmt.Errorf("pool leadership lost while spawning worker")
	}
	// Record the spawn as a "starting" worker so the startup lag is visible and
	// counted against demand. Cleared when the worker registers, or pruned by
	// PrunePendingSpawns if it never does.
	if err := p.state.AddPendingSpawn(workflowUID, p.languageHint); err != nil {
		slog.Error("spawnWorker: failed to record pending spawn", "workflow_uid", workflowUID, "error", err)
	}
	slog.Info("Spawned pool worker", "workflow_uid", workflowUID)
	return nil
}

// reapDeadWorkers marks workers whose heartbeat has expired as Exited, cancels
// their Argo workflow if any, and resets the job they held back to Pending so a
// future cycle re-queues it and scaleWorkers spawns a fresh worker for it. This
// is the sole job-recovery path now that jobs are no longer individually
// tracked against Argo.
func (p *PoolManager) reapDeadWorkers() error {
	stale, err := p.state.GetStaleWorkers(p.config.HeartbeatExpiry)
	if err != nil {
		slog.Error("reapDeadWorkers: failed to get stale workers", "heartbeat_expiry", p.config.HeartbeatExpiry, "error", err)
		return err
	}

	for _, workerID := range stale {
		slog.Warn("Reaping dead worker", "worker_id", workerID)

		// Look up the Argo workflow before requeuing (requeue clears worker_id)
		argoWfID, jobSpec, lookupErr := p.state.GetWorkerArgoWorkflow(workerID)
		if lookupErr == nil && argoWfID != "" {
			if _, cancelErr := p.argo.CancelWorkflow(argoWfID); cancelErr != nil {
				slog.Warn("Failed to cancel Argo workflow for reaped worker",
					"worker_id", workerID, "workflow_id", argoWfID, "error", cancelErr)
			} else {
				slog.Info("Cancelled Argo workflow for reaped worker",
					"worker_id", workerID, "workflow_id", argoWfID)
			}
		}

		if err := p.state.RequeueWorkerJob(workerID); err != nil {
			slog.Error("Failed to requeue job for dead worker", "worker_id", workerID, "error", err)
		}

		// Reset requeued job to Pending with cleared ArgoWorkflowID so it gets re-submitted
		if lookupErr == nil && jobSpec != (common.JobSpec{}) {
			p.state.SetStatus(jobSpec, common.StatusPending)
			jobInfo, infoErr := p.state.GetJobInfo(jobSpec)
			if infoErr == nil {
				jobInfo.ArgoWorkflowID = ""
				p.state.SetJobInfo(jobSpec, jobInfo)
			}
		}

		if err := p.state.SetWorkerStatus(workerID, common.WorkerExited); err != nil {
			slog.Error("Failed to mark worker as exited", "worker_id", workerID, "error", err)
		}
	}

	return nil
}

// cleanupExitedWorkers removes old WorkerExited rows from the worker_pool table.
func (p *PoolManager) cleanupExitedWorkers() error {
	return p.state.CleanupExitedWorkers(7 * 24 * time.Hour)
}

// selectJobsFairly implements fair scheduling across users: each user gets a
// roughly equal share of available slots, with runtime-based tie-breaking.
func selectJobsFairly(
	jobsByUser map[string][]queue.AnalyzeJob,
	userCounts map[string]int,
	userRuntimes map[string]float64,
	slotsAvailable int,
) []queue.AnalyzeJob {
	if len(jobsByUser) == 0 || slotsAvailable <= 0 {
		return nil
	}

	type userInfo struct {
		user           string
		pendingCount   int
		runningCount   int
		recentRuntime  float64
		jobsToSchedule int
	}

	users := make([]*userInfo, 0, len(jobsByUser))
	for user, jobs := range jobsByUser {
		users = append(users, &userInfo{
			user:          user,
			pendingCount:  len(jobs),
			runningCount:  userCounts[user],
			recentRuntime: userRuntimes[user],
		})
	}

	// Sort by: running count asc, runtime asc, pending count desc
	sort.Slice(users, func(i, j int) bool {
		if users[i].runningCount != users[j].runningCount {
			return users[i].runningCount < users[j].runningCount
		}
		if users[i].recentRuntime != users[j].recentRuntime {
			return users[i].recentRuntime < users[j].recentRuntime
		}
		return users[i].pendingCount > users[j].pendingCount
	})

	// Round-robin allocation
	remaining := slotsAvailable
	for remaining > 0 {
		scheduled := false
		for _, u := range users {
			if u.jobsToSchedule < u.pendingCount {
				u.jobsToSchedule++
				remaining--
				scheduled = true
				if remaining == 0 {
					break
				}
			}
		}
		if !scheduled {
			break
		}
	}

	// Collect selected jobs
	var result []queue.AnalyzeJob
	for _, u := range users {
		if u.jobsToSchedule > 0 {
			jobs := jobsByUser[u.user]
			count := u.jobsToSchedule
			if count > len(jobs) {
				count = len(jobs)
			}
			result = append(result, jobs[:count]...)

			slog.Info("Queueing jobs for user",
				"user", u.user,
				"count", count,
				"running", u.runningCount,
				"pending", u.pendingCount,
				"recent_runtime_seconds", u.recentRuntime)
		}
	}

	return result
}

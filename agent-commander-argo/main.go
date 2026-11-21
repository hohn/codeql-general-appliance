package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"log/slog"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/google/uuid"

	"github.com/hohn/mrvacommander/pkg/agent"
	"github.com/hohn/mrvacommander/pkg/artifactstore"
	"github.com/hohn/mrvacommander/pkg/common"
	"github.com/hohn/mrvacommander/pkg/deploy"
	"github.com/hohn/mrvacommander/pkg/qldbstore"
	"github.com/hohn/mrvacommander/pkg/state"
)

func main() {
	slog.Info("Starting worker pool agent")

	logLevel := flag.String("loglevel", "info", "Set log level: debug, info, warn, error")
	flag.Parse()

	// Apply 'loglevel' flag
	switch *logLevel {
	case "debug":
		slog.SetLogLoggerLevel(slog.LevelDebug)
	case "info":
		slog.SetLogLoggerLevel(slog.LevelInfo)
	case "warn":
		slog.SetLogLoggerLevel(slog.LevelWarn)
	case "error":
		slog.SetLogLoggerLevel(slog.LevelError)
	default:
		log.Printf("Invalid logging verbosity level: %s", *logLevel)
		os.Exit(1)
	}

	slog.Info("Log level set to", slog.Any("loglevel", *logLevel))
	slog.Info("Running version of agent", slog.Any("version", "v0.6.0-pool"))

	// Generate unique worker ID
	hostname, _ := os.Hostname()
	workerID := fmt.Sprintf("%s-%s", hostname, uuid.New().String())
	slog.Info("Worker ID", "worker_id", workerID)

	// Read pool timing configuration from environment
	claimPollSeconds := envIntOrDefault("MRVA_POOL_CLAIM_POLL_SECONDS", 2)
	idleTimeoutSeconds := envIntOrDefault("MRVA_POOL_IDLE_TIMEOUT_SECONDS", 300)
	heartbeatSeconds := envIntOrDefault("MRVA_POOL_HEARTBEAT_SECONDS", 10)

	if claimPollSeconds <= 0 || idleTimeoutSeconds <= 0 || heartbeatSeconds <= 0 {
		slog.Error("Pool timing values must be positive",
			"claim_poll_seconds", claimPollSeconds,
			"idle_timeout_seconds", idleTimeoutSeconds,
			"heartbeat_seconds", heartbeatSeconds)
		os.Exit(1)
	}

	claimPollInterval := time.Duration(claimPollSeconds) * time.Second
	idleTimeout := time.Duration(idleTimeoutSeconds) * time.Second
	heartbeatInterval := time.Duration(heartbeatSeconds) * time.Second

	// Initialize services. Workers skip schema setup: the server creates
	// the full schema before spawning any worker, and having workers run
	// DDL concurrently with other workers' claims deadlocks Postgres.
	pgState := state.NewPGStateNoSchema()
	artifacts, databases := initServices()

	// Register worker in pool
	podName := os.Getenv("HOSTNAME") // Kubernetes pod name
	if err := pgState.RegisterWorker(workerID, podName); err != nil {
		slog.Error("Failed to register worker", slog.Any("error", err))
		os.Exit(1)
	}

	// Handle shutdown signals via context cancellation
	ctx, cancel := context.WithCancel(context.Background())
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigChan
		slog.Info("Received shutdown signal")
		cancel()
	}()

	// Start heartbeat goroutine
	heartbeatDone := make(chan struct{})
	go func() {
		defer close(heartbeatDone)
		ticker := time.NewTicker(heartbeatInterval)
		defer ticker.Stop()
		const maxTransientFailures = 3
		consecutiveFailures := 0
		for {
			select {
			case <-ticker.C:
				if err := pgState.WorkerHeartbeat(workerID); err != nil {
					slog.Error("Heartbeat failed", "error", err)
					if isReapedError(err) {
						slog.Info("Worker was reaped by server, exiting heartbeat loop")
						return
					}
					consecutiveFailures++
					if consecutiveFailures >= maxTransientFailures {
						slog.Error("Too many consecutive heartbeat failures, exiting",
							"failures", consecutiveFailures)
						return
					}
				} else {
					consecutiveFailures = 0
				}
			case <-ctx.Done():
				return
			}
		}
	}()

	// Worker main loop: claim -> execute -> complete -> claim next
	idleStart := time.Now()
	claimTicker := time.NewTicker(claimPollInterval)
	defer claimTicker.Stop()

	slog.Info("Worker entering main loop",
		"claim_poll", claimPollInterval,
		"idle_timeout", idleTimeout,
		"heartbeat", heartbeatInterval)

	for {
		// Check for shutdown signal or heartbeat failure
		select {
		case <-ctx.Done():
			slog.Info("Shutdown signal received in main loop")
			goto shutdown
		case <-heartbeatDone:
			slog.Error("Heartbeat goroutine exited, shutting down")
			goto shutdown
		default:
		}

		// Check for drain signal from pool manager
		workerStatus, err := pgState.GetWorkerStatus(workerID)
		if err != nil {
			slog.Error("Failed to get worker status, shutting down", "error", err)
			goto shutdown
		} else if workerStatus == common.WorkerDraining || workerStatus == common.WorkerExited {
			slog.Info("Worker no longer active, shutting down", "status", workerStatus)
			goto shutdown
		}

		// Attempt to claim a job
		job, err := pgState.ClaimJob(workerID)
		if err != nil {
			slog.Error("ClaimJob failed", "error", err)
			if time.Since(idleStart) > idleTimeout {
				slog.Info("Idle timeout exceeded during claim errors, shutting down")
				goto shutdown
			}
			select {
			case <-claimTicker.C:
			case <-ctx.Done():
				slog.Info("Shutdown signal received in main loop")
				goto shutdown
			case <-heartbeatDone:
				slog.Error("Heartbeat goroutine exited, shutting down")
				goto shutdown
			}
			continue
		}

		if job == nil {
			// No work available - check idle timeout
			if time.Since(idleStart) > idleTimeout {
				slog.Info("Idle timeout exceeded, shutting down",
					"idle_duration", time.Since(idleStart))
				goto shutdown
			}
			select {
			case <-claimTicker.C:
			case <-ctx.Done():
				slog.Info("Shutdown signal received in main loop")
				goto shutdown
			case <-heartbeatDone:
				slog.Error("Heartbeat goroutine exited, shutting down")
				goto shutdown
			}
			continue
		}

		// Got a job - execute it
		jobKey := fmt.Sprintf("%d/%s/%s", job.Spec.SessionID, job.Spec.Owner, job.Spec.Repo)
		slog.Info("Claimed job", "job", jobKey)

		if err := pgState.SetWorkerBusy(workerID, jobKey); err != nil {
			slog.Error("Failed to set worker busy", "error", err)
		}

		// Execute the analysis
		result, err := agent.RunAnalysisJob(*job, artifacts, databases)
		if err != nil {
			slog.Error("Failed to run analysis job", slog.Any("error", err))
			// Mark job as failed
			if completeErr := pgState.CompleteJob(workerID, job.Spec, common.StatusFailed); completeErr != nil {
				slog.Error("Failed to mark job as failed", "error", completeErr)
			}
		} else {
			slog.Info("Analysis job completed",
				slog.String("status", result.Status.ToExternalString()),
				slog.Int("result_count", result.ResultCount))

			// Persist the result reference (analyze_results) and status,
			// then record completion. SetResultAndStatus writes
			// analyze_results + job_status, CompleteJob stamps
			// job_info.completed_at. Without SetResultAndStatus the
			// server's GetResult fails and it downgrades a succeeded job
			// back to in-progress.
			pgState.SetResultAndStatus(job.Spec, result, result.Status)

			// Mark job as succeeded
			if completeErr := pgState.CompleteJob(workerID, job.Spec, result.Status); completeErr != nil {
				slog.Error("Failed to mark job as completed", "error", completeErr)
			}
		}

		// Worker is idle again
		if err := pgState.SetWorkerIdle(workerID); err != nil {
			slog.Error("Failed to set worker idle", "error", err)
		}
		idleStart = time.Now()

		// Continue loop: claim next job without exit
	}

shutdown:
	cancel()
	if err := pgState.SetWorkerStatus(workerID, common.WorkerExited); err != nil {
		slog.Error("Failed to set worker exited", "error", err)
	}

	// Exit all
	slog.Info("Worker exiting", "worker_id", workerID)
	os.Stdout.Sync()
	os.Stderr.Sync()
	return
}

// initServices initializes the agent's backends.
//
// The agent persists results directly to Postgres state (SetResultAndStatus
// + CompleteJob); no message broker is involved. When MRVA_STANDALONE=true it
// uses the same single-VM backends the server uses in --mode=standalone:
//   - artifact store selected by MRVA_STANDALONE_STORAGE (local MinIO by
//     default, or the filesystem store at MRVA_ARTIFACT_DIR),
//   - filesystem CodeQL DB store at MRVA_QLDB_DIR.
//
// Otherwise (container mode), MinIO/BCS + HEPC are required.
// Exits the process on failure.
func initServices() (artifactstore.Store, qldbstore.Store) {
	if os.Getenv("MRVA_STANDALONE") == "true" {
		slog.Info("agent: standalone backends (no Docker)")

		artifacts, err := deploy.InitStandaloneArtifactStore()
		if err != nil {
			slog.Error("Failed to initialize standalone artifact store",
				slog.Any("error", err))
			os.Exit(1)
		}

		qldbRoot := os.Getenv("MRVA_QLDB_DIR")
		databases, err := deploy.InitStandaloneDatabaseStore(qldbRoot)
		if err != nil {
			slog.Error("Failed to initialize standalone database store",
				slog.Any("error", err))
			os.Exit(1)
		}

		return artifacts, databases
	}

	artifacts, err := deploy.InitBCSMinIOArtifactStore()
	if err != nil {
		slog.Error("Failed to initialize artifact store", slog.Any("error", err))
		os.Exit(1)
	}

	databases, err := deploy.InitHEPCDatabaseStore()
	if err != nil {
		slog.Error("Failed to initialize database store", slog.Any("error", err))
		os.Exit(1)
	}

	return artifacts, databases
}

// envIntOrDefault parses an env var as an integer, returning defaultVal if unset or malformed.
func envIntOrDefault(key string, defaultVal int) int {
	v := os.Getenv(key)
	if v == "" {
		return defaultVal
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		slog.Warn("Malformed env var, using default", "key", key, "value", v, "default", defaultVal)
		return defaultVal
	}
	return n
}

// isReapedError returns true if the heartbeat error indicates the worker was
// deliberately reaped (status set to WorkerExited) rather than a transient DB issue.
func isReapedError(err error) bool {
	return err != nil && strings.Contains(err.Error(), "not found or exited")
}

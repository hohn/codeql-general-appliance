// Copyright © 2024 github
// Licensed under the Apache License, Version 2.0 (the "License").

package main

import (
	"flag"
	"fmt"
	"log"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"syscall"
	"time"

	"github.com/hohn/mrvacommander/pkg/deploy"
	"github.com/hohn/mrvacommander/pkg/scheduler"
	"github.com/hohn/mrvacommander/pkg/server"
	"github.com/hohn/mrvacommander/pkg/state"
)

func main() {
	// force rebuild
	// Define flags
	helpFlag := flag.Bool("help", false, "Display help message")
	logLevel := flag.String("loglevel", "debug", "Set log level: debug, info, warn, error")
	mode := flag.String("mode", "container", "Set mode: standalone, container, cluster")
	dbPathRoot := flag.String("dbpath", "", "Set the root path for the database store if using standalone mode.")
	dbgDumpSysview := flag.Bool("dbg-dump-sysview", false, "Debug: append each sysview snapshot to the dump file (default sysview-dump; override path with MRVA_SYSVIEW_DUMP_PATH) for later inspection/replay.")
	storage := flag.String("storage", "", "Standalone artifact backend: minio (default) or filesystem. Overrides MRVA_STANDALONE_STORAGE; inherited by spawned agents.")

	// Custom usage function for the help flag
	flag.Usage = func() {
		log.Printf("Usage of %s:\n", os.Args[0])
		flag.PrintDefaults()
		log.Println("\nExamples:")
		log.Println("go run main.go --loglevel=debug --mode=container --dbpath=/path/to/db_dir")
	}

	// Parse the flags
	flag.Parse()

	// Handle the help flag
	if *helpFlag {
		flag.Usage()
		return
	}

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

	// Process database root if standalone and not provided
	if *mode == "standalone" && *dbPathRoot == "" {
		slog.Warn("No database root path provided.")
		// Current directory of the Executable has a codeql directory. There.
		// Resolve the absolute directory based on os.Executable()
		execPath, err := os.Executable()
		if err != nil {
			slog.Error("Failed to get executable path", slog.Any("error", err))
			os.Exit(1)
		}
		*dbPathRoot = filepath.Dir(execPath) + "/codeql/dbs/"
		slog.Info("Using default database root path", "dbPathRoot", *dbPathRoot)
	}

	// // Read configuration
	// config := mcc.LoadConfig("mcconfig.toml")

	// Output configuration summary
	log.Printf("Help: %t\n", *helpFlag)
	log.Printf("Log Level: %s\n", *logLevel)
	log.Printf("Mode: %s\n", *mode)

	// Handle signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Apply 'mode' flag
	switch *mode {
	case "standalone":
		// Single-VM dev mode. No Docker required; uses:
		//   - PostgreSQL on the host (POSTGRES_* env)
		//   - artifact store selected by --storage / MRVA_STANDALONE_STORAGE
		//     (local MinIO by default, filesystem as an override)
		//   - filesystem CodeQL DB store (--dbpath)
		//   - no broker: agents talk to the server through Postgres only
		//   - LocalArgoClient: spawns agent-commander-argo as a local
		//     subprocess instead of submitting an Argo Workflow.
		//
		// Export the chosen storage backend so the agent subprocesses spawned
		// by LocalArgoClient (which inherit os.Environ()) select the same one.
		if *storage != "" {
			os.Setenv("MRVA_STANDALONE_STORAGE", *storage)
		}
		if err := runStandalone(*dbPathRoot, *dbgDumpSysview, sigChan); err != nil {
			slog.Error("standalone mode failed", "error", err)
			os.Exit(1)
		}

	case "container":
		queueImpl := deploy.InitNoopQueue()
		defer queueImpl.Close()

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

		// Initialize state and Argo client
		pgState := state.NewPGState()

		var argoClient scheduler.ArgoWorkflowClient
		if os.Getenv("MRVA_ENVSIM") == "true" {
			localClient, err := scheduler.NewLocalArgoClient()
			if err != nil {
				slog.Error("Failed to create local Argo client", "error", err)
				os.Exit(1)
			}
			argoClient = localClient
			slog.Info("Using LOCAL Argo client (envsim mode)")
			defer localClient.Cleanup()
		} else {
			realClient, err := scheduler.NewArgoClientFromEnv()
			if err != nil {
				slog.Error("Failed to create Argo client", "error", err)
				os.Exit(1)
			}
			argoClient = realClient
		}

		// Create server components using NewVisibles constructor
		// This properly initializes the PoolManager with config from environment
		visibles := server.NewVisibles(
			queueImpl,
			pgState,
			artifacts,
			databases,
			argoClient,
			server.NewJWTAuthenticator(),
		)
		// Production sysview: slower refresh, behind auth middleware.
		visibles.SysView = server.NewSysViewConfig(5*time.Second, true, *dbgDumpSysview)

		commander := server.NewCommanderSingle(visibles)
		defer commander.Stop()

		slog.Info("Started server in container mode.")
		<-sigChan
	default:
		slog.Error("Invalid value for --mode. Allowed values are: standalone, container, cluster")
		os.Exit(1)
	}

	slog.Info("Server shutdown complete")
}

// applyStandaloneResourceDefaults fills in sane single-machine worker-pool
// defaults for standalone mode, but only for values the operator has not set.
// Resolved values are written back to the process environment so that (a) the
// pool manager picks them up via pool.NewConfigFromEnv and (b) spawned agent
// subprocesses inherit them (they run CodeQL with MRVA_CODEQL_THREADS). Any
// pre-existing value is always preserved, so the test harness and local runs
// retain full control.
//
// Defaults: 2 cores per worker (MRVA_CODEQL_THREADS) and (NumCPU-1)/coresPerWorker
// workers (MRVA_POOL_MAX_WORKERS), at least one worker.
func applyStandaloneResourceDefaults() {
	const defaultCoresPerWorker = 2

	coresPerWorker := defaultCoresPerWorker
	if v := os.Getenv("MRVA_CODEQL_THREADS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			coresPerWorker = n
		}
	} else {
		os.Setenv("MRVA_CODEQL_THREADS", strconv.Itoa(coresPerWorker))
	}

	if os.Getenv("MRVA_POOL_MAX_WORKERS") == "" {
		workers := (runtime.NumCPU() - 1) / coresPerWorker
		if workers < 1 {
			workers = 1
		}
		os.Setenv("MRVA_POOL_MAX_WORKERS", strconv.Itoa(workers))
	}

	// Tighten the scheduling backstop for local runs. The pool manager is now
	// also woken directly on job submission, so these only matter when a wake
	// is missed; small values keep worker spawn + idle pickup snappy. Both are
	// overridable and only filled in when unset.
	setenvDefault("MRVA_POOL_SCALE_CHECK_SECONDS", "2")
	setenvDefault("MRVA_POOL_CLAIM_POLL_SECONDS", "2")

	slog.Info("Standalone worker-pool resource defaults resolved",
		"system_cores", runtime.NumCPU(),
		"cores_per_worker", os.Getenv("MRVA_CODEQL_THREADS"),
		"max_workers", os.Getenv("MRVA_POOL_MAX_WORKERS"),
		"scale_check_seconds", os.Getenv("MRVA_POOL_SCALE_CHECK_SECONDS"),
		"claim_poll_seconds", os.Getenv("MRVA_POOL_CLAIM_POLL_SECONDS"))
}

// setenvDefault sets an environment variable only when it is currently unset,
// preserving any operator-provided value.
func setenvDefault(key, value string) {
	if os.Getenv(key) == "" {
		os.Setenv(key, value)
	}
}

// runStandalone wires the no-Docker, single-VM deployment. Returns an
// error rather than calling os.Exit so the surrounding switch can
// report uniformly.
func runStandalone(dbPathRoot string, dumpSysview bool, sigChan <-chan os.Signal) error {
	if dbPathRoot == "" {
		return fmt.Errorf("standalone mode requires --dbpath (CodeQL DB store root)")
	}

	// Fill in sane single-machine worker-pool defaults before anything reads
	// them (the pool manager and the agent subprocesses both consume these).
	applyStandaloneResourceDefaults()

	queueImpl := deploy.InitNoopQueue()
	defer queueImpl.Close()

	artifacts, err := deploy.InitStandaloneArtifactStore()
	if err != nil {
		return fmt.Errorf("artifact store: %w", err)
	}

	databases, err := deploy.InitStandaloneDatabaseStore(dbPathRoot)
	if err != nil {
		return fmt.Errorf("qldb store: %w", err)
	}

	// Host Postgres (POSTGRES_* env vars). NewPGState exits the
	// process on missing vars, mirroring container mode.
	pgState := state.NewPGState()

	// Agents are spawned as subprocesses on the same host. The path
	// to the agent binary comes from MRVA_ENVSIM_AGENT_BINARY (the
	// same variable used by container mode's envsim path; the Makefile
	// 'standalone' target sets it automatically).
	localClient, err := scheduler.NewLocalArgoClient()
	if err != nil {
		return fmt.Errorf("local argo client: %w", err)
	}
	defer localClient.Cleanup()

	visibles := server.NewVisibles(
		queueImpl,
		pgState,
		artifacts,
		databases,
		localClient,
		server.NewDevAuthenticator(),
	)
	// Standalone sysview: fast refresh, open (no auth) for local development.
	visibles.SysView = server.NewSysViewConfig(500*time.Millisecond, false, dumpSysview)
	commander := server.NewCommanderSingle(visibles)
	defer commander.Stop()

	slog.Info("Started server in standalone mode (no Docker).",
		"dbpath", dbPathRoot,
		"artifact_dir", os.Getenv("MRVA_ARTIFACT_DIR"))
	<-sigChan
	return nil
}

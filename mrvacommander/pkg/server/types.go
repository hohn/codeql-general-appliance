package server

import (
	"log/slog"

	"github.com/hohn/mrvacommander/pkg/artifactstore"
	"github.com/hohn/mrvacommander/pkg/common"
	"github.com/hohn/mrvacommander/pkg/pool"
	"github.com/hohn/mrvacommander/pkg/qldbstore"
	"github.com/hohn/mrvacommander/pkg/queue"
	"github.com/hohn/mrvacommander/pkg/scheduler"
	"github.com/hohn/mrvacommander/pkg/state"
)

type SessionInfo struct {
	ID                  int
	QueryPack           string
	PackSHA1            string // SHA1 (hex) of the decoded query pack bytes
	Language            queue.QueryLanguage
	User                string // User who submitted the request (from JWT)
	AccessMismatchRepos []common.NameWithOwner
	NotFoundRepos       []common.NameWithOwner
	NoCodeqlDBRepos     []common.NameWithOwner
}

type CommanderSingle struct {
	v *Visibles
}

func NewCommanderSingle(st *Visibles) *CommanderSingle {
	c := CommanderSingle{v: st}

	// Start pool manager in background
	go st.PoolManager.Start()

	// Start the sysview snapshot goroutine (background dashboard).
	sv := startSysView(st.State, st.PoolManager, st.SysView)

	setupEndpoints(&c, st.Authenticator, sv)
	go c.ConsumeResults()
	return &c
}

// Stop releases this server's pool-manager lease before process shutdown.
func (c *CommanderSingle) Stop() {
	c.v.PoolManager.Stop()
}

type Visibles struct {
	Queue         queue.Queue
	State         state.ServerState
	Artifacts     artifactstore.Store
	CodeQLDBStore qldbstore.Store
	PoolManager   *pool.PoolManager // Pool manager for fair queueing and worker lifecycle
	Authenticator Authenticator     // Resolves the request username (mode-selected)
	SysView       SysViewConfig     // /sysview dashboard config (mode-selected)
}

// NewVisibles creates a Visibles struct with a properly initialized PoolManager.
// The argo parameter should be an ArgoWorkflowClient implementation.
// The auth parameter selects how request usernames are resolved (JWT in
// container/cluster mode, request header in standalone mode).
func NewVisibles(
	q queue.Queue,
	st state.ServerState,
	artifacts artifactstore.Store,
	codeqlDBStore qldbstore.Store,
	argo scheduler.ArgoWorkflowClient,
	auth Authenticator,
) *Visibles {
	poolConfig := pool.NewConfigFromEnv()
	poolManager := pool.NewPoolManager(poolConfig, st, argo)

	// Log pool configuration for visibility
	slog.Info("Pool manager configured",
		"max_workers", poolConfig.MaxWorkers,
		"idle_timeout", poolConfig.IdleTimeout,
		"scale_check_interval", poolConfig.ScaleCheckInterval)

	return &Visibles{
		Queue:         q,
		State:         st,
		Artifacts:     artifacts,
		CodeQLDBStore: codeqlDBStore,
		PoolManager:   poolManager,
		Authenticator: auth,
	}
}

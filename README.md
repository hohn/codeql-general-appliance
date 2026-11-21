# Single Machine MRVA

## Installed? Open CGA

On the machine where `cga` is installed, start the documentation gateway:

```sh
cga gateway start
cga gateway status
```

For a remote VM, keep an SSH tunnel open from your workstation. Replace
`hohn@svm` with your SSH destination:

```sh
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 \
  -L 8599:127.0.0.1:8599 hohn@svm
```

Open **http://127.0.0.1:8599/** in your workstation's browser, or directly on
the CGA machine for local use. Choose **CGA overview** and follow **Sample 05 in
section 03** for a first analysis.

No initialized workflow, running MRVA, or configured viewers are needed. The
overview and help are already rendered; no documentation build is required. The
reference manual is optional and built separately.

Reconnect with the same SSH command. Stop only the gateway with
`cga gateway stop`.

## Documentation

Choose the depth you need:

1. **[CGA overview](docs/cga-overview.html)** — understand the appliance, follow
   the fixed Sample 05 worked example, and install CGA.
2. **[CGA help](docs/cga-help.html)** — choose a task and look up instructions
   and commands.
3. **[Reference manual (book)](docs/book/index.html)** — consult detailed
   workflows, components, and operations; it is reference, not required
   introductory reading.

The repository and implementation reference follows below. The
[advanced reading guide](READING-GUIDE.md) supplies deeper task-based paths.

This repository is a science experiment and prototype for handling CodeQL
databases and queries, applying queries to databases, and supporting human/LLM
investigation. Code, examples, and usage documentation evolve together. Examples
leave room for experimentation; e2e tests are fixed examples that test the code.

This repository is:

- a **single-machine MRVA system** — a complete Multi-Repository Variant
  Analysis (MRVA) stack (server, agents, state, stores) that runs on one host
  with no Docker required, and
- the **testbed for large-scale deployment** — the same Go modules deploy to a
  cluster via Argo Workflows; the single-machine setup keeps the moving parts
  visible so the system can be developed, exercised, and debugged locally.

MRVA takes one CodeQL query and runs it across many CodeQL databases in
parallel. Here a single Go server (the "commander") accepts submissions,
schedules jobs onto a pool of local worker subprocesses (the "agents"), and
records everything in a host PostgreSQL database. Results are written back as
SARIF. A live system view is served at `http://localhost:8081/sysview`.

## CGA command-line interface

**CGA is the recommended end-to-end interface to this repository.** It selects
prepared CodeQL databases and queries, submits MRVA analyses, tracks and
downloads results, ingests SARIF, exports findings, and manages the combined
analysis/preparation dashboard.

Install the repository's unified `cga` dispatcher on your user `PATH` from
anywhere inside the checkout:

```sh
repo_root=$(git rev-parse --show-toplevel)
install -d "$HOME/.local/bin"
ln -sfn "$repo_root/cga/cga" "$HOME/.local/bin/cga"
install -d "$HOME/.local/share/bash-completion/completions"
ln -sfn "$repo_root/cga/completions/cga.bash" \
  "$HOME/.local/share/bash-completion/completions/cga"
cga --help
```

If `$HOME/.local/bin` is not already on `PATH`, add
`export PATH="$HOME/.local/bin:$PATH"` to your shell profile. A system-wide
alternative on a dedicated development machine is:

```sh
sudo ln -sfn "$(git rev-parse --show-toplevel)/cga/cga" /usr/local/bin/cga
```

The completion installation is discovered automatically by `bash-completion` in
new Bash shells. For the current shell, either start a new shell or run:

```sh
source "$(git rev-parse --show-toplevel)/cga/completions/cga.bash"
```

See [`cga/README.md`](cga/README.md) for command completion, the dashboard,
component commands, and the starting single-user
[`mrva-flow`](cga/mrva-flow/README.md) example. The earlier two-user
[`sample-05-i`](cga/sample-05-i/README.md) remains available for
experimentation.

For shell-based assistant discovery, use `cga llm context --help`, then
`cga llm context bench` (alias `cga llm cb`) for experiment/session state or
`cga llm context unified` (alias `cga llm cu`) for the workflow outline. These
read local state without requiring a web server. Add `--show-html-endpoint`,
`--show-json-endpoint`, or `--show-docs` to print the corresponding viewer URL,
JSON URL, or local documentation paths.

Bench, Unified View, shell commands, and assistant context also share opaque
visual element IDs, such as `:f3a,1,J` for session 1's job stage. Use
`cga show --registry`, `cga show :f3a,1,J`, `cga related :f3a,1,J`, or
`cga open :f3a,1,J`. Clicking a UI badge opens a pinned fact inspector with its
own terminal; pasting its Copilot command never executes it automatically. See
the [VID reference contract](cga/README.md#visual-element-identifiers-vids).

The canonical way to bring the whole thing up, submit work, and verify it is the
phase-based driver `cga/system-tests/run-system-02` (see
[`cga/system-tests/README.md`](cga/system-tests/README.md)).

## Sample workflows and system tests

The sample end-to-end workflows (bringing the stack up, submitting work,
verifying, capturing/replaying sysview dumps) and the state-inspection recipes
live with the harness that drives them. See
[`cga/system-tests/README.md`](cga/system-tests/README.md) for the configuration tables,
the `run-system-*` sample workflow, the replayable-dump workflow, and the
MinIO/PostgreSQL state-inspection samples.

## Related documentation

- [`cga/README.md`](cga/README.md) — the recommended unified CLI for database
  and query selection, MRVA execution, SARIF ingestion, and result export.
- [`cga/cgamr/README.md`](cga/cgamr/README.md) — the MRVA HTTP client for
  submission, status, and result downloads.
- [`cga/system-tests/README.md`](cga/system-tests/README.md) — configuration, sample
  workflows, replay, and state-inspection recipes.
- [`server-commander/README.md`](server-commander/README.md) — the commander
  (server) binary.
- [`agent-commander-argo/README.md`](agent-commander-argo/README.md) — the
  worker/agent binary.
- [`mrvacommander/README.md`](mrvacommander/README.md) — the shared library
  module.
- [`sysview-view/README.md`](sysview-view/README.md) — offline sysview replay
  tool.

<a id="mrva-component-map"></a>

## MRVA repository / component layout

The workspace is composed of three sibling Go modules. Two of them
(`server-commander`, `agent-commander-argo`) are thin `main` wrappers that wire
together components from the shared library module `mrvacommander`.

### Top-level components (deployable binaries)

#### server-commander (`server-commander/main.go`)

- Long-running HTTP server: the MRVA "commander".
- `--mode` selects the deployment (default `container`):
  - `standalone` — single-VM dev mode, no Docker. Uses host PostgreSQL
    (`POSTGRES_*`), a filesystem artifact store (`MRVA_ARTIFACT_DIR`), a
    filesystem CodeQL DB store (`--dbpath`), and a `LocalArgoClient` that spawns
    `agent-commander-argo` as a local subprocess. This is the mode
    `run-system-02` and the live single-machine deployment use.
  - `container` — MinIO/S3 artifact store, HEPC CodeQL DB store, host
    PostgreSQL, and either the real Argo client or a local client when
    `MRVA_ENVSIM=true`.
  - `cluster` — accepted by the `--mode` help text but **not implemented**; it
    falls through to an error. Cluster deployment is done with `container` mode
    plus Argo Workflows.
- Neither mode uses a message broker: both construct a **no-op queue**
  (`deploy.InitNoopQueue`); agents coordinate with the server through PostgreSQL
  only.
- Entry point constructs `server.NewVisibles(...)` then
  `server.NewCommanderSingle(...)` and blocks on signals.
- Built locally (e.g. `make` / `go build`) to `server-commander/mrvaserver`; the
  binary is gitignored, not tracked.

#### agent-commander-argo (`agent-commander-argo/main.go`)

- Worker process. Two modes:
  1. Pool worker loop: register in the Postgres worker pool, heartbeat, claim
     jobs (`pgState.ClaimJob`), run analysis (`agent.RunAnalysisJob`), and
     **persist the result directly to Postgres** (`pgState.SetResultAndStatus`
     - `pgState.CompleteJob`).
  2. Single-job mode (`--job <JSON>`): used inside Argo Workflow pods; runs one
     job and exits.
- Built locally to `agent-commander-argo/mrvaagent`; the binary is gitignored,
  not tracked.

#### mrvacommander (shared library module + auxiliary tooling)

- Hosts `pkg/...` used by both binaries above.
- Also contains: `cmd/server/doc.go`, `client/` (containers, `Plan.ipynb`,
  qldbtools), `config/mcc`, `init/rabbitmq` boot files, `tools/` (curl recorder
  & captures), `utils/` (archive/download helpers plus PR/version-bump shell
  scripts), `doc/`, `demo/`, `db_schema_changes/`, `docker-compose*.yml`,
  `Makefile`, etc. **Note:** `docker-compose*.yml` and the `cmd/{server,agent}`
  Docker containers are legacy/deprecated and kept only as structural guidance;
  the live deployment is Argo Workflows + `--mode=standalone`.

### Library packages (`mrvacommander/pkg/*`) — core components

#### server (`pkg/server`)

- HTTP front end of the commander. Files: `server.go`, `auth.go`,
  `interfaces.go`, `types.go`, `sysview.go`.
- Defines `CommanderSingle`, `Visibles` (bundle of injected dependencies: Queue,
  State, Artifacts, Databases, ArgoClient, PoolManager), and the gorilla/mux
  router (`setupEndpoints`).
- Endpoints: variant-analysis submit / status / cancel / download, plus the
  system view (`/sysview`, `/sysview/data`).
- `auth.go` provides `AuthMiddleware` for the submission routes.

#### agent (`pkg/agent`)

- Analysis execution engine used by `agent-commander-argo`.
- `agent.go`: `RunAnalysisJob` (drives codeql, uploads results).
- `pool_worker.go`: worker-pool helpers (used in conjunction with the `state`
  worker-pool tables).
- `interfaces.go`: agent-side contracts.

#### pool (`pkg/pool`)

- Pool manager / autoscaler. `Config` read from `MRVA_POOL_*` env vars
  (MaxWorkers, MinWorkers, RampFactor, DecayRate, IdleTimeout, HeartbeatExpiry,
  ScaleCheckInterval, DecayInterval, RecentRuntimeWindow).
- Uses a Postgres advisory lock (`queueAdvisoryLockID = 73001`) for
  leader-elected fair queueing.

#### scheduler (`pkg/scheduler`)

- Fair scheduler that promotes Pending -> Queued and dispatches jobs to workers
  / Argo workflows.
- `scheduler.go`: fair-share logic (per-user job counts and recent runtime
  window).
- `argo_client.go`: real `ArgoWorkflowClient` (spawns Argo Workflows = "argo pod
  spawner").
- `local_client.go`: in-process/local stand-in (`NewLocalArgoClient`), used in
  `standalone` mode and in `container` mode when `MRVA_ENVSIM=true`.
- Config via `MRVA_SCHEDULER_*` env vars.

#### state (`pkg/state`) — "postgres for state"

- `interfaces.go`: `ServerState` interface, the central state contract (jobs,
  sessions, results, worker pool, scheduler locks, advisory locks, etc.).
- `state_postgres.go`: Postgres-backed implementation (`NewPGState`). Backs the
  job queue, worker pool, fair-scheduler bookkeeping, and leader election.

#### queue (`pkg/queue`)

- Message queue abstraction. `interfaces.go` defines `Queue` and
  `QueueWithSync`.
- `queue_rabbitmq.go`: RabbitMQ implementation. **Present in the library but not
  wired into the live binaries** — both server modes use the no-op queue.
- `queue_single.go`: in-process single-host implementation.
- `types.go`: `AnalyzeJob`, `AnalyzeResult`, `QueryLanguage`.

#### artifactstore (`pkg/artifactstore`)

- Storage for query packs and analysis result artifacts.
- `interfaces.go`, `common.go`.
- `store_minio.go`: MinIO / S3-compatible (BCS) backend (container mode).
- `store_memory.go`: in-memory backend for tests.
- A filesystem-backed store is used in standalone mode
  (`deploy.InitFilesystemArtifactStore`, rooted at `MRVA_ARTIFACT_DIR`).

#### qldbstore (`pkg/qldbstore`) — CodeQL database store

- `interfaces.go`: `Store` contract for serving CodeQL DBs.
- `qldbstore_hepc.go`: HEPC-backed implementation (`NewHepcStore`, used in
  container/production mode).
- `qldbstore_local.go`: local filesystem implementation (standalone mode,
  `deploy.InitFilesystemDatabaseStore`, rooted at `--dbpath`).

#### codeql (`pkg/codeql`)

- Wrapper around the CodeQL CLI (`codeql.go`, `types.go`). Used by the agent to
  execute analyses.

#### common (`pkg/common`)

- Cross-cutting types and helpers: `types.go` (Status, WorkerStatus,
  NameWithOwner, StatusSummary, ...), `jobspec.go` (JobSpec, JobInfo),
  `extapi.go` (external API types), `minio.go` (shared minio helpers).

#### deploy (`pkg/deploy`)

- Composition root used by both `main` binaries. `init.go` exposes
  `InitMinIOArtifactStore`, `InitHEPCDatabaseStore`,
  `InitFilesystemArtifactStore`, `InitFilesystemDatabaseStore`, and
  `InitNoopQueue`, plus `validateEnvVars`. Reads `MRVA_*` env vars and
  constructs concrete implementations of the library interfaces.

### Support libraries / cross-cutting concerns

#### Logging

- Uses Go standard `log/slog` throughout (level configured by `--loglevel` in
  both binaries; `slog.SetLogLoggerLevel`).
- Legacy `log` package used for a few startup messages.

#### HTTP request handling

- `gorilla/mux` router in `pkg/server/server.go` (`setupEndpoints`).
- `pkg/server/auth.go` provides `AuthMiddleware` applied to the
  submission/cancel subrouter.
- `CommanderAPI` interface (in `pkg/server/interfaces.go`) lists the handler
  methods (`MRVARequest`, `MRVAStatus`, `CancelVariantAnalysis`, `RootHandler`,
  ...).

#### Configuration

- All runtime config via `MRVA_*` (and `POSTGRES_*`) environment variables. The
  Go code computes sane defaults only when a value is unset; the harness and
  local runs keep full override flexibility.
- `mrvacommander/config/mcc` holds (commented-out) TOML config loader
  scaffolding.

#### Concurrency / coordination primitives

- Postgres advisory locks (`pkg/pool`) for leader-elected scheduling.
- Named scheduler locks (`AcquireSchedulerLock` / `RenewSchedulerLock` /
  `ReleaseSchedulerLock`) for distributed leader election with TTL.
- Worker pool registry & heartbeats in Postgres (`RegisterWorker`,
  `WorkerHeartbeat`, `ClaimJob`, `CompleteJob`, `GetStaleWorkers`,
  `RequeueWorkerJob`, `CleanupExitedWorkers`).

#### External integrations

- PostgreSQL (state, fair scheduling, worker pool, locks) — the one hard
  dependency of the single-machine system.
- MinIO / BCS S3 (artifact store: query packs + results) — container mode.
- External HEPC servers (CodeQL DB store) — container mode. Local standalone
  workflows use CGA's plain HTTP database serving instead.
- Argo Workflows (`pkg/scheduler/argo_client.go`) for spawning per-job pods in
  cluster deployments; the local client stands in for standalone/envsim.
- CodeQL CLI (`pkg/codeql`) invoked from the agent.
- RabbitMQ (`pkg/queue/queue_rabbitmq.go`) exists in the library but is not used
  by the current single-machine binaries.

### Mapping to user-supplied example

- agent -> `agent-commander-argo` + `pkg/agent`
- server -> `server-commander` + `pkg/server`
- library -> `mrvacommander/pkg/*`
  - postgres for state -> `pkg/state` (`state_postgres.go`)
  - argo pod spawner -> `pkg/scheduler/argo_client.go` (+ `local_client.go`
    fallback)
  - fair scheduler -> `pkg/scheduler/scheduler.go` (+ `pkg/pool` for
    autoscaling)
- support libraries
  - loggers -> `log/slog` (configured in each `main.go`)
  - request handlers -> `pkg/server` (gorilla/mux router + `AuthMiddleware`)

## This code is based on imported git revisions

```text
==== /home/hohn/c/example/psa-mrva/agent-commander-argo
1d8e498 (HEAD -> pool-patches, tag: v1.0.19-mh-pool-patches-20260623124738, origin/pool-patches)
==== /home/hohn/c/example/psa-mrva/mrvacommander
c36f339 (HEAD -> pool-patches, tag: v1.0.19-mh-pool-patches-20260623124738, origin/pool-patches)
==== /home/hohn/c/example/psa-mrva/server-commander
2f9d021 (HEAD -> pool-patches, tag: v1.0.19-mh-pool-patches-20260623124738, origin/pool-patches)
```

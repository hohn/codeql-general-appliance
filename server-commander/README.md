[![Devise](https://badges.dev.example.com/live/devise/verify-status/PSA-MRVA/server-commander)](https://devise.dx.example.com/repository/SCOMMANDER)
[![BPaaS](https://badges.dev.example.com/live/devise/bpaas-status/psa-mrva/server-commander)](https://ui.bpaas.prod.example.com/#/tenancies/psa-mrva/applications/server-commander)

## Standalone (no-Docker) dev mode

The `--mode=standalone` mode brings the server up without Docker, MinIO,
HEPC, or Argo. It is intended for fast local development on a
single machine; `--mode=container` and `docker-compose-demo.yml` remain
the supported production paths.

### Components in standalone mode

| Concern             | Container mode (prod)    | Standalone mode (dev)                              |
| ------------------- | ------------------------ | -------------------------------------------------- |
| State               | PostgreSQL in Docker     | PostgreSQL on the host (`brew install postgresql`) |
| Job queue / results | None: agent → state directly; pool ticks on timer | None: agent → state directly; pool ticks on timer  |
| Artifact store      | MinIO                    | Filesystem (`MRVA_ARTIFACT_DIR`)                   |
| CodeQL DB store     | HEPC                     | Filesystem (`MRVA_QLDB_DIR`, same as `--dbpath`)   |
| Agent spawning      | Argo Workflows           | `LocalArgoClient` — `fork+exec` agent subprocess   |

### Prerequisites

- Go (matching the version in `go.mod`).
- PostgreSQL on the host (default `localhost:5432`).
- `codeql` CLI on `$PATH`.
- The `agent-commander-argo` binary built at `../agent-commander-argo/mrvaagent`
  (the Makefile target builds it automatically).

### One-shot bring-up

```sh
# Create a dev database once.
createdb mrvadev

# Build and run the server. The Makefile sets MRVA_STANDALONE=true,
# POSTGRES_*, MRVA_ARTIFACT_DIR, MRVA_QLDB_DIR, MRVA_ENVSIM_AGENT_BINARY,
# CODEQL_CLI_PATH for you (override any of them on the command line).
make standalone POSTGRES_DB=mrvadev
```

The server creates its tables on first run (`CREATE TABLE IF NOT EXISTS`),
listens on `:8080`, and spawns agent subprocesses on demand when jobs
are submitted.

### Staging a CodeQL database

The filesystem `qldbstore` expects this layout:

```
$MRVA_QLDB_DIR/<owner>/<repo>/<owner>_<repo>_db.zip
```

For example, to use the sample `iniparser-4.1` database from `sample-dbs/`:

```sh
mkdir -p $MRVA_QLDB_DIR/debian/iniparser-4.1
cd .../sample-dbs/debian
zip -qr $MRVA_QLDB_DIR/debian/iniparser-4.1/debian_iniparser-4.1_db.zip iniparser-4.1
```

### Submitting a job

The HTTP API is unchanged; any client that talks to `--mode=container`
also works in standalone. CGA accepts a prebuilt query pack and repositories
already available in the server's configured database store:

```sh
cd .../single-machine-mrva
cga init my-analysis
cga -C my-analysis chain start
cga -C my-analysis ql index ../sample-query
cga -C my-analysis ql select relpath Fprintf.ql
cga -C my-analysis ql pack --output query.tgz
cga -C my-analysis mr submit --name sample --user alice \
    --pack query.tgz \
    --language cpp \
    --repos debian/iniparser-4.1 \
    --server http://127.0.0.1:8080 \
    --controller-owner octo --controller-repo ctl
```

### End-to-end tests

Linux-only scripts exercise `--mode=standalone` against real CodeQL DBs
and CGA's HTTP client plus sample data. They live in the
sibling `cga/system-tests/` directory; run them from there (they build the
server + agent via `make -C ../../server-commander`):

The multi-agent test is phase-decomposed into `run-system-02` plus two
helper scripts, all sharing `standalone-multi-agent-lib.sh`, so you can run
it, inspect the resulting Postgres state, then tear down:

- `./run-system-02 all` — full pipeline; or run a single named phase
  (`preflight`, `reset`, `stage`, `build`, `start`, `pack`, `submit1`,
  `submit2`, `poll`, `artifacts`, `claims`, `verify`) to step through
  interactively. It submits two users' sessions across several real CodeQL
  DBs; the standalone scheduler spawns one agent subprocess per job, so the
  DBs are analyzed by independent agents in parallel. It asserts distinct
  workers claimed distinct jobs (no double-claim) and all succeeded, then
  deliberately **leaves the server running and Postgres populated** on exit.
  `./run-system-02 query` and `./run-system-02 cleanup` delegate to the two
  helper scripts below.
- `./query-standalone-multi-agent-e2e.sh` — dumps each mrva table's
  schema and rows, plus decoded per-session views (status names, worker
  timing). Includes a blob-size guard asserting the invariant that
  Postgres holds only *references*: large state (query packs, SARIF, DB
  zips) lives in the artifact store, never in a jsonb/bytea column.
- `./cleanup-standalone-multi-agent-e2e.sh` — stops the server (and its
  agent subprocesses), drops the mrva tables, and removes the work dir
  and transient files. Idempotent.

All of these bootstrap the Postgres role/DB if needed and set
`CODEQL_JAVA_HOME=/usr` so the CodeQL CLI works on arm64.

### Notes / limitations

- `docker-compose-demo*.yml` and the `init/` directory remain
  production-only.
- The pool manager polls Postgres on its own tick
  (`MRVA_POOL_*_INTERVAL_SECONDS`); standalone mode drops the broker-based
  result notification, so end-to-end latency from submit to running is
  bounded by that tick (default 15s).
- Job-start timestamps are now written as UTC; previously the value was
  formatted with the local TZ offset and silently truncated by the
  `timestamp` (non-tz) column in Postgres, which caused the reconciler
  to instantly classify freshly-submitted jobs as "stale" on non-UTC
  hosts.

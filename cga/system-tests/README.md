# System tests / sample workflows

This directory holds the phase-based drivers that bring the whole single-machine
MRVA stack up, submit work, and verify it end-to-end:

- `run-system-02` — two users, one shared query pack (alice: 3 jobs, bob: 5 jobs
  = 8 jobs). The canonical driver.
- `run-system-03` — one user, three sessions, three packs (`*-multisession-*`),
  storage=minio.
- `run-system-04` — per-language packs variant.
- `run-system-09/` — one-CVE complete CGA preparation through CGA export.
- `run-system-10/` — collection-scale CGA analysis of every complete,
  successfully promoted six-database CVE group.
- [`run-system-11/`](run-system-11/README.md) — sysview observation over 200+
  distinct C/C++ databases, with configurable users/sessions for thousands of
  jobs, using the CGA dispatcher.

The earlier drivers source `standalone-multi-agent-lib.sh` for configuration and
helpers (`query-standalone-multi-agent-e2e.sh`,
`cleanup-standalone-multi-agent-e2e.sh`). Run them from this directory.
Scenario 11 uses `cga mx` directly and can run from the repository root; see
its local guide before launching shared infrastructure.
The standalone query and cleanup helpers accept `--help` without contacting
services; unknown arguments are rejected before any lifecycle actions.

## CGA client operations

The drivers use CGA for query indexing/selection/packing, MRVA submissions,
status checks, and result downloads. Prepared packs and repository lists are
explicit inputs to `cga mr submit`; the databases remain in the configured
HTTP database store. There is no database-upload operation on submission.

Each scenario records client operations in
`$CGA_TEST_WORKFLOW/.cga/` (default `$MRVA_WORK_DIR/workflow/.cga/`).
The workflow survives separate phase invocations; `reset` clears the default
workflow with the work directory. Do not reuse an old overridden workflow
after resetting the server database. `cga mr submit` refuses duplicate names.
Use `cga -C "$CGA_TEST_WORKFLOW" state show` or `tree show` to inspect it.

Phases stay separate so the failover/idle/restart scenarios can intervene
between submission, polling, and download. `run-system-08` deliberately sends
concurrent raw HTTP submissions, then records them with `cga mr attach`:
recording both submissions directly through one workflow would serialize them.
SQL assertions and endpoint-specific observations remain in the harness.

Scenarios `09` and `10` use separate recorded preparation and analysis
workflows. Their JSON session files are exported snapshots used by assertions
and dashboards, not manually threaded component state; see their local READMEs
for workflow locations and collection prerequisites.

## Configuration for sample workflow

The harness reads its configuration from `standalone-multi-agent-lib.sh`
(sourced by every `run-system-*` script and by the query/cleanup helpers). Every
value below is an environment variable of the form `${VAR:-default}`, so it can
be overridden by exporting it before invoking a runner, e.g.
`PORT=9091 ./run-system-02 all`. Go computes matching defaults on its own when a
variable is unset, so the harness stays fully in control.

`run-system-03` additionally exports its own work dir / logs / state (the
`*-multisession-*` variants) and sets `MRVA_STANDALONE_STORAGE=minio` before
sourcing the library; everything else it inherits from the table below.

### Server and inputs

| Variable                   | Default                             | Effect                                                                    |
| -------------------------- | ----------------------------------- | ------------------------------------------------------------------------- |
| `PORT`                     | `8081`                              | TCP port the Go server listens on (also exported as `SERVER_PORT`).       |
| `CONTROLLER_OWNER`         | `octo`                              | Controller-repo owner used in the submission URLs.                        |
| `CONTROLLER_REPO`          | `ctl`                               | Controller-repo name used in the submission URLs.                         |
| `SAMPLE_DB_ROOT`           | `$REPO_ROOT/sample-dbs`             | Root holding the sample CodeQL DBs, laid out `<language>/<owner>/<repo>`. |
| `QUERY_PATH`               | `$REPO_ROOT/sample-query/Fprintf.ql` | Query bundled into the pack (run-system-02's single shared pack).         |
| `LANGUAGE`                 | `cpp`                               | CodeQL language the query pack targets.                                   |
| `POLL_INTERVAL`            | `3`                                 | Seconds between job-status polls while waiting for completion.            |
| `POLL_DEADLINE_SECS`       | `600`                               | Maximum seconds to wait for all jobs to reach a terminal state.           |
| `CODEQL_JAVA_HOME`         | `/usr`                              | JDK for the CodeQL CLI (its bundled JRE can't exec on arm64).             |
| `CODEQL_CLI_PATH`          | `$(command -v codeql)`              | CodeQL binary used to build packs and analyze DBs.                        |
| `MRVA_ENVSIM_AGENT_BINARY` | `$REPO_ROOT/agent-commander-argo/mrvaagent` | Agent binary the server fork/execs per worker.                       |

### PostgreSQL

| Variable            | Default     | Effect                                                     |
| ------------------- | ----------- | ---------------------------------------------------------- |
| `POSTGRES_DB`       | `mrvadev`   | Database name (bootstrapped by the harness if absent).     |
| `POSTGRES_HOST`     | `localhost` | Postgres host.                                             |
| `POSTGRES_PORT`     | `5432`      | Postgres TCP port.                                         |
| `POSTGRES_USER`     | `$USER`     | Login role (created with `CREATEDB` if it does not exist). |
| `POSTGRES_PASSWORD` | `mrva`      | Password for the login role (scram auth over TCP).         |

### Artifact storage

| Variable                  | Default                      | Effect                                                                                                                |
| ------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `MRVA_STANDALONE_STORAGE` | `filesystem`                 | Artifact backend: `minio` or `filesystem`. run-system-03 sets `minio`.                                                |
| `MRVA_WORK_DIR`           | `/tmp/mrva-standalone-multi` | Root for `artifacts/`, `qldbs/`, and `minio-data/`. Wiped by `reset`/`cleanup`.                                       |
| `MINIO_PORT`              | `9000`                       | Port the local MinIO server listens on (only used when storage=minio).                                                |
| `MRVA_MINIO_ENDPOINT`     | `localhost:9000`             | MinIO endpoint the server/agent connect to.                                                                           |
| `MRVA_MINIO_ACCESS_KEY`   | `minioadmin`                 | MinIO access key (also MinIO's root user when the harness starts it).                                                 |
| `MRVA_MINIO_SECRET_KEY`   | `minioadmin`                 | MinIO secret key (also MinIO's root password).                                                                        |
| `MINIO_BUCKET`            | `mrvabucket`                 | Bucket holding packs and results.                                                                                     |
| `MINIO_DATA_DIR`          | `$MRVA_WORK_DIR/minio-data`  | On-disk object data dir for the local MinIO server.                                                                   |
| `MINIO_BIN`               | `minio`                      | MinIO **server** binary. Must be the community AGPLv3 build; the enterprise AIStor build denies S3 without a license. |

MinIO's log and PID file are harness bookkeeping (not read by the server) — see
[test runner Variables and locations](#test-runner-variables-and-locations).

### CodeQL database server

The server/agent no longer read CodeQL DBs from a shared on-disk `qldbs`
directory. Instead the harness owns the DB zips and serves them over HTTP; the
server/agent fetch each DB via the `HttpCodeQLDatabaseStore` (selected in
`deploy.InitStandaloneDatabaseStore` when `MRVA_DB_SERVER_URL` is set). This
keeps all server/agent-owned state out of harness-writable directories.

| Variable             | Default                   | Effect                                                                                         |
| -------------------- | ------------------------- | ---------------------------------------------------------------------------------------------- |
| `DB_SERVER_PORT`     | `9080`                    | Port the harness `python3 -m http.server` serves DB zips on.                                   |
| `MRVA_DB_SERVER_URL` | `http://127.0.0.1:9080`   | Base URL the server/agent fetch DBs from. When set, selects the HTTP DB store over filesystem. |
| `MRVA_DB_SERVE_DIR`  | `$MRVA_WORK_DIR/db-serve` | Harness-owned dir served at the base URL, laid out `<language>/<owner>/<repo>/..._db.zip`.     |

Each DB is fetched at
`<MRVA_DB_SERVER_URL>/<owner>/<repo>/<owner>_<repo>_db.zip` (HEAD to probe
availability, GET to download). The DB server's log and PID file are harness
bookkeeping — see
[test runner Variables and locations](#test-runner-variables-and-locations).

### Worker pool and scheduling

| Variable                        | Default                     | Effect                                                              |
| ------------------------------- | --------------------------- | ------------------------------------------------------------------- |
| `MRVA_CODEQL_THREADS`           | `2`                         | Cores per worker; also passed to CodeQL as its thread count.        |
| `MRVA_POOL_MAX_WORKERS`         | `(nproc-1)/threads` (min 1) | Max concurrent worker subprocesses.                                 |
| `MRVA_POOL_SCALE_CHECK_SECONDS` | `2`                         | Pool-manager scale-check interval (backstop when a wake is missed). |
| `MRVA_POOL_CLAIM_POLL_SECONDS`  | `2`                         | Interval at which an idle worker polls Postgres for a job to claim. |

### sysview dump (affects the server)

Only these two variables reach the server/agent; everything else in the old
"transient files" list is harness-only bookkeeping, documented under
[test runner Variables and locations](#test-runner-variables-and-locations)
below.

| Variable                 | Default        | Effect                                                                   |
| ------------------------ | -------------- | ------------------------------------------------------------------------ |
| `MRVA_DBG_DUMP_SYSVIEW`  | (empty = off)  | When set, `phase_start` passes `--dbg-dump-sysview` to the server.       |
| `MRVA_SYSVIEW_DUMP_PATH` | `sysview-dump` | Where the server appends sysview snapshots; removed by `stop`/`cleanup`. |

## Sample workflow

```sh
cd ~/work-ghp/single-machine-mrva/cga/system-tests

# Help: list all phases (this is also the no-argument default).
./run-system-02

# Clean up any leftovers from a previous run (stops the server, drops the
# MRVA tables, wipes the work dir).
./run-system-02 cleanup

# Optionally watch progress live while a run is in flight.
chromium-browser http://localhost:8081/sysview

# Full end-to-end test: preflight, reset, stage CodeQL DBs, build, start the
# server, submit two users' sessions (alice: 3 jobs, bob: 5 jobs = 8 jobs),
# poll to completion, and verify. Leaves the server running and Postgres
# populated for inspection.
./run-system-02 all

# Optional: SARIF ingestion (not part of `all`; SARIF processing is not MRVA
# core, but fits at the tail of a full run once artifacts exist). Run the
# three phases individually...
./run-system-02 copy_sarif   # collect result SARIF into data-large/, shaped
                             # like the sysview page:
                             #   user-<name>/session-<id>/job-<num>/...
./run-system-02 tolite       # each SARIF -> a per-job SQLite database
./run-system-02 toduck       # all SQLite -> one cumulative DuckDB

# ...or all three at once:
./run-system-02 ingest-all

# Optional: predefined result queries over the ingested databases.
../../sarif-ingest/bin/srfi -h
../../sarif-ingest/bin/srfi showprob data-large/all.duckdb   # kind:problem
../../sarif-ingest/bin/srfi showpath data-large/all.duckdb   # kind:path-problem
```

Other useful subcommands: `./run-system-02 where` (show the pipeline with a
pointer at the current step, non-destructive) and `./run-system-02 query` (dump
the Postgres state). The SARIF-ingest tool lives in `../../sarif-ingest/`; see
`../../sarif-ingest/notes/sarif-ingest.org` for details.

## Replayable sample workflow

The `/sysview` dashboard above is real-time. To capture system state over time
for later inspection or replay, start the server with `--dbg-dump-sysview`: at
every refresh interval it appends the current sysview as one JSON line to a dump
file (JSONL). The dump path defaults to `sysview-dump` (in the server's working
directory) and is overridable via `MRVA_SYSVIEW_DUMP_PATH`.

The `run-system-02` harness wires this in as an opt-in, so a normal `all` run
also records a replayable dump:

```sh
cd ~/work-ghp/single-machine-mrva/cga/system-tests

# Clean up any leftovers from a previous run (also removes the sysview dump).
./run-system-02 cleanup

# Full end-to-end run that also captures a sysview dump. The flag is opt-in
# (off by default); MRVA_SYSVIEW_DUMP_PATH chooses where the dump lands.
MRVA_DBG_DUMP_SYSVIEW=1 MRVA_SYSVIEW_DUMP_PATH=/tmp/sysview-dump \
    ./run-system-02 all
```

Because `all` leaves the server running, its dump keeps growing. Stop the server
(while keeping the Postgres tables, work dir and the dump) once the run is done:

```sh
# Stop the server but keep all state (restart later with 'start').
./run-system-02 stop
```

Then replay the captured run with the `sysview-view` tool, which serves the same
sysview UI driven by a vertical index slider (drag it, use the mouse wheel over
it, or press Up/Down and Home/End to scrub; Reload re-reads the dump while the
server is still appending):

```sh
cd ~/work-ghp/single-machine-mrva/sysview-view
go build ./...
./sysview-view --dump /tmp/sysview-dump --addr :8090

# then open the replay UI:
chromium-browser http://localhost:8090/
```

The live dashboard and the replay tool share their rendering code
(`mrvacommander/pkg/sysviewui`), so a replayed snapshot looks identical to the
live view at that moment. When you are finished, `./run-system-02 cleanup` tears
everything down and deletes the dump file. See `../../sysview-view/README.md` for
details.

For a copy you can archive or view with no running process at all (no
`mrvaserver`, no `sysview-view`), export the dump to a single self-contained
HTML file with the snapshots baked in, then open it directly with `file://`:

```sh
cd ~/work-ghp/single-machine-mrva/sysview-view
./sysview-view --dump /tmp/sysview-dump --export replay.html
chromium-browser replay.html
```

## For run-system-03

The same instructions apply verbatim to `run-system-03` (the one-user,
three-session, three-pack scenario) — just substitute `./run-system-03` for
`./run-system-02` in every command above:

```sh
cd ~/work-ghp/single-machine-mrva/cga/system-tests
./run-system-03 cleanup
MRVA_DBG_DUMP_SYSVIEW=1 MRVA_SYSVIEW_DUMP_PATH=/tmp/sysview-dump \
    ./run-system-03 all
./run-system-03 stop
```

## For run-system-04

The same instructions apply verbatim to `run-system-04` (the one-user,
three-session, distinct-language scenario — cpp/python/javascript) — just
substitute `./run-system-04` for `./run-system-02` in every command above:

```sh
cd ~/work-ghp/single-machine-mrva/cga/system-tests
./run-system-04 cleanup
MRVA_DBG_DUMP_SYSVIEW=1 MRVA_SYSVIEW_DUMP_PATH=/tmp/sysview-dump \
    ./run-system-04 all
./run-system-04 stop
```

## For run-system-05

The same instructions apply to `run-system-05` (the status + download scenario:
two users, one submission each — `bob-1` and `eve-1`) — just substitute
`./run-system-05` for `./run-system-02` in every command above:

```sh
cd ~/work-ghp/single-machine-mrva/cga/system-tests
./run-system-05 cleanup
MRVA_DBG_DUMP_SYSVIEW=1 MRVA_SYSVIEW_DUMP_PATH=/tmp/sysview-dump \
    ./run-system-05 all
./run-system-05 stop
```

## State inspection samples

Once a run has populated state you can inspect it directly. The connection
defaults below match the harness (see the configuration table above); override
the env vars if you changed them.

### Test Runner Variables and Locations

The configuration table near the top of this file lists every tunable with its
_shared-library_ default (i.e. the values `run-system-02` uses). This section
covers the harness-only bookkeeping that does **not** reach the server or agent:
per-scenario file locations. Each harness sets a short tag `RUN_TAG` (`<T>`)
before sourcing the shared lib; every transient file then lives under one
per-scenario dir, `/tmp/mrva-<T>/`, so runs never clobber each other and `/tmp`
stays tidy. On-disk stores (artifacts, staged DBs, MinIO objects) live under a
distinct `MRVA_WORK_DIR` (`$W`).

| Harness         | `RUN_TAG` (`<T>`) | `MRVA_WORK_DIR` (`$W`)              | Storage      |
| --------------- | ----------------- | ----------------------------------- | ------------ |
| `run-system-02` | `multi`           | `/tmp/mrva-standalone-multi`        | `filesystem` |
| `run-system-03` | `multisession`    | `/tmp/mrva-standalone-multisession` | `minio`      |
| `run-system-04` | `multilang`       | `/tmp/mrva-standalone-multilang`    | `minio`      |
| `run-system-05` | `statusdl`        | `/tmp/mrva-standalone-statusdl`     | `minio`      |

Transient files (harness-only) — all under `/tmp/mrva-<T>/`, wiped by
`reset`/`cleanup`:

| Variable          | Value                       | What lives there                          |
| ----------------- | --------------------------- | ----------------------------------------- |
| `MRVA_TMP_DIR`    | `/tmp/mrva-<T>`             | the per-scenario dir holding all of below |
| `SERVER_LOG`      | `/tmp/mrva-<T>/server.log`  | server + spawned-agents combined log      |
| `SERVER_PID_FILE` | `/tmp/mrva-<T>/server.pid`  | server PID                                |
| `REQ_LOG`         | `/tmp/mrva-<T>/req.log`     | CGA pack-build log                       |
| `SUBMIT_JSON`     | `/tmp/mrva-<T>/submit.json` | last submission request body              |
| `STATE_FILE`      | `/tmp/mrva-<T>/state.env`   | state handed between invocations (ids...) |
| `MINIO_LOG`       | `/tmp/mrva-<T>/minio.log`   | MinIO server log (when storage=minio)     |
| `MINIO_PID_FILE`  | `/tmp/mrva-<T>/minio.pid`   | MinIO server PID (when storage=minio)     |

On-disk stores (under `$W`; wiped by `reset`/`cleanup`):

| Variable            | Value           | What lives there                            |
| ------------------- | --------------- | ------------------------------------------- |
| `MRVA_ARTIFACT_DIR` | `$W/artifacts`  | filesystem artifact store (packs + results) |
| `MRVA_QLDB_DIR`     | `$W/qldbs`      | staged CodeQL databases                     |
| `MINIO_DATA_DIR`    | `$W/minio-data` | MinIO on-disk objects (when storage=minio)  |
| `DOWNLOAD_DIR`      | `$W/downloads`  | run-system-05 only: downloaded result zips  |

Other harness paths (fixed, shared across scenarios), used only by the optional
`ingest-*` SARIF phases:

| Variable         | Value                      | What it is                    |
| ---------------- | -------------------------- | ----------------------------- |
| `DATA_LARGE_DIR` | `data-large`               | output tree for SARIF ingest  |
| `SRFI`           | `$REPO_ROOT/sarif-ingest/bin/srfi` | path to the `srfi` SARIF tool |

Copy/paste: pick the harness you ran, then inspect its files:

```sh
# run-system-05 example (swap $W and $T for another harness via the table above).
W=/tmp/mrva-standalone-statusdl
T=statusdl

tail -n 40 "/tmp/mrva-${T}/server.log"   # server + agents
cat "/tmp/mrva-${T}/state.env"           # session ids, PIDs, pack SHA1s
ls -R "/tmp/mrva-${T}" "$W"              # transient files + on-disk stores
```

### Object storage (MinIO) via `mc`

The MinIO client is upstream `mc`; on this host the package installs the binary
as `mcli`. These commands need the MinIO server running (only relevant when
`MRVA_STANDALONE_STORAGE=minio`). Note that `run-system-03 stop` and `cleanup`
shut MinIO down, so inspect while a run is up, or restart the server against the
persisted data dir first (the objects survive on disk):

```sh
# Start MinIO against the persisted data (adjust the data dir to your work dir;
# run-system-03 defaults to /tmp/mrva-standalone-multisession/minio-data).
MINIO_ROOT_USER=minioadmin MINIO_ROOT_PASSWORD=minioadmin \
    minio server /tmp/mrva-standalone-multisession/minio-data --address :9000 &
```

Then register an alias for the local server and list / fetch objects:

```sh
# Register the local server as alias "local" (endpoint / access / secret).
mcli alias set local http://localhost:9000 minioadmin minioadmin

# Bucket list.
mcli ls local

# Bucket entries (recursive, with sizes) for the MRVA bucket.
mcli ls --recursive local/mrvabucket

# Entry download: copy one object to the current directory ...
mcli cp local/mrvabucket/<object-key> ./

# ... or stream it to stdout.
mcli cat local/mrvabucket/<object-key>
```

### PostgreSQL via `psql` (or `pgcli`)

`psql` is scriptable; `pgcli` gives the same access with autocompletion for
interactive poking. Both honour `PGPASSWORD`:

```sh
export PGPASSWORD=mrva            # POSTGRES_PASSWORD
PSQL="psql -h localhost -U $USER -d mrvadev"   # or: pgcli -h localhost -U $USER mrvadev

# Table list.
$PSQL -c '\dt'

# Table schema for one table (columns, types, indexes).
$PSQL -c '\d job_info'

# Table contents.
$PSQL -c 'SELECT * FROM job_info;'
$PSQL -c 'SELECT * FROM job_status;'
$PSQL -c 'SELECT * FROM worker_pool;'
```

# cgamx — CodeQL generic appliance: standalone MRVA infrastructure

`cgamx` owns the **standalone MRVA infrastructure** for the cga appliance:
Postgres, the MinIO artifact store, the CodeQL-database HTTP server, and the
`mrvaserver` process — plus the build, reset, log-scan and cleanup steps around
them. It is the CGAST-native replacement for the global phases that the cga
samples used to borrow from `cga/system-tests/run-system-05` (via a bash
`system_phase`/`phase_*` shim). With `cgamx`, an operator script drives the
whole lifecycle through cga\* binaries only, passing all state as CGAST.

Like every cga\* program it is a JSON-in / JSON-out filter: each command reads
the CGAST from stdin, runs one infrastructure phase, records runtime state
(process ids, chosen ports/paths) under the `cgamx` key, and writes the merged
CGAST to stdout. All human-readable and progress output goes to stderr, so the
program composes in a pipe with `cgadl`, `cgaql`, `cgamr`, and `cgasi`.

## Commands

```sh
cgamx preflight   # check codeql/go, ensure Postgres, free the ports
cgamx reset       # drop mrva tables, wipe work dir + logs
cgamx build       # build mrvaserver + mrvaagent
cgamx start       # start CodeQL DB server + mrvaserver (+ MinIO if storage=minio)
cgamx logs        # tail the server log + scan for errors
cgamx check       # error gate: non-zero exit on non-benign server errors
cgamx stop        # stop services, keep tables + work dir
cgamx cleanup     # stop services, drop tables, remove work dir
cgamx info        # print current infrastructure state (from the CGAST)
cgamx cmd         # serve the localhost command server (runs cga* commands)
```

Typical standalone bring-up and tear-down, threading one CGAST through:

```sh
s=cga-tmp/session.json
for phase in preflight reset build start; do
    cgamx "$phase" < "$s" > "$s".n && mv "$s".n "$s"
done
# ... run cgadl / cgaql / cgamr / cgasi against the live server ...
cgamx logs  < "$s" > "$s".n && mv "$s".n "$s"
cgamx check < "$s" > "$s".n && mv "$s".n "$s"   # PASS/FAIL gate
cgamx cleanup < "$s" > "$s".n && mv "$s".n "$s"
```

Inside an initialized workflow the top-level dispatcher performs that state
threading and immutable recording:

```sh
cga init .
cga mx preflight
cga chain start
cga mx reset
cga mx build
cga mx start
```

`start` records the `mrvaserver`, MinIO, and DB-server process ids in the CGAST
`cgamx` object, so a later `stop`/`cleanup` in a separate invocation finds them
there (PID files under the tmp dir and `ss`-based port reclaim are backstops).
Detached services are stopped by process group, ensuring that spawned MRVA
agents and in-flight CodeQL subprocesses cannot survive the server as orphans.

## Configuration

`cgamx` resolves every setting from the environment and computes a sane default
**only when the variable is unset**, so operator/harness overrides always win
and spawned `mrvaserver`/`mrvaagent` subprocesses inherit identical values.

Build sources, the server executable, and the default agent executable are
anchored to the checkout containing `cgamx`, not to `CGAST_ROOT` or `CGA_ROOT`.
Those variables control CGAST artifact paths; a separate workflow directory
does not relocate the source checkout. An explicit `MRVA_ENVSIM_AGENT_BINARY`
still overrides the default agent executable.

Notable variables (defaults in parentheses):

| Variable                                        | Default                                 |
| ----------------------------------------------- | --------------------------------------- |
| `PORT`                                          | `8081` (mrvaserver)                     |
| `MRVA_STANDALONE_STORAGE`                       | `filesystem` (or `minio`)               |
| `MRVA_WORK_DIR`                                 | `/tmp/mrva-cgamx`                       |
| `RUN_TAG` / `MRVA_TMP_DIR`                      | `cgamx` / `/tmp/mrva-<RUN_TAG>`         |
| `POSTGRES_{HOST,PORT,USER,PASSWORD,DB}`         | `localhost/active local cluster port/$USER/mrva/mrvadev` |
| `MINIO_PORT` / `MRVA_MINIO_*`                   | `9000` / `minioadmin`                   |
| `DB_SERVER_PORT` / `MRVA_DB_SERVER_URL`         | `9080` / `http://127.0.0.1:9080`        |
| `MRVA_QLDB_DIR`                                 | `$MRVA_WORK_DIR/qldbs`                  |
| `MRVA_DB_SERVE_DIR`                             | `$MRVA_WORK_DIR/db-serve`               |
| `MRVA_CODEQL_THREADS` / `MRVA_POOL_MAX_WORKERS` | `2` / `(cores-1)/threads`               |
| `MRVA_ENVSIM_AGENT_BINARY`                      | `<repo>/agent-commander-argo/mrvaagent` |
| `CODEQL_JAVA_HOME`                              | `/usr` (required on arm64)              |
| `SERVER_LOG`                                    | `$MRVA_TMP_DIR/server.log`              |

The CodeQL databases are served over HTTP from `MRVA_DB_SERVE_DIR`; populate it
with `cgadl download --output-dir "$MRVA_WORK_DIR/db-serve"` so `cgamx start`
and `cgamr submit` agree on the qldbstore tree.

`cga mx preflight` performs an autoconf-style PostgreSQL presence check before
starting infrastructure. It reports the discovered server executable and
version, `pg_isready`, local `pg_lsclusters` entries, and probes the configured
port plus likely local ports (`5432`, `5433`, `55432`, and `55440`). Findings
are printed and persisted under `cgamx.postgres_probe`; the configured endpoint
must still become ready before preflight succeeds.

Set `MRVA_DBG_DUMP_SYSVIEW=1` to have `start` pass `--dbg-dump-sysview` to the
server (dump path defaults in Go to `sysview-dump`, override with
`MRVA_SYSVIEW_DUMP_PATH`); `cleanup` removes the dump.

## The command server (`cgamx cmd`)

`cgamx cmd` is the one cga\* server that is **not** a read-only fragment viewer:
it lets the composite page turn a click into a real cga\* command. The page is
only a _view_ — its inputs are scratch space until you apply them — and applying
a change is defined to be _exactly_ the same as a user or LLM typing a new cga\*
command in the shell. `cgamx cmd` makes that literally true.

It binds to `127.0.0.1:$CGA_CGAMX_PORT` (default `8607`) and exposes:

```text
GET  /healthz   # readiness probe (launcher)
GET  /          # JSON index
POST /run       # run one cga* command as a CGAST filter
```

`POST /run` accepts a JSON body of either `{"argv": ["cgasi", "view", ...]}`
(preferred — no quoting ambiguity) or `{"command": "cgasi view ..."}`
(`shlex`-split, **never** a shell). It runs the named program with the shared
session CGAST (`$CGA_SESSION`) on stdin and, on success, atomically replaces the
session with the program's stdout. The command's stderr (its human channel) and
exit code come back as JSON.

When `CGA_WORKFLOW_ROOT` identifies an initialized `.cga/` workflow, the
server routes supported filter components through the top-level dispatcher
instead. Dashboard changes then create normal immutable steps with source
`dashboard`; `.cga/current.json` remains the viewer compatibility copy.

Safety: only programs whose base name matches `cga*` **and** resolve on `PATH`
may run, and the server is localhost-only. Anything else is refused with a
non-zero exit code and an explanatory message.

```sh
curl -s -X POST http://127.0.0.1:8607/run \
  -H 'Content-Type: application/json' \
  -d '{"argv":["cgasi","view","--erc","40","--user","^bob$","--clear"]}'
# -> {"ok": true, "exit_code": 0, ...}; $CGA_SESSION now has the new view
```

## Layout

Standard-library Python, mirroring the other cga\* handlers:

- `bin/cgamx` — thin POSIX launcher (puts `cgamx` and `cga/cgalib` on the path).
- `cgamx/cli.py` — argparse + CGAST glue (subcommand dispatch).
- `cgamx/infra.py` — the phase implementations and Postgres/MinIO/DB-server
  helpers (ported from `cga/system-tests/standalone-multi-agent-lib.sh` and the
  global phases of `cga/system-tests/run-system-05`).
- `cgamx/cmd.py` — the `cmd` command server (POST /run whitelist + atomic
  session swap).
- `tests/test_cli.py` — filter-contract, config, and log-scan tests.
- `tests/test_cmd.py` — command-server whitelist, body parsing, and
  session-threading tests.
- `tests/test_infra.py` — detached process-group termination tests.

Linux only: the phases rely on Linux process-management tools (`ss`, `kill`,
`setsid`) and a host Postgres. `cgamx` shares the MRVA server port and Postgres
with the rest of the appliance, so run only one MRVA scenario at a time.

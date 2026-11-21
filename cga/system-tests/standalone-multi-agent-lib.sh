# shellcheck shell=bash
# Shared config + helpers for the standalone multi-agent e2e scripts.
#
# This file is meant to be *sourced*, not executed:
#
#   run-system-02                          -- bring up + submit + verify
#   query-standalone-multi-agent-e2e.sh    -- dump Postgres schema + values
#   cleanup-standalone-multi-agent-e2e.sh  -- tear everything back down
#
# All variables use ${VAR:-default} so they can be overridden from the
# environment, and the three scripts stay in lockstep on ports, paths,
# the Postgres connection, and the set of tables involved.

TESTS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_ROOT/../.." && pwd)"

# CodeQL ships an x86_64 JRE that cannot exec on arm64; point it at the
# system JDK. Harmless on x86_64 Linux where /usr also holds a JDK.
export CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME:-/usr}"

# --- server / CGA client -----------------------------------------------

PORT="${PORT:-8081}"
export SERVER_PORT="$PORT"
SERVER="http://127.0.0.1:${PORT}"
CONTROLLER_OWNER="${CONTROLLER_OWNER:-octo}"
CONTROLLER_REPO="${CONTROLLER_REPO:-ctl}"

# The DBs analyzed in parallel. <owner>/<repo> pairs; the sample DB
# directory for each is $SAMPLE_DB_ROOT/<language>/<owner>/<repo>.
if [ -z "${DB_REPOS+set}" ]; then
    DB_REPOS=("debian/iniparser-4.1" "debian/lua-filesystem-1.8.0")
fi
SAMPLE_DB_ROOT="$(realpath -m "${SAMPLE_DB_ROOT:-${REPO_ROOT}/sample-dbs}")"
QUERY_PATH="$(realpath -m "${QUERY_PATH:-${REPO_ROOT}/sample-query/Fprintf.ql}")"
LANGUAGE="${LANGUAGE:-cpp}"
POLL_INTERVAL="${POLL_INTERVAL:-3}"
POLL_DEADLINE_SECS="${POLL_DEADLINE_SECS:-600}"

# --- Postgres -----------------------------------------------------------

POSTGRES_DB="${POSTGRES_DB:-mrvadev}"
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_USER="${POSTGRES_USER:-$USER}"
# TCP connections use scram auth on Debian/Ubuntu, so a non-empty
# password is required. Override POSTGRES_PASSWORD to match an existing
# role, or let pg_ensure_role_db create the role with this value.
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-mrva}"
export POSTGRES_DB
# Let every psql invocation authenticate over TCP without a prompt.
export PGPASSWORD="$POSTGRES_PASSWORD"

# The tables (and sequence) the Go server creates in standalone mode.
# Kept here so run (reset), query (dump) and cleanup (drop) agree.
MRVA_TABLES=(
    analyze_results analyze_jobs job_repo_map job_info
    job_status scheduler_lock server_registry worker_pool
    job_info_worker_id pending_spawns
)
MRVA_SEQUENCES=(session_id_seq)

# --- filesystem stores + logs ------------------------------------------

MRVA_WORK_DIR="$(realpath -m "${MRVA_WORK_DIR:-/tmp/mrva-standalone-multi}")"
export MRVA_ARTIFACT_DIR="${MRVA_WORK_DIR}/artifacts"
export MRVA_QLDB_DIR="${MRVA_WORK_DIR}/qldbs"

# Short per-scenario tag. Harnesses override RUN_TAG before sourcing so their
# transient files never clobber each other; run-system-02 keeps the default.
RUN_TAG="${RUN_TAG:-multi}"
# All harness-only bookkeeping (server/CGA/minio logs, PID files, the
# submission body, and the cross-invocation state file) lives under ONE
# per-scenario dir so it doesn't pollute /tmp. Still individually overridable.
MRVA_TMP_DIR="${MRVA_TMP_DIR:-/tmp/mrva-${RUN_TAG}}"
mkdir -p "$MRVA_TMP_DIR"

# --- CodeQL DB server (HTTP) -------------------------------------------
#
# The harness OWNS and SERVES the CodeQL databases; the Go server/agent only
# read them. A plain `python3 -m http.server` roots at MRVA_DB_SERVE_DIR and
# the Go HttpCodeQLDatabaseStore fetches from MRVA_DB_SERVER_URL, forming
# <baseURL>/<owner>/<repo>/<owner>_<repo>_db.zip (same layout as on disk). This
# keeps server/agent-owned state (artifact store, Postgres) free of
# harness-written database files. Set MRVA_DB_SERVER_URL="" to fall back to the
# server's local-filesystem DB store (--dbpath).
DB_SERVER_PORT="${DB_SERVER_PORT:-9080}"
export MRVA_DB_SERVER_URL="${MRVA_DB_SERVER_URL:-http://127.0.0.1:${DB_SERVER_PORT}}"
# The zip tree the harness serves. Kept under the work dir so a work-dir wipe
# clears it; it is NOT the server's --dbpath (the server never reads it).
MRVA_DB_SERVE_DIR="$(realpath -m "${MRVA_DB_SERVE_DIR:-${MRVA_WORK_DIR}/db-serve}")"
DB_SERVER_LOG="${DB_SERVER_LOG:-${MRVA_TMP_DIR}/db-server.log}"
DB_SERVER_PID_FILE="${DB_SERVER_PID_FILE:-${MRVA_TMP_DIR}/db-server.pid}"

# --- object storage (MinIO) --------------------------------------------
#
# Standalone artifact backend. The Go server/agent default to MinIO (blobs in
# object storage, only references in Postgres), but this harness defaults to
# the filesystem store so the existing run-system-02 scenario keeps working
# unchanged. A runner opts into MinIO by exporting MRVA_STANDALONE_STORAGE=minio
# BEFORE sourcing this file (see run-system-03).
export MRVA_STANDALONE_STORAGE="${MRVA_STANDALONE_STORAGE:-filesystem}"

# Local MinIO connection + credentials (only used when storage=minio). Go fills
# identical defaults when these are unset; set them here too so the harness
# helpers (start/stop/reclaim) and the server agree on endpoint + creds.
MINIO_PORT="${MINIO_PORT:-9000}"
export MRVA_MINIO_ENDPOINT="${MRVA_MINIO_ENDPOINT:-localhost:${MINIO_PORT}}"
export MRVA_MINIO_ACCESS_KEY="${MRVA_MINIO_ACCESS_KEY:-minioadmin}"
export MRVA_MINIO_SECRET_KEY="${MRVA_MINIO_SECRET_KEY:-minioadmin}"
# MinIO object data lives under the work dir, so a work-dir wipe clears it.
MINIO_DATA_DIR="${MINIO_DATA_DIR:-${MRVA_WORK_DIR}/minio-data}"
MINIO_LOG="${MINIO_LOG:-${MRVA_TMP_DIR}/minio.log}"
MINIO_PID_FILE="${MINIO_PID_FILE:-${MRVA_TMP_DIR}/minio.pid}"
# The MinIO server binary. Must be the community (AGPLv3) server build; the
# enterprise "AIStor" build denies all S3 operations without a license.
MINIO_BIN="${MINIO_BIN:-minio}"
# Single shared bucket for packs and results (matches the Go default).
MINIO_BUCKET="${MINIO_BUCKET:-mrvabucket}"

# SARIF ingest (the optional `ingest-*` phases). SARIF processing is not part
# of MRVA core, so this lives outside MRVA_WORK_DIR: the collected SARIF and
# the SQLite/DuckDB databases derived from it are kept under the repo's
# cga/system-tests/data-large tree, mirroring the sysview page's grouping
# (user-<name>/session-<id>/job-<num>). Relative paths use the harness cwd.
DATA_LARGE_DIR="${DATA_LARGE_DIR:-data-large}"
SRFI="${SRFI:-${REPO_ROOT}/sarif-ingest/bin/srfi}"
export MRVA_STANDALONE=true
export MRVA_ENVSIM_AGENT_BINARY="${MRVA_ENVSIM_AGENT_BINARY:-${REPO_ROOT}/agent-commander-argo/mrvaagent}"
export CODEQL_CLI_PATH="${CODEQL_CLI_PATH:-$(command -v codeql || true)}"

CGA_TEST_WORKFLOW="${CGA_TEST_WORKFLOW:-${MRVA_WORK_DIR}/workflow}"

cga() {
    if [ ! -f "$CGA_TEST_WORKFLOW/.cga/config" ]; then
        mkdir -p "$CGA_TEST_WORKFLOW"
        "$REPO_ROOT/cga/cga" init "$CGA_TEST_WORKFLOW" >&2 || return
        "$REPO_ROOT/cga/cga" -C "$CGA_TEST_WORKFLOW" chain start --name "$RUN_TAG" >&2 || return
    fi
    "$REPO_ROOT/cga/cga" -C "$CGA_TEST_WORKFLOW" "$@"
}

cga_pack_query() {
    local query="$1" output="$2"
    query="$(realpath "$query")" || return
    output="$(realpath -m "$output")" || return
    cga ql index "$(dirname "$query")" || return
    cga ql select relpath "$(basename "$query")" || return
    CGA_CGAQL_CODEQL="$CODEQL_CLI_PATH" cga ql pack --output "$output"
}

cga_submit() {
    local name="$1" user="$2" language="$3" pack="$4" server="$5"
    shift 5
    pack="$(realpath "$pack")" || return
    cga mr submit --name "$name" --user "$user" --language "$language" \
        --pack "$pack" --repos "$@" --server "$server" \
        --controller-owner "$CONTROLLER_OWNER" --controller-repo "$CONTROLLER_REPO" || return
    cga --json state show | python3 -c \
        'import json,sys; print(json.dumps(json.load(sys.stdin)["cgamr-submissions"][sys.argv[1]]["response"]))' "$name"
}

cga_status_json() {
    local name="$1"; shift
    cga mr status --name "$name" "$@" || return
    cga --json state show | python3 -c \
        'import json,sys; print(json.dumps(json.load(sys.stdin)["cgamr-submissions"][sys.argv[1]]["status_response"]))' "$name"
}

# Worker-pool sizing (overridable for maximum flexibility). Default to 2 cores
# per worker and (syscores - 1) / cores-per-worker workers, matching the Go
# standalone defaults. Explicit env values (from the caller) always win.
export MRVA_CODEQL_THREADS="${MRVA_CODEQL_THREADS:-2}"
_syscores="$(nproc 2>/dev/null || echo 1)"
_default_workers=$(( (_syscores - 1) / MRVA_CODEQL_THREADS ))
[ "$_default_workers" -lt 1 ] && _default_workers=1
export MRVA_POOL_MAX_WORKERS="${MRVA_POOL_MAX_WORKERS:-$_default_workers}"

# Scheduling responsiveness (overridable). The pool manager is also woken on
# job submission, so these are the backstop when a wake is missed; keep them
# small locally so worker spawn and idle job pickup stay snappy.
export MRVA_POOL_SCALE_CHECK_SECONDS="${MRVA_POOL_SCALE_CHECK_SECONDS:-2}"
export MRVA_POOL_CLAIM_POLL_SECONDS="${MRVA_POOL_CLAIM_POLL_SECONDS:-2}"

# Optional sysview capture for later inspection/replay with sysview-view.
# Off by default; set MRVA_DBG_DUMP_SYSVIEW=1 to have phase_start pass
# --dbg-dump-sysview to the server. The dump path itself defaults in Go
# (sysview-dump); override with MRVA_SYSVIEW_DUMP_PATH.
MRVA_DBG_DUMP_SYSVIEW="${MRVA_DBG_DUMP_SYSVIEW:-}"

# Where the server writes its sysview dump (relative to the server's cwd,
# i.e. system-tests/, unless absolute). `stop`/`cleanup` remove it. Keep the
# default in sync with the Go default ("sysview-dump").
SYSVIEW_DUMP_PATH="${MRVA_SYSVIEW_DUMP_PATH:-sysview-dump}"

SERVER_LOG="${SERVER_LOG:-${MRVA_TMP_DIR}/server.log}"
SERVER_PID_FILE="${SERVER_PID_FILE:-${MRVA_TMP_DIR}/server.pid}"
REQ_LOG="${REQ_LOG:-${MRVA_TMP_DIR}/req.log}"
SUBMIT_JSON="${SUBMIT_JSON:-${MRVA_TMP_DIR}/submit.json}"

# State handed from `run` to `query`/`cleanup` (e.g. the session id). It
# lives under MRVA_TMP_DIR (outside MRVA_WORK_DIR) so it survives even if the
# work dir is wiped, and so cleanup can find it to remove.
STATE_FILE="${STATE_FILE:-${MRVA_TMP_DIR}/state.env}"

# Friendly names for common.Status integer codes (pkg/common/types.go).
status_name() {
    case "$1" in
        0) echo "Pending"   ;;
        1) echo "Queued"    ;;
        2) echo "Succeeded" ;;
        3) echo "Failed"    ;;
        *) echo "Status($1)" ;;
    esac
}

# psql wrapper bound to the mrva database. Extra args pass through.
psql_mrva() {
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
         -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

# Persist a KEY=VALUE line to the state file (idempotent per key).
save_state() {
    local key="$1" val="$2"
    mkdir -p "$(dirname "$STATE_FILE")"
    if [ -f "$STATE_FILE" ]; then
        grep -v "^${key}=" "$STATE_FILE" > "${STATE_FILE}.tmp" 2>/dev/null || true
        mv "${STATE_FILE}.tmp" "$STATE_FILE"
    fi
    echo "${key}=${val}" >> "$STATE_FILE"
}

# Load the state file if present (defines SID, SERVER_PID, ... in scope).
load_state() {
    if [ -f "$STATE_FILE" ]; then
        # shellcheck disable=SC1090
        . "$STATE_FILE"
    fi
}

# Ensure the host Postgres is accepting connections, starting it if the
# platform tooling allows.
pg_ensure_running() {
    if pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" >/dev/null 2>&1; then
        return 0
    fi
    echo "starting PostgreSQL"
    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl start postgresql >/dev/null 2>&1 || \
            systemctl start postgresql >/dev/null 2>&1 || true
    elif command -v pg_ctlcluster >/dev/null 2>&1; then
        local pg_ver
        pg_ver="$(ls /usr/lib/postgresql/ 2>/dev/null | sort -n | tail -1)"
        if [ -n "$pg_ver" ]; then
            sudo pg_ctlcluster "$pg_ver" main start >/dev/null 2>&1 || \
                pg_ctlcluster "$pg_ver" main start >/dev/null 2>&1 || true
        fi
    fi
    local _
    for _ in $(seq 1 30); do
        if pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done
}

# Ensure the login role and database exist. On Debian/Ubuntu the only
# preinstalled role is `postgres` (peer auth over the local socket) and
# TCP uses scram, so bootstrap the role + database via the postgres
# superuser if we can't already authenticate over TCP.
pg_ensure_role_db() {
    if psql_mrva -c "SELECT 1;" >/dev/null 2>&1; then
        return 0
    fi
    echo "bootstrapping role '${POSTGRES_USER}' and database '${POSTGRES_DB}'"
    sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
   IF EXISTS (SELECT FROM pg_roles WHERE rolname = '${POSTGRES_USER}') THEN
      ALTER ROLE "${POSTGRES_USER}" LOGIN CREATEDB PASSWORD '${POSTGRES_PASSWORD}';
   ELSE
      CREATE ROLE "${POSTGRES_USER}" LOGIN CREATEDB PASSWORD '${POSTGRES_PASSWORD}';
   END IF;
END
\$\$;
SQL
    if ! sudo -u postgres psql -tAc \
            "SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}';" \
            | grep -q 1; then
        sudo -u postgres createdb -O "$POSTGRES_USER" "$POSTGRES_DB"
    fi
}

# --- MinIO lifecycle (only active when MRVA_STANDALONE_STORAGE=minio) ---

# True when the standalone artifact backend is MinIO.
storage_is_minio() { [ "${MRVA_STANDALONE_STORAGE}" = "minio" ]; }

# Print the PIDs listening on a TCP port, one per line. Uses `ss` (always
# present here; `lsof` is not), so it reliably finds orphaned listeners.
# Always exits 0 (empty output when nothing is listening) so it is safe under
# `set -e` in command substitutions.
pids_on_port() {
    local port="$1"
    ss -ltnp 2>/dev/null \
        | awk -v p=":${port}\$" '$4 ~ p' \
        | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true
}

# Reclaim the MinIO port: kill any stale process bound to it. No-op unless the
# MinIO backend is selected.
minio_reclaim_port() {
    storage_is_minio || return 0
    local pids p
    pids="$(pids_on_port "$MINIO_PORT")"
    if [ -n "$pids" ]; then
        echo "killing stale processes on MinIO port ${MINIO_PORT}: ${pids}"
        for p in $pids; do kill "$p" 2>/dev/null || true; done
        sleep 1
    fi
}

# Start a local MinIO server on MINIO_PORT with data under MINIO_DATA_DIR.
# No-op unless the MinIO backend is selected. Idempotent: returns early if a
# MinIO is already answering health checks on the endpoint.
minio_start() {
    storage_is_minio || return 0
    echo "--- starting MinIO on :${MINIO_PORT} (data ${MINIO_DATA_DIR}) ---"
    if curl -sf "http://${MRVA_MINIO_ENDPOINT}/minio/health/live" >/dev/null 2>&1; then
        echo "  MinIO already running on ${MRVA_MINIO_ENDPOINT}"
        return 0
    fi
    if ! command -v "$MINIO_BIN" >/dev/null 2>&1; then
        echo "ERROR: MinIO server '$MINIO_BIN' not found on PATH (install it, or set MRVA_STANDALONE_STORAGE=filesystem)" >&2
        return 1
    fi
    mkdir -p "$MINIO_DATA_DIR"
    MINIO_ROOT_USER="$MRVA_MINIO_ACCESS_KEY" \
    MINIO_ROOT_PASSWORD="$MRVA_MINIO_SECRET_KEY" \
        nohup "$MINIO_BIN" server "$MINIO_DATA_DIR" --address ":${MINIO_PORT}" \
            > "$MINIO_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$MINIO_PID_FILE"
    save_state MINIO_PID "$pid"
    local _
    for _ in $(seq 1 40); do
        if curl -sf "http://${MRVA_MINIO_ENDPOINT}/minio/health/live" >/dev/null 2>&1; then
            echo "  MinIO up (pid ${pid})"
            return 0
        fi
        sleep 0.5
    done
    echo "ERROR: MinIO did not come up. Tail:" >&2
    tail -20 "$MINIO_LOG" >&2
    return 1
}

# Stop the local MinIO server (by recorded pid and by port). Keeps the data
# dir. No-op unless the MinIO backend is selected.
minio_stop() {
    storage_is_minio || return 0
    load_state
    local stopped=0 pid seen="" p
    for pid in "${MINIO_PID:-}" "$(cat "$MINIO_PID_FILE" 2>/dev/null || true)"; do
        [ -n "$pid" ] || continue
        case " $seen " in *" $pid "*) continue ;; esac
        seen="$seen $pid"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            echo "  sent SIGTERM to MinIO pid ${pid}"
            stopped=1
        fi
    done
    for p in $(pids_on_port "$MINIO_PORT"); do
        kill "$p" 2>/dev/null || true
        echo "  killed process on MinIO port ${MINIO_PORT}: ${p}"
        stopped=1
    done
    rm -f "$MINIO_PID_FILE"
    [ "$stopped" -eq 1 ] || echo "  (no running MinIO found)"
    return 0
}

# True when the Go DB store is the HTTP store (harness serves DBs over HTTP).
# When MRVA_DB_SERVER_URL is empty the server falls back to its --dbpath store,
# so the harness DB server is not needed.
db_server_enabled() { [ -n "${MRVA_DB_SERVER_URL:-}" ]; }

# Reclaim the DB-server port: kill any stale process bound to it. No-op when
# the HTTP DB store is disabled.
db_server_reclaim_port() {
    db_server_enabled || return 0
    local pids p
    pids="$(pids_on_port "$DB_SERVER_PORT")"
    if [ -n "$pids" ]; then
        echo "killing stale processes on DB-server port ${DB_SERVER_PORT}: ${pids}"
        for p in $pids; do kill "$p" 2>/dev/null || true; done
        sleep 1
    fi
}

# Start a plain HTTP file server rooting at MRVA_DB_SERVE_DIR so the Go
# HttpCodeQLDatabaseStore can fetch DB zips. No-op when the HTTP DB store is
# disabled. Idempotent: returns early if the port already answers.
db_server_start() {
    db_server_enabled || return 0
    echo "--- starting CodeQL DB server on :${DB_SERVER_PORT} (root ${MRVA_DB_SERVE_DIR}) ---"
    if curl -sf "${MRVA_DB_SERVER_URL}/" >/dev/null 2>&1; then
        echo "  DB server already running on ${MRVA_DB_SERVER_URL}"
        return 0
    fi
    mkdir -p "$MRVA_DB_SERVE_DIR"
    # Fully detach: new session (setsid), stdin from /dev/null, stdout/stderr to
    # the log, and disown so this never-terminating server is not a tracked job
    # the parent shell would wait on (or keep the pipe open for) at exit.
    setsid python3 -m http.server "$DB_SERVER_PORT" --bind 127.0.0.1 \
        --directory "$MRVA_DB_SERVE_DIR" \
        </dev/null > "$DB_SERVER_LOG" 2>&1 &
    local pid=$!
    disown "$pid" 2>/dev/null || true
    echo "$pid" > "$DB_SERVER_PID_FILE"
    save_state DB_SERVER_PID "$pid"
    local _
    for _ in $(seq 1 40); do
        if curl -sf "${MRVA_DB_SERVER_URL}/" >/dev/null 2>&1; then
            echo "  DB server up (pid ${pid})"
            return 0
        fi
        sleep 0.5
    done
    echo "ERROR: DB server did not come up. Tail:" >&2
    tail -20 "$DB_SERVER_LOG" >&2
    return 1
}

# Stop the harness DB server (by recorded pid and by port). No-op when the
# HTTP DB store is disabled.
db_server_stop() {
    db_server_enabled || return 0
    load_state
    local stopped=0 pid seen="" p
    for pid in "${DB_SERVER_PID:-}" "$(cat "$DB_SERVER_PID_FILE" 2>/dev/null || true)"; do
        [ -n "$pid" ] || continue
        case " $seen " in *" $pid "*) continue ;; esac
        seen="$seen $pid"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            echo "  sent SIGTERM to DB-server pid ${pid}"
            stopped=1
        fi
    done
    for p in $(pids_on_port "$DB_SERVER_PORT"); do
        kill "$p" 2>/dev/null || true
        echo "  killed process on DB-server port ${DB_SERVER_PORT}: ${p}"
        stopped=1
    done
    rm -f "$DB_SERVER_PID_FILE"
    [ "$stopped" -eq 1 ] || echo "  (no running DB server found)"
    return 0
}

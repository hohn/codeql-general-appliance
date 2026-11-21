#!/usr/bin/env bash
# Tear down everything left running/populated by
# run-system-02: the Go server (and the agent
# subprocesses it spawned), the Postgres tables, the filesystem work
# dir, and the transient log/state files.
#
# Postgres itself (the server/cluster) is left running -- we only drop
# the mrva tables, not the database or the host service. Run from the
# system-tests/ directory.
#
# Idempotent: safe to run even if `run` was never invoked or already
# cleaned up.

set -euo pipefail

case "$#:${1:-}" in
    1:-h|1:--help|1:help)
        echo "Usage: $0"
        echo "Stop configured services and remove MRVA tables, work files, and logs."
        exit 0
        ;;
    0:) ;;
    *) echo "ERROR: unexpected arguments" >&2; exit 2 ;;
esac

# shellcheck source=standalone-multi-agent-lib.sh
. "$(dirname "$0")/standalone-multi-agent-lib.sh"

load_state

# --- 1. stop the server (kills its child agent processes too) ----------

echo "--- 1. stopping Go server ---"
stopped=0
# Prefer the pid recorded in the state file / pid file (dedup identical).
seen_pids=""
for pid in "${SERVER_PID:-}" "$(cat "$SERVER_PID_FILE" 2>/dev/null || true)"; do
    [ -n "$pid" ] || continue
    case " $seen_pids " in *" $pid "*) continue ;; esac
    seen_pids="$seen_pids $pid"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "  sent SIGTERM to server pid ${pid}"
        stopped=1
    fi
done
# Backstop: anything still bound to our port.
STALE_PIDS="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
if [ -n "$STALE_PIDS" ]; then
    for p in $STALE_PIDS; do
        kill "$p" 2>/dev/null || true
        echo "  killed process on port ${PORT}: ${p}"
        stopped=1
    done
fi
[ "$stopped" -eq 1 ] || echo "  (no running server found)"
sleep 1

# --- 1b. stop MinIO (only when the MinIO backend is in use) ------------

if storage_is_minio; then
    echo "--- 1b. stopping MinIO ---"
    minio_stop
fi

# --- 1c. stop the harness CodeQL DB server (HTTP store only) -----------

if db_server_enabled; then
    echo "--- 1c. stopping CodeQL DB server ---"
    db_server_stop
fi

# --- 2. drop the mrva tables -------------------------------------------

echo "--- 2. dropping mrva tables ---"
if psql_mrva -c "SELECT 1;" >/dev/null 2>&1; then
    psql_mrva -q -c "
DROP TABLE IF EXISTS $(IFS=,; echo "${MRVA_TABLES[*]}") CASCADE;
DROP SEQUENCE IF EXISTS $(IFS=,; echo "${MRVA_SEQUENCES[*]}") CASCADE;
" >/dev/null
    echo "  dropped: ${MRVA_TABLES[*]}"
else
    echo "  (cannot connect to ${POSTGRES_DB}; nothing dropped)"
fi

# --- 3. remove filesystem work dir + transient files -------------------

echo "--- 3. removing work dir + logs ---"
rm -rf "$MRVA_WORK_DIR" "$MRVA_TMP_DIR"
# sysview dump (from --dbg-dump-sysview); path may have been recorded in state.
rm -f "${SYSVIEW_DUMP_PATH:-sysview-dump}"
echo "  removed ${MRVA_WORK_DIR}, ${MRVA_TMP_DIR} and transient files"

echo "cleanup complete."

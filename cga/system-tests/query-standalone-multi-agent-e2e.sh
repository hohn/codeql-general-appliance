#!/usr/bin/env bash
# Inspect the Postgres state left behind by
# run-system-02: table schemas and their current
# row values, plus a couple of decoded per-session views.
#
# Safe to run repeatedly; it only reads. Run it after the `run` script
# and before `cleanup`. Run from the system-tests/ directory.

set -euo pipefail

case "$#:${1:-}" in
    1:-h|1:--help|1:help)
        echo "Usage: $0"
        echo "Read the configured MRVA PostgreSQL state without changing it."
        exit 0
        ;;
    0:) ;;
    *) echo "ERROR: unexpected arguments" >&2; exit 2 ;;
esac

# shellcheck source=standalone-multi-agent-lib.sh
. "$(dirname "$0")/standalone-multi-agent-lib.sh"

# Pick up SID (and other run outputs) if the run script recorded them.
load_state

if ! psql_mrva -c "SELECT 1;" >/dev/null 2>&1; then
    echo "ERROR: cannot connect to ${POSTGRES_DB} at ${POSTGRES_HOST}:${POSTGRES_PORT} as ${POSTGRES_USER}."
    echo "Run ./run-system-02 all first."
    exit 1
fi

echo "=== database ${POSTGRES_DB} @ ${POSTGRES_HOST}:${POSTGRES_PORT} (user ${POSTGRES_USER}) ==="
if [ -n "${SID:-}" ]; then
    echo "session id (from state file): ${SID}"
fi
echo

# --- 1. relation overview ----------------------------------------------

echo "=== 1. relations ==="
psql_mrva -c "\dt+"
echo "=== sequences ==="
psql_mrva -c "\ds"

# --- 2. per-table schema + values --------------------------------------
#
# For each mrva table that actually exists: print its full schema (\d+)
# followed by every row.
#
# INVARIANT: large state is never stored in Postgres -- it lives in
# MinIO/S3 or on the filesystem artifact store; Postgres holds only
# *references*. So jsonb columns here (payload/result) must stay small.
# Section 2b below asserts that; if it flags an oversized row, something
# is wrong (a blob leaked into the DB).

for tbl in "${MRVA_TABLES[@]}"; do
    exists="$(psql_mrva -t -A -c \
        "SELECT to_regclass('public.${tbl}') IS NOT NULL;" 2>/dev/null \
        | tr -d '[:space:]')"
    if [ "$exists" != "t" ]; then
        continue
    fi
    echo
    echo "=================================================================="
    echo "=== table: ${tbl} ==="
    echo "=================================================================="
    echo "--- schema ---"
    psql_mrva -c "\d+ ${tbl}"
    rows="$(psql_mrva -t -A -c "SELECT COUNT(*) FROM ${tbl};" 2>/dev/null \
            | tr -d '[:space:]')"
    echo "--- values (${rows} row(s)) ---"
    psql_mrva -x -c "SELECT * FROM ${tbl};"
done

# --- 2b. blob-size guard -----------------------------------------------
#
# Enforce the "references only" invariant: every jsonb column in every
# mrva table must be small. Anything over BLOB_WARN_BYTES is almost
# certainly bulk state (a query pack, SARIF, DB zip) that leaked into
# Postgres instead of the artifact store.

BLOB_WARN_BYTES="${BLOB_WARN_BYTES:-65536}"   # 64 KiB
echo
echo "=================================================================="
echo "=== 2b. blob-size guard (jsonb must be references, < ${BLOB_WARN_BYTES} B) ==="
echo "=================================================================="
BLOB_VIOLATION=0
# All jsonb columns across the mrva tables.
json_cols="$(psql_mrva -t -A -F'|' -c "
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema='public'
  AND data_type='jsonb'
ORDER BY table_name, column_name;" 2>/dev/null)"
if [ -z "$json_cols" ]; then
    echo "  (no jsonb columns present)"
else
    while IFS='|' read -r tbl col; do
        [ -n "$tbl" ] || continue
        maxsz="$(psql_mrva -t -A -c \
            "SELECT COALESCE(MAX(pg_column_size(${col})), 0) FROM ${tbl};" \
            2>/dev/null | tr -d '[:space:]')"
        if [ "${maxsz:-0}" -gt "$BLOB_WARN_BYTES" ]; then
            echo "  WARN ${tbl}.${col}: max ${maxsz} B exceeds ${BLOB_WARN_BYTES} B -- possible blob leak!"
            psql_mrva -c \
                "SELECT owner, repo, pg_column_size(${col}) AS bytes
                   FROM ${tbl}
                  WHERE pg_column_size(${col}) > ${BLOB_WARN_BYTES}
                  ORDER BY bytes DESC;"
            BLOB_VIOLATION=1
        else
            echo "  ok   ${tbl}.${col}: max ${maxsz:-0} B"
        fi
    done <<< "$json_cols"
fi
if [ "$BLOB_VIOLATION" -eq 0 ]; then
    echo "  PASS: all jsonb columns hold only small references."
else
    echo "  FAIL: oversized jsonb detected -- large state must live in the artifact store, not Postgres."
fi

# --- 3. decoded per-session views --------------------------------------

echo
echo "=================================================================="
echo "=== 3. decoded views ==="
echo "=================================================================="

# job_status with the integer status code translated to a name.
echo "--- job_status (status decoded) ---"
psql_mrva -c "
SELECT session_id,
       owner,
       repo,
       status AS status_code,
       CASE status
           WHEN 0 THEN 'Pending'
           WHEN 1 THEN 'Queued'
           WHEN 2 THEN 'Succeeded'
           WHEN 3 THEN 'Failed'
           ELSE 'Status(' || status || ')'
       END AS status_name
FROM job_status
ORDER BY session_id, owner, repo;"

# Which worker ran which job, and how long it took.
echo "--- job_info (worker + timing) ---"
psql_mrva -c "
SELECT session_id,
       owner,
       repo,
       worker_id,
       started_at,
       completed_at,
       (completed_at - started_at) AS duration
FROM job_info
ORDER BY session_id, owner, repo;"

# Worker pool: how many jobs each worker completed.
echo "--- worker_pool ---"
psql_mrva -c "
SELECT worker_id,
       status,
       jobs_completed,
       current_job,
       registered_at,
       heartbeat_at
FROM worker_pool
ORDER BY worker_id;"

echo
echo "done. Tear down with ./cleanup-standalone-multi-agent-e2e.sh"

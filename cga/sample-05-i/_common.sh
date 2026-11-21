#!/usr/bin/env bash
# Shared environment and atomic CGAST update helpers for sample-05-i.
#
# sample-05-i is the STANDALONE twin of sample-05. Every NN-*.sh script drives
# the MRVA lifecycle through cga* binaries ONLY, passing all state as a CGAST
# JSON object. The infrastructure phases that sample-05 borrowed from
# cga/system-tests/run-system-05 are now owned by the `cgamx` component
# (cga/cgamx), invoked here exactly like the other cga* filters.
set -euo pipefail

SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CGA_ROOT="$(cd "${SAMPLE_DIR}/.." && pwd)"
export CGA_ROOT
REPO_ROOT="$(cd "${CGA_ROOT}/.." && pwd)"
export REPO_ROOT
export CGA_TMPDIR="${CGA_TMPDIR:-${CGA_ROOT}/cga-tmp}"
export CGA_SESSION="${CGA_SESSION:-${CGA_TMPDIR}/sample-05-i.json}"
export CGA_HISTORY_DIR="${CGA_HISTORY_DIR:-${CGA_TMPDIR}/sample-05-i-history}"
export CGA_RUN_DIR="${CGA_RUN_DIR:-${CGA_ROOT}/.run/sample-05-i}"
export CGA_DASHBOARD_DUMP="${CGA_DASHBOARD_DUMP:-${CGA_TMPDIR}/sample-05-i-dashboard.jsonl}"
export CGA_DASHBOARD_EXPORT="${CGA_DASHBOARD_EXPORT:-${CGA_TMPDIR}/sample-05-i-replay.html}"

# Put every cga*/bin and the cga root (for `cga run`) on PATH so the NN scripts
# call the component binaries by bare name.
for _bin in "${CGA_ROOT}"/*/bin; do
    case ":${PATH}:" in
        *":${_bin}:"*) ;;
        *) PATH="${_bin}:${PATH}" ;;
    esac
done
case ":${PATH}:" in *":${CGA_ROOT}:"*) ;; *) PATH="${CGA_ROOT}:${PATH}" ;; esac
export PATH

# Dedicated viewer ports keep this sample independent from sample-05 (8700-8708)
# and the default CGA page (8600-8608).
export CGA_PAGE_PORT="${CGA_PAGE_PORT:-8710}"
export CGA_CGASV_PORT="${CGA_CGASV_PORT:-8711}"
export CGA_CGADL_PORT="${CGA_CGADL_PORT:-8712}"
export CGA_CGAQL_PORT="${CGA_CGAQL_PORT:-8713}"
export CGA_CGAMR_PORT="${CGA_CGAMR_PORT:-8714}"
export CGA_CGAMU_PORT="${CGA_CGAMU_PORT:-8715}"
export CGA_CGASI_PORT="${CGA_CGASI_PORT:-8716}"
export CGA_CGAMX_PORT="${CGA_CGAMX_PORT:-8717}"
export CGA_CGAEX_PORT="${CGA_CGAEX_PORT:-8718}"

# Sample identity. cgamx computes every other MRVA setting (Postgres, MinIO,
# DB-server, pool sizing, ...) from these with ${VAR:-default}, so overriding
# any of them here is enough to keep the whole sample self-consistent.
export RUN_TAG="${RUN_TAG:-cga-sample-05-i}"
export MRVA_WORK_DIR="${MRVA_WORK_DIR:-/tmp/mrva-cga-sample-05-i}"
export MRVA_TMP_DIR="${MRVA_TMP_DIR:-/tmp/mrva-${RUN_TAG}}"
export MRVA_STANDALONE_STORAGE="${MRVA_STANDALONE_STORAGE:-filesystem}"
export PORT="${PORT:-8081}"
export CGA_MRVA_SERVER="${CGA_MRVA_SERVER:-http://127.0.0.1:${PORT}}"
export CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME:-/usr}"

mkdir -p "$CGA_TMPDIR"

ensure_session() {
    if [ ! -s "$CGA_SESSION" ]; then
        printf '{}\n' > "$CGA_SESSION"
    fi
}

# Start a new snapshot chain from {} or from an immutable node in an earlier
# chain. CGA_CHAIN_PARENT is the convenient manual-run override.
cga_start_chain() {
    local parent="${1:-${CGA_CHAIN_PARENT:-}}"
    local chain
    chain="$(python3 "${SAMPLE_DIR}/_history.py" \
        --history-dir "$CGA_HISTORY_DIR" --session "$CGA_SESSION" \
        start ${parent:+--parent "$parent"})" || return $?
    printf 'CGAST chain: %s\n' "$chain"
}

cga_step() {
    ensure_session
    local tmp source_path source_step node
    tmp="$(mktemp "${CGA_TMPDIR}/sample-05-i.next.XXXXXX")"
    if "$@" < "$CGA_SESSION" > "$tmp"; then
        source_path="${BASH_SOURCE[2]-interactive}"
        source_step="$(basename "$source_path" .sh)"
        if node="$(python3 "${SAMPLE_DIR}/_history.py" \
            --history-dir "$CGA_HISTORY_DIR" --session "$CGA_SESSION" \
            record --output "$tmp" --source-step "$source_step" -- "$@")"; then
            rm -f "$tmp"
            if [ "$node" != untracked ]; then
                printf 'CGAST node: %s\n' "$node"
            fi
        else
            local rc=$?
            rm -f "$tmp"
            return "$rc"
        fi
    else
        local rc=$?
        rm -f "$tmp"
        return "$rc"
    fi
}

capture_dashboard() {
    local attempt
    for attempt in 1 2 3; do
        if cga view --dump "$CGA_DASHBOARD_DUMP" --capture --label "$*"; then
            return 0
        fi
        [ "$attempt" -eq 3 ] || sleep 0.25
    done
    return 1
}

# Invoke a cga* component (bare name, on PATH) as a CGAST filter.
cga_cmd() {
    local rc
    cga_step "$@" || {
        rc=$?
        return "$rc"
    }
    if ! capture_dashboard "$*"; then
        printf 'WARNING: cga command succeeded, but dashboard capture failed: %s\n' \
            "$*" >&2
    fi
    return 0
}

show_next() {
    printf '\nNext: %s\n' "$*"
}

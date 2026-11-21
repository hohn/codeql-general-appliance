#!/usr/bin/env bash
# Shared environment and atomic CGAST update helpers for sample-05.
set -euo pipefail

SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CGA_ROOT="$(cd "${SAMPLE_DIR}/.." && pwd)"
export CGA_ROOT
REPO_ROOT="$(cd "${CGA_ROOT}/.." && pwd)"
export CGA_TMPDIR="${CGA_TMPDIR:-${CGA_ROOT}/cga-tmp}"
export CGA_SESSION="${CGA_SESSION:-${CGA_TMPDIR}/sample-05.json}"
export CGA_RUN_DIR="${CGA_RUN_DIR:-${CGA_ROOT}/.run/sample-05}"

# Dedicated viewer ports avoid accidentally reusing fragment servers that were
# launched against the default cga-tmp/session.json.
export CGA_PAGE_PORT="${CGA_PAGE_PORT:-8700}"
export CGA_CGASV_PORT="${CGA_CGASV_PORT:-8701}"
export CGA_CGADL_PORT="${CGA_CGADL_PORT:-8702}"
export CGA_CGAQL_PORT="${CGA_CGAQL_PORT:-8703}"
export CGA_CGAMR_PORT="${CGA_CGAMR_PORT:-8704}"
export CGA_CGAMU_PORT="${CGA_CGAMU_PORT:-8705}"
export CGA_CGASI_PORT="${CGA_CGASI_PORT:-8706}"
export CGA_CGAMX_PORT="${CGA_CGAMX_PORT:-8707}"
export CGA_CGAEX_PORT="${CGA_CGAEX_PORT:-8708}"

# Keep this sample independent from run-system-05 and the other scenarios.
export RUN_TAG="${RUN_TAG:-cga-sample-05}"
export MRVA_WORK_DIR="${MRVA_WORK_DIR:-/tmp/mrva-cga-sample-05}"
export MRVA_TMP_DIR="${MRVA_TMP_DIR:-/tmp/mrva-${RUN_TAG}}"
export SERVER_LOG="${SERVER_LOG:-${MRVA_TMP_DIR}/server.log}"
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

# Run one cga* CGAST filter and replace the browser's session only on success.
cga_step() {
    ensure_session
    local tmp
    tmp="$(mktemp "${CGA_TMPDIR}/sample-05.next.XXXXXX")"
    if "$@" < "$CGA_SESSION" > "$tmp"; then
        mv "$tmp" "$CGA_SESSION"
    else
        local rc=$?
        rm -f "$tmp"
        return "$rc"
    fi
}

cga_cmd() {
    local component="$1"
    shift
    cga_step "${CGA_ROOT}/${component}/bin/${component}" "$@"
}

system_phase() {
    (cd "${REPO_ROOT}/cga/system-tests" && ./run-system-05 "$@")
}

show_next() {
    printf '\nNext: %s\n' "$*"
}

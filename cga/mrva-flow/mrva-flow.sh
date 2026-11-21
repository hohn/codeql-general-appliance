#!/usr/bin/env bash
set -euo pipefail

SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SAMPLE_DIR"
CGA_ROOT="$(cd "${SAMPLE_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${CGA_ROOT}/.." && pwd)"
export CGA_ROOT REPO_ROOT
export CGA_WORKFLOW_ROOT="$SAMPLE_DIR"
export CGA_TMPDIR="${CGA_TMPDIR:-${SAMPLE_DIR}/.cga/tmp}"
export CGA_SESSION="${CGA_SESSION:-${SAMPLE_DIR}/.cga/current.json}"
export CGA_RUN_DIR="${CGA_RUN_DIR:-${SAMPLE_DIR}/.cga/run}"
export CGA_DASHBOARD_DUMP="${CGA_DASHBOARD_DUMP:-${CGA_TMPDIR}/mrva-flow-dashboard.jsonl}"
export CGA_DASHBOARD_EXPORT="${CGA_DASHBOARD_EXPORT:-${CGA_TMPDIR}/mrva-flow-replay.html}"
export CGA_DFG_EXPORT="${CGA_DFG_EXPORT:-${CGA_TMPDIR}/mrva-flow-data-flow.html}"
export CGA_CFG_EXPORT="${CGA_CFG_EXPORT:-${CGA_TMPDIR}/mrva-flow-control-flow.html}"
export CGA_WORKFLOW_STORE="${CGA_WORKFLOW_STORE:-../../../single-machine-mrva-artifacts}"
export CGA_SOURCE_STEP="${CGA_SOURCE_STEP:-mrva-flow}"

for _bin in "${CGA_ROOT}"/*/bin; do
    case ":${PATH}:" in
        *":${_bin}:"*) ;;
        *) PATH="${_bin}:${PATH}" ;;
    esac
done
case ":${PATH}:" in
    *":${CGA_ROOT}:"*) ;;
    *) PATH="${CGA_ROOT}:${PATH}" ;;
esac
export PATH

export CGA_PAGE_PORT="${CGA_PAGE_PORT:-8720}"
export CGA_CGASV_PORT="${CGA_CGASV_PORT:-8721}"
export CGA_CGADL_PORT="${CGA_CGADL_PORT:-8722}"
export CGA_CGAQL_PORT="${CGA_CGAQL_PORT:-8723}"
export CGA_CGAMR_PORT="${CGA_CGAMR_PORT:-8724}"
export CGA_CGAMU_PORT="${CGA_CGAMU_PORT:-8725}"
export CGA_CGASI_PORT="${CGA_CGASI_PORT:-8726}"
export CGA_CGAMX_PORT="${CGA_CGAMX_PORT:-8727}"
export CGA_CGAEX_PORT="${CGA_CGAEX_PORT:-8728}"
export CGA_CGAUV_PORT="${CGA_CGAUV_PORT:-8729}"

export FLOW_USER="${FLOW_USER:-bob}"
export FLOW_SUBMISSION="${FLOW_SUBMISSION:-bob-1}"
export FLOW_QUERY="${FLOW_QUERY:-Fprintf.ql}"
export RUN_TAG="${RUN_TAG:-cga-mrva-flow}"
export MRVA_WORK_DIR="${MRVA_WORK_DIR:-${SAMPLE_DIR}/.cga/runtime/mrva}"
export MRVA_TMP_DIR="${MRVA_TMP_DIR:-${SAMPLE_DIR}/.cga/runtime/services}"
export MRVA_STANDALONE_STORAGE="${MRVA_STANDALONE_STORAGE:-filesystem}"
export PORT="${PORT:-8081}"
export CGA_MRVA_SERVER="${CGA_MRVA_SERVER:-http://127.0.0.1:${PORT}}"
export CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME:-/usr}"
export CGA_MR_POLL_SECONDS="${CGA_MR_POLL_SECONDS:-5}"
export CGA_MR_TIMEOUT_SECONDS="${CGA_MR_TIMEOUT_SECONDS:-1800}"

_cga_trace_source() {
    export CGA_SOURCE_FILE="${BASH_SOURCE[1]}"
    export CGA_SOURCE_LINE="${BASH_LINENO[0]}"
}
trap _cga_trace_source DEBUG

case "${1:-run}" in
    stop)
        cga mx stop
        cga uv stop
        cga run stop
        exit
        ;;
    cleanup)
        cga mx cleanup
        cga uv stop
        cga run stop
        exit
        ;;
    run) ;;
    *)
        printf 'usage: %s [run|stop|cleanup]\n' "$0" >&2
        exit 2
        ;;
esac

if [ ! -f .cga/config ]; then
    cga init . --store "$CGA_WORKFLOW_STORE"
fi

chain="$(cga chain start --name "mrva-flow-$(date -u +%Y%m%dT%H%M%SZ)-$$")"

rm -f "$CGA_DASHBOARD_DUMP"
cga run start
cga uv start
cga view --dump "$CGA_DASHBOARD_DUMP" --capture --label "cga run start"

cga mx preflight
cga mx reset
cga mx build
cga mx start

cga dl getmeta --tag user:viewable "${CGA_ROOT}/cgadl/db-collection.global/metadata.sql"
cga ql index --tag user:viewable "${REPO_ROOT}/sample-query"
cga dl sql --user "$FLOW_USER" --query-file "${SAMPLE_DIR}/databases.sql"
cga dl download --output-dir "${MRVA_WORK_DIR}/db-serve"
cga ql select --user "$FLOW_USER" relpath "$FLOW_QUERY"
cga ql pack --tag user:show-progress

cga mr run \
    --tag user:show-progress \
    --name "$FLOW_SUBMISSION" \
    --user "$FLOW_USER" \
    --language cpp \
    --output-dir "${CGA_TMPDIR}/mrva-flow-downloads/${FLOW_SUBMISSION}" \
    --log-dir "${CGA_TMPDIR}/mrva-flow-checkpoints/${chain}" \
    --poll-seconds "$CGA_MR_POLL_SECONDS" \
    --timeout-seconds "$CGA_MR_TIMEOUT_SECONDS"

cga si ingest \
    --name "$FLOW_SUBMISSION" \
    --output-dir "${CGA_TMPDIR}/mrva-flow-ingest"
cga ex human --tag user:primary-interest-data --output "${CGA_TMPDIR}/mrva-flow-results.md"
cga ex llm --output "${CGA_TMPDIR}/mrva-flow-results.json"
cga si verify "$FLOW_SUBMISSION"
cga mx check

cga view --dump "$CGA_DASHBOARD_DUMP" --export "$CGA_DASHBOARD_EXPORT"
cga tree show -v --format html -o "$CGA_DFG_EXPORT"
cga tree show --control-flow --format html -o "$CGA_CFG_EXPORT"

printf '\nCGA dashboard: http://127.0.0.1:%s/\n' "$CGA_PAGE_PORT"
printf 'CGA Unified View: http://127.0.0.1:%s/\n' "$CGA_CGAUV_PORT"
printf 'MRVA sysview: %s/sysview\n' "$CGA_MRVA_SERVER"
printf 'Offline replay: %s\n' "$CGA_DASHBOARD_EXPORT"
printf 'DFG tree: %s\n' "$CGA_DFG_EXPORT"
printf 'CFG tree: %s\n' "$CGA_CFG_EXPORT"
printf 'Chain: %s\n' "$chain"
printf 'Stop: %s stop\n' "$0"
printf 'Cleanup: %s cleanup\n' "$0"

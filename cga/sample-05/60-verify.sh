#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamr verify bob-1 eve-1
cga_cmd cgasi verify bob-1 eve-1
cga_cmd cgasi info
system_phase logs
if grep -E "ERROR|panic|fatal" "$SERVER_LOG" 2>/dev/null \
        | grep -v 'mrva-project-resolver' >/dev/null; then
    printf 'FAIL: non-benign errors found in %s\n' "$SERVER_LOG" >&2
    exit 1
fi
printf 'PASS: no non-benign server errors.\n'
printf '\nThe MRVA server and cga page remain running for inspection.\n'
show_next "./90-stop.sh or ./99-cleanup.sh"

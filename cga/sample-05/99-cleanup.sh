#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

system_phase cleanup
"${CGA_ROOT}/cga" run stop
printf 'MRVA runtime removed. CGAST/downloads/ingest DBs remain at %s.\n' \
    "$CGA_TMPDIR"

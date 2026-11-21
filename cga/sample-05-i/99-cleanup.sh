#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamx cleanup
cga run stop
printf 'MRVA runtime removed. CGAST/downloads/ingest DBs remain at %s.\n' \
    "$CGA_TMPDIR"

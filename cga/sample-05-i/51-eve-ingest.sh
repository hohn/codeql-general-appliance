#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgasi ingest --name eve-1 \
    --output-dir "${CGA_TMPDIR}/sample-05-i-ingest"
show_next "./55-export-results.sh"

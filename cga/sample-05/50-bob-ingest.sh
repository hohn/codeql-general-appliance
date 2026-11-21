#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgasi ingest --name bob-1 \
    --output-dir "${CGA_TMPDIR}/sample-05-ingest"
show_next "./51-eve-ingest.sh"

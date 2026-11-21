#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgaex human \
    --output "${CGA_TMPDIR}/sample-05-i-results.md"
cga_cmd cgaex llm \
    --output "${CGA_TMPDIR}/sample-05-i-results.json"
cga_cmd cgaex info
show_next "./60-verify.sh"

#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamr download --name bob-1 \
    --output-dir "${CGA_TMPDIR}/sample-05-downloads/bob-1"
show_next "./41-eve-download.sh"

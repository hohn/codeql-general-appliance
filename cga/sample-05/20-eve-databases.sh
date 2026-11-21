#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

# One C++ database, mirroring eve-1's one-job run.
cga_cmd cgadl sql --user eve --query-file "${SAMPLE_DIR}/eve-dbs.sql"
cga_cmd cgadl download --output-dir "${MRVA_WORK_DIR}/db-serve"
show_next "./21-eve-query.sh"

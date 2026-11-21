#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

# Two C++ databases, mirroring bob-1's two-job run.
cga_cmd cgadl sql --user bob --query-file "${SAMPLE_DIR}/bob-dbs.sql"
cga_cmd cgadl download --output-dir "${MRVA_WORK_DIR}/db-serve"
show_next "./11-bob-query.sh"

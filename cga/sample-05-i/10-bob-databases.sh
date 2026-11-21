#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

# Six C++ databases: two baseline repos plus four chosen because they contain
# real fprintf call sites, so Fprintf.ql yields results for cgasi to ingest.
cga_cmd cgadl sql --user bob --query-file "${SAMPLE_DIR}/bob-dbs.sql"
cga_cmd cgadl download --output-dir "${MRVA_WORK_DIR}/db-serve"
show_next "./11-bob-query.sh"

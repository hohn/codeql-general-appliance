#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgadl getmeta "${CGA_ROOT}/cgadl/db-collection.global/metadata.sql"
cga_cmd cgaql index "${REPO_ROOT}/sample-query"
cga_cmd cgadl info
cga_cmd cgaql info
show_next "./10-bob-databases.sh"

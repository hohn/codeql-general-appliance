#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgaql select --user eve relpath DeadCodeCondition.ql
cga_cmd cgaql pack
show_next "./22-eve-submit.sh"

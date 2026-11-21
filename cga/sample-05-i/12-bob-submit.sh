#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamr submit --name bob-1 --user bob --language cpp
show_next "./13-bob-status.sh"

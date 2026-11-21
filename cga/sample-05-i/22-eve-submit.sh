#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamr submit --name eve-1 --user eve --language cpp
show_next "./23-eve-status.sh"

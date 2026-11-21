#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamr status --name eve-1
printf '\nRepeat ./30-bob-status.sh and ./31-eve-status.sh until terminal.\n'

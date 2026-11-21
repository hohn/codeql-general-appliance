#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

# Deliberately one observation, not an automatic polling loop.
cga_cmd cgamr status --name bob-1
printf '\nIf bob-1 is still in progress, run this script again later.\n'

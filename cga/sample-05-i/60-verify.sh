#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamr verify bob-1 eve-1
cga_cmd cgasi verify bob-1 eve-1
cga_cmd cgasi info
cga_cmd cgamx logs
cga_cmd cgamx check
printf '\nThe MRVA server and cga page remain running for inspection.\n'
show_next "./70-export-dashboard.sh"

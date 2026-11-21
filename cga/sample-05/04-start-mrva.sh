#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

system_phase start
printf '\nMRVA sysview: %s/sysview\n' "$CGA_MRVA_SERVER"
show_next "./05-index-libraries.sh"

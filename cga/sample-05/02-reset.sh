#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

system_phase reset
printf '{}\n' > "$CGA_SESSION"
show_next "./03-build.sh"

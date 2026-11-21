#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

"${CGA_ROOT}/cga" run start
printf '\nOpen http://127.0.0.1:%s/ and leave it visible.\n' "$CGA_PAGE_PORT"
show_next "./01-preflight.sh"

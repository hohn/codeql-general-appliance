#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

# Start all cga* fragment servers + the composite page.
rm -f "$CGA_DASHBOARD_DUMP"
cga run start
capture_dashboard "cga run start"
printf '\nOpen http://127.0.0.1:%s/ and leave it visible.\n' "$CGA_PAGE_PORT"
printf 'Dashboard capture: %s\n' "$CGA_DASHBOARD_DUMP"
show_next "./01-preflight.sh"

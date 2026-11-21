#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga view --dump "$CGA_DASHBOARD_DUMP" --export "$CGA_DASHBOARD_EXPORT"
printf '\nOffline dashboard replay: %s\n' "$CGA_DASHBOARD_EXPORT"
printf 'Open with: chromium-browser %q\n' "$CGA_DASHBOARD_EXPORT"
show_next "./90-stop.sh or ./99-cleanup.sh"

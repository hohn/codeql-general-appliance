#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamx stop
cga run stop
printf 'Stopped services; retained Postgres, CGAST, databases, and downloads.\n'

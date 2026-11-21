#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

# cgamx owns the standalone MRVA infrastructure; preflight checks tools, ensures
# Postgres, and frees the server/MinIO/DB-server ports.
cga_cmd cgamx preflight
show_next "./02-reset.sh"

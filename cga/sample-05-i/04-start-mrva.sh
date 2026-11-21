#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

# Start MinIO + the CodeQL DB HTTP server + mrvaserver (pids recorded in CGAST).
cga_cmd cgamx start
printf '\nMRVA sysview: %s/sysview\n' "$CGA_MRVA_SERVER"
show_next "./05-index-libraries.sh"

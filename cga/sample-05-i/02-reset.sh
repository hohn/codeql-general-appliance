#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

# Fresh snapshot chain for the run, then drop MRVA tables + wipe the work dir.
cga_start_chain
cga_cmd cgamx reset
show_next "./03-build.sh"

#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgaql select --user bob relpath Fprintf.ql
cga_cmd cgaql pack
show_next "./12-bob-submit.sh"

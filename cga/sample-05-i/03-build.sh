#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

cga_cmd cgamx build
show_next "./04-start-mrva.sh"

#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"

system_phase build
show_next "./04-start-mrva.sh"

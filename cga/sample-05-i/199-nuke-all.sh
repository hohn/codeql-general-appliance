#!/usr/bin/env bash
# 199-nuke-all.sh -- TESTING ONLY, for a DEDICATED machine.
#
# Force every trace of this sample's runtime to be gone -- including ORPHANED
# cga* servers. The graceful `cga run stop` only kills the processes it has
# pidfiles for, so a viewer started by an earlier run can survive and keep
# serving stale HTML/Python (a common "why isn't my change showing up?" trap,
# since each `cgasi serve` loads serve.py once at startup). This script does the
# normal graceful shutdown first, then pgrep/pkill anything cga* still alive.
#
# NOT for shared machines: it kills by name/path pattern (mrvaserver, mrvaagent,
# minio, every <cga>/*/bin/* server, and the composite page). On a dedicated box
# that is exactly what we want between test runs.
set -uo pipefail
# shellcheck source=_common.sh
. "$(dirname "$0")/_common.sh"
set +e  # best-effort: keep going even when a shutdown step fails.

log() { printf '%s\n' "$*"; }

# 1. Graceful shutdowns (best effort) --------------------------------------
log '=== graceful shutdown ==='
cga_cmd cgamx cleanup   # stop MRVA services, drop tables, wipe work dir
cga run stop            # kill pidfiled cga* fragment servers + the page

# 2. Force-kill any survivors ----------------------------------------------
# Patterns are anchored to THIS checkout / this sample's work dir so we never
# touch unrelated processes (CGA_ROOT and MRVA_WORK_DIR are absolute paths).
log '=== force-killing survivors ==='
patterns=(
    "${CGA_ROOT}/[a-z]*/bin/cga"       # cga* fragment + cmd servers (py & go)
    "http\.server.*${CGA_ROOT}/web"    # composite page static server
    "${CGA_ROOT}/cga-run"              # the launcher itself
    "mrvaserver"                       # MRVA server binary
    "mrvaagent"                        # spawned MRVA agent binaries
    "${MRVA_WORK_DIR}"                 # minio + db-serve rooted in the work dir
)

kill_pattern() {  # signal pattern
    local sig="$1" pat="$2" pids
    pids="$(pgrep -f "$pat" 2>/dev/null)"
    [ -n "$pids" ] || return 0
    log "  ${sig} [$pat]: $(printf '%s' "$pids" | tr '\n' ' ')"
    pkill "-${sig}" -f "$pat" 2>/dev/null
}

for pat in "${patterns[@]}"; do kill_pattern TERM "$pat"; done
sleep 1
# Escalate to KILL for anything that ignored TERM.
for pat in "${patterns[@]}"; do kill_pattern KILL "$pat"; done

# 3. Report ----------------------------------------------------------------
log '=== survivors after nuke (should be empty) ==='
left=0
for pat in "${patterns[@]}"; do
    if pgrep -af "$pat" 2>/dev/null; then left=1; fi
done
[ "$left" = 0 ] && log '  (none)'

log ''
log 'Nuked. Start fresh with: ./00-start-cga.sh'

#!/usr/bin/env bash
# real01.sh -- concrete, sequential (NO-pipe) walk of planning.org case real01.
#
# case real01 is the tree of three cga* chains that fork at shared CGAST states
# st01 (the root) and st12 (the refined-DB state):
#
#   A: st01 -cgadl0-> st02 -cgaql0-> st03 -cgamr0-> st04   (baseline)
#   B: st01 -cgadl1-> st12 -cgaql0-> st13 -cgamr0-> st14   (refine DB choice)
#   C: st01 -cgadl1-> st12 -cgaql1-> st23 -cgamr0-> st24   (refine query choice)
#
# Single user: bob. Every arrow is ONE cga* CGAST filter applied with explicit
# input/output file redirection -- no pipes anywhere. Each dot-graph node is one
# state file under $STATE named exactly as in the diagram (st01, st02, ... st24).
# Branching is real: st01 and st12 are each produced once and forked.
#
# Numeral semantics: the number on a dot-graph node is its ARGUMENT-TUPLE id, not
# an invocation id. Same number == identical cga* CLI arguments, possibly run
# more than once with a different CGAST on stdin (planning.org: "the numbered
# arguments to cga* denote distinct parameters"). Thus:
#   cgadl 0 -> real01-dbs-0.sql (broad 6-repo set)   cgadl 1 -> real01-dbs-1.sql (3-repo subset)
#   cgaql 0 -> Fprintf.ql                            cgaql 1 -> DeadCodeCondition.ql
#   cgamr 0 -> ONE arg set (--name real01 --user bob --language cpp), run on all
#              three terminal edges with the differing st03/st13/st23 as stdin.
#
# Prerequisite: sample-05-i infra must be up (its 00-start-cga .. 04-start-mrva),
# because `cgamr submit` talks to the live MRVA server and needs the downloaded
# DBs. sample-05-i itself is NOT modified; we only source its environment.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse sample-05-i environment + PATH (cga* bins, ports, MRVA_WORK_DIR, ...).
# shellcheck source=../sample-05-i/_common.sh
. "${HERE}/../sample-05-i/_common.sh"

STATE="${CGA_TMPDIR}/real01"
DBDIR="${MRVA_WORK_DIR}/db-serve"
rm -rf "$STATE"
mkdir -p "$STATE"

# --- no-pipe compound dot-graph nodes -----------------------------------------
# Each cga* node in the diagram is really a short filter sequence. We thread the
# sub-steps through anonymous temp files so no pipe is ever used, and the named
# node states (stNN) only ever hold the node's final output.

# cgadl node: DB select (sql) then download.  IN -> OUT.
node_cgadl() { # OUT IN SQLFILE
    local out="$1" in="$2" sql="$3" w
    w="$(mktemp "${STATE}/.dl.XXXXXX")"
    cgadl sql --user bob --query-file "$sql" <"${STATE}/${in}" >"$w"
    cgadl download --output-dir "$DBDIR" <"$w" >"${STATE}/${out}"
    rm -f "$w"
    printf '  %-4s <- %-4s : cgadl (%s)\n' "$out" "$in" "$(basename "$sql")"
}

# cgaql node: query select then pack.  IN -> OUT.
node_cgaql() { # OUT IN QLFILE
    local out="$1" in="$2" ql="$3" w
    w="$(mktemp "${STATE}/.ql.XXXXXX")"
    cgaql select --user bob relpath "$ql" <"${STATE}/${in}" >"$w"
    cgaql pack <"$w" >"${STATE}/${out}"
    rm -f "$w"
    printf '  %-4s <- %-4s : cgaql (%s)\n' "$out" "$in" "$ql"
}

# cgamr node: submit.  IN -> OUT. NAME is part of the argument tuple, so the same
# cgamr numeral must pass the same NAME (only stdin differs across edges).
node_cgamr() { # OUT IN NAME
    local out="$1" in="$2" name="$3"
    cgamr submit --name "$name" --user bob --language cpp \
        <"${STATE}/${in}" >"${STATE}/${out}"
    printf '  %-4s <- %-4s : cgamr submit (%s)\n' "$out" "$in" "$name"
}

# The single "cgamr 0" argument tuple, reused verbatim on every terminal edge.
# MRVA assigns the session id internally per submit, so the three submissions of
# this identical tuple yield three distinct sessions captured in st04/st14/st24.
CGAMR0_NAME="real01"

# in-place filter (used only to build the shared root st01).  STATE cmd...
apply_inplace() { # ST cmd...
    local st="$1" tmp
    shift
    tmp="$(mktemp "${STATE}/.${st}.XXXXXX")"
    "$@" <"${STATE}/${st}" >"$tmp"
    mv "$tmp" "${STATE}/${st}"
}

# --- bootstrap the shared root st01 -------------------------------------------
# st01 carries the DB catalog (getmeta) and the query index (cgaql index) so the
# cgadl/cgaql selects downstream have something to resolve against.
printf '{}\n' >"${STATE}/st01"
apply_inplace st01 cgadl getmeta "${CGA_ROOT}/cgadl/db-collection.global/metadata.sql"
apply_inplace st01 cgaql index "${REPO_ROOT}/sample-query"
echo "root  : st01 (getmeta + cgaql index)"

echo "chain A (baseline):"
node_cgadl st02 st01 "${HERE}/real01-dbs-0.sql"
node_cgaql st03 st02 Fprintf.ql
node_cgamr st04 st03 "$CGAMR0_NAME"

echo "chain B (refine DB choice; fork from st01):"
node_cgadl st12 st01 "${HERE}/real01-dbs-1.sql"
node_cgaql st13 st12 Fprintf.ql
node_cgamr st14 st13 "$CGAMR0_NAME"

echo "chain C (refine query choice; fork from st12 -- no re-download):"
node_cgaql st23 st12 DeadCodeCondition.ql
node_cgamr st24 st23 "$CGAMR0_NAME"

echo
echo "done. node state files under ${STATE}:"
for f in "${STATE}"/st*; do
    printf '  %s\n' "$(basename "$f")"
done

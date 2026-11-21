#!/usr/bin/env bash
# A normalized shell equivalent of my-bench's active query-study chain cga_1.
# Reconstructed from its command history and frozen accepted query packs.
# This is an illustration, not a literal replay of every click or failed edit.
# It uses cga's component commands, without cga bench or its session model.
# Session setup is deliberately repeated, without helper functions or loops:
# this is the linear bookkeeping hidden behind the UI's Add session and grid.
#
# All six sessions use the same AFLplusplus/AFLplusplus C++ database:
#   commit: 474ff18ba2a7999a518a4d194fcd5a1f87c3625d
#   content hash: a5ff9f6b9c69310d398f38b5322ecaf914182e5cd50b9fb32731e75b32ced64c
#
# Session  Accepted query                         Observed findings
#   1      fprintf                               172
#   2      fprintf, same as S1                   172
#   3      printf                               1478
#   4      printf, same as S3                    1478
#   5      fprintf, back to the baseline         172
#   6      fprintf, more than two arguments      116
#
# S2's MyQuery placeholder was edited but never accepted: the actual run used
# the library query again. Here we omit that detour and emit its accepted text.
# S6 was edited outside the recorded edit-query command; its frozen pack, not
# the absence of that command in the log, determines the query shown here.
#
# Read this file first. To execute, choose a NEW workflow directory:
#   SIX_SESSION_REPLAY_DIR=/path/to/new-workflow bash this-file.sh
# Stop the other standalone MRVA deployment first: MRVA setup shares
# the normal MRVA/Postgres/archive-server ports and can reclaim/reset them.
# This script must not be run in, or pointed at, the live my-bench workflow.
set -euo pipefail

: "${SIX_SESSION_REPLAY_DIR:?Set a NEW workflow directory; this script starts MRVA and runs six analyses}"
if [[ -e "$SIX_SESSION_REPLAY_DIR" ]]; then
  printf 'Refusing to reuse an existing path: %s\n' "$SIX_SESSION_REPLAY_DIR" >&2
  exit 1
fi
if [[ -n "${CGA_DIR-}" || -n "${CGA_WORKFLOW_ACTIVE-}" ]]; then
  printf 'Run from a clean shell, without an active CGA dispatcher context.\n' >&2
  exit 1
fi

CGA_HOME=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
export PATH="$CGA_HOME:$PATH"
export CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME-/usr}"
MRVA_USER=$(id -un)
CATALOGUE="$CGA_HOME/cgadl/db-collection.global/metadata.sql"
SERVER="${CGA_MRVA_SERVER-http://127.0.0.1:${PORT-8081}}"

cga init "$SIX_SESSION_REPLAY_DIR"
cd -- "$SIX_SESSION_REPLAY_DIR"
export CGA_WORKFLOW_ROOT="$PWD"
export CGA_ROOT="$CGA_HOME"
export CGA_TMPDIR="$PWD/.cga/tmp"
export MRVA_WORK_DIR="$PWD/.cga/runtime/mrva"
export MRVA_TMP_DIR="$PWD/.cga/runtime/services"
export MRVA_STANDALONE_STORAGE="${MRVA_STANDALONE_STORAGE-filesystem}"
cga chain start --name fixed-database
cga mx preflight
cga mx reset
cga mx build
cga mx start
cga mx check

# Establish D once. Stable criteria replace browser generation/row-number pairs.
cga dl getmeta "$CATALOGUE"
cga dl select \
  git_owner AFLplusplus git_repo AFLplusplus primary_language cpp \
  content_hash a5ff9f6b9c69310d398f38b5322ecaf914182e5cd50b9fb32731e75b32ced64c
cga dl download \
  --output-dir "$PWD/.cga/runtime/mrva/db-serve"
cga state export --output "$PWD/fixed-database.state"
mkdir -- "$PWD/queries" "$PWD/results"

# Each import starts a separate chain with D but no Q, submission, or ingestion.
# These chains stand in for Bench's six session-local workspaces.
# The dependency pin is from S1's accepted pack, not today's mutable library.
# Each mr run provides bounded submit/status polling/download/verification and
# operation checkpoints. On an uncertain/failed submission, stop and inspect
# its saved checkpoint; do not blindly submit again or restart this script.

# Session 1: establish the fprintf reference (observed: 172 findings).
cga state import "$PWD/fixed-database.state" --name session-1
mkdir -- "$PWD/queries/session-1"
cat > "$PWD/queries/session-1/qlpack.yml" <<'YAML'
name: cga/cgaql-pack
version: 0.0.1
library: false
warnOnImplicitThis: false
dependencies:
  codeql/cpp-all: 12.1.1
YAML
cat > "$PWD/queries/session-1/Fprintf.ql" <<'QL'
/**
 * @name findPrintf
 * @description Find calls to plain fprintf
 * @kind problem
 * @id cpp-fprintf-call
 * @problem.severity warning
 */

import cpp

from FunctionCall fc
where
  fc.getTarget().getName() = "fprintf"
select fc, "call of fprintf"
QL
cga ql index "$PWD/queries/session-1"
cga ql select filename Fprintf.ql
cga ql pack
mkdir -- "$PWD/results/session-1"
cga state export --output "$PWD/results/session-1/accepted-inputs.state"
cga mr run --name session-1 --user "$MRVA_USER" --server "$SERVER" \
  --output-dir "$PWD/results/session-1/downloads" \
  --log-dir "$PWD/results/session-1/job-log" \
  --poll-seconds 2 --timeout-seconds 1800
cga si ingest --name session-1 --output-dir "$PWD/results/session-1/ingested"
cga si verify session-1
cga state export --output "$PWD/results/session-1/completed.state"

# Session 2: repeat fprintf with fresh query/job/result state (observed: 172).
cga state import "$PWD/fixed-database.state" --name session-2
mkdir -- "$PWD/queries/session-2"
cat > "$PWD/queries/session-2/qlpack.yml" <<'YAML'
name: cga/cgaql-pack
version: 0.0.1
library: false
warnOnImplicitThis: false
dependencies:
  codeql/cpp-all: 12.1.1
YAML
cat > "$PWD/queries/session-2/Fprintf.ql" <<'QL'
/**
 * @name findPrintf
 * @description Find calls to plain fprintf
 * @kind problem
 * @id cpp-fprintf-call
 * @problem.severity warning
 */

import cpp

from FunctionCall fc
where
  fc.getTarget().getName() = "fprintf"
select fc, "call of fprintf"
QL
cga ql index "$PWD/queries/session-2"
cga ql select filename Fprintf.ql
cga ql pack
mkdir -- "$PWD/results/session-2"
cga state export --output "$PWD/results/session-2/accepted-inputs.state"
cga mr run --name session-2 --user "$MRVA_USER" --server "$SERVER" \
  --output-dir "$PWD/results/session-2/downloads" \
  --log-dir "$PWD/results/session-2/job-log" \
  --poll-seconds 2 --timeout-seconds 1800
cga si ingest --name session-2 --output-dir "$PWD/results/session-2/ingested"
cga si verify session-2
cga state export --output "$PWD/results/session-2/completed.state"

# Session 3: change the target and rule ID to printf (observed: 1478).
cga state import "$PWD/fixed-database.state" --name session-3
mkdir -- "$PWD/queries/session-3"
cat > "$PWD/queries/session-3/qlpack.yml" <<'YAML'
name: cga/cgaql-pack
version: 0.0.1
library: false
warnOnImplicitThis: false
dependencies:
  codeql/cpp-all: 12.1.1
YAML
cat > "$PWD/queries/session-3/Fprintf.ql" <<'QL'
/**
 * @name findPrintf
 * @description Find calls to plain fprintf
 * @kind problem
 * @id cpp-printf-call
 * @problem.severity warning
 */

import cpp

from FunctionCall fc
where
  fc.getTarget().getName() = "printf"
select fc, "call of printf"
QL
cga ql index "$PWD/queries/session-3"
cga ql select filename Fprintf.ql
cga ql pack
mkdir -- "$PWD/results/session-3"
cga state export --output "$PWD/results/session-3/accepted-inputs.state"
cga mr run --name session-3 --user "$MRVA_USER" --server "$SERVER" \
  --output-dir "$PWD/results/session-3/downloads" \
  --log-dir "$PWD/results/session-3/job-log" \
  --poll-seconds 2 --timeout-seconds 1800
cga si ingest --name session-3 --output-dir "$PWD/results/session-3/ingested"
cga si verify session-3
cga state export --output "$PWD/results/session-3/completed.state"

# Session 4: independently repeat the printf variant (observed: 1478).
cga state import "$PWD/fixed-database.state" --name session-4
mkdir -- "$PWD/queries/session-4"
cat > "$PWD/queries/session-4/qlpack.yml" <<'YAML'
name: cga/cgaql-pack
version: 0.0.1
library: false
warnOnImplicitThis: false
dependencies:
  codeql/cpp-all: 12.1.1
YAML
cat > "$PWD/queries/session-4/Fprintf.ql" <<'QL'
/**
 * @name findPrintf
 * @description Find calls to plain fprintf
 * @kind problem
 * @id cpp-printf-call
 * @problem.severity warning
 */

import cpp

from FunctionCall fc
where
  fc.getTarget().getName() = "printf"
select fc, "call of printf"
QL
cga ql index "$PWD/queries/session-4"
cga ql select filename Fprintf.ql
cga ql pack
mkdir -- "$PWD/results/session-4"
cga state export --output "$PWD/results/session-4/accepted-inputs.state"
cga mr run --name session-4 --user "$MRVA_USER" --server "$SERVER" \
  --output-dir "$PWD/results/session-4/downloads" \
  --log-dir "$PWD/results/session-4/job-log" \
  --poll-seconds 2 --timeout-seconds 1800
cga si ingest --name session-4 --output-dir "$PWD/results/session-4/ingested"
cga si verify session-4
cga state export --output "$PWD/results/session-4/completed.state"

# Session 5: return to the baseline fprintf query (observed: 172).
cga state import "$PWD/fixed-database.state" --name session-5
mkdir -- "$PWD/queries/session-5"
cat > "$PWD/queries/session-5/qlpack.yml" <<'YAML'
name: cga/cgaql-pack
version: 0.0.1
library: false
warnOnImplicitThis: false
dependencies:
  codeql/cpp-all: 12.1.1
YAML
cat > "$PWD/queries/session-5/Fprintf.ql" <<'QL'
/**
 * @name findPrintf
 * @description Find calls to plain fprintf
 * @kind problem
 * @id cpp-fprintf-call
 * @problem.severity warning
 */

import cpp

from FunctionCall fc
where
  fc.getTarget().getName() = "fprintf"
select fc, "call of fprintf"
QL
cga ql index "$PWD/queries/session-5"
cga ql select filename Fprintf.ql
cga ql pack
mkdir -- "$PWD/results/session-5"
cga state export --output "$PWD/results/session-5/accepted-inputs.state"
cga mr run --name session-5 --user "$MRVA_USER" --server "$SERVER" \
  --output-dir "$PWD/results/session-5/downloads" \
  --log-dir "$PWD/results/session-5/job-log" \
  --poll-seconds 2 --timeout-seconds 1800
cga si ingest --name session-5 --output-dir "$PWD/results/session-5/ingested"
cga si verify session-5
cga state export --output "$PWD/results/session-5/completed.state"

# Session 6: restrict fprintf to more than two arguments (observed: 116).
cga state import "$PWD/fixed-database.state" --name session-6
mkdir -- "$PWD/queries/session-6"
cat > "$PWD/queries/session-6/qlpack.yml" <<'YAML'
name: cga/cgaql-pack
version: 0.0.1
library: false
warnOnImplicitThis: false
dependencies:
  codeql/cpp-all: 12.1.1
YAML
cat > "$PWD/queries/session-6/Fprintf.ql" <<'QL'
/**
 * @name findPrintf
 * @description Find calls to plain fprintf
 * @kind problem
 * @id cpp-fprintf-call
 * @problem.severity warning
 */

import cpp

from FunctionCall fc
where
  fc.getTarget().getName() = "fprintf"
  and fc.getNumberOfArguments() > 2
select fc, "call of fprintf"
QL
cga ql index "$PWD/queries/session-6"
cga ql select filename Fprintf.ql
cga ql pack
mkdir -- "$PWD/results/session-6"
cga state export --output "$PWD/results/session-6/accepted-inputs.state"
cga mr run --name session-6 --user "$MRVA_USER" --server "$SERVER" \
  --output-dir "$PWD/results/session-6/downloads" \
  --log-dir "$PWD/results/session-6/job-log" \
  --poll-seconds 2 --timeout-seconds 1800
cga si ingest --name session-6 --output-dir "$PWD/results/session-6/ingested"
cga si verify session-6
cga state export --output "$PWD/results/session-6/completed.state"

# Manual inspection/count comparison. si sql writes its human table to stderr.
cat > "$PWD/finding-count.sql" <<'SQL'
SELECT count(*) AS finding_count FROM sarif_results;
SQL
cga chain switch session-1
printf '\nSession 1\n'
cga si sql --query-file "$PWD/finding-count.sql"
cga chain switch session-2
printf '\nSession 2\n'
cga si sql --query-file "$PWD/finding-count.sql"
cga chain switch session-3
printf '\nSession 3\n'
cga si sql --query-file "$PWD/finding-count.sql"
cga chain switch session-4
printf '\nSession 4\n'
cga si sql --query-file "$PWD/finding-count.sql"
cga chain switch session-5
printf '\nSession 5\n'
cga si sql --query-file "$PWD/finding-count.sql"
cga chain switch session-6
printf '\nSession 6\n'
cga si sql --query-file "$PWD/finding-count.sql"
cga chain switch session-6

# Not reproduced here: Bench's accepted-input digest checks, immutable R
# snapshots, fixed-D enforcement, or full S1-relative added/removed/unchanged
# finding comparisons. A count-only comparison is not a finding-level diff.
# Bench also saves us hand-carrying state/paths, managing isolated source drafts,
# remembering which edits were accepted, and wiring tables/SQL/editor popups.
# Observed counts above are a reference, not assertions for different toolsets.
# Services remain available for inspection; explicit teardown, when wanted:
#   cga mx stop
# CGA shell workflow: introductory outline

[Introductory guide](../../INTRODUCTORY-GUIDE.md) | [Bench](bench.md) |
[Advanced reading guide](../../READING-GUIDE.md)

This document will explain one sequence: prepare inputs, apply a query to
selected databases, then inspect results. The sections below contain the core
shell commands; worked inputs and explanations remain to be filled in.

For a small first analysis using five prepared databases and `Fprintf.ql`, run
`cga help sample 05`. Display one step with `cga h s 05 00`; append `r` to
execute it. Step 00 explicitly creates the sample directory and saves settings
for later shells or notebook cells. The
[sample recipe](../../cga/samples/05/README.md) is linked under **Start here** in
the [offline help browser](../../docs/cga-help.html). The longer
`cga help getting-started` guide (also `cga -hs`) remains available. The
templates below cover the broader preparation-to-analysis workflow.

## Before starting

Use a fresh workspace. Preparation and analysis each retain their own state.
Replace `/absolute/path/to/...` values with your chosen inputs. These blocks are
templates, not a run-all script.

```sh
export EXPERIMENT_ROOT="$HOME/cga-experiments/first-analysis"
mkdir -p "$EXPERIMENT_ROOT"
mkdir "$EXPERIMENT_ROOT/preparation" "$EXPERIMENT_ROOT/analysis"
export CODEQL_JAVA_HOME=/usr
```

This assumes the [host dependencies](../../INSTALL.md) and `cga` are installed.
The analysis bring-up below owns the local MRVA ports and resets its MRVA
database state. Do not run it alongside Bench or another MRVA example.

## CGA preparation: prepare inputs

Preparation produces database archives, a database catalogue, and a query tree.
Start a recorded preparation workflow:

```sh
cd "$EXPERIMENT_ROOT/preparation"
cga init .
cga chain start --name preparation

SPEC=/absolute/path/to/spec.json
cga codeql check
cga cve import "$SPEC"
cga cve select
cga cve expand
cga src-prep plan
cga src-prep fetch --output-dir "$PWD/sources"
cga query-gen materialize --output-dir "$PWD/queries"
cga query-gen index
cga db plan --mode trace --output-dir "$PWD/jobs"
```

Choose a generated job file and build it. Repeat the build for each desired
database; source-specific build dependencies must already be available:

```sh
JOB=/absolute/path/to/generated-job.json
cga db build --job "$JOB" --trace --output-dir "$PWD/databases"

QUERY=/absolute/path/to/validation-query.ql
cga db validate query --query "$QUERY" --output-dir "$PWD/validation"
cga catalog create --output "$PWD/metadata.sql" --manifest "$PWD/manifest.json"
```

To view preparation history, start Unified View:

```sh
export CGA_UV_RUN_DIR="$PWD/.cga/runtime/unified-view"
export CGA_CGAUV_PORT=8609
cga uv start
cga uv status
```

Open <http://127.0.0.1:8609/>. This viewer does not build databases.

To expand: selecting a specification, source/build requirements, choosing a
build job, and identifying the three outputs. Use the
[preparation reference](../../cga/README-prep.md) or the explicit
[query-030 example](../../cga/analysis/CVE-2016-9843/query-030/README.md) for
case-specific details.

## Apply queries

Create a separate analysis workflow. Import the prepared catalogue and queries;
do not reinitialize the preparation workflow.

```sh
cd "$EXPERIMENT_ROOT/analysis"
cga init .
cga chain start --name analysis

export MRVA_WORK_DIR="$PWD/.cga/runtime/mrva"
export MRVA_TMP_DIR="$PWD/.cga/runtime/services"
export MRVA_DB_SERVE_DIR="$MRVA_WORK_DIR/db-serve"
cga mx preflight
cga mx reset
cga mx build
cga mx start

cga dl getmeta "$EXPERIMENT_ROOT/preparation/metadata.sql"
SELECTION_SQL=/absolute/path/to/database-selection.sql
cga dl sql --user "$USER" --query-file "$SELECTION_SQL"
cga dl download --output-dir "$MRVA_DB_SERVE_DIR"

cga ql index "$EXPERIMENT_ROOT/preparation/queries"
QUERY_RELPATH=path/within/query-tree.ql
cga ql select --user "$USER" relpath "$QUERY_RELPATH"
cga ql pack

cga mr run --name first-run --user "$USER" --language cpp \
  --output-dir "$PWD/downloads/first-run" \
  --log-dir "$PWD/checkpoints/first-run" \
  --poll-seconds 5 --timeout-seconds 1800
```

Choose a matching language instead of `cpp` when needed. `mr run` submits, waits
with a timeout, downloads, and verifies the archives. Use fresh submission names
and checkpoint directories for new runs; inspect existing status/checkpoints
after interruption rather than blindly resubmitting.

To expand: the selection SQL, query choice, progress, and resuming interrupted
work. The [single-user example](../../cga/mrva-flow/README.md) supplies a
complete concrete analysis with prepared inputs.

## Result inspection

Ingest the downloaded results and create reports:

```sh
cga si ingest --name first-run --output-dir "$PWD/findings"
cga si verify first-run
cga si info
cga si list 10
cga ex human --output "$PWD/results.md"
cga ex llm --output "$PWD/results.json"
```

The Markdown report is for human reading; JSON retains structured information
for LLMs and other tools. A successful analysis can have zero findings, and
findings alone do not establish that a query detects a particular vulnerability.

To expand: one finding, zero-finding inputs, query/database provenance, and how
to inspect the full evidence.

## Viewers: reconnect and stop

From the analysis directory, configure the viewers to use this workflow:

```sh
export EXPERIMENT_ROOT="$HOME/cga-experiments/first-analysis"
cd "$EXPERIMENT_ROOT/analysis"
export CGA_WORKFLOW_ROOT="$PWD"
export CGA_SESSION="$PWD/.cga/current.json"
export CGA_RUN_DIR="$PWD/.cga/runtime/viewers"
export CGA_UV_RUN_DIR="$CGA_RUN_DIR/unified-view"
export CGA_CGAUV_PORT=8619
cga run start
cga uv start
cga run status
cga uv status
```

Open the analysis dashboard at <http://127.0.0.1:8600/> and Unified View at
<http://127.0.0.1:8619/>. MRVA's live system view is at
<http://127.0.0.1:8081/sysview> while MRVA is running.

To reconnect, reopen the same browser URL. In a new terminal, repeat the
directory/exports block above before using `status`, `start`, or `stop`. Use
`start` only if the viewer is stopped; it does not rerun the analysis. There is
no separate `reconnect` subcommand.

Stop or restart just the analysis viewers, retaining results and MRVA:

```sh
cga uv stop
cga run stop
# When wanted again:
cga run start
cga uv start
```

To stop the preparation viewer from another terminal:

```sh
export EXPERIMENT_ROOT="$HOME/cga-experiments/first-analysis"
cd "$EXPERIMENT_ROOT/preparation"
export CGA_UV_RUN_DIR="$PWD/.cga/runtime/unified-view"
export CGA_CGAUV_PORT=8609
cga uv stop
```

Stop MRVA separately from the original analysis terminal, retaining results:

```sh
cd "$EXPERIMENT_ROOT/analysis"
cga mx check
cga mx stop
```

Viewer shutdown and MRVA shutdown are different operations. For remote browser
access, see [port forwarding](../../REMOTE-CONNECTION.md).

To expand: a picture of the viewers and the distinction between analysis state,
running services, and browser connections.

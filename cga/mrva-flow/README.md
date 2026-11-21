# cga mrva-flow — single-user standalone MRVA walkthrough

This is the canonical single-script CGA/MRVA flow. It is the single-user
successor to the manually stepped two-user
[`sample-05-i`](../sample-05-i/README.md), which remains available for
experimentation and possible expansion. Both are prototype examples.

The flow uses Bob's `Fprintf.ql` scenario because its six small C++ databases
produce real findings while remaining quick enough for local development. Each
meaningful state transition is one visible `cga` command and therefore one node
in the `.cga` data-flow and control-flow views.

Defaults:

- user `bob`, submission `bob-1`, query `Fprintf.ql`;
- workflow metadata `.cga/`;
- workflow-local temporary files, service logs, PID files, and MRVA runtime
  under `.cga/`;
- content-addressed objects under the configured sibling
  `single-machine-mrva-artifacts/` root;
- viewer ports 8720–8728; and
- CGA Unified View port 8729; and
- MRVA server port 8081.

`FLOW_USER`, `FLOW_SUBMISSION`, and `FLOW_QUERY` override the user-facing
identity. The infrastructure settings remain independently overridable through
the environment variables honored by `cgamx`.

## Run it

Run the complete flow:

```sh
cd cga/mrva-flow
./mrva-flow.sh
```

The script initializes `.cga/` on its first invocation and configures the
sibling artifact repository as the object-store root. Override the initial root
with `CGA_WORKFLOW_STORE`. Later runs retain `.cga/config`; use `cga store set`
to change it deliberately.

`cga mr run` performs bounded polling internally and records submit, status,
download, and verification as one graph node. It preserves detailed operation
checkpoints under `.cga/tmp/mrva-flow-checkpoints/<chain>/`. Override
`CGA_MR_POLL_SECONDS` or `CGA_MR_TIMEOUT_SECONDS` when needed.

The successful run leaves MRVA and the CGA page running for inspection. Stop
services while retaining state with `./mrva-flow.sh stop`, or remove MRVA
runtime state with `./mrva-flow.sh cleanup`.

The run also starts **CGA Unified View** at <http://127.0.0.1:8729/>. It shows
the active chain as grouped command steps with state/source detail, captured
command transcripts, and a compact live MRVA system summary. The existing CGA
Workflow State page on 8720 and MRVA System View on 8081 remain available.

## Inspect the flow

Inspect the `.cga/` workflow directly:

```sh
cga status
cga chain list
cga chain show -v
cga tree show -v
cga tree show --control-flow
cga tree show --format dot > data-flow.dot
cga tree show --format pdf -o data-flow.pdf
cga tree show --format html -o data-flow.html
cga artifact list
cga doctor
```

The verbose tree is the `.cga` data-flow view: it shows immutable whole-CGAST
states, changed keys, and the command that produced each successor state.
`--control-flow` shows command execution order without data deltas. `.cga/`
holds only workflow metadata and relative content-addressed keys; the configured
object-store root supplies the bytes.

Every run starts a new timestamp-named immutable chain.

## Flow

1. `cgamx` checks, resets, builds, and starts the standalone infrastructure.
2. `cgadl` indexes the database catalogue, selects six databases, and downloads
   them into the flow-owned qldbstore.
3. `cgaql` indexes the query library, selects `Fprintf.ql`, and builds its pack.
4. `cgamr run` submits one named analysis, waits for terminal status, downloads
   results, and verifies the archives in one graph step.
5. `cgasi` imports the submission into per-job SQLite files and one cumulative
   DuckDB, then verifies the findings store.
6. `cgaex` writes human-readable Markdown and structured JSON exports.
7. `cgamx` checks the service logs for non-benign errors.

Every successful command also captures the composite dashboard. The JSONL dump
is `.cga/tmp/mrva-flow-dashboard.jsonl`; the script creates the self-contained
replay `.cga/tmp/mrva-flow-replay.html`. It also exports the final `.cga`
data-flow and control-flow trees to `.cga/tmp/mrva-flow-data-flow.html` and
`.cga/tmp/mrva-flow-control-flow.html`. Override those paths with
`CGA_DFG_EXPORT` and `CGA_CFG_EXPORT`. The HTML files embed Graphviz SVG and use
the same topology and left-aligned multiline node labels as PDF output.

The flow is Linux-only and shares MRVA port 8081 and PostgreSQL with the other
system scenarios. Run only one MRVA scenario at a time.

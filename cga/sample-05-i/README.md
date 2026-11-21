# cga sample-05-i — standalone interactive status/download/ingest sequence

> **Earlier prototype example:** this two-user walkthrough is retained for
> experimentation and possible expansion. Start with
> [`../mrva-flow`](../mrva-flow) for a single-user recorded MRVA flow.

This is the **standalone** twin of [`../sample-05`](../sample-05). It keeps the
exact same operator-driven sequence of cga component commands and the same test
axes, but every `NN-*.sh` step drives the MRVA lifecycle through **cga\*
binaries only**, passing all state as a CGAST JSON object. The infrastructure
phases that `sample-05` borrowed from `cga/system-tests/run-system-05` (via a bash
`system_phase`/`phase_*` shim) are now owned by the [`cgamx`](../cgamx)
component and invoked exactly like the other cga\* filters. Nothing under
`cga/system-tests/` is required to run it.

The retained test axes mostly match `sample-05`, with one intentional
divergence: Bob runs `Fprintf.ql` across six databases chosen to contain real
`fprintf` call sites, so `cgasi` ingests non-empty results (Eve's axis is
unchanged).

- two named submissions and two standalone identities (`bob-1`/`bob` and
  `eve-1`/`eve`),
- six jobs for Bob and one for Eve,
- one query pack per submission,
- an immediate status observation after each submit,
- repeated, manually initiated status observations until terminal,
- result-archive download, per-user SARIF ingestion into one cumulative DuckDB,
  archive/ingestion verification, and a server error-log gate.

Seven small C++ databases are obtained through `cgadl`. Its explicit
`--output-dir` is the sample-owned qldbstore tree served over HTTP to the MRVA
server/agents, matching the repository's standalone storage model while keeping
selection and retrieval inside the cga component model.

## What "standalone" changes vs. sample-05

`sample-05` sourced `run-system-05` for its global infrastructure phases via a
`system_phase` shim, so its `NN-*.sh` scripts mixed bash `phase_*` calls with
cga\* commands. `sample-05-i` removes that split: the infrastructure phases —
`preflight`, `reset`, `build`, `start`, `logs`, `check`, `stop`, `cleanup` — are
owned by the [`cgamx`](../cgamx) component (a CGAST filter like
`cgadl`/`cgamr`), whose logic was ported to Python from
`cga/system-tests/standalone-multi-agent-lib.sh`, the global phases of
`cga/system-tests/run-system-05`, and
`cga/system-tests/cleanup-standalone-multi-agent-e2e.sh`. Every `NN-*.sh` step is
therefore a single atomic cga\* filter application over the shared CGAST. Two
adaptations were made during the port: config paths are anchored at the cga/repo
root rather than a `cga/system-tests/` cwd, and stale-port reclaim uses `ss` instead
of `lsof` (not installed on the dev hosts here). The cga component interactions
are otherwise identical to `sample-05`.

`_common.sh` puts every `cga/*/bin` and the cga root on `$PATH`, so the scripts
call `cgamx`, `cgadl`, `cgaql`, `cgamr`, `cgasi`, and `cga run` by bare name;
`cga_cmd` is just the atomic session-swap wrapper around one such filter.

## Run it

Run each script separately, from this directory, and inspect the browser and
shell output before moving on:

```sh
cd cga/sample-05-i
./00-start-cga.sh
./01-preflight.sh
./02-reset.sh
./03-build.sh
./04-start-mrva.sh
./05-index-libraries.sh

./10-bob-databases.sh
./11-bob-query.sh
./12-bob-submit.sh
./13-bob-status.sh

./20-eve-databases.sh
./21-eve-query.sh
./22-eve-submit.sh
./23-eve-status.sh

./30-bob-status.sh   # invoke these two again until both say succeeded
./31-eve-status.sh

./40-bob-download.sh
./41-eve-download.sh
./50-bob-ingest.sh
./51-eve-ingest.sh
./55-export-results.sh

./60-verify.sh
./70-export-dashboard.sh
```

`00-start-cga.sh` prints the composite cga URL (port 8710 by default).
`04-start-mrva.sh` also prints the live MRVA sysview URL. The cga page re-reads
`cga-tmp/sample-05-i.json`, so every successful component command becomes
visible when the page is refreshed. The page is a **snapshot**, not a live
poller: it does not auto-refresh (an auto-refresh would wipe unapplied input in
the editable cgasi Findings view). Refresh it explicitly with the prominent
**reload** button, by clicking an overview box, or by pressing **apply** in the
Findings view (which sends the equivalent `cgasi view` command to the
`cgamx cmd` server, then refreshes).

`02-reset.sh` starts a new whole-CGAST snapshot chain. Every successful
`cga_cmd` writes an immutable node under `cga-tmp/sample-05-i-history/nodes/`,
records its command, numbered-script source, and parent in `manifest.json`, then
updates `sample-05-i.json` as the viewer-compatible current head. Compact node
IDs have the form `cga_<chain>_<tool>_<action>_<sequence>`, for example
`cga_0_dl_download_1`. To branch a later manual run from an earlier node, set
its ID while resetting:

```sh
CGA_CHAIN_PARENT=cga_0_mr_status_7 ./02-reset.sh
```

Without `CGA_CHAIN_PARENT`, the new chain starts from `{}`. Override
`CGA_HISTORY_DIR` to put the immutable history elsewhere.

Inspect the accumulated run graph through the unified dispatcher:

```sh
MANIFEST=../cga-tmp/sample-05-i-history/manifest.json
cga dfg --manifest "$MANIFEST" info
cga dfg --manifest "$MANIFEST" show
cga dfg --manifest "$MANIFEST" --markdown info
cga dfg --manifest "$MANIFEST" --dot show
cga dfg --manifest "$MANIFEST" --render sample-05-i-dfg.pdf show
cga dfg --manifest "$MANIFEST" --render-user sample-05-i-dfg.html show
cga cfg --manifest "$MANIFEST" show
cga cfg --manifest "$MANIFEST" --render sample-05-i-cfg.pdf show
cga cfg --manifest "$MANIFEST" --render-user sample-05-i-cfg.html show
```

The long command names are `cga data-flow-graph` and `cga control-flow-graph`.
These are legacy-manifest inspectors; this deprecated reference therefore passes
its manifest explicitly. Current `.cga/` workflows use `cga tree show`.

Every successful `cga_cmd` also captures the complete rendered dashboard: the
header, all five overviews, and all five detail panels. The JSONL dump is
`cga-tmp/sample-05-i-dashboard.jsonl` by default and is reset by
`00-start-cga.sh`. `70-export-dashboard.sh` turns it into
`cga-tmp/sample-05-i-replay.html`, a single self-contained file that can be
opened with `file://` after every CGA and MRVA process has stopped. Its progress
slider is on the left; dragging it, scrolling over it, or using arrow, Home, and
End keys replays the run. Clicking an overview shows that component's captured
detail for the selected point.

> **Browser cache:** the page loads `cga.js`; if you have opened it before, a
> normal reload may serve a cached copy of the script. After the page's
> JavaScript changes, do a **hard reload** (Ctrl+Shift+R) once so the new script
> is loaded — otherwise you may still see the old behaviour (e.g. entries being
> wiped).

There is intentionally no `all` command and no polling loop. Each script is one
human/LLM-controlled component interaction. The `30` and `31` scripts each make
one status request; deciding when to observe again is part of the sample.

After verification, leave the services running for inspection or use:

```sh
./90-stop.sh          # stop services, retain runtime state
./99-cleanup.sh       # stop services and remove MRVA tables/work state
./199-nuke-all.sh     # TESTING ONLY (dedicated machine): force-kill everything
```

`199-nuke-all.sh` is the sledgehammer for a **dedicated** test machine: it runs
the graceful shutdowns, then `pgrep`/`pkill`s any orphaned cga\* server, the
composite page, and the MRVA binaries. Use it when a normal `cga run stop` left
a stale server behind (e.g. a `cgasi serve` still serving old code after a
source edit — Python loads `serve.py` once at startup, so edits are invisible
until the server is restarted). Do **not** run it on a shared machine.

Cleanup retains the sample CGAST, downloaded result archives, per-job SQLite
databases, and cumulative DuckDB under `cga/cga-tmp/`. `02-reset.sh` starts a
fresh CGAST on the next run.

## Components and state

The scripts pass one shared CGAST atomically through the components:

1. `cgadl getmeta/sql/download` selects and retrieves the CodeQL databases; Bob
   and Eve are attributed in `cgadl-history`, so both remain visible.
2. `cgaql index/select/pack` selects and bundles one query, likewise retaining
   both user-scoped selections in `cgaql-history`.
3. `cgamr submit` verifies the selected qldbstore files, submits their
   repository names with the current pack, and records the named session.
4. `cgamr status` records the server response for that named session.
5. `cgamr download` retrieves every result archive reported by status.
6. `cgasi ingest` extracts each archive's `results.sarif`, converts it to SQLite
   with the MRVA user attached to every row, and rebuilds one cumulative DuckDB
   across Bob and Eve.
7. `cgaex human/llm` turns that cumulative result store and its per-job
   provenance into a Markdown report and self-contained structured JSON,
   retaining successful zero-finding jobs.
8. `cgamr verify` checks `succeeded` plus one on-disk archive per selected
   repository; `cgasi verify` checks the extracted inputs, `user` schema, and
   cumulative row count. `cgamx logs` tails the server log and `cgamx check` is
   the final gate that rejects non-benign server errors.

`_common.sh` supplies overridable defaults, puts the cga\* binaries on `$PATH`,
and provides the snapshotting CGAST update helper (`cga_cmd`). The standalone
infrastructure phases live in the `cgamx` component, which computes every MRVA
setting from the environment with a default only when unset. Useful overrides
include `CGA_SESSION`, `CGA_HISTORY_DIR`, `CGA_CHAIN_PARENT`, `CGA_MRVA_SERVER`,
`RUN_TAG`, `MRVA_WORK_DIR`, the `CGA_*_PORT` variables, and every environment
variable honored by `cgamx` (`PORT`, `POSTGRES_*`, `MRVA_STANDALONE_STORAGE`,
`MRVA_MINIO_*`, `MRVA_POOL_*`, ...). Dedicated ports 8710–8718 and
`.run/sample-05-i/` keep this viewer independent from both the default cga page
(8600–8608) and `sample-05`; `RUN_TAG=cga-sample-05-i` and
`/tmp/mrva-cga-sample-05-i` keep its runtime state separate too. It still shares
the MRVA server port (`8081`) and Postgres, so run only one MRVA scenario at a
time.

Like `cga/system-tests/run-system-05`, the full sequence is Linux-only. The MRVA
infrastructure and the cga launcher rely on Linux process-management tools.

# run-system-11: observe sysview at scale

Run the same trivial `sample-query/Fprintf.ql` over 200+ distinct C/C++
databases, then repeat that selection across users and sessions. This is a
debugging observation, not a performance pass/fail threshold or an evaluation of
the query's findings. The browser is the human observation surface;
`/sysview/data` supplies machine-readable measurements.

The shell driver uses the **CGA dispatcher** for database selection/download,
query selection/packing, submissions/status, infrastructure, and artifact
recording. `observe.py` adds only scenario-specific input checks, coordination of
status polling through `cga mr status`, and endpoint sampling. It does not
implement a second MRVA client or manually thread workflow state.

## Run

From the repository root:

```sh
run=cga/system-tests/run-system-11/run

# Prepare inputs without starting/resetting MRVA. Initial download takes time.
# Progress shows completed/total archives and bytes for the current transfer.
$run prepare

# These phases reclaim ports and reset shared PostgreSQL state.
$run preflight reset build start

# Submit one session; every selected database becomes one job.
$run submit
# Open http://127.0.0.1:8081/sysview in your browser.
open http://127.0.0.1:8081/sysview
$run observe
$run wait verify

# Stop, retaining state and evidence; reconnect by starting and reopening the URL.
$run stop
$run start

# Stop services and remove MRVA runtime state, retaining inputs and observations.
$run cleanup
```

`$run all` runs preparation through verification and leaves MRVA running for
inspection. Use it only with a fresh experiment root. If inputs are already
prepared, use the separate phases above. Do not run another MRVA scenario
concurrently: different scratch roots do not isolate PostgreSQL or service
ports. `reset` does not stop services; run `preflight` first or stop them
explicitly.

Preparation can download large archives. It freezes the catalogue selection and
query pack in a recorded workflow under `.cga-system-11/analysis`, and
records archive hashes, creation versions, the pack hash, and runtime version in
`.cga-system-11/inputs.json`. Archives are staged under
`.cga-system-11/databases`, outside the MRVA reset directory. Stop/cleanup do
not delete these prepared inputs or observation reports.

The default root is the ignored `<checkout>/.cga-system-11` directory, not
`/tmp`. On this machine it lives under
`/mnt/common/home/hohn/work-ghp/single-machine-mrva`, on the larger filesystem.
**Plan for at least 50 GiB free before preparing a fresh run.** An observed
`.cga-system-11/` directory occupied **26 GiB** (`du -shx` reported `26G`);
16 GiB is not enough for the complete experiment. Allow additional space for
concurrent workers' unpacked databases, results, logs, and retained observations.
The 50 GiB planning allowance is not a guaranteed peak bound, especially when
increasing worker concurrency or retaining multiple runs.

Preparation and server startup still enforce only a **16 GiB free-space
headroom check** on each runtime filesystem; passing it does not establish that
the whole run will fit. `TMPDIR` defaults to `$CGA_SYSTEM11_ROOT/tmp` so query
packing and workers' unpacked databases also stay off `/tmp`. Explicit path
overrides are preserved and checked; an explicitly exported `TMPDIR=/tmp` must
be changed if that filesystem is too small.

If preparation fails partway, rerun `$run prepare` with the same root and inputs.
Completed archives are verified and skipped. HTTP transfers with catalogue
SHA-256 hashes resume retained `.part` files when the origin supports Range;
otherwise the current archive restarts, never appends a full response to a
partial file. Incomplete or mismatched data is not published as a completed ZIP.
Progress appears immediately through CGA, with per-file byte counts during
transfers and completed/total archive counts. No service reset is needed.
Preparation refuses to replace `inputs.json` once the entire input set is frozen.

The default catalogue is `cga/cgadl/db-collection.global/metadata.sql`.
[`databases.sql`](databases.sql) chooses one snapshot per `owner/repo`, latest by
ingestion time with a deterministic hash tie-break. MRVA identifies a database
by `owner/repo`, so multiple snapshots of that repository must not be counted as
independent jobs within a submission. The current catalogue has 2,923 rows but
230 distinct C/C++ repositories; the default baseline therefore has 230 jobs.
Selections below 200, duplicate identities/content hashes, and archive hash
mismatches are errors, not skipped observations.

Database creation versions are intentionally mixed. The runtime is recorded,
not required to equal each database's creation version. Actual analysis
incompatibilities and OOM failures remain visible job outcomes; they are not
silently excluded from D or counted as successful analyses.
`CODEQL_CLI_PATH` selects the runtime and, by default, the query-packing CLI.
Use the full CodeQL bundle so `cga ql pack` can resolve its pinned library.

## Scale up and compare

Keep the prepared inputs and reset execution state before submitting a larger
workload:

```sh
# ensure machine is large enough
export MRVA_POOL_MAX_WORKERS=10
export MRVA_CODEQL_RAM_MB=12288
run=cga/system-tests/run-system-11/run
$run stop
$run preflight reset start
USERS=5 SESSIONS=2 $run submit
$run observe
$run wait verify
```

With 230 selected databases, this creates ten sessions and 2,300 jobs.
`workload.tsv` records submission names and authenticated users before the first
submission. A repeated `submit` is rejected; after an interrupted submission,
inspect `cga -C .cga-system-11/analysis mr info` rather than blindly
resubmitting. `wait` uses the recorded workload, not the current `USERS` or
`SESSIONS` environment. `verify` checks the exact users, distinct session IDs,
repository sets, pack identity, and **terminal per-repository outcomes**. It
reports succeeded/failed/canceled/timed-out counts and lists unsuccessful jobs.
This verifies a completed observation, not that every analysis succeeded. It
does not download/ingest SARIF.

MRVA's aggregate session status `succeeded` can mean mixed completed outcomes;
it does not guarantee all individual jobs succeeded. Both `wait` and `verify`
therefore inspect the full per-repository response. Missing, duplicate,
unexpected, or unknown-status jobs are errors. Active jobs keep `wait` polling
and cause `verify` to report that completion has not yet been observed.

The strict log-error gate remains separately available as `$run check`
(`cga mx check`). It can fail on recorded analysis failures, including OOMs;
it is not automatically run by `verify` or `all`.

For full/limited comparisons, reuse the frozen inputs, worker settings, and
workload shape, stopping/resetting/restarting between runs. This scenario does
**not** implement limited mode. On branches supporting `MRVA_DEBUG_SYSVIEW`,
`true` enables full snapshots; use `limited` only once that server behavior
exists. Older servers ignore the variable. An off server's 403 is an observation
failure, not an empty healthy snapshot.

```sh
$run stop
MRVA_DEBUG_SYSVIEW=limited $run preflight reset start
USERS=5 SESSIONS=2 $run submit
$run observe
```

Each `observe` invocation creates a new JSONL file under `observations/`. It
checks the HTML endpoint once, then samples the JSON endpoint with a request
timeout, recording response time including body transfer, payload bytes,
Python JSON parsing time, server generation label/refresh interval, and shown
entity counts. HTTP failures and snapshot errors are retained and fail the
command; successful reports are also recorded with `cga artifact add`.

Python parsing time is **not browser rendering time**. The current generation
label is only a time of day, not a reliable snapshot-age metric, and the current
server does not expose build/query duration. Those require later server
instrumentation. Use the browser's Performance panel during refreshes to inspect
rendering, and manually observe scrolling, collapsing, pause/resume, and
interaction latency. Capture another report after completion for settled-state
comparison. Leave snapshot dumping off for baseline measurements unless its
cost is specifically being investigated.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CGA_SYSTEM11_ROOT` | `<checkout>/.cga-system-11` | Experiment inputs, workflow, reports, and runtime |
| `CGA_TEST_WORKFLOW` | `$CGA_SYSTEM11_ROOT/analysis` | Recorded CGA workflow |
| `TMPDIR` | `$CGA_SYSTEM11_ROOT/tmp` | Query-pack and worker temporary files |
| `CGA_SYSTEM11_CATALOGUE` | Global catalogue above | Source catalogue |
| `CGA_SYSTEM11_SELECTION_SQL` | Local `databases.sql` | Explicit database selection |
| `USERS` / `SESSIONS` | `1` / `1` | Users and sessions per user at submission |
| `MRVA_POOL_MAX_WORKERS` | `2` | Bound concurrent CodeQL memory use |
| `OBSERVE_SAMPLES` | `60` | JSON endpoint samples per report |
| `OBSERVE_INTERVAL` | `1` | Seconds between completed samples |
| `OBSERVE_REQUEST_TIMEOUT` | `10` | Per-request socket timeout in seconds |
| `POLL_INTERVAL` | `5` | Seconds between status-poll cycles |
| `POLL_DEADLINE_SECS` | `14400` | Poll deadline; an in-flight CGA request may outlast it |

Existing `cga mx` environment overrides remain available, including ports,
PostgreSQL, storage, and runtime paths. Preserve the same overrides across
separate phase invocations. Preparation is frozen once per root; use a new root
to intentionally change D or Q.

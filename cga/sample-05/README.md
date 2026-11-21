# cga sample-05 — interactive status/download/ingest sequence

This directory lifts the semantics of
[`cga/system-tests/run-system-05`](../system-tests/run-system-05) into an
operator-driven sequence of cga component commands. It keeps the same important
test axes:

- two named submissions and two standalone identities (`bob-1`/`bob` and
  `eve-1`/`eve`),
- two jobs for Bob and one for Eve,
- one query pack per submission,
- an immediate status observation after each submit,
- repeated, manually initiated status observations until terminal,
- result-archive download, per-user SARIF ingestion into one cumulative DuckDB,
  archive/ingestion verification, and a server error-log gate.

The database identities differ from the small Debian fixtures in
`run-system-05`. This sample deliberately obtains three small C++ databases
through `cgadl`. Its explicit `--output-dir` is the harness-owned qldbstore tree
served over HTTP to the MRVA server/agents, matching the repository's standalone
storage model while keeping selection and retrieval inside the cga component
model.

## Run it

Run each script separately, from this directory, and inspect the browser and
shell output before moving on:

```sh
cd cga/sample-05
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

./40-bob-download.sh # download and view sarif
./41-eve-download.sh
./50-bob-ingest.sh
./51-eve-ingest.sh

./60-verify.sh
```

`00-start-cga.sh` prints the composite cga URL (port 8700 by default).
`04-start-mrva.sh` also prints the live MRVA sysview URL. The cga page re-reads
`cga-tmp/sample-05.json`, so every successful component command becomes visible
without restarting the page. The composite page refreshes its fragments every
two seconds while visible and retains the selected detail panel. Clicking any
overview also refreshes all overviews before displaying the selected detail.

There is intentionally no `all` command and no polling loop. Each script is one
human/LLM-controlled component interaction. The `30` and `31` scripts each make
one status request; deciding when to observe again is part of the sample.

After verification, leave the services running for inspection or use:

```sh
./90-stop.sh          # stop services, retain runtime state
./99-cleanup.sh       # stop services and remove MRVA tables/work state
```

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
7. `cgamr verify` checks `succeeded` plus one on-disk archive per selected
   repository; `cgasi verify` checks the extracted inputs, `user` schema, and
   cumulative row count. The final script also rejects non-benign server errors.

`_common.sh` supplies overridable defaults and the atomic CGAST update helper.
Useful overrides include `CGA_SESSION`, `CGA_MRVA_SERVER`, `RUN_TAG`,
`MRVA_WORK_DIR`, the `CGA_*_PORT` variables, and every environment variable
honored by the standalone system-test harness. Dedicated ports 8700–8708 and
`.run/sample-05/` keep the sample viewer independent from the default CGA page.

Like `cga/system-tests/run-system-05`, the full sequence is Linux-only. The MRVA
harness and the cga launcher rely on Linux process-management tools.

The setup/build/server scripts reuse only the global infrastructure phases of
`run-system-05`. Submission lifecycle work is performed by the cga components.

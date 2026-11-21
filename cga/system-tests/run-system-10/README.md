# run-system-10

This is the collection-scale preparation-to-analysis end-to-end test. It derives the
eligible database set from the live `cgactl` PostgreSQL state and promoted
collection, rather than using fixture databases.

A CVE is eligible only when its controller jobs are successful and completed,
promotion records exist, and all six `(variant, mode)` combinations exist:

```text
{vulnerable, patched, most-recent} × {none, trace}
```

For every eligible CVE, the driver materializes the query declared by its real
CGA preparation specification, builds reproducible query packs through `cgaql`, selects
exactly that CVE's six catalogue rows, and creates one named MRVA submission.
It then downloads all SARIF, ingests it into CGA's cumulative DuckDB store,
exports human and LLM reports, and verifies the cardinalities.

Run the complete workflow from the repository root:

```bash
cga/system-tests/run-system-10/run all
```

The phases are independently runnable:

```bash
cga/system-tests/run-system-10/run select
cga/system-tests/run-system-10/run queries
cga/system-tests/run-system-10/run submit
cga/system-tests/run-system-10/run wait
cga/system-tests/run-system-10/run download
cga/system-tests/run-system-10/run ingest
cga/system-tests/run-system-10/run export
cga/system-tests/run-system-10/run verify
cga/system-tests/run-system-10/run info
cga/system-tests/run-system-10/run cleanup
```

Runtime state and reports default to `/tmp/cga-system-10`. `all` leaves MRVA
running for inspection. The database HTTP server serves the existing
`cga/db-collection.local/databases` qldbstore tree without copying it.

Analysis operations are recorded in `$CGA_TEST_WORKFLOW` (default
`$CGA_SYSTEM10_ROOT/analysis`, with `CGA_SYSTEM10_ROOT=/tmp/cga-system-10`).
Query preparation uses one separate recorded workflow per CVE under
`$CGA_PREP_TMPDIR`. JSON session files are exported read-only snapshots for
assertions and dashboards. `reset` starts a fresh analysis chain.

`CGACTL_DATABASE_URL` must point to the controller database containing the
`cgactl.jobs` and `cgactl.promotions` tables. The default is
`postgresql:///cgactl`; ordinary libpq connection variables such as `PGPORT`
also apply. An unavailable controller, empty eligible set, or incompatible
CodeQL version is an error, not a skipped or successful collection run.

The CodeQL runtime must match the version recorded by every database in the
eligible set, and the full CodeQL bundle must be installed. `cgaql` resolves
the exact bundled library-pack version, so this test neither selects “latest”
from the registry nor silently analyzes with a mismatched CLI.
Set `CODEQL_CLI_PATH` to the selected bundle's `codeql` executable when a
different CodeQL installation is also present on the host; the driver gives
that explicit path precedence for all phases.

The driver defaults to two concurrent MRVA workers. CodeQL evaluation uses
substantial off-heap memory in addition to its Java heap; four workers caused
the kernel OOM killer to terminate an analysis on the 36 GiB reference VM.
`MRVA_POOL_MAX_WORKERS` remains an explicit operator override.

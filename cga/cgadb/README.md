# `cga db build` — build one CodeQL database

`cga db build` consumes one immutable job produced by `cga db plan`, creates
one disposable source copy, creates one CodeQL database, bundles one archive,
and appends one database record to preparation CGAST.

```sh
cga db build --job FILE --trace --output-dir DIR
cga db build --job FILE --bm-none --output-dir DIR
```

`--trace` and `--bm-none` are mutually exclusive and must match the job mode.
Trace jobs require a `build_command`; build-mode-none jobs invoke
`codeql database create --build-mode=none`.

With `--use-llm`, a supervisor reads the build parameters and human source
documentation, supplies dependency/setup commands and a trace build command, and
receives failure output for repair. `cga db plan --use-llm` permits planning
before the trace command is discovered and records that choice in its jobs.
`--llm-attempts N` bounds attempts (default 3). Every attempt uses a new
disposable copy and retains its recipes, logs, outcome, and effective source
hash. See the
[supervisor contract](../cgaassist/README.md#llm-supervised-attempts).

Before building, verify the input tree against the planned source hash. After
bundling, hash the final ZIP and publish it as
`OWNER/UPSTREAM_REPOSITORY-SHA256/OWNER_UPSTREAM_REPOSITORY-SHA256_db.zip`. The
hash-qualified identity is independent of version/mode labels and unchanged by
export. Completed job IDs cannot be built twice in the same recorded inputs.

`--trace` is a strict contract, not merely a request to pass `--command`.
After database creation, the builder rejects scan fallback unless the database
contains a nonempty `build-tracer.log` with at least one intercepted process
and no source-scanning marker. This verification happens before bundling or
recording, and its tracer-log hash and intercepted-process count are retained
as provenance.

Optional `--record FILE` selects the durable record path. `--resources DIR`
associates externally collected telemetry with the record but does not perform
measurement. Use the orthogonal wrapper:

```sh
cga control measure --cgast-filter \
  --output-dir resources/JOB \
  --log logs/JOB.log -- \
  cga db build --job jobs/JOB.json --trace \
    --output-dir databases --resources resources/JOB
```

The component writes `cgadb-records`, a cumulative list of one record per
successful invocation. It does not plan matrices, execute queries, or create
catalogues. The direct internal `cgadb serve` entry point remains solely for
the preparation dashboard.

## Archive an existing database

```sh
cga db zip --db-dir /path/to/codeql-db --output /path/to/database.zip
```

This archives an already-built database without rebuilding it. The ZIP has one
top-level database directory containing `codeql-database.yml`; symlinks are
excluded. Output must be outside the database directory. The archive path and
SHA-256 are appended to `cgadb-archives`. ZIP creation does not upload anything:
serve the archive through CGA's database-serving workflow.

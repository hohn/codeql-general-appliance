# cgactl — CGA preparation database-build controller

`cgactl` coordinates the distributed CodeQL database campaign through one
PostgreSQL instance. It creates the 3-variant × 2-mode job matrix, atomically
leases one job to each builder, retains attempt history, fences stale workers,
and serves a read-only campaign dashboard.

The controller deliberately separates deterministic coordination from build
judgment. Jobs begin in the `static` lane. Static failures stop in
`awaiting-llm`; an explicit sweep creates a new immutable attempt in the
`llm-repair` lane. Remaining failures become `escalated` and may be swept into
`master-recovery` with a larger or exclusive-host resource profile.

## Layout

- `bin/cgactl` — executable entry point.
- `lib/cgactl/` — controller, PostgreSQL adapter, matrix, and HTTP service.
- `share/schema.sql` — tables, views, indexes, and queue functions.
- `share/index.html`, `dashboard.css`, `dashboard.js` — read-only dashboard.
- `doc/design.md` — invariants, trust boundary, and recovery model.

Python uses only the standard library. PostgreSQL access is through `psql`, so
no Python database driver is required.

Use `cga ctl --help` to discover the complete command tree, including recovery
and promotion commands. Each subcommand's `--help` describes prerequisites,
effects, environment defaults and adjacent steps without contacting PostgreSQL.
The repository launcher resolves the shared help library in `cga/cgalib`.

## Quick start

Set a DSN or use the standard `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and
`PGDATABASE` variables:

```sh
export CGACTL_DATABASE_URL=postgresql:///cgactl
cgactl/bin/cgactl db-init
cgactl/bin/cgactl matrix \
  --toolchain-digest 'sha256:IMAGE-AND-CODEQL-DIGEST' \
  --output /tmp/cga-jobs.json
cgactl/bin/cgactl jobs-load /tmp/cga-jobs.json
cgactl/bin/cgactl serve
```

The generated source identity is `tree-sha256`, a deterministic digest of the
prepared source tree's paths, entry types, modes, symlink targets, and file
contents. `--source-identity descriptor` remains available only for planning a
matrix before source preparation.

## Builder protocol

Register an immutable Incus baseline and resource profiles, then assign them
to queued jobs. Snapshot creation is an operator action; registration never
creates or mutates a snapshot:

```sh
cgactl/bin/cgactl snapshot-register \
  --snapshot-id cga-codeql-2.23.9-ubuntu-noble-amd64-v1 \
  --container ubu --snapshot clean-v1 \
  --toolchain-digest codeql:2.23.9-ubu-noble-amd64
cgactl/bin/cgactl resource-profile-set --name normal \
  --cpu 8 --memory-bytes 17179869184 --max-concurrent 3
cgactl/bin/cgactl resource-profile-set --name host-max \
  --cpu 9999 --memory-bytes 999999999999 --exclusive-host --max-concurrent 1
cgactl/bin/cgactl jobs-config --lane static --resource-profile normal \
  --base-snapshot cga-codeql-2.23.9-ubuntu-noble-amd64-v1
```

Requested limits are capped during preparation so the VM retains at least two
CPUs and 4 GiB by default. Override the reserves with
`CGACTL_HOST_RESERVE_CPU` and `CGACTL_HOST_RESERVE_MEMORY_BYTES`, but the
controller always requires at least one CPU and 1 GiB for the host. Disk
profiles are capped from the Incus storage-pool resources with a 20 GiB
default reserve (`CGACTL_HOST_RESERVE_DISK_BYTES`) and 5 GiB hard minimum.
Each profile can also impose `--max-concurrent`; claim scheduling serializes
the check so a worker pool cannot exceed that profile's campaign concurrency.

Registering separately is optional because `claim` registers or refreshes the
builder:

```sh
cgactl/bin/cgactl claim --builder build-01 \
  --lane static \
  --metadata '{"architecture":"arm64","container":"cga-builder-v1"}'
```

The JSON response contains `job_id` and `lease_token`. Before any build work,
the host stops the container, restores its registered snapshot, applies the
capped resource profile, starts it, and records the effective environment on
the attempt:

```sh
cgactl/bin/cgactl container-prepare --builder build-01 --job-id JOB \
  --lease-token TOKEN --container ubu
```

The builder then uses:

```sh
cgactl/bin/cgactl phase --builder build-01 --job-id JOB \
  --lease-token TOKEN --status preparing
cgactl/bin/cgactl renew --builder build-01 --job-id JOB \
  --lease-token TOKEN
cgactl/bin/cgactl phase --builder build-01 --job-id JOB \
  --lease-token TOKEN --status building
cgactl/bin/cgactl finish --builder build-01 --job-id JOB \
  --lease-token TOKEN --status succeeded --result @result.json
```

Failed jobs remain terminal until the controller explicitly authorizes a new
attempt. Campaign sweeps retain the failed attempt and advance only the job's
lane and disposition:

```sh
cgactl/bin/cgactl sweep --from-lane static --to-lane llm-repair \
  --reason 'initial LLM recovery sweep'
cgactl/bin/cgactl sweep --from-lane llm-repair \
  --to-lane master-recovery --resource-profile host-max \
  --base-snapshot cga-codeql-2.23.9-ubuntu-noble-amd64-v1 \
  --exclusive-host --reason 'master escalation sweep'
```

LLM and master workers use `claim --lane llm-repair` and
`claim --lane master-recovery` respectively. They are unrestricted inside the
restored container. Their source changes, packages, commands, and conclusions
belong in structured attempt provenance; the pristine source digest remains
the job identity.

Before opening a sweep, export its deterministic recovery input. The report
contains each job specification, latest terminal result and artifact
references, and the complete immutable attempt history:

```sh
cgactl/bin/cgactl failures --disposition awaiting-llm \
  --output /tmp/static-failures.json
cgactl/bin/cgactl failures --disposition escalated \
  --output /tmp/master-escalations.json
```

Run the reconciler periodically:

```sh
cgactl/bin/cgactl requeue-expired
```

Wrap each database-creation command to sample aggregate process-group CPU,
RSS, and I/O once per second. The raw JSONL, summary JSON, and standalone HTML
report are written outside PostgreSQL:

```sh
cgactl/bin/cgactl measure --output-dir /build/resources \
  --log /build/build.log -- codeql database create ...
```

## Promote a successful database

A successful `finish` transaction queues promotion automatically. Run the
trusted promoter on the host, normally as a persistent service:

```sh
cgactl/bin/cgactl promote-auto --collection db-collection.local
```

`--once` processes at most one queued promotion for cron or testing. Promotion
failures remain visible as `failed` and are not confused with build failures.

Promotion fetches the controller-recorded artifact (currently `incus://` and
`file://` URIs), verifies its size and SHA-256, unbundles and resolves it with
CodeQL, installs it atomically under collision-safe qldbstore identity, writes
a provenance sidecar, preserves all other declared artifacts such as logs and
smoke SARIF, and transactionally updates `metadata.sql`. PostgreSQL retains a
small promotion record; when a `resource_report` artifact exists, the
dashboard links to the preserved report:

```sh
cgactl/bin/cgactl promote --job-id JOB \
  --collection db-collection.local
```

The mode is part of the repository identity, for example
`debian/zlib-vulnerable-trace`, so trace and build-mode-none artifacts cannot
collide. `db-collection.local/` is intentionally Git-ignored.

Audit the on-disk collection, optionally hashing every archive, and compare it
with successful controller jobs without changing either side:

```sh
cgactl/bin/cgactl collection-status \
  --collection db-collection.local --verify
CGACTL_DATABASE_URL=postgresql:///cgactl \
  cgactl/bin/cgactl collection-reconcile \
  --collection db-collection.local
```

The dashboard defaults to <http://127.0.0.1:8520>. It serves only GET routes:
`/`, `/healthz`, static assets, `/api/snapshot`, and files below its configured
collection root. Use `serve --collection PATH` when the collection is not
`db-collection.local/`.

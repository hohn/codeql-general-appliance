# Building the CVE CodeQL databases

## Recommendation

The proposed Incus/ZFS arrangement is a good fit, with one important change:
treat a build as a reproducible, immutable job described by a manifest, and
treat the LLM as the repair agent for that job rather than as its scheduler or
source of record. A small deterministic controller should assign work, capture
logs and metadata, validate database output, and collect results. LLM reports
then add diagnosis and reusable build knowledge without determining whether a
job is complete.

There are currently 61 `examples/cves/cve-*` directories, not 60. At three
variants and two extraction modes, the present tree implies **366 database
jobs**. If the intended total is 360, the controller needs an explicit
60-project allowlist rather than deriving its workload from directory names.

## Unit of work

Use one job identity per tuple:

```text
(CVE, source variant, extraction mode, source digest, toolchain digest)
```

For example:

```text
cve-2016-9843 / vulnerable / trace / <source-sha256> / <image+codeql-id>
```

The extraction modes should be named `trace` and `none`. `trace` invokes
`codeql database create` with the project's real build command; `none` invokes
it with `--build-mode=none` and no build command. Do not run both modes in the
same checked-out source directory. Debian builds modify source trees, and the
second result would otherwise depend on job order. Give each job a fresh ZFS
clone or freshly unpacked source snapshot.

The repository uses two vocabularies that should be normalized in the job
manifest: specifications call the latter variants `patched` and
`most-recent`, while downloaded directories currently use `fixed` and
`current`. Pick canonical names and record aliases; do not let workers infer
the mapping.

## Storage layout

A full independent copy of the 3.9 GiB CVE tree in every container is
unnecessary. It also makes it harder to know which inputs a worker actually
used. Prefer three storage layers:

1. A small, read-only base image containing the OS, CodeQL CLI and packs, the
   checked-out CGA preparation code, and common build tooling.
2. A read-only source cache with one verified pristine snapshot per
   CVE/variant. Download and unpack sources once, record hashes, then snapshot.
3. A writable ZFS clone per job containing only that source snapshot, job
   workspace, logs, and database output.

Mount only the selected CVE metadata into the worker if that makes the worker
interface clearer, but avoid manufacturing 61 partial Git clones. A base
snapshot plus a job-specific source mount provides the same consistency with
less copying and a more explicit trust boundary. If a complete CGA preparation checkout
inside every container is useful for tooling, make it a shared read-only image
layer rather than a copied working tree.

Use ZFS compression and per-job quotas. Snapshots/clones provide most of the
space saving expected here; global ZFS dedup is usually not worth its memory
and operational cost. Keep source archives, build products, CodeQL databases,
and logs as separate datasets or directories so retention policies can differ.

Database destinations must be unique and initially absent. On success, make
the database artifact immutable (or snapshot it), then publish it by atomic
rename into a results area. Never let two retries write the same destination.

## Controller and container lifecycle

Use a bounded pool of identical workers rather than starting 366 containers at
once. Set concurrency from measured CPU, RAM, I/O, and temporary-space peaks;
native builds plus CodeQL extraction can consume much more space than the
final bundled database. Start with a pilot set and raise concurrency only after
observing high-water marks.

Each job should follow this lifecycle:

1. Resolve the job manifest and verify the source digest.
2. Clone a pristine source snapshot into a new workspace.
3. Install declared build dependencies in a controlled preparation phase.
4. Record the container image, OS/architecture, CodeQL version, packs,
   dependency state, environment, source digest, and exact command.
5. Run one extraction mode with wall-clock and resource limits.
6. Validate the database with CodeQL, record source-file counts and database
   size, and optionally bundle it.
7. Publish result metadata and logs, then snapshot successful output.
8. Destroy failed scratch state only after retaining the evidence needed for
   repair; destroy successful build intermediates according to policy.

Separate dependency preparation from database creation in the logs even when
the controller performs them in one container. This distinguishes an
unavailable historical dependency from an extraction or compilation failure.
Network access should be disabled during the actual database build if all
inputs can be prefetched. At minimum, retain package repository snapshots or
resolved package versions: an unpinned `apt-get build-dep` makes later retries
different experiments.

Architecture is part of the toolchain identity. Do not silently mix native
arm64 builds, x86_64 builds, and emulated builds in one comparison set. If both
are useful, make architecture another manifest dimension. On arm64 Linux this
repository requires `CODEQL_JAVA_HOME=/usr`; put it in the arm64 container
image and record it in the job environment, or CodeQL's bundled x86_64 JRE
fails with `Exec format error`.

## Success means more than exit status

A zero exit code is necessary but not sufficient. A successful job should
have:

- a finalized, inspectable CodeQL database;
- the expected language and source root;
- nonzero extracted source/code where appropriate;
- captured extractor and build logs;
- a recorded database size and source-file count;
- immutable provenance linking it to source and toolchain digests; and
- optionally, a small smoke query that proves the database can be queried.

The `none` database is not expected to be semantically equivalent to the
traced database. It is the comparison subject. Record useful comparison
metrics such as files seen, files extracted, database size, creation time, and
smoke-query results. Keep the same CodeQL CLI and pack versions for each paired
comparison.

## Repair policy for LLM workers

Give the worker the original manifest, source, logs, and a fresh retry
workspace. Permit repairs only under an explicit policy. It is reasonable to
install missing dependencies, adjust environment variables, apply known
compatibility flags, or correct the declared build command. It is not
reasonable to change vulnerable source code merely to obtain a build unless
that alteration is separately identified as a build-only patch.

Every retry should be a new attempt with its own directory and report. Record
all commands and file changes. A recovered job must report both success and the
delta from the original recipe. Promote a repair into the central recipe only
after it succeeds from a fresh pristine source snapshot; otherwise a dirty
workspace can create a false recovery.

Bound autonomous repair by attempt count and elapsed time. Terminal states
should distinguish at least:

```text
succeeded
succeeded-after-repair
failed-source
failed-dependencies
failed-build
failed-extraction
failed-validation
timed-out
infrastructure-error
```

## Reporting contract

Require a machine-readable `result.json` from every attempt, alongside full
stdout/stderr logs and an optional Markdown explanation. A useful minimum is:

```json
{
  "schema_version": 1,
  "job_id": "cve-2016-9843--vulnerable--trace--...",
  "cve": "CVE-2016-9843",
  "variant": "vulnerable",
  "mode": "trace",
  "attempt": 1,
  "status": "succeeded",
  "source_digest": "sha256:...",
  "toolchain_digest": "sha256:...",
  "started_at": "...",
  "finished_at": "...",
  "commands": [],
  "changes": [],
  "metrics": {},
  "artifacts": {},
  "failure": null,
  "insights": []
}
```

The central consolidator should ingest JSON, reject duplicate or mismatched
job identities, and generate the human report from it. Free-form insights
should carry a scope such as package, build system, distro release,
architecture, or CodeQL version. That lets later agents retrieve relevant
advice without blindly applying a workaround learned on an unrelated project.
The consolidated knowledge base should preserve provenance back to the job and
attempt that established each insight.

## Rollout

Before launching the full matrix, run a representative pilot of roughly six
projects: small and large sources, old and current Debian packaging, and more
than one build system if present. Run all three variants and both modes for the
pilot. Use it to establish:

- actual source, scratch, raw-database, and bundled-database sizes;
- RAM/CPU/I/O high-water marks and safe worker concurrency;
- timeout and retry limits;
- whether `none` validation and comparison metrics are meaningful;
- which dependencies belong in the base image; and
- whether the report schema captures every repair cleanly.

Then freeze the base image and CodeQL version for the 366-job campaign. Run
trace/none pairs near each other in time but in separate pristine workspaces.
Periodically checkpoint the result index, and make reruns select jobs by
manifest identity and terminal status rather than by inspecting directories.

## Repository integration

The focused `cga db build` path consumes one immutable job and bundles one
result. It intentionally does not model campaign attempts, retries, or
distributed scheduling. The proposed matrix therefore needs a separate
campaign driver whose manifest references `cga db plan` jobs and one-database
records. Avoid overloading the build record with distributed-run semantics
until the manifest and result schemas have been exercised by the pilot.

The checked-in CVE metadata is small; downloaded material under each `tmp/` is
ignored by Git and accounts for several GiB. On this host the `tmp` paths are
relative symlinks into the adjacent durable
`single-machine-mrva-artifacts/examples/cves/` tree. Keep generated databases
and campaign reports outside the Git working tree.
Commit only manifests, schemas, normalized recipes, concise consolidated
findings, and tooling needed to reproduce the campaign. This also follows the
parent repository's storage rule: large database archives belong in external
filesystem or object storage, never Git, Git LFS, or PostgreSQL. PostgreSQL, if
used by a controller, should contain only job state, provenance, and artifact
references.

Preserve the existing CGA boundary. Database construction and catalogue
generation belong to CGA preparation; downstream selection, download, query packing, and
MRVA execution belong to CGA. Give all three variants distinct synthetic
repository identities, as the current zlib fixture does, so qldbstore outputs
cannot collide while the catalogue retains the original Debian package and
version provenance.

## PostgreSQL controller

A single PostgreSQL instance is preferable to a three-node cowsql cluster for
this campaign. The controller is already the logical authority, the workload
is finite and restartable, and temporary loss of coordination does not require
the builds to remain continuously available. PostgreSQL also follows the
existing MRVA deployment and operational model in this repository.

PostgreSQL holds only coordination data: jobs, attempts, builders, leases,
events, recipes, insights, and artifact references. Source trees, logs, build
products, and CodeQL databases remain in ZFS or external filesystem/object
storage. Put PostgreSQL itself on durable storage, back it up, and periodically
export the job/result catalogue to JSON. The deterministic campaign manifest
can recreate planned jobs, and published per-attempt result manifests can be
used to reconcile artifact metadata after recovery.

Builders claim work atomically with `FOR UPDATE SKIP LOCKED`. Claims are
time-limited leases containing a random fencing token. Every heartbeat, phase
change, and terminal update must match the job, builder, and current token;
this prevents a late process from publishing over a job reassigned after its
lease expired. A builder may own at most one active job. Expired jobs become
new attempts rather than overwriting the history of the abandoned attempt.

The controller can consist of separate scheduler/reconciler and read-only
dashboard processes while remaining one logical authority. Builders may use a
controller API or restricted PostgreSQL stored functions. The latter is a
simple initial implementation: grant builders permission to execute the
claim/heartbeat/result functions without granting arbitrary table writes. A
single PostgreSQL node is inadequate only if job claiming and dashboard
availability must survive loss of the database host without a recovery pause;
that is not presently a campaign requirement.

Successful jobs enter the master collection through `cgactl promote`, not by
copying bundles manually. Promotion fetches the controller-recorded artifact,
checks its size and SHA-256, unbundles and resolves it with CodeQL, installs it
under a mode-bearing qldbstore identity, preserves the full attempt as a
provenance sidecar, and updates the SQLite catalogue. The local master is the
Git-ignored `db-collection.local/` tree. `collection-status --verify` audits
the filesystem and hashes, while `collection-reconcile` compares it with the
successful jobs in PostgreSQL without changing either side.

Database creation should run through `cgactl measure`, including both traced
and build-mode-none extraction. It samples aggregate process-group CPU, RSS,
process count, and I/O every second and writes raw JSONL, a JSON summary, and a
standalone HTML report beside the build artifacts. Promotion preserves these
files under the job's collection provenance. PostgreSQL stores only the
promotion and report paths, and the host dashboard links the terminal status
to the report; it does not ingest the sample stream.

Production manifests use a deterministic `tree-sha256` identity over each
prepared source tree, including paths, types, permission modes, symlink
targets, and file contents. The zlib pilot was migrated from descriptor
identity to tree identity without rebuilding the already-promoted vulnerable
trace database. Its other five databases were then built and promoted with
resource telemetry. The migrated database intentionally has no telemetry
report because retaining its original bytes was the migration requirement.

Campaign execution is staged rather than allowing opportunistic retries.
Static workers run the canonical recipe and stop on failure. An explicit LLM
sweep advances those terminal jobs to new attempts in the `llm-repair` lane;
remaining failures escalate to a master LLM, which may select an exclusive
profile using nearly all host resources while retaining a controller-enforced
host reserve. Each attempt begins by restoring a registered immutable Incus
base snapshot. LLMs are unrestricted inside that disposable container, while
`cgactl` remains authoritative for leases, source/toolchain identity,
attempt history, scheduling, validation, and host-side automatic promotion.

This boundary is intentionally confined to CGA preparation. CGA consumes only the
promoted database collection and does not receive build logs, repair recipes,
container state, or campaign scheduling details. A future higher orchestrator
may coordinate CGA preparation and CGA, but neither controller should absorb the other's
state model.

# preparation-to-analysis end-to-end analysis

## Scope and notation

Let

```text
V = {most-recent, patched, vulnerable}
M = {none, trace}
```

For a CVE `c`, let `J(c, v, m)` be the set of controller jobs for variant
`v` and build mode `m`. A database produced by a job is eligible when:

- the job status matches `succeeded*`;
- the job disposition is `completed`;
- a `cgactl.promotions` row exists for the job; and
- all six databases for the CVE have one common CodeQL toolchain identity.

The set of complete CVEs and the database set are therefore

```text
C* = {c | for every (v, m) in V x M, exactly one eligible job is present}
D_c = {db(j) | j is the eligible member of J(c, v, m), (v, m) in V x M}
D   = union(D_c for c in C*)
```

Thus `|D_c| = 6` for every `c` in `C*`. This definition intentionally uses
controller state and promotion records as well as files in the collection; an
archive alone does not establish eligibility.

Let `B` be the query bindings declared by the CVE specifications:

```text
B = {(c, q) | the specification for c declares query q}
A = {(q, d) | (c, q) is in B and d is in D_c}
```

`A` is the analysis applicability relation. This is more precise than
`cve_of(q) covers d`: a generic query such as `cpp/overrun-write` can be bound
to several CVEs and therefore has no unique `cve_of(q)` value.

The analysis is

```text
Analyze : A -> SARIF
Analyze(q, d) = s_(q,d)
```

Operationally, CGA batches the six applicable pairs for one binding into one
MRVA submission:

```text
Analyze(q, D_c) -> {s_(q,d) | d in D_c}
```

It does not run the Cartesian product of every query against every database.

## Permanent test

[`cga/system-tests/run-system-10/run`](system-tests/run-system-10/run) is the
permanent collection-scale driver. It:

1. derives `C*` and `D` from the live `cgactl` PostgreSQL database;
2. requires the host CodeQL runtime to match the recorded database version;
3. materializes each CVE's real query and its sibling `.qll` modules through
   CGA preparation;
4. deduplicates identical query definitions and builds reproducible CGA query
   packs;
5. selects exactly `D_c` and submits one six-database MRVA request per query
   binding;
6. downloads and ingests every SARIF archive, exports the human and LLM views,
   and verifies cardinalities across the chain.

Run all phases with:

```bash
./system-tests/run-system-10/run all
```

The phases are also independently runnable. Runtime state and reports are in
`/tmp/cga-system-10`; the test serves the existing promoted collection in
place and does not copy its database archives. See
[`run-system-10/README.md`](system-tests/run-system-10/README.md) for the
phase list and operating details.

## Test snapshot: 2026-08-20

The live eligibility query selected 19 complete CVEs and 114 databases, all
built with CodeQL 2.23.9:

| CVE              | Debian source package |
| ---------------- | --------------------- |
| CVE-2016-9843    | zlib                  |
| CVE-2018-1000052 | fmtlib                |
| CVE-2018-1000127 | memcached             |
| CVE-2018-1000880 | libarchive            |
| CVE-2018-10887   | libgit2               |
| CVE-2018-12326   | redis                 |
| CVE-2018-12982   | libpodofo             |
| CVE-2018-13785   | libpng1.6             |
| CVE-2018-16554   | jhead                 |
| CVE-2018-17540   | strongswan            |
| CVE-2018-19886   | faac                  |
| CVE-2018-20182   | rdesktop              |
| CVE-2018-20534   | libsolv               |
| CVE-2018-5205    | irssi                 |
| CVE-2019-11072   | lighttpd              |
| CVE-2019-13115   | libssh2               |
| CVE-2019-15296   | faad2                 |
| CVE-2019-15945   | opensc                |
| CVE-2019-5052    | sdl-image1.2          |

Those specifications produce 19 bindings but only four distinct query IDs:

- `cga/cve-2016-9843-crc32-location`
- `cpp/overrun-write`
- `cpp/tainted-arithmetic`
- `cpp/tainted-format-string`

The resulting applicability relation has `|A| = 19 x 6 = 114` analysis jobs.

## Source fixes found by the test

The first complete-chain attempt found two reproducibility defects, one
lifecycle defect, and two test-driver resource/observability problems:

- `cgaql` used a wildcard language-pack dependency. That could select a
  registry manifest newer than the installed CLI could parse. It now resolves
  and records the exact `codeql/<language>-all` version bundled with the
  selected CodeQL binary, and passes that bundle as the pack search path.
- CGA preparation query materialization and CGA query packing copied entry-point `.ql`
  files but omitted sibling `.qll` support modules. Both stages now preserve
  those modules; the local `cpp/tainted-arithmetic` copy includes its required
  `Bounded.qll` module.
- Collection-scale polling originally emitted every repository status on every
  pass. The permanent driver now reports completed, pending, and failed
  submission counts only when they change.
- Four simultaneous CodeQL evaluations exhausted the 36 GiB reference VM;
  individual evaluators reached about 8 GiB RSS despite smaller Java heaps.
  The test now defaults to two MRVA workers while retaining an explicit
  `MRVA_POOL_MAX_WORKERS` override.
- `cgamx stop` terminated the detached MRVA server but left its CodeQL
  grandchildren running. It now signals the detached process group, including
  agents and their in-flight subprocesses, and has regression coverage for the
  group and fallback paths.

Regression tests cover the exact bundled dependency and sibling-module paths.

## Observed result

The full verification was intentionally paused on this 36 GiB VM and must be
resumed as a fresh `run-system-10 all` run on a larger host. The local MRVA
state under `/tmp` is disposable and is not part of the promoted database
collection.

Two attempts established the following:

- The first attempt used four workers. At 2026-08-20 14:05:50, the kernel OOM
  killer terminated the CodeQL Java process for
  `debian/libarchive-most-recent-none` in the CVE-2018-1000880 submission.
  MRVA recorded the job as failed; CodeQL exited 137. At the OOM event, four
  evaluators were resident and the killed process had approximately 7.8 GiB
  anonymous RSS. This is a resource failure, not a query or database failure,
  and should be retried on a larger machine.
- A clean attempt with two workers successfully completed 24 repository
  analyses before the scheduler was deliberately drained. The two in-flight
  libgit2 analyses were allowed to finish, producing a final parked state of 26
  succeeded and 88 pending analyses, with no terminal failures in the second
  attempt. Even two evaluators reached roughly 8.2 GiB RSS each and caused two
  desktop low-memory warnings, so this VM is not an appropriate host for the
  complete sample.

On the larger host, install the complete CodeQL 2.23.9 bundle and DuckDB CLI,
make the `cgactl` PostgreSQL database and promoted collection available, and
run:

```bash
MRVA_POOL_MAX_WORKERS=<memory-appropriate-count> \
  ./system-tests/run-system-10/run all
```

Choose concurrency from measured memory, not CPU count. Some remaining
analyses may exceed 64 GiB individually; retain any exit-137/OOM job identity
as a resource failure and retry it on a still larger worker rather than
classifying its database or query as invalid.

## Completed result: 2026-08-24

The fresh larger-host run completed the full chain. The host had 98 GiB RAM
and 25 CPUs. The first pass used six standalone workers with
`MRVA_CODEQL_RAM_MB=16384` and `MRVA_CODEQL_THREADS=4`; these are evaluator
settings rather than standalone cgroup limits. All 114 analyses succeeded, so
there were no memory/CPU failure identities and no 90 GiB/16-core retries were
needed. The earlier 80% fit figure came from experiments on 2,400 randomly
selected Debian projects and was not treated as a prediction for this
collection.

The verified result is:

- 19/19 successful submissions;
- 114/114 downloaded SARIF archives;
- 114/114 ingested SARIF files;
- 666 finding rows; and
- a clean MRVA server error gate.

Large local artifacts are preserved outside Git at
`/mnt/common/home/hohn/work-ghp/single-machine-mrva-artifacts/`. This includes
the promoted `db-collection.local/` tree and the complete run tree under
`runs/run-system-10-2026-08-24/`, with separate SHA-256 manifests. The usual
`cga/db-collection.local` path is an ignored compatibility symlink.

The analysis proper ran from the first completion at 10:55:58 PDT to the last
at 11:04:34 PDT. Five-second telemetry observed a maximum individual CodeQL
Java RSS of 9.62 GiB, maximum concurrent Java RSS of 50.31 GiB, and minimum
host `MemAvailable` of 36.19 GiB. Six Java evaluators were observed
concurrently. Per-job runtime ranged from 7.608 to 85.040 seconds, with a
21.748-second median.

Runtime outputs remain under `/tmp/cga-system-10`. A durable, tracked copy of
the raw status/resource samples, service logs, final PostgreSQL state,
controller reconstruction, CGA state, reports, and checksums is under
`cga/analysis/run-system-10-2026-08-24/`.

The transferred `controller/cgactl.pgdump` was the documented initial backup:
it contained all 366 job definitions but only the first six promotions. The
local controller state was reconstructed from the 122 promoted
`provenance/*/result.json` records and reproduced the documented eligible set
of 19 CVEs/114 databases before analysis. The reconstructed controller dump is
preserved with the run evidence.

The run also found that an explicit alternate CodeQL bundle was shadowed by
the driver's unconditional `/usr/local/bin` path precedence. `run-system-10`
now gives `CODEQL_CLI_PATH` precedence, and its README documents the override.
MRVA and the database HTTP service were stopped after verification; the
runtime results and PostgreSQL tables were retained.

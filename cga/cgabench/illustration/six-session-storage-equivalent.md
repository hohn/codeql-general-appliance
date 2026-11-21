# Six-session storage equivalent

This is a hand-kept experiment notebook for the same six-session `query-study`
illustrated by [the linear shell sequence](six-session-shell-equivalent.sh).
It collects the **data and connections a person would need to retain**, not
every CGAST checkpoint, command response, editor setting, or intermediate draft.
The records below describe the actual accepted artifacts in `my-bench`, active
chain `cga_1`; the shell illustration's friendlier filenames are not their
on-disk names.

The sections are nodes in the storage graph. A session connects an accepted
database and query to a submission; that submission connects to results; the
comparison connects selected result snapshots back to their inputs. A filename
or a finding count alone is not enough to recover those connections.

**Path convention:** `W` means `cga/cgabench/my-bench`, relative to the repository
root. `T` means `W/.cga/tmp`. File links are relative to this document and point
to existing local artifacts, many of which are not committed to Git. This is an
index, **not a portable archive**: it does not copy or relocate those files.

## Experiment and session index

Experiment: `query-study`; mode: `query-changes`; reference: **S1**.
All six sessions are complete. Every session uses the same accepted
[database D](#shared-database-d), not six independently chosen databases.

| Session | Database | Accepted query | Submission | Results | Findings |
| --- | --- | --- | --- | --- | --- |
| [S1](#session-1) | [D](#shared-database-d), reference | [Q1: fprintf](#s1-accepted-query) | [J1](#s1-submission) | [R1](#s1-results) | 172 |
| [S2](#session-2) | [D](#shared-database-d), inherited from S1 | [Q2: fprintf again](#s2-accepted-query) | [J2](#s2-submission) | [R2](#s2-results) | 172 |
| [S3](#session-3) | [D](#shared-database-d), inherited from S1 | [Q3: printf](#s3-accepted-query) | [J3](#s3-submission) | [R3](#s3-results) | 1478 |
| [S4](#session-4) | [D](#shared-database-d), inherited from S1 | [Q4: printf again](#s4-accepted-query) | [J4](#s4-submission) | [R4](#s4-results) | 1478 |
| [S5](#session-5) | [D](#shared-database-d), inherited from S1 | [Q5: back to fprintf](#s5-accepted-query) | [J5](#s5-submission) | [R5](#s5-results) | 172 |
| [S6](#session-6) | [D](#shared-database-d), inherited from S1 | [Q6: narrower fprintf](#s6-accepted-query) | [J6](#s6-submission) | [R6](#s6-results) | 116 |

The latest [comparison C](#comparison-c) uses all six R nodes and S1 as baseline.
Its result is not implied by the six counts above.

## Shared database D

There are two different objects to remember: **which database was selected**
and **the downloaded bytes used for analysis**.

| Record | Retained value or file |
| --- | --- |
| Catalogue used to choose D | [metadata.sql](../../cgadl/db-collection.global/metadata.sql) |
| Accepted selection, one database | [T/cgabench-g577fiy4.json](../my-bench/.cga/tmp/cgabench-g577fiy4.json) |
| Repository | `AFLplusplus/AFLplusplus` |
| Language | `cpp` |
| Source commit | `474ff18ba2a7999a518a4d194fcd5a1f87c3625d` |
| Build identifier | `30eebb0889` |
| Database-producing tool | `codeql-cpp`, version `2.23.1` |
| Download | [AFLplusplus_AFLplusplus_db.zip](../my-bench/.cga/runtime/mrva/db-serve/AFLplusplus/AFLplusplus/AFLplusplus_AFLplusplus_db.zip) |
| Download directory | `W/.cga/runtime/mrva/db-serve/AFLplusplus/AFLplusplus/` |
| Download size | 27,271,907 bytes |
| Selection SHA-256 | `8b15f9e90eaa35e9a5ccb186a1a3160915034cdf165507cbe51e2decbfb636b6` |
| Archive SHA-256 / catalogue content hash | `a5ff9f6b9c69310d398f38b5322ecaf914182e5cd50b9fb32731e75b32ced64c` |

The selection preserves its original
[download URL](https://hohnlab.org/mrva/values/AFLplusplus-AFLplusplus-ctsj-30eebb0889-a5ff9f6b9c69310d.zip)
and catalogue metadata. Keeping the selected row avoids relying on row 7,
the current contents of a mutable catalogue, or just the repository name.

There is **one retained database archive referenced by all six sessions**.
S2-S6 record inheritance from S1.D and its selection/archive digests. They do
not need separate archive copies or fresh downloads. This observation does not
claim that the original download request was a cache miss.

Manual connection to retain: `S1.D = S2.D = ... = S6.D = this selection + these
archive bytes`. Database inputs and the result ZIPs below are different things.

## Common submission context

The following context applies to [J1-J6](#experiment-and-session-index):

| Field | Value |
| --- | --- |
| MRVA server | `http://127.0.0.1:8081` |
| Controller owner/repository | `octo/ctl` |
| Submission user | `hohn` |
| Language | `cpp` |
| Repository/job target | `AFLplusplus/AFLplusplus` |
| Terminal status | `succeeded` |

Each submission additionally needs its **own** client submission name, server
session ID, accepted query pack, and result locations. Here the MRVA IDs happen
to be 1-6, matching the Bench row numbers. That is a coincidence, not a mapping
rule; IDs are scoped to the server deployment and can be reused after a reset.

## Session 1

### S1 accepted query

[Q1](#s1-accepted-query) plus [D](#shared-database-d) are the inputs to
[J1](#s1-submission). Q1 was selected from the existing `sample-query` library:
`Fprintf.ql`, rule `cpp-fprintf-call`, targeting `fprintf`.

| Record | Retained file or value |
| --- | --- |
| Accepted query selection | [T/cgabench-query-ppodqxeh.json](../my-bench/.cga/tmp/cgabench-query-ppodqxeh.json) |
| Submitted pack | [T/cgabench-ybqj_pss.tgz](../my-bench/.cga/tmp/cgabench-ybqj_pss.tgz) |
| Selection SHA-256 | `d1782784f649814c500929705edc694d49995d91a27133ee56d74ee93110b139` |
| Pack SHA-256 | `1c4a942fb1c73f4d9bdf88ab9873200a6f7ebb0654a7e0094b17313f16f82e62` |

The accepted pack contains the source, manifest, and packaged dependencies.
Its manifest records CodeQL CLI `2.27.1` and `codeql/cpp-all: 12.1.1`.
The selection's original source path is `sample-query/Fprintf.ql` under the
repository root; that mutable file is not the accepted source of truth.

### S1 submission

**J1:** `bench-ddd8efab29e2449abae45ab84c4aacde`; MRVA session **1**.
Connect [D](#shared-database-d) and [Q1's pack](#s1-accepted-query), with the
[common context](#common-submission-context), to [R1](#s1-results).

### S1 results

**R1:** 172 findings from [J1](#s1-submission). SQL/SARIF storage root: `T/cgasi-a378mqh4/`.
SARIF and SQLite are in its `bench-ddd8efab29e2449abae45ab84c4aacde/` subdirectory.

| Object | Retained file |
| --- | --- |
| Downloaded result ZIP | [AFLplusplus-AFLplusplus.zip](../my-bench/.cga/tmp/cgamr-bench-ddd8efab29e2449abae45ab84c4aacde-ux8qz_3w/AFLplusplus-AFLplusplus.zip) |
| Extracted raw SARIF | [job-01-AFLplusplus-AFLplusplus.sarif](../my-bench/.cga/tmp/cgasi-a378mqh4/bench-ddd8efab29e2449abae45ab84c4aacde/job-01-AFLplusplus-AFLplusplus.sarif) |
| Ingested per-job SQLite | [job-01-AFLplusplus-AFLplusplus.sqlite](../my-bench/.cga/tmp/cgasi-a378mqh4/bench-ddd8efab29e2449abae45ab84c4aacde/job-01-AFLplusplus-AFLplusplus.sqlite) |
| Session findings DuckDB | [all.duckdb](../my-bench/.cga/tmp/cgasi-a378mqh4/all.duckdb) |
| Frozen findings/provenance snapshot | [T/cgabench-results-yk9xj5oz.json](../my-bench/.cga/tmp/cgabench-results-yk9xj5oz.json) |

Snapshot SHA-256: `8c0eee340763558fa3b386da7c429a8977bd769b4cd1f279a8f6dfc46511f1ec`.
R1 is the reference input to [comparison C](#comparison-c).

## Session 2

### S2 accepted query

[Q2](#s2-accepted-query) plus [D](#shared-database-d) are the inputs to
[J2](#s2-submission). The accepted selection used the existing library again:
`Fprintf.ql`, rule `cpp-fprintf-call`, targeting `fprintf`, identical source
bytes to Q1. The edited `MyQuery` placeholder was **not** the accepted input.

| Record | Retained file or value |
| --- | --- |
| Accepted query selection | [T/cgabench-query-9pa25d4v.json](../my-bench/.cga/tmp/cgabench-query-9pa25d4v.json) |
| Submitted pack | [T/cgabench-sfogicj1.tgz](../my-bench/.cga/tmp/cgabench-sfogicj1.tgz) |
| Selection SHA-256 | `d1782784f649814c500929705edc694d49995d91a27133ee56d74ee93110b139` |
| Pack SHA-256 | `d8f9f48f743f182f5a81c8a403af76e892a5a1876c21c457ae79f3ab8fb5ac5a` |

### S2 submission

**J2:** `bench-34852f18481f423d84ac6c96f0913d18`; MRVA session **2**.
Connect [D](#shared-database-d) and [Q2's pack](#s2-accepted-query), with the
[common context](#common-submission-context), to [R2](#s2-results).

### S2 results

**R2:** 172 findings from [J2](#s2-submission). SQL/SARIF storage root: `T/cgasi-a17y4o67/`.
SARIF and SQLite are in its `bench-34852f18481f423d84ac6c96f0913d18/` subdirectory.

| Object | Retained file |
| --- | --- |
| Downloaded result ZIP | [AFLplusplus-AFLplusplus.zip](../my-bench/.cga/tmp/cgamr-bench-34852f18481f423d84ac6c96f0913d18-od5kmoq8/AFLplusplus-AFLplusplus.zip) |
| Extracted raw SARIF | [job-01-AFLplusplus-AFLplusplus.sarif](../my-bench/.cga/tmp/cgasi-a17y4o67/bench-34852f18481f423d84ac6c96f0913d18/job-01-AFLplusplus-AFLplusplus.sarif) |
| Ingested per-job SQLite | [job-01-AFLplusplus-AFLplusplus.sqlite](../my-bench/.cga/tmp/cgasi-a17y4o67/bench-34852f18481f423d84ac6c96f0913d18/job-01-AFLplusplus-AFLplusplus.sqlite) |
| Session findings DuckDB | [all.duckdb](../my-bench/.cga/tmp/cgasi-a17y4o67/all.duckdb) |
| Frozen findings/provenance snapshot | [T/cgabench-results-hgyh1g77.json](../my-bench/.cga/tmp/cgabench-results-hgyh1g77.json) |

Snapshot SHA-256: `0885734be142c978ef252beef14d469d46599f01667a69070681fe0732c12c5d`.
R2 is an independent repeat, not a pointer to R1; both feed
[comparison C](#comparison-c).

## Session 3

### S3 accepted query

[Q3](#s3-accepted-query) plus [D](#shared-database-d) are the inputs to
[J3](#s3-submission). The editable source began as a copy of
[S1's accepted pack](#s1-accepted-query), then changed to `printf` with rule
`cpp-printf-call`. The filename is still `Fprintf.ql`.

| Record | Retained file or value |
| --- | --- |
| Accepted query selection | [T/cgabench-query-0ah4t8qj.json](../my-bench/.cga/tmp/cgabench-query-0ah4t8qj.json) |
| Submitted pack | [T/cgabench-h_nh5ook.tgz](../my-bench/.cga/tmp/cgabench-h_nh5ook.tgz) |
| Selection SHA-256 | `c3fccdbc48cd716d1e521f04984e1795040d17ccf3ae91eb00a1e5942ffb4df8` |
| Pack SHA-256 | `4ef31c5d70a524e92410ec82dc8531301e135f8d9bdcb4b728ce759b1648d693` |

### S3 submission

**J3:** `bench-0528f6d2d5564d4ea3d1b2a748655899`; MRVA session **3**.
Connect [D](#shared-database-d) and [Q3's pack](#s3-accepted-query), with the
[common context](#common-submission-context), to [R3](#s3-results).

### S3 results

**R3:** 1478 findings from [J3](#s3-submission). SQL/SARIF storage root: `T/cgasi-6u0d4_l8/`.
SARIF and SQLite are in its `bench-0528f6d2d5564d4ea3d1b2a748655899/` subdirectory.

| Object | Retained file |
| --- | --- |
| Downloaded result ZIP | [AFLplusplus-AFLplusplus.zip](../my-bench/.cga/tmp/cgamr-bench-0528f6d2d5564d4ea3d1b2a748655899-nlhb5bwb/AFLplusplus-AFLplusplus.zip) |
| Extracted raw SARIF | [job-01-AFLplusplus-AFLplusplus.sarif](../my-bench/.cga/tmp/cgasi-6u0d4_l8/bench-0528f6d2d5564d4ea3d1b2a748655899/job-01-AFLplusplus-AFLplusplus.sarif) |
| Ingested per-job SQLite | [job-01-AFLplusplus-AFLplusplus.sqlite](../my-bench/.cga/tmp/cgasi-6u0d4_l8/bench-0528f6d2d5564d4ea3d1b2a748655899/job-01-AFLplusplus-AFLplusplus.sqlite) |
| Session findings DuckDB | [all.duckdb](../my-bench/.cga/tmp/cgasi-6u0d4_l8/all.duckdb) |
| Frozen findings/provenance snapshot | [T/cgabench-results-hqxp1hg1.json](../my-bench/.cga/tmp/cgabench-results-hqxp1hg1.json) |

Snapshot SHA-256: `6e8ab6bcf490f564d03b6f98e17ea1497797fb1bb85c2c651b9480e722a7b99e`.
R3 feeds [comparison C](#comparison-c).

## Session 4

### S4 accepted query

[Q4](#s4-accepted-query) plus [D](#shared-database-d) are the inputs to
[J4](#s4-submission). Another copy of [S1's accepted pack](#s1-accepted-query)
was edited to the same `printf` / `cpp-printf-call` source as Q3. The accepted
pack, not the intermediate editor save with the old rule ID, defines this run.

| Record | Retained file or value |
| --- | --- |
| Accepted query selection | [T/cgabench-query-gf0wmx31.json](../my-bench/.cga/tmp/cgabench-query-gf0wmx31.json) |
| Submitted pack | [T/cgabench-gb5dtwz4.tgz](../my-bench/.cga/tmp/cgabench-gb5dtwz4.tgz) |
| Selection SHA-256 | `cdb419b58aa051ffd03e97eb5c43c9de43560ca61e79f56f3bfb6d2cebc0255c` |
| Pack SHA-256 | `08890c6a29ab11b7619a0ced9b92769007e48fd2928d2d74784053c90272a817` |

### S4 submission

**J4:** `bench-6e3428e4c5094f84ad47f8c7355136e8`; MRVA session **4**.
Connect [D](#shared-database-d) and [Q4's pack](#s4-accepted-query), with the
[common context](#common-submission-context), to [R4](#s4-results).

### S4 results

**R4:** 1478 findings from [J4](#s4-submission). SQL/SARIF storage root: `T/cgasi-yo87yd0u/`.
SARIF and SQLite are in its `bench-6e3428e4c5094f84ad47f8c7355136e8/` subdirectory.

| Object | Retained file |
| --- | --- |
| Downloaded result ZIP | [AFLplusplus-AFLplusplus.zip](../my-bench/.cga/tmp/cgamr-bench-6e3428e4c5094f84ad47f8c7355136e8-f3bxqgra/AFLplusplus-AFLplusplus.zip) |
| Extracted raw SARIF | [job-01-AFLplusplus-AFLplusplus.sarif](../my-bench/.cga/tmp/cgasi-yo87yd0u/bench-6e3428e4c5094f84ad47f8c7355136e8/job-01-AFLplusplus-AFLplusplus.sarif) |
| Ingested per-job SQLite | [job-01-AFLplusplus-AFLplusplus.sqlite](../my-bench/.cga/tmp/cgasi-yo87yd0u/bench-6e3428e4c5094f84ad47f8c7355136e8/job-01-AFLplusplus-AFLplusplus.sqlite) |
| Session findings DuckDB | [all.duckdb](../my-bench/.cga/tmp/cgasi-yo87yd0u/all.duckdb) |
| Frozen findings/provenance snapshot | [T/cgabench-results-akxu3h2r.json](../my-bench/.cga/tmp/cgabench-results-akxu3h2r.json) |

Snapshot SHA-256: `6183ed1069fc8d18ea4bd560ce0dfc229d1952f7efa0b42bff00492f13d47f83`.
R4 is a separate run with its own artifacts, despite having Q3's source and
R3's finding count. It feeds [comparison C](#comparison-c).

## Session 5

### S5 accepted query

[Q5](#s5-accepted-query) plus [D](#shared-database-d) are the inputs to
[J5](#s5-submission). A copy of [S1's accepted pack](#s1-accepted-query) was
accepted with the baseline `fprintf` / `cpp-fprintf-call` source again.

| Record | Retained file or value |
| --- | --- |
| Accepted query selection | [T/cgabench-query-8md9lxf_.json](../my-bench/.cga/tmp/cgabench-query-8md9lxf_.json) |
| Submitted pack | [T/cgabench-x0eitzl0.tgz](../my-bench/.cga/tmp/cgabench-x0eitzl0.tgz) |
| Selection SHA-256 | `1df19440197a6be03e5a8a9648d4211ca787a3846ab01039c00d66833fb41409` |
| Pack SHA-256 | `b8b1b5d7db5b2454257bd168e052950fd1ba157a5914dd60160e6f28fe5d9da6` |

### S5 submission

**J5:** `bench-5b39b02738214bcb9f83fa527dbd9b18`; MRVA session **5**.
Connect [D](#shared-database-d) and [Q5's pack](#s5-accepted-query), with the
[common context](#common-submission-context), to [R5](#s5-results).

### S5 results

**R5:** 172 findings from [J5](#s5-submission). SQL/SARIF storage root: `T/cgasi-va678b_0/`.
SARIF and SQLite are in its `bench-5b39b02738214bcb9f83fa527dbd9b18/` subdirectory.

| Object | Retained file |
| --- | --- |
| Downloaded result ZIP | [AFLplusplus-AFLplusplus.zip](../my-bench/.cga/tmp/cgamr-bench-5b39b02738214bcb9f83fa527dbd9b18-f4l9rtm5/AFLplusplus-AFLplusplus.zip) |
| Extracted raw SARIF | [job-01-AFLplusplus-AFLplusplus.sarif](../my-bench/.cga/tmp/cgasi-va678b_0/bench-5b39b02738214bcb9f83fa527dbd9b18/job-01-AFLplusplus-AFLplusplus.sarif) |
| Ingested per-job SQLite | [job-01-AFLplusplus-AFLplusplus.sqlite](../my-bench/.cga/tmp/cgasi-va678b_0/bench-5b39b02738214bcb9f83fa527dbd9b18/job-01-AFLplusplus-AFLplusplus.sqlite) |
| Session findings DuckDB | [all.duckdb](../my-bench/.cga/tmp/cgasi-va678b_0/all.duckdb) |
| Frozen findings/provenance snapshot | [T/cgabench-results-mp7_20xr.json](../my-bench/.cga/tmp/cgabench-results-mp7_20xr.json) |

Snapshot SHA-256: `a2dec49ad1e26701447bd985360c6e7c9f2917a24caf11c4a1616de61ae90ca9`.
R5 feeds [comparison C](#comparison-c).

## Session 6

### S6 accepted query

[Q6](#s6-accepted-query) plus [D](#shared-database-d) are the inputs to
[J6](#s6-submission). A copy of [S1's accepted pack](#s1-accepted-query) was
edited to require `fprintf` **and** `fc.getNumberOfArguments() > 2`.
The rule remains `cpp-fprintf-call`.

| Record | Retained file or value |
| --- | --- |
| Accepted query selection | [T/cgabench-query-m9my1tol.json](../my-bench/.cga/tmp/cgabench-query-m9my1tol.json) |
| Submitted pack | [T/cgabench-m7bug8en.tgz](../my-bench/.cga/tmp/cgabench-m7bug8en.tgz) |
| Selection SHA-256 | `0c3b5b36c55898f56059e7327849836bc80f832fd2b6b67dc9338974888c874c` |
| Pack SHA-256 | `c75fdc6e80e1d70eccb755dbd8b99990909ea8caecc5e48e8f4cc5d7996ad996` |

The accepted pack contains a 286-byte `Fprintf.ql`, while its selection row's
`file_size` still says 250. The packed source includes the extra condition:
catalogue display metadata and current draft files are not substitutes for
the accepted source bytes.

### S6 submission

**J6:** `bench-5ee64681e7e84f99a22335abcb266f80`; MRVA session **6**.
Connect [D](#shared-database-d) and [Q6's pack](#s6-accepted-query), with the
[common context](#common-submission-context), to [R6](#s6-results).

### S6 results

**R6:** 116 findings from [J6](#s6-submission). SQL/SARIF storage root: `T/cgasi-y2voc79o/`.
SARIF and SQLite are in its `bench-5ee64681e7e84f99a22335abcb266f80/` subdirectory.

| Object | Retained file |
| --- | --- |
| Downloaded result ZIP | [AFLplusplus-AFLplusplus.zip](../my-bench/.cga/tmp/cgamr-bench-5ee64681e7e84f99a22335abcb266f80-jrr3lko5/AFLplusplus-AFLplusplus.zip) |
| Extracted raw SARIF | [job-01-AFLplusplus-AFLplusplus.sarif](../my-bench/.cga/tmp/cgasi-y2voc79o/bench-5ee64681e7e84f99a22335abcb266f80/job-01-AFLplusplus-AFLplusplus.sarif) |
| Ingested per-job SQLite | [job-01-AFLplusplus-AFLplusplus.sqlite](../my-bench/.cga/tmp/cgasi-y2voc79o/bench-5ee64681e7e84f99a22335abcb266f80/job-01-AFLplusplus-AFLplusplus.sqlite) |
| Session findings DuckDB | [all.duckdb](../my-bench/.cga/tmp/cgasi-y2voc79o/all.duckdb) |
| Frozen findings/provenance snapshot | [T/cgabench-results-b28zmo3x.json](../my-bench/.cga/tmp/cgabench-results-b28zmo3x.json) |

Snapshot SHA-256: `cdc8d4daaf529de7c0ef576ab9898fd75859940db75c0599def2373a6caeddc8`.
R6 feeds [comparison C](#comparison-c).

## What each result representation preserves

The edges within every R section have different meanings:

```text
submission + repository
    -> downloaded result ZIP
        -> results.sarif
            -> per-job SQLite -> session all.duckdb
            -> frozen findings/provenance JSON -> comparison C
```

The result ZIP contains `results.sarif`; the separately retained `.sarif`
file is its extracted copy. SQLite and DuckDB expose the ingested findings
for SQL. The frozen JSON preserves each finding's `identity`, SARIF `result`,
and `provenance`, plus ingestion information.

That provenance connects a finding to its Bench session/name, user, submission,
MRVA session, repository, SARIF path, and **zero-based run and result indices**
within that SARIF. The session record connects it further back to D and Q.
The frozen result document is not a complete substitute for that input index.

Identical basenames recur throughout the study. Each result ZIP is named
`AFLplusplus-AFLplusplus.zip`; each job has the same SARIF/SQLite basename;
every session SQL store is named `all.duckdb`. **The enclosing session/job
directory is part of the identity.** Putting them in one folder without
renaming or keeping these connections would lose which run they came from.

## SQL stores and their scope

Each linked SQLite and DuckDB has a `sarif_results` table with columns:

```text
user, file_name, kind, rule_id, rule_name, uri,
start_line, start_column, result_json
```

`result_json` retains the SARIF result object. The SQL database is therefore
more than a count or a summary table. The [Findings popup](../README.md) uses
the selected session's DuckDB; its separate result-summary tab shows counts
derived from the ingestion records.

Although the filename is `all.duckdb`, **each of these six stores contains only
its own session's ingestion**. There is no study-wide combined SQL store here.
Each session has one repository/job, hence one per-job SQLite input.

For example, from the repository's `cga/` directory, this reads S6 without
changing it:

```sh
duckdb -readonly -safe -no-init -bail \
  cgabench/my-bench/.cga/tmp/cgasi-y2voc79o/all.duckdb \
  -c 'SELECT rule_id, count(*) AS findings FROM sarif_results GROUP BY rule_id;'
```

It reports `cpp-fprintf-call` with a count of 116. If combining
stores by hand, attach an explicit session label before unioning records:
`user`, `file_name`, and `rule_id` repeat across sessions and cannot identify
a trial.

The Databases, Queries, and Result summary SQL popups are different again:
they materialize temporary DuckDB tables named `databases`, `queries`, and
`result_summaries` from accepted evidence. Those databases are discarded after
the request; they are not additional retained experiment/comparison stores.

## Comparison C

**Important distinction:** the current Bench does **not** create a separate
comparison SQL database. It reads the frozen findings JSON snapshots and
writes a comparison **JSON document**. The six DuckDBs above are retained SQL
findings stores, not six materialized comparison databases.

Latest retained comparison:
[T/cgabench-comparison-une4142z.json](../my-bench/.cga/tmp/cgabench-comparison-une4142z.json).
Created: `2026-10-16T18:39:21.745977+00:00`.
SHA-256, calculated for this notebook:
`120eb54a319cf6ac5501a16dc7db07dea67c353661e39d5a69a9bc145958422e`.

Its input edges are [R1](#s1-results), [R2](#s2-results), [R3](#s3-results),
[R4](#s4-results), [R5](#s5-results), and [R6](#s6-results); baseline is
`E.S[1].R`. The document also retains each input's D/Q artifacts, job record,
user/name, and inherited-input provenance, rather than only the six counts.

Comparison identity is **exact repository, rule, physical/logical locations,
and message**, with **multiset** semantics. Duplicate findings retain their
multiplicity. Each session's added/removed results are relative to S1; the
`common` list is the intersection across **all** selected sessions.

| Compared session | Findings | Added versus S1 | Removed versus S1 |
| --- | --- | --- | --- |
| S1 | 172 | 0 | 0 |
| S2 | 172 | 0 | 0 |
| S3 | 1478 | 1478 | 172 |
| S4 | 1478 | 1478 | 172 |
| S5 | 172 | 0 | 0 |
| S6 | 116 | 0 | 56 |

Common to all six: **0**. The `printf` trials use a different rule and message,
so sharing a source location would not make a finding identical to a baseline
`fprintf` finding. Equal counts likewise would not prove equal findings.

The retained earlier comparisons are separate graph nodes, not overwritten
versions of the latest file:

| Inputs | Retained comparison |
| --- | --- |
| S1, S2 | [cgabench-comparison-s_n1ecfb.json](../my-bench/.cga/tmp/cgabench-comparison-s_n1ecfb.json) |
| S1, S2, S3 | [cgabench-comparison-283yymvv.json](../my-bench/.cga/tmp/cgabench-comparison-283yymvv.json) |
| S1, S2, S3, repeated | [cgabench-comparison-uob1n904.json](../my-bench/.cga/tmp/cgabench-comparison-uob1n904.json) |
| S1, S4 | [cgabench-comparison-ikhc7wyi.json](../my-bench/.cga/tmp/cgabench-comparison-ikhc7wyi.json) |
| S1, S5 | [cgabench-comparison-ote51xwg.json](../my-bench/.cga/tmp/cgabench-comparison-ote51xwg.json) |
| S1-S5 | [cgabench-comparison-2qbsg9n5.json](../my-bench/.cga/tmp/cgabench-comparison-2qbsg9n5.json) |
| S1-S5, repeated | [cgabench-comparison-3n2tvoab.json](../my-bench/.cga/tmp/cgabench-comparison-3n2tvoab.json) |

For a hand-built SQL comparison, the user would additionally retain the
session-to-database mapping, baseline/input list, SQL or view definitions,
identity/multiplicity policy, and saved output. Merely keeping `all.duckdb`
or subtracting counts would not preserve this comparison.

## What a person would keep, rather than all CGAST state

| Keep by hand | Why |
| --- | --- |
| This experiment/session index and D/Q/J/R/C links | Preserve the graph: what ran against what, and which results were compared |
| The accepted D selection, archive identity/hash, and archive or a verified way to retrieve it | Identify the actual analyzed code/database, not today's catalogue entry |
| Each accepted query selection and pack, with hashes | Preserve the selected query and executable inputs, including dependencies, independently of drafts |
| Actual findings: the SQL stores and frozen result snapshots | Retain inspectable results and the comparison-ready identities/provenance |
| A raw SARIF form, preferably ZIP or extracted SARIF | Recommended for full-report inspection, independent re-ingestion, and following original-report provenance |
| Comparison document(s), input list, baseline, and comparison policy | Preserve the conclusions and their derivation, not just displayed totals |

Raw SARIF is not required merely to query an existing SQL store or compare
already-frozen R snapshots. Keeping it is nevertheless useful: `result_json`
and frozen finding objects do not preserve the entire SARIF report's
tool/rule/run metadata. ZIP and extracted SARIF duplicate the report; a manual
archive could keep one raw form and document how to recover the other.

SQLite and DuckDB also overlap: DuckDB is rebuilt from the ingested per-job
SQLite files. A manually curated archive could choose a canonical retained
representation plus a regeneration recipe instead of keeping every derivative.
This notebook lists **what is actually retained**, not a deletion plan for
the running Bench.

There is no need in such a notebook to preserve every unsuccessful draft,
editor port, disclosure state, service-check response, polling response, or
whole-CGAST revision just to understand the completed study. Recovery while a
job is in flight is a separate concern; this index does not replace execution
checkpoints.

The awkward part is not storing six reports. It is preserving every edge:
which database bytes, which accepted query bytes, which remote job, which
report, which SQL projection, and which comparison inputs. Paths under
`.cga/tmp` here are live retained evidence, despite the name. Removing them or
copying only the state JSON would leave missing targets. Moving the experiment
by hand requires copying the chosen artifacts **and updating all these links
and provenance paths**; this document does not perform that migration.
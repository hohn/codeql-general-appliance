# CVE query-effectiveness study

This is a manual source-to-SARIF evaluation of three CVEs from the completed
`run-system-10-2026-08-24` analysis. The sample is purposive: it tests three
different query behaviors and is not a statistical estimate for all 19
eligible CVEs.

| CVE | Query | Assessment | Short reason |
| --- | --- | --- | --- |
| [CVE-2016-9843](CVE-2016-9843.md) | `cga/cve-2016-9843-crc32-location` | **Almost found** | Selects the correct source file, but no line or vulnerability logic and no vulnerable/fixed discrimination. |
| [CVE-2018-16554](CVE-2018-16554.md) | `cpp/tainted-format-string` | **Not found; related alert elsewhere** | Reports a command-line-controlled format string in `jhead.c`, not the fixed GPS altitude write in `gpsinfo.c`. |
| [CVE-2018-1000880](CVE-2018-1000880.md) | `cpp/overrun-write` | **Not found** | Produces no results; the CVE is a WARC input-consumption/progress bug, not a write-overrun data flow. |

The follow-up [remaining 16-case report](REMAINING-CASES.md) finds no direct or
file-level near hit in any other CVE. Across the full 19-CVE collection the
outcome is zero directly found, one file-level almost found (zlib), and 18 not
found.

## Method

For each CVE:

1. Treat the Debian vulnerable-to-patched source delta as the local ground
   truth for the fault location and repair mechanism. Inspect the current
   implementation to identify whether the same repair remains applicable.
2. Inspect all six SARIF products: three source variants (`vulnerable`,
   `patched`, `most-recent`) crossed with two independently built CodeQL
   databases. `trace` runs the real package build; `none` uses CodeQL
   `--build-mode=none` without a build command.
3. Compare each primary result and any path locations with the known fault
   file, function, statement, and repair mechanism. Compare variants only
   within the same extraction mode.
4. Record two separate judgments. **Relevance** asks whether the result reaches
   the known fault; **discrimination** asks whether results distinguish the
   vulnerable source from the patched/current source. “Almost found” means the
   query materially narrows review to the correct area but does not identify
   the faulty operation. A same-package alert for a different operation is not
   counted as almost found.

This is static-result validation, not exploit reproduction. A zero-result
SARIF file is evidence that this query/database combination emitted no result;
it is not evidence that the program is safe.

## Data and reproduction

The reviewed run contains 114 successful analyses and 666 result rows. Raw
SARIF, per-job SQLite, and the cumulative DuckDB are preserved under:

```text
/mnt/common/home/hohn/work-ghp/single-machine-mrva-artifacts/runs/run-system-10-2026-08-24/
```

The external run checksum manifest is anchored by
[`../../ARTIFACTS.sha256`](../../ARTIFACTS.sha256). The compact six-row-per-CVE
extract is [`finding-summary.tsv`](finding-summary.tsv). Regenerate it from
the raw SARIF with:

```bash
python3 query-effectiveness/summarize-sarif.py \
  >query-effectiveness/finding-summary.tsv
```

Run that command from this evidence directory. The script reads versions and
query identities from each checked-in CVE `spec.json`; it does not infer them
from SARIF filenames.

## Cross-case result

None of the three queries proves the selected vulnerability. The zlib query
does exactly what its metadata promises—a file-level review pointer—and is a
useful pipeline positive control, but not a detector. The two generic queries
do not reach their known CVE repairs. In both generic cases the initial CWE to
query mapping is the limiting factor: jhead's repair bounds an output buffer
rather than sanitizing an attacker-controlled format string, and libarchive's
repair ensures parser input is consumed rather than bounding a destination
write.

The practical next step is to derive CVE checks from the repair semantics
first, then use generic CWE queries as supporting evidence. Variant
discrimination should be an explicit acceptance test: a proposed CVE query
should identify the vulnerable operation and cease to report that operation,
or report a clearly changed path, in the patched version built in the same
mode.

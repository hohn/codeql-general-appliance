# Query effectiveness: remaining 16 CVEs

## Conclusion

**All 16 remaining cases fail as CVE detectors.** Eleven produce no findings
in any source variant or database mode. The other five produce 649 findings,
but no vulnerable or patched result location or path step enters the known
fault file. None qualifies even as the file-level “almost found” seen in the
zlib positive-control query.

Together with the initial three-case review, the collection result is:

| Assessment | CVEs | Meaning |
| --- | ---: | --- |
| Directly found | 0 | No result identifies a known vulnerable operation. |
| Almost found | 1 | The zlib query selects the right file only; it cannot distinguish variants. |
| Not found | 18 | No result reaches the known fault, or the query emits no result. |

This supports calling the existing query set a failure **for CVE detection**.
It does not mean every reported generic issue is false, or that CodeQL cannot
express suitable queries. It means these query definitions and CVE mappings do
not validate the known vulnerabilities in this corpus.

## Remaining-case results

Counts below are `none / trace`, always compared within the same build mode.

| CVE / package | Query | Vulnerable | Patched | Current | Evaluation |
| --- | --- | ---: | ---: | ---: | --- |
| CVE-2018-1000052 / fmtlib | format string | 0 / 0 | 0 / 0 | 0 / 0 | No finding for the invalid-format-specifier fault. |
| CVE-2018-1000127 / memcached | arithmetic | 6 / 14 | 6 / 14 | 49 / 10 | Findings are in `memcached.c` and current vendor code; none reaches `items.c:item_free()`. |
| CVE-2018-10887 / libgit2 | arithmetic | 11 / 29 | 11 / 29 | 40 / 45 | Many unrelated arithmetic paths; none reaches `delta.c:git_delta_apply()`. |
| CVE-2018-12326 / redis | overrun write | 0 / 0 | 0 / 0 | 0 / 0 | No finding for the `redis-cli` buffer overflow. |
| CVE-2018-12982 / libpodofo | overrun write | 0 / 0 | 0 / 0 | 0 / 0 | No finding for `PdfVariant::DelayedLoad()`'s invalid read. |
| CVE-2018-13785 / libpng | arithmetic | 0 / 2 | 0 / 2 | 0 / 1 | Findings are only in `contrib/libtests`; none reaches `pngrutil.c`. |
| CVE-2018-17540 / strongSwan | overrun write | 0 / 0 | 0 / 0 | 0 / 0 | No finding for the GMP certificate buffer overflow. |
| CVE-2018-19886 / FAAC | overrun write | 0 / 0 | 0 / 0 | 0 / 0 | No finding for `huff2.c:huffcode()`'s invalid dereference. |
| CVE-2018-20182 / rdesktop | overrun write | 0 / 0 | 0 / 0 | 0 / 0 | No finding for the `seamless_process_line()` global-buffer overflow. |
| CVE-2018-20534 / libsolv | overrun write | 0 / 0 | 0 / 0 | 0 / 0 | No finding for the disputed test-suite illegal access. |
| CVE-2018-5205 / Irssi | format string | 0 / 0 | 0 / 0 | 0 / 0 | No finding; the known fault is an incomplete-escape out-of-bounds read, not tainted format text. |
| CVE-2019-11072 / lighttpd | arithmetic | 25 / 27 | 25 / 27 | 136 / 110 | Vulnerable and patched findings are identical and do not enter `burl.c`; current-only `burl.c` alerts cannot validate the original CVE. |
| CVE-2019-13115 / libssh2 | arithmetic | 15 / 3 | 3 / 3 | 4 / 2 | All findings land in `misc.c`, not the vulnerable `kex.c` path; the vulnerable-only count increase is unrelated noise. |
| CVE-2019-15296 / FAAD2 | overrun write | 0 / 0 | 0 / 0 | 0 / 0 | No finding for the `faad_resetbits()` buffer overflow. |
| CVE-2019-15945 / OpenSC | overrun write | 0 / 0 | 0 / 0 | 0 / 0 | No finding for `decode_bit_string()`'s out-of-bounds access. |
| CVE-2019-5052 / SDL_image | arithmetic | 0 / 0 | 0 / 0 | 0 / 0 | No finding despite a directly relevant PCX allocation integer overflow. |

The exact counts, fault-site labels, fault-file checks, and query IDs are in
[`remaining-case-summary.tsv`](remaining-case-summary.tsv). They can be
regenerated from the preserved SARIF and tracked report with:

```bash
python3 query-effectiveness/summarize-remaining.py \
  >query-effectiveness/remaining-case-summary.tsv
```

Run the command from the `run-system-10-2026-08-24` evidence directory.

## Query-level diagnosis

### `cpp/overrun-write`

This query is assigned to nine CVEs including libarchive. Across 54 successful
analyses it emits zero results. Its implementation is substantially narrower
than its CVE assignments: it requires product flow between a heuristic
allocation's simple size expression and a modeled array-function write whose
size exceeds the allocation by a computed constant delta. Several assigned
CVEs are reads or invalid dereferences, and even the true write-overflow cases
do not necessarily have this allocation/write shape.

### `cpp/tainted-format-string`

Across fmtlib, jhead, and Irssi, only jhead emits results—seven paths to an
unrelated command-line-controlled `sprintf()` format argument. The query is
specifically taint flow from a recognized external source to a printf-family
format argument. It cannot detect a literal but invalid format specifier, an
undersized formatted-output destination, or an escape-parser out-of-bounds
read merely because those faults were labeled CWE-134.

### `cpp/tainted-arithmetic`

This query emits all 649 generic findings in the remaining set, spread across
five CVEs; SDL_image emits none. Result volume does not correlate with the
known faults. Vulnerable and patched counts are identical for memcached,
libgit2, libpng, and lighttpd. Libssh2 has a vulnerable-only count increase in
`none` mode, but every result is in `misc.c`, while the repair is in `kex.c`.
The query's low-precision, broad taint-to-arithmetic model creates many review
leads without providing CVE identity or variant discrimination.

### CVE-specific zlib location query

The custom query is a useful analysis-pipeline positive control, but its only
predicate is the filename `crc32.c`. It accounts for the collection's sole
“almost found” classification and should not be included in a detector success
rate.

## Implications for the test design

The six-database matrix and preserved SARIF are useful; they exposed the
failure clearly. The weak point is treating a broad CWE query as a CVE query.
Future acceptance should require, for each CVE:

1. a source-level oracle naming the vulnerable operation and repair;
2. a query result whose primary location or path reaches that operation;
3. vulnerable-to-patched discrimination within at least one build mode; and
4. an explicit explanation when current-source results represent a different
   issue rather than persistence of the CVE.

Until a query passes those checks, its output should be labeled a generic
candidate search, not a CVE detection result.

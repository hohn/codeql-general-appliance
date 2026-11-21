# cgasi — CodeQL generic appliance: SARIF ingestor

`cgasi` turns downloaded MRVA result archives into one cumulative, queryable
DuckDB database. It is a CGAST-aware front end to
[`sarif-ingest`](../../sarif-ingest/): every SARIF is converted to an individual
SQLite database with `srfi tolite`, then all recorded SQLite inputs are combined
with `srfi toduck`.

Every command reads one CGAST object from stdin, merges its state, and writes
the result to stdout. Human and query output goes to stderr, so `cgasi` composes
with the other `cga*` filters.

## Named ingestion

```sh
cgasi ingest --name bob-1 [--output-dir DIR]
cgasi ingest --name eve-1 [--output-dir DIR]
cgasi verify bob-1 eve-1
```

`ingest` reads the named entry from `cgamr-submissions`, requires a successful
submission with downloaded result archives, and then:

1. extracts `results.sarif` from every archive;
2. creates one SQLite database per SARIF;
3. stores the submission's user on every result row;
4. records the submission, session, user, language, query pack, and an explicit
   per-job record in `cgasi-ingestions`; each job carries its repository,
   status, finding count, MRVA result count, artifact size, and archive/SARIF/
   SQLite paths;
5. rebuilds the single cumulative `cgasi-db` DuckDB from every recorded
   ingestion, across all users.

If `--output-dir` is omitted, the first ingest creates an anonymous directory
under `cga-tmp/` and records it as `cgasi-root`. Later ingests reuse that root.
An explicit shared directory is useful for a repeatable workflow such as
[`../sample-05/`](../sample-05/README.md).

The cumulative `sarif_results` table has these columns:

```text
user, file_name, kind, rule_id, rule_name, uri,
start_line, start_column, result_json
```

`user` is the MRVA identity recorded by `cgamr`, so queries can isolate one user
even though `cgasi-db` is cumulative:

```sql
select user, rule_id, uri, start_line
from sarif_results
where user = 'bob';
```

## Commands

```sh
cgasi ingest --name NAME             # named archive -> SQLite -> cumulative DB
cgasi verify [NAME ...]              # verify files, schemas, and row totals

cgasi tolite FILE.sarif [OUT]        # low-level SARIF -> SQLite
             [--user USER]
cgasi toduck OUT [A.sqlite ...]      # low-level SQLite -> cumulative DuckDB

cgasi keys                           # list result columns
cgasi values user                    # list distinct values of one column
cgasi list [N]                       # list the first N result rows
cgasi search [key value ...]         # exact-match search, including user
cgasi sql [--query-file FILE]        # execute read-only SQL from cgasi-query
cgasi view [--erc 10|40|100]         # set the Findings view (rows + filters)
           [--user RE] [--rule RE] [--kind RE]
           [--uri RE] [--line RE] [--clear]
cgasi info                           # cumulative database summary
cgasi serve                          # serve live /overview and /detail fragments
```

The lower-level `tolite` command records its outputs in `cgasi-sqlites`.
`toduck` uses explicit inputs when supplied, or that recorded list otherwise.
Only `toduck` and the named `ingest` workflow write `cgasi-db` because that key
always denotes a cumulative DuckDB.

`sql` opens DuckDB read-only. The query path is supplied with `--query-file` or
carried in the CGAST as `cgasi-query`.

`view` drives the `/detail` Findings table from the CGAST (`cgasi-view`), so the
control lives in Python rather than the page. `--erc` chooses how many entry
rows to show (10, 40, or 100; default 10). Each
`--user/--rule/--kind/--uri/ --line` value is a regular expression that filters
that column (partial match, so `.` matches any non-empty value); an empty value
or `--clear` removes a filter. With no filters the table shows all findings, up
to the ERC.

## CGAST keys

| Key                | Meaning                                                |
| ------------------ | ------------------------------------------------------ |
| `cgasi-db`         | cumulative DuckDB across every recorded user/ingestion |
| `cgasi-ingestions` | named submissions with explicit per-job provenance     |
| `cgasi-root`       | shared ingestion output directory                      |
| `cgasi-active`     | most recently ingested submission                      |
| `cgasi-sqlites`    | outputs accumulated by the low-level `tolite` command  |
| `cgasi-query`      | SQL text file used by `sql`                            |
| `cgasi-view`       | Findings view: `erc` plus per-column regex `filters`   |

## Serve contract

`cgasi serve` starts an HTTP server (default port `8606`, override with
`CGA_CGASI_PORT`) exposing `/overview`, `/detail`, `/healthz`, and the standard
route index. The fragments re-read the session CGAST on every request.
`/overview` shows the cumulative database, ingestion count, users, and result
count. `/detail` separates the per-ingestion provenance from the Findings table.
The Findings table is driven by `cgasi-view` (see `cgasi view`): an entry-row
count `<select>`, a per-column regex filter row (`user`, `rule`, `kind`, `uri`,
`line`), the matching rows up to the ERC, and an **apply** button. The model and
control still live in the CGAST — the page is only a view. Filling the fields
and clicking apply simply assembles the equivalent `cgasi view …` command and
sends it to the `cgamx cmd` server (`POST /run`), which runs it as a CGAST
filter over the shared session. This is identical to typing that `cgasi view`
command in the shell. So that unapplied input is never lost, the periodic page
refresh updates the overview fragments only; use the page's reload button (or an
overview click) to refresh the detail after applying. A successful SARIF input
may contain zero problem/path-problem findings; in that case the Findings
section says so instead of rendering a misleading table row.

`cgasi` itself is standard-library only. Conversion requires Python and the
repository's `sarif-ingest/bin/srfi`; cumulative conversion and querying also
require the `duckdb` CLI.

Structured consumers such as CGA Bench reuse `cgasi.store.selection_sql` for the
exact-match search query and `query_page` for a read-only result table.
`query_page` returns rows, column names (even for empty results), total count,
and pagination metadata. It accepts one SELECT/CTE, normalizes it with DuckDB's
SQL parser, opens the database in read-only/safe mode without initialization
files or external access, and applies a 15-second timeout per query operation.
Existing `search`, `sql`, and regex-based `view` CLI behavior is unchanged.

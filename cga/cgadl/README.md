# cgadl — CodeQL generic appliance: DB library handler

`cgadl` is a **consumer** of a prebuilt CodeQL database catalogue: an SQLite index
(`metadata.sql`) where every row describes one CodeQL database and carries a
`result_url` for retrieval.

`cgadl` never builds or repairs the catalogue — construction belongs to
[CGA preparation](../README-prep.md). `cgadl` only reads it, lets a
human or an LLM select a subset, persists that subset to a small JSON file, and
downloads the selected databases into the on-disk layout the rest of MRVA
expects.

Every `cgadl` command is a **CGAST filter** (see the
[cga README](../README.md#state)): it reads the cga struct (a JSON object) from
stdin, does its work, and writes the merged CGAST to stdout. Human output goes
to stderr; there are no default state paths — inputs and outputs travel in the
CGAST as anonymous temp files under `cga/cga-tmp/`.

## Semantics

1. **Get the catalogue.** Pull `metadata.sql` from a URL or a local path; the
   temp copy is recorded in the CGAST as `cgadl-metadata`:

   ```sh
   echo '{}' | cgadl getmeta https://hohnlab.org/.../metadata.sql   # or a path
   ```

2. **Get a list of DB URLs.** Three ways, from most guided to most powerful.
   Inspection commands print to stderr and pass the CGAST through unchanged;
   `select` / `sql` record the result as `cgadl-selection`:

   ```sh
   cgadl keys                       # the catalogue keys (searchable columns)
   cgadl values primary_language    # distinct values of one key
   cgadl list 10                    # human view of the first 10 databases

   cgadl select --user bob primary_language cpp            # simplified select
   cgadl sql --user bob --query-file query.sql              # raw read-only SQL
   ```

   `select` (and `sql`) write a **selected-for-download** JSON temp file. The
   `--user` attribution is also appended to `cgadl-history`, so later users do
   not erase earlier selections in the views. The file is
   deliberately simple: an envelope plus one full catalogue row per selected
   database, so `download` has the `result_url` and `cgadl/detail` can show
   owner / repo / language / size / URL.

3. **Download the selected databases.**

   ```sh
   cgadl download                   # fetch every URL in the selection
   ```

   Each database lands under a `cgadl-dbdir` temp directory, in the **qldbstore
   layout** used by `cgamr`, `mrvacommander`, and the system tests:

   ```
   <dbdir>/<owner>/<repo>/<owner>_<repo>_db.zip
   ```

   Existing files are verified against the catalogue SHA-256 when present and
   skipped (use `--force` to refetch, `--dry-run` to preview). Failed transfers
   retain `.part` files; HTTP(S) downloads with catalogue hashes resume them
   using Range when supported. A server ignoring Range restarts that archive
   safely. Completed transfers are length/hash checked before publication.
   Corrupt completed archives are errors; use `--force` to replace them.
   These databases also supplement the system-tests fixtures.

   Progress on stderr includes completed/total archives and periodically updated
   byte counts for the current transfer. Normal `cga dl download` workflow
   recording forwards this progress immediately while retaining its transcript.

4. **Serve the views.** `cgadl serve` exposes the `/overview` and `/detail`
   fragments for the composite cga page, rendered live from the session CGAST
   (`cga-tmp/session.json`). `/overview` summarises the catalogue and the
   accumulated selections; `/detail` renders all selected databases with
   `user` as its first column.

## Commands

```sh
cgadl getmeta <url|path>       # fetch metadata.sql        -> cgadl-metadata
cgadl keys    [--metadata P]   # catalogue keys (searchable columns)
cgadl values <key>             # distinct values of one key
cgadl list [N]                 # list the first N databases (default 10)
cgadl select [--user U] [key value ...] # selection + history
cgadl sql [--user U] [--query-file F]   # read-only SQL + history
cgadl download [--output-dir D] # download selected DBs     -> cgadl-dbdir
cgadl info                     # high-level info (text, stderr)
cgadl serve                    # serve /overview and /detail fragments
```

Every read command resolves the catalogue from the CGAST `cgadl-metadata` key
(or a one-off `--metadata` argument, which is also recorded into the CGAST).

## CGAST keys

| Key               | Written by         | Meaning                           |
| ----------------- | ------------------ | --------------------------------- |
| `cgadl-metadata`  | `getmeta`          | catalogue (SQLite `metadata.sql`) |
| `cgadl-query`     | `sql --query-file` | SQL text file for `sql`           |
| `cgadl-selection` | `select` / `sql`   | selected-for-download JSON        |
| `cgadl-dbdir`     | `download`         | directory holding the fetched DBs |
| `cgadl-history`   | `select` / `sql`   | user-scoped selection provenance  |

Without `--output-dir`, `download` creates an anonymous directory under
`cga-tmp/`. An explicit destination is useful when another process owns and
serves a qldbstore tree, as in [`../sample-05/`](../sample-05/README.md).

Ports remain env-configurable: `CGA_CGADL_PORT` (default `8602`) for `serve`.

## Layout

The executable lives under `bin/` and the logic lives in a sibling library
package. `db-collection.global/metadata.sql` links to the bundled global
catalogue in the same directory:

```
cgadl/
  bin/cgadl                 POSIX entry point (thin launcher)
  cgadl/                    library package
    cli.py                  CGAST filter: argument parsing + command dispatch
    catalog.py              read-only metadata.sql access
    selection.py            the selected-for-download JSON file
    download.py             getmeta + database downloads (qldbstore layout)
    serve.py                /overview and /detail fragments (session-live)
  db-collection.global/     metadata.sql (symlinked local-path source for getmeta)
```

The catalogue schema (`metadata` table) has one row per database:
`content_hash`, `build_cid`, `git_branch`, `git_commit_id`, `git_owner`,
`git_repo`, `ingestion_datetime_utc`, `primary_language`, `result_url`,
`tool_name`, `tool_version`, `projname`, `db_file_size`.

New selections qualify `git_repo` with the full database-bundle `content_hash`:
`UPSTREAM_REPOSITORY-SHA256`. Already-qualified identities are unchanged. This
permits multiple versions/modes of one upstream repository without archive path
or MRVA request collisions. The source SQLite catalogue and old recorded
selection files are not rewritten; their original names remain readable.

`cgadl` is standard-library only (no external dependencies), matching the rest
of the cga skeleton.

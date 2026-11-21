# cgaql — CodeQL generic appliance: query library handler

`cgaql` is the **query-library** handler for the cga appliance. It mirrors
[`cgadl`](../cgadl/README.md) (the DB-library handler), but over a catalogue of
CodeQL _queries_ instead of databases:

1. **index** a tree of `.ql` files into a small on-disk SQLite catalogue,
2. **select** a subset of queries into a JSON file (exact-match or raw SQL),
3. **pack** the selected queries into CodeQL pack bundles for
   [`cgamr`](../cgamr/README.md).

The query source is a tree of `.ql` files, e.g. the repo's
[`sample-query/`](../../sample-query) tree. Each query's `@id` / `@name` /
`@description` / `@kind` / `@problem.severity` header and its language (the bare
`import <lang>` line) are parsed into the catalogue.

Every `cgaql` command is a **CGAST filter** (see the
[cga README](../README.md#state)): it reads the cga struct (a JSON object) from
stdin, does its work, and writes the merged CGAST to stdout. Human output goes
to stderr; there are no default state paths — the index, selection and packs
travel in the CGAST as anonymous temp files under `cga/cga-tmp/`.

## Commands

```sh
cgaql index <DIR>             # scan the .ql source tree     -> cgaql-index
cgaql keys                    # catalogue keys (searchable columns)
cgaql values <key>            # distinct values of one key
cgaql list [N]                # list the first N queries (default 10)
cgaql select [--user U] [key value ...] # selection + user history
cgaql sql [--user U] [--query-file F]   # read-only SQL + user history
cgaql pack                    # bundle every selected query  -> cgaql-pack (array)
cgaql clean                   # remove the cached pack bundles
cgaql info                    # high-level info (text, stderr)
cgaql serve                   # serve /overview and /detail fragments
```

`index` must be run first; every other read command opens that index read-only.
`select` and `sql` write the active selection JSON and append its `--user`
attribution to `cgaql-history`; therefore a later user's selection does not
erase earlier rows in `/detail`. `pack` reads the active selection and builds one
CodeQL pack bundle per selected query into its own anonymous temp file, and
records their paths as a JSON array under `cgaql-pack`. Bundles are built
using `codeql pack install` then `codeql pack bundle`, so `cgamr` can submit
them directly. With exactly one selected query, `pack --output FILE` writes to
an explicit destination and records that path instead. `clean` unlinks
the `cgaql-pack` bundles and drops the key.

Pack dependencies use the exact `codeql/<language>-all` version shipped in the
CodeQL bundle containing the selected CLI. This keeps builds reproducible and
prevents an older CLI from selecting a newer, unreadable registry manifest.
Install the full CodeQL bundle rather than a bare CLI. An exact-version escape
hatch is available as `CGA_CGAQL_<LANGUAGE>_DEP_VERSION` (for example,
`CGA_CGAQL_CPP_DEP_VERSION=6.1.4`) when an operator intentionally supplies the
library pack through another mechanism.

The shared `pack.initialize_pack` helper writes the same pinned manifest into
a persistent directory and refuses to overwrite an existing `qlpack.yml`.
`cga bench` reuses it for user query workspaces; temporary bundle construction
and editable workspaces therefore share dependency resolution.

### Example

```sh
# thread the CGAST through a variable (piping is optional)
st=$(echo '{}' | cgaql index ../sample-query)
st=$(echo "$st" | cgaql select --user bob language cpp)
st=$(echo "$st" | cgaql pack)                     # -> cgaql-pack: [ ... .tgz ]

# or drive it with SQL from a file:
printf "SELECT * FROM queries WHERE severity='error'" > sel.sql
st=$(echo "$st" | cgaql sql --query-file sel.sql)
```

## Serve contract

`cgaql serve` starts an HTTP server (default port `8603`, override with
`CGA_CGAQL_PORT`) exposing `/overview`, `/detail`, `/healthz`, and a `/` JSON
route index. It renders live from the session CGAST (`cga-tmp/session.json`):
`/overview` summarises the catalogue, accumulated selections and cached packs;
`/detail` lists them with `user` as the first column. Fragments share the
standard cga envelope.

## CGAST keys

| Key               | Written by         | Meaning                            |
| ----------------- | ------------------ | ---------------------------------- |
| `cgaql-querydir`  | `index`            | `.ql` source tree that was scanned |
| `cgaql-index`     | `index`            | persisted SQLite catalogue         |
| `cgaql-query`     | `sql --query-file` | SQL text file for `sql`            |
| `cgaql-selection` | `select` / `sql`   | selected-for-pack JSON             |
| `cgaql-pack`      | `pack`             | JSON array of pack-bundle `.tgz`   |
| `cgaql-history`   | `select` / `sql`   | user-scoped selections and packs   |

Ports remain env-configurable: `CGA_CGAQL_PORT` (default `8603`) for `serve`,
and `CGA_CGAQL_CODEQL` (default `codeql`) selects the binary `pack` shells out
to.

## Layout

Following the cgadl convention, the executable lives under `bin/` and
the logic lives in a sibling library package:

```
cgaql/
  bin/cgaql        POSIX entry point (thin launcher)
  cgaql/           library package
    catalog.py     scan .ql -> SQLite index; read-only keys/values/list/select/sql
    selection.py   the selected-for-pack JSON file
    pack.py        codeql pack install + bundle -> one .tgz per query
    serve.py       /overview and /detail fragments (session-live)
    cli.py         CGAST filter: argument parsing + command dispatch
```

`cgaql` is standard-library only (it shells out to `codeql` for `pack`). The
index, selection and packs live under `cga/cga-tmp/` (gitignored).

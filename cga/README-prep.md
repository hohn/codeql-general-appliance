# CGA preparation

The preparation tools are the part of the `cga/` collection that produces the
inputs the selection side can run. They turn CVE specifications into source work
items, CodeQL database archives plus a catalogue, and a query directory. They do
not select an analysis or submit one to MRVA. They keep their own preparation
session, ports, and web page, and hand their outputs to the analysis tools
(`cgadl`, `cgaql`) explicitly.

The four input-preparation commands are JSON-in/JSON-out filters with their own preparation state:

```text
cgacv -> cgasp -> cgadb
                  -> cgaqg
```

For guided database preparation use [`cga a d`](cgaassist/README.md): `fetch`,
`build`, `index`, and `export`. It orchestrates the plumbing below in a recorded
preparation workflow. `fetch`/`build --use-llm` enables executing recipe
supervision and retained repair attempts. Ordinary source versions do not
require CVE specifications.

## Command reference

### Orchestration

| Command                      | Purpose                                                                                             |
| ---------------------------- | --------------------------------------------------------------------------------------------------- |
| `./cga/cga-prep-run`         | Same as `start`.                                                                                    |
| `./cga/cga-prep-run start`   | Seed the session if absent, start all four component servers, and serve the dashboard on port 8500. |
| `./cga/cga-prep-run all`     | Alias for `start`.                                                                                  |
| `./cga/cga-prep-run status`  | Report whether the dashboard and component servers are running.                                     |
| `./cga/cga-prep-run stop`    | Stop processes recorded under `cga/.run-prep/`.                                                     |
| `./cga/cga-prep-run seed`    | Replace the preparation session with the bundled CVE-2016-9843 dry-run pipeline.                    |
| `./cga/cga-prep-run outputs` | Print absolute paths for the generated database catalogue, database directory, and query directory. |

### `cgacv` — CVE specifications

| Command                       | Consumes                               | Produces or performs                                                           |
| ----------------------------- | -------------------------------------- | ------------------------------------------------------------------------------ |
| `cgacv import SPEC`           | Versioned CVE JSON file                | Validates, normalizes, and stores `cgacv-spec`.                                |
| `cgacv validate [SPEC]`       | Supplied file or current specification | Checks the document without changing the selection.                            |
| `cgacv select [--cve CVE-ID]` | `cgacv-spec`                           | Selects all CVEs or one CVE and writes `cgacv-selection`.                      |
| `cgacv expand`                | `cgacv-selection`                      | Creates vulnerable, patched, and most-recent work items in `cgacv-work-items`. |
| `cgacv info`                  | Current state                          | Prints stored CVE artifact paths.                                              |
| `cgacv serve`                 | Session file                           | Serves its dashboard fragment on port 8501.                                    |

### `cgasp` — source preparation

| Command                                            | Consumes                          | Produces or performs                                                                    |
| -------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------- |
| `cga src-prep plan [--manifest FILE]`              | Source manifest or CVE work items | Writes the Git, tar/ZIP, or Debian acquisition plan to `cgasp-plan`.                    |
| `cga src-prep fetch [--manifest FILE] [--use-llm]` | Manifest, plan, or work items     | Fetches/extracts source trees, resolves commits and hashes, and writes `cgasp-sources`. |
| `cgasp info`                                       | Current state                     | Prints plan and source-result paths.                                                    |
| `cgasp serve`                                      | Session file                      | Serves its dashboard fragment on port 8502.                                             |

### CodeQL database preparation

| Command                                      | Consumes                            | Produces or performs                                                                 |
| -------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------ |
| `cga codeql check`                           | Toolchain requirements              | Records CodeQL version, platform, and required pack hashes in `cgacodeql-check`.     |
| `cga db plan`                                | `cgasp-sources`                     | Writes one immutable job per source × mode and records `cgadbplan-jobs`.             |
| `cga db build --job FILE --trace\|--bm-none` | One job                             | Builds and bundles exactly one database and appends one item to `cgadb-records`.     |
| `cga db zip --db-dir DIR --output FILE`      | Existing CodeQL database            | Creates a ZIP archive without rebuilding or uploading the database.                  |
| `cga db validate query`                      | `cgadb-records`                     | Runs one query against selected built databases and writes `cgadbvalidate-results`.  |
| `cga catalog create`                         | Build and validation records        | Writes a generated SQLite catalogue and manifest.                                    |
| `cga catalog merge`                          | Generated plus preserved catalogues | Verifies and merges records into the final catalogue and manifest.                   |
| `cga catalog verify`                         | Catalogue and manifest              | Rechecks hashes, records, repository equality, and archives.                         |
| `cga catalog export DIRECTORY`               | Verified catalogue and manifest     | Publishes ZIPs, relocated `metadata.sql`, and manifest into a new serving directory. |

Built database identities use the upstream repository name plus the full bundle
SHA-256. Version, mode, and build-repair details remain provenance.
`cga db build --use-llm` supervises dependency/build discovery without weakening
trace checks. `db-build`, `db-plan`, and `db-validate` are compatibility
aliases, not separate builders; use `cga db ...` in new workflows.

The `cgadb serve` executable entry point remains internal to the preparation
dashboard on port 8503. It is not part of the public `cga db` command family.

### `cgaqg` — query generation

| Command                                | Consumes                    | Produces or performs                                          |
| -------------------------------------- | --------------------------- | ------------------------------------------------------------- |
| `cgaqg materialize [--output-dir DIR]` | CVE work items or selection | Copies or writes query definitions and sets `cgaqg-querydir`. |
| `cgaqg index`                          | `cgaqg-querydir`            | Builds the SQLite query index in `cgaqg-index`.               |
| `cgaqg info`                           | Current state               | Prints materialized-query and index paths.                    |
| `cgaqg serve`                          | Session file                | Serves its dashboard fragment on port 8504.                   |

The component commands read a CGAST JSON object from standard input and emit the
updated object to standard output, so they compose as filters:

```sh
state='{}'
state=$(printf '%s' "$state" | cga cve import spec.json)
state=$(printf '%s' "$state" | cga cve select)
state=$(printf '%s' "$state" | cga cve expand)
state=$(printf '%s' "$state" | cga src-prep plan)
state=$(printf '%s' "$state" | cga src-prep fetch)
state=$(printf '%s' "$state" | cga db plan \
  --mode trace --output-dir jobs)

for job in jobs/*.json; do
  [ "$(basename "$job")" = jobs.json ] && continue
  state=$(printf '%s' "$state" | cga db build \
    --job "$job" --trace --output-dir databases)
done

state=$(printf '%s' "$state" | cga catalog create \
  --output metadata.sql --manifest manifest.json)
state=$(printf '%s' "$state" | cga query-gen materialize)
state=$(printf '%s' "$state" | cga query-gen index)
```

`cga-prep-run start` seeds all four panels with a network-free dry run of the
bundled CVE-2016-9843 sample. `cga-prep-run seed` recreates that preparation session
explicitly. Run the independent web view at <http://127.0.0.1:8500/>.

The page uses ports 8501 through 8504 for `cgacv`, `cgasp`, `cgadb`, and
`cgaqg`. `CGA_PREP_PAGE_PORT`, `CGA_PREP_CGACV_PORT`, `CGA_PREP_CGASP_PORT`,
`CGA_PREP_CGADB_PORT`, and `CGA_PREP_CGAQG_PORT` override those defaults.
State lives under `cga/cga-prep-tmp/` unless `CGA_PREP_TMPDIR`
or `CGA_PREP_SESSION` says otherwise.

## Service lifecycle commands

Reusable service components sit alongside the input-preparation components:

| Component                            | Lifecycle subcommands                                | Owns                                           |
| ------------------------------------ | ---------------------------------------------------- | ---------------------------------------------- |
| [`cgapg`](cgapg/README.md)           | `init`, `start`, `createdb`, `check`, `stop`, `info` | Private PostgreSQL cluster.                    |
| [`cgadbserve`](cgadbserve/README.md) | `start`, `check`, `stop`, `info`                     | Serve database archives to local MRVA workers. |
| [`cgamrva`](cgamrva/README.md)       | `start`, `check`, `stop`, `info`                     | MRVA server and its workers only.              |

Each tree exposes its executable under `bin/`. These are CLI filters using
the shared CGAST JSON protocol, not a separate preparation-state type. They preserve
unrelated keys and keep their service state under their component name.
They do not select queries, rebuild CodeQL databases, submit analyses, or
reset shared services. The existing four-panel dashboard is unchanged.

Study scripts call these commands in a single numbered sequence: service
preparation, CGA query execution, then service finalization. See the
[zlib baseline](analysis/CVE-2016-9843/query-010/README.md).

Run lifecycle tests with `python3 -m unittest discover -s cga/tests -v`
from the repository root.

## Explicit handoff to CGA

After preparation, `./cga/cga-prep-run outputs` prints the absolute paths CGA
needs. Load those artifacts into a separate CGA session explicitly:

```sh
cgadl getmeta /absolute/path/to/metadata.sql
cgadl select
cgadl download

cgaql index /absolute/path/to/queries
cgaql select
cgaql pack
```

The CGA preparation state contains `cgadb-records`, `cgacatalog-catalog`,
`cgacatalog-manifest`, and `cgaqg-querydir`;
it never writes `cgadl-*` or `cgaql-*` chooser state.

The CVE preparation samples are in [`examples/cves/`](examples/cves/).

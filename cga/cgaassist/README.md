# Bash-first assistance: the SQLite toy

Follow
[codeql-dataflow-sql-injection](https://github.com/hohn/codeql-dataflow-sql-injection)
from database creation through query authoring to a vulnerable/patched
comparison. `cga assist database-build` (`cga a d`) builds the initial
collection; `cga assist query-writing` (`cga a q`) prepares and publishes the
query. The paired experiment uses CGA's lower-level commands to rebuild the
collection and run it through MRVA.

The completed work is retained outside Git under
`../single-machine-mrva-artifacts/cgaassist/sqlite-toy/`. The commands show how
it was created: reuse existing collections, working trees, and publications
rather than rerunning their creation. To inspect the final result, jump to
[Compare in DuckDB and return later](#compare-in-duckdb-and-return-later). For a
new run, choose an unused `TOY` directory.

## Set up the toy workspace

Install the host dependencies in [INSTALL.md](../../INSTALL.md), including
CodeQL's C++ libraries. This walkthrough uses Bash, `cga`, CodeQL, Clang, Git,
`sqlite3`, `jq`, `unzip`, `patch`, `dpkg-deb`, DuckDB, and PostgreSQL. From the
repository root, define these paths; repeat this block when returning in a fresh
shell:

```sh
REPO="$PWD"
TOY="$(cd .. && pwd)/single-machine-mrva-artifacts/cgaassist/sqlite-toy"
WORK="$TOY/query-writing/.cga/tmp/query-writing/working"
PAIR="$TOY/paired"
ANALYSIS="$PAIR/mrva-analysis"
EXAMPLE="$REPO/cga/cgaassist/examples/sqlite-toy"
BASE=bc7cda527427917e7a68676911c16e7db407c25a
export CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME:-/usr}"
```

`EXAMPLE` points to the tracked query, patch, and SQL fixtures in this checkout.
`BASE` is the toy revision used in the retained run. `/usr` is this Linux host's
CodeQL Java setting; keep your explicit override if different. New sources,
database archives, and results below stay under `TOY`.

## Build a database collection

The toy documents `./build.sh` and needs SQLite headers and libraries. Fetch the
pinned revision and build both extraction modes:

```sh
mkdir -p "$TOY/preparation"
cd "$TOY/preparation"
cga init
cga chain start --name database-build
cga a d fetch \
  --git https://github.com/hohn/codeql-dataflow-sql-injection.git \
  --ref "toy=$BASE" --language cpp --use-llm
cga a d build --mode bm-none --mode trace --use-llm
cga a d index
cga a d export "$TOY/collection"
```

`fetch` records the source commit and tree hash. `build` makes independent
disposable copies; successful jobs are verified and skipped when resumed.
`index` creates and verifies `metadata.sql` and `manifest.json`. `export` copies
both databases and their metadata into `collection/` with local file URLs.
Authoring uses those files directly; the later MRVA run serves its own copy.

The two databases have the same source revision but different extraction modes,
not different vulnerability versions. Each database identity is
`hohn/codeql-dataflow-sql-injection-` followed by its final ZIP's full SHA-256.
Copying/exporting preserves that identity; rebuilding may produce new bytes.

If `collection/` already exists, continue below. For interrupted preparation,
return to `preparation/` and repeat the unfinished phase. Source and build
choices are fixed once jobs are planned; export refuses an existing directory.

### LLM-supervised attempts

Here `--use-llm` lets the supervisor read the toy's human build documentation,
prepare dependencies, and supply the trace build command. In the retained run,
it repaired the missing SQLite dependency by downloading development/runtime
Debian packages, extracting them locally, and generating a build wrapper.

CGA starts supervision before execution and returns failed attempt logs for
repair, up to three attempts by default (`--llm-attempts` changes the bound).
The default runner is `copilot --silent --available-tools= --prompt`, followed
by the task. Its JSON response contains `commands` (argv arrays),
`build_command` (a string or null), and `notes` (a string).
`CGA_PREP_LLM_COMMAND` can replace the runner; its argv is parsed without a
shell and the prompt is appended as one argument.

CGA executes the recipes with the caller's normal permissions, not expanded tool
approvals. Fetch recipes prepare prerequisites; CGA checks out the requested
revision itself. Build recipes operate on disposable sources; compilation runs
under CodeQL. Requests, recipes, command logs, outcomes, and attempt sources
remain under the preparation workflow's `.cga/tmp/database-build/`. Trace mode
still requires intercepted-process evidence; reporting success cannot substitute
for a real traced build.

## Set up query authoring

Start a separate authoring workflow and import the toy catalogue:

```sh
cga a q start "$TOY/query-writing"
cd "$TOY/query-writing"
cga a q catalogue "$TOY/collection/metadata.sql"
cga a q select-databases --rows 1 2
cga a q download
cga a q prepare
```

At the last prompt, choose both displayed, hash-qualified identities. The
working tree at `WORK` contains `Fprintf.ql`, a pinned `qlpack.yml` and
lockfile, the two extracted databases, and `query.code-workspace`.
`editor-databases.json` lists their local directories. These editor inputs are
fixed after preparation.

```sh
code "$WORK/query.code-workspace"
```

In VS Code's **CodeQL Databases** view, add the directories listed in
`editor-databases.json`. Run the starter `Fprintf.ql` against the traced
database: it finds the toy's `fprintf()` calls.

If the authoring workflow already exists, skip `start` and `prepare`. Return
with `cd "$TOY/query-writing"`; `cga state show` and `cga tree show` inspect its
retained state and history.

## Author the injection query

Read the traced database's identity from `metadata.sql`, then locate its
prepared editor directory:

```sh
TRACED_NAME="$(sqlite3 "$TOY/collection/metadata.sql" \
  "SELECT git_owner || '-' || git_repo FROM metadata
   WHERE build_cid LIKE '%--trace--%';")"
TRACED="$(find "$WORK/databases" -mindepth 1 -maxdepth 1 \
  -type d -name "db-*-$TRACED_NAME")"
```

Extract its `src.zip` to inspect `add-user.c`. Skip extraction if
`extracted-source/` is already retained:

```sh
unzip -q "$TRACED/src.zip" -d "$WORK/extracted-source"
find "$WORK/extracted-source" -name add-user.c -print
```

The injection path is stdin `read()` at line 52, through `get_user_info()` and
`write_info()`, into `snprintf()` SQL construction at line 80, then
`sqlite3_exec()` at line 84. Trailing-whitespace removal does not escape SQL.

Leave `Fprintf.ql` unchanged and write `injection.ql` beside it. The completed
[injection.ql](examples/sqlite-toy/injection.ql) uses C++ global taint tracking
from modeled user-input sources to the SQL-text argument of `sqlite3_exec()`.
Copy it from `EXAMPLE`, the fixture directory defined in the setup block:

```sh
cp "$EXAMPLE/injection.ql" "$WORK/injection.ql"
```

Close VS Code before command-line evaluation if its CodeQL extension holds the
database lock. Do not remove the lock file.

```sh
cd "$WORK"
codeql database analyze "$TRACED" injection.ql \
  --format=sarifv2.1.0 --output=injection.sarif \
  --threads=2 --ram=4096 --rerun
```

The retained result has one finding at `add-user.c:84`, with an interprocedural
path from line 52. The display may condense the modeled `snprintf()` step.

## Save drafts and publish

Save this query, not the starter:

```sh
cd "$TOY/query-writing"
cga a q save injection --source "$WORK/injection.ql"
```

This stages the query, support modules, manifest, and lockfile under
`.cga/tmp/query-writing/qlib/injection/` and indexes that draft. Unfinished
drafts are allowed. After editing `working/injection.ql`, repeat the same `save`
command; earlier saved snapshots remain in history.

Publish the verified draft into the toy's permanent query library:

```sh
cga a q publish "$TOY/queries" --name injection
cga ql list
```

Publication checks a private copy with CodeQL's check-only compilation, then
copies and indexes `queries/injection/injection.ql`. It does not copy editor
databases or run the query. Failed compilation leaves the destination unchanged.
If this publication already exists, reuse it; overwriting the package or its
query ID is refused.

## SQLite injection: publish, patch, rebuild, and compare

The published injection query is now the fixed input for a matched experiment:
rebuild both vulnerable and patched sources with the same SQLite dependency, run
the query on all four databases through MRVA, then compare in DuckDB. One
submission selects the entire collection, just as it would for hundreds of
databases. The original `collection/` and editor databases remain unchanged.

The completed builds are retained under `PAIR`, with the MRVA analysis in
`ANALYSIS`. Their creation commands follow; choose unused directories for
another run, or jump to the comparison to inspect the existing MRVA results.

### Patch the toy and prepare the shared dependency

Clone the toy at `BASE`, copy it for the patched revision, and reuse the exact
development/runtime packages acquired in the earlier LLM-supervised trace build.
The manifest records that build's disposable source location. Neither original
sources nor original database archives are modified.

```sh
mkdir "$PAIR"
mkdir -p "$PAIR/sources" "$PAIR/dependencies/packages"
git clone --quiet https://github.com/hohn/codeql-dataflow-sql-injection.git \
  "$PAIR/sources/vulnerable"
git -C "$PAIR/sources/vulnerable" checkout --quiet --detach "$BASE"
cp -a "$PAIR/sources/vulnerable" "$PAIR/sources/patched"

PACKAGES="$(jq -er '.databases[] | select(.mode == "trace") |
  .disposable_source + "/.cga-sqlite/packages"' "$TOY/collection/manifest.json")"
cp "$PACKAGES"/libsqlite3-{0,dev}_*.deb "$PAIR/dependencies/packages/"
for archive in "$PAIR/dependencies/packages/"*.deb; do
  dpkg-deb --extract "$archive" "$PAIR/dependencies/root"
done

cp "$EXAMPLE"/{sources.json,environment.sh,bind-parameters.patch} "$PAIR/"
patch --directory="$PAIR/sources/patched" -p1 < "$PAIR/bind-parameters.patch"
cd "$PAIR"
sha256sum bind-parameters.patch dependencies/packages/*.deb > inputs.sha256
source ./environment.sh
```

This run uses native ARM64 SQLite `libsqlite3-dev` and `libsqlite3-0`
`3.54.1-1`, shared by all four builds. `environment.sh` supplies the extracted
headers/libraries through `CPATH`, `LIBRARY_PATH`, and `LD_LIBRARY_PATH`,
including for `bm-none` extraction. It fails if the dependency is missing. On
another host, supply matching native development/runtime packages rather than
reusing ARM64 packages. The original host's CodeQL Java default is `/usr`; an
explicit `CODEQL_JAVA_HOME` is preserved.

The [patch](examples/sqlite-toy/bind-parameters.patch) replaces SQL
interpolation with `sqlite3_prepare_v2("INSERT INTO users VALUES (?, ?)")`,
`sqlite3_bind_int()`, `sqlite3_bind_text(..., SQLITE_TRANSIENT)`, and
`sqlite3_step()`. It checks errors and finalizes the statement. The patched tree
is a local patch on `BASE`, not a claimed new upstream commit; CGA hashes both
source trees and retains the patch reference in the build records.

### Build both revisions in both modes

```sh
cd "$PAIR"
source ./environment.sh
cga init
cga chain start --name sqlite-injection-pair
cga sp adopt --manifest sources.json
cga db plan --mode bm-none --mode trace --output-dir jobs

cga db build --job jobs/sqlite-toy-vulnerable--none.json \
  --bm-none --output-dir databases
cga db build --job jobs/sqlite-toy-vulnerable--trace.json \
  --trace --output-dir databases
cga db build --job jobs/sqlite-toy-patched--none.json \
  --bm-none --output-dir databases
cga db build --job jobs/sqlite-toy-patched--trace.json \
  --trace --output-dir databases
```

The source manifest supplies `bash ./build.sh` for trace mode. All jobs use the
same dependency prefix and independent disposable source copies. `bm-none` does
not run the compiler build; the catalogue calls that mode `none`. Trace builds
must have positive intercepted-process evidence. Existing built job IDs are
refused, so use a fresh paired workflow for another experiment.

As an additional runtime check, the patched trace executable was run against an
isolated temporary `users.sqlite` with names `Alice`, `O'Reilly`, and
`Robert'); SELECT 'inert'; --`. All three were inserted literally and the
temporary database was removed; the original toy database was not used.

### Publish the four-database collection

```sh
cga cat create --output index/metadata.sql --manifest index/manifest.json
cga cat verify --catalog index/metadata.sql --manifest index/manifest.json
cga cat export "$PAIR/collection"
cga cat verify \
  --catalog "$PAIR/collection/metadata.sql" \
  --manifest "$PAIR/collection/manifest.json"
cga state export -o "$PAIR/preparation-state.json"
```

The collection has `(vulnerable, patched) x (none, trace)`, with four
hash-qualified identities and local file URLs. The manifest maps those
identities to variant, mode, source hashes, and tracer evidence.

### Run the published query on all four through MRVA

Start a separate analysis workflow. Import the four-database catalogue and the
published query, select every database, and build one query pack:

```sh
cga init "$ANALYSIS"
cd "$ANALYSIS"
export CGAST_TMPDIR="$ANALYSIS/.cga/tmp/artifacts"
cga chain start --name sqlite-injection-mrva
cga dl getmeta "$PAIR/collection/metadata.sql"
cga dl select --user toy
cga dl download --output-dir "$ANALYSIS/qldbstore"
cga ql index "$TOY/queries"
cga ql select --user toy id cpp/toy-sql-injection
cga ql pack
```

Start toy-owned services with a private PostgreSQL cluster and separate ports.
Choose free ports before running this block; these commands refuse occupied
ports rather than stopping another experiment. No shared reset is used.

```sh
export PORT=18081 SERVER_PORT=18081
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55433
export POSTGRES_USER=study POSTGRES_DB=mrvadev
export MRVA_WORK_DIR="$ANALYSIS/runtime/mrva"
export MRVA_TMP_DIR="$ANALYSIS/runtime/logs"
export SERVER_LOG="$MRVA_TMP_DIR/server.log"
export MRVA_ENVSIM_AGENT_BINARY="$REPO/agent-commander-argo/mrvaagent"
export MRVA_DB_SERVER_URL=http://127.0.0.1:19080
export CGA_MRVA_SERVER=http://127.0.0.1:18081
export MRVA_STANDALONE_STORAGE=filesystem MRVA_POOL_MAX_WORKERS=2

cga pg init --data-dir "$ANALYSIS/runtime/pgdata" \
  --bin-dir "$(pg_config --bindir)" --port "$POSTGRES_PORT" --user "$POSTGRES_USER"
cga pg start
cga pg createdb "$POSTGRES_DB"
cga ds start --directory "$ANALYSIS/qldbstore" \
  --port 19080 --log "$ANALYSIS/runtime/archives.log"
cga mx build
cga ms start --binary "$REPO/server-commander/mrvaserver"
cga pg check
cga ds check
cga ms check
```

Submit once, wait for completion, and retrieve all four result archives:

```sh
cga mr run --name sqlite-injection --user toy --language cpp \
  --output-dir "$ANALYSIS/downloads" --log-dir "$ANALYSIS/checkpoints"
```

MRVA workers consume the served archives, not the editor databases. The worker
pool schedules the selected collection without a shell loop over databases.
`succeeded` means execution completed, not zero findings. If interrupted,
inspect `cga mr status --name sqlite-injection` and the retained checkpoints;
resume with
`cga mr download --name sqlite-injection --output-dir "$ANALYSIS/downloads"`
after success rather than submitting again.

### Combine the results in DuckDB

```sh
cga si ingest --name sqlite-injection --output-dir "$ANALYSIS/findings"
cga si verify sqlite-injection
cga state export -o "$ANALYSIS/analysis-state.json"
cp "$EXAMPLE"/{compare.sql,locations.sql} "$ANALYSIS/"
```

Named ingestion extracts each SARIF, creates four per-job SQLite inputs, and
combines them into `findings/all.duckdb`. It also records the repository, MRVA
status/count, query pack, and artifacts for every job, including both successful
zero-finding jobs. `verify` checks those artifacts and cumulative counts.

### Compare in DuckDB and return later

For the retained run, first restore the path variables from
[Set up the toy workspace](#set-up-the-toy-workspace) in a fresh shell, then:

```sh
cd "$ANALYSIS"
cga si sql --query-file compare.sql
cga si sql --query-file locations.sql
```

`compare.sql` joins the DuckDB findings to `../collection/manifest.json` and the
named ingestion in `analysis-state.json`. Its explicit four-build matrix retains
zero-finding jobs, flags missing builds/jobs and mismatched
MRVA/ingestion/DuckDB counts, and prints repository, user, session, and query
pack provenance. Keep those JSON files and the ingestion artifacts.

Observed MRVA result with CodeQL 2.27.1 and one published query pack:

| Variant    | Mode  | Status   | Findings |
| ---------- | ----- | -------- | -------: |
| vulnerable | none  | complete |        1 |
| vulnerable | trace | complete |        1 |
| patched    | none  | complete |        0 |
| patched    | trace | complete |        0 |

`locations.sql` shows both vulnerable findings at `add-user.c:84:27`. The fixed
program's bound-parameter behavior was also checked at runtime. This query
covers the toy's `sqlite3_exec()` flow; zero findings are not a general proof
about every SQLite API or other vulnerabilities.

After finishing the submission, stop only this workflow's services:

```sh
cga ms check
cga ms stop
cga ds stop
cga pg stop
cga state export -o "$ANALYSIS/analysis-state.json"
```

The retained services are stopped. Reading the DuckDB comparison later does not
require restarting MRVA, the archive server, or PostgreSQL.

Only the query, patch, manifests/settings, comparison SQL, and these
instructions are kept in Git. Sources, dependency packages, database ZIPs,
SARIF, SQLite, DuckDB, and CGA workflow histories remain in the external
artifact tree.

## Fixed SQLite toy check

To repeat just the initial acquisition/build/export/download check in a new
directory, without the authoring and patch comparison:

```sh
CHECK="$TOY/check-001"
python3 "$REPO/cga/cgaassist/tests/sqlite_toy.py" "$CHECK" --use-llm
```

The check builds both extraction modes, verifies identities and resumption,
exports and briefly serves the collection, downloads into a separate workflow,
and unbundles both databases. It stops its own server. `CHECK/collection/`
retains local file URLs for later authoring; `CHECK/http-collection/` was used
only by the temporary serving check.

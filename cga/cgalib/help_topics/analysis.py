"""Command-specific help for analysis inputs, execution, and evidence."""

from command_help import HelpTopic


STATE_ENV = (
    ("CGAST_ROOT", "Root for relative CGAST paths; takes precedence over CGA_ROOT."),
    ("CGA_ROOT", "Fallback CGAST path root; default is the checkout's cga directory."),
    ("CGAST_TMPDIR", "Managed artifact/scratch directory; takes precedence over CGA_TMPDIR."),
    ("CGA_TMPDIR", "Fallback scratch directory; default <CGAST root>/cga-tmp."),
)
SESSION_ENV = (
    ("CGAST_SESSION", "Live session JSON file; takes precedence over CGA_SESSION."),
    ("CGA_SESSION", "Fallback live session file; default <CGAST root>/cga-tmp/session.json."),
)
MRVA_ENV = (
    ("CGA_MRVA_SERVER", "Server URL; default http://127.0.0.1:8081. --server overrides it."),
    ("CGA_MRVA_CONTROLLER_OWNER", "Controller owner; default octo. --controller-owner overrides it."),
    ("CGA_MRVA_CONTROLLER_REPO", "Controller repository; default ctl. --controller-repo overrides it."),
    ("CGA_MRVA_BEARER_TOKEN", "Optional authentication token; unset by default. --bearer-token overrides it."),
)
PACK_ENV = (
    ("CGA_CGAQL_CODEQL", "CodeQL executable used for packing; default codeql."),
    ("CGA_CGAQL_<LANGUAGE>_DEP_VERSION",
     "Optional exact language-library version, for example CGA_CGAQL_CPP_DEP_VERSION. "
     "Otherwise use the version shipped with the selected CodeQL bundle."),
)
GRAPH_ENV = (
    ("CGA_HISTORY_DIR", "Legacy history directory; defaults the manifest to its manifest.json."),
    ("CGA_TMPDIR", "Without CGA_HISTORY_DIR, find mrva-flow-history/manifest.json here; "
     "default is cga/cga-tmp in the checkout."),
)
EDITOR_ENV = (
    ("CGACC_CODE_SERVER", "Explicit code-server executable, preferred over PATH and the pinned cache."),
    ("XDG_CACHE_HOME", "Installation cache base; default ~/.cache. Releases live under cga/."),
)


TOPICS: dict[tuple[str, ...], HelpTopic] = {
    ("dl",): HelpTopic(
        "select and retrieve prepared CodeQL databases",
        "Read a prebuilt SQLite metadata catalogue, inspect its columns, select databases, "
        "and download their archives in qldbstore layout. This consumer does not build or "
        "repair catalogues. Start with getmeta or --metadata, then select and download. "
        "Use cga for recorded workflow state; the direct cgadl binary remains a JSON-in/"
        "JSON-out CGAST filter with human output on stderr.",
        ("cga dl getmeta /data/catalogue/metadata.sql",
         "cga dl select --user bob primary_language cpp",
         "cga dl download --output-dir /data/qldbstore"),
        STATE_ENV),
    ("dl", "getmeta"): HelpTopic(
        "copy or fetch a database catalogue",
        "Copy an existing local catalogue or fetch its URL into a new managed .sql file "
        "and record cgadl-metadata. The input must be a prepared SQLite metadata "
        "catalogue; this command neither constructs nor validates database archives.",
        ("cga dl getmeta /data/catalogue/metadata.sql",)),
    ("dl", "keys"): HelpTopic(
        "list searchable database catalogue columns",
        "Open cgadl-metadata read-only and print column names to stderr. Run getmeta "
        "first or supply --metadata, which also records that catalogue path in state.",
        ("cga dl keys --metadata /data/catalogue/metadata.sql",)),
    ("dl", "values"): HelpTopic(
        "list distinct values of a database column",
        "Print distinct values for one known catalogue column to stderr. Requires "
        "cgadl-metadata or --metadata; use keys to discover valid column names.",
        ("cga dl keys", "cga dl values primary_language")),
    ("dl", "list"): HelpTopic(
        "preview database catalogue rows",
        "Print the first N databases (default 10) with owner, repository, language, tool "
        "version, archive size, and result URL. Requires getmeta or --metadata. This "
        "preview does not change the active download selection.",
        ("cga dl list 20",)),
    ("dl", "select"): HelpTopic(
        "select databases by exact column matches",
        "Match every supplied key/value pair against the prepared catalogue; no pairs "
        "select all rows. Requires getmeta or --metadata. Write the full matching rows "
        "to a new cgadl-selection JSON file and append --user attribution to "
        "cgadl-history. This replaces the active selection, not earlier history; it "
        "does not download archives.",
        ("cga dl select --user bob primary_language cpp git_owner octo",
         "cga dl download --output-dir /data/qldbstore")),
    ("dl", "sql"): HelpTopic(
        "query the database catalogue with read-only SQL",
        "Read SQL from --query-file (recorded as cgadl-query) or the existing "
        "cgadl-query file, and execute it against cgadl-metadata read-only. Nonempty "
        "results containing result_url become the active cgadl-selection and append "
        "user-scoped history; other results only print to stderr. Use full catalogue "
        "rows when the selection will be downloaded.",
        ("cga dl sql --user bob --query-file database-selection.sql",)),
    ("dl", "download"): HelpTopic(
        "download the active database selection",
        "Requires a nonempty cgadl-selection. Write archives as "
        "<output-dir>/<owner>/<repo>/<owner>_<repo>_db.zip and record cgadl-dbdir; "
        "without --output-dir allocate a managed directory. Existing archives are "
        "verified against catalogue hashes when present and skipped; --force replaces "
        "them. Failed transfers retain .part files, resumable for hashed HTTP(S) "
        "downloads. Length/hash failures exit nonzero. --dry-run reports destinations "
        "without transferring, but still records the destination in state. MRVA must "
        "serve this same database store; archives are not uploaded by submit.",
        ("cga dl download --output-dir /data/qldbstore --dry-run",
         "cga dl download --output-dir /data/qldbstore")),
    ("dl", "info"): HelpTopic(
        "summarize catalogue and active database inputs",
        "Print the catalogue path, row count and keys when available, active selection "
        "count, and download directory to stderr. Missing catalogue state is reported "
        "rather than initialized; --metadata records an explicit catalogue path.",
        ("cga dl info",)),
    ("dl", "serve"): HelpTopic(
        "serve live database-library fragments",
        "Run the component HTTP server until interrupted. /overview summarizes the "
        "catalogue and accumulated selections; /detail includes selections across "
        "users. Routes re-read the shared session CGAST, not a frozen stdin snapshot. "
        "This starts a viewer, not catalogue acquisition or downloads.",
        ("cga dl serve",),
        (("CGA_CGADL_PORT", "HTTP listening port; default 8602."),) + SESSION_ENV),
    ("ql",): HelpTopic(
        "index, select, and bundle CodeQL queries",
        "Scan a .ql source tree into a SQLite catalogue, select queries, and build one "
        "CodeQL pack bundle per selected query for MRVA. Indexing reads query header "
        "metadata and bare language imports; packing requires an installed CodeQL "
        "bundle. Use cga for recorded workflows; direct cgaql remains a CGAST JSON "
        "filter with human output on stderr.",
        ("cga ql index /data/queries", "cga ql select --user bob language cpp",
         "cga ql pack"),
        STATE_ENV + PACK_ENV),
    ("ql", "index"): HelpTopic(
        "index a tree of CodeQL query sources",
        "Recursively scan .ql files, reading header fields such as @id, @kind, and "
        "@problem.severity plus language imports into a new SQLite cgaql-index. "
        "An explicit directory is recorded as cgaql-querydir; otherwise reuse that "
        "state key. This does not compile queries or build packs.",
        ("cga ql index /data/queries", "cga ql list 10")),
    ("ql", "keys"): HelpTopic(
        "list searchable query catalogue columns",
        "Requires cgaql-index from index. Print its column names to stderr without "
        "changing the selection or query sources.",
        ("cga ql index /data/queries", "cga ql keys")),
    ("ql", "values"): HelpTopic(
        "list distinct values of a query column",
        "Requires cgaql-index and a known column name. Print distinct values to stderr; "
        "use keys to discover columns before selecting queries.",
        ("cga ql values language", "cga ql values kind")),
    ("ql", "list"): HelpTopic(
        "preview indexed CodeQL queries",
        "Requires cgaql-index. Print the first N queries (default 10), showing language, "
        "ID, kind, severity, and relative source path. This does not select or pack them.",
        ("cga ql list 20",)),
    ("ql", "select"): HelpTopic(
        "select indexed queries by exact matches",
        "Requires cgaql-index. Match all key/value pairs, or select all rows when no "
        "criteria are supplied. Write a new active cgaql-selection and append --user "
        "attribution to cgaql-history without erasing earlier selections. Run pack "
        "separately to materialize bundles.",
        ("cga ql select --user bob language cpp kind problem", "cga ql pack")),
    ("ql", "sql"): HelpTopic(
        "query the query catalogue with read-only SQL",
        "Requires cgaql-index. Read SQL from --query-file (recorded as cgaql-query) or "
        "the existing query file. Nonempty results containing path replace the active "
        "cgaql-selection and append user history; other results only print to stderr. "
        "Select complete query rows when the result will be packed.",
        ("cga ql sql --user bob --query-file query-selection.sql",)),
    ("ql", "pack"): HelpTopic(
        "build bundles for the selected queries",
        "Requires a nonempty cgaql-selection and a full CodeQL bundle with compatible "
        "language libraries. Build one .tgz per query using codeql pack install and "
        "pack bundle, including sibling .qll support files. Record successful bundles "
        "in cgaql-pack and the active history entry; any build failure exits nonzero. "
        "--output requires exactly one query and overwrites that destination. "
        "--dry-run only reports planned queries and leaves pack state unchanged.",
        ("cga ql select --user bob id cpp/example",
         "cga ql pack --output /data/query.tgz"),
        PACK_ENV),
    ("ql", "clean"): HelpTopic(
        "delete recorded query pack bundles",
        "Unlink bundle files referenced by both active cgaql-pack and historical "
        "cgaql-history packs, including explicitly supplied --output destinations. "
        "Remove the active pack key and historical pack references. Query sources, "
        "index, and selection history remain; run pack to rebuild bundles.",
        ("cga ql info", "cga ql clean")),
    ("ql", "info"): HelpTopic(
        "summarize query sources, index, and bundles",
        "Print the source tree, index path/count/keys, active selection count, and "
        "cached bundle count to stderr. Missing state is reported without indexing "
        "or packing anything.",
        ("cga ql info",)),
    ("ql", "serve"): HelpTopic(
        "serve live query-library fragments",
        "Run the HTTP fragment server until interrupted. /overview summarizes the "
        "index, selections, and bundles; /detail includes user-attributed history. "
        "The server re-reads shared session state on each request and does not index "
        "or build queries.",
        ("cga ql serve",),
        (("CGA_CGAQL_PORT", "HTTP listening port; default 8603."),) + SESSION_ENV),
    ("mr",): HelpTopic(
        "submit, monitor, and retrieve MRVA analyses",
        "Manage named submissions in cgamr-submissions. A submission name is a local "
        "run label; --user is the MRVA request identity, not that label. Prepare a "
        "query pack and databases served by MRVA before submitting. run composes "
        "bounded submit/poll/download/verify with recovery checkpoints; individual "
        "commands allow explicit recovery. Direct cgamr remains a JSON CGAST filter "
        "with monitoring on stderr.",
        ("cga mr run --name bob-1 --user bob --output-dir results --log-dir run-log",
         "cga mr info --name bob-1"),
        STATE_ENV + MRVA_ENV),
    ("mr", "submit"): HelpTopic(
        "submit one query pack against repositories",
        "Create a new named server session and record its ID, identity, connection, "
        "pack, and repositories. Normally requires cgaql-pack, cgadl-selection, and "
        "downloaded qldbstore archives under cgadl-dbdir; --pack-index chooses one "
        "bundle (default 0). Alternatively --pack supplies a prebuilt bundle and "
        "--repos supplies server-resident owner/repo names; --repos requires "
        "--language. Without --language infer exactly one selected database language. "
        "The server must already serve the databases: this does not upload them. "
        "Existing names are rejected; inspect status before any resubmission.",
        ("cga mr submit --name bob-1 --user bob",
         "cga mr submit --name prepared --user bob --pack query.tgz --language cpp --repos octo/a"),
        MRVA_ENV),
    ("mr", "attach"): HelpTopic(
        "track an existing MRVA session without submitting",
        "Fetch status for --session-id using --user and the selected server/controller, "
        "then save the session under a new --name. Requires a reachable existing "
        "session and an unused local name. Later status/download requests reuse its "
        "recorded identity and connection; no new work is submitted.",
        ("cga mr attach --name recovered --user bob --session-id 42",
         "cga mr status --name recovered"),
        MRVA_ENV),
    ("mr", "run"): HelpTopic(
        "submit once, wait, download, and verify",
        "Requires the selected database archives in cgadl-dbdir, a cgaql-pack bundle, "
        "and a server serving those databases. Submit under a new name, poll every "
        "5 seconds by default, then download and verify only after success. The "
        "default polling deadline is 1800 seconds; an in-flight HTTP request may "
        "outlast it. Both intervals must be positive. --log-dir must be absent or "
        "empty: every operation writes input/output state and metadata, plus "
        "latest.state for recovery. On failure/timeout inspect these checkpoints and "
        "resume with status/download; do not repeat run or submit blindly.",
        ("cga mr run --name bob-1 --user bob --output-dir results --log-dir run-log",
         "cga mr status --name bob-1", "cga mr download --name bob-1 --output-dir results"),
        MRVA_ENV),
    ("mr", "status"): HelpTopic(
        "refresh one named submission's status",
        "Requires a recorded submission from submit, run, or attach. Perform one "
        "request (no polling), store the full status response and overall status, "
        "and print per-repository progress to stderr. Explicit connection flags "
        "override recorded server/controller, which take precedence over environment "
        "defaults. Use this to inspect uncertain submission outcomes before recovery.",
        ("cga mr status --name bob-1",),
        MRVA_ENV),
    ("mr", "download"): HelpTopic(
        "retrieve available result archives for a submission",
        "Requires a recorded named submission. Refresh status, request artifact "
        "metadata for each repository, and download available ZIPs as owner-repo.zip "
        "under --output-dir or a new managed directory. Existing destination files "
        "are overwritten. Record downloads and status in the submission. This does "
        "not wait for completion and may retrieve only some results; use verify "
        "after a successful run. Recorded connection defaults are reused.",
        ("cga mr status --name bob-1",
         "cga mr download --name bob-1 --output-dir results", "cga mr verify bob-1"),
        MRVA_ENV),
    ("mr", "info"): HelpTopic(
        "summarize locally recorded MRVA submissions",
        "Print name, user, session ID, last recorded status, repository count, and "
        "download count to stderr. Omit --name to list all records. This does not "
        "contact MRVA or refresh status.",
        ("cga mr info", "cga mr info --name bob-1")),
    ("mr", "verify"): HelpTopic(
        "check successful status and downloaded archive counts",
        "Check the supplied names, or all recorded submissions when omitted. Each "
        "must have recorded status succeeded, at least one repository, and an existing "
        "downloaded file per repository by count. Print PASS/FAIL to stderr and exit "
        "nonzero if any check fails. This does not refresh server status, validate "
        "ZIP contents, or ingest findings.",
        ("cga mr verify bob-1 eve-1",)),
    ("mr", "reset"): HelpTopic(
        "remove local submission tracking state",
        "Forget one --name, or all submission and active-display state when omitted. "
        "This does not cancel server jobs, delete result archives, or remove other "
        "component state. Forgetting a name permits a later submit to create new "
        "work, so inspect existing sessions before resubmitting.",
        ("cga mr info --name bob-1", "cga mr reset --name bob-1")),
    ("mr", "serve"): HelpTopic(
        "serve live MRVA submission fragments",
        "Run the HTTP fragment server until interrupted, rendering named submissions "
        "and active lifecycle information from shared session state. Serving the "
        "view does not submit work or poll the MRVA server.",
        ("cga mr serve",),
        (("CGA_CGAMR_PORT", "HTTP listening port; default 8604."),) + SESSION_ENV),
    ("si",): HelpTopic(
        "ingest and query cumulative SARIF evidence",
        "Convert downloaded named MRVA results into per-job SQLite files and one "
        "cumulative DuckDB, retaining user and job provenance. Conversion requires "
        "the repository's sarif-ingest/bin/srfi; cumulative conversion/querying "
        "requires the duckdb CLI. Low-level tolite/toduck accept standalone inputs. "
        "Direct cgasi remains a JSON CGAST filter; query and diagnostic output goes "
        "to stderr.",
        ("cga si ingest --name bob-1", "cga si verify bob-1", "cga si search user bob"),
        STATE_ENV),
    ("si", "ingest"): HelpTopic(
        "ingest one successful named MRVA submission",
        "Requires a succeeded cgamr-submissions entry with a nonempty user and one "
        "downloaded archive per repository. Extract results.sarif, convert each job "
        "to SQLite with that user, and record explicit job/artifact provenance in "
        "cgasi-ingestions. Rebuild cgasi-db from every recorded ingestion, checking "
        "row totals before replacing all.duckdb. Existing ingestions' SQLite files "
        "must remain available. Reingesting a name replaces that record and its "
        "generated job files, rather than appending duplicate results. --output-dir "
        "sets cgasi-root; otherwise reuse it or allocate a managed directory.",
        ("cga mr verify bob-1",
         "cga si ingest --name bob-1 --output-dir ingested", "cga si verify bob-1")),
    ("si", "tolite"): HelpTopic(
        "convert standalone SARIF to SQLite",
        "Requires an existing SARIF file and sarif-ingest/bin/srfi. Create the "
        "specified SQLite output or replace the SARIF suffix with .sqlite; conversion "
        "can overwrite an existing output. --user tags every result row (default "
        "empty). Append the path to cgasi-sqlites without duplicates. This does "
        "not create a named ingestion or update cumulative cgasi-db.",
        ("cga si tolite results.sarif results.sqlite --user bob",
         "cga si toduck combined results.sqlite")),
    ("si", "toduck"): HelpTopic(
        "combine standalone SQLite results into DuckDB",
        "Combine explicit SQLite inputs, or cgasi-sqlites from tolite when none "
        "are supplied. All input files must exist. Rebuild the output DuckDB, "
        "appending .duckdb unless already present, and record it as cgasi-db. "
        "This can replace an existing database; it does not create named ingestion "
        "provenance. Requires srfi and the duckdb CLI.",
        ("cga si toduck combined first.sqlite second.sqlite",)),
    ("si", "keys"): HelpTopic(
        "list cumulative result columns",
        "Requires cgasi-db from ingest or toduck and the duckdb CLI. Print the "
        "sarif_results columns to stderr without modifying evidence.",
        ("cga si keys",)),
    ("si", "values"): HelpTopic(
        "list distinct values of a result column",
        "Requires cgasi-db and a valid sarif_results column. Print distinct values "
        "to stderr; use keys to discover columns such as user or rule_id.",
        ("cga si values user", "cga si values rule_id")),
    ("si", "list"): HelpTopic(
        "preview cumulative SARIF result rows",
        "Requires cgasi-db and the duckdb CLI. Print the first N result rows "
        "(default 20) to stderr. Successful jobs with zero findings are represented "
        "in named ingestion provenance, not fabricated result rows.",
        ("cga si list 10",)),
    ("si", "search"): HelpTopic(
        "search cumulative results by exact matches",
        "Requires cgasi-db. Match every supplied column/value pair in sarif_results "
        "and print rows to stderr; no pairs return all results. Use the user column "
        "to isolate an MRVA identity. This is exact matching, not the regex-based "
        "Findings view, and it does not change view filters.",
        ("cga si search user bob kind problem",)),
    ("si", "sql"): HelpTopic(
        "query cumulative findings with read-only SQL",
        "Requires cgasi-db and the duckdb CLI. Read SQL from --query-file, recording "
        "the path as cgasi-query, or reuse that key. Execute against DuckDB read-only "
        "and print tabular rows to stderr. This does not export a report, replace "
        "the database, or change Findings view filters.",
        ("cga si sql --query-file findings.sql",)),
    ("si", "info"): HelpTopic(
        "summarize the cumulative evidence store",
        "Print the cumulative database path, named ingestion count, users, result "
        "count/columns when available, and srfi backend path to stderr. This does "
        "not ingest, convert, or refresh MRVA results.",
        ("cga si info",)),
    ("si", "view"): HelpTopic(
        "configure the live Findings table",
        "Update cgasi-view only: --erc sets entry row count (10, 40, or 100; "
        "initial default 10), and --user/--rule/--kind/--uri/--line set partial "
        "regular-expression column filters. Empty values remove individual filters; "
        "--clear clears all filters before applying the supplied options. Omitted "
        "settings are preserved. No server or database is needed to configure "
        "the view, and stored evidence and CLI search results are unchanged.",
        ("cga si view --erc 40 --user '^bob$' --kind problem",
         "cga si view --user ''", "cga si view --clear")),
    ("si", "verify"): HelpTopic(
        "verify named ingestion artifacts and cumulative totals",
        "Verify specified ingestion names or all names when omitted. Check recorded "
        "job artifacts exist, per-job row totals agree, SQLite result schemas carry "
        "the expected user, and cumulative DuckDB rows equal the total across all "
        "ingestions, even when only some names were requested. Print PASS/FAIL and "
        "exit nonzero on any failure. A successful zero-finding job is valid; no "
        "ingestions is an error. This does not repair or rebuild files.",
        ("cga si verify bob-1 eve-1",)),
    ("si", "serve"): HelpTopic(
        "serve live ingestion and Findings fragments",
        "Run the HTTP fragment server until interrupted. /overview summarizes the "
        "cumulative store; /detail separates per-ingestion provenance from the "
        "Findings table configured by si view. Re-read shared session state on "
        "requests. This does not convert or ingest data.",
        ("cga si serve",),
        (("CGA_CGASI_PORT", "HTTP listening port; default 8606."),) + SESSION_ENV),
    ("ex",): HelpTopic(
        "export findings with submission and job provenance",
        "Read cumulative cgasi-db and explicit per-job cgasi-ingestions records to "
        "write human Markdown or structured LLM JSON. Requires ingested evidence "
        "and valid provenance; inconsistent counts or unmappable findings are errors. "
        "Zero-finding jobs remain explicit. Generated files are recorded under "
        "cgaex-exports. Direct cgaex remains a JSON CGAST filter, not report text "
        "on stdout.",
        ("cga si verify", "cga ex human --output report.md",
         "cga ex llm --output report.json"),
        STATE_ENV),
    ("ex", "human"): HelpTopic(
        "write a provenance-aware Markdown report",
        "Requires cumulative cgasi-db, duckdb, and valid named per-job ingestion "
        "provenance. Export the complete store, not just si view filters, with "
        "submission/job summaries including successful zero-finding jobs. Write "
        "--output or a new managed .md file, creating parent directories and "
        "overwriting an existing destination. Record the human artifact and "
        "finding count under cgaex-exports.",
        ("cga ex human --output reports/analysis.md",)),
    ("ex", "llm"): HelpTopic(
        "write structured analysis evidence as JSON",
        "Requires cumulative cgasi-db, duckdb, and valid named ingestion/job "
        "provenance. Write a self-contained cga.analysis-export.v2 document with "
        "summary, submissions, jobs, artifacts, and findings mapped to their "
        "submission/session/repository. Include zero-finding jobs; reject malformed "
        "or inconsistent provenance. Export all findings regardless of view filters. "
        "--output overwrites the destination; otherwise allocate a managed .json "
        "file. Record it under cgaex-exports. No LLM is contacted.",
        ("cga ex llm --output reports/analysis.json",)),
    ("ex", "info"): HelpTopic(
        "list recorded export files and finding counts",
        "Print cgaex-exports paths and finding counts to stderr, or report no "
        "exports. This reads local state without querying findings or generating "
        "new reports.",
        ("cga ex info",)),
    ("ex", "serve"): HelpTopic(
        "serve live export summaries and artifact fragments",
        "Run the HTTP fragment server until interrupted, reading recorded exports "
        "from the shared live session. It does not generate or refresh report files; "
        "run human or llm separately after evidence changes.",
        ("cga ex serve",),
        (("CGA_CGAEX_PORT", "HTTP listening port; default 8608."),) + SESSION_ENV),
    ("dfg",): HelpTopic(
        "inspect legacy whole-CGAST data-flow graphs",
        "Read a numbered-flow history manifest and immutable snapshots without "
        "changing them. DFG nodes are states, annotated with top-level keys added, "
        "updated, or removed relative to their parent; edges identify producing "
        "commands. These are legacy manifests, not current .cga workflows, which "
        "use cga tree show -v. Put format and manifest options before info/show. "
        "Output is graph text on stdout, not a CGAST JSON filter.",
        ("cga dfg --manifest run-history/manifest.json show",
         "cga dfg --render data-flow.pdf show"),
        GRAPH_ENV),
    ("dfg", "info"): HelpTopic(
        "summarize legacy data-flow graph storage",
        "Load the history manifest and report chains, roots, heads, immutable state "
        "counts, snapshot directory, and current-head compatibility-copy path. "
        "--session only overrides the displayed compatibility path, not graph "
        "input. Place --manifest, --session, and --markdown before info; DOT and "
        "render formats apply only to show. No files are modified.",
        ("cga dfg --manifest run-history/manifest.json --markdown info",),
        GRAPH_ENV),
    ("dfg", "show"): HelpTopic(
        "show immutable states and their data changes",
        "Read manifest snapshots and show top-level CGAST key deltas from each "
        "parent, ordered by chain and sequence. Default output is a plain table; "
        "--markdown writes a table, --dot emits DOT with chain clusters and current "
        "head highlighting. --render FILE writes a PDF using Graphviz dot; "
        "--render-user FILE writes dependency-free interactive HTML/SVG. File "
        "outputs create parents, overwrite destinations, and print the path. "
        "All options precede show. Use cga cfg for command-invocation nodes.",
        ("cga dfg --markdown show", "cga dfg --render-user data-flow.html show"),
        GRAPH_ENV),
    ("cfg",): HelpTopic(
        "inspect legacy command execution graphs",
        "Read a numbered-flow history manifest without modifying it. CFG nodes "
        "are command invocations in execution order; parent edges preserve chains "
        "and branches, unlike the state-and-delta nodes in dfg. Current .cga "
        "workflows use cga tree show --control-flow instead. Place manifest/format "
        "options before info/show. Output is graph text, not CGAST JSON.",
        ("cga cfg --manifest run-history/manifest.json show",
         "cga cfg --render control-flow.pdf show"),
        GRAPH_ENV),
    ("cfg", "info"): HelpTopic(
        "summarize legacy control-flow graph storage",
        "Report the manifest's chains, roots, heads, immutable snapshot counts "
        "and storage paths as a whole-CGAST control-flow graph. --session changes "
        "only the displayed compatibility-copy path. Put global options before "
        "info; --markdown is supported, while DOT/PDF/HTML formats require show. "
        "This does not execute recorded commands.",
        ("cga cfg --manifest run-history/manifest.json --markdown info",),
        GRAPH_ENV),
    ("cfg", "show"): HelpTopic(
        "show recorded command invocations and parent edges",
        "Display command nodes ordered by chain and sequence, preserving branch "
        "and cross-chain parent relationships. Default output is a plain table; "
        "--markdown emits a table, --dot emits Graphviz DOT clustered by chain "
        "with the current head highlighted. --render FILE requires Graphviz dot "
        "and writes PDF; --render-user FILE writes dependency-free HTML/SVG. "
        "Rendered files overwrite destinations and print their paths. Options "
        "precede show. Recorded commands are displayed, never replayed.",
        ("cga cfg --dot show", "cga cfg --render-user control-flow.html show"),
        GRAPH_ENV),
    ("cc",): HelpTopic(
        "install or launch native browser VS Code",
        "Use native Coder code-server with host tools and filesystem permissions, "
        "not a container or sandbox. Install explicitly, inspect the executable, "
        "or serve an existing .code-workspace until interrupted. Opening an editor "
        "never downloads code-server automatically. Requires Python 3.11+; the "
        "pinned installer supports Linux amd64/arm64. This component prints JSON "
        "descriptors and is not a CGAST state filter.",
        ("cga cc install", "cga cc info",
         "cga cc serve query.code-workspace --runtime .cga/runtime/manual-editor --port 8611"),
        EDITOR_ENV),
    ("cc", "install"): HelpTopic(
        "install the pinned checksum-verified code-server",
        "Download the pinned Coder release for Linux amd64/arm64, verify its "
        "SHA-256, and extract it under the user cache. Reuse an existing cached "
        "binary without another download. Print its executable path as JSON. "
        "Requires network access for a new installation; does not start an "
        "editor or install extensions. Other platforms must supply their own "
        "code-server through PATH or CGACC_CODE_SERVER.",
        ("cga cc install", "cga cc info"),
        (("XDG_CACHE_HOME", "Cache base; default ~/.cache. Install under cga/code-server-<version>-linux-<arch>."),)),
    ("cc", "info"): HelpTopic(
        "locate code-server without installing or starting it",
        "Print JSON containing the executable selected from CGACC_CODE_SERVER, "
        "then PATH, then the pinned user cache. An invalid explicit override is "
        "an error rather than a fallback; a missing executable reports how to "
        "install it. This performs no download and does not check editor health.",
        ("cga cc info",),
        EDITOR_ENV),
    ("cc", "serve"): HelpTopic(
        "serve an existing VS Code workspace in the foreground",
        "Requires an existing .code-workspace and an installed code-server. Bind "
        "IPv4 loopback on --port (default 0 allocates a port; occupied fixed ports "
        "are errors), create private runtime config/logs/settings/extensions under "
        "--runtime, and wait for health before printing a JSON descriptor. The "
        "descriptor includes a generated login password: treat stdout as sensitive. "
        "Runtime config.yaml is rewritten and the directory mode is set to 0700. "
        "SIGINT/SIGTERM closes the owned editor process group, including terminals; "
        "runtime files remain. The editor runs as the local OS account: use only "
        "on a trusted single-user host, never publish it to untrusted users.",
        ("cga cc serve /data/query.code-workspace --runtime .cga/runtime/manual-editor --port 8611",),
        EDITOR_ENV),
}

"""Help for experiments, infrastructure, local projections, and element references."""

from command_help import HelpTopic


WORKFLOW_ENV = (
    ("CGA_DIR", "Explicit workflow metadata directory; otherwise discover .cga from the current directory."),
    ("CGA_OBJECT_STORE", "Override the configured object store when reading retained workflow artifacts."),
)
BENCH_ENV = (
    ("CGA_TMPDIR", "Scratch directory; Bench-managed services default below the workflow's .cga/tmp."),
    ("CGA_MRVA_SERVER", "MRVA endpoint; Bench defaults to http://127.0.0.1:$PORT (PORT defaults to 8081)."),
    ("MRVA_WORK_DIR / MRVA_TMP_DIR", "Bench service data/log directories; default below .cga/runtime. Existing overrides are preserved."),
    ("MRVA_STANDALONE_STORAGE", "Artifact backend: filesystem (default) or minio."),
)
MX_ENV = (
    ("PORT", "MRVA HTTP port (default: 8081); do not run concurrent MRVA scenarios on shared ports/PostgreSQL."),
    ("POSTGRES_HOST / POSTGRES_PORT", "PostgreSQL endpoint (localhost and the active local cluster port by default)."),
    ("POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB", "PostgreSQL credentials/database (defaults: $USER, mrva, mrvadev)."),
    ("MRVA_WORK_DIR / MRVA_TMP_DIR", "Service data and scratch/log directories; defaults: /tmp/mrva-cgamx and /tmp/mrva-$RUN_TAG."),
    ("RUN_TAG", "Scratch namespace (default: cgamx). Explicit environment settings are never replaced by defaults."),
    ("MRVA_STANDALONE_STORAGE", "Artifact backend: filesystem (default) or minio."),
    ("DB_SERVER_PORT / MRVA_DB_SERVER_URL / MRVA_DB_SERVE_DIR", "Database archive service: 9080, http://127.0.0.1:9080, and $MRVA_WORK_DIR/db-serve by default."),
    ("SERVER_LOG", "MRVA log path (default: $MRVA_TMP_DIR/server.log)."),
)
VID_ENV = (
    *WORKFLOW_ENV,
    ("CGA_OUTPUT_JSON", "Set to 1 to emit structured JSON rather than human-readable properties or relations."),
)


TOPICS: dict[tuple[str, ...], HelpTopic] = {
    ("bench",): HelpTopic(
        "prepare, run, and compare single-axis experiments",
        "An experiment contains one-based sessions with D (databases), Q (queries), "
        "J (jobs), and R (frozen results). Select query-changes to hold D fixed, or "
        "database-changes to hold Q fixed. S1 supplies the reference input and results. "
        "Use an initialized workflow and active chain for recorded commands; direct "
        "cgabench commands are CGAST JSON-in/JSON-out filters with diagnostics on stderr. "
        "Accepting both inputs normally advances analysis; comparing results is always explicit.",
        ("cga init .", "cga chain start", "cga bench init query-study --mode query-changes",
         "cga bench session baseline", "cga bench show E", "cga bench serve"),
        BENCH_ENV,
    ),
    ("bench", "init"): HelpTopic(
        "create an experiment in the current state",
        "Create a named experiment with no sessions. The state must not already contain "
        "an experiment. Choose --mode query-changes (fixed databases) or database-changes "
        "(fixed query), or select the mode later with bench mode. A mode is required before "
        "session mutations. The dispatcher records the new CGAST in the workflow.",
        ("cga init .", "cga chain start", "cga bench init query-study --mode query-changes",
         "cga bench session baseline"),
    ),
    ("bench", "mode"): HelpTopic(
        "select and validate the experiment's fixed input",
        "Require an existing experiment. query-changes fixes D; database-changes fixes Q. "
        "Validate previously accepted fixed artifacts against S1 without rewriting evidence. "
        "Once sessions exist, an already selected mode cannot change. An unclassified "
        "experiment remains readable but cannot prepare or run sessions until classified.",
        ("cga bench init query-study", "cga bench mode query-changes", "cga bench session baseline"),
    ),
    ("bench", "session"): HelpTopic(
        "append a reference session or a fixed-input variant",
        "Append S1 or a later session and make it active. Require a selected experiment "
        "mode; variants require S1's accepted fixed input and inherit only that input, "
        "not jobs/results. NAME defaults to a unique session-N label. --user defaults "
        "to S1's MRVA identity, or the login username for S1; --server selects its endpoint. "
        "Creating a variant does not itself run or compare it.",
        ("cga bench session baseline --user alice", "cga bench show 'E.S[1].D'",
         "# After S1's fixed D is accepted in query-changes mode:",
         "cga bench session refined", "cga bench show 'E.S[2]'"),
    ),
    ("bench", "clone"): HelpTopic(
        "reference an accepted fixed input from a prior session",
        "Clone only the mode's fixed D or Q stage into the selected session (active by "
        "default), using --from-session 1 by default. Require an accepted prior input "
        "matching S1's fixed identity. Reuse artifacts and record source/digests rather "
        "than copying large files. J/R and the changing input cannot be cloned. "
        "Unless --no-advance is supplied, attempt analysis after acceptance.",
        ("cga bench session refined",
         "cga bench clone --session 2 --stage D --from-session 1 --no-advance",
         "cga bench show 'E.S[2].D'"),
    ),
    ("bench", "infrastructure"): HelpTopic(
        "manage the experiment's analysis services",
        "Run setup or a single maintenance phase through cgamx and retain runtime state. "
        "setup checks/reclaims ports, resets only a new runtime, builds, and starts MRVA "
        "plus archive/optional MinIO services; an existing runtime restarts without reset. "
        "preflight checks/reclaims, reset destroys MRVA tables/work files, build compiles, "
        "start starts, check gates log errors, stop preserves data, cleanup stops and deletes "
        "runtime data. PostgreSQL is shared and not stopped. Do not overlap another MRVA run.",
        ("cga bench infrastructure setup", "cga bench infrastructure check",
         "cga bench infrastructure stop"),
        BENCH_ENV,
    ),
    ("bench", "catalogue"): HelpTopic(
        "load an indexed database catalogue",
        "Load an existing SQLite catalogue through database-library getmeta; this does not "
        "build databases or accept D. Require a classified experiment. With --session N, "
        "load into that session's editable D workspace; otherwise load the experiment-wide "
        "library. --source user marks a session's supplied catalogue as user-provided. "
        "Choose catalogue rows separately to download and accept database archives.",
        ("cga bench catalogue databases/metadata.sql", "cga bench serve --no-services",
         "# Select database rows in the library table, then inspect D:",
         "cga bench show 'E.S[1].D'"),
    ),
    ("bench", "library"): HelpTopic(
        "index a query source tree for selection",
        "Run query-library index on DIRECTORY without accepting Q or executing analysis. "
        "Require a classified experiment. --session N indexes into that session's editable "
        "Q workspace; otherwise the query library is shared by the experiment. Choose one "
        "query table row separately to pack and accept it.",
        ("cga bench library queries/", "cga bench serve --no-services",
         "cga bench show 'E.S[1].Q'"),
    ),
    ("bench", "choose-databases"): HelpTopic(
        "download and accept selected database-library rows",
        "Require an editable D cell and loaded catalogue. --generation is the exact current "
        "table SHA256, and --rows are original SQLite rowids, not display positions. "
        "Choose 1..100 distinct rows with one language and one version per repository. "
        "Download archives, verify immutable identities, accept D, and normally advance "
        "analysis; --no-advance defers it. --session defaults to the active row and "
        "--source defaults to list. Obtain generation/rowids from the Bench library table/API.",
        ("cga bench catalogue databases/metadata.sql",
         "cga bench choose-databases --session 1 --generation \"$GENERATION\" --rows 1 3 --no-advance",
         "cga bench show 'E.S[1].D'", "cga bench advance --session 1"),
        (("MRVA_DB_SERVE_DIR", "Download destination when not already recorded by cgamx; use the archive tree served to MRVA."),),
    ),
    ("bench", "choose-query"): HelpTopic(
        "pack and accept one query-library row",
        "Require an editable Q cell and indexed library. --generation is the exact current "
        "table SHA256 and --rows must contain exactly one original SQLite rowid. "
        "Validate its language against accepted D, pack the query, accept Q, and normally "
        "advance analysis; --no-advance defers it. --session defaults to the active row "
        "and --source to list. Obtain generation/rowid from the Bench library table/API.",
        ("cga bench library queries/",
         "cga bench choose-query --session 1 --generation \"$GENERATION\" --rows 1 --no-advance",
         "cga bench show 'E.S[1].Q'", "cga bench advance --session 1"),
    ),
    ("bench", "create-query"): HelpTopic(
        "write a persistent editable query starter",
        "Create a named query and pack metadata in a new DIRECTORY for the selected "
        "session's editable Q cell (active by default). Require an experiment mode and "
        "a supported CodeQL language. Index the source and record draft provenance, "
        "but do not accept Q or start analysis. Edit and then choose the resulting "
        "query-library row when ready.",
        ("cga bench create-query --session 1 --directory queries/new --name NewQuery --language cpp",
         "cga bench edit-query --session 1 --source \"$(cat queries/new/NewQuery.ql)\"",
         "cga bench show 'E.S[1].Q'"),
    ),
    ("bench", "edit-query"): HelpTopic(
        "save and reindex a session's editable query",
        "Require an editable Q cell and a persistent draft already created or copied "
        "for that session. Take the updated text from --source TEXT, save it into the "
        "draft, and reindex the library. --source is the query text, not a filename. "
        "--session defaults to the active session. "
        "This records source work, not an accepted Q artifact, job, or comparison.",
        ("cga bench copy-query --session 2 --from-session 1 --directory queries/refined",
         "cga bench edit-query --session 2 --source \"$(cat edited-query.ql)\"",
         "cga bench show 'E.S[2].Q'"),
    ),
    ("bench", "copy-query"): HelpTopic(
        "copy query source into an isolated editable draft",
        "Require an editable Q cell. Copy either a prior session's accepted query pack "
        "(--from-session N) or a library query (--generation SHA256 --row ROWID); "
        "these sources are mutually exclusive. Create a new DIRECTORY with source/support "
        "files and provenance, and reindex it. --source list|user selects the library "
        "source; --session defaults to active. Copying is not fixed-Q cloning: it "
        "does not accept Q, run jobs, or compute comparisons.",
        ("cga bench session refined",
         "cga bench copy-query --session 2 --from-session 1 --directory queries/refined",
         "cga bench edit-query --session 2 --source \"$(cat edited-query.ql)\""),
    ),
    ("bench", "database"): HelpTopic(
        "accept prepared database selection and archives as D",
        "Require an editable session D cell and classified experiment. Use --selection "
        "and --dbdir for prepared selection JSON and downloaded archives, or reuse "
        "the session workspace's current database-library outputs. Verify language, "
        "archive digests, and immutable owner/repository identities. --source records "
        "list or user provenance. Acceptance normally advances analysis when Q is ready; "
        "--no-advance defers it. --session defaults to the active row.",
        ("cga bench database --session 1 --selection selected-databases.json --dbdir archives --no-advance",
         "cga bench show 'E.S[1].D'", "cga bench advance --session 1"),
    ),
    ("bench", "query"): HelpTopic(
        "accept a prepared query selection and pack as Q",
        "Require an editable Q cell and classified experiment. Use --selection and --pack "
        "for prepared query selection JSON and a packed archive, or reuse current "
        "session query-library outputs. --pack-index defaults to 0 when choosing among "
        "workspace packs. Verify retained bytes and language compatibility with D. "
        "--source records list or user provenance. Normally advance analysis after "
        "acceptance; --no-advance defers it. --session defaults to active.",
        ("cga bench query --session 1 --selection selected-query.json --pack query.tar.gz --no-advance",
         "cga bench show 'E.S[1].Q'", "cga bench advance --session 1"),
    ),
    ("bench", "advance"): HelpTopic(
        "continue one session to its next recoverable checkpoint",
        "Synchronize and advance the selected session (active by default). Require a "
        "classified experiment and valid fixed inputs. Pause explicitly for missing "
        "D/Q, submit ready inputs, poll existing jobs, download results, and freeze "
        "completed R evidence as appropriate. Reuse recovery checkpoints rather than "
        "duplicating uncertain submissions. This may contact MRVA and write artifacts; "
        "it never computes E.C automatically.",
        ("cga bench show 'E.S[1]'", "cga bench advance --session 1",
         "cga bench show 'E.S[1].J'", "cga bench advance --session 1"),
        BENCH_ENV,
    ),
    ("bench", "work"): HelpTopic(
        "record a note on editable database or query work",
        "Append a timestamped note to the selected session's D or Q history and make "
        "that session active. Require a classified experiment and editable input; "
        "submitted/completed evidence and inherited fixed inputs cannot be edited. "
        "This records work only: it does not accept artifacts or advance jobs. "
        "--session defaults to the active session.",
        ("cga bench work --session 2 --stage Q --note 'Tightened the source predicate'",
         "cga bench show 'E.S[2].Q'"),
    ),
    ("bench", "tool"): HelpTopic(
        "run a component tool in an editable input workspace",
        "Run the trailing component command in the selected session's isolated D or Q "
        "workspace and retain its outputs there. Require a classified experiment and "
        "editable input. --session defaults to active. Use -- to separate Bench options "
        "from component arguments. Running a preparation tool does not itself accept "
        "D/Q, submit jobs, or compare results; accept the prepared input explicitly.",
        ("cga bench tool --session 1 --stage Q -- ql index queries/",
         "cga bench tool --session 1 --stage Q -- ql select name MyQuery",
         "cga bench tool --session 1 --stage Q -- ql pack",
         "cga bench query --session 1 --no-advance"),
    ),
    ("bench", "show"): HelpTopic(
        "inspect an experiment, session, cell, or comparison",
        "Project the existing experiment without running analysis or computing a new "
        "comparison. ADDRESS defaults to E; accept E.C, E.S[N], E.S[N].D/Q/J/R, "
        "and column aliases E.D/Q/J/R[N]. The component prints the projection to "
        "stderr and preserves CGAST on stdout; use llm context bench --json for "
        "a standalone structured assistant projection.",
        ("cga bench show E", "cga bench show 'E.S[1].J'", "cga bench show E.C",
         "cga llm context bench --json"),
    ),
    ("bench", "info"): HelpTopic(
        "print the current experiment summary",
        "Project E from the current state, including experiment mode, sessions, "
        "D/Q/J/R status, and existing comparison metadata. Require an initialized "
        "experiment. Print human inspection output on stderr while preserving "
        "the JSON CGAST filter output; do not advance jobs or recompute comparisons.",
        ("cga bench info", "cga bench show 'E.S[1]'", "cga llm cb"),
    ),
    ("bench", "compare"): HelpTopic(
        "compare frozen completed sessions against S1",
        "Explicitly compute E.C from immutable completed SARIF evidence. Require "
        "a classified experiment, completed S1, and valid matching fixed input. "
        "Optional session numbers select variants; by default compare completed "
        "sessions. Always retain S1 as baseline and record result snapshots/provenance. "
        "Report common/added/removed findings; this is separate from running sessions "
        "and does not resubmit, reingest, or modify their frozen R evidence.",
        ("cga bench show 'E.S[1].R'", "cga bench show 'E.S[2].R'",
         "cga bench compare 2", "cga bench show E.C"),
    ),
    ("bench", "serve"): HelpTopic(
        "serve the mutable experiment grid on loopback",
        "Run the foreground Bench viewer at 127.0.0.1:8610 by default. Require a "
        "workflow experiment, or --session-file for a raw CGAST. Automatically set up "
        "analysis services unless --no-services is supplied, and prestart Copilot "
        "unless --no-assistant is supplied. The UI can mutate experiment state. "
        "--editor-port 0 allocates per-session editors automatically; a nonzero "
        "base assigns S1 that port, S2 base+1, etc. Shutdown closes owned editors, "
        "assistant, and inspector shells, not MRVA services. Restart after backend edits.",
        ("cga bench stop",
         "cga bench serve --no-services --no-assistant --editor-port 8611",
         "# From another terminal in this workflow:", "cga bench stop"),
        BENCH_ENV,
    ),
    ("bench", "stop"): HelpTopic(
        "stop this workflow's viewer and owned editors",
        "Find the recorded Bench viewer for this workflow (or the same explicit "
        "--session-file used at startup), send SIGTERM to its verified process "
        "identity, and wait up to 30 seconds for cleanup. Succeed if already stopped. "
        "Do not search by process name, stop MRVA/archive/MinIO/PostgreSQL, alter the "
        "experiment, or record a workflow step. Older untracked viewers must be "
        "stopped in their original terminal.",
        ("cga bench stop", "cga bench serve --no-services",
         "# Raw-state alternative:",
         "cga bench stop --session-file session.json"),
    ),
    ("mx",): HelpTopic(
        "control standalone MRVA infrastructure one phase at a time",
        "Manage PostgreSQL readiness, MRVA builds, archive serving, optional MinIO, "
        "and the MRVA server. Recorded commands retain runtime paths/PIDs under cgamx; "
        "direct components read/write one CGAST JSON object, with diagnostics on stderr. "
        "cmd is a separate foreground command server, not a filter. Linux host tools, "
        "Go, CodeQL, and PostgreSQL are required for bring-up. Phases share ports and "
        "database tables with Bench/tests: never run competing scenarios concurrently. "
        "reset/cleanup are destructive; start does not imply preflight or reset.",
        ("cga init .", "cga mx preflight", "cga chain start", "cga mx reset",
         "cga mx build", "cga mx start", "cga mx check", "cga mx stop"),
        MX_ENV,
    ),
    ("mx", "preflight"): HelpTopic(
        "check host tools, PostgreSQL, and reclaim service ports",
        "Check CodeQL/Go and required Linux utilities, discover/probe PostgreSQL, "
        "ensure the configured database endpoint is ready, and reclaim configured "
        "service ports. Persist postgres_probe findings and runtime configuration. "
        "This is not a harmless status check: it can start local PostgreSQL and "
        "stop conflicting port owners. Run before starting a single owned scenario, "
        "not alongside Bench or another MRVA test. It does not start MRVA.",
        ("cga mx preflight", "cga chain start", "cga mx reset", "cga mx build"),
        (*MX_ENV, ("CODEQL_JAVA_HOME", "Java location (default: /usr); required for the arm64 CodeQL setup.")),
    ),
    ("mx", "reset"): HelpTopic(
        "drop MRVA tables and recreate empty service directories",
        "Destructively drop the MRVA tables in the configured PostgreSQL database "
        "and remove MRVA_WORK_DIR/MRVA_TMP_DIR, including logs, archives, caches, "
        "and prior runtime PID metadata. Recreate required empty directories. "
        "Use only for a deliberate clean slate after preflight and before start; "
        "do not reset a running or recoverable experiment. This phase does not "
        "stop an existing service first.",
        ("cga mx preflight", "cga mx reset", "cga mx build", "cga mx start"),
        MX_ENV,
    ),
    ("mx", "build"): HelpTopic(
        "compile the MRVA server and standalone agent",
        "Invoke the server-commander Makefile targets mrvaserver and mrvaagent "
        "and record the completed phase. Require the repository's Go/Make toolchain "
        "and local sibling module dependencies. Do not reset data, reclaim ports, "
        "or start services. Build before start; an already running process continues "
        "using its old binary until explicitly restarted.",
        ("cga mx build", "cga mx start", "cga mx info"),
    ),
    ("mx", "start"): HelpTopic(
        "start archive serving, optional MinIO, and MRVA",
        "Start the database archive HTTP server, MinIO when selected, and the built "
        "MRVA server with its standalone agent pool. Require prior preflight/build "
        "and initialized runtime/database state. Retain process IDs, ports, paths, "
        "and optional sysview dump path in CGAST. It neither resets tables nor "
        "performs preflight. Populate the served archive tree for subsequent MRVA "
        "submissions. Services outlive this command; stop them explicitly.",
        ("cga mx build", "cga mx start", "cga mx info", "cga mx check", "cga mx stop"),
        (*MX_ENV,
         ("MRVA_CODEQL_THREADS / MRVA_POOL_MAX_WORKERS", "Threads per agent (default 2) and worker count (default derived from available cores)."),
         ("MRVA_ENVSIM_AGENT_BINARY", "Standalone agent binary; defaults to the repository's agent-commander-argo/mrvaagent."),
         ("MINIO_PORT / MRVA_MINIO_ENDPOINT", "Optional MinIO listener/endpoint (9000 / localhost:9000 by default)."),
         ("MRVA_MINIO_ACCESS_KEY / MRVA_MINIO_SECRET_KEY", "Optional MinIO credentials (both default to minioadmin)."),
         ("MRVA_DBG_DUMP_SYSVIEW / MRVA_SYSVIEW_DUMP_PATH", "Enable sysview dumping and select its file (default: sysview-dump).")),
    ),
    ("mx", "logs"): HelpTopic(
        "print the MRVA log tail and diagnostic error scan",
        "Print the last 25 server-log lines and matching non-benign errors to "
        "stderr while preserving CGAST stdout. Require the configured SERVER_LOG "
        "for useful output; do not start services or continuously follow the file. "
        "This phase displays errors but is not the failing error gate: run check "
        "to make non-benign log errors fail a script.",
        ("cga mx logs", "cga mx check"),
        (("SERVER_LOG", "Server log to read (default: $MRVA_TMP_DIR/server.log)."),),
    ),
    ("mx", "check"): HelpTopic(
        "fail when the server log contains non-benign errors",
        "Scan SERVER_LOG using the MRVA benign-error exclusions. Print PASS and "
        "preserve CGAST on success; report FAIL and exit nonzero when real errors "
        "are found. This is a log gate, not a server-readiness probe, and does not "
        "start or stop services. Use logs to inspect the diagnostic context.",
        ("cga mx logs", "cga mx check", "cga mx stop"),
        (("SERVER_LOG", "Server log to scan (default: $MRVA_TMP_DIR/server.log)."),),
    ),
    ("mx", "stop"): HelpTopic(
        "stop MRVA and its owned auxiliary services while retaining data",
        "Stop the MRVA process group, including spawned agents/CodeQL processes, "
        "and the configured database archive server and optional MinIO. Use "
        "recorded runtime PIDs with PID-file/port backstops. Keep PostgreSQL, "
        "tables, work directories, and logs for inspection or restart; cleanup "
        "is the separate destructive operation. Preserve updated CGAST runtime state.",
        ("cga mx check", "cga mx stop", "cga mx info", "cga mx start"),
        MX_ENV,
    ),
    ("mx", "cleanup"): HelpTopic(
        "stop services and destroy standalone runtime data",
        "Stop MRVA/agents and auxiliary services, drop MRVA tables when PostgreSQL "
        "is reachable, remove work/scratch directories and logs, and remove the "
        "recorded sysview dump. Clear recorded runtime PIDs. PostgreSQL itself "
        "remains running. This destroys recovery evidence and downloaded inputs: "
        "export or retain required artifacts first. Do not use against another "
        "experiment's shared configuration.",
        ("cga mx logs", "cga mx check", "# Only after retaining required evidence:",
         "cga mx cleanup", "cga mx info"),
        MX_ENV,
    ),
    ("mx", "info"): HelpTopic(
        "print recorded standalone infrastructure configuration",
        "Print storage backend, service ports/PIDs, work/log paths, and last "
        "phase from CGAST, falling back to resolved environment defaults. "
        "Preserve CGAST stdout and put the human summary on stderr. "
        "This does not probe readiness or start infrastructure; recorded PIDs "
        "alone do not prove a service is alive.",
        ("cga mx info", "cga mx logs", "cga mx check"),
        MX_ENV,
    ),
    ("mx", "cmd"): HelpTopic(
        "serve a loopback command/apply endpoint",
        "Run a foreground HTTP server at 127.0.0.1:8607 by default. Unlike "
        "fragment viewers this can execute cga* commands as the local OS user. "
        "POST /run accepts an argv array or shlex-split command, never a shell; "
        "only cga* programs on PATH are accepted. Route supported commands into "
        "the initialized workflow with dashboard provenance, otherwise atomically "
        "replace CGA_SESSION with successful filter stdout. It reads no stdin "
        "CGAST and starts no MRVA infrastructure. Stop the foreground process to exit.",
        ("cga run start",
         "# Standalone alternative, with an existing session.json:",
         "CGA_SESSION=\"$PWD/session.json\" cga mx cmd",
         "# Readiness from another terminal:",
         "curl --fail http://127.0.0.1:8607/healthz"),
        (("CGA_CGAMX_PORT", "Loopback command-server port (default: 8607)."),
         ("CGA_SESSION", "Existing JSON CGAST file for non-workflow command execution."),
         ("CGA_WORKFLOW_ROOT", "Initialized workflow root for recorded dashboard commands."),
         ("PATH", "Must resolve the allowed cga* component programs.")),
    ),
    ("uv", "serve"): HelpTopic(
        "run the internal foreground Unified View HTTP server",
        "Internal Python entry point used by the Unified View lifecycle launcher. "
        "Require an initialized local workflow and bind only to 127.0.0.1 on "
        "CGA_CGAUV_PORT (default 8609). Serve workflow/history projections and "
        "shared VID inspectors without starting MRVA or changing analysis state. "
        "Explicit inspector terminals run as the local OS user. SIGTERM/Ctrl+C "
        "closes owned inspector terminals and the HTTP listener. Use public "
        "cga uv start/status/stop for managed lifecycle, not cga uv serve.",
        ("cga uv start", "cga uv status", "cga uv stop"),
        (*WORKFLOW_ENV, ("CGA_CGAUV_PORT", "Loopback Unified View listener port (default: 8609).")),
    ),
    ("uv", "outline"): HelpTopic(
        "print a bounded workflow outline without a web service",
        "Read the current workflow's retained local history and selected resources, "
        "printing Markdown by default or JSON with --format json. --detail steps "
        "(default) includes command detail; summary provides a compact projection. "
        "Repeat --match-tag field:value to filter tagged entities. Secret-tagged "
        "entities are redacted and counted by default. --include-sensitive explicitly "
        "overrides that policy locally; never send that output to an external LLM. "
        "No services start and no workflow step/state mutation is recorded.",
        ("cga uv outline", "cga uv outline --format json --detail summary",
         "cga uv outline --match-tag audience:user", "cga uv search Fprintf"),
        WORKFLOW_ENV,
    ),
    ("uv", "search"): HelpTopic(
        "search retained workflow commands and selected resources",
        "Search the current local workflow without HTTP or state changes. QUERY "
        "defaults to empty for filter-only discovery. Repeat --match-tag field:value "
        "and --kind to restrict results; use --offset 0 and --limit 50 defaults "
        "for a bounded page with total/count/truncation metadata. Print Markdown "
        "or --format json. Secret entities are excluded unless the explicit local "
        "--include-sensitive override is supplied; do not share sensitive output "
        "with an external LLM. Inspect returned steps/VIDs separately.",
        ("cga uv search Fprintf",
         "cga uv search --kind database --format json --limit 20",
         "cga uv search --match-tag presentation:progress",
         "cga show :h7m,1"),
        WORKFLOW_ENV,
    ),
    ("view",): HelpTopic(
        "capture live dashboard fragments or export an offline replay",
        "Choose exactly one mode. --capture fetches every analysis dashboard "
        "fragment from already running local component servers and appends one "
        "all-or-nothing JSONL snapshot; a failed fetch appends nothing. --export "
        "HTML reads valid captures and writes one self-contained, read-only replay "
        "with inline CSS, fragments, and controls, requiring no live services. "
        "--dump defaults to cga-dashboard-dump; --label to 'manual capture'; "
        "--timeout is 5 seconds per fragment by default. This command does not "
        "start servers or mutate the recorded workflow state.",
        ("cga run start",
         "cga view --dump dashboard.jsonl --capture --label 'baseline results'",
         "cga view --dump dashboard.jsonl --export replay.html", "cga run stop"),
        (("CGA_CGASV_PORT", "System header fragment port (default: 8601)."),
         ("CGA_CGADL_PORT / CGA_CGAQL_PORT", "Database/query fragment ports (defaults: 8602 / 8603)."),
         ("CGA_CGAMR_PORT / CGA_CGAMU_PORT", "Request/update fragment ports (defaults: 8604 / 8605)."),
         ("CGA_CGASI_PORT / CGA_CGAEX_PORT", "Ingestion/export fragment ports (defaults: 8606 / 8608)."),
         ("CGA_ROOT", "CGA collection root containing web/index.html and web/cga.css for export; defaults to this checkout.")),
    ),
    ("llm",): HelpTopic(
        "read assistant context directly from local CGA state",
        "Choose context bench for experiment/session D/Q/J/R state or context "
        "unified for workflow history and selected resources. Aliases cb and cu "
        "select the same sources. These are bounded read-only projections, not "
        "requests to a running viewer: they start no services and record no steps. "
        "Endpoint/doc flags print references only, without fetching or verifying them.",
        ("cga llm context bench", "cga llm cb --json", "cga llm context unified",
         "cga llm cu --show-docs"),
        WORKFLOW_ENV,
    ),
    ("llm", "context"): HelpTopic(
        "choose experiment or workflow assistant context",
        "bench reads the addressable experiment model; unified reads the "
        "redacted workflow outline. Require a local initialized workflow for "
        "context, or bench --session-file for raw CGAST. Each source supports "
        "mutually exclusive --json, --show-html-endpoint, --show-json-endpoint, "
        "and --show-docs. Reference-only flags work without initialized state. "
        "Use --port only to construct URLs; it does not start a viewer.",
        ("cga llm context bench", "cga llm context unified --detail summary",
         "cga llm context bench --show-json-endpoint",
         "cga llm context unified --show-docs"),
        WORKFLOW_ENV,
    ),
    ("show",): HelpTopic(
        "inspect a visual element's properties and immutable facts",
        "Resolve an opaque VID such as :f3a,1,J, a quoted Lisp reference, "
        "or a qualified cga://vid URI. Short references use the current workflow, "
        "chain, and experiment; --chain and --at select explicit history. Return "
        "properties, cumulative retained facts, and qualified/pinned references, "
        "or --json for structured output. --registry lists permanent roots without "
        "a workflow. --session-file observes raw CGAST in adjacent VID history "
        "without rewriting the source. Normal workflow inspection starts no "
        "service and records no command step. Secret-tagged objects are rejected.",
        ("cga show --registry", "cga show :f3a,1,J",
         "cga show '(:f3a 1 :J)' --json", "cga related :f3a,1,J"),
        VID_ENV,
    ),
    ("related",): HelpTopic(
        "list an element's typed links to qualified targets",
        "Resolve the same VID forms and history selectors as show, then print "
        "typed relations with qualified target references, or --json for a "
        "structured relation array. Require the current workflow or an explicitly "
        "qualified/raw --session-file context. Relations derive from retained "
        "immutable evidence, not current mutable files; secret-tagged objects "
        "are rejected. This does not start a viewer or run analysis. Observing "
        "a raw session may retain adjacent VID history without changing its CGAST.",
        ("cga show :f3a,1,J", "cga related :f3a,1,J --json",
         "cga show :h7m,1"),
        VID_ENV,
    ),
    ("open",): HelpTopic(
        "open a pinned visual-element inspector in an existing viewer",
        "Resolve a VID and open its pinned fact frontier in a browser; "
        "--print-url prints the URL instead. Require retained workflow/raw-session "
        "evidence and a running Bench or Unified View for browser inspection. "
        "No viewer starts automatically. --url accepts only a loopback HTTP "
        "origin and overrides defaults: Bench :8610 for experiment/session/comparison "
        "objects, Unified :8609 for others. --chain/--at select history. "
        "The inspector's explicit terminal runs with the operator's normal account; "
        "opening an inspector itself does not run an analysis command.",
        ("cga uv start", "cga open :h7m,1",
         "cga open :f3a,1 --url http://127.0.0.1:8610 --print-url",
         "cga related :h7m,1"),
        (*WORKFLOW_ENV,
         ("CGA_BENCH_URL", "Inherited viewer origin (including inspector terminals); overridden by --url."),
         ("CGA_CGAUV_PORT", "Unified viewer port for non-Bench objects (default: 8609).")),
    ),
}

for path in (("llm", "context", "bench"), ("llm", "cb")):
    TOPICS[path] = HelpTopic(
        "read Bench experiment and session context" + (" (alias for context bench)" if path[-1] == "cb" else ""),
        "Read the local experiment's mode, reference, sessions, D/Q/J/R requirements, "
        "comparison status, and VID context. Require a workflow experiment or "
        "--session-file FILE for raw CGAST. Print Markdown by default, structured "
        "projection with --json, or one reference-only output: --show-html-endpoint, "
        "--show-json-endpoint, --show-docs. Endpoint URLs default to 127.0.0.1:8610 "
        "(--port overrides); printing them does not fetch content or prove a viewer "
        "is running. No service startup, observation-history write, or recorded mutation.",
        ("cga llm context bench", "cga llm cb --json",
         "cga llm cb --session-file session.json", "cga llm cb --show-json-endpoint",
         "cga bench show 'E.S[1].J'"),
        (*WORKFLOW_ENV, ("CGA_OUTPUT_JSON", "Set to 1 for structured context output; endpoint/doc flags still take precedence.")),
    )

for path in (("llm", "context", "unified"), ("llm", "cu")):
    TOPICS[path] = HelpTopic(
        "read Unified workflow context" + (" (alias for context unified)" if path[-1] == "cu" else ""),
        "Read the local workflow outline and selected resources without HTTP, "
        "service startup, or recorded state changes. --detail steps is the default; "
        "summary is compact. Secret-tagged entities are redacted unless the explicit "
        "local --include-sensitive override is supplied; never share sensitive output "
        "with an external LLM. Print Markdown, --json, or one reference-only "
        "--show-html-endpoint/--show-json-endpoint/--show-docs output. URL flags "
        "need no workflow and default to 127.0.0.1:8609; --port overrides the port "
        "but neither starts nor probes a viewer.",
        ("cga llm context unified", "cga llm cu --json --detail summary",
         "cga llm cu --show-html-endpoint", "cga uv search Fprintf"),
        (*WORKFLOW_ENV,
         ("CGA_CGAUV_PORT", "Unified endpoint URL port (default: 8609); overridden by --port."),
         ("CGA_OUTPUT_JSON", "Set to 1 for structured context output; endpoint/doc flags still take precedence.")),
    )

"""Help for workflow history, dispatcher groups, and shell lifecycle commands."""

from command_help import HelpTopic
from tutorial_help import help_topics as tutorial_topics
from sample_help import STEPS


DISCOVERY = (
    ("CGA_DIR", "Explicit .cga metadata directory; otherwise discover it from the current directory and its parents."),
)
STORE = DISCOVERY + (
    ("CGA_OBJECT_STORE", "Override the configured filesystem or HTTP object-store root for this invocation."),
)
INSPECTION = STORE + (
    ("CGA_OUTPUT_JSON", "Set to 1 for structured inspection output; also selected by global --json."),
)
RUN_ENV = (
    ("CGA_SESSION", "Session CGAST read by analysis viewers; defaults to CGA_TMPDIR/session.json."),
    ("CGA_TMPDIR", "Analysis scratch directory; defaults to cga-tmp under the collection."),
    ("CGA_RUN_DIR", "Analysis service PID/log directory; defaults to .run under the collection."),
    ("CGA_PAGE_PORT", "Analysis dashboard HTTP port; defaults to 8600."),
)
UV_ENV = (
    ("CGA_CGAUV_PORT", "Unified View HTTP port; defaults to 8609."),
    ("CGA_UV_RUN_DIR", "Unified View PID/log directory; defaults to unified-view under CGA_RUN_DIR or .run."),
)

OVERVIEW = """\
CGA, the CodeQL General Appliance, is a collection of shell utilities
for using CodeQL at scale:
- applying CodeQL queries;
- building CodeQL databases;
- examining SARIF results.

On a single large, dedicated virtual machine, "at scale" means a few
users selecting from hundreds of queries and thousands of databases.
Typical runs:
- Select a query for a past vulnerability and apply it to vulnerable
  and recent, presumably patched builds. Check that the old builds
  still produce findings and the patched builds do not.
- Given a vulnerability report for a codebase and revision, write a
  query to detect it, then apply that query to other codebases to
  investigate whether they are also affected.

The components that apply queries across databases are called MRVA:
multi-repo variant analysis. Earlier MRVA deployments have used more
than 40 agents across multiple servers. The workflow stays the same;
only the scale changes: multiple users can each select 10,000 or more
projects, submit a query, and collect results.

Every run requires substantial metadata:
- Which query ran? Track the query and its version, including the
  executable pack and dependencies.
- Which projects were analyzed? Track project, revision, and build
  mode. Useful metadata also includes vulnerable/patched labels,
  build date, and release version.
- What was found? A location-based result identifies a project,
  file, line, and description, but must also retain its query,
  database/build, submission, and ingestion provenance. SARIF can
  include additional locations and code flows.

Tracking this manually is tedious. CGA uses project-local workflows:
.cga/ owns workflow metadata, history, and artifact references. The
configured content-addressed store holds retained artifact bytes and
may live outside the project. Users and LLMs can inspect state from
the shell; browser-based viewers expose workflow and result views.

Query and CodeQL database collections are indexed and selected through
SQLite catalogues. SARIF results can be collected into a single DuckDB
database for an analysis; SQLite ingestion is also supported. Result
collections can range from megabytes to gigabytes, with millions of
findings across thousands of databases. DuckDB supports fast analytical
filtering; selective queries may finish in under a second, depending
on the data, query, and machine.

Preparation and analysis are separate: explicitly hand prepared query
and database artifacts to the analysis workflow. A successful run, or
zero findings, does not by itself establish whether a vulnerability
was detected or ruled out. Review the evidence and use known
vulnerable/patched builds to assess query effectiveness.
"""

RUNNING_CGA = """\
Run CGA inside a Linux VM, not directly on the host OS. Use a dedicated,
disposable VM for experiments. CGA is a complex experimental prototype,
developed by one developer with an LLM. Review focuses on code
structure, documentation, and observable behavior rather than
line-by-line inspection of every generated change. CGA has extensive
end-to-end tests, not just small unit tests; those fixed examples also
provide starting points for common workflows.

CGA consists of separate shell-callable components. Components read
state and produce new state, using the filesystem as persistent memory.
Through the cga dispatcher, recorded operations retain immutable
snapshots and artifacts. Retained history grows incrementally:
H_i is a subset of H_(i+1). This does not mean that every working file,
current-state projection, or running service is immutable.

The components have documentation for both humans and LLMs. In the
author's experience, the LLMs tested so far have operated CGA without
observed hallucinations or semantic errors. This is experience with
those runs, not a guarantee of error-free operation.

For installation, scripting, general CGA questions, and inspection of
an existing run, the author strongly recommends a frontier LLM.
Start an assistant with AGENTS.md and the focused task route in
docs/cga-help-llm.org. Inspect existing evidence before rerunning work.
These commands provide read-only projections:

  cga llm context unified   # workflows
  cga llm context bench     # Bench experiments

In a disposable Linux VM, the VM boundary can make an assistant's
--yolo mode practical, if that assistant supports it. The flag does
not add isolation: destructive commands can destroy the VM, and
mounted host directories, shared storage, credentials, and network
services remain reachable according to the VM's access. Recreating
the VM may take seconds when an image or snapshot is ready; restoring
external data is a separate matter.

Start with cga help sample 05 for a small, fixed analysis, or
cga help getting-started for the longer walkthrough. Install the
dependencies in INSTALL.md first. Consult cga COMMAND -h for the
operation's prerequisites and effects. Shared MRVA ports and
PostgreSQL are not isolated merely by using different workspaces.
"""

GETTING_STARTED_COMMANDS = """\
1. Understand the system and choose inputs

   CGA records choices and commands in a .cga/ workflow. MRVA runs a
   selected query pack over selected CodeQL databases. SARIF ingestion
   and export turn the downloaded results into inspectable evidence.
   Preparation produces inputs; analysis consumes them explicitly.

   This first path uses the six existing C++ databases selected by
   cga/mrva-flow/databases.sql and sample-query/Fprintf.ql. It does not
   build databases or require writing a query.

2. Check prerequisites and start a fresh recorded analysis

   Run on Linux from the repository root with cga on PATH. Install the
   host dependencies first (INSTALL.md), including CodeQL and its C++
   query dependencies. Database downloads need network access and free
   disk space. Choose a new workspace; mkdir refuses an existing one.

   export CGA_REPO="$PWD"
   mkdir "$HOME/cga-first-analysis"
   cd "$HOME/cga-first-analysis"
   cga init
   cga chain start --name first-analysis
   export CGA_TMPDIR="$PWD/.cga/tmp"
   export MRVA_WORK_DIR="$PWD/.cga/runtime/mrva"
   export MRVA_TMP_DIR="$PWD/.cga/runtime/services"
   export MRVA_DB_SERVE_DIR="$MRVA_WORK_DIR/db-serve"
   export MRVA_STANDALONE_STORAGE="${MRVA_STANDALONE_STORAGE:-filesystem}"
   export CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME:-/usr}"

3. Start standalone MRVA and the viewers

   These lifecycle commands own shared MRVA ports and reset its database
   state. Do not run them alongside Bench or another MRVA scenario.
   preflight checks/reclaims; start starts. They are separate phases.

   cga mx preflight
   cga mx reset
   cga mx build
   cga mx start
   cga serve start
   cga serve status

   serve starts the viewers and gateway for existing state. Missing viewer
   state is reported as SKIP; it is not created. Open http://127.0.0.1:8599/
   for the dashboard, Unified View, and live MRVA state.

4. Select and retrieve the databases; select and pack the query

   getmeta imports catalogue metadata, not database archives. download
   retrieves the selected archives into the store served to MRVA.
   index imports query metadata; select and pack choose executable input.

   cga dl getmeta "$CGA_REPO/cga/cgadl/db-collection.global/metadata.sql"
   cga dl sql --user bob --query-file "$CGA_REPO/cga/mrva-flow/databases.sql"
   cga dl download --output-dir "$MRVA_DB_SERVE_DIR"
   cga ql index "$CGA_REPO/sample-query"
   cga ql select --user bob relpath Fprintf.ql
   cga ql pack

5. Submit, wait, download, and verify

   mr run performs these operations with bounded polling and checkpoints.
   A new analysis needs a fresh submission name and checkpoint directory.
   After an interruption inspect status/checkpoints before resubmitting.

   cga mr run --name first-run --user bob --language cpp \\
     --output-dir "$PWD/downloads/first-run" \\
     --log-dir "$PWD/checkpoints/first-run" \\
     --poll-seconds 5 --timeout-seconds 1800

6. Review findings and retain provenance

   cga si ingest --name first-run --output-dir "$PWD/findings"
   cga si verify first-run
   cga si info
   cga si list 10
   cga ex human --output "$PWD/results.md"
   cga ex llm --output "$PWD/results.json"
   cat "$PWD/results.md"
   cga status
   cga chain show -v
   cga tree show -v
   cga doctor

   Markdown is for human review; JSON retains structured evidence for
   LLMs and tools. Trace findings back to query, database, and submission.
   Successful execution may produce zero findings. Fprintf.ql is a
   pipeline demonstration, not proof of vulnerability detection.

7. View, reconnect, and stop

   Check the viewers started in step 3:

   cga serve status

   Reconnect at http://127.0.0.1:8599/ . In a new shell, return to this
   analysis directory. If viewers were stopped, cga serve start restarts
   them without rerunning the analysis; repeating start is idempotent.
   For a remote host, run this on your workstation, replacing user@host:

   ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 \\
     -L 8599:127.0.0.1:8599 user@host

   Reopen the same URL after reconnecting SSH. See REMOTE-CONNECTION.md.

   Stop viewers if started, then check and stop MRVA separately:

   cga serve stop
   cga mx check
   cga mx stop

   Stopping retains results and workflow history; it is not cleanup.

8. Prepare your own inputs when ready

   Database creation and query writing are independent inputs to analysis.
   Use a separate preparation workspace and chain, not the analysis state.
   The main preparation operations are:

   cga codeql check
   cga cve import /absolute/path/to/spec.json
   cga cve select
   cga cve expand
   cga src-prep plan
   cga src-prep fetch --output-dir "$PWD/sources"
   cga query-gen materialize --output-dir "$PWD/queries"
   cga query-gen index
   cga db plan --mode trace --output-dir "$PWD/jobs"
   cga db build --job /absolute/path/to/job.json --trace \\
     --output-dir "$PWD/databases"
   cga db validate query --query /absolute/path/to/validation.ql \\
     --output-dir "$PWD/validation"
   cga catalog create --output "$PWD/metadata.sql" \\
     --manifest "$PWD/manifest.json"

   This last block is a template, not a run-all script: initialize the
   separate workflow, supply real specifications/build jobs, and install
   source-specific build dependencies. Import its catalogue with
   cga dl getmeta and its query tree with cga ql index in the analysis
   workspace. Preparation state is never imported implicitly.
"""

GETTING_STARTED_READING = """\
Read in this order; paths are relative to the repository root:

  guides/introductory/cli-workflow.md
    Preparation/analysis boundaries and viewer lifecycle templates.
  cga/mrva-flow/README.md and mrva-flow.sh
    The concrete six-database Fprintf example, also runnable as one script.
  cga/sample-05/README.md
    Manually stepped two-user submission/status/download/ingestion example.
  cga/analysis/CVE-2016-9843/query-030/README.md
    Worked database preparation and explicit handoff; requires its stated
    architecture, toolchain, and inputs, not generic first-run defaults.
  cga/system-tests/README.md
    Fixed e2e scenarios and assertions, not a required onboarding sequence.
  cga -h and cga COMMAND -h
    Complete command reference and detailed command prerequisites.
"""

TOPICS = {
    ("assist",): HelpTopic(
        "Guide database building and query authoring in recorded Bash workflows.",
        "Use database-build (d) for fetch/build/index/export preparation, or\n"
        "query-writing (alias q) for C++ query authoring with prebuilt\n"
        "CodeQL databases. The top-level alias is a. This is independent of\n"
        "Bench experiments but reuses database/query-library operations and\n"
        "the same pinned CodeQL pack helper. No editor or MRVA service is\n"
        "started automatically.",
        ("cga a d -h", "cga a q start my-query", "cd my-query", "cga a q -h"),
    ),
    ("assist", "database-build"): HelpTopic(
        "Fetch sources, build databases, index, and export a collection.",
        "Inside an initialized preparation workflow, use fetch, build, index, and\n"
        "export. Missing common choices prompt on the terminal; explicit flags\n"
        "support scripts. Git refs and tar/ZIP inputs may name multiple versions.\n"
        "Build one or both bm-none/trace modes. --use-llm on fetch/build starts an\n"
        "executing recipe supervisor with retained attempts, logs, and repairs.\n"
        "Completed databases use upstream repository plus bundle SHA-256 identities.\n"
        "Preparation does not import analysis chooser state or start services.\n"
        "Complex recipes use src-prep manifests, db plan/build, and catalog directly.",
        ("cga init", "cga chain start --name database-build",
         "cga a d fetch --git https://github.com/hohn/codeql-dataflow-sql-injection --language cpp",
         "cga a d build --mode bm-none --mode trace --use-llm",
         "cga a d index", "cga a d export /data/toy-collection"),
    ),
    ("assist", "database-build", "fetch"): HelpTopic(
        "Acquire one or more named source versions.",
        "Use --git URL with repeated --ref LABEL=REF, or repeated --archive\n"
        "LABEL=URL_OR_PATH for tar/ZIP sources. Git defaults to current=HEAD;\n"
        "its owner/repository are inferred unless overridden. Archives require\n"
        "owner/repository choices. Supply --language or choose it interactively.\n"
        "Resolved Git commits, archive hashes, and source-tree hashes are retained.\n"
        "Verified completed acquisitions resume; changed choices require another\n"
        "workflow. --use-llm supervises acquisition prerequisites and repairs using\n"
        "the same source plumbing. Sources become fixed after build planning.",
        ("cga a d fetch --git https://github.com/hohn/codeql-dataflow-sql-injection --ref toy=master --language cpp --use-llm",
         "cga a d fetch --archive pre=/data/pre.tar.gz --archive post=/data/post.zip --owner local --repo toy --language cpp"),
        (("CGA_PREP_LLM_COMMAND", "LLM recipe runner argv, parsed without a shell; the JSON task prompt is appended as one argument. Defaults to copilot --silent --available-tools= --prompt. Existing permissions are not broadened."),),
    ),
    ("assist", "database-build", "build"): HelpTopic(
        "Build databases for each version and mode.",
        "Select repeated --mode bm-none/trace, or choose interactively. Trace needs\n"
        "--command unless --use-llm discovers the build from source documentation.\n"
        "The supervisor supplies preparation commands/build recipes; CGA executes\n"
        "them under normal caller permissions and feeds failed attempt logs back\n"
        "for repair. Each attempt has a disposable source copy. --llm-attempts\n"
        "bounds retries (default 3). Strict trace verification cannot be bypassed.\n"
        "Successful jobs are hash-verified and skipped on resume. Build choices\n"
        "are fixed once planned. Use plumbing manifests for per-version recipes.",
        ("cga a d build --mode bm-none --mode trace --use-llm",
         "cga a d build --mode trace --command ./build.sh"),
        (("CGA_DB_CODEQL", "CodeQL executable; otherwise CGA_PREP_CGADB_CODEQL, then codeql."),
         ("CGA_PREP_LLM_COMMAND", "Recipe runner; default copilot --silent --available-tools= --prompt. The task prompt is appended as one argv argument.")),
    ),
    ("assist", "database-build", "index"): HelpTopic(
        "Create and verify metadata.sql and its provenance manifest.",
        "Reuse catalog create/verify over this preparation workflow's builds.\n"
        "Require the complete planned matrix unless --allow-partial is explicit.\n"
        "Write a new immutable index directory inside preparation scratch.\n"
        "This does not import the catalogue into an analysis workflow.",
        ("cga a d index", "cga a d index --allow-partial"),
    ),
    ("assist", "database-build", "export"): HelpTopic(
        "Publish an indexed collection without starting its archive server.",
        "Copy database ZIPs, metadata.sql, and manifest.json into a new DIRECTORY.\n"
        "Preserve content identities and update archive locations and manifest\n"
        "hashes. --base-url supplies HTTP(S) result URLs; otherwise use exported\n"
        "local file URLs. The index must reflect all currently completed builds.\n"
        "Verify before publication. Serving and analysis import remain separate.\n"
        "Use catalog export --move only when literal relocation is required.",
        ("cga a d export /data/toy-collection",
         "cga ds start --directory /data/toy-collection --port 9080 --log /data/toy-server.log"),
    ),
    ("assist", "query-writing"): HelpTopic(
        "Author a query, stage drafts, and publish a validated query package.",
        "Run start DIRECTORY, cd there, then catalogue, select-databases,\n"
        "download, prepare, save NAME, and publish LIBRARY. Omitted choices\n"
        "prompt through the terminal; explicit arguments support replay.\n"
        "prepare extracts at least two user-chosen C++ databases, supplies\n"
        "Fprintf.ql and a pinned qlpack.yml, and generates a VS Code workspace.\n"
        "Scratch is resumable inside .cga/tmp/query-writing; publication copies\n"
        "only query/support sources and pack metadata to a permanent library.\n"
        "It requires CodeQL check-only compilation and refuses overwrites.\n"
        "Query application and MRVA lifecycle are separate later work.",
        ("cga a q start my-query", "cd my-query", "cga a q catalogue",
         "cga a q select-databases", "cga a q download", "cga a q prepare",
         "# Edit the printed workspace.", "cga a q save MyQuery",
         "cga a q publish /data/my-queries"),
    ),
    ("assist", "query-writing", "start"): HelpTopic(
        "Create a new named authoring directory and recorded workflow.",
        "DIRECTORY must not exist. Create its .cga workflow and query-writing\n"
        "chain, resumable scratch, and initially empty qlibdir. Print the cd\n"
        "command for later operations. No MRVA setup, reset, build, or editor\n"
        "launch occurs. Existing workflows and operator settings are preserved.",
        ("cga a q start my-query", "cd my-query", "cga a q catalogue"),
    ),
    ("assist", "query-writing", "catalogue"): HelpTopic(
        "Choose and import a prebuilt database catalogue.",
        "Supply a local metadata.sql path or URL, or choose interactively from\n"
        "known repository catalogues. Reuse db-lib getmeta and clear stale\n"
        "selection/download state. Catalogue changes are refused after prepare,\n"
        "when the editor's database selection has become fixed.",
        ("cga a q catalogue", "cga a q catalogue /data/databases/metadata.sql"),
    ),
    ("assist", "query-writing", "select-databases"): HelpTopic(
        "Select compatible C++ databases by original catalogue rowid.",
        "Display up to 100 matching rows with rowids, repository, version, and\n"
        "size. --search narrows that preview by a literal owner/repository/version\n"
        "substring. Enter at least two distinct rowids, or supply --rows.\n"
        "Select 2..100 distinct C++ databases, including versions of one repository, without\n"
        "downloading them. Prepared editor inputs cannot be changed.",
        ("cga a q select-databases --search file",
         "cga a q select-databases --rows 1 4"),
    ),
    ("assist", "query-writing", "download"): HelpTopic(
        "Download the selected database archives into authoring scratch.",
        "Reuse db-lib download and its content checks and progress reporting.\n"
        "Archives go under .cga/tmp/query-writing/archives and are retained for\n"
        "prepare and later shells. This does not start an archive or MRVA server.",
        ("cga a q download", "cga a q prepare"),
    ),
    ("assist", "query-writing", "prepare"): HelpTopic(
        "Prepare a CodeQL working tree with editor databases.",
        "Choose two or more databases from the downloaded selection, interactively\n"
        "or with --databases owner/repository ... . Extract each with codeql\n"
        "database unbundle into its own directory. Copy the supplied Fprintf.ql,\n"
        "initialize a qlpack.yml pinned to the installed CodeQL bundle, install\n"
        "its dependencies, and generate query.code-workspace and editor-databases.json.\n"
        "Print how to open VS Code and add those local database folders to the\n"
        "CodeQL extension; do not launch it. Existing working trees are refused.",
        ("cga a q prepare",
         "cga a q prepare --databases dsvpn/dsvpn file/file"),
        (("CGA_CGAQL_CODEQL", "CodeQL executable; default codeql. Pack dependency overrides match query-lib pack."),),
    ),
    ("assist", "query-writing", "save"): HelpTopic(
        "Stage and index a named query draft without requiring compilation.",
        "Use the working tree's Fprintf.ql or --source FILE, a root-level .ql\n"
        "in that tree. Save its source, .qll support modules, pinned manifest,\n"
        "and lockfile into scratch qlibdir/NAME. Unchanged starter @id/@name\n"
        "metadata is renamed for NAME. Re-saving an owned name replaces only\n"
        "its staging copy and retains the old draft in scratch history.\n"
        "Index the staging library; unfinished drafts are allowed. Nothing is\n"
        "published, packed, submitted, or executed.",
        ("cga a q save MyQuery", "cga a q save Refined --source /path/to/working/Refined.ql"),
    ),
    ("assist", "query-writing", "publish"): HelpTopic(
        "Validate and copy a staged query into a permanent source library.",
        "Choose a new or existing permanent LIBRARY directory. Use --name or\n"
        "the last saved draft. Validate a private copy using codeql query compile\n"
        "--check-only: this checks QL, not a C/C++ project build or query run.\n"
        "A failed check leaves the draft and destination unchanged. Refuse an\n"
        "existing destination package or duplicate query @id. Copy only the\n"
        "query/support files and pack metadata, then index permanent source\n"
        "paths for normal cga ql list/select/pack. Never publish editor databases.",
        ("cga a q publish /data/queries", "cga a q publish /data/queries --name MyQuery"),
        (("CGA_CGAQL_CODEQL", "CodeQL executable used for dependency resolution and check-only compilation; default codeql."),),
    ),
    (): HelpTopic(
        "Select, run, and inspect recorded CodeQL experiments.",
        "Use CGA to prepare inputs, select databases and queries, execute MRVA work,\n"
        "and retain results with immutable workflow history. Short and long command\n"
        "names are equivalent. Start with init and chain start; request -h on any\n"
        "command or nested subcommand for prerequisites, effects, and examples.\n"
        "Start with cga help sample 05 for a fixed, stepwise first analysis.\n"
        "Global options precede the command. Infrastructure lifecycle commands can\n"
        "affect shared ports, services, and PostgreSQL; inspect their help first.",
        ("mkdir my-analysis", "cd my-analysis", "cga init", "cga chain start --name baseline", "cga dl -h"),
        DISCOVERY + (
            ("CGA_OBJECT_STORE", "Override the workflow object store; --store takes precedence."),
            ("CGA_OUTPUT_JSON", "Set to 1 for structured inspection output, or use --json."),
            ("CGA_QUIET", "Set to 1 to suppress workflow progress messages, or use --quiet."),
        ),
    ),
    ("help",): HelpTopic(
        "Read tutorials, executable samples, or export offline help.",
        "Use overview for CGA's purpose, scale, provenance, and VM/LLM guidance.\n"
        "Use sample 05 for a fixed single-user analysis, one small step at a time.\n"
        "Sample help is read-only unless a step ends in run (alias r).\n"
        "The Start here tutorials have named, read-only chapter help: use\n"
        "bash-tutorial-sql, mrva-flow, bench-intro, shell-workflow,\n"
        "two-user-standalone, two-user-workflow, or zlib-study.\n"
        "Use getting-started for the longer command walkthrough, also\n"
        "available as cga -hs or cga -h -s. Use --export to capture the current\n"
        "CLI help and write a self-contained HTML file. Open\n"
        "it directly in a browser: no web server, Bench, MRVA, or active workflow\n"
        "is required. Select a command in the left outline to show its help above;\n"
        "click an immediate subcommand to inspect it below. Deeper commands are\n"
        "shown as shell help invocations. Browse alphabetical contents or task\n"
        "groups, or search all embedded help using plain text or a regex.\n"
        "docs/cga-help.html is the main CGA/MRVA entry point. Collapsible\n"
        "Start here and LLM start here groups link tutorials and focused guides;\n"
        "linked documents open separately and need the checkout's layout.\n"
        "make -C docs help rebuilds the browser and linked human HTML guides.\n"
        "Exporting requests help only and never\n"
        "executes the documented operations. Regenerate after CLI help changes.\n"
        "With no arguments, cga help still displays the top-level terminal help.",
        ("cga help overview", "cga help sample 05", "cga h s 05 00", "cga help --export cga-help.html"),
        (("CGA_QUIET", "Set to 1, or use global --quiet, to suppress export progress."),),
    ),
    ("help", "overview"): HelpTopic(
        "Understand CGA's purpose, scale, provenance, and operating model.",
        "Read Overview and Running for an introduction to CGA and MRVA,\n"
        "metadata and artifact tracking, and the recommended Linux VM and\n"
        "LLM-assisted workflow. This guide is read-only: displaying it never\n"
        "initializes a workflow, starts services, or records a step.",
        ("cga help overview", "cga help sample 05", "cga help getting-started"),
    ),
    ("help", "getting-started"): HelpTopic(
        "Run a first recorded CodeQL analysis and inspect its results.",
        "Read the Commands walkthrough in order: use prepared databases and the\n"
        "supplied Fprintf query, run MRVA, and inspect retained findings. Database\n"
        "creation is a later, separate activity. Commands shown here are text:\n"
        "displaying this guide never starts services, resets state, downloads\n"
        "inputs, or records workflow steps. cga -hs and cga -h -s print this same\n"
        "guide. Shell paths and default URLs assume the stated Linux setup;\n"
        "operator environment overrides remain effective.",
        ("cga help getting-started", "cga -h -s", "cga -hs", "cga mr run -h"),
    ),
    ("help", "sample"): HelpTopic(
        "Read or run a fixed, numbered sample recipe.",
        "Choose a sample number, then a step number or exact step name.\n"
        "Help displays the shell commands; only a trailing run or r executes\n"
        "them. The aliases are h for help and s for sample; sample-05 is also\n"
        "accepted as sample 05. No prefix abbreviations are accepted.",
        ("cga help sample 05", "cga h s 05 00", "cga h s 05 00 r"),
    ),
    ("help", "sample", "05"): HelpTopic(
        "Run Fprintf.ql on five prepared C++ databases, one step at a time.",
        "Use one user (bob), the supplied Fprintf.ql, and five fixed database\n"
        "archives downloaded from the repository catalogue. Execute the steps\n"
        "in listed order; repeat only status until succeeded. Step 00 explicitly\n"
        "creates the sample workspace and saves runtime environment overrides\n"
        "for later shells or Jupyter cells. An existing workspace is refused.\n\n"
        "Requires Linux and the host dependencies in INSTALL.md, including\n"
        "CodeQL with C++ libraries and DuckDB. Downloads require network and\n"
        "disk space. Preflight can reclaim ports; reset clears shared MRVA\n"
        "PostgreSQL state. Do not execute alongside Bench or another MRVA run.\n"
        "Display is always read-only. There is no run-all or automatic cleanup.\n"
        "Step 20 stops services while retaining history and results.",
        ("cga help sample 05 00", "cga h s 05 start r",
         "cga h s 05 13 r  # repeat until succeeded", "cga h s 05 20 r"),
    ),
    ("init",): HelpTopic(
        "Initialize a directory for a recorded CGA workflow.",
        "Create DIRECTORY if needed and initialize its .cga/ workflow metadata\n"
        "and object store. The directory must not already contain an initialized\n"
        "workflow. This does not start MRVA, select inputs, or start recording a\n"
        "chain: run cga chain start before commands you want recorded. Subsequent\n"
        "commands discover the workflow from this directory or its descendants.\n"
        "Relative filesystem store paths are resolved from the workflow directory.",
        ("mkdir my-analysis", "cd my-analysis", "cga init", "cga chain start --name baseline", "cga status"),
        (("CGA_OBJECT_STORE", "Initial filesystem path or HTTP object-store root, used when --store\n  is omitted. Defaults to .cga/objects in the workflow directory.\n  The chosen store is saved in the workflow configuration."),),
    ),
    ("root",): HelpTopic(
        "Print the current workflow's root directory.",
        "Discover the initialized workflow and print its absolute root path.\n"
        "This is read-only and does not require an active chain or running MRVA.",
        ("cga init my-analysis", "cga -C my-analysis root", "cga -C my-analysis status"),
        DISCOVERY,
    ),
    ("status",): HelpTopic(
        "Summarize workflow configuration and recorded progress.",
        "Show the workflow root, effective object store, current chain and head,\n"
        "and counts of steps, chains, and artifacts. This reads local workflow\n"
        "metadata; it does not poll MRVA jobs. Use cga mr status for job progress.",
        ("cga chain start --name baseline", "cga status", "cga --json status"),
        INSPECTION,
    ),
    ("doctor",): HelpTopic(
        "Check workflow metadata and referenced object integrity.",
        "Validate the initialized workflow and its retained objects. Print detected\n"
        "errors and return failure when verification fails; do not repair metadata\n"
        "or resubmit work. The configured object store must be reachable.",
        ("cga status", "cga doctor", "cga store verify"),
        STORE,
    ),
    ("chain",): HelpTopic(
        "Create, select, and inspect immutable workflow chains.",
        "Chains retain ordered CGAST states and command history. Starting a chain\n"
        "selects where subsequent recorded commands append; branching preserves\n"
        "earlier states instead of overwriting them. A workflow must be initialized.",
        ("cga init", "cga chain start --name baseline", "cga chain list", "cga chain show -v"),
        INSPECTION,
    ),
    ("chain", "start"): HelpTopic(
        "Start and select a new workflow chain.",
        "Create a new chain from empty state, or branch from --from REVISION.\n"
        "Print its chain ID and make it current for subsequent recorded commands.\n"
        "This does not start services or execute an analysis.",
        ("cga init", "cga chain start --name baseline", "cga dl getmeta metadata.sql", "cga chain show -v"),
        STORE,
    ),
    ("chain", "list"): HelpTopic(
        "List recorded chains and identify the current one.",
        "Show chain IDs, optional names, step counts, heads, and branch origins.\n"
        "An asterisk marks the selected chain. No state or selection is changed.",
        ("cga chain start --name baseline", "cga chain list", "cga chain show baseline"),
        INSPECTION,
    ),
    ("chain", "current"): HelpTopic(
        "Print the selected chain ID.",
        "Read the workflow HEAD and print the active chain ID. Fail if no chain\n"
        "has been selected; initialize a workflow and start a chain first.",
        ("cga chain start --name baseline", "cga chain current", "cga state show"),
        DISCOVERY,
    ),
    ("chain", "switch"): HelpTopic(
        "Select an existing chain for subsequent commands.",
        "Resolve CHAIN by ID or name and update the current chain and compatibility\n"
        "state. Existing immutable history is retained; no analysis is rerun.",
        ("cga chain list", "cga chain switch baseline", "cga state show"),
        STORE,
    ),
    ("chain", "show"): HelpTopic(
        "Inspect a chain's recorded command sequence.",
        "Show the named chain, or the current chain when omitted, with its origin,\n"
        "head, and ordered steps. Use -v for state-key changes and provenance;\n"
        "global --json returns the retained chain and node metadata.",
        ("cga chain list", "cga chain show -v", "cga tree show -v"),
        INSPECTION,
    ),
    ("chain", "rename"): HelpTopic(
        "Change a chain's human-readable name.",
        "Resolve the existing chain and change its name without rewriting recorded\n"
        "states or commands. Use the resulting name when switching or inspecting.",
        ("cga chain list", "cga chain rename cga_0 baseline", "cga chain show baseline"),
        DISCOVERY,
    ),
    ("state",): HelpTopic(
        "Inspect, compare, export, and import CGAST states.",
        "CGAST states reference selected inputs, submissions, and artifacts.\n"
        "Inspection and export read retained states; import creates a new chain\n"
        "with an imported JSON object. These operations do not run MRVA jobs.",
        ("cga state show", "cga state export -o state.json", "cga state validate"),
        INSPECTION,
    ),
    ("state", "show"): HelpTopic(
        "Print a retained CGAST state as JSON.",
        "Show REVISION, or the current chain's state when omitted. --raw omits the\n"
        "human revision label, as does global --json. Read-only; no job polling.",
        ("cga chain current", "cga state show --raw", "cga mr info"),
        INSPECTION,
    ),
    ("state", "diff"): HelpTopic(
        "Compare two retained CGAST states.",
        "Resolve LEFT and RIGHT revisions and print a unified diff of their sorted\n"
        "JSON states. This compares references and metadata, not artifact contents.",
        ("cga log", "cga state diff cga_0 cga_1", "cga chain show -v"),
        STORE,
    ),
    ("state", "validate"): HelpTopic(
        "Validate that a retained state is canonicalizable JSON.",
        "Load REVISION, or the current chain state, and check its canonical JSON\n"
        "representation. This is not a semantic check of job success or findings;\n"
        "use doctor for workflow/object integrity and mr verify for MRVA results.",
        ("cga state show", "cga state validate", "cga doctor"),
        STORE,
    ),
    ("state", "export"): HelpTopic(
        "Write a retained CGAST state to a JSON file.",
        "Export REVISION or the current state to --output, creating parent directories\n"
        "and replacing the destination atomically. The JSON contains references;\n"
        "it does not copy external databases or all referenced object-store bytes.",
        ("cga state validate", "cga state export -o state.json", "cga artifact list"),
        STORE,
    ),
    ("state", "import"): HelpTopic(
        "Import a CGAST JSON object into a new chain.",
        "Read FILE, require a JSON object, start a new chain, and record its imported\n"
        "state. Existing referenced paths and stores must still be usable; this does\n"
        "not reconstruct missing external inputs or execute the recorded commands.",
        ("cga state export -o state.json", "cga state import state.json --name imported", "cga state show"),
        STORE,
    ),
    ("step",): HelpTopic(
        "Inspect individual recorded steps and compare their states.",
        "Use node IDs from log or chain show to inspect retained command provenance\n"
        "and the CGAST produced by a step. No execution or mutation is performed.",
        ("cga log", "cga step show cga_0_dl_getmeta_0", "cga chain show -v"),
        INSPECTION,
    ),
    ("step", "show"): HelpTopic(
        "Show a recorded command step's provenance.",
        "Print NODE's command, chain, parent, timestamps, state object, and artifact\n"
        "count. Add -v to include its CGAST; global --json selects structured output.",
        ("cga log", "cga step show -v cga_0_dl_getmeta_0", "cga artifact list"),
        INSPECTION,
    ),
    ("step", "diff"): HelpTopic(
        "Diff the CGAST states produced by two steps.",
        "Resolve LEFT and RIGHT and print a unified JSON state diff. Use IDs from\n"
        "log or chain show. This does not compare process logs or SARIF contents.",
        ("cga log", "cga step diff cga_0_dl_getmeta_0 cga_0_dl_select_1", "cga tree show -v"),
        STORE,
    ),
    ("log",): HelpTopic(
        "Show recorded commands in chronological order.",
        "List successful recorded nodes for the current chain, or all chains with\n"
        "--all. --limit keeps only the last N entries. This reads workflow history,\n"
        "not live service logs; use mx logs for standalone MRVA logs.",
        ("cga status", "cga log --all --limit 10", "cga chain show -v"),
        INSPECTION,
    ),
    ("tree",): HelpTopic(
        "Display and export the workflow's chain forest.",
        "Render chain branching and optionally recorded commands/state changes.\n"
        "The forest comes from immutable workflow metadata, not running processes.",
        ("cga chain list", "cga tree show -v", "cga tree show --format html -o workflow.html"),
        STORE,
    ),
    ("tree", "show"): HelpTopic(
        "Render the workflow forest as text, Markdown, DOT, HTML, or PDF.",
        "Show chains and branch origins; -v includes steps and --control-flow focuses\n"
        "on command order. HTML/PDF require Graphviz dot and --output. Output files\n"
        "are written locally; this does not start a web viewer or alter the history.",
        ("cga chain show -v", "cga tree show -v", "cga tree show --format html -o workflow.html"),
        STORE,
    ),
    ("config",): HelpTopic(
        "Inspect and edit workflow configuration.",
        "Configuration is stored in .cga/config. Keys use dotted paths. Use store\n"
        "set rather than config set to change an object-store root with verification.",
        ("cga config list", "cga config get workflow.name", "cga config path"),
        DISCOVERY,
    ),
    ("config", "list"): HelpTopic(
        "Print the workflow configuration as JSON.",
        "Read .cga/config and show all persisted keys without changing them.\n"
        "Runtime environment overrides are not written into this configuration.",
        ("cga status", "cga config list", "cga store show"),
        DISCOVERY,
    ),
    ("config", "get"): HelpTopic(
        "Read one dotted workflow configuration key.",
        "Resolve KEY in the saved configuration. Scalars print as text and objects\n"
        "or arrays print as JSON. An unknown key is an explicit error.",
        ("cga config list", "cga config get workflow.name", "cga config path"),
        DISCOVERY,
    ),
    ("config", "set"): HelpTopic(
        "Set a writable workflow configuration key.",
        "Parse VALUE as JSON when possible, otherwise store it as a string. Dotted\n"
        "KEY paths create nested objects. Format version and object_store.root\n"
        "cannot be changed here; use store set for object-store migration.",
        ("cga config get workflow.name", "cga config set workflow.name experiment", "cga status"),
        DISCOVERY,
    ),
    ("config", "unset"): HelpTopic(
        "Remove an optional workflow configuration key.",
        "Delete an existing dotted KEY. Required format and object-store fields\n"
        "cannot be removed. This does not delete retained states or artifact bytes.",
        ("cga config set experiment.note temporary", "cga config unset experiment.note", "cga config list"),
        DISCOVERY,
    ),
    ("config", "path"): HelpTopic(
        "Print the workflow configuration file's absolute path.",
        "Discover the workflow and print its .cga/config location without changing\n"
        "the file or requiring an active chain.",
        ("cga root", "cga config path", "cga config list"),
        DISCOVERY,
    ),
    ("store",): HelpTopic(
        "Inspect, switch, and verify the workflow object store.",
        "The filesystem or HTTP store holds content-addressed workflow objects.\n"
        "Changing its root does not copy bytes; populate the destination before\n"
        "switching. Verification requires that the effective store is reachable.",
        ("cga store show", "cga store check", "cga store verify"),
        INSPECTION,
    ),
    ("store", "show"): HelpTopic(
        "Show configured and effective object-store roots.",
        "Report the saved root, effective root, backend, and whether an environment\n"
        "override is active. No objects are copied or configuration changed.",
        ("cga config list", "cga store show", "cga store check"),
        INSPECTION,
    ),
    ("store", "set"): HelpTopic(
        "Persist a new object-store root after checking references.",
        "Verify that ROOT contains the workflow's referenced objects, then update\n"
        "the saved configuration. This does not migrate bytes. --allow-missing\n"
        "bypasses the missing-object rejection and can leave history unreadable.",
        ("cga store show", "# Copy existing objects into /data/cga-objects first.", "cga store set /data/cga-objects", "cga store verify"),
        STORE,
    ),
    ("store", "check"): HelpTopic(
        "Check that the effective object store is usable.",
        "Verify one existing reference; when no references exist, write and verify\n"
        "an empty-state object. This is a connectivity/basic integrity check, not\n"
        "a complete verification of every referenced object.",
        ("cga store show", "cga store check", "cga store verify"),
        STORE,
    ),
    ("store", "verify"): HelpTopic(
        "Verify all distinct referenced workflow objects.",
        "Read and validate the content-addressed references in the manifest against\n"
        "the effective object store. Missing or corrupt objects cause an error;\n"
        "this does not repair or copy objects.",
        ("cga store show", "cga store verify", "cga doctor"),
        STORE,
    ),
    ("artifact",): HelpTopic(
        "Register and inspect durable content-addressed artifacts.",
        "Artifacts retain named files in the workflow object store. Registration\n"
        "copies file bytes into the store; inspection and materialization use the\n"
        "retained object rather than relying solely on the original source path.",
        ("cga artifact add report.json --name report", "cga artifact list", "cga artifact verify"),
        INSPECTION,
    ),
    ("artifact", "add"): HelpTopic(
        "Retain a file as a named workflow artifact.",
        "Read FILE, store its bytes by content hash, and register an artifact ID\n"
        "with its logical name and kind. The original source file is not removed.\n"
        "Large files consume object-store space as well as their source storage.",
        ("cga artifact add report.json --name report", "cga artifact list", "cga artifact verify"),
        STORE,
    ),
    ("artifact", "list"): HelpTopic(
        "List retained artifacts and their object-store keys.",
        "Show artifact IDs, kinds, byte counts, logical names, and storage keys.\n"
        "An optional CHAIN filters to artifacts associated with its recorded nodes.",
        ("cga artifact list", "cga artifact show artifact_0", "cga artifact path artifact_0"),
        INSPECTION,
    ),
    ("artifact", "show"): HelpTopic(
        "Print a retained artifact's manifest metadata.",
        "Resolve ARTIFACT and print its complete registration record as JSON.\n"
        "This does not display the artifact's contents or download remote bytes.",
        ("cga artifact list", "cga artifact show artifact_0", "cga artifact verify artifact_0"),
        DISCOVERY,
    ),
    ("artifact", "verify"): HelpTopic(
        "Check one or all retained artifacts against their content hashes.",
        "Verify ARTIFACT, or every registered artifact when omitted, using the\n"
        "effective object store. Missing or mismatched bytes cause failure.",
        ("cga artifact list", "cga artifact verify artifact_0", "cga doctor"),
        STORE,
    ),
    ("artifact", "path"): HelpTopic(
        "Print an artifact's local object path or remote URL.",
        "Resolve ARTIFACT and print its object-store location without copying it.\n"
        "Use materialize when an HTTP-backed artifact is needed as a local file.",
        ("cga artifact list", "cga artifact path artifact_0", "cga artifact materialize artifact_0 -o report.json"),
        STORE,
    ),
    ("artifact", "materialize"): HelpTopic(
        "Copy a retained artifact to a local destination.",
        "Resolve ARTIFACT in the effective store and materialize its bytes locally.\n"
        "Use --output for an explicit destination. This may read from an HTTP store\n"
        "and does not change the immutable artifact registration.",
        ("cga artifact list", "cga artifact materialize artifact_0 -o report.json", "cga artifact verify artifact_0"),
        STORE,
    ),
    ("db",): HelpTopic(
        "Plan, build, validate, and archive CodeQL databases.",
        "Use prepared sources to plan database builds, build a single database,\n"
        "validate it, or archive an existing database directory. Dedicated db-plan,\n"
        "db-build, and db-validate aliases invoke the same respective commands.\n"
        "Request help on a subcommand before preparing or executing a build.",
        ("cga sp info", "cga db plan -h", "cga db build -h", "cga db validate -h"),
    ),
    ("run",): HelpTopic(
        "Manage the analysis dashboard and its fragment services.",
        "Start, stop, inspect, build, or seed the analysis dashboard. With no action,\n"
        "start is selected. This launcher manages local viewer services; it is not\n"
        "the MRVA analysis job runner (mr run) or MRVA lifecycle controller (mx).\n"
        "Startup can build tools and seed sample state.",
        ("cga run start", "cga run status", "cga run stop"),
        RUN_ENV,
    ),
    ("serve",): HelpTopic(
        "Manage the gateway and all configured CGA viewers together.",
        "Start, inspect, or stop analysis/preparation dashboards, Unified Views,\n"
        "Bench and the gateway, including live checkout documentation on the\n"
        "same URL. Missing workspace state is reported as SKIP;\n"
        "startup never initializes workflows, seeds samples, starts MRVA, submits\n"
        "jobs, or prestarts assistants/editors. With no action, start is selected.\n"
        "--config accepts a JSON workspace map; paths are relative to that file.\n"
        "Without it, use the current workflow and existing legacy/sample state.\n"
        "Build, seed and outputs retain their explicit dashboard-only behavior.",
        ("cga serve start", "cga serve status", "cga serve outputs", "cga serve stop"),
        RUN_ENV + (
            ("CGA_SERVE_CONFIG", "Optional viewer workspace configuration JSON; see cgagateway/README.md."),
            ("CGA_SERVE_RUN_DIR", "Aggregate ownership records, binaries and logs; defaults to .run/viewers."),
            ("CGA_GATEWAY_PORT / CGA_GATEWAY_RUN_DIR", "Gateway port/runtime; defaults to 8599 / .run/gateway."),
            ("CGA_PREP_PAGE_PORT", "Preparation dashboard port; defaults to 8500."),
            ("CGA_PREP_SESSION", "Preparation session CGAST; defaults to CGA_PREP_TMPDIR/session.json."),
            ("CGA_PREP_RUN_DIR", "Preparation service PID/log directory; defaults to .run-prep."),
        ),
    ),
    ("public-html",): HelpTopic(
        "Prepare a static documentation publication and print its setup script.",
        "Publish documentation independently of the CGA gateway and viewers.\n"
        "The setup action clones the installed checkout's committed HEAD into\n"
        "$HOME/public_html/single-machine-mrva if needed, then prints a commented\n"
        "Debian/lighttpd Bash script to stdout. Only clone creation is automatic;\n"
        "book building, ACL changes, configuration installation and service\n"
        "changes require reviewing and running the printed script.",
        ("cga public-html setup > /tmp/cga-public-html.sh",
         "less /tmp/cga-public-html.sh",
         "bash /tmp/cga-public-html.sh"),
        (("HOME", "Home containing public_html; defaults to the current user's home."),),
    ),
    ("public-html", "setup"): HelpTopic(
        "Clone documentation if needed and print the remaining shell steps.",
        "Create an independent local clone of committed HEAD, not uncommitted\n"
        "changes or ignored artifacts. Reuse an existing CGA checkout without\n"
        "fetching, pulling, resetting or changing its files. Refuse non-checkout\n"
        "destinations and symlinks. Progress goes to stderr; stdout is only the\n"
        "documented Bash script. The script uses the current home/account,\n"
        "builds the optional book and configures Debian lighttpd with scoped\n"
        "permissions and access exclusions. It refuses to overwrite a differing\n"
        "existing lighttpd configuration. Setup itself never runs those steps,\n"
        "changes permissions or services, or records a workflow operation.",
        ("cga public-html setup > /tmp/cga-public-html.sh",
         "bash -n /tmp/cga-public-html.sh",
         "less /tmp/cga-public-html.sh",
         "bash /tmp/cga-public-html.sh"),
        (("HOME", "Publication parent: $HOME/public_html; the clone is single-machine-mrva."),),
    ),
    ("gateway",): HelpTopic(
        "Join the loopback viewers and session editors behind one URL.",
        "Run an independent loopback HTTP gateway on port 8599. Start builds its\n"
        "Go standard-library binary and starts only the gateway, not the viewers\n"
        "or MRVA. Stop signals only its recorded\n"
        "process identity. Direct viewer ports remain available for development.\n"
        "Forward just the gateway port over SSH and open its landing page.\n"
        "Overview, help and the optional built reference manual are served live\n"
        "from the checkout below /documentation/, even without viewer state.\n"
        "--config accepts a JSON object overriding documented route-prefix ports;\n"
        "see cgagateway/README.md. Editor routes follow live Bench discovery.",
        ("cga gateway start", "cga gateway status",
         "ssh -N -L 8599:127.0.0.1:8599 user@remote",
         "# Open http://127.0.0.1:8599/; reconnect with the same SSH command.",
         "cga gateway stop"),
        (("CGA_GATEWAY_PORT", "Gateway HTTP port; defaults to 8599."),
         ("CGA_GATEWAY_RUN_DIR", "Gateway binary, ownership record and log directory; defaults to .run/gateway."),
         ("CGA_PAGE_PORT / CGA_CGAUV_PORT / CGA_<COMPONENT>_PORT",
          "Existing analysis viewer port overrides; the gateway preserves them."),
         ("CGA_PREP_*_PORT", "Existing preparation dashboard/component port overrides."),
         ("PORT / DB_SERVER_PORT", "MRVA System View / archive port overrides; defaults to 8081 / 9080.")),
    ),
    ("uv",): HelpTopic(
        "View and search a unified, read-only workflow outline.",
        "Manage the Unified View web service or inspect its outline/search directly\n"
        "in the terminal. With no action, start is selected. Outline/search do not\n"
        "require a running web server. The viewer projects existing workflow state\n"
        "rather than executing jobs or changing selections.",
        ("cga uv outline", "cga uv start", "cga uv status", "cga uv stop"),
        UV_ENV,
    ),
    ("mu",): HelpTopic(
        "Serve the MRVA submission user-view fragments.",
        "Read named cgamr submissions from the shared session CGAST and expose\n"
        "overview/detail fragments for the analysis dashboard. This viewer does\n"
        "not submit jobs or poll the MRVA server itself.",
        ("cga mr info", "cga mu serve", "# Stop the foreground viewer with Ctrl-C."),
        (("CGA_CGAMU_PORT", "Fragment HTTP port; defaults to 8605."),
         ("CGA_SESSION", "CGAST file read on each request; otherwise CGA_ROOT/cga-tmp/session.json."),
         ("CGA_ROOT", "Collection root used for the default session path; defaults to the current directory.")),
    ),
    ("sv",): HelpTopic(
        "Serve the analysis dashboard's workflow-state header.",
        "Read the shared session CGAST and serve its workflow-state header fragment.\n"
        "This is the composite dashboard header, not MRVA's /sysview endpoint.",
        ("cga state show", "cga sv serve", "# Stop the foreground viewer with Ctrl-C."),
        (("CGA_CGASV_PORT", "Fragment HTTP port; defaults to 8601."),
         ("CGA_SESSION", "CGAST file read by the header; otherwise CGA_ROOT/cga-tmp/session.json."),
         ("CGA_ROOT", "Collection root used for the default session path; defaults to the current directory.")),
    ),
}

TOPICS.update(tutorial_topics())

for step in STEPS:
    TOPICS[("help", "sample", "05", step.number)] = HelpTopic(
        step.summary,
        "Display the Commands below without changing state. Append run or r\n"
        "to execute exactly this Bash block. Each invocation loads the saved\n"
        "workspace settings; no previous shell exports are required.\n\n"
        + step.outcome,
        (f"cga help sample 05 {step.number}",
         f"cga h s 05 {step.name} r"),
    )

for family in ("mu", "sv"):
    TOPICS[(family, "serve")] = TOPICS[(family,)]

for action, summary, description, example in (
    ("start", "Start the independent loopback viewer gateway.",
     "Build the standard-library Go proxy and start it on port 8599 (or --port).\n"
     "--config accepts documented route-prefix port overrides. Existing viewers\n"
     "remain independent; no workflow, editor, or MRVA service is started.\n"
     "Serve checkout documentation under /documentation/ on the same port.\n"
     "An existing gateway with matching settings is retained.",
     ("cga gateway start", "cga gateway start --config /path/to/gateway.json")),
    ("status", "Inspect the recorded gateway process and HTTP readiness.",
     "Check the recorded process identity and gateway health endpoint. A running\n"
     "gateway prints its URL and PID; no recorded live process prints stopped.\n"
     "This command does not start viewers or modify workflow state.",
     ("cga gateway status",)),
    ("stop", "Stop only the gateway's recorded process.",
     "Verify the recorded process identity before stopping the gateway. Other\n"
     "services, editors, workflows and experiment state are unaffected. A stopped\n"
     "gateway is harmless; a reused or unrecorded PID is never signalled.",
     ("cga gateway stop",)),
):
    TOPICS[("gateway", action)] = HelpTopic(
        summary, description, example, TOPICS[("gateway",)].environment)

for family in ("run", "serve"):
    environment = TOPICS[(family,)].environment
    for action, summary, description, examples in (
        ("start", "Start the dashboard services.",
         "Start the local dashboard and fragment services, building/seeding as needed.\n"
         "Existing listening services may be reused. This does not submit MRVA jobs.",
         (f"cga {family} start", f"cga {family} status", f"cga {family} stop")),
        ("stop", "Stop the dashboard services recorded by the launcher.",
         "Stop the dashboard processes identified by the launcher's PID files.\n"
         "This is viewer lifecycle, not cancellation of MRVA analysis jobs.",
         (f"cga {family} status", f"cga {family} stop", f"cga {family} start")),
        ("status", "Report whether dashboard services are responding.",
         "Probe the configured viewer ports and report service availability.\n"
         "No services are started and no analysis jobs are submitted.",
         (f"cga {family} start", f"cga {family} status", f"cga {family} stop")),
        ("build", "Build the analysis dashboard's required tools.",
         "Build the Go analysis fragment providers used by the dashboard launcher.\n"
         "This does not start viewer services or submit an MRVA analysis.",
         (f"cga {family} build", f"cga {family} start", f"cga {family} status")),
        ("seed", "Seed the dashboard's sample session state.",
         "Replace the launcher's session CGAST with sample state for experimentation.\n"
         "Existing viewer-session selections are overwritten. This does not select\n"
         "inputs for your recorded experiment or submit MRVA jobs.",
         (f"cga {family} seed", f"cga {family} start", f"cga {family} status")),
    ):
        TOPICS[(family, action)] = HelpTopic(summary, description, examples, environment)

for action, summary, description in (
    ("start", "Start the gateway and every configured viewer.",
     "Start the gateway with live documentation and launch viewers only against\n"
     "existing state; report unconfigured or absent\n"
     "state as SKIP. --config selects analysis, preparation, Bench and flow\n"
     "workspaces. Never seed samples, start MRVA or prestart assistants/editors.\n"
     "Matching owned processes are retained. Occupied foreign viewer ports are\n"
     "errors; an independently managed gateway is reused only with matching routes."),
    ("status", "Report managed viewer readiness and skipped profiles.",
     "Inspect recorded process identities and HTTP readiness. Previously skipped\n"
     "profiles remain visible. Missing managed services return failure; no services\n"
     "are started and no workflow state is modified."),
    ("stop", "Stop only viewers started by the aggregate launcher.",
     "Verify process identities before stopping owned viewers and their gateway.\n"
     "An independently started gateway is left running. MRVA, archive services\n"
     "and workflows are untouched. Bench shutdown closes its owned editors/shells.\n"
     "Stop/status use the ownership record, not paths in a possibly changed config."),
):
    TOPICS[("serve", action)] = HelpTopic(
        summary, description,
        ("cga serve start --config /path/to/viewers.json",
         "cga serve status", "cga serve stop"),
        TOPICS[("serve",)].environment)

TOPICS[("serve", "outputs")] = HelpTopic(
    "List retained preparation-dashboard outputs.",
    "Show preparation artifacts from the launcher's session CGAST without running\n"
    "new source fetches, database builds, or MRVA analyses.",
    ("cga serve seed", "cga serve outputs", "cga serve status"),
    TOPICS[("serve",)].environment,
)

for action, summary, description in (
    ("start", "Start the Unified View web service.",
     "Start the read-only workflow viewer on its configured port and print its URL.\n"
     "This does not start MRVA, select inputs, or submit jobs."),
    ("stop", "Stop the recorded Unified View process.",
     "Stop the viewer identified by its PID file and remove that file. Retain the\n"
     "workflow, immutable states, and analysis results."),
    ("status", "Check whether Unified View is responding.",
     "Probe the configured HTTP health endpoint. Return failure if the viewer is\n"
     "not responding; do not start a replacement service."),
):
    TOPICS[("uv", action)] = HelpTopic(
        summary, description,
        ("cga uv start", "cga uv status", "cga uv stop"),
        UV_ENV,
    )

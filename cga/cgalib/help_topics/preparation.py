"""Help for preparation filters, isolated services, and build campaigns."""

from command_help import HelpTopic


PREP_ENV = (
    ("CGA_PREP_ROOT", "Preparation collection root; defaults to the repository's cga directory. CGAST_ROOT takes precedence."),
    ("CGA_PREP_TMPDIR", "Preparation scratch directory; defaults to cga/cga-prep-tmp. CGAST_TMPDIR takes precedence."),
)
SESSION_ENV = PREP_ENV + (
    ("CGA_PREP_SESSION", "Dashboard session JSON; defaults to session.json under preparation scratch. CGAST_SESSION takes precedence."),
)
DB_ENV = PREP_ENV + (
    ("CGA_DB_CODEQL", "CodeQL executable for database builds and validation; defaults to CGA_PREP_CGADB_CODEQL, then codeql."),
    ("CGA_PREP_CGADB_CODEQL", "Compatibility executable setting, used only when CGA_DB_CODEQL is unset."),
)
LLM_ENV = (
    ("CGA_PREP_LLM_COMMAND", "LLM recipe runner argv parsed without a shell; the JSON task prompt is appended as one argument. Defaults to copilot --silent --available-tools= --prompt. No tool/path/trust permissions are broadened."),
)
CTL_ENV = (
    ("CGACTL_DATABASE_URL", "PostgreSQL DSN, overridden by --database-url. Otherwise psql uses the standard PGHOST, PGPORT, PGUSER, PGPASSWORD and PGDATABASE settings."),
    ("CGACTL_PSQL", "PostgreSQL client executable; defaults to psql."),
)
INCUS_ENV = (("CGACTL_INCUS", "Incus executable; defaults to incus, overridden by --incus."),)
PROMOTION_ENV = CTL_ENV + (
    ("CGACTL_CODEQL", "CodeQL executable for promotion verification; defaults to codeql, overridden by --codeql."),
)
MRVA_ENV = (
    ("PORT / SERVER_PORT", "MRVA listener port; PORT defaults to 8081 and supplies SERVER_PORT when unset."),
    ("POSTGRES_HOST / POSTGRES_PORT / POSTGRES_DB", "Existing PostgreSQL service; defaults to localhost, the locally selected PostgreSQL port (otherwise 5432), and mrvadev."),
    ("POSTGRES_USER / POSTGRES_PASSWORD", "PostgreSQL credentials; defaults to USER (otherwise postgres) and the local-development password mrva. PGPASSWORD is set from POSTGRES_PASSWORD."),
    ("MRVA_WORK_DIR / MRVA_TMP_DIR", "Runtime/artifact root and scratch/log root; defaults to /tmp/mrva-cgamx and /tmp/mrva-${RUN_TAG}, with RUN_TAG defaulting to cgamx."),
    ("MRVA_ARTIFACT_DIR / MRVA_QLDB_DIR", "Artifact and worker database directories; default to artifacts and qldbs under MRVA_WORK_DIR."),
    ("SERVER_LOG", "New server log path; defaults to server.log under MRVA_TMP_DIR. Existing logs are refused."),
    ("MRVA_DB_SERVER_URL / DB_SERVER_PORT", "Existing database archive service URL; defaults to http://127.0.0.1:9080, with its default port taken from DB_SERVER_PORT."),
    ("MRVA_STANDALONE_STORAGE", "Artifact backend; defaults to filesystem. For minio, the external object store must already be running."),
    ("MRVA_MINIO_ENDPOINT / MRVA_MINIO_ACCESS_KEY / MRVA_MINIO_SECRET_KEY", "MinIO connection settings when selected; defaults to localhost:9000 (MINIO_PORT), minioadmin and minioadmin. Development defaults are not production credentials."),
    ("MRVA_ENVSIM_AGENT_BINARY / CODEQL_CLI_PATH / CODEQL_JAVA_HOME", "Worker executable, CodeQL executable and JDK root; defaults to agent-commander-argo/mrvaagent in this repository, codeql from PATH, and /usr."),
    ("MRVA_CODEQL_THREADS / MRVA_POOL_MAX_WORKERS", "Defaults to two CodeQL threads and max(1, (host CPUs - 1) // threads) workers."),
    ("MRVA_POOL_SCALE_CHECK_SECONDS / MRVA_POOL_CLAIM_POLL_SECONDS", "Worker scaling and claim polling intervals; both default to 2 seconds."),
    ("MRVA_DBG_DUMP_SYSVIEW / MRVA_SYSVIEW_DUMP_PATH", "Optional sysview capture; disabled unless the first value is nonempty. Dump path defaults to sysview-dump."),
)


TOPICS: dict[tuple[str, ...], HelpTopic] = {
    ("cv",): HelpTopic(
        "import, select and expand CVE specifications",
        "Turn a versioned CVE JSON specification into deterministic preparation inputs. "
        "Import validates and normalizes the document; select chooses CVEs; expand creates "
        "vulnerable, patched and most-recent source work items. Human or external LLM "
        "authoring happens before import. These filters consume and emit preparation "
        "CGAST on stdin/stdout, not analysis chooser state.",
        ("cga cv import spec.json", "cga cv select --cve CVE-2016-9843", "cga cv expand", "cga sp plan"),
        PREP_ENV,
    ),
    ("cv", "import"): HelpTopic(
        "validate and store a CVE specification",
        "Read SPEC, validate its versioned CVE structure, normalize source/query definitions "
        "and resolve query paths relative to the specification. Write a new normalized "
        "JSON artifact and set cgacv-spec in preparation CGAST. No source download or LLM "
        "invocation occurs; select and expand are separate steps.",
        ("cga cv import spec.json", "cga cv validate", "cga cv select --cve CVE-2016-9843"),
        PREP_ENV,
    ),
    ("cv", "validate"): HelpTopic(
        "check a supplied or imported CVE specification",
        "Validate SPEC when provided, otherwise require the current cgacv-spec artifact. "
        "Report the number of valid CVEs on stderr without changing selection or creating "
        "source work items. The input CGAST passes through unchanged.",
        ("cga cv validate spec.json", "cga cv import spec.json", "cga cv validate", "cga cv select"),
        PREP_ENV,
    ),
    ("cv", "select"): HelpTopic(
        "select all imported CVEs or one CVE",
        "Require cgacv-spec from import. Select every CVE unless --cve names one "
        "(case-insensitive), write cgacv-selection and append selection history. An "
        "unmatched CVE fails. Selection alone does not fetch sources; expand next.",
        ("cga cv import spec.json", "cga cv select --cve CVE-2016-9843", "cga cv expand"),
        PREP_ENV,
    ),
    ("cv", "expand"): HelpTopic(
        "expand selected CVEs into source work items",
        "Require cgacv-selection and write cgacv-work-items with each selected CVE's "
        "vulnerable, patched and most-recent variants. Work items retain source, dependency, "
        "build and query metadata for source preparation and query materialization. "
        "No network access or build is performed.",
        ("cga cv select", "cga cv expand", "cga sp plan", "cga qg materialize --output-dir queries"),
        PREP_ENV,
    ),
    ("cv", "info"): HelpTopic(
        "show CVE preparation artifact paths",
        "Print the current cgacv-spec, cgacv-selection and cgacv-work-items paths, "
        "or '(none)' for missing artifacts, to stderr. Pass preparation CGAST through "
        "without selecting, validating or downloading anything.",
        ("cga cv import spec.json", "cga cv info", "cga cv select"),
        PREP_ENV,
    ),
    ("cv", "serve"): HelpTopic(
        "serve the CVE preparation dashboard fragment",
        "Run the CVE component HTTP fragment on port 8501 by default. The dashboard reads "
        "the preparation session file, not a separate analysis chooser. This is a "
        "foreground service; it does not import a specification or seed a session.",
        ("# Populate the preparation session before opening its dashboard.", "cga cv import spec.json", "cga cv serve"),
        SESSION_ENV + (("CGA_PREP_CGACV_PORT", "CVE fragment port; defaults to 8501."),),
    ),
    ("sp",): HelpTopic(
        "plan, fetch or adopt source trees",
        "Convert explicit source manifests or CVE work items into Git, tar/ZIP, or Debian acquisition plans, then fetch "
        "source trees. Alternatively adopt existing local trees from a manifest. Record "
        "cgasp-plan and cgasp-sources in preparation CGAST; dependency commands are "
        "preserved for database builds, not installed while fetching.",
        ("cga cv expand", "cga sp plan", "cga sp fetch --output-dir sources", "cga db plan --mode trace --output-dir jobs"),
        PREP_ENV,
    ),
    ("sp", "plan"): HelpTopic(
        "record source acquisition inputs and commands",
        "Read --manifest FILE with a nonempty items array, or require cgacv-work-items "
        "from cga cv expand. Items retain id, owner, repo, language, version and build "
        "metadata plus source.strategy (git/archive/debian-dsc), source.url and Git source.ref. "
        "Archive paths are relative to the manifest; source.sha256 optionally pins bytes. Write cgasp-plan with Git clone/"
        "detached-checkout or dget/dpkg-source commands for each variant and retain build "
        "dependencies. Planning does not execute those commands or change source trees.",
        ("cga cv expand", "cga sp plan", "cga sp fetch --output-dir sources"),
        PREP_ENV,
    ),
    ("sp", "fetch"): HelpTopic(
        "materialize planned source trees",
        "Use --manifest FILE, cgasp-plan, or cgacv-work-items. Fetch Git references, "
        "tar/ZIP archives, or Debian .dsc sources. Resolve commits and hash source trees; "
        "archive SHA-256 pins are verified and unsafe extraction paths are rejected. "
        "Existing destinations are refused unless --results FILE contains a matching "
        "verified acquisition to resume. --use-llm starts a recipe supervisor before "
        "acquisition and feeds failures back for up to --llm-attempts (default 3). "
        "Keep supervisor requests, recipes, commands, logs and outcomes under .attempts. "
        "Without --output-dir allocate preparation "
        "scratch. --dry-run records planned destinations without fetching or deleting them. "
        "Write per-item status to cgasp-sources; acquisition errors make the command fail.",
        ("cga sp plan", "cga sp fetch --output-dir fresh-sources --dry-run", "cga sp fetch --output-dir fresh-sources", "cga db plan --mode trace --output-dir jobs"),
        PREP_ENV + LLM_ENV,
    ),
    ("sp", "adopt"): HelpTopic(
        "register existing local sources without copying them",
        "Read a manifest object with a nonempty items array. Each item needs a unique safe "
        "id and an existing source_dir; relative paths resolve against the manifest. Hash "
        "each source tree and verify source_tree_sha256 when supplied. Preserve build "
        "metadata and record ready cgasp-sources. No source files are modified; database "
        "builds later create independent disposable copies.",
        ("# sources.json contains items with id, source_dir and build metadata.", "cga sp adopt --manifest sources.json", "cga db plan --mode bm-none --output-dir jobs"),
        PREP_ENV,
    ),
    ("sp", "info"): HelpTopic(
        "show source planning and materialization paths",
        "Print cgasp-plan and cgasp-sources paths, or '(none)', to stderr while passing "
        "preparation CGAST through unchanged. This inspects references without fetching "
        "or rehashing source trees.",
        ("cga sp fetch --output-dir sources --dry-run", "cga sp info"),
        PREP_ENV,
    ),
    ("sp", "serve"): HelpTopic(
        "serve the source preparation dashboard fragment",
        "Run the source component HTTP fragment on port 8502 by default, reading the "
        "preparation session JSON. The foreground service displays plans/results; "
        "starting it does not acquire sources or install dependencies.",
        ("cga sp plan", "cga sp serve"),
        SESSION_ENV + (("CGA_PREP_CGASP_PORT", "Source fragment port; defaults to 8502."),),
    ),
    ("db", "plan"): HelpTopic(
        "expand prepared sources into immutable database jobs",
        "Require cgasp-sources and an empty or new output directory. Write one "
        "cga.database-job.v1 file per source and unique --mode, plus jobs.json recorded "
        "as cgadbplan-jobs. Trace jobs require a build_command unless --use-llm "
        "records supervised command discovery. Architecture and repository "
        "suffix label the jobs; they do not configure a compiler or cross-build. Planning "
        "does not copy sources, install dependencies or invoke CodeQL.",
        ("cga sp adopt --manifest sources.json", "cga db plan --mode bm-none --mode trace --output-dir jobs", "cga db build --job jobs/JOB.json --trace --output-dir databases"),
        PREP_ENV,
    ),
    ("db", "plan", "info"): HelpTopic(
        "show the current database job manifest",
        "Print the cgadbplan-jobs path or '(none)' to stderr and pass preparation "
        "CGAST through unchanged. This inspects an existing plan without regenerating jobs.",
        ("cga db plan --mode trace --output-dir jobs", "cga db plan info"),
        PREP_ENV,
    ),
    ("db", "build"): HelpTopic(
        "build and bundle exactly one CodeQL database",
        "Require one planned job and the matching --trace or --bm-none mode. Copy ready "
        "sources into a new disposable workspace, execute the job's dependency commands "
        "(which may install packages), run CodeQL database create, then bundle an archive "
        "and append a durable record to cgadb-records. Trace mode requires intercepted "
        "process evidence and rejects source-scan fallback before bundling. Existing build "
        "deterministic workspaces or duplicate completed job IDs are refused. "
        "After bundling, the final repository is upstream name plus the full bundle "
        "SHA-256; version/mode labels remain provenance. --use-llm (or a supervised "
        "job) discovers dependencies/build commands from human documentation and "
        "repairs failed disposable attempts, bounded by --llm-attempts (default 3). "
        "The executor captures all commands and output; the LLM cannot declare an "
        "unverified database successful. --dry-run writes a planned "
        "record without copying sources or invoking tools. --resources attaches existing "
        "telemetry; it does not measure the build.",
        ("cga cq check --codeql /opt/codeql/codeql", "cga db plan --mode trace --output-dir jobs", "cga db build --job jobs/JOB.json --trace --output-dir databases", "cga db validate query --query smoke.ql --output-dir validation"),
        DB_ENV + LLM_ENV,
    ),
    ("db", "zip"): HelpTopic(
        "archive an existing CodeQL database without rebuilding",
        "Require a database directory containing codeql-database.yml. Write a ZIP with one "
        "top-level database directory, excluding symlinks, and append its path and SHA-256 "
        "to cgadb-archives. The output must lie outside the database directory. An existing "
        "output ZIP is replaced. No CodeQL build, upload or catalogue publication occurs.",
        ("cga db zip --db-dir databases/existing-db --output archives/existing-db.zip", "cga ds start --directory archives --port 9080 --log logs/archives.log"),
        PREP_ENV,
    ),
    ("db", "validate"): HelpTopic(
        "run explicit validation over built database records",
        "Use query to analyze databases referenced by cgadb-records and retain SARIF, "
        "query hashes and finding counts in cgadbvalidate-results. Use info to inspect "
        "the result manifest. Validation is separate from build and does not rebundle "
        "archives; a completed query is not proof of vulnerability-detection effectiveness.",
        ("cga db build --job jobs/JOB.json --trace --output-dir databases", "cga db validate query --query smoke.ql --output-dir validation", "cga db validate info"),
        DB_ENV,
    ),
    ("db", "validate", "query"): HelpTopic(
        "run one query against selected built databases",
        "Require an existing query, built cgadb-records and an empty or new output "
        "directory. Analyze every record unless repeated --record values select job IDs "
        "or owner/repo identities. Run CodeQL with --rerun, write per-record SARIF plus "
        "validations.json, and set cgadbvalidate-results with hashes and finding counts. "
        "Databases are not rebuilt or rebundled; analysis caches may be updated.",
        ("cga db build --job jobs/JOB.json --trace --output-dir databases", "cga db validate query --query smoke.ql --record JOB_ID --output-dir validation", "cga cat create --output metadata.sql --manifest manifest.json"),
        DB_ENV,
    ),
    ("db", "validate", "info"): HelpTopic(
        "show the database validation manifest path",
        "Print cgadbvalidate-results or '(none)' to stderr, preserving preparation "
        "CGAST. This does not execute a query or recheck previously generated SARIF.",
        ("cga db validate query --query smoke.ql --output-dir validation", "cga db validate info"),
        PREP_ENV,
    ),
    ("cat",): HelpTopic(
        "create, merge, verify and export database catalogues",
        "Publish built database records as a SQLite metadata catalogue and provenance "
        "manifest. Optionally merge preserved rows from a base catalogue after checking "
        "their archives. Store cgacatalog-catalog and cgacatalog-manifest in preparation "
        "state; analysis imports the resulting catalogue separately with cga dl getmeta.",
        ("cga cat create --output metadata.sql --manifest manifest.json", "cga cat verify --catalog metadata.sql --manifest manifest.json", "# In a separate analysis workflow:", "cga dl getmeta metadata.sql"),
        PREP_ENV,
    ),
    ("cat", "create"): HelpTopic(
        "publish built records as a SQLite catalogue and manifest",
        "Require cgadb-records containing built databases. Check archive hashes and "
        "retain source, extraction, toolchain and resource provenance; attach validation "
        "results when cgadbvalidate-results exists. Write --output and --manifest and "
        "record their paths. Existing output catalogue/manifest files are replaced, so "
        "choose dedicated paths. Planned dry-run records are not publishable.",
        ("cga db validate query --query smoke.ql --output-dir validation", "cga cat create --output metadata.sql --manifest manifest.json", "cga cat verify --catalog metadata.sql --manifest manifest.json"),
        PREP_ENV,
    ),
    ("cat", "merge"): HelpTopic(
        "merge verified generated and preserved catalogue records",
        "First verify the generated catalogue and its manifest. Select preserved rows "
        "using --base-query-file SQL, resolve each ZIP under --base-archive-root as "
        "owner/repo/owner_repo_db.zip, and verify size/hash before replacing untrusted "
        "result URLs with local file URLs. Optional descriptors must exactly match the "
        "selected repositories. Reject duplicate repositories. Write a new catalogue and "
        "manifest, replacing existing output files; keep input and output paths separate.",
        ("cga cat create --output generated.sql --manifest generated.json", "cga cat merge --catalog generated.sql --catalog-manifest generated.json --base-catalog preserved.sql --base-query-file selected.sql --base-archive-root databases --output metadata.sql --manifest manifest.json", "cga cat verify --catalog metadata.sql --manifest manifest.json"),
        PREP_ENV,
    ),
    ("cat", "verify"): HelpTopic(
        "verify a catalogue, manifest and their archives",
        "Check the catalogue SHA-256, row/manifest counts, exact repository membership, "
        "record equality, archive existence and archive hashes. On success set "
        "cgacatalog-catalog and cgacatalog-manifest and append verification history. "
        "Catalogue and archive bytes are not changed.",
        ("cga cat create --output metadata.sql --manifest manifest.json", "cga cat verify --catalog metadata.sql --manifest manifest.json", "# Import into a separate analysis workflow:", "cga dl getmeta metadata.sql"),
        PREP_ENV,
    ),
    ("cat", "export"): HelpTopic(
        "publish a verified database collection in a new directory",
        "Use --catalog/--manifest or current preparation references. Verify the input, "
        "copy archives into owner/repo/owner_repo_db.zip layout, and publish metadata.sql "
        "plus manifest.json by renaming a verified staging directory. Database identities "
        "include their bundle SHA-256; local URLs and manifest paths are relocated. "
        "--base-url instead writes HTTP(S) URLs without starting a service. Existing "
        "destinations are refused. --move removes original archives only after verified "
        "publication; original catalogue references then no longer resolve those archives.",
        ("cga cat export /data/collection",
         "cga cat export /data/http-collection --base-url http://127.0.0.1:9080",
         "cga ds start --directory /data/http-collection --port 9080 --log /data/archives.log"),
        PREP_ENV,
    ),
    ("cat", "info"): HelpTopic(
        "show preparation catalogue and manifest paths",
        "Print cgacatalog-catalog and cgacatalog-manifest paths, or '(none)', to stderr "
        "without re-verifying files or changing preparation CGAST.",
        ("cga cat verify --catalog metadata.sql --manifest manifest.json", "cga cat info"),
        PREP_ENV,
    ),
    ("cq",): HelpTopic(
        "check and record the CodeQL preparation toolchain",
        "Validate the selected CodeQL executable, optional exact version and host "
        "platform constraints, and required bundle files/packs. Record their hashes in "
        "cgacodeql-check. This check is independent of database planning and never "
        "installs CodeQL or builds a database.",
        ("cga cq check --codeql /opt/codeql/codeql --system Linux", "cga cq info", "cga db plan --mode trace --output-dir jobs"),
        PREP_ENV + (("CGA_CODEQL", "CodeQL executable; takes precedence over --codeql, otherwise defaults to codeql."),),
    ),
    ("cq", "check"): HelpTopic(
        "verify CodeQL version, platform and required file hashes",
        "Run CodeQL version and check --version, --system and any accepted --machine "
        "values. Hash each --require-file and each owner/name@version pack's qlpack.yml "
        "under the selected executable's sibling qlpacks tree. Use an explicit bundle "
        "path when checking packs. Write cgacodeql-check without installing tools, "
        "downloading packs or configuring later builds' executable selection.",
        ("cga cq check --codeql /opt/codeql/codeql --version 2.27.1 --system Linux --machine aarch64 --machine arm64 --pack codeql/cpp-all@12.1.1", "cga cq info", "CGA_DB_CODEQL=/opt/codeql/codeql cga db build --job jobs/JOB.json --trace --output-dir databases"),
        PREP_ENV + (("CGA_CODEQL", "Executable override, even when --codeql is supplied; fallback is --codeql, then codeql."),),
    ),
    ("cq", "info"): HelpTopic(
        "show the recorded CodeQL toolchain check path",
        "Print cgacodeql-check or '(none)' to stderr and preserve preparation CGAST. "
        "This reads the reference only; run check again to verify a changed installation.",
        ("cga cq check --codeql /opt/codeql/codeql", "cga cq info"),
        PREP_ENV,
    ),
    ("qg",): HelpTopic(
        "materialize and index queries from CVE specifications",
        "Use selected or expanded CVE query definitions to write a query library and "
        "preparation-only SQLite index. Preserve sibling .qll modules for path-backed "
        "queries. These filters do not change analysis query chooser state; hand the "
        "generated directory to cga ql index in a separate analysis workflow.",
        ("cga cv select", "cga qg materialize --output-dir queries", "cga qg index", "# In a separate analysis workflow:", "cga ql index queries"),
        PREP_ENV,
    ),
    ("qg", "materialize"): HelpTopic(
        "write CVE query definitions into a query directory",
        "Read queries from cgacv-work-items, falling back to cgacv-selection. Deduplicate "
        "matching query IDs and reject conflicting definitions. Copy path-backed queries "
        "and sibling .qll modules or write inline sources. --output-dir defaults to new "
        "preparation scratch; matching .ql destinations are overwritten, while conflicting "
        "support modules fail. Set cgaqg-querydir and a materialization manifest. This "
        "does not compile queries or create an analysis pack.",
        ("cga cv import spec.json", "cga cv select", "cga qg materialize --output-dir queries", "cga qg index"),
        PREP_ENV,
    ),
    ("qg", "index"): HelpTopic(
        "index the materialized preparation query library",
        "Require cgaqg-querydir from materialize and build a SQLite metadata index of "
        "its .ql queries. Fail when no queries are found; otherwise set cgaqg-index and "
        "append preparation history. Analysis still requires an explicit cga ql index "
        "of the query directory in its own workflow.",
        ("cga qg materialize --output-dir queries", "cga qg index", "# In a separate analysis workflow:", "cga ql index queries", "cga ql select"),
        PREP_ENV,
    ),
    ("qg", "info"): HelpTopic(
        "show materialized query and preparation index paths",
        "Print cgaqg-materialized, cgaqg-querydir and cgaqg-index paths, or '(none)', "
        "to stderr. Pass preparation CGAST through without materializing, compiling or "
        "selecting queries.",
        ("cga qg materialize --output-dir queries", "cga qg index", "cga qg info"),
        PREP_ENV,
    ),
    ("qg", "serve"): HelpTopic(
        "serve the query preparation dashboard fragment",
        "Run the query-generation HTTP fragment on port 8504 by default. Read the "
        "preparation session JSON to display materialization and index state. This "
        "foreground service does not create queries, index a library or pack a selection.",
        ("cga qg materialize --output-dir queries", "cga qg serve"),
        SESSION_ENV + (("CGA_PREP_CGAQG_PORT", "Query preparation fragment port; defaults to 8504."),),
    ),
    ("pg",): HelpTopic(
        "manage a private loopback-only PostgreSQL cluster",
        "Initialize, start, create databases in, check and stop an isolated development "
        "cluster. Commands consume/emit CGAST and only change cgapg state; selected "
        "paths, tools, user and port are retained there. Trust authentication permits "
        "any local user to connect. Never expose this cluster to a network or use it "
        "for production data. Stop preserves cluster files and logs; no reset, deletion "
        "or port reclamation is performed.",
        ("cga pg init --data-dir runtime/pgdata --bin-dir /usr/lib/postgresql/16/bin --port 55432", "cga pg start", "cga pg createdb mrvadev", "cga pg check", "cga pg stop"),
        PREP_ENV,
    ),
    ("pg", "init"): HelpTopic(
        "initialize a new private PostgreSQL cluster",
        "Require an absent --data-dir, PostgreSQL tools in --bin-dir, a free loopback "
        "port and no existing cgapg state. Run initdb with UTF-8, no locale and trust "
        "authentication; record paths, port and user (default study) in CGAST. The server "
        "is not started. Any local user can connect once started, so this is for isolated "
        "development only. Existing cluster directories are never overwritten.",
        ("cga pg init --data-dir runtime/pgdata --bin-dir /usr/lib/postgresql/16/bin --port 55432 --user study", "cga pg start", "cga pg createdb mrvadev"),
        PREP_ENV,
    ),
    ("pg", "start"): HelpTopic(
        "start the recorded private PostgreSQL cluster",
        "Require initialized cgapg state, no postmaster.pid and a free recorded port. "
        "Start with pg_ctl on 127.0.0.1 with Unix sockets disabled; record PID and Linux "
        "process identity. A failed launch is stopped if it created a postmaster.pid. "
        "This does not create application databases, reset tables or reclaim listeners.",
        ("cga pg init --data-dir runtime/pgdata --bin-dir /usr/lib/postgresql/16/bin --port 55432", "cga pg start", "cga pg createdb mrvadev", "cga pg check"),
        PREP_ENV,
    ),
    ("pg", "createdb"): HelpTopic(
        "create an application database in the private cluster",
        "Require a running PostgreSQL process matching its recorded cgapg identity. "
        "Run the recorded createdb executable over loopback with the stored port/user, "
        "then append NAME to the component's database list. An existing database is not "
        "dropped or reset; createdb errors are reported.",
        ("cga pg start", "cga pg createdb mrvadev", "cga pg check"),
        PREP_ENV,
    ),
    ("pg", "check"): HelpTopic(
        "check the recorded PostgreSQL process and readiness",
        "Require the live PID to match the recorded Linux process identity, then run "
        "pg_isready using the cluster's loopback connection settings. Preserve CGAST "
        "without initializing a cluster, starting a server or repairing a listener.",
        ("cga pg start", "cga pg check", "cga pg info"),
        PREP_ENV,
    ),
    ("pg", "stop"): HelpTopic(
        "stop only the recorded private PostgreSQL cluster",
        "Require cgapg state. If the recorded process identity is still live, run "
        "pg_ctl fast shutdown, disconnecting clients and rolling back active transactions; "
        "then mark the component stopped. Preserve the cluster and log. No unrelated "
        "listener is reclaimed and no database files are deleted.",
        ("# Stop dependent MRVA workers before their private database.", "cga ms stop", "cga pg stop", "cga pg info"),
        PREP_ENV,
    ),
    ("pg", "info"): HelpTopic(
        "show recorded private PostgreSQL settings",
        "Require cgapg state and print its stored paths, tools, port, user, databases "
        "and process identity to stderr. Pass CGAST through unchanged. This reports "
        "recorded state; use check to verify current readiness.",
        ("cga pg info", "cga pg check"),
        PREP_ENV,
    ),
    ("ds",): HelpTopic(
        "serve database archives to local MRVA workers",
        "Manage a loopback-only, unauthenticated Python HTTP server over a database "
        "archive directory. Commands consume/emit CGAST and only change cgadbserve "
        "state. This service does not build, select, download or evaluate databases. "
        "Starts refuse occupied ports and existing logs; stops preserve archives/logs.",
        ("cga ds start --directory qldbstore --port 9080 --log logs/archives.log", "cga ds check", "cga ds info", "cga ds stop"),
        PREP_ENV,
    ),
    ("ds", "start"): HelpTopic(
        "start a local database archive HTTP server",
        "Serve --directory on 127.0.0.1 at --port, creating the directory if needed. "
        "Require a free port and a new --log path; no existing listener is reclaimed "
        "and no log is overwritten. Record PID, Linux process identity, directory and "
        "port in cgadbserve state after HTTP readiness. Failed starts stop their own "
        "process. Point MRVA_DB_SERVER_URL at this service before starting MRVA.",
        ("cga ds start --directory qldbstore --port 9080 --log logs/archives.log", "cga ds check", "MRVA_DB_SERVER_URL=http://127.0.0.1:9080 cga ms start --binary server-commander/mrvaserver"),
        PREP_ENV,
    ),
    ("ds", "check"): HelpTopic(
        "verify the recorded archive server is reachable",
        "Require cgadbserve state, a matching live process identity and a successful "
        "HTTP request to its loopback port. This does not inspect ZIP contents or "
        "repair/start a missing server; CGAST passes through unchanged.",
        ("cga ds start --directory qldbstore --port 9080 --log logs/archives.log", "cga ds check"),
        PREP_ENV,
    ),
    ("ds", "stop"): HelpTopic(
        "stop the owned archive server without deleting archives",
        "Require cgadbserve state. Signal only the recorded Linux process identity and "
        "its owned process group, then mark the service stopped. Unrelated listeners "
        "are untouched; database ZIPs and logs remain. A later start must use a new log.",
        ("# Finish dependent MRVA work before stopping archive access.", "cga ms stop", "cga ds stop", "cga ds info"),
        PREP_ENV,
    ),
    ("ds", "info"): HelpTopic(
        "show the recorded archive server runtime",
        "Print cgadbserve's stored directory, port, log, PID and status to stderr, "
        "preserving CGAST. This does not verify liveness or archive contents; use check "
        "for an HTTP readiness check.",
        ("cga ds info", "cga ds check"),
        PREP_ENV,
    ),
    ("ms",): HelpTopic(
        "manage MRVA and its workers independently of other services",
        "Start, check and stop only the MRVA server/worker process group. PostgreSQL, "
        "the database archive server and any external object store must already be "
        "available. Commands consume/emit CGAST and only change cgamrva state. Unlike "
        "the combined cga mx lifecycle, these commands never reset tables, reclaim "
        "ports, build databases or submit queries. Stop preserves data and logs.",
        ("cga pg check", "cga ds check", "cga ms start --binary server-commander/mrvaserver", "cga ms check", "cga ms stop"),
        PREP_ENV + MRVA_ENV,
    ),
    ("ms", "start"): HelpTopic(
        "start the standalone MRVA server and workers",
        "Require an existing MRVA binary and available configured PostgreSQL, archive "
        "and optional object-store services. Reuse cga mx configuration defaults only "
        "when unset, launch standalone mode, wait for HTTP readiness and retain PID/"
        "Linux process identity in cgamrva. Refuse occupied ports and existing SERVER_LOG; "
        "failed starts stop their own process. This does not start dependencies, reclaim "
        "ports or clear data. Use explicit private-cluster credentials when applicable.",
        ("cga pg check", "cga ds check", "POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 POSTGRES_USER=study POSTGRES_DB=mrvadev MRVA_WORK_DIR=runtime/mrva MRVA_TMP_DIR=runtime/mrva-logs cga ms start --binary server-commander/mrvaserver", "cga ms check"),
        PREP_ENV + MRVA_ENV,
    ),
    ("ms", "check"): HelpTopic(
        "check MRVA readiness and non-benign log errors",
        "Require cgamrva state, a matching live process identity and successful HTTP "
        "readiness. Reject recorded log lines containing ERROR, panic or fatal except "
        "mrva-project-resolver warnings. This is a read-only gate, not a restart or "
        "database/query check.",
        ("# After starting the server with its dependencies:", "cga ms check", "cga ms info"),
        PREP_ENV,
    ),
    ("ms", "stop"): HelpTopic(
        "stop only the recorded MRVA server and workers",
        "Require cgamrva state. Signal the recorded Linux process identity and its "
        "owned process group, including workers, and mark the service stopped. "
        "In-flight work can be interrupted. PostgreSQL, archive service, object store, "
        "database files, artifacts and logs are preserved; no ports are reclaimed.",
        ("# Finish or checkpoint analyses before shutdown.", "cga ms check", "cga ms stop", "cga ds stop", "cga pg stop"),
        PREP_ENV,
    ),
    ("ms", "info"): HelpTopic(
        "show the recorded MRVA lifecycle runtime",
        "Print cgamrva's stored binary, work directory, archive URL, log, port and "
        "process identity to stderr. Preserve CGAST without contacting MRVA or its "
        "dependencies; use check to verify the live server and log gate.",
        ("cga ms info", "cga ms check"),
        PREP_ENV,
    ),
    ("ctl",): HelpTopic(
        "coordinate leased database-build campaigns",
        "Manage a PostgreSQL-backed job matrix, fenced builder leases, immutable "
        "attempt history, resource/snapshot configuration and trusted artifact promotion. "
        "Build judgment remains with workers in static, llm-repair or master-recovery "
        "lanes. Large sources, products, archives and telemetry stay in external files "
        "or container storage, not PostgreSQL. Most commands require the installed "
        "schema and psql; matrix and measure are local. Controller output is command "
        "JSON or text, not CGAST, except measure --cgast-filter preserves child stdout.",
        ("export CGACTL_DATABASE_URL=postgresql:///cgactl", "cga ctl db-init", "cga ctl matrix --cves-dir cga/examples/cves --toolchain-digest codeql:2.27.1 --output jobs.json", "cga ctl jobs-load jobs.json", "cga ctl status"),
        CTL_ENV,
    ),
    ("ctl", "db-init"): HelpTopic(
        "install or upgrade the controller schema",
        "Connect to an existing PostgreSQL database through psql and execute the "
        "bundled schema.sql, creating or upgrading controller tables, indexes, views "
        "and queue functions. This changes database schema; it does not create/start "
        "PostgreSQL, build sources or load a job matrix. Requires schema-management "
        "privileges. Existing campaign records are not a request for a reset.",
        ("export CGACTL_DATABASE_URL=postgresql:///cgactl", "cga ctl db-init", "cga ctl jobs-load jobs.json", "cga ctl status"),
        CTL_ENV,
    ),
    ("ctl", "matrix"): HelpTopic(
        "generate deterministic CVE variant and extraction jobs",
        "Read cve-*/spec.json under --cves-dir (default examples/cves relative to the "
        "working directory) and emit trace/none jobs for each variant. The toolchain "
        "digest is part of job identity. Default tree identity hashes prepared "
        "tmp/{vulnerable,fixed,current}/source trees beside each spec; descriptor identity "
        "permits planning before source preparation. Write JSON to stdout or replace "
        "--output. No database connection, fetching or build is performed.",
        ("# Prepare source trees before using the default tree identity.", "cga ctl matrix --cves-dir cga/examples/cves --toolchain-digest codeql:2.27.1 --output jobs.json", "cga ctl jobs-load jobs.json"),
    ),
    ("ctl", "jobs-load"): HelpTopic(
        "idempotently load a controller job manifest",
        "Read the manifest produced by matrix and load its jobs into the initialized "
        "controller database. Stable job identities permit repeated loads without "
        "duplicating work. This changes queue records but does not claim jobs, reset "
        "attempt history or run builds; configure snapshots/resources before workers claim.",
        ("cga ctl db-init", "cga ctl matrix --cves-dir cga/examples/cves --toolchain-digest codeql:2.27.1 --output jobs.json", "cga ctl jobs-load jobs.json", "cga ctl status"),
        CTL_ENV,
    ),
    ("ctl", "builder-register"): HelpTopic(
        "register or refresh a builder identity",
        "Store the named builder and optional metadata JSON in PostgreSQL. Metadata "
        "accepts inline JSON or @file. This does not create a container or acquire a "
        "job; claim also registers/refreshes the builder when called.",
        ("cga ctl builder-register --builder build-01 --metadata '{\"architecture\":\"arm64\",\"container\":\"ubu\"}'", "cga ctl claim --builder build-01 --lane static"),
        CTL_ENV,
    ),
    ("ctl", "claim"): HelpTopic(
        "atomically lease at most one eligible job",
        "Register/refresh the builder and claim one queued job from the selected lane "
        "(static by default), respecting profile concurrency and exclusive-host fencing. "
        "Emit a JSON job with job_id and a fresh lease_token, or no claim when none is "
        "eligible. The lease defaults to 300 seconds. Save the returned identity/token "
        "for prepare, phase, renew and finish; claim does not launch a build.",
        ("cga ctl jobs-load jobs.json", "# Configure the lane's registered snapshot/resource profile first.", "cga ctl claim --builder build-01 --lane static", "# Use JOB and TOKEN from the response.", "cga ctl container-prepare --builder build-01 --job-id JOB --lease-token TOKEN --container ubu"),
        CTL_ENV,
    ),
    ("ctl", "renew"): HelpTopic(
        "extend a current builder's fenced lease",
        "Require the job ID, builder and lease token returned by claim. Extend the "
        "current unexpired lease by --lease-seconds (default 300) and emit the database "
        "response. A stale or wrong token cannot renew another attempt. Workers must "
        "renew during long phases; this does not retry or restart a job.",
        ("cga ctl claim --builder build-01", "# Use JOB and TOKEN returned by claim.", "cga ctl renew --builder build-01 --job-id JOB --lease-token TOKEN --lease-seconds 300"),
        CTL_ENV,
    ),
    ("ctl", "phase"): HelpTopic(
        "record a leased attempt's current build phase",
        "Require a current job lease, matching builder and token. Record preparing, "
        "building or validating in controller state and emit the updated response. "
        "This is bookkeeping, not a build command or lease renewal; perform the work "
        "and renew independently.",
        ("# After claim and container-prepare, using their JOB and TOKEN:", "cga ctl phase --builder build-01 --job-id JOB --lease-token TOKEN --status building", "cga ctl renew --builder build-01 --job-id JOB --lease-token TOKEN"),
        CTL_ENV,
    ),
    ("ctl", "finish"): HelpTopic(
        "close a fenced attempt with a terminal result",
        "Require the current builder/job/token lease and a terminal status. Store "
        "--result JSON (inline or @file) as immutable attempt provenance and release "
        "the lease. Success queues trusted host-side promotion; failures stop for "
        "explicit recovery. This does not verify or install database archives itself; "
        "successful results must describe durable artifact references for promotion.",
        ("# After building and validating under a live lease:", "cga ctl finish --builder build-01 --job-id JOB --lease-token TOKEN --status succeeded --result @result.json", "cga ctl promote-auto --collection db-collection.local --once"),
        CTL_ENV,
    ),
    ("ctl", "retry"): HelpTopic(
        "explicitly requeue one terminal job",
        "Authorize another attempt for a terminal job and record the required reason. "
        "Retain previous immutable attempts rather than overwriting failure evidence. "
        "This changes scheduling state; it neither repairs source code nor runs the "
        "job. Use sweep for a deliberate batch transition into a recovery lane.",
        ("cga ctl failures --output failures.json", "cga ctl retry --job-id JOB --reason 'dependency issue corrected'", "cga ctl claim --builder build-01"),
        CTL_ENV,
    ),
    ("ctl", "sweep"): HelpTopic(
        "advance terminal failures into an explicit recovery lane",
        "Requeue up to --limit failures (default 100) from static to llm-repair, "
        "llm-repair to master-recovery, or within master-recovery, recording a required reason. Preserve attempt "
        "history and optionally assign a new resource profile, base snapshot or "
        "exclusive-host setting. This authorizes future attempts; it does not perform "
        "LLM repair. Export failures and review the recovery scope first.",
        ("cga ctl failures --disposition awaiting-llm --output static-failures.json", "cga ctl sweep --from-lane static --to-lane llm-repair --reason 'reviewed static failures' --limit 10", "cga ctl claim --builder repair-01 --lane llm-repair"),
        CTL_ENV,
    ),
    ("ctl", "job-config"): HelpTopic(
        "configure one queued job's lane and execution resources",
        "Assign a lane, registered resource profile (default default), optional base "
        "snapshot and exclusive-host flag to one queued job. This changes scheduling "
        "configuration, not an already-running container or the immutable job identity. "
        "Register snapshot/profile inputs before assigning them.",
        ("cga ctl snapshot-register --snapshot-id clean --container ubu --snapshot clean-v1 --toolchain-digest codeql:2.27.1", "cga ctl resource-profile-set --name normal --cpu 8 --memory-bytes 17179869184", "cga ctl job-config --job-id JOB --lane static --resource-profile normal --base-snapshot clean"),
        CTL_ENV,
    ),
    ("ctl", "jobs-config"): HelpTopic(
        "configure a bounded set of queued jobs in one lane",
        "Assign a registered resource profile, required base snapshot and optional "
        "exclusive-host policy to queued jobs in the selected lane, up to --limit "
        "(default 100000). Existing active attempts are not reconfigured. This changes "
        "queue policy without restoring containers or launching builds.",
        ("# Register clean and normal before assigning them.", "cga ctl jobs-config --lane static --resource-profile normal --base-snapshot clean --limit 100", "cga ctl claim --builder build-01 --lane static"),
        CTL_ENV,
    ),
    ("ctl", "snapshot-register"): HelpTopic(
        "register an existing immutable Incus baseline",
        "Query Incus to verify that the container snapshot exists, then store its "
        "identity, toolchain digest, observed creation/stateful metadata and supplied "
        "metadata in PostgreSQL. Snapshot creation is an operator prerequisite. "
        "Registration does not create, restore or mutate the snapshot/container; "
        "container-prepare later verifies its toolchain against the job.",
        ("# Create and inspect ubu/clean-v1 before registration.", "cga ctl snapshot-register --snapshot-id clean --container ubu --snapshot clean-v1 --toolchain-digest codeql:2.27.1", "cga ctl jobs-config --lane static --base-snapshot clean"),
        CTL_ENV + INCUS_ENV,
    ),
    ("ctl", "resource-profile-set"): HelpTopic(
        "store campaign resource limits and concurrency policy",
        "Create or update a named controller resource profile with optional CPU, "
        "memory/disk byte limits, maximum concurrency, exclusive-host scheduling and "
        "JSON metadata. Claim enforces concurrency; container-prepare caps requested "
        "limits to retain host reserves and applies them to Incus. Setting a profile "
        "does not immediately resize running containers.",
        ("cga ctl resource-profile-set --name normal --cpu 8 --memory-bytes 17179869184 --max-concurrent 3", "cga ctl jobs-config --lane static --resource-profile normal --base-snapshot clean"),
        CTL_ENV,
    ),
    ("ctl", "container-prepare"): HelpTopic(
        "restore and start a leased builder with fenced resources",
        "Require a live builder/job/token lease and an active registered snapshot for "
        "the same container and toolchain. Force-stop a running container, restore the "
        "baseline (discarding changes since that snapshot), apply resource limits capped "
        "by host/storage capacity, then start it. Record effective environment on the "
        "attempt. This is destructive to unpreserved container work; export needed "
        "artifacts first. Host reserves cannot fall below 1 CPU, 1 GiB RAM and 5 GiB disk.",
        ("cga ctl claim --builder build-01 --lane static", "# Save returned JOB/TOKEN; ensure ubu contains no unpreserved work.", "cga ctl container-prepare --builder build-01 --job-id JOB --lease-token TOKEN --container ubu", "cga ctl phase --builder build-01 --job-id JOB --lease-token TOKEN --status building"),
        CTL_ENV + INCUS_ENV + (
            ("CGACTL_HOST_RESERVE_CPU", "Host CPU reserve; defaults to 2, overridden by --reserve-cpu."),
            ("CGACTL_HOST_RESERVE_MEMORY_BYTES", "Host RAM reserve; defaults to 4294967296 (4 GiB), overridden by --reserve-memory-bytes."),
            ("CGACTL_HOST_RESERVE_DISK_BYTES", "Storage reserve; defaults to 21474836480 (20 GiB), overridden by --reserve-disk-bytes."),
        ),
    ),
    ("ctl", "promote"): HelpTopic(
        "verify and publish a successful job's artifacts",
        "Require a successful controller result with durable file:// or incus:// "
        "artifact references and available CodeQL. Fetch the archive, verify size and "
        "SHA-256, unbundle/resolve it, atomically install its collision-safe qldbstore "
        "identity, preserve sidecar provenance and declared artifacts, and update "
        "metadata.sql. This writes the collection and promotion records; it does not "
        "rebuild sources or submit an analysis. Run the trusted promoter on the host.",
        ("cga ctl finish --builder build-01 --job-id JOB --lease-token TOKEN --status succeeded --result @result.json", "cga ctl promote --job-id JOB --collection db-collection.local", "cga ctl collection-status --collection db-collection.local --verify"),
        PROMOTION_ENV,
    ),
    ("ctl", "promote-auto"): HelpTopic(
        "process the host-side successful-job promotion queue",
        "Requeue stale promotion claims, then claim and verify queued successful "
        "artifacts using the same checks as promote. Persist archives, provenance and "
        "catalogue updates outside PostgreSQL. --once processes at most one claim and "
        "prints its JSON result; otherwise poll continuously (default interval 5 "
        "seconds). Promotion failures are recorded separately from build failures.",
        ("# Run after successful jobs have finished with artifact references.", "cga ctl promote-auto --collection db-collection.local --once", "cga ctl collection-reconcile --collection db-collection.local"),
        PROMOTION_ENV,
    ),
    ("ctl", "collection-status"): HelpTopic(
        "summarize the promoted on-disk database collection",
        "Read the collection catalogue and provenance to summarize published "
        "databases. --verify additionally hashes archives. Emit JSON without changing "
        "collection bytes or queue state. This is local inspection and requires no "
        "database connection; collection-reconcile also compares controller successes.",
        ("cga ctl collection-status --collection db-collection.local --verify", "cga ctl collection-reconcile --collection db-collection.local"),
    ),
    ("ctl", "collection-reconcile"): HelpTopic(
        "compare controller successes with promoted collection evidence",
        "Read successful controller jobs and the configured on-disk collection, "
        "checking which successful results are represented by published evidence. "
        "Emit an audit report without repairing, deleting or promoting anything. "
        "Requires PostgreSQL access and readable collection files.",
        ("cga ctl collection-status --collection db-collection.local --verify", "cga ctl collection-reconcile --collection db-collection.local"),
        CTL_ENV,
    ),
    ("ctl", "requeue-expired"): HelpTopic(
        "requeue attempts whose builder leases expired",
        "Find expired active leases in PostgreSQL, record their abandoned attempts "
        "and make jobs eligible for a later claim. This changes queue state and "
        "fences stale builders; it does not kill their processes or delete artifacts. "
        "Run periodically while workers renew active leases.",
        ("cga ctl status", "cga ctl requeue-expired", "cga ctl status --json"),
        CTL_ENV,
    ),
    ("ctl", "status"): HelpTopic(
        "report controller campaign status",
        "Query the controller snapshot and print sorted job counts by default. "
        "--json emits the full snapshot used by the dashboard. This requires the "
        "installed schema and PostgreSQL connection but does not claim, retry, "
        "promote or otherwise mutate jobs.",
        ("cga ctl jobs-load jobs.json", "cga ctl status", "cga ctl status --json"),
        CTL_ENV,
    ),
    ("ctl", "failures"): HelpTopic(
        "export recovery inputs with immutable attempt history",
        "Select jobs awaiting LLM repair or escalated recovery, optionally filtering "
        "by disposition and execution lane. Emit each job, latest terminal attempt "
        "and complete ordered attempt history as JSON to stdout or replace --output. "
        "Review this report before authorizing a sweep; export does not retry jobs "
        "or run an LLM.",
        ("cga ctl failures --disposition awaiting-llm --output static-failures.json", "cga ctl sweep --from-lane static --to-lane llm-repair --reason 'reviewed failures'"),
        CTL_ENV,
    ),
    ("ctl", "serve"): HelpTopic(
        "serve a read-only build campaign dashboard",
        "Run the foreground controller HTTP dashboard over PostgreSQL campaign "
        "snapshots and the configured collection root. Serve GET-only health, static, "
        "snapshot and collection-file routes; no mutation API or build execution is "
        "exposed. Default bind is 127.0.0.1:8520. This starts neither PostgreSQL nor "
        "workers and does not install the controller schema.",
        ("cga ctl db-init", "cga ctl status", "cga ctl serve --collection db-collection.local"),
        CTL_ENV + (
            ("CGACTL_HOST", "Dashboard bind address; defaults to 127.0.0.1, overridden by --host."),
            ("CGACTL_PORT", "Dashboard port; defaults to 8520, overridden by --port."),
        ),
    ),
    ("ctl", "measure"): HelpTopic(
        "run a command with process-group resource telemetry",
        "Execute argv after --, sampling aggregate process-group CPU, RSS and I/O "
        "at --interval (default 1 second, minimum 0.2). Write resource_samples.jsonl, "
        "resource_summary.json and resource_report.html under --output-dir; existing "
        "files and an optional --log are overwritten. Return the child's exit code. "
        "--cgast-filter leaves child stdout untouched and emits summary JSON on stderr, "
        "preserving JSON filter pipelines. No controller database connection is needed; "
        "the child retains all its own side effects.",
        ("# Require a planned trace job and a usable CodeQL toolchain.", "mkdir -p logs", "cga ctl measure --cgast-filter --output-dir resources/JOB --log logs/JOB.log -- cga db build --job jobs/JOB.json --trace --output-dir databases --resources resources/JOB", "cga cat create --output metadata.sql --manifest manifest.json"),
    ),
}

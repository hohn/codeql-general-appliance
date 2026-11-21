# CGA Bench

For a shorter usage outline, see the
[introductory Bench guide](../../guides/introductory/bench.md). This document
remains the detailed reference.

`cga bench` is an experiment workbench, not another MRVA pipeline. Each
experiment holds an append-only, one-based session array. Every session has the same
four cells: **D** (database selection), **Q** (accepted query pack), **J** (MRVA
submission), and **R** (frozen results). Comparison **E.C** is a separate,
explicitly invoked view.
Selecting a cell replaces a fixed detail panel, never expands a tree.
The browser consumes prebuilt CodeQL databases through indexed SQLite catalogues;
its input-authoring workflow focuses on writing and refining queries.

Commands are standard-library Python CGAST filters with human output on stderr.
The dispatcher records them in an initialized `.cga` workflow. Direct
`bin/cgabench` use retains JSON-in/JSON-out composition.

The human UI contains named actions and selectable tables, not general command
forms or raw state dumps. The explicit VS Code launcher and the advanced
read-only SQL panel are exceptions. Detailed state, command access, source, and
provenance remain available to LLM clients through the APIs below.

## Experiment purpose and contract (humans and LLMs)

Each experiment studies **exactly one changing input**, never database and query
changes together:

| Experiment mode  | Fixed input                              | Changing input                                                |
| ---------------- | ---------------------------------------- | ------------------------------------------------------------- |
| Query changes    | Database selection and database contents | Existing, copied, written, or refined queries                 |
| Database changes | Accepted query selection and query pack  | Selection of existing indexed databases or database revisions |

**Session 1 (S1) is the reference session** in both modes. The Sessions grid
represents either experiment type using the same D/Q/J/R cells. Humans and LLMs
prepare only D and Q. J and R are derived by running the session: they are not
user-authored inputs and must not be cloned into a later session.

Comparison is a separate, later operation in **Comparison**. It runs only on an
explicit comparison action, never because an input was edited, a session was
added/run/completed, or the section was expanded. **View comparison** displays
existing comparison evidence without recomputing it. Experimental comparisons
use S1 as the baseline and require its completed results.

### Session actions

Later sessions clone/reference **exactly one** accepted input from a prior
session: D for query-change experiments, or Q for database-change experiments.
They do not clone both inputs, jobs, or results.

| Input row  | Query-change experiment                   | Database-change experiment            |
| ---------- | ----------------------------------------- | ------------------------------------- |
| Database D | Clone/reference the fixed database input  | Edit the database selection           |
| Query Q    | Edit, copy, write, or refine query source | Clone/reference the fixed query input |

Here, **Edit database** means changing a selection of prebuilt, indexed
databases, not building databases inside Bench. **Edit query** can begin with a
session-local copy of an existing query's source. Copying editable source is
distinct from cloning an accepted, fixed query artifact.

Database identities retain MRVA's `owner/repository` format. The repository
name includes a content hash, so revisions, architecture, build mode, and other
content changes have distinct identities. Bench rejects different bytes under
an already accepted identity and does not force-overwrite cached downloads.

The same contract applies to both human and LLM interfaces:

- Select one experiment mode in the header's **Mode** menu; S1 is marked
  **Reference**. Choosing a mode validates it immediately and updates the
  Sessions guidance. Both choices appear directly in the menu, with a checkmark
  beside the selected mode; there is no nested selector or validation button.
  The mode cannot change after sessions exist.
- **Add session** creates a variant with only the fixed input inherited,
  defaulting to S1. This is enabled after S1's fixed input is accepted; S1's results
  need not be complete merely to prepare another session.
- **Clone...** on the fixed D/Q row and **Edit** on the
  changing row. S1 establishes both original inputs; later sessions cannot edit
  the fixed side or clone both sides. S1's fixed input locks when variants exist.
  J/R remain inspectable, derived cells.
- Clones reference accepted snapshots, not mutable workspace links. They reuse
  database archives/query packs without copying large files and record the source
  session, input stage, and content digests. A prior-session source must have
  the same fixed input as S1.
- Bench validates the fixed-input invariant in CLI/API operations, before running,
  and before comparison; UI controls alone are insufficient. Submitted input
  and completed evidence remain immutable.
- Automatic advancement is preserved: accepting the second ready input starts
  analysis, subject to the fixed-input validation. Comparison remains a
  separate, explicit action; `--no-advance` still defers analysis.
- Comparison always includes completed S1 as baseline and retains selected
  result snapshots and provenance. Revisiting or expanding Comparison never
  executes it.
- Explicit mode selection and validation are required before further mutations of
  existing experiments. These are disposable prototypes, so no automatic
  migration or legacy behavior exemption is needed; do not silently classify
  or delete them.

Choose a mode at initialization with `init NAME --mode query-changes` or
`--mode database-changes`, or explicitly afterwards with `mode MODE`. An
unclassified experiment stays readable but cannot prepare, add, or run sessions,
or compute comparisons. Selecting a mode validates any existing accepted fixed
inputs against S1 without rewriting session evidence. An incompatible prototype
needs a separate experiment.

For an editable Q cell, **Copy to editable draft** accepts either a selected
library query or an earlier session's accepted query. It creates a new directory,
copies source/support files, records provenance, and opens the draft editor.
Earlier-session copies come from the frozen query pack, not its original mutable
source directory. Copying/saving a draft does not accept Q or start analysis;
choose the edited query from its table when ready.

```sh
cga bench mode query-changes
cga bench session refined          # inherits S1.D only
cga bench clone --session 2 --stage D --from-session 1 --no-advance
cga bench copy-query --session 2 --from-session 1 --directory queries/refined
# Or use --generation HASH --row N to copy a selected library query.
```

## Start an experiment

[`illustration/six-session-shell-equivalent.sh`](illustration/six-session-shell-equivalent.sh)
reconstructs the live `my-bench` six-session query study as a shell sequence.
It uses lower-level `cga` commands without Bench to show accepted query variants,
observed finding counts, selection/packing, and the job protocol Bench manages.
The sequence deliberately repeats every session's setup and execution inline,
without helper functions or loops, exposing the bookkeeping hidden by the grid.
Its manual count comparison does not reproduce Bench's finding-level diffs or
accepted-input/result snapshot safeguards.
It is an illustration for a **new** workflow, not a script to run against the
existing viewer; read its infrastructure warning before executing it.

The companion
[`six-session-storage-equivalent.md`](illustration/six-session-storage-equivalent.md)
is a linked, hand-kept view of the same study's accepted inputs, downloaded
artifacts, findings stores, submissions, and comparison evidence. It distinguishes
retained SQL findings databases from the JSON-based comparison and records the
connections a user would otherwise have to maintain.

To turn both complete sources into large, zoomable vector posters, run from
`cga/`:

```sh
python3 cgabench/illustration/render_illustrations.py
```

The generator needs Python 3 and Ghostscript (`gs`), not the live Bench or MRVA.
It writes SVG, PostScript, single-page PDF, PNG overviews, and JSON geometry/source
audits under `illustration/rendered/`. These generated files are tracked in Git
for direct viewing and reuse; regenerate and stage them with source changes. Use
`--output-dir PATH` to choose another destination.
The command poster puts every script line on one continuous winding path; the
storage poster places the full Markdown sections in six session folders and
connects specific input/result fields. Solid, dashed, and dash-dot wires distinguish
inputs, derivations, and JSON comparison inputs; dotted wires retain section
references. Source text, including repeated paths and hashes, is never abbreviated.
The SVGs include the original source and its SHA-256 in metadata, plus source-line
coordinates for auditing; internal wiring ports link to their document sections.
The PDFs use custom poster-sized pages, not text squeezed onto office paper.

```sh
mkdir my-bench
cd my-bench
cga init .
cga chain start
cga bench init query-study --mode query-changes
cga bench session baseline --user alice
cga bench advance
cga bench show 'E.S[1].D'
cga bench serve                    # http://127.0.0.1:8610
```

`session` appends S1 or a variant inheriting S1's fixed input and makes it active.
Accept S1's fixed input before creating variants; incomplete jobs/results do not
prevent preparing variants. Calling `cga bench session` without
arguments generates an internal label from the next row number and reuses the
first session's MRVA identity. For an experiment without sessions, it uses the
logged-in OS username (`getpass.getuser()`). Explicit names and `--user` remain
available to CLI/LLM clients; existing sessions are not renamed or reassigned.
`--session N` addresses a specific row; otherwise commands use the active row.
`show` accepts `E`, `E.C`, `E.S[N]`, `E.S[N].D/Q/J/R`, and column aliases
`E.D/Q/J/R[N]`. It prints the projection on stderr and preserves CGAST stdout.

`serve` prepares the bench's own analysis infrastructure automatically: check
PostgreSQL/tools and reclaim spurious service ports, reset a new runtime, build,
then start MRVA and the database archive server (plus MinIO when selected).
Runtime/scratch files default below the workflow's `.cga/`; environment
overrides are preserved. Existing bench runtimes restart without resetting MRVA
state. The bench and `mrva-flow` are independent and must not run MRVA
simultaneously.

`--no-services` disables automatic infrastructure setup; it does not disable
the warm Copilot assistant. `--no-assistant` skips automatic Copilot startup
(the panel can still start it explicitly). Setup errors
leave the viewer available with an explicit infrastructure warning and detailed
assistant diagnostics. **Prepare services**, **Check services**, **Stop
services**, and confirmed maintenance actions are also available in the UI.
Infrastructure groups these under **setup** and **Maintenance** labels, with
maintenance actions visible without a separate toggle. Both groups use light
cards with stacked action rows; action buttons throughout the detail views share
the same light, left-accented style. Stage colors still indicate their status,
and expand/collapse arrows and VID anchors remain borderless.
Running an action titles the detail pane with that action; **View infrastructure**
returns to **Detail: Infrastructure** while preserving the last action's result
and any error.
**Stop services** stops MRVA/archive/MinIO, not the shared host PostgreSQL.

### Stop or restart the viewer

Restart the viewer after Python backend changes; browser reloads pick up static
assets but cannot reload the running backend. If the backend lacks the session
evidence fields required by the page, Bench reports an explicit restart error.

Run from the same bench workflow directory (or one of its subdirectories):

```sh
cga bench stop && cga bench serve --no-services --editor-port 8611
```

`stop` sends SIGTERM only to that workflow's recorded viewer and waits for its
HTTP listener, warm Copilot assistant, owned VS Code editors and legacy terminals to finish shutting
down. It does not stop MRVA/archive/MinIO, alter experiment state, or record a
workflow step. It succeeds when the viewer is already stopped, so the command
above works on first startup too. `serve` remains a foreground command; its
original Ctrl+C/SIGTERM shutdown behavior is unchanged.

Ownership is tracked under `.cga/runtime/cgabench/` using a lifetime lock and
PID/boot/start-time identity, so stale records cannot stop a reused PID.
Only one viewer may serve a workflow at a time. Stop waits up to 30 seconds;
if cleanup has not finished, it reports an error rather than force-killing
processes or starting another viewer over them.

For raw CGAST files, use the same explicit file for both commands:

```sh
cga bench stop --session-file /path/to/session.json &&
  cga bench serve --session-file /path/to/session.json --no-services --editor-port 8611
```

Their ownership files live beside the CGAST in
`.cgabench-runtime/session.json/`. Viewers launched before this ownership
tracking was added must be stopped once with Ctrl+C or `kill -TERM <their-PID>`;
`stop` never searches for processes by name or kills an unrecorded port owner.

## Human workflow

**Apple outline** is the default presentation. **View > Appearance** switches
between **Apple outline** and the original **Classic** layout. The choice is
saved only in this browser (`cga.bench.presentation`), not in the experiment,
workflow, or API model. Switching presentation preserves current inputs,
selected detail, and Classic disclosure state.

The Apple layout has a header (**P_head**), a left navigation outline (**P_1**),
upper-right content (**P_2**), and lower-right detail (**P_3**). Both dividers
support dragging, arrow keys, and double-click/Home to reset. Narrow screens
stack the panes vertically.

- P_head uses a split toolbar: its left background continues P_1's gray surface,
  and its white right portion holds the experiment title and right-aligned
  controls. The boundary tracks the resizable divider. Reload is an accessible
  circular-arrow icon; View and Mode are borderless text menus with chevrons.
  These controls use subtle gray hover/open backgrounds and keyboard focus rings.
- The sidebar button at the far left hides/restores P_1, preserving its width,
  selection, and P_2/P_3 content. It stays visible when navigation is hidden.
  Classic retains its original header controls and workflow pane.
- P_1 contains MRVA system summary and Workflow commands, with Infrastructure
  (Setup, Maintenance, and System view), Sessions, and Comparison beneath it. Disclosure
  arrows expand/collapse independently of row selection. Up/Down and Home/End
  navigate visible rows; Left/Right collapse/expand branches.
  A muted Contents heading, rounded gray row selection, and single-line labels
  with ellipsis/full-label tooltips follow the sidebar presentation.
- Selecting a row displays its existing content in P_2. Sessions is selected
  initially. Selecting an infrastructure command exposes its action button
  there; selection alone never executes it.
- Apple Sessions uses one row per session, with Compare, Session, D, Q, J, R,
  and Action columns. Compact status buttons show Unicode symbols:
  **○** empty/blocked, **◐** running, **✓** complete, and **×** failed. The legend,
  full-status tooltips, and accessible labels explain them; VID anchors remain
  beside each status. Completed sessions omit the disabled Continue button.
  Classic retains its original sessions-as-columns table.
- Clicking a session's D/Q/J/R status or Edit/Clone control opens the unchanged
  detail (`:e7n`) in P_3. Infrastructure actions/status and explicit comparison
  views/reports use P_3 too. Selecting Comparison does not compute a comparison;
  **Compare** is still an explicit action.
- Infrastructure > **System view** (`:m3d`) opens the existing read-only MRVA
  dashboard directly in P_3 without changing P_2. The embedded dashboard retains
  its original colors, even in the Apple presentation.
  Offline errors appear in P_3, and leaving the view stops its background polling.
  **View > live system** remains the separate-window option. Infrastructure
  command diagnostics still appear in P_3; Classic retains **View infrastructure**.

Embedding permits only the configured `CGA_MRVA_SERVER` HTTP(S) origin in Bench's
`frame-src` policy, alongside its existing same-origin permission. The iframe
allows scripts and its own origin, but not forms, popups, or top-level navigation.
Activating this policy requires a viewer restart (`cga bench stop`, then
`cga bench serve --no-services` with the original port/editor options); this ends
the viewer-owned assistant, but does not change the experiment or restart MRVA.

Apple uses system fonts, grayscale selection/focus, and gray/black surfaces,
except for the embedded MRVA dashboard. Grid status symbols do not rely on color; full status names remain
in tooltips and accessible labels. Rounded controls, VID references, and shadowless
boxes remain available in both presentations.

In Classic, the top of the page has a collapsible MRVA system summary, including server
identities, job/worker state counts, and pending spawns. Runtime details appear
directly below the summary cards without a separate toggle.
It refreshes independently of the experiment and reports offline errors.
Expand/collapse controls use borderless arrows, retaining keyboard focus indicators.

Beside **Reload**, the **View** menu offers **live system** (or **offline system**)
and **Copilot assistant**, with matching item styles. **live system** opens the existing MRVA system view;
**Copilot assistant** opens the
shared Copilot xterm.js terminal in a separate popup. Repeated clicks focus the
same open window. Bench starts one interactive Copilot process at
viewer startup, before optional infrastructure setup, so opening the popup
attaches to that already-starting session rather than paying startup cost then.
Normal Copilot trust, authentication, and permission prompts
remain in effect; an unattended first run can wait for your response there.
The initial prompt supplies the live workflow/Bench API context and asks Copilot
to wait for a request without running tools or changing state. It is not pinned
to a session or fact frontier.

In Classic, the View and Mode controls align with Reload. Their dropdowns use a compact
macOS-style panel in the summary cards' light blue, with rounded corners, borderless rows, and blue
hover/keyboard-focus highlighting. All page buttons share that borderless,
rounded styling and system font; stage status colors remain distinct.
**Add session**, **Reload**, **View**, and **Mode** retain thin blue-gray outlines
to make them recognizable as buttons.
Infrastructure's Setup and Maintenance groups and the expanded Comparison
controls use the same light blue panel and rounded corners. All boxes, including
dropdowns, are shadowless.

Closing the popup, navigation, and browser reload do not stop this assistant;
reopening or reconnecting replays its bounded in-memory terminal output.
All windows share the same PTY and input. **Reconnect**, **Start assistant**,
and **Stop assistant** live in the popup, not the main Bench page.
**Reconnect** attaches without starting another process. **Stop assistant**
stops the shared process; **Start assistant** explicitly starts a fresh session
after exit/stop or retries a startup failure. Startup/connection errors appear
in the popup; blocked-popup errors appear below the main page header.
Viewer shutdown stops this process; a viewer restart starts a new
conversation. VID popup terminals remain independent, paste-only shells.
The assistant runs as the viewer's OS account, with its authentication and normal
Copilot permissions, not a session's MRVA identity.

Below it, the collapsible **Workflow commands** pane on the left contains
infrastructure actions, **Add session**, the transposed D/Q/J/R grid, and
comparison actions. Sessions are columns; database, query, job, and result
stages are rows. **Infrastructure**, **Sessions**, and **Comparison** are
independently collapsible subtopics; Sessions contains both Add session and the grid.
Collapsing them leaves the current detail and experiment state unchanged.
The shared **Detail** pane on the right displays infrastructure
action status/errors, the selected cell, or comparison results. **View infrastructure**
and **View comparison** revisit those details without running an action.
Drag the divider or use its arrow keys to resize the panes; double-click or
press Home to reset it. Narrow screens stack the panes.

Input preparation belongs to the editable cell's **Detail: session N, stage
D/Q** panel. D shows only database preparation; Q shows only query preparation.
Selecting a later session's fixed cell shows its clone provenance and a prior-session
source dropdown instead of editing controls.
The model's one-based session addresses (`E.S[N].D/Q/J/R`) are unchanged.

### Shared element references

Small anchor symbols (Unicode U+2693) identify meaningful panels and controls, session headings,
D/Q/J/R cells, their accepted inputs/repository jobs/results, and library rows.
For example, `:f3a,1,J` is S1's J cell and `:f3a,1,J,2` is its second
repository job in accepted database order. These are logical identities, not
render positions or revision numbers; existing `E.S[N]` addresses still work.
The global root registry uses permanent opaque three-character base-36 IDs.

Anchors follow text labels and compact buttons; hover or focus to discover the VID.
Single-click to copy the short VID only. Double-click to copy it and open an
independent inspector, not to run its adjacent action.
Clipboard failures are shown without blocking inspection.
The active origin anchor and popup share a highlight color. The popup
pins accumulated immutable facts at opening and owns a separate xterm.js shell.
**Paste Copilot command with context** inserts only; press Enter yourself to
start Copilot with normal permissions. Closing a popup stops its shell, with a
120-second inactivity expiry for lost tabs. These are distinct from the legacy
session D/R terminals, which retain their existing lifetime.

Use `cga show :f3a,1,J`, `cga related :f3a,1,J`, or
`cga open :f3a,1,J --url http://127.0.0.1:8610` from the shell.
Copy a popup's full pinned reference when sharing context across chains.
`/api/vid/registry` and `/api/llm` describe discovery; the full
[VID contract](../README.md#visual-element-identifiers-vids) documents
qualification, facts, raw-file observations, and terminal ownership.

**Add session** requires no name or identity input. Session column headings
show the one-based number and status, with **Reference** on S1,
for example **1 Reference (incomplete)**. Internal names and MRVA identities remain in the
detailed assistant model.

Detail displays the cell's requirement and accepted-input summary in a labelled
**Status** box, separate from the optional **Development note** form and **Stage
history**.

In D, **Read existing database catalogue** is the only preparation path, shown
as text rather than a dropdown; use **Load database catalogue** to import it.
In Q, choose **Read existing query library** and **Index query
library**. Input paths initially suggest the same catalogue and sample query
directory used by `mrva-flow`. Loading/indexing in Detail updates only the
selected session's library, not other sessions or `mrva-flow` state. Existing
shared libraries remain available as defaults until a session loads its own.

Database preparation includes a **Discovered catalogues** dropdown populated
from `metadata.sql` files under the bench workspace and CGA component directory.
Hidden directories, `node_modules`, and `__pycache__` are skipped; directory
symlinks are not traversed. The suggested
`cgadl/db-collection.global/metadata.sql` is also checked explicitly so a linked
collection remains available. **Rescan catalogues** discovers newly added files.
Choosing an option fills the path; **Load database catalogue** performs the
import. Manual path/URL entry remains available for files elsewhere or named
differently. Discovery details use an outline: the number found, **Searched**
with one nested entry per root, and the scan exclusions/instructions.

Catalogues are SQLite files, not SQL scripts or CodeQL database archives. They
contain metadata and download locations for prebuilt databases. Obtain a
catalogue from a collection provider or generate one using database preparation
tools (see [CGA preparation](../README-prep.md)); the bench consumes, rather than
constructs, these catalogues.

The loaded library appears as a filterable, paginated table. **Find substring in
library metadata** searches all metadata columns, including the CodeQL version;
`%` and `_` are literal characters, not SQL wildcards. Matching is
case-insensitive for ASCII letters. Select database rows and **Use selected
databases** to download and accept them. Select one query and **Use query and
continue** to build its pack and accept it. Acceptance advances the session;
once both inputs are ready, analysis starts automatically. Tables carry a
library-generation token so a stale selection cannot silently target newly
indexed rows. Downloads go into the bench-owned archive server directory.

Choose **Write query and index** in a Q cell to create a persistent query
directory with an editable dummy `.ql` query, `qlpack.yml`, and a README.
Manifest generation reuses `cgaql`'s exact installed-bundle dependency logic.
Existing directories are never overwritten. Edit/save the query in the fixed
detail panel, then choose it from the workspace table to accept it. The starter
deliberately finds nothing; developing and validating a detector remains an
explicit user/assistant task. Saving a draft does not silently replace an
accepted query or the library previously loaded using **Read existing query
library**.

Database acquisition, building, validation, and catalogue generation happen
outside the browser using the existing preparation components. Legacy database
preparation CLI/API operations remain supported, but D detail does not offer a
build terminal or build-output import path. Existing terminal sessions are not
stopped by this UI change.

The browser's **Open VS Code** button starts a native, password-authenticated
[Coder code-server](../cgacc/README.md) pop-up for the completed R cell.
Install it once with `cga cc install`, or set `CGACC_CODE_SERVER` to an existing
installation. No session editor is started until the button is clicked;
the shared assistant starts separately with Bench.
For remote use, [CGA gateway](../cgagateway/README.md) exposes Bench at
`http://127.0.0.1:8599/bench/` and discovers live session editors through the same
SSH-forwarded port; the default automatic editor ports work without extra forwards.
For direct-port SSH forwarding, start with `cga bench serve --editor-port 8611`: S1 uses
8611, S2 uses 8612, and so on, independent of opening order. The default `0`
retains automatic ports. Occupied/out-of-range ports report errors rather than
silently changing ports. See [the forwarding example](../cgacc/doc/usage.md#ssh-forwarding).
Editors survive navigation/reload and pop-up closure; reopening reuses the same
session process. SIGINT/SIGTERM stops owned editors and legacy PTYs without
stopping MRVA services. Legacy terminal history is buffered in memory
(one MiB per PTY, with an explicit truncation notice), not registered as CGAST
evidence; normal shell history rules still apply. Deliberately detached
processes are not managed. Shells run as the bench's OS account, not the row's
MRVA identity. This full-shell capability is intended for a trusted single-user
loopback host: do not publish or proxy the bench port to untrusted clients.

The assistant popup uses locally vendored xterm.js; the main Bench page and
D/R detail cells contain no terminal. The historical cell terminal API remains available for
compatibility; no CDN or Node runtime is needed to serve the Bench page.

## Browse completed results

Every session detail (D, Q, J, or R) includes **Databases**, **Queries**,
**Result summary**, and **Findings** tabs in the same light card style as the
other controls.
Each shows a count, at most one preview row, and a **Browse all / SQL** popup link.
The previews use the session's accepted database archives, accepted query snapshot,
and total/per-repository findings, with VID anchors to their source evidence.
Unaccepted inputs and unavailable results are labeled explicitly. The selected
stage opens its matching tab (J opens the result summary); switching tabs is
read-only. Arrow keys and Home/End navigate the tabs.

For completed sessions, the **Findings** tab shows the total count, one finding,
and a **Browse all findings / SQL** link. Full filtering, pagination, SQL, and
editor controls live in that popup, not the main detail pane.

The evidence popup uses the same restricted DuckDB SELECT/WITH interface as
Findings, including SQL aggregates, empty-result columns, explicit errors, and
**Previous/Next** pagination (30 rows per page). Its tables are **databases**,
**queries**, **result_summaries**, or **sarif_results** (Findings), selected by
the popup's session and tab;
the available columns are listed above the SQL editor. `ordinal` retains the
one-based accepted evidence order. **Show all rows** restores the default SQL;
rows remain paginated. Database/query/result summaries load only the selected
session's retained evidence into a temporary database; Findings uses its existing
session-local DuckDB. Browsing never accepts inputs, runs analysis, or
changes evidence. Repeated popup-link clicks focus the same window.

Open a completed session's Findings popup to see a paginated table with repository,
rule ID/name, kind, file URI, line/column, and SARIF message. Existing completed
sessions work without resubmission or reingestion: R processing already invokes
`cgasi ingest`, which creates per-job SQLite databases and a combined
session-local DuckDB.

**Apply exact-match filters** uses the same query builder as
`cga sarif-ingest search`. Repository choices map to the job's SARIF filename;
rule ID, kind, file URI, and start line are also available. Nonempty filters are
combined with AND; text matches are exact and case-sensitive. **Clear filters**
returns to all findings. **Previous/Next** show 30 rows at a time.

**Run read-only SQL** runs one SELECT or WITH query over
`sarif_results` using cgasi's structured DuckDB query helpers. For example:

```sql
SELECT rule_id, count(*) AS findings
FROM sarif_results
GROUP BY rule_id
ORDER BY findings DESC, rule_id
```

Columns are `user`, `file_name`, `kind`, `rule_id`, `rule_name`, `uri`,
`start_line`, `start_column`, and `result_json` (the original SARIF finding).
SQL replaces the exact-match view rather than silently combining filters.
Returned columns and pagination adapt to the query, including aggregates and
empty results. Errors are shown beside the table, never as a successful empty
result. DuckDB parses/normalizes one SELECT before execution; the database is
opened read-only in CLI safe mode, initialization files and external
filesystem/network access are disabled, and each query operation times out after
15 seconds. No view operation changes the session, checkpoint, frozen snapshot,
or completed stage history.

The findings **Open VS Code** button opens a project in the existing, separate
`.cga/tmp/cgabench-query/session-N` directory (or `.cgabench-query/session-N`
beside a raw session file). It is independent of the D build shell. The generated
`query.code-workspace` sets that folder as the integrated terminal working
directory. `AGENTS.md` and `.github/copilot-instructions.md` point assistants to
`bench-context.json`, refreshed with the session identity, accepted inputs,
DuckDB/per-job SQLite paths, frozen snapshot, static documentation and API
URLs/headers/examples. They direct assistants to use read-only result queries,
without reingestion or execution workflow mutations. Existing instruction/project
files are not overwritten. Agent extensions/authentication remain user-managed;
opening VS Code does not start Copilot or override permission/trust controls.
The editor has your OS account's full permissions; instructions are not a shell
sandbox. See [cgacc's runtime contract](../cgacc/doc/usage.md).

## Choose existing inputs or prepare your own

Database/query refinement happens inside the respective workspace. Seed a
session from top-level `cgadl-metadata`, `cgaql-index`, and `cgaql-querydir`, or
import them directly. Low-level tool output is reserved for terminal/LLM use.
The examples below establish S1. For variants, prepare only the changing stage;
the fixed stage must use Clone instead of library/tool/work/accept operations.

```sh
cga bench tool --stage D -- dl getmeta /path/to/metadata.sql
cga bench tool --stage D -- dl list 20
cga bench tool --stage D -- dl select primary_language cpp git_owner acme
cga bench tool --stage D -- dl download
cga bench database

cga bench tool --stage Q -- ql index /path/to/queries
cga bench tool --stage Q -- ql list 20
cga bench tool --stage Q -- ql select id cpp/my-query
cga bench tool --stage Q -- ql pack
cga bench query
```

The tool commands use **session-local workspace state**, not another row's
selection. Selecting again invalidates its previous download/pack association.
Acceptance freezes the selected metadata and copies the query pack; later
workspace operations cannot silently change accepted inputs. Database archive
digests are recorded at acceptance and rechecked before submission. A session
must have one language; its database and query languages must agree.

For user-created inputs, use existing `cga db`/`cga catalog` preparation
commands, or write/refine queries in your editor and index/pack them as above.
The bench supplies a starter/editor but does not replace database builders or
automate local query evaluation. `work` records required work and refinement
notes:

```sh
cga bench work --stage Q --note 'Write and smoke-test the refined detector'
cga bench tool --stage Q -- ql index /path/to/my-new-queries
cga bench tool --stage Q -- ql select id cpp/refined-detector
cga bench tool --stage Q -- ql pack
cga bench query --source user
```

Explicit prepared artifacts can also be accepted:

```sh
cga bench database --source user --selection databases.json --dbdir ./downloaded
cga bench query --source user --selection queries.json --pack ./query.tgz
```

Database selections use the existing `{"databases": [...]}` envelope and
download layout `OWNER/REPO/OWNER_REPO_db.zip`. Query selections use
`{"queries": [...]}`. Database rows require `git_owner`, `git_repo`,
`primary_language`; query rows require `language`. For current CGA selections,
`database`/`query` can omit paths. With multiple `cgaql` bundles,
`--pack-index N` (zero-based) freezes exactly the corresponding query row. An
explicit `--pack` must already represent the supplied selection.

## Advance, pause, and preserve evidence

Accepting an input advances automatically; `--no-advance` defers execution.
`advance` stops at the first missing accepted input. With D and Q accepted, it
uses the real `cgamr submit`/`status`/`download`/`verify` and `cgasi ingest`
components. Each invocation checks status once, returning **running** if work is
pending. There is no automatic polling loop. Invoke `advance` again to resume;
the browser has the same action.

Infrastructure actions reuse the existing CGA lifecycle components. The usual
`CGA_MRVA_*` environment settings apply; `session --server URL` pins a specific
endpoint. `--user` is the authenticated MRVA identity, while bench session names
are experiment labels. Ingestion needs the existing SARIF tooling, SQLite, and
DuckDB.

Every external operation has an atomic session checkpoint. Successful submission
is retained even if status/download/ingestion subsequently fails, so retrying
`advance` does not submit again. Errors are nonzero with explicit stderr
diagnostics, and raw filters also emit the partial CGAST for recovery. Workflow
failures remain in the workflow attempt journal without committing a new node;
the session's already-recorded checkpoint lets the UI display the failure and
the next `advance` recover completed operations.

If submission itself fails or is interrupted after starting, its outcome is
**uncertain**: automatic resubmission is refused. Inspect the MRVA server before
creating a replacement session. This deliberately avoids duplicating a job when
the server received a request but its response was lost.

Partial/missing downloads are retried on the next advance. Result archives are
ordered by the submitted repositories before ingestion, regardless of server
status ordering. Selections whose repository names would collide under MRVA's
`OWNER-REPO.zip` result naming are rejected explicitly.

Once submission starts, D and Q are locked. Completed sessions are immutable
evidence; new database/query revisions belong to a new session. Results include
per-job ingestion records, zero-finding jobs, exact SARIF findings,
query/database digests, MRVA identity, and source/result provenance. Workflow
artifact discovery registers these files in the normal configured object store.

Checkpoints and raw component files are operational paths under `CGAST_TMPDIR`
(or the existing CGA scratch default). Retain them for resuming a live bench;
CAS workflow evidence alone does not recreate a running MRVA session. Concurrent
browser mutations are serialized by the workflow lock (or a session-file lock);
raw filter callers must serialize their own state-file updates.

## Compare and use the browser

```sh
cga bench session refined --user alice
# Choose/refine/accept its inputs, then advance until complete.
cga bench compare 1 2
cga bench show E.C
```

With no indices, `compare` uses all complete rows in insertion order. At least
two distinct complete results are required. S1 is always included and moved to
the first position, even if omitted or listed later; incomplete S1 blocks comparison.
For example, `compare 2` compares S2 to S1. Each
input reports **added** and **removed** findings relative to it, and **common**
means present in every input. Duplicates are compared as multisets, not
discarded. All selected result references and their D/Q/J provenance are
retained; prior comparison artifacts remain in comparison history.

Matching is deliberately conservative: exact repository, rule ID, primary
physical/logical locations (including regions), and SARIF message. Artifact and
rule indices are resolved. Renamed repositories, changed source-root URIs,
shifted line numbers, or changed messages are **not** treated as equivalent.
This is finding comparison, not automatic CVE correctness evaluation. Completed
finding snapshots are digest-checked before comparison.

`serve --port N` exposes the standalone grid, fixed details, and comparison
panels. The browser can append sessions, load libraries, choose prepared inputs,
create/edit queries, record work, advance, and compare selected rows. Mutations
use the same CLI commands through `cga`, including workflow history and
artifacts. The grid is refreshed on explicit reload/action, not periodically, so
unfinished form input is preserved. It binds loopback only; same-origin mutation
requests are required. Use an SSH local forward for remote access.

Outside a workflow, supply a persisted CGAST explicitly:

```sh
cga bench serve --session-file /path/to/session.json
```

That file must already contain an initialized bench. Browser changes are atomic
file updates; CLI filters still require the caller to persist their output.
Session-file mode does not start infrastructure automatically.

## Assistant endpoints

The discoverable CLI entry point is `cga llm context bench` (alias
`cga llm cb`). It reads local experiment/session context without requiring
this server. Add `--show-html-endpoint`, `--show-json-endpoint`, or
`--show-docs` to print the viewer URL, model URL, or local documentation paths;
use `--port PORT` for a non-default viewer port.

`GET /api/llm` describes the detailed interface. All are on the bench's own
origin:

| Endpoint                      | Purpose                                                                  |
| ----------------------------- | ------------------------------------------------------------------------ |
| `/api/view`                   | Command-free human projection and MRVA summary                           |
| `/api/model`                  | Full addressable experiment, state, histories, and comparison provenance |
| `/api/catalogues`             | Discovered catalogue paths and scan roots; GET rescans                   |
| `/api/collections/databases`  | Loaded catalogue rows, search/pagination, generation token               |
| `/api/collections/queries`    | Session library (shared fallback), or `source=user&session=N` workspace  |
| `/api/query-source?session=N` | Editable query source and pinned pack manifest                           |
| `/api/sysview`                | Detailed MRVA system proxy                                               |
| `POST /api/action`            | Named human actions with structured fields                               |
| `POST /api/command`           | Detailed allowlisted bench argv, including session-local tool operations |
| `POST /api/results`           | Session-scoped exact-match search or read-only SQL with pagination       |
| `POST /api/evidence`          | Session/stage-scoped retained database/query/result summary SQL pages    |
| `POST /api/editor`            | Open/reuse password-authenticated VS Code for a completed session        |
| `POST /api/terminal`          | Persistent separate D/R shells: open/read/write/resize/insert/stop       |

Mutations require `Content-Type: application/json` and `X-CGA-Bench: 1`, with
same-origin browser requests. Human errors are summarized; full diagnostics
remain on stderr/in workflow attempts and `startup_error` in `/api/llm`.
Libraries support `search`, `offset`, `limit` (maximum 100), `session`, and
`source=list|user`. Selection commands require the returned `generation` and row
IDs, for example `choose-databases --generation HASH --rows 1 2`. Named
preparation commands are `mode MODE`, `clone --stage D|Q --from-session N`,
`copy-query`, `catalogue PATH [--session N]`,
`library DIRECTORY [--session N]`, `create-query`, `edit-query`, and
`infrastructure setup|...`. Omitting `--session` on catalogue/library commands
retains the shared-library behavior. `catalogue --session N --source user PATH`
marks the built-catalogue handoff, independently of existing-catalogue defaults.
Human catalogue/library actions carry the selected session; canonical LLM
addresses such as `E.S[1].D` remain unchanged.

Result requests require the same JSON/same-origin headers, an explicit one-based
`session`, `offset` (default 0), and `limit` (default 30, maximum 100). Supply
either `filters` (string values for `file_name`, `rule_id`, `kind`, `uri`,
`start_line`) or `sql`. Responses include `rows`, `columns`, `total`,
`has_more`, and repository/SQLite provenance. `/api/llm` documents this format.

Editor requests use the same JSON/same-origin guards and take `{"session": N}`.
The non-cacheable response contains the local login URL, generated password,
workspace/project paths and PID. The UI submits the password in a pop-up form,
never in a URL. Missing code-server, blocked pop-ups and startup failures are
shown explicitly.

Legacy terminal requests use the same JSON/same-origin guards. `open` takes `session`,
`columns`, `rows`, optional `stage` (`D` by default, or completed `R`), and
optional `restart`; subsequent operations take the opaque returned `id`. `read`
additionally takes a byte `cursor`, returning base64 output, the next cursor,
truncation/running status, and explicit errors. `write` takes UTF-8 `data`;
`insert` pastes the prepared Copilot command with no Enter. Terminal input is
not an allowlisted bench command: it is intentionally a full interactive shell.
Scripts remain restricted to this origin; forms may additionally target IPv4
loopback ports for code-server login.

## Validation

```sh
cd cga/cgabench
python3 -m unittest discover -s tests
```

Focused tests cover state/address invariants, input freezing, blocked/failed
resume behavior, duplicate-sensitive comparison, and browser persistence. The
integration test uses the **real component binaries and SARIF ingestion**
against a localhost MRVA-protocol fixture, including a failed-status workflow
recovery, two completed sessions, comparison, and browser-to-dispatcher
recording.

When Chromium and a Node version with built-in WebSocket support are available,
the suite also exercises library loading, table-based selection, query
creation/copying/editing, mode selection, Clone/Edit controls, status/notes,
and the editor launch/error paths in a real headless browser. When code-server is
installed, it also checks authenticated pop-up workbench loading and process
reuse across reloads. `cd cga/cgacc && python3 -m unittest discover -s tests`
checks native authentication, session isolation, restart and shutdown.
Legacy PTY tests cover resizing, bounded output, persistence,
foreground-job shutdown, and insertion without execution. A fake Copilot
executable checks command arguments without starting an actual paid LLM session.

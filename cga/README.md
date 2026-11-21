# CGA: select and run CodeQL analysis

Start with the [CGA overview](../docs/cga-overview.html) for the big picture,
fixed Sample 05 example, and installation. Use [CGA help](../docs/cga-help.html)
for tasks and commands, and the [reference manual](../docs/book/index.html) for
detailed workflows, components, and operations.

This page is the CGA command and state reference. This is an experimental
prototype: usage examples and supporting code evolve together.

CGA selects prepared CodeQL databases and queries, runs them through MRVA,
ingests SARIF, and exports the results. The preparation utilities that generate
databases and queries now live in the same `cga/` collection (see
[`README-prep.md`](README-prep.md)) and hand their artifacts to the selection
side explicitly.

```text
DB catalogue -> cgadl --+
                       +-> cgamr -> cgamu -> cgasi -> cgaex
query tree  -> cgaql --+
```

## Unified `cga` command

`cga/cga` is a single dispatcher for every tool in this collection. Each tool
has a short acronym and an explicit long name; either works:

```sh
cga db-lib list          # or: cga dl list
cga query-lib pack       # or: cga ql pack
cga assist database-build -h # or: cga a d -h; guided preparation
cga assist query-writing -h # or: cga a q -h; Bash-first authoring
cga bench serve         # experiment grid, refinement, and result comparison
cga mrva-request submit  # or: cga mr submit
cga chain list           # or: cga cn ls
cga tree show
cga data-flow-graph show # or: cga dfg show
cga control-flow-graph show # or: cga cfg show
cga run start              # analysis dashboard only
cga view --capture ...     # capture/export analysis dashboard
cga uv start               # read-only CGA Unified View
cga uv outline             # searchable text projection
cga uv search Fprintf      # bounded workflow/resource search
cga llm context bench     # assistant context for an experiment (alias: llm cb)
cga llm context unified   # assistant context for a workflow (alias: llm cu)
cga serve start            # analysis + preparation dashboards
cga public-html setup      # static documentation clone + printed setup script
cga github.io setup        # GitHub Pages workflow + printed repository settings
```

Install the dispatcher on your user `PATH` from anywhere inside the checkout:

```sh
repo_root=$(git rev-parse --show-toplevel)
install -d "$HOME/.local/bin"
ln -sfn "$repo_root/cga/cga" "$HOME/.local/bin/cga"
install -d "$HOME/.local/share/bash-completion/completions"
ln -sfn "$repo_root/cga/completions/cga.bash" \
  "$HOME/.local/share/bash-completion/completions/cga"
cga --help
```

If `$HOME/.local/bin` is not already on `PATH`, add
`export PATH="$HOME/.local/bin:$PATH"` to your shell profile. On a dedicated
development machine, install the same repository-linked command system-wide
instead:

```sh
sudo ln -sfn "$(git rev-parse --show-toplevel)/cga/cga" /usr/local/bin/cga
```

Both symlinks intentionally point into the checkout, so dispatcher and
completion updates take effect immediately. Moving or deleting the checkout
requires recreating them.

`bash-completion` discovers the completion automatically in new Bash shells.
Enable it immediately in the current shell with:

```sh
source "$(git rev-parse --show-toplevel)/cga/completions/cga.bash"
```

`cga <TAB>` lists every command, a short acronym completes to its long form, and
`cga <command> <TAB>` lists that command's subcommands. Run `cga` with no
arguments for the full command list.

### Command help

Use `-h` or `--help` on any command, including nested subcommands:

```sh
cga -h
cga init -h
cga mr submit -h
cga db build -h
```

Help uses **Name**, **Synopsis**, argument/option lists, **Description**,
**Environment Variables** when applicable, and a contextual **Example**.
Headings use the terminal's native argparse emphasis; redirected output remains
plain by default. Help explains prerequisites, effects, and configuration without
starting services, reading CGAST input, or recording a workflow step. Short and
long command aliases share the same help.

For CGA's purpose, scale, provenance model, and Linux VM/LLM guidance:

```sh
cga help overview
```

Open the checked-in [offline help browser](../docs/cga-help.html) without
regenerating it; it opens the overview before the getting-started walkthrough.
Or export a fresh snapshot:

```sh
cga help --export cga-help.html
```

For a small first analysis, display or execute one fixed sample step at a time:

```sh
cga help sample 05
cga h s 05 00       # display workspace setup
cga h s 05 00 r     # execute that step
cga h s 05 01       # display the next step
```

Step numbers and exact step names are interchangeable. `h`, `s`, and `r` alias
`help`, `sample`, and `run`; `cga help sample-05` also opens the overview. Only
a trailing `run`/`r` executes commands. Step 00 explicitly creates
`cga/cga-tmp/help-sample-05/` and saves runtime settings for later shells or
Jupyter cells. The [sample recipe](samples/05/README.md) lists the complete
single-user sequence: five fixed prepared databases, `Fprintf.ql`, and SQL
showing up to four findings per database.

The longer getting-started walkthrough remains available:

```sh
cga help getting-started
cga -h -s
cga -hs
```

These are equivalent, read-only help requests. The Commands section walks
through prepared databases and the supplied `Fprintf.ql`, selection, execution,
ingestion/export, and viewer start/reconnect/stop. It explains separate
preparation as a later step and identifies the worked examples. Displaying help
does not execute those commands or require an initialized workflow.

The other **Start here** guides provide the same read-only chapter interface:

```sh
cga help bash-tutorial-sql
cga help mrva-flow
cga help bench-intro
cga help shell-workflow
cga help two-user-standalone
cga help two-user-workflow
cga help zlib-study
```

Each overview lists chapter names; append one, for example
`cga help mrva-flow inspect`. The canonical Markdown supplies the displayed
instructions. Original HTML remains separately accessible and unchanged.

Open the generated file directly in your desktop browser. If CGA runs on a
remote VM, copy this one file to the desktop; no viewer server or X11 is needed.
The HTML embeds the current `-h` output, styles, and navigation, with no
external assets or Bench dependency.

The sidebar follows the reading order **Start here**, **LLM start here**, **Task
groups**, **Reference**. Start here opens getting started by default, with
embedded chapters for every tutorial and individual sample 05 steps. **Original
write-ups** holds the preserved HTML guides under Reference, alongside the
collapsible **system tests** group below **cga index**. Their links open in a
separate tab without changing the panes. Both start groups, system tests, and
Original write-ups are independently collapsible. The four task groups are
Create databases, Write and
prepare queries, Apply queries, and Review results. Commands can appear in
several task groups; shared workflow utilities remain in the alphabetical
Reference. Outline items select help in the upper-right pane (**PR_t**). The
**cga index** row opens the top-level help and toggles the alphabetical list; it
also supports keyboard expansion and collapse. The **⊟** header button
(**Collapse all** on hover) closes the index and all task groups, including the
start outlines, without changing the displayed help. Click a subcommand link
there to open its help in the lower-right pane (**PR_b**). Selecting another
outline item clears PR_b. Both panes scroll independently; drag the divider, or
focus it and use Up/Down/Home/End, to resize them. Deeper commands appear as
copyable shell help invocations, not further browser navigation. Nothing in the
viewer executes commands or refreshes state. The header search covers all
embedded help pages, not just the visible panes. Enter text and press **Search**
(or Enter) to highlight matching **cga index** entries; typing or toggling
**Regex** alone does not run a search. Matching checks the entire help text,
including subcommand pages, and expands the index without filtering out
nonmatches. Select a highlighted entry to inspect its help; matching subcommand
links and text are highlighted too. Search is case-insensitive plain text by
default; enable **Regex** for JavaScript regular expressions (with multiline
anchors). Invalid patterns are reported above the index. Clear the input and
press **Search** to remove highlights. Regenerate the HTML after changing CLI
help. Existing output files are replaced. `cga help` without arguments still
prints the top-level terminal help.

The offline help browser also has Bench-style anchor symbols. Its fresh roots
identify help controls, groups, documents, command pages, and sections.
Single-click copies a reference; double-click opens an independent inspector
with pinned help text, UI properties, related help, and copyable context.
The adjacent control is never activated. **Copy context** supplies JSON for a
human/LLM conversation; **Copy link** supplies a content-pinned file link.
Help references use `cga://help`, not workflow `cga://vid`; they require no
server or terminal and are not resolved by `cga show`. See the
[documentation entry point](../docs/README.md#cga-and-mrva-entry-point).

## Assistant context

Use the [LLM exploration entry guide](../docs/cga-help-llm.org) to choose one
task route and read only the relevant help, contracts, and evidence. It is
independent of the all-in-one human help browser.

Start with `cga --help` and `cga llm context --help`. The CLI is the front door
to CGA state; text and web endpoints are projections of that state:

```sh
cga llm context bench       # experiment and session D/Q/J/R summary
cga llm cb                  # short alias
cga llm context unified     # workflow outline, steps, and selected resources
cga llm cu                  # short alias
```

Both commands read the current workflow without changing state, recording a
step, starting services, or requiring an HTTP server. Bench uses the addressable
experiment model, including recoverable session checkpoints; Unified uses the
existing outline projection and redacts secret-tagged entities by default. Use
`--json` (or global `cga --json`) for the structured projection. Normal workflow
discovery, `-C`, `--cga-dir`, and `--store` apply. Outside a workflow, Bench can
read an explicit `--session-file /path/to/session.json`.

Each source also supports these output-only projections:

```sh
cga llm context bench --show-html-endpoint  # http://127.0.0.1:8610/
cga llm context bench --show-json-endpoint  # http://127.0.0.1:8610/api/model
cga llm context unified --show-html-endpoint # http://127.0.0.1:8609/
cga llm context unified --show-json-endpoint # http://127.0.0.1:8609/api/outline
cga llm context bench --show-docs           # local documentation paths
cga llm context unified --show-docs
```

These flags are mutually exclusive and work without initialized state. They
print URLs or documentation paths, not fetched content, and do not verify that a
viewer is running. Start viewers separately with `cga bench serve` or
`cga uv start`. Unified URLs honor `CGA_CGAUV_PORT`; use `--port PORT` for a
custom viewer port (including a non-default `cga bench serve --port PORT`).
Bench's `/api/llm` remains available for detailed HTTP interface discovery.
Unified additionally accepts `--detail summary|steps` and the explicit local
`--include-sensitive` override; do not send sensitive output to external LLMs.

## Visual element identifiers (VIDs)

Bench, Unified View, CLI output, and assistant context share opaque element
identifiers. Permanent roots are registered in `cgalib/vid_registry.py`: exactly
three lowercase base-36 characters after `:`, with no semantic encoding. Never
reassign a registered root, even if its original element is retired.

| Reference    | Logical element                                      |
| ------------ | ---------------------------------------------------- |
| `:8x1`       | Experiment                                           |
| `:f3a`       | Sessions                                             |
| `:f3a,1`     | Session 1, not revision 1                            |
| `:f3a,1,J`   | Session 1's job stage                                |
| `:f3a,1,J,2` | Its second repository job in accepted database order |
| `:h7m,1`     | First successful command on the qualified chain      |
| `:r6t,1`     | First workflow-wide failed-attempt index             |
| `:91c,1`     | First workflow-wide retained-artifact index          |

```sh
cga show --registry                 # roots and labels; no workflow required
cga show :f3a,1,J                   # latest properties and accumulated facts
cga show '(:f3a 1 :J)' --json        # equivalent quoted Lisp spelling
cga related :f3a,1,J                # typed links with qualified targets
cga open :f3a,1,J                   # inspector in a running viewer
cga open :h7m,1 --url http://127.0.0.1:8729
cga open :f3a,1 --print-url          # print instead of launching a browser
```

Short references use the current workflow, experiment, and chain. Copy the
returned `qualified_ref` for that logical object independent of the active
chain, or `pinned_ref` to retain the exact opening fact frontier. Both use
`cga://vid?workflow=...&chain=...&experiment=...&ref=...`; a pinned URI adds
`at=...`. Quote URIs in the shell. `--chain` and `--at` also select context
explicitly. Frontiers include the immutable node and attempt/artifact counter
cutoffs, so failures and manual artifacts cannot appear retroactively in an
already-open inspector. `--at NODE` selects evidence available at that node;
copy the full returned frontier to include later metadata without advancing it.
Foreign-workflow, wrong-experiment, stale, and unretained references fail
explicitly rather than falling back to another object.

Facts are append-only observations projected from retained immutable CGAST
snapshots and CAS evidence, not a second authoritative database. Existing facts
retain their IDs when later observations arrive. CGAST dictionaries, session
checkpoints, and working files remain mutable derived projections; historical
VID inspection does not follow their current paths. Collection rows carry their
immutable `g<SHA256>` generation and original SQLite rowid or JSON position,
never a filtered/sorted display position. Metadata tags remain access-policy
metadata, not immutable artifact facts. VID inspection rejects secret-tagged
objects and conservatively rejects state-derived experiment/session histories
containing secret-tagged steps.

In either view, a small anchor symbol (Unicode U+2693) follows each referenced
text label or compact control. Its tooltip and accessible name contain the VID;
the full root/path no longer occupies screen space. A single click only copies
the short VID (for example, `:f3a,1,J`). A double-click copies it and opens a
separate, pinned inspector without applying the adjacent analysis action.
Clipboard errors are explicit and do not prevent the inspector from opening.
Presentation-only splitters have no share anchors; their previously assigned
roots remain reserved. The active origin anchor and popup color bar match. Each
popup displays its qualified reference, properties, accumulated facts, typed
relations, and its own xterm.js shell. Closing it stops that shell; a 120-second
server-side inactivity lease covers lost tabs. Viewer shutdown closes all owned
shells. Shells run as the normal local OS user; they are not a read-only
sandbox.

**Paste Copilot command with context** only inserts a command; it never sends
Enter or starts Copilot. The command points to a private `context.json` with the
pinned object and uses normal Copilot permissions. Each popup has a separate
workspace below `.cga/tmp/inspectors/`; those files remain available after the
shell stops.

`open` does not start a viewer. It defaults to Bench `:8610` for experiment,
session, and comparison objects, otherwise Unified View's `CGA_CGAUV_PORT` or
`:8609`; use `--url` for other deployments. Inside an inspector terminal, its
viewer origin is inherited. Both viewers serve `/api/vid/registry`,
`/api/vid?ref=REF`, `/api/vid/related?ref=REF`, and `/vid?ref=REF`. Terminal
operations use the guarded, same-origin JSON endpoint `/api/vid/terminal`.

For raw CGAST files, `cga show :f3a,1 --session-file /path/to/session.json` and
the Bench viewer retain observed states under the adjacent
`.cgabench-runtime/session.json/vid/`. This adds inspection history without
rewriting the source file. Unobserved earlier edits cannot be reconstructed.

## Workflows

[`cga a d`](cgaassist/README.md#build-a-database-collection) provides guided
database preparation: fetch named Git or archive versions, build one or both
extraction modes, index, and export a content-addressed collection. Fetch/build
can use `--use-llm` to supervise dependency discovery and repair. Detailed
recipes remain available through `src-prep`, `db`, and `catalog` plumbing;
archive serving with `cga ds` remains separate.

[`cga a q`](cgaassist/README.md) provides Bash-first C++ query authoring: start
a named workflow, choose and download databases, prepare a CodeQL working tree,
save drafts, and publish to a permanent query library after check-only
compilation. It neither creates a Bench experiment nor starts MRVA.

[`cga bench`](cgabench/README.md) adds an addressable experiment grid with
independent database/query/job/result sessions. It uses existing CGA selection,
MRVA, and ingestion components, pauses for missing inputs or pending jobs, and
compares immutable completed SARIF evidence. Its standalone browser supports the
same mutations as the CLI.

Initialize a workflow in the directory that will own it:

```sh
cd my-analysis
cga init .
cga mx preflight
cga chain start
cga mx reset
```

`cga init -h` explains initialization, store selection (including environment
variables), and the next commands in a minimal workflow. Initialization creates
`.cga/`, analogous to `.git/`; it does not start a recorded chain. Run
`cga chain start` before the commands
whose history you want to retain. When a supported component
command runs beneath that directory, the dispatcher reads the current CGAST,
passes it to the component on stdin, validates the resulting JSON object, stores
it as an immutable content-addressed object, and advances the current chain
atomically. Direct `cga*` component binaries retain their JSON-in/JSON-out
interface for low-level use outside a workflow.

Both analysis commands and CGAST-native preparation/lifecycle commands are
recorded. This includes `cga db plan|build|validate`, `cga codeql`,
`cga src-prep`, `cga catalog`, `cga postgres`, `cga db-serve`, and
`cga mrva-server`. `cga control measure --cgast-filter` is also recorded while
its nested component command runs inside the same atomic workflow step.

Common workflow commands:

```sh
cga status
cga chain list
cga chain show -v
cga chain start --from <node-or-chain>
cga state show
cga state diff <left> <right>
cga log
cga tree show
cga tree show --format html -o flow.html
cga tree show --format pdf -o flow.pdf
cga doctor
cga uv start
```

HTML tree output embeds Graphviz SVG and uses the same topology and left-aligned
multiline labels as PDF output.

The current object-store root is configured by `object_store.root` in
`.cga/config`. It can be a filesystem path, `file:` URL, or HTTP(S) URL:

```sh
cga store show
cga store check
cga store verify
cga store set ../../single-machine-mrva-artifacts
```

Every durable reference in `.cga/` is a normalized relative key such as
`objects/sha256/ab/abcdef...`; absolute filesystem paths and complete artifact
URLs are never stored as object references. Changing the root therefore does not
rewrite workflow history. `cga store set` rejects a root that lacks currently
referenced objects unless `--allow-missing` is explicit.

CGAST state objects are always stored by content. Durable files discovered in
component output—including query packs, downloaded result archives, SARIF,
SQLite/DuckDB stores, and exports—are registered in the artifact catalogue and
copied into the same content-addressed store. Inspect them with:

```sh
cga artifact list
cga artifact show <artifact>
cga artifact path <artifact>
cga artifact materialize <artifact> -o FILE
cga artifact verify
```

Global `-C DIR`, `--cga-dir DIR`, `--store ROOT`, and `CGA_OBJECT_STORE=ROOT`
overrides support scripts and deployment-specific store locations. The
command-line store override has precedence over the environment, which has
precedence over `.cga/config`.

Recorded component commands also accept common `--tag PROFILE-OR-KEY:VALUE`
options before or after the component action (but before `--`). The dispatcher
normalizes and records them without passing them to component parsers.

See [`cgawf/FLOW-SCRIPT-GUIDE.md`](cgawf/FLOW-SCRIPT-GUIDE.md) for concise
human/LLM-authored flow conventions and a review checklist.

When `CGA_DASHBOARD_DUMP` is set, every successful component command invokes
`cga view` to append a dashboard capture. Capture failure is reported as a
warning without disguising the component command's successful result.

## Commands

State-mutating component commands are JSON-in/JSON-out CGAST filters. Human and
progress output is written to stderr, leaving stdout composable:

```sh
state=$(
  printf '{}\n' \
    | cgadl getmeta /path/to/metadata.sql \
    | cgadl select --user demo primary_language cpp \
    | cgadl download --output-dir "$MRVA_DB_SERVE_DIR" \
    | cgaql index /path/to/query-tree \
    | cgaql select --user demo language cpp \
    | cgaql pack \
    | cgamr submit --name demo-1 --user demo --language cpp
)
```

The principal commands are:

| Program  | Role                            | Typical commands                        |
| -------- | ------------------------------- | --------------------------------------- |
| `cgadl`  | choose prepared databases       | `getmeta`, `list`, `select`, `download` |
| `cgaql`  | choose prepared queries         | `index`, `list`, `select`, `pack`       |
| `cgamr`  | submit and retrieve MRVA work   | `submit`, `status`, `download`          |
| `cgamu`  | show the MRVA user view         | `serve`                                 |
| `cgasi`  | ingest and query SARIF          | `ingest`, `search`, `view`, `verify`    |
| `cgaex`  | export terminal results         | `human`, `llm`                          |
| `cgadfg` | inspect CGAST data/control flow | `cga dfg show`, `cga cfg show`          |
| `cgamx`  | manage local standalone MRVA    | `preflight`, `build`, `start`, `stop`   |
| `cgasv`  | dashboard header                | `serve`                                 |

`cgadl getmeta` accepts a local SQLite catalogue or URL. `cgaql index` accepts a
local directory containing `.ql` files. This explicit loading is the handoff
boundary from any preparation system, including CGA preparation.

## State

Top-level `cga` commands beneath an initialized workflow persist state under
`.cga/` and in its configured object store. `.cga/current.json` is a
compatibility copy for dashboard services; immutable history is authoritative.
`CGA_ROOT` and `CGA_TMPDIR` continue to control component-relative paths and
scratch space.

Direct component binaries have no implicit state files. Each reads one JSON
object from stdin, adds or updates its keys, and writes the object to stdout.
This interface remains useful for pipelines and tests, but normal workflows
should use the top-level dispatcher.

`cgadfg` is a read-only inspector rather than a CGAST filter. It reads the
legacy manifest format used before `.cga/`. Existing `cga dfg` and `cga cfg`
commands remain available to inspect those histories. New workflows use
`cga tree show`, whose text, Markdown, DOT, HTML, and PDF formats read `.cga/`
directly.

Selection history is user-tagged. The singular `cgadl-selection`, `cgadl-dbdir`,
`cgaql-selection`, and `cgaql-pack` values are the active inputs to the next
`cgamr submit`.

## Web view

For remote use, [CGA gateway](cgagateway/README.md) joins the dashboards, Unified
Views, Bench, its dynamically allocated VS Code editors, MRVA System View,
archive browser, and live documentation behind one loopback URL:

```sh
cga gateway start          # remote: gateway only; start viewers normally
# workstation:
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 \
  -L 8599:127.0.0.1:8599 hohn@svm
# Open http://127.0.0.1:8599/; reconnect with the same SSH command.
# remote:
cga gateway status
cga gateway stop           # leaves viewers and workflows running
```

The landing page also opens the **CGA overview**, **CGA help**, and **Reference
manual** over HTTP from the remote checkout. They need no local checkout or
additional SSH forward. Documentation is available even with no configured
viewers; build the optional book with `make -C docs book`. See
[documentation serving](cgagateway/README.md#documentation) for rebuild
commands.

For an ordinary static web server instead of the gateway:

```sh
cga public-html setup > /tmp/cga-public-html.sh
less /tmp/cga-public-html.sh
bash /tmp/cga-public-html.sh
```

Setup creates `~/public_html/single-machine-mrva` from the installed checkout's
committed HEAD if needed; an existing documentation clone is left untouched. Its
stdout is a documented Bash script for the extra book/lighttpd/permission steps,
not a transcript. Review it before running; setup itself starts no services and
changes no permissions. See
[static publication](../docs/README.md#static-publication-with-lighttpd).

For GitHub Pages instead, run `cga github.io setup`. It writes the publication
workflow in the installed checkout and prints the manual GitHub settings. It
does not commit, push, change remote settings, or deploy. See
[GitHub Pages publication](../docs/README.md#github-pages-publication).

The direct ports below remain available for development.

Start the CGA page at <http://127.0.0.1:8600/>:

```sh
cga serve start     # gateway + every viewer with existing configured state
cga serve status
cga serve stop
```

`cga serve` starts analysis and preparation dashboards, Unified Views, Bench,
the mrva-flow dashboards, and the gateway against existing state only.
Missing state is reported as `SKIP`; it never seeds samples, starts MRVA, or
prestarts assistants/editors. Open <http://127.0.0.1:8599/>.
Use `cga serve start --config /path/to/viewers.json` for separate workspaces;
see [unified startup](cgagateway/README.md#unified-viewer-startup).
Status/stop use the recorded ownership, regardless of the current directory.
An independent gateway can be reused, but is not stopped by the aggregate.

The direct analysis page remains at <http://127.0.0.1:8600/> and preparation at
<http://127.0.0.1:8500/>. The original `cga/cga-run` and `cga/cga-prep-run`
launchers remain available for independent development; do not mix lifecycle
owners on the same ports. `cga serve build|seed|outputs` retain their explicit
dashboard-only behavior, including destructive sample replacement with `seed`.

Use `cga run start|stop|status|build|seed` for only the analysis dashboard. Use
`cga view` to capture it or export a replay. The `cga-run` and `cga-view`
executables remain implementation details behind these commands.

Use `cga uv start|stop|status` for **CGA Unified View**, a separate read-only
page on port 8609. It combines the active `.cga` command flow, state deltas,
artifacts, source excerpts, transcripts, normalized component state, and a
compact proxy of the MRVA System View. It does not replace the existing views.

| Environment variable | Default | Service          |
| -------------------- | ------: | ---------------- |
| `CGA_PAGE_PORT`      |    8600 | composite page   |
| `CGA_CGASV_PORT`     |    8601 | header           |
| `CGA_CGADL_PORT`     |    8602 | database chooser |
| `CGA_CGAQL_PORT`     |    8603 | query chooser    |
| `CGA_CGAMR_PORT`     |    8604 | MRVA requestor   |
| `CGA_CGAMU_PORT`     |    8605 | user view        |
| `CGA_CGASI_PORT`     |    8606 | SARIF ingest     |
| `CGA_CGAMX_PORT`     |    8607 | command bridge   |
| `CGA_CGAEX_PORT`     |    8608 | result export    |
| `CGA_CGAUV_PORT`     |    8609 | unified view     |

Each fragment server exposes `/healthz`; `cgasv` exposes `/header`, and the
remaining visual components expose `/overview` and `/detail`. The page is
read-only except for commands intentionally routed through `cgamx`.

`cga view` captures the rendered CGA dashboard into JSONL and can export a
self-contained replay page. It captures only CGA components; CGA preparation is
a separate dashboard.

## Examples and verification

- [`sample-05/`](sample-05/README.md) demonstrates direct CGA selection and
  execution using existing database and query inputs.
- [`mrva-flow/`](mrva-flow/README.md) is the canonical single-user,
  operator-driven standalone flow with immutable history and dashboard capture.
- [`sample-05-i/`](sample-05-i/README.md) retains the earlier two-user
  standalone example for experimentation and possible expansion.
- [`cga/system-tests/run-system-09`](system-tests/run-system-09/README.md)
  prepares artifacts in a separate CGA preparation session, explicitly imports
  them into CGA, then verifies the complete real CodeQL/MRVA/SARIF/export path.

The LLM export schema is `cga.analysis-export.v2`; submission and job records
include zero-finding work and findings retain submission, session, job index,
and repository provenance.

## Layout

```text
cga/
  cga           unified two-level command dispatcher
  cgawf/        .cga workflow, chain, state, store, and artifact implementation
  completions/  bash completion for cga
  cga-run       analysis launcher and session (:8600)
  cga-prep-run  preparation launcher and session (:8500)
  cgalib/       shared HTTP and CGAST plumbing
  cgadl/        database library chooser
  cgaql/        query library chooser and packer
  cgaassist/    guided database preparation and recorded query authoring
  cgamr/        MRVA requestor
  cgamu/        MRVA user view
  cgasi/        SARIF ingestion
  cgaex/        human and LLM exports
  cgadfg/       whole-CGAST run graph inspector
  cgamx/        local MRVA lifecycle and command bridge
  cgasv/        dashboard header
  cga-view/     dashboard capture and replay
  cgauv/        read-only unified workflow/runtime view
  cgacc/        native Coder code-server browser workspaces (bin/lib/doc)
  cgacv/ cgasp/ cgadb/ cgaqg/   preparation: CVE, source, DB, query
  cgapg/ cgadbserve/ cgamrva/ cgactl/   preparation services and controller
  sample-05*/   direct-use examples
  web/          CGA analysis composite page
  web-prep/     CGA preparation composite page
```

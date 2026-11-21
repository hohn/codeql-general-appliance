# CGA Unified View (`cgauv`)

CGA Unified View joins the current `.cga` command history, state deltas,
artifacts, source provenance, command transcripts, component state, and live
MRVA system summary in one read-only page.

```sh
cga uv start
cga uv status
cga uv stop
```

The generic port is 8609 (`CGA_CGAUV_PORT`). `mrva-flow.sh` uses 8729 and
starts the view automatically.

For remote use, [CGA gateway](../cgagateway/README.md) serves these views at
`/unified/` and `/flow/unified/` under one SSH-forwarded port, including the
linked dashboards, MRVA System View, and VID inspector popups.

## Interface

- The top panel summarizes `/sysview/data` and links to the complete MRVA
  System View. Its triangle control collapses the summary cards and runtime
  details while leaving the heading and availability status visible.
- The left rail shows the active chain in command order, grouped into
  collapsible contiguous stages.
- Hover or keyboard focus previews command, delta, and source information.
- Clicking a command pins its normalized state/provenance/artifact detail.
- The lower pane displays the captured read-only command transcript.
- Failed attempts appear as red pseudo-steps without advancing CGAST.
- The upper-right theme dropdown offers dark, light, **font on white**, and
  **minimalist b&w**.
  Light uses a colorblind-friendly, primarily white/black palette. Font on white
  keeps all surfaces white and most text black; colored text is bold.
  Minimalist b&w adopts CGA Bench's system sans-serif typography and thin,
  square outlines, with monochrome selection/focus indicators and dashed/dotted
  failure/warning outlines. Source and transcript text remain monospaced.
  The choice is retained in browser-local storage. Element outlines are 1 px
  wide in every theme; workflow layout, controls, and behavior are unchanged.

The analysis model and transcript panes expose read APIs:

```text
GET /
GET /healthz
GET /api/model
GET /api/outline
GET /api/search
GET /api/step?id=<node-or-attempt>
GET /api/artifact?id=<artifact>
GET /api/collections/databases
GET /api/collections/queries
GET /api/sysview
GET /existing/source
GET /api/vid/registry
GET /api/vid?ref=<reference>
GET /api/vid/related?ref=<reference>
GET /vid?ref=<reference>
```

It intentionally has no analysis command/apply endpoint. A shared VID inspector
does expose `POST /api/vid/terminal` for explicit local shell interaction, guarded
by loopback Host, same-origin, JSON, and `X-CGA-VID: 1` checks. The shell uses the
operator's normal account and is not a read-only sandbox; the workflow/transcript
panes themselves remain inspection-only.

Existing views remain independent and supported: CGA Workflow State, MRVA
System View, dashboard replay, and `.cga` DFG/CFG exports.

## Outline and search

For assistant discovery, use `cga llm context unified` (alias `cga llm cu`).
It reads the local redacted outline without HTTP requests or state changes.
`--show-html-endpoint`, `--show-json-endpoint`, and `--show-docs` print the
viewer URL, outline URL, or local documentation paths. URLs honor
`CGA_CGAUV_PORT` or an explicit `--port PORT`; they do not start a viewer.

```sh
cga uv outline
cga uv outline --format json --detail summary
cga uv outline --match-tag audience:user
cga uv outline --include-sensitive

cga uv search Fprintf
cga uv search --match-tag presentation:progress
cga uv search --kind database --format json --limit 20
```

Normalized responses carry versioned schemas:

- `cga.use.model.v1`
- `cga.use.step.v1`
- `cga.use.artifact.v1`
- `cga.use.outline.v1`
- `cga.use.search.v1`
- `cga.use.collection.v1`

Search and collection responses include offset, limit, count, total, and
explicit truncation metadata.

Outline/search projections exclude `sensitivity:secret` entities by default and
report redaction counts. `--include-sensitive` is an explicit local override;
do not use it when sending output to an external LLM. Direct local detail APIs
remain available for human/operator inspection.

Selected databases and queries are linked normalized collections with text
search, exact-field filtering, sorting, and pagination. The browser exposes
these tables from the workflow rail. They read retained immutable selections,
not whatever a working selection file contains today.

## Shared element references

Workflow controls, successful steps, failed attempts, retained artifacts, and
selected collection rows carry the same opaque VIDs used by Bench and the CLI.
For example, `:h7m,1` identifies the first successful command on the qualified
chain; its identity survives filtering, stage regrouping, and sorting.
`cga show --registry` lists the permanent three-character base-36 roots.

Small anchor symbols (Unicode U+2693) follow labels and compact controls; their
tooltips and accessible names expose the VID. Single-click only copies the short
VID. Double-click copies it and opens an independent popup with matching origin color, the full
qualified reference, accumulated immutable facts, and the opening fact frontier.
Clipboard failures are visible and do not prevent inspection or run the adjacent action.
Its xterm.js terminal is separate from both the captured transcript and other
popups. **Paste Copilot command with context** never sends Enter; it inserts a
normal-permission Copilot command referring to the pinned private context file.
Closing the window stops its shell; a 120-second inactivity lease handles lost
tabs, and viewer shutdown stops all owned popup terminals.

```sh
cga show :h7m,1
cga related :h7m,1 --json
cga open :h7m,1 --url http://127.0.0.1:8609
```

See the shared [VID contract](../README.md#visual-element-identifiers-vids)
for context qualification, historical evidence, collection generations, and
secret-tag handling.

## Tags

The dispatcher accepts common `--tag` options anywhere before an argument
separator (`--`). It removes them before component parsing and records both the
readable profiles and expanded canonical tags on `.cga` nodes, failed attempts,
and directly produced artifact occurrences.

```sh
cga dl getmeta --tag user:viewable metadata.sql
cga --tag audience:user --tag subject:query ql index queries/
```

Current readable profiles:

```text
user:viewable
user:show-progress
user:primary-interest-data
```

Canonical keys are `audience`, `prominence`, `searchable`, `sensitivity`,
`subject`, and `presentation`. Unknown keys or invalid controlled values fail
explicitly.

Flow stage grouping is presentation metadata in `flow-view.json`; it does not
change script execution or graph relations. Workflows without that file use
the generic command-stage fallback. Its optional `source` field supplies the
read-only source link in the CGA Unified View header.

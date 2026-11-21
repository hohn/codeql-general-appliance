# CGA Flow Plan

Evolving outline for CGA use, flow design, and future editing facilities.

## Scope and terminology

CGA has two distinct concerns:

1. **CGA use** — running, observing, comparing, and reviewing analysis flows.
2. **CGA development** — changing CGA components, storage, APIs, and UI code.

This plan is primarily about **CGA use**. Development work should expose stable
interfaces that make CGA use understandable to humans, scripts, and LLMs.

Canonical names:

- **CGA Unified View** (`cgauv`, `cga uv`) joins workflow, state, provenance,
  transcripts, artifacts, and a compact MRVA runtime summary.
- **CGA Workflow State** is the existing component-oriented dashboard.
- **MRVA System View** is the internal server/worker/job runtime view.
- `.cga/` is the durable workflow repository. Its graph is relational even
  when a UI uses stages or nested boxes for presentation.

`cgaud` is obsolete terminology; the component acronym is `cgauv`.

## Principles

- Flow scripts are the origin of workflow intent, order, and mutable choices.
- Keep flow scripts legible, concise, and close to a human MRVA specification.
- Do not move flow semantics into UI configuration or generated framework code.
- Keep the canonical workflow representation textual and machine-readable.
- Treat every visual view as a projection of workflow/state/runtime data.
- Preserve existing views; add links and shared identities rather than forcing
  one UI to contain every detail.
- Start with a compact primary view and reveal details on demand.
- Do not imply that presentation nesting is authoritative graph topology.
- Keep current state, immutable history, failed attempts, source provenance,
  transcripts, and artifacts distinguishable.
- Prefer read-only observation until an editing/execution operation has a clear
  purpose, permission model, audit trail, and recovery behavior.
- Keep browser, CLI, VS Code, and LLM clients on the same versioned data model.

## Scripts are the source of truth

### User-facing core

The core of a flow should read like an executable specification assembled from
small CGA building blocks:

```sh
cga dl getmeta ...
cga ql index ...
cga dl sql ...
cga dl download ...
cga ql select ...
cga ql pack

cga mr run ...

cga si ingest ...
cga ex human ...
cga ex llm ...
cga si verify ...
cga mx check

cga view ...
cga tree show -v --format html ...
cga tree show --control-flow --format html ...
```

Environment setup, lifecycle scaffolding, output locations, and instrumentation
are necessary, but they are not the conceptual flow a CodeQL user should have
to reason about first.

### Consequences

- [ ] Preserve the script as the authoritative, editable workflow definition.
- [ ] Keep CGA commands composable enough that the script structure remains
      close to a numbered natural-language MRVA specification.
- [ ] Keep introspection implicit in CGA command execution; do not add verbose
      instrumentation calls to the script.
- [ ] Make CGA Unified View derive its command rail and source excerpts from the
      executed script rather than a separate UI flow definition.
- [ ] Treat stage grouping and presentation tags as non-semantic hints.
- [ ] Keep generated workflow code reviewable and intentionally sparse.
- [ ] Establish style guidance for LLM-generated flow scripts:
  - one meaningful CGA operation per command
  - descriptive variables instead of expanded literals
  - no duplicated state threading
  - no hidden multi-subsystem shell functions
  - bounded compound commands only when they represent one user operation
  - setup separated visually from the conceptual flow

### LLM role

LLMs are well suited to translate a concise MRVA specification into a CGA flow
script because:

- CGA commands provide constrained building blocks.
- The generated script remains close to the original specification.
- `.cga` automatically supplies provenance, state history, artifacts,
  transcripts, attempts, and graphical/text projections.
- The script remains inspectable and editable by a human.

- [x] Define a spec-to-script prompt/template.
- [x] Add an example pairing an MRVA specification with its concise CGA script.
- [x] Add a review checklist for generated scripts.
- [ ] Validate generated scripts structurally before execution.
- [ ] Avoid generating dense, monolithic workflow implementations from scratch.

## 1. LLM support for CGA use

### Goal

An LLM should be able to understand and navigate a CGA workflow without
scraping rendered HTML or loading the complete state and artifact set at once.

### Current foundation

- [x] `.cga/manifest.json` records chains, successful nodes, failed attempts,
      commands, relations, state objects, artifacts, timing, source excerpts,
      and transcript references.
- [x] `cgauv` provides normalized read-only endpoints:
  - `/api/model`
  - `/api/step?id=...`
  - `/api/sysview`
- [x] CLI inspection exists through `cga status`, `cga chain`, `cga state`,
      `cga step`, `cga log`, `cga tree`, and `cga artifact`.
- [x] Human and LLM result exports exist through `cga ex human` and
      `cga ex llm`.

### Searchable outline and text projection

- [ ] Define a versioned **CGA use model** independent of HTML layout.
- [ ] Provide all CGA Unified View content as concise outline/text:
  - workflow and active-chain summary
  - grouped command steps
  - parent/child and artifact relations
  - state-delta summaries
  - source provenance
  - transcript availability and excerpts
  - active MRVA submission/runtime summary
- [ ] Add a stable JSON schema identifier to normalized API responses.
- [ ] Add a text/Markdown endpoint, tentatively:
  - `GET /api/outline`
  - `cga uv outline`
- [ ] Support detail levels so callers can control context size:
  - summary
  - stage
  - step
  - full state delta
  - transcript
  - artifact metadata
- [ ] Support search/filter without downloading all detail:
  - command/tool/action
  - stage
  - state key
  - artifact kind/name
  - source path
  - status/failure
  - submission/user/session/repository
- [ ] Add stable deep links for every user-relevant entity:
  - workflow/chain/stage/step/attempt
  - selected database
  - selected query
  - submission/session/job/repository
  - ingestion/finding
  - export/artifact
- [ ] Ensure summaries link to the complete underlying collection rather than
      silently truncating it.
- [ ] Expose selected database and query collections as normalized resources,
      not only static HTML tables or opaque selection artifacts.
- [ ] Add filtering, search, sorting, and pagination for long collections.
- [ ] Preserve the originating script command and selection criteria alongside
      the resulting selected items.
- [x] Define deterministic ordering and stable identifiers.
- [x] Define result-size limits and explicit pagination/truncation metadata.
- [x] Define initial sensitivity-tag redaction before external LLM use; expand
      field-level tagging as new sensitive data is identified.
- [ ] Add examples of LLM tasks:
  - explain the current flow
  - locate the command that introduced a state key
  - summarize a failed attempt
  - compare two chains
  - find relevant source and transcript excerpts
  - enumerate produced artifacts
  - assess MRVA completion and findings

### Commentary

The outline should be generated from the same normalized model as the UI, not
maintained as a second semantic database. HTML remains a client. LLMs should
prefer JSON or Markdown with explicit schema/version and truncation markers.

The existing `/api/model` plus `/api/step` split is a useful pattern: first
retrieve a small navigational summary, then request only selected detail.

Every summary should answer both:

1. What is important now?
2. Where is the complete detail?

No user-relevant detail should exist only in a static dashboard fragment.

## User relevance and presentation metadata

### Problem

Current CGAST, component state, runtime state, and artifacts mix:

- information central to a CodeQL/MRVA user
- operator/lifecycle information
- system implementation detail
- diagnostic/debug detail

The distinction has not been identified consistently. CGA Unified View should
not hard-code all of these judgments, and flow scripts should not be cluttered
with presentation annotations.

### Proposed non-intrusive tags

Use optional structured metadata with two layers:

1. defaults attached to command/state/artifact descriptions
2. flow-specific tags attached at the authoritative script command site

```text
audience:    user | operator | system
prominence:  primary | detail | diagnostic
searchable:  true | false
sensitivity: normal | local-sensitive | secret
subject:     catalogue | query | selection | run | finding | result | export | ...
presentation: progress | collection | summary | ...
```

Interpretation:

- `audience` says who normally needs the information.
- `prominence` controls default placement, not accessibility.
- `searchable` identifies useful indexed fields.
- `sensitivity` controls rendering, export, and LLM disclosure.
- `subject` identifies what the tagged step/data represents.
- `presentation` is an optional view hint; it should not be confused with
  relevance or execution semantics.

Unknown or untagged data should default to `detail`, remain reachable, and not
be sent to an external LLM automatically.

### Where tags should live

- [ ] Command metadata owned by the component that defines the command.
- [ ] State-key metadata keyed by exact key or stable key pattern.
- [ ] Artifact-kind metadata owned by artifact producers.
- [ ] MRVA runtime-field metadata owned by the sysview schema.
- [ ] Flow-specific command tags in the script when relevance differs for that
      flow.
- [ ] Optional flow-level sidecar defaults only when repeating tags would make
      the script materially less legible.

The tags must not become a second source of workflow semantics. They influence
projection, search, and disclosure only.

### Script tagging requirements

- [x] Define one controlled `key:value` vocabulary before applying tags broadly.
- [x] Decide initial tag scope explicitly:
  - command/step
  - resulting state keys
  - resulting artifacts
  - referenced collection items
- [ ] Define reusable component/schema defaults and inheritance to flow
      overrides.
- [x] Parse common tags in the top-level `cga` dispatcher so every component
      does not need its own `--tag` implementation.
- [x] Store normalized tags in `.cga` node/attempt metadata.
- [x] Propagate tags to directly produced logical artifact occurrences while
      deduplicating only their CAS bytes.
- [x] Preserve tags in outline, search, collection, and deep-link APIs.
- [x] Reject unknown controlled tag keys/values.
- [x] Keep tags short enough that the command remains close to the MRVA
      specification.

Tentative syntax:

```sh
cga \
  --tag audience:user \
  --tag prominence:detail \
  --tag subject:database-catalogue \
  dl getmeta ...
```

The dispatcher supports common `--tag` options anywhere before an argument
separator (`--`), removes them before component parsing, and records them on the
`.cga` node or attempt. This keeps tags adjacent to the operation they describe
without changing every component parser.

Readable shorthand profiles can coexist with a controlled stored vocabulary:

```text
user:viewable              -> audience:user, prominence:detail
user:show-progress         -> audience:user, presentation:progress
user:primary-interest-data -> audience:user, prominence:primary
                              subject:human-results
```

Search and APIs should expose the expanded canonical tags. The script may retain
the concise profile when that materially improves readability.

### Review of the initial `mrva-flow.sh` tag experiment

The intent is useful, but the example vocabulary mixes separate concerns:

- `user:viewable` combines audience and accessibility. User-relevant details
  should already be reachable; a more searchable form is
  `audience:user`, `prominence:detail`, and a concrete `subject`.
- `user:show-progress` combines audience with a presentation behavior. Prefer
  `audience:user` plus `presentation:progress`.
- `user:primary-interest-data` captures the right intent but should be split
  into `audience:user`, `prominence:primary`, and a subject such as
  `subject:human-results`.

Tags on a command are not automatically sufficient to search the items inside a
selected database/query collection. The producer must expose normalized
collection items and define whether command tags propagate to those items.

The pilot tags in `mrva-flow.sh` are executable. Common tag parsing/storage is
implemented and the accidental `--user "$FLOW_USER"` regression was restored.

### Uses

- [ ] Default CGA Unified View detail selection.
- [ ] Human “show user/operator/system detail” filters.
- [ ] Search facets.
- [ ] LLM context selection.
- [ ] Redaction and disclosure warnings.
- [ ] Outline detail levels.
- [ ] Diagnostics view.

## 2. Text editing and execution facilities

### xterm.js

- [ ] Keep xterm.js as a possible client, but do not add it without a concrete
      operation.
- [ ] Before a real terminal, define:
  - what process or shell it controls
  - working directory and environment
  - authentication and authorization
  - PTY/WebSocket lifecycle
  - resize and reconnect behavior
  - command and output audit trail
  - timeout/cancellation
  - workspace and filesystem boundaries
  - how terminal actions relate to `.cga` attempts/nodes

### Commentary

A terminal is an execution surface, not a text-editing abstraction. It may be
useful for debugging or running explicit flow operations, but it does not by
itself provide safe structured editing, provenance, diagnostics, or review.

The current terminal-styled pane should remain read-only until an executable
use case is selected.

### Lower-risk editing path

- [ ] Add source-location actions:
  - copy path and line range
  - open source in the local editor
  - open transcript/artifact location
- [ ] Define structured edit operations before arbitrary shell access:
  - edit a query
  - change a flow parameter
  - select databases/queries
  - branch from a prior step
  - rerun a bounded stage
- [ ] Record edits and executions as attempts with source/provenance.
- [ ] Keep changes reviewable before execution.

### VS Code option

- [ ] Evaluate a VS Code extension or webview host for CGA Unified View.
- [ ] Reuse `cgauv` APIs and frontend concepts rather than moving the semantic
      model into VS Code.
- [ ] Candidate VS Code integrations:
  - reveal source range in an editor
  - show diagnostics
  - use native diff/review
  - run named tasks
  - use an integrated terminal when explicitly requested
  - share selected step/context with Copilot/LLM tools

### Commentary

Do not make VS Code the only CGA client. A VS Code host is attractive for
editing, but the localhost web UI and CLI should remain viable. The preferred
architecture is:

```text
.cga + object store + MRVA
            |
      versioned CGA use model
       /         |          \
    browser     CLI       VS Code
```

This keeps automation, remote use, and non-VS-Code environments possible.

## 3. Flows to accommodate in CGA Unified View

### Shared flow contract

Before adding more flow scripts, define what every flow exposes.

- [ ] Workflow identity and version.
- [ ] Entry script(s) and supported actions.
- [ ] Stage metadata:
  - stable stage ID
  - display name
  - order
  - command membership
- [ ] Inputs, outputs, and artifact kinds.
- [ ] Source provenance.
- [ ] Success/terminal criteria.
- [ ] Retry/resume/branch semantics.
- [ ] Runtime services and health endpoints.
- [ ] Flow-specific summary fields.
- [ ] Optional comparison dimensions.
- [ ] Optional presentation metadata overrides that do not alter execution.

Stage grouping should eventually come from flow metadata rather than a
hard-coded command-token table in `cgauv`.

### `mrva-flow`

- [x] Single `mrva-flow.sh` driver.
- [x] One `.cga` node per meaningful state transition.
- [x] Grouped command rail in CGA Unified View.
- [x] Source, timing, transcripts, state deltas, component state, and artifacts.
- [x] Compact joined MRVA system summary.
- [x] Existing workflow-state, sysview, replay, DFG, and CFG views remain viable.
- [x] Define `mrva-flow/flow-view.json` presentation-only stage metadata.
- [x] Link the authoritative flow source from CGA Unified View.
- [x] Add flow-level outline/text export.
- [ ] Add linked, searchable selected-database and selected-query views.
- [ ] Decide whether internal `cga mr run` checkpoints should be expandable
      sub-operations in CGA Unified View.

### `query-dev-flow`

Planned driver: `query-dev-flow.sh`.

Primary purpose: iterative development of one query against selected databases.

Candidate stages:

1. Select/adopt query source.
2. Select one or more representative databases.
3. Compile/pack query.
4. Run fast local validation.
5. Inspect findings and diagnostics.
6. Edit or branch.
7. Compare rerun with baseline.
8. Promote/export accepted query.

Needs:

- [ ] Query source and pack identity.
- [ ] Compiler diagnostics and source locations.
- [ ] Fast rerun semantics that do not rebuild unrelated infrastructure.
- [ ] Baseline-versus-candidate result comparison.
- [ ] Finding examples linked to query source.
- [ ] Explicit accepted/rejected experiment records.
- [ ] Editor integration is likely more valuable here than a generic terminal.

### `query-suite-review-flow`

Planned driver: `query-suite-review-flow.sh`.

Primary purpose: review multiple queries across a representative database suite.

Candidate stages:

1. Select query suite/version.
2. Select database matrix.
3. Plan query × database work.
4. Execute bounded batches.
5. Aggregate findings, failures, and performance.
6. Review query-level summaries.
7. Drill into outliers/findings.
8. Record review disposition.
9. Export review report.

Needs:

- [ ] Matrix and batch representation without flattening thousands of steps into
      one rail.
- [ ] Hierarchical presentation for navigation, while preserving many-to-many
      query/database relations.
- [ ] Query and database facets.
- [ ] Performance/resource summaries.
- [ ] Partial completion and retry semantics.
- [ ] Review annotations/dispositions.
- [ ] Comparisons across suite versions or prior runs.
- [ ] Sampling and pagination for LLM/human context limits.

### Commentary on multiple flows

`mrva-flow` is linear and small. It should not dictate the only presentation.
Future flows need a common model with optional projections:

- chronological command flow
- stage summary
- matrix
- comparison
- finding/review queue
- artifact/provenance graph

The underlying relations should remain explicit so each projection can be
derived without changing workflow truth.

## Cross-cutting design questions

- [ ] How are flows discovered?
  - directory containing `.cga/`
  - registered workspace catalogue
  - explicit `cga -C PATH`
- [ ] Should CGA Unified View select among workflows, or remain scoped to one
      `.cga` root per server?
- [ ] How are flow metadata and UI hints versioned?
- [ ] Which state is canonical when live runtime and durable workflow disagree?
- [ ] How should stale/unavailable runtime state be represented?
- [ ] Which annotations belong in `.cga`, and which belong in an external review
      store?
- [ ] How are branches and comparisons selected without displaying the entire
      forest at once?
- [ ] What is the authorization model before adding editing or execution?
- [ ] Which operations must work remotely?
- [ ] Which fields are user, operator, system, or diagnostic information?
- [ ] Who owns relevance tags and reviews changes to them?
- [ ] Can every summary/detail count be followed to the complete collection?
- [ ] How should script setup be folded/collapsed without obscuring that the
      script remains authoritative?

## Proposed roadmap

### Phase 1 — searchable CGA use model

- [x] Define controlled tag vocabulary.
- [x] Define initial command/attempt/artifact/collection tag scope.
- [x] Implement common tag parsing and `.cga` storage.
- [x] Pilot structured tags in `mrva-flow.sh`.
- [x] Index tags and expose tag filtering/search.
- [x] Version normalized model, step, artifact, outline, search, and collection
      schemas.
- [x] Add `/api/outline` and `cga uv outline`.
- [x] Add bounded search/filter/detail-level controls with explicit pagination
      and truncation metadata.
- [x] Document and implement LLM-safe outline/search redaction for
      `sensitivity:secret`, with explicit local override and redaction counts.
- [x] Move `mrva-flow` stage metadata out of `cgauv` command heuristics while
      retaining a generic fallback for other flows.
- [x] Add linked selected-database and selected-query resources.
- [x] Add server-side filtering/search/sorting/pagination for long collections.
- [x] Add spec-to-script guidance, template, style rules, and review checklist
      in `cga/cgawf/FLOW-SCRIPT-GUIDE.md`.

### Phase 2 — multiple read-only flows

- [ ] Define the shared flow contract.
- [ ] Implement `query-dev-flow.sh`.
- [ ] Adapt CGA Unified View to query-development details.
- [ ] Implement `query-suite-review-flow.sh`.
- [ ] Add matrix/comparison/review projections.

### Phase 3 — structured editing

- [ ] Add editor reveal/open actions.
- [ ] Add reviewed parameter/query edits.
- [ ] Add bounded rerun/branch actions with audit records.
- [ ] Evaluate VS Code extension/webview integration.

### Phase 4 — optional interactive execution

- [ ] Select a concrete xterm.js use case.
- [ ] Design PTY/auth/audit/lifecycle boundaries.
- [ ] Implement only if structured operations and editor integration are
      insufficient.

## LLM notes

- Treat this file as an evolving outline; update decisions and checkbox state as
  work progresses.
- Use `cgauv`, never `cgaud`.
- Keep **CGA use** requirements separate from CGA implementation details.
- Treat flow scripts as the authoritative mutable workflow source.
- Keep generated scripts close to the user's numbered MRVA specification.
- Do not move execution choices into CGA Unified View metadata.
- Do not infer tree semantics from nested UI boxes.
- Do not parse HTML when a normalized JSON/text representation exists.
- Retrieve summaries first and details on demand.
- Preserve source/transcript/artifact provenance in recommendations.
- Keep existing CGA Workflow State, MRVA System View, replay, DFG, and CFG views
  working.
- Do not introduce an interactive terminal as a convenience-only feature.
- Prefer editor-native operations for editing and diagnostics.
- New flow-specific UI requirements should first be expressed as additions to a
  shared flow contract or normalized model.
- Presentation/relevance tags must not change execution semantics.
- Script-site tags are valid flow-specific metadata, while component metadata
  provides reusable defaults.
- “Primary” and “detail” affect defaults only; all non-secret user-relevant
  information must remain reachable by links.

## Decision log

- 2026-09-29: CGA Unified View version one is live-current-state and read-only.
- 2026-09-29: Command steps are grouped into contiguous functional stages.
- 2026-09-29: Detail selection is pinned by click; hover/focus provides preview.
- 2026-09-29: Terminal pane is transcript-only; interactive xterm.js is deferred.
- 2026-09-29: Failed attempts are recorded separately and do not advance CGAST.
- 2026-09-29: Existing views remain supported and linked.
- 2026-09-30: Canonical component acronym changed from `cgaud` to `cgauv`.
- 2026-09-30: Flow scripts are the authoritative source of workflow intent and
  the only currently mutable workflow component.
- 2026-09-30: CGA Unified View remains a projection; it must not replace script
  semantics.
- 2026-09-30: User-relevant details must be linkable and long collections must
  support filtering/search.
- 2026-09-30: Relevance metadata will be non-intrusive and non-semantic.
- 2026-09-30: Tag vocabulary, scope, storage, and pilot application precede the
  searchable CGA use model.
- 2026-09-30: Flow scripts may carry concise flow-specific tags; reusable
  defaults remain owned by components and schemas.
- 2026-09-30: Phase 1 implemented common tag profiles/canonical facets,
  versioned outline/search/collection schemas, `cga uv outline/search`, and
  linked searchable selected-database/query collections.
- 2026-09-30: Logical artifact occurrences retain producer-specific tags;
  content-addressed bytes remain deduplicated.
- 2026-09-30: `mrva-flow` stage grouping moved to non-semantic
  `flow-view.json`; generic fallback remains for unannotated flows.
- 2026-09-30: Outline/search hide `sensitivity:secret` by default and report
  redaction counts; local callers may opt in explicitly.

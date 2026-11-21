# Agent core

Read this file first; do not reread it when a later guide links back here.
For CGA work, next choose one route in the
[LLM exploration guide](../docs/cga-help-llm.org). For other work, use only the
matching topic below. These links are choices, not a reading checklist.

Expand from the task to relevant help/state, a named contract section, then
the owning component only when needed. Stop expanding when the task is answerable.

## Purpose

This entire repository is a science experiment and prototype. The goals are
handling CodeQL databases and queries, applying queries to databases, and
supporting humans and LLMs in investigating results. Code, usage documentation,
and examples evolve together; none is useful without the others.

Examples permit experimentation and are retained for future expansion. E2e tests
are fixed examples with assertions that test the code. Do not equate a
successful pipeline with an effective vulnerability detector. Remove obsolete
documentation rather than archiving it; Git retains the history.

## Essential invariants

- Use `cga` for normal recorded workflows. Direct component binaries remain
  JSON-in/JSON-out filters; stdout is state, diagnostics belong on stderr.
- Preparation and analysis use separate state with an explicit artifact handoff.
  `.cga/` owns workflow metadata and local runtime/scratch; its configured store
  owns content-addressed objects.
- Large sources, databases, archives, and results belong outside Git and outside
  PostgreSQL. PostgreSQL stores operational state and references. Do not delete
  external artifact trees or treat ignored symlinks as junk.
- Preserve operator-supplied configuration. Go fills defaults only when env vars
  are unset; harnesses keep overrides visible. Ask when configuration ownership
  or behavior is ambiguous.
- Keep lifecycle phases decoupled: preflight checks/reclaims; start starts. A
  stale `mrvaserver` on `:8081` can serve an old binary. Read the relevant
  lifecycle notes before starting/resetting shared infrastructure.
- Bench, mrva-flow, and standalone tests can share MRVA ports and PostgreSQL.
  Separate scratch directories do not make concurrent runs independent.
- Server and worker modules use the local sibling `mrvacommander` module.
  Build/test in the owning module, not as one root Go module.
- Preserve examples and update their usage explanations with behavior changes.
  Use the smallest relevant check; do not run a resetting e2e just to explore.

## Read only the matching topic

| Task                                                        | Topic                             |
| ----------------------------------------------------------- | --------------------------------- |
| Host setup, CodeQL Java, Git environment                    | [Environment](environment.md)     |
| Command routing, workflow state, assistant context, VIDs    | [CGA](cga.md)                     |
| Experiment invariants, checkpoints, viewer/editor lifecycle | [Bench](bench.md)                 |
| Source/database/query preparation, catalogues, controller   | [Preparation](preparation.md)     |
| Deployment, configuration, scheduling, identity, storage    | [MRVA runtime](mrva-runtime.md)   |
| Standalone e2e phases and scenario selection                | [System tests](system-tests.md)   |
| Live sysview, Unified View, replay, shared rendering        | [Views](views.md)                 |
| Markdown, books, generated files, line counting             | [Documentation](documentation.md) |

For live experiment context, prefer the bounded read-only
`cga llm context bench` or `cga llm context unified` projection before opening
raw state, result archives, or implementation trees. See
[Assistant context](../cga/README.md#assistant-context).

Only if focused investigation cannot establish ownership, use the
[advanced project map](../READING-GUIDE.md#reading-paths) as a last resort.

Keep this core short. Put new subsystem details in their topic file, not here.

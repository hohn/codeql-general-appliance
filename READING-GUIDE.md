# Advanced reading guide

This guide assumes practical CodeQL experience: databases, query packs, SARIF,
and reading shell workflows. It is intended for experienced humans and LLMs, not
as an introduction to CodeQL or CGA. Audience markers below do not imply
beginner accessibility.

For a first look and a fixed worked example, start with the
[CGA overview](docs/cga-overview.html), then use [CGA help](docs/cga-help.html)
for tasks and commands. The [introductory guide](INTRODUCTORY-GUIDE.md) offers
additional usage outlines; the [reference manual](docs/book/index.html) collects
detailed material.

This repository is a science experiment and an evolving prototype, not a
finished software product. Its purpose is to handle CodeQL databases and
queries, apply queries to databases, and help humans and LLMs investigate the
results. The code makes those activities possible; usage, examples, and their
explanations are equally important. Code and examples evolve together.

Use this guide to choose a small reading path, not to read the repository cover
to cover. The paths point into existing documentation; they are not additional
tutorials or instructions to launch services.

## How to read

**[Both]** is useful to humans and LLMs, **[Human]** emphasizes explanation and
interactive exploration, and **[LLM]** emphasizes bounded discovery and
implementation constraints. These are reading hints, not access restrictions.

**Start** means the initial reading for that question. **Reference** means
follow the link only when the question needs that detail. **Stop** identifies
what you should understand before returning to your experiment or task.

**[LLM]** This is the broader project map, not mandatory onboarding. Read the
short [agent core](.agent-notes/README.md) once, then use the
[CGA LLM entry guide](docs/cga-help-llm.org) for CGA work or the core's matching
topic for other tasks. Return here only if that focused route and
component-local investigation cannot establish ownership.

When that fallback is needed, choose one question below. Read named sections,
not entire documents or the example catalogue. Follow other component links
only when evidence crosses their boundary. For an existing experiment, inspect
its bounded state projection before reading implementation code or raw artifacts.

## Orientation [Both]

The main activities are:

| Activity                    | What it contributes                                                                           | Starting document                        |
| --------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Prepare inputs              | Acquire sources, build and validate CodeQL databases, materialize queries, publish catalogues | [Preparation](cga/README-prep.md)        |
| Apply queries               | Select databases and query packs, submit MRVA jobs, download results                          | [CGA](cga/README.md)                     |
| Investigate and compare     | Work with accepted inputs, frozen results, and explicit experiment comparisons                | [Bench](cga/cgabench/README.md)          |
| Retain and explain evidence | Record workflow steps, provenance, SARIF ingestion, and human/LLM exports                     | [CGA workflows](cga/README.md#workflows) |

CGA is the command interface joining these activities. MRVA is the execution
system: a server schedules query evaluations across databases and workers return
SARIF. Bench provides an experiment/session interface. Preparation and analysis
exchange artifacts explicitly; they do not share one mutable session.

## Reading paths

### Understand an end-to-end analysis [Both]

**Question:** How do selected databases and a query become inspectable results?

**Start:** Read the introduction and **Flow** in the
[single-user MRVA example](cga/mrva-flow/README.md#flow), then read its
[driver](cga/mrva-flow/mrva-flow.sh) alongside that sequence.

**Reference:** [CGA State](cga/README.md#state) explains the state passed
between operations. Follow only the component README for the step you are
exploring. Read the example's **Run it** section before actually running it: it
manages shared infrastructure and leaves services available for inspection.

**Stop:** You can identify database selection, query packing, execution,
ingestion, and export, and distinguish setup/teardown from the analysis.

### Explore query or database changes [Both]

**Question:** What changes between sessions, and what makes a comparison valid?

**Start:** Read **Experiment purpose and contract (humans and LLMs)** and
**Session actions** in the [Bench guide](cga/cgabench/README.md).

**Reference:** Continue to that guide's commands and human/LLM interfaces for
your chosen interaction. Read [Bench operational notes](.agent-notes/bench.md)
only for implementation changes, recovery, or viewer lifecycle questions.

**Stop:** You can explain the fixed versus changing input, S1 as the reference,
the D/Q/J/R cells, and why running a session and comparing results are different
operations.

### Prepare databases and queries [Both]

**Question:** Where do analysis inputs come from, and how are they handed over?

**Start:** Read the [preparation introduction](cga/README-prep.md) and its
[explicit handoff](cga/README-prep.md#explicit-handoff-to-cga). For a concrete
worked sequence, read **Componentized preparation** in the
[query-030 example](cga/analysis/CVE-2016-9843/query-030/README.md#componentized-preparation).

**Reference:** Use the [CVE catalogue](cga/examples/cves/README.md) to choose
another case. Read only the relevant preparation command's README when changing
source acquisition, database construction, validation, or indexing.
[Preparation notes](.agent-notes/preparation.md) cover campaign and storage
constraints.

**Stop:** You can locate source/database/query provenance and explain which
artifacts are explicitly imported into a separate analysis workflow.

### Investigate findings and supporting evidence [Both]

**Question:** What does this result establish, and where is its evidence?

**Start:** Read [named ingestion](cga/cgasi/README.md#named-ingestion) and the
[export contract](cga/cgaex/README.md). For an actual investigation, read the
[zlib study](cga/analysis/CVE-2016-9843/README.md) and choose one query
checkpoint rather than reading all of them.

**Reference:** The [analysis evidence index](cga/analysis/README.md) points to
preserved collection runs; their query-effectiveness reports distinguish
candidate findings from demonstrated CVE detections. Large evidence trees live
outside Git; follow their manifests, not a recursive artifact dump.

**Stop:** You can trace a finding to its query, database, submission, and
ingestion, and distinguish successful execution, zero findings, and detector
effectiveness.

### Inspect an existing experiment or workflow [LLM]

**Question:** What is already selected or completed, without re-reading or
rerunning everything?

**Start:** Read [Assistant context](cga/README.md#assistant-context). Use
`cga llm context bench` for experiment/session state or
`cga llm context unified` for the workflow outline, in the relevant workspace.
These are read-only and do not need a running web server.

**Reference:** Follow the returned documentation or resource references.
[Visual element identifiers](cga/README.md#visual-element-identifiers-vids)
explain shared addresses for CLI and UI facts.
[Unified outline and search](cga/cgauv/README.md#outline-and-search) provides
more targeted discovery.

**Stop:** You know the current inputs, completed work, and unresolved step. Open
full source, state, or result artifacts only to answer a specific remaining
question.

### Evolve a usage example [Both]

**Question:** How should a new or changed experiment express its operations?

**Start:** Read the [flow script guide](cga/cgawf/FLOW-SCRIPT-GUIDE.md), then
choose the closest [example below](#examples-and-fixed-checks-both).

**Reference:** Read [CGA Workflows](cga/README.md#workflows) and
[State](cga/README.md#state) when changing recording or composition.
[CGA notes](.agent-notes/cga.md) describe non-obvious integration constraints.

**Stop:** Each meaningful operation and experimental choice is visible, with
explicit inputs, outputs, lifecycle, and provenance. Change supporting code and
usage documentation together when the example needs new behavior.

### Change or debug the supporting code [Both]

**Question:** Which implementation owns the behavior observed in the example?

**Start:** Locate the example's failing or changing operation first. Use
[CGA Layout](cga/README.md#layout) for command ownership or the root README's
[MRVA component map](README.md#mrva-component-map) for server, worker,
scheduling, and storage behavior.

**Reference:** Read only the matching agent topic:
[runtime](.agent-notes/mrva-runtime.md), [CGA](.agent-notes/cga.md),
[Bench](.agent-notes/bench.md), [preparation](.agent-notes/preparation.md), or
[views](.agent-notes/views.md). Read
[system-test notes](.agent-notes/system-tests.md) before using an e2e driver,
and [environment notes](.agent-notes/environment.md) before host setup.

**Stop:** You have identified the owning operation, state contract, and smallest
relevant check. Read another subsystem only if the evidence crosses that
boundary; retain a usable example alongside implementation changes.

## Structural conventions [Both]

| Convention                                                                                                                            | Where to learn the details                                             |
| ------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Use the top-level `cga` dispatcher for recorded workflows; direct component binaries remain JSON-in/JSON-out filters                  | [Commands and state](cga/README.md#state)                              |
| `.cga/` holds workflow metadata/history and local runtime/scratch; the configured content-addressed store holds objects               | [Workflows](cga/README.md#workflows)                                   |
| Many Python components use `bin/`, a same-name package, and `tests/`; some preparation services use `bin/lib/doc/share` instead       | [CGA layout](cga/README.md#layout), [controller](cga/cgactl/README.md) |
| Server and worker are separate Go modules using the sibling `mrvacommander` shared module; other utilities may have their own modules | [MRVA component map](README.md#mrva-component-map)                     |
| PostgreSQL holds operational state and references, not large database/source/result blobs                                             | [Runtime storage notes](.agent-notes/mrva-runtime.md#storage)          |
| Operator overrides survive defaults; lifecycle ownership and setup/analysis boundaries stay explicit                                  | [Agent core](.agent-notes/README.md#essential-invariants)              |
| Usage documentation stays near examples/components; the book links canonical Markdown through symlinks                                | [Documentation notes](.agent-notes/documentation.md)                   |

## Examples and fixed checks [Both]

Everything here is prototype material. "Starting example" means a useful entry
point today, not production readiness. Keep earlier examples when they offer a
different experimental shape or could be expanded.

**Examples leave room for experimentation. E2e tests are a special case of
examples with fixed inputs and assertions that test the code.** Passing a fixed
check does not by itself demonstrate that a scientific detector is effective.

| Material                                                    | Role                             | What to read it for                                                                                                                                                        |
| ----------------------------------------------------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [mrva-flow](cga/mrva-flow/README.md)                        | Starting example                 | One single-user recorded analysis with visible lifecycle and result exports                                                                                                |
| [Bench](cga/cgabench/README.md)                             | Interactive experiment interface | Session-based query/database variation and explicit comparisons                                                                                                            |
| [query-030](cga/analysis/CVE-2016-9843/query-030/README.md) | Focused worked example           | Explicit preparation, validation, handoff, and analysis across architecture/toolchain inputs                                                                               |
| [sample-05](cga/sample-05/README.md)                        | Earlier example, retained        | Manually stepped two-user selection, status, download, and ingestion                                                                                                       |
| [sample-05-i](cga/sample-05-i/README.md)                    | Earlier example, retained        | The two-user sequence with CGA-owned standalone infrastructure                                                                                                             |
| [CVE examples](cga/examples/cves/README.md)                 | Experimental input collection    | Individual cases, source versions, and associated queries; choose a case rather than reading the catalogue recursively                                                     |
| [run-system-02](cga/system-tests/README.md#sample-workflow)     | Fixed e2e check                  | Standalone server/worker execution and verification                                                                                                                        |
| [run-system-09](cga/system-tests/run-system-09/README.md)       | Fixed e2e check                  | Preparation-to-export handoff with a small controlled finding expectation                                                                                                  |
| [run-system-10](cga/system-tests/run-system-10/README.md)       | Collection-scale e2e check       | Execution over the promoted collection; pair with [effectiveness evidence](cga/analysis/run-system-10-2026-08-24/query-effectiveness/README.md) when interpreting findings |
| [run-system-11](cga/system-tests/run-system-11/README.md)       | Scale observation               | Sysview behavior over 200+ distinct C/C++ databases and multi-user/session workloads; CGA-based phases and endpoint measurements |

## Further reading and maintenance

**[Human]** The [project book](docs/README.md) assembles component and usage
documentation for browsing. [Conceptual notes](notes/README.md) form a separate
book; consult them for a specific idea rather than as required onboarding.
[Installation](INSTALL.md) and [remote access](REMOTE-CONNECTION.md) are
references for running experiments, not prerequisites for understanding them.

**[Both]** Keep this guide a routing layer. Put detailed usage beside the
example, implementation contracts beside the component, and non-obvious
operational constraints in the relevant agent topic. Update these links when an
example or command changes. Remove out-of-date documentation rather than
creating a documentation archive; Git retains earlier versions. Preserve the
examples themselves for further experimentation.

# Introductory guide

Begin with the [CGA overview](docs/cga-overview.html): the appliance, a fixed
Sample 05 worked example, and installation. Use [CGA help](docs/cga-help.html)
for tasks and commands. The outlines below are further usage routes, not
prerequisites for that first example.

This is a navigable outline for simpler usage guides, ready for expansion. The
linked pages contain core commands and brief descriptions, not completed
tutorials. They assume `cga` and the required tools are installed; see
[installation](INSTALL.md) and
[CLI installation](README.md#cga-command-line-interface).

This repository is an experiment/prototype. Work with databases and queries,
inspect what happens, and evolve examples and supporting code together.

## Choose a starting point

| Guide                                                     | Scope                                                                                                                |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| [CGA Bench](guides/introductory/bench.md)                 | One document for starting an experiment, working with sessions, comparing results, and managing its viewer           |
| [CGA shell workflow](guides/introductory/cli-workflow.md) | One document with sections for preparing inputs, applying queries, and inspecting results, including viewer commands |

The Bench outline follows the existing
[Bench documentation](cga/cgabench/README.md) closely. Bench consumes prepared
databases; it does not build them. The shell workflow makes preparation and
analysis separate, explicit activities.

## Sections to develop

- [Bench: start and reconnect](guides/introductory/bench.md#start-an-experiment).
- [Bench: inputs, sessions, and comparison](guides/introductory/bench.md#work-with-inputs-and-sessions).
- [CGA preparation: prepare inputs](guides/introductory/cli-workflow.md#cga-preparation-prepare-inputs).
- [Apply queries](guides/introductory/cli-workflow.md#apply-queries).
- [Result inspection](guides/introductory/cli-workflow.md#result-inspection).
- [Shell-workflow viewers: reconnect and stop](guides/introductory/cli-workflow.md#viewers-reconnect-and-stop).

Each page leaves room for plain-language explanations, a chosen worked example,
and illustrations. Command templates containing `/absolute/path/to/...` need
real inputs before use; they are not run-all scripts.

For deeper navigation and implementation constraints, use the
[advanced reading guide](READING-GUIDE.md). Its human/LLM markers describe
audience, not introductory difficulty.

# Summary

[Repository and implementation reference](overview.md)

- [Introductory guide](introductory-guide.md)
  - [CGA Bench](guides/introductory/bench.md)
  - [Prepare, apply, and inspect](guides/introductory/cli-workflow.md)
- [Advanced reading guide](reading-guide.md)
  - [Single-user MRVA example](cga/mrva-flow/README.md)
  - [Bench experiments](cga/cgabench/README.md)
  - [Writing flow scripts](cga/cgawf/FLOW-SCRIPT-GUIDE.md)
  - [Explicit preparation and analysis example](cga/analysis/CVE-2016-9843/query-030/README.md)
  - [Zlib query investigation](cga/analysis/CVE-2016-9843/README.md)
  - [Collection evidence](cga/analysis/README.md)
  - [Query effectiveness](cga/analysis/run-system-10-2026-08-24/query-effectiveness/README.md)
  - [Controlled handoff e2e](system-tests/run-system-09/README.md)
  - [Collection e2e](system-tests/run-system-10/README.md)
  - [Sysview scale observation](system-tests/run-system-11/README.md)

# Components

- [server-commander](server-commander.md)
- [agent-commander-argo](agent-commander-argo.md)
- [mrvacommander](mrvacommander.md)
- [sysview-view](sysview-view.md)
- [cga](cga.md)
  - [cgasv (system overview)](cgasv.md)
  - [cgadl (DB library)](cgadl.md)
  - [cgaql (query library)](cgaql.md)
  - [cgamr (MRVA requestor)](cgamr.md)
  - [cgamu (MRVA user view)](cgamu.md)
  - [cgasi (SARIF ingestor)](cgasi.md)
  - [cgamx (MRVA infrastructure)](cgamx.md)
- [cga preparation (CodeQL appliance preparation)](cga-prep.md)
  - [C/C++ path-problem CVE catalogue](cga-prep-cves.md)
  - [Build controller](cga/cgactl/README.md)
- [Result export](cga/cgaex/README.md)
- [Unified View](cga/cgauv/README.md)

# Operations

- [Install dependencies](install-dependencies.md)
- [Remote connection](remote-connection.md)
- [System tests / sample workflows](system-tests.md)
- [Interaction via CGA](cga-sample-05.md)
- [Interaction via independent CGA](cga-sample-05-i.md)

# Advanced reading references

- [Agent core](.agent-notes/README.md)
  - [Environment](.agent-notes/environment.md)
  - [CGA integration](.agent-notes/cga.md)
  - [Bench constraints](.agent-notes/bench.md)
  - [Preparation](.agent-notes/preparation.md)
  - [MRVA runtime](.agent-notes/mrva-runtime.md)
  - [System tests](.agent-notes/system-tests.md)
  - [Views and replay](.agent-notes/views.md)
  - [Documentation](.agent-notes/documentation.md)
- [Using the project book](docs/README.md)
- [Conceptual notes index](notes/README.md)

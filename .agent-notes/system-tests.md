# System-test notes

E2e tests are fixed examples: they test implementation behavior with specified
inputs and assertions. Other examples leave experimental choices open. Start
with the [usage/configuration guide](../cga/system-tests/README.md).

## Lifecycle pitfalls

- Canonical standalone check:
  `cd cga/system-tests && CODEQL_JAVA_HOME=/usr ./run-system-02 all`. It exercises
  two users and eight jobs.
- `all` includes `preflight reset`: it reclaims the configured port and drops
  MRVA state before execution. It leaves the server on `:8081` and PostgreSQL
  state available for inspection. Do not run it merely to discover behavior.
- Phases are intentionally decoupled. `preflight` reclaims the port; `start`
  launches. `build start` alone does not remove an old server.
- A stale server can leave you testing the wrong binary. Inspect
  `ss -ltnp | grep :8081` and the owning process; stop only the identified
  process. The system harness preflight uses `lsof`, which must be installed.
- Different scenario scratch paths do not isolate PostgreSQL or shared ports.
  Run only one shared-infrastructure scenario at a time.
- `where` describes phases without mutation; `query` inspects state. `cleanup`
  stops services and removes MRVA runtime state.
- SARIF `ingest-all` is optional in run-system-02, not part of `all`. It needs
  the SARIF ingestor plus SQLite and DuckDB CLIs.
- `cga/system-tests/standalone-multi-agent-lib.sh` owns shared harness plumbing.
  `cga/cgamx` owns the equivalent CGA-facing lifecycle; preserve each public
  phase's responsibility rather than mixing setup into analysis commands.
- Client operations use a recorded CGA workflow at
  `$CGA_TEST_WORKFLOW` (default `$MRVA_WORK_DIR/workflow`). Prepared packs and
  repository lists are explicit submission inputs; database ZIP creation is
  `cga db zip`, not an upload. Scenario 08 retains concurrent HTTP submissions
  and then attaches their sessions to CGA to avoid serializing the race.
- Scenarios 09/10 also use native recorded workflows. Their session JSON files
  are exported snapshots, not filter inputs. Scenario 09 explicitly plans
  three build-mode-none jobs, builds each independently, and verifies a
  catalogue before importing it into analysis.

## Choose a fixed check

| Scenario      | What it fixes and checks                                     |
| ------------- | ------------------------------------------------------------ |
| run-system-02 | Two-user standalone execution                                |
| run-system-03 | Multiple sessions and query packs in one language            |
| run-system-04 | Sessions in multiple languages                               |
| run-system-05 | Named submissions, status, and downloads                     |
| run-system-06 | Idle worker exit and fresh workers for later work            |
| run-system-07 | Two-server leader failover and backup behavior               |
| run-system-08 | Two workload waves, queue restart, and stale-status recovery |
| run-system-09 | Small controlled preparation-to-analysis-to-export handoff   |
| run-system-10 | Execution over eligible promoted collection groups           |
| run-system-11 | Sysview observation over 200+ distinct DBs, scaled by user/session |

Read the chosen driver's usage and local README before running. Collection
checks need the right database/toolchain provenance and adequate memory; CodeQL
RSS can greatly exceed its Java heap. Successful collection execution does not
prove its generic queries detect the target CVEs. Consult the
[effectiveness evidence](../cga/analysis/run-system-10-2026-08-24/query-effectiveness/README.md).

Scenario 11 uses the dispatcher and `cga mx` directly, without sourcing the bash
harness. Its global-catalogue SQL selects one latest snapshot per C/C++
owner/repo; mixed creation versions are recorded, not rejected by equality.
Prepared inputs and observation evidence live outside the reset MRVA directory.
The default root is `<checkout>/.cga-system-11`, including `TMPDIR` for worker
unpacking. Plan for at least 50 GiB free for a fresh run (26 GiB observed
footprint), with more for concurrency/retained runs. Preparation/start check only
16 GiB free headroom on each runtime filesystem, not total capacity.
Retry interrupted preparation with the same root; `cga dl download` verifies
completed ZIPs and resumes hash-addressed HTTP partials where supported.
Its `wait`/`verify` check complete per-repository terminal accounting, explicitly
reporting failed/canceled/timed-out jobs rather than requiring all-success.
MRVA session `succeeded` also covers mixed terminal outcomes. Strict server-log
checking is the separate `check` phase, not an observation-success gate.
It does not implement the proposed limited server mode or browser automation.

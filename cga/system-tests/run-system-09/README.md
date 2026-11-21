# run-system-09

Complete standalone end-to-end test for separate CGA preparation and CGA
analysis:

```text
CGA preparation session: CVE specification
  -> vulnerable / patched / most-recent source variants
  -> explicit database jobs, build-mode-none databases, and verified DB catalogue
  -> generated query source tree
  -> explicit catalogue/query-directory handoff
CGA session:
  -> database and query selection + query pack
  -> MRVA analysis of all three databases
  -> SARIF download and cumulative ingestion
  -> human Markdown and LLM JSON exports
```

The test creates a small local Git repository containing a Debian-packaged C
source tree. Three commits stand in for the Debian `zlib` versions associated
with CVE-2016-9843. The repository is served over localhost Git dumb HTTP, so
source acquisition is real but does not depend on external archives. CodeQL
database creation, MRVA scheduling, analysis, SARIF conversion, and exports are
not mocked.

Preparation and analysis each have a recorded CGA workflow, at
`$CGA_PREP_WORKFLOW` (default `$CGA_SYSTEM09_ROOT/preparation`) and
`$CGA_TEST_WORKFLOW` (default `$CGA_SYSTEM09_ROOT/analysis`). The default
`CGA_SYSTEM09_ROOT` is `/tmp/cga-system-09`. JSON session files are exported
snapshots for assertions and dashboard compatibility, not pipeline inputs.
Database planning creates three immutable jobs; each `cga db build` builds one
variant in build-mode-none, and `cga catalog create/verify` produces the explicit
handoff. Repository identities use the upstream name plus the bundle SHA-256;
the three version labels and `none` mode remain in manifest provenance.

Run from the repository root:

```bash
cga/system-tests/run-system-09/run all
cga/system-tests/run-system-09/run info
cga/system-tests/run-system-09/run cleanup
```

## Viewing progress in the dashboards

CGA preparation and CGA deliberately use different session files and pages. To observe
both, start each launcher against the corresponding system-test session.

Start CGA preparation:

```bash
export CGA_PREP_SESSION=/tmp/cga-system-09/cga-prep-session.json
export CGA_PREP_TMPDIR=/tmp/cga-system-09/cga-prep-st
export CGA_PREP_RUN_DIR=/tmp/cga-system-09/cga-prep-run
cga/cga-prep-run start
```

Open <http://127.0.0.1:8500/>. In another terminal, start CGA execution:

```bash
export CGA_SESSION=/tmp/cga-system-09/cga-session.json
export CGA_TMPDIR=/tmp/cga-system-09/cgast
export CGA_RUN_DIR=/tmp/cga-system-09/cga-run
cga/cga run start
```

Open <http://127.0.0.1:8600/>.

In the second terminal, run the test:

```bash
cga/system-tests/run-system-09/run all
```

The dashboards read their live session files but do not refresh automatically.
Click **reload** to display newly completed stages.

After inspection, stop both the test infrastructure and dashboard:

```bash
CGA_RUN_DIR=/tmp/cga-system-09/cga-run cga/cga run stop
CGA_PREP_RUN_DIR=/tmp/cga-system-09/cga-prep-run cga/cga-prep-run stop
cga/system-tests/run-system-09/run cleanup
```

`all` leaves MRVA and its PostgreSQL state running for inspection. Artifacts
live under `/tmp/cga-system-09/`; MRVA state lives under
`/tmp/mrva-cga-system-09/`.

The expected result is:

```text
1 CVE x 3 variants x 1 query -> 3 findings -> 2 exports
```

As with the other standalone scenarios, run only one MRVA system test at a time
because the default instance uses PostgreSQL and port 8081.

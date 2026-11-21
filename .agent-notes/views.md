# View and replay notes

Start with the owning usage document: [CGA](../cga/README.md#web-view),
[Bench](../cga/cgabench/README.md), [Unified View](../cga/cgauv/README.md), or
[sysview replay](../sysview-view/README.md).

## MRVA sysview

- `mrvacommander/pkg/server/sysview.go` caches snapshots for `/sysview/data`;
  `/sysview` polls them while preserving collapse/scroll state.
  `MRVA_SYSVIEW_REFRESH_SECONDS` overrides refresh timing.
- CSS and renderer JS are shared embedded assets in
  `mrvacommander/pkg/sysviewui/`. Live sysview and `sysview-view` reuse them; do
  not fork renderers for replay.
- Live rendering consumes `renderSteps` in short batches so Pause can interrupt
  large DOM builds; replay drains the same steps synchronously via `render`.
  Pause cancels queued polling, the active fetch, and unfinished rendering.
  Stale cycles must neither paint nor schedule another poll after resume.
  Browser regression: `cd mrvacommander && go test ./pkg/server -run TestSysViewPauseInBrowser`.
- Go composes HTML using raw strings: do not introduce unescaped backticks.
  Rebuild and restart the server after embedded view changes, then reload.
- Job rows retain pack identity derived from submitted bytes and report progress
  independently from worker state. Preserve provenance when changing grouping or
  summaries.
- `--dbg-dump-sysview` writes JSONL; `MRVA_SYSVIEW_DUMP_PATH` selects its path.
  The harness enables it explicitly with `MRVA_DBG_DUMP_SYSVIEW=1`.
- `sysview-view` reads retained dumps and can export self-contained HTML. In the
  harness, stop retains state/dump; cleanup removes runtime state/dump.

## CGA views

- `cga serve start|status|stop` (`cgalib/viewers.py`) aggregates existing
  configured viewer state, reports missing profiles as SKIP, and owns only
  processes it launches. Never seed state or start MRVA/assistants implicitly.
  Dashboard JS configuration stays runtime-local per profile. Direct launchers
  retain their explicit seed/development behavior; do not mix port owners.
- `cga gateway start|status|stop` owns an independent loopback gateway on 8599.
  `cga/cgagateway/` owns HTTP/WebSocket routing; `cgalib/gateway.py` owns
  lifecycle. `/documentation/` serves live checkout documents and web assets
  under the same origin, including optional built books. Preserve
  repository-relative links, no-cache reads, read-only methods, and the
  runtime/checkout path boundary. No separate documentation process, workspace,
  or port is needed. Preserve mount-relative browser URLs and the direct-port
  development views. Editor routes discover already-running sessions through
  Bench `/api/editors`; discovery must not start editors or return login
  passwords.
- `cga view` captures dashboard fragments and can export a self-contained
  replay. The mrva-flow example records replay and graph exports under
  `.cga/tmp/`; `CGA_DASHBOARD_DUMP`, `CGA_CFG_EXPORT`, and `CGA_DFG_EXPORT`
  control the relevant outputs.
- The live composite dashboard is a snapshot, not a periodic replacement of
  editable detail fragments. Refreshing must not silently discard form input.
- `cga/cga-view/cgaview/static_server.py` serves loopback-only/no-cache assets;
  do not replace it with a generic HTTP server.
- Unified View is a read-only normalized workflow projection with a server-side
  sysview proxy. Outline/search omit secret-tagged entities by default.
- Dashboard/replay share light/dark preferences; Unified View has additional
  themes. Keep theme changes presentation-only and preserve shared state. Bench
  has its own Apple/Classic presentation contract; see [Bench notes](bench.md).

# cgasv — CodeQL generic appliance: system overview

`cgasv` is the **system-overview** provider for the cga composite page. It is a
Go program that serves the page **header** fragment (`/header`) — the banner
strip at the top of the composite layout — with the appliance title and the
server clock.

It grows from `sysview` / `pkg/sysviewui`. For now it serves the header,
including a live view of the active CGAST pipeline read from the session; richer
system state is deferred.

## Command

```sh
cgasv serve     # serve the /header fragment
```

`cgasv` only serves (it has no CLI state of its own), but as part of the
[CGAST protocol](../README.md#state) its header reads the session CGAST
(`cga-tmp/session.json`, override with `CGA_SESSION`) live on every request and
shows which cga* components are active in the current pipeline.

## Serve contract

`cgasv serve` starts an HTTP server (default port `8601`, override with
`CGA_CGASV_PORT`) exposing:

- `/header` — the composite page's header fragment.
- `/healthz` — readiness probe used by `cga run`.
- `/` — a small JSON index of the available routes.

All responses carry `Access-Control-Allow-Origin: *` so the composite page can
fetch them cross-port. Fragments share the standard cga envelope (`.cga-frag` /
`.cga-frag-title` / `.cga-frag-body`).

## Layout

Following the cga convention, the compiled binary lives under `bin/`:

```
cgasv/
  main.go          package main (fragment server)
  go.mod
  Makefile         `make` -> go build -o bin/cgasv
  bin/cgasv        compiled binary (gitignored; built by cga-run/Makefile)
```

Build with `make` (or `cga run build`); run via `cga run start`.

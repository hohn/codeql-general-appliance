# cgamu — CodeQL generic appliance: MRVA user view

`cgamu` is the **MRVA user-view** provider for the cga composite page. It is a
Go program that serves the `/overview` and `/detail` fragments summarising MRVA
sessions (session, user, job count, state).

It is a compact subset of the MRVA `sysview`. Rows come directly from the live
[`cgamr`](../cgamr/README.md) named submissions in the session CGAST. Before a
submission exists the detail is empty; it never predicts or invents sessions.

## Command

```sh
cgamu serve     # serve the /overview and /detail fragments
```

`cgamu` only serves (it has no CLI state of its own), but as part of the
[CGAST protocol](../README.md#state) it reads the session CGAST
(`cga-tmp/session.json`, override with `CGA_SESSION`) live on every request and
reflects every entry in `cgamr-submissions`. A row's job count is the number of
repositories in that submission, and API states such as `in_progress` are
displayed as `in-progress`.

## Serve contract

`cgamu serve` starts an HTTP server (default port `8605`, override with
`CGA_CGAMU_PORT`) exposing:

- `/overview` — session/user summary fragment.
- `/detail` — per-session detail table.
- `/healthz` — readiness probe used by `cga run`.
- `/` — a small JSON index of the available routes.

All responses carry `Access-Control-Allow-Origin: *`; fragments share the
standard cga envelope so Go and Python components render uniformly.

## Layout

Following the cga convention, the compiled binary lives under `bin/`:

```
cgamu/
  main.go          package main (fragment server)
  go.mod
  Makefile         `make` -> go build -o bin/cgamu
  bin/cgamu        compiled binary (gitignored; built by cga-run/Makefile)
```

Build with `make` (or `cga run build`); run via `cga run start`.

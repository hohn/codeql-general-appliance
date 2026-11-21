# sysview-view

Offline replay tool for the MRVA **sysview** system-state dashboard.

The server, when started with `--dbg-dump-sysview`, appends one JSON snapshot of
the sysview per refresh interval to a dump file (JSONL). `sysview-view` reads
that dump and serves a web page that renders the **exact same** sysview UI as
the live dashboard, driven by a vertical discrete index slider so you can scrub
through the captured system state over time.

The rendering (CSS + JS) is shared with the live dashboard via
`github.com/hohn/mrvacommander/pkg/sysviewui`, so the two stay identical.

On the live `/sysview` page, **Pause** cancels the active download or unfinished
render and changes to **Resume**, retaining the displayed state for inspection.
Large job/worker views are built in short batches so the control remains
responsive during construction. Resume fetches fresh state; canceled refreshes
cannot repaint later. Replay uses the same renderer without live polling.

## Capture a dump

Start the server with the debug flag:

```sh
mrvaserver --mode=standalone --dbg-dump-sysview
```

The dump path defaults to `sysview-dump` in the server's working directory.
Override it with `MRVA_SYSVIEW_DUMP_PATH`.

In the `cga/system-tests/run-system-02` harness the dump is opt-in:

```sh
MRVA_DBG_DUMP_SYSVIEW=1 MRVA_SYSVIEW_DUMP_PATH=/tmp/sysview-dump ./run-system-02 all
```

`all` leaves the server running (and dumping); `./run-system-02 stop` halts it
while keeping state, and `./run-system-02 cleanup` also deletes the dump file.

## Replay

```sh
go build ./...
./sysview-view --dump /path/to/sysview-dump --addr :8090
```

Then open <http://127.0.0.1:8090/>. Drag the vertical slider, use the mouse
wheel over it, or press the Up/Down (or Left/Right) arrow keys to scrub;
Home/End jump to the first/last snapshot; **Reload** re-reads the dump file
(safe to use while the server is still appending).

Endpoints:

- `GET /` — the replay UI.
- `GET /snapshots` — the dump as a JSON array (blank and partially-written lines
  are skipped).

## Self-contained export (no server)

To view a captured run with **no running process at all** — no `mrvaserver`, no
`sysview-view` — export the dump to a single standalone HTML file with the
snapshots baked in, then open it directly with `file://`:

```sh
./sysview-view --dump /path/to/sysview-dump --export replay.html
xdg-open replay.html    # or: chromium-browser replay.html
```

The exported file is fully self-contained (CSS, JS and all snapshot data
embedded; no external references), so it is easy to archive or share. The same
slider / wheel / keyboard controls work offline; **Reload** simply re-reads the
embedded data.

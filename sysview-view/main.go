// Command sysview-view is an offline replay tool for the MRVA sysview.
//
// The server, when started with --dbg-dump-sysview, appends one JSON snapshot
// per refresh interval to a dump file (sysview-dump, JSONL). sysview-view reads
// that file and serves a web page that renders the exact same sysview UI as the
// live dashboard, driven by a vertical discrete index slider so you can scrub
// through the captured system state over time.
//
// Usage:
//
//	sysview-view [--dump sysview-dump] [--addr :8090]
//	sysview-view --dump sysview-dump --export replay.html   # self-contained
//
// With --export, the dump is baked into a single standalone HTML file that
// renders with no server at all (open it directly via file://).
//
// The rendering (CSS + JS) is shared with the live dashboard via
// github.com/hohn/mrvacommander/pkg/sysviewui, so the two stay identical.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"log"
	"log/slog"
	"net/http"
	"os"
	"strings"

	"github.com/hohn/mrvacommander/pkg/sysviewui"
)

func main() {
	dumpPath := flag.String("dump", "sysview-dump", "Path to the sysview dump file (JSONL) written by the server's --dbg-dump-sysview.")
	addr := flag.String("addr", ":8090", "Address to serve the replay UI on.")
	export := flag.String("export", "", "If set, write a self-contained standalone HTML file (dump data embedded) to this path and exit; no server is started. Open it directly with file://.")
	flag.Parse()

	// Export mode: bake the dump into a single HTML file that needs no server.
	if *export != "" {
		arr, n, err := readSnapshotsJSON(*dumpPath)
		if err != nil {
			log.Fatalf("sysview-view: cannot read dump %q: %v", *dumpPath, err)
		}
		if err := os.WriteFile(*export, []byte(buildStaticPage(arr)), 0644); err != nil {
			log.Fatalf("sysview-view: cannot write %q: %v", *export, err)
		}
		slog.Info("sysview-view exported standalone HTML (open with file://)",
			"out", *export, "dump", *dumpPath, "snapshots", n)
		return
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		_, _ = w.Write([]byte(page))
	})
	mux.HandleFunc("/snapshots", snapshotsHandler(*dumpPath))

	slog.Info("sysview-view serving", "addr", *addr, "dump", *dumpPath,
		"url", "http://127.0.0.1"+*addr+"/")
	if err := http.ListenAndServe(*addr, mux); err != nil {
		log.Fatalf("sysview-view: %v", err)
	}
}

// snapshotsHandler serves the dump file contents as a JSON array of snapshots.
// The file is (re-)read on every request so the "Reload" button picks up new
// appends while the server keeps dumping.
func snapshotsHandler(dumpPath string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")

		arr, _, err := readSnapshotsJSON(dumpPath)
		if err != nil {
			if os.IsNotExist(err) {
				_, _ = w.Write([]byte("[]"))
				return
			}
			slog.Error("sysview-view: read dump failed", "path", dumpPath, "error", err)
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		_, _ = w.Write(arr)
	}
}

// readSnapshotsJSON reads the JSONL dump and returns it as a JSON array of
// snapshots plus the snapshot count. Blank and partially-written lines (e.g. a
// final line the server is mid-append on) are skipped, so it is safe to read
// while the server is still dumping.
func readSnapshotsJSON(dumpPath string) ([]byte, int, error) {
	data, err := os.ReadFile(dumpPath)
	if err != nil {
		return nil, 0, err
	}
	var buf bytes.Buffer
	buf.WriteByte('[')
	n := 0
	for _, line := range bytes.Split(data, []byte("\n")) {
		line = bytes.TrimSpace(line)
		if len(line) == 0 || !json.Valid(line) {
			continue
		}
		if n > 0 {
			buf.WriteByte(',')
		}
		buf.Write(line)
		n++
	}
	buf.WriteByte(']')
	return buf.Bytes(), n, nil
}

// buildStaticPage returns a fully self-contained HTML document with the dump's
// snapshots embedded inline, so it renders with no server at all (open via
// file://). It reuses the exact same markup/CSS/JS as the served page; the
// driver prefers window.SNAPS_EMBEDDED over fetching /snapshots. The "<" bytes
// in the JSON are escaped to \u003c so the data can never break out of the
// <script> element (JSON keeps them only inside string values).
func buildStaticPage(snapshotsJSON []byte) string {
	safe := strings.ReplaceAll(string(snapshotsJSON), "<", `\u003c`)
	var b strings.Builder
	b.WriteString(pageHead)
	b.WriteString(sysviewui.Style)
	b.WriteString(viewerStyle)
	b.WriteString(pageBody)
	b.WriteString("<script>window.SNAPS_EMBEDDED = ")
	b.WriteString(safe)
	b.WriteString(";</script>\n")
	b.WriteString(scriptOpen)
	b.WriteString(sysviewui.RenderJS)
	b.WriteString(viewerDriver)
	b.WriteString(pageTail)
	return b.String()
}

// page is the served replay UI (fetches /snapshots). It reuses the shared
// sysview Style + RenderJS so the rendered view is identical to the live
// dashboard, and adds the vertical index slider driver. The self-contained
// export (buildStaticPage) reuses the same parts with data embedded instead.
// NOTE: no backticks may appear in the raw strings below.
var page = pageHead + sysviewui.Style + viewerStyle + pageBody +
	scriptOpen + sysviewui.RenderJS + viewerDriver + pageTail

const scriptOpen = "<script>\n"

const pageHead = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MRVA sysview - replay</title>
`

const viewerStyle = `<style>
  .replay-wrap { display:flex; align-items:flex-start; gap:18px; }
  .slider-col { position:sticky; top:12px; flex:0 0 auto; display:flex;
    flex-direction:column; align-items:center; gap:10px; border:1px solid var(--line);
    border-radius:8px; padding:14px 12px; background:#f6f8fa; }
  .slider-col input[type=range] { writing-mode:vertical-lr; direction:ltr;
    width:26px; height:60vh; cursor:pointer; touch-action:none; accent-color:var(--c-running); }
  .slider-label { font-weight:600; font-size:13px; white-space:nowrap; }
  .slider-time { color:var(--muted); font-size:11px; text-align:center; white-space:nowrap; }
  .view-col { flex:1 1 auto; min-width:0; }
  #reloadBtn { flex:none; cursor:pointer; font:600 13px/1 inherit; color:#fff;
    background:var(--c-running); border:1px solid rgba(0,0,0,.12); border-radius:6px; padding:8px 16px; }
  #reloadBtn:hover { filter:brightness(1.06); }
</style>
`

const pageBody = `</head>
<body>
  <div class="topbar">
    <div>
      <h1>MRVA sysview &mdash; replay</h1>
      <p class="sub">Offline replay of the sysview dump: drag the vertical slider, use the mouse wheel over it, or press Up/Down (Home/End) to scrub captured snapshots.</p>
    </div>
    <button id="reloadBtn" type="button" title="Re-read the dump file">Reload</button>
  </div>
  <div class="replay-wrap">
    <div class="slider-col">
      <div class="slider-label" id="idxLabel">0 / 0</div>
      <input id="idx" type="range" min="0" max="0" step="1" value="0" />
      <div class="slider-time" id="idxTime">&mdash;</div>
    </div>
    <div class="view-col">
      <div id="meta">loading&hellip;</div>
      <h2>Servers</h2>
      <div id="servers" class="servers-status"></div>
      <h2>Users, sessions &amp; jobs</h2>
      <div id="jobs"></div>
      <h2>Worker pool</h2>
      <div class="legend">
        <span class="item"><span class="swatch sw-starting"></span>starting</span>
        <span class="item"><span class="swatch sw-idle"></span>idle</span>
        <span class="item"><span class="swatch sw-running"></span>running</span>
        <span class="item"><span class="swatch sw-stopping"></span>stopping</span>
        <span class="item"><span class="swatch sw-down"></span>down (presumed/exited)</span>
        <span class="item"><span class="swatch sw-exited"></span>exited</span>
      </div>
      <div id="workers" class="grid"></div>
    </div>
  </div>
`

// viewerDriver drives the shared render(data) from an in-memory array of
// snapshots selected by the vertical slider. It replaces the live dashboard's
// polling loop. NOTE: no backticks.
const viewerDriver = `
var SNAPS = [];
var cur = 0;
var idxEl = document.getElementById("idx");
var idxLabel = document.getElementById("idxLabel");
var idxTime = document.getElementById("idxTime");

function show(i) {
  if (!SNAPS.length) {
    render({ jobs: [], workers: [], spawns: [], generated_at: "\u2014", refresh_ms: 0 });
    idxLabel.textContent = "0 / 0";
    idxTime.textContent = "\u2014";
    return;
  }
  if (i < 0) i = 0;
  if (i > SNAPS.length - 1) i = SNAPS.length - 1;
  cur = i;
  idxEl.value = String(i);
  idxLabel.textContent = (i + 1) + " / " + SNAPS.length;
  var s = SNAPS[i] || {};
  idxTime.textContent = s.generated_at ? s.generated_at : "\u2014";
  render(s);
}

function load() {
  // Self-contained export path: data is baked into the page, no server needed.
  if (Array.isArray(window.SNAPS_EMBEDDED)) {
    SNAPS = window.SNAPS_EMBEDDED;
    idxEl.min = "0";
    idxEl.max = String(Math.max(0, SNAPS.length - 1));
    if (cur > SNAPS.length - 1) cur = SNAPS.length - 1;
    if (cur < 0) cur = 0;
    show(cur);
    return;
  }
  fetch("snapshots", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (arr) {
      SNAPS = Array.isArray(arr) ? arr : [];
      idxEl.min = "0";
      idxEl.max = String(Math.max(0, SNAPS.length - 1));
      if (cur > SNAPS.length - 1) cur = SNAPS.length - 1;
      if (cur < 0) cur = 0;
      show(cur);
    })
    .catch(function (err) {
      document.getElementById("meta").textContent = "load error: " + err;
    });
}

function step(delta) { show(cur + delta); }

// A single "input" listener keeps the model in sync with native drag/click on
// the range. "change" is a backstop for browsers that only emit it on release.
function onSlider() { show(parseInt(idxEl.value, 10) || 0); }
idxEl.addEventListener("input", onSlider);
idxEl.addEventListener("change", onSlider);

document.getElementById("reloadBtn").addEventListener("click", load);

// Keyboard: handle globally and always preventDefault so the behaviour is the
// same whether or not the range has focus. Calling preventDefault here also
// cancels the native range key handling, so there is never a double/opposite
// step (the source of the earlier inconsistent-scroll behaviour).
document.addEventListener("keydown", function (e) {
  var t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA") && t !== idxEl) return;
  switch (e.key) {
    case "ArrowUp": case "ArrowLeft": case "PageUp": step(-1); e.preventDefault(); break;
    case "ArrowDown": case "ArrowRight": case "PageDown": step(1); e.preventDefault(); break;
    case "Home": show(0); e.preventDefault(); break;
    case "End": show(SNAPS.length - 1); e.preventDefault(); break;
  }
});

// Mouse wheel over the slider column is a reliable alternative to dragging the
// (CSS-vertical) range thumb, which some browsers map inconsistently.
var sliderCol = document.querySelector(".slider-col");
if (sliderCol) {
  sliderCol.addEventListener("wheel", function (e) {
    step(e.deltaY > 0 ? 1 : -1);
    e.preventDefault();
  }, { passive: false });
}

load();
`

const pageTail = `</script>
</body>
</html>`

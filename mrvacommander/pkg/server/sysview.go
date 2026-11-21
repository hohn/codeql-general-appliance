package server

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"sync/atomic"
	"time"

	"github.com/hohn/mrvacommander/pkg/pool"
	"github.com/hohn/mrvacommander/pkg/state"
	"github.com/hohn/mrvacommander/pkg/sysviewui"
)

// SysViewConfig controls the /sysview system-state dashboard.
type SysViewConfig struct {
	// RefreshInterval is how often the background goroutine rebuilds the
	// snapshot; the page polls at the same rate.
	RefreshInterval time.Duration
	// RequireAuth registers /sysview behind the auth middleware (production)
	// rather than on the open router (standalone).
	RequireAuth bool
	// DumpEnabled turns on the debug snapshot dump: at every RefreshInterval
	// the current sysview JSON is appended (as one JSONL line) to DumpPath, so
	// the run can be inspected/replayed later with the sysview-view tool.
	DumpEnabled bool
	// DumpPath is the JSONL dump file (default "sysview-dump").
	DumpPath string
}

const sysViewRefreshEnv = "MRVA_SYSVIEW_REFRESH_SECONDS"

const (
	sysViewDumpPathEnv     = "MRVA_SYSVIEW_DUMP_PATH"
	sysViewDefaultDumpPath = "sysview-dump"
)

// NewSysViewConfig resolves the sysview config. The default refresh interval is
// mode-specific (the caller passes 0.5s for standalone, 5s for production);
// MRVA_SYSVIEW_REFRESH_SECONDS (a float, e.g. "0.5" or "2") overrides it.
// dumpEnabled turns on the debug snapshot dump; its path defaults to
// "sysview-dump" and is overridable via MRVA_SYSVIEW_DUMP_PATH.
func NewSysViewConfig(defaultRefresh time.Duration, requireAuth, dumpEnabled bool) SysViewConfig {
	interval := defaultRefresh
	if v := os.Getenv(sysViewRefreshEnv); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil && f > 0 {
			interval = time.Duration(f * float64(time.Second))
		} else {
			slog.Warn("Invalid "+sysViewRefreshEnv+", using default",
				"value", v, "default", defaultRefresh)
		}
	}
	dumpPath := sysViewDefaultDumpPath
	if v := os.Getenv(sysViewDumpPathEnv); v != "" {
		dumpPath = v
	}
	return SysViewConfig{
		RefreshInterval: interval,
		RequireAuth:     requireAuth,
		DumpEnabled:     dumpEnabled,
		DumpPath:        dumpPath,
	}
}

// sysViewSpawn is a pending_spawns row with its age computed for display.
type sysViewSpawn struct {
	WorkflowUID  string `json:"workflow_uid"`
	LanguageHint string `json:"language_hint"`
	AgeS         int    `json:"age_s"`
}

// sysViewSnapshot is the JSON payload served at /sysview/data.
type sysViewSnapshot struct {
	RefreshMs        int64                 `json:"refresh_ms"`
	HeartbeatExpiryS int                   `json:"heartbeat_expiry_s"`
	GeneratedAt      string                `json:"generated_at"`
	ServedBy         string                `json:"served_by"`
	Servers          []state.SysViewServer `json:"servers"`
	Jobs             []state.SysViewJob    `json:"jobs"`
	Workers          []state.SysViewWorker `json:"workers"`
	Spawns           []sysViewSpawn        `json:"spawns"`
	Error            string                `json:"error,omitempty"`
}

// sysView owns the background snapshot goroutine and serves the dashboard.
type sysView struct {
	st               state.ServerState
	poolManager      *pool.PoolManager
	cfg              SysViewConfig
	heartbeatExpiryS int
	cached           atomic.Pointer[[]byte]
	dump             *os.File // debug snapshot dump (JSONL), nil when disabled
}

// startSysView builds an initial snapshot and launches the refresh goroutine.
func startSysView(st state.ServerState, poolManager *pool.PoolManager, cfg SysViewConfig) *sysView {
	if cfg.RefreshInterval <= 0 {
		cfg.RefreshInterval = 5 * time.Second // guard: NewTicker(0) panics
	}
	sv := &sysView{
		st:               st,
		poolManager:      poolManager,
		cfg:              cfg,
		heartbeatExpiryS: heartbeatExpirySeconds(),
	}
	if cfg.DumpEnabled {
		f, err := os.OpenFile(cfg.DumpPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
		if err != nil {
			slog.Error("sysview: cannot open dump file; dump disabled",
				"path", cfg.DumpPath, "error", err)
		} else {
			sv.dump = f
			slog.Info("sysview dump enabled", "path", cfg.DumpPath,
				"interval", cfg.RefreshInterval)
		}
	}
	sv.rebuild() // seed so the first request has data
	go sv.loop()
	slog.Info("sysview started", "endpoint", "/sysview",
		"refresh", cfg.RefreshInterval, "require_auth", cfg.RequireAuth,
		"dump", sv.dump != nil)
	return sv
}

func heartbeatExpirySeconds() int {
	if v := os.Getenv("MRVA_POOL_HEARTBEAT_EXPIRY_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return 120
}

func (sv *sysView) loop() {
	t := time.NewTicker(sv.cfg.RefreshInterval)
	defer t.Stop()
	for range t.C {
		sv.rebuild()
	}
}

// rebuild queries the current system state and caches it as JSON.
func (sv *sysView) rebuild() {
	snap := sysViewSnapshot{
		RefreshMs:        sv.cfg.RefreshInterval.Milliseconds(),
		HeartbeatExpiryS: sv.heartbeatExpiryS,
		GeneratedAt:      time.Now().Format("15:04:05"),
	}
	if sv.poolManager != nil {
		snap.ServedBy = sv.poolManager.Status().InstanceID
		if servers, err := sv.st.SysViewServers(sv.poolManager.ServerStaleAfter()); err != nil {
			snap.Error = err.Error()
		} else {
			snap.Servers = servers
		}
	}
	if jobs, err := sv.st.SysViewJobs(); err != nil {
		snap.Error = err.Error()
	} else {
		snap.Jobs = jobs
	}
	if workers, err := sv.st.SysViewWorkers(); err != nil {
		snap.Error = err.Error()
	} else {
		snap.Workers = workers
	}
	if spawns, err := sv.st.GetPendingSpawns(); err != nil {
		snap.Error = err.Error()
	} else {
		now := time.Now()
		for _, ps := range spawns {
			snap.Spawns = append(snap.Spawns, sysViewSpawn{
				WorkflowUID:  ps.WorkflowUID,
				LanguageHint: ps.LanguageHint,
				AgeS:         int(now.Sub(ps.SpawnedAt).Seconds()),
			})
		}
	}
	b, err := json.Marshal(snap)
	if err != nil {
		slog.Error("sysview: marshal failed", "error", err)
		return
	}
	sv.cached.Store(&b)

	// Debug dump: append this snapshot as one JSONL line. rebuild() is only
	// ever called serially (seed then the single loop goroutine), so the
	// append needs no locking.
	if sv.dump != nil {
		line := append(append([]byte{}, b...), '\n')
		if _, err := sv.dump.Write(line); err != nil {
			slog.Error("sysview: dump append failed", "path", sv.cfg.DumpPath, "error", err)
		}
	}
}

func (sv *sysView) handleData(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	if p := sv.cached.Load(); p != nil {
		_, _ = w.Write(*p)
		return
	}
	_, _ = w.Write([]byte(`{"error":"snapshot not ready"}`))
}

func (sv *sysView) handlePage(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = w.Write([]byte(sysViewHTML))
}

// The live dashboard page is composed from the shared sysviewui assets
// (Style + RenderJS, also used by the offline sysview-view replay tool) plus
// the live-only polling/pause driver below. It polls /sysview/data at the
// server-configured rate and re-renders in place, preserving collapse state.
// NOTE: no backticks may appear in any of these raw string literals.
const sysViewHead = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MRVA sysview</title>
`

const sysViewBody = `</head>
<body>
  <div class="topbar">
    <div>
      <h1>MRVA sysview</h1>
      <p class="sub">Live system state: users &rsaquo; sessions &rsaquo; jobs (top) and the worker pool (bottom).</p>
    </div>
    <button id="pauseBtn" type="button" title="Pause auto-refresh to inspect the current state">Pause</button>
  </div>
  <div id="meta">connecting&hellip;</div>
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

<script>
`

// sysViewLiveDriver is the live-only refresh loop and Pause/Resume control.
const sysViewLiveDriver = `
var refreshMs = 500;
var paused = false;
var pending = null; // outstanding setTimeout id, so pausing cancels it
var activeRefresh = null;

function scheduleNext() {
  if (paused) return;
  pending = setTimeout(tick, refreshMs);
}

function yieldToControls() {
  return new Promise(function (resolve) { setTimeout(resolve, 0); });
}

async function tick() {
  pending = null;
  if (paused) return; // guard against a race with the pause toggle
  var refresh = new AbortController();
  activeRefresh = refresh;
  try {
    var response = await fetch("/sysview/data", {
      credentials: "same-origin", cache: "no-store", signal: refresh.signal
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    var data = await response.json();
    await yieldToControls();
    if (paused || refresh.signal.aborted) return;
    if (typeof data.refresh_ms === "number" && data.refresh_ms > 0) refreshMs = data.refresh_ms;
    var steps = renderSteps(data);
    var deadline = performance.now() + 8;
    while (!steps.next().done) {
      if (performance.now() >= deadline) {
        await yieldToControls();
        if (paused || refresh.signal.aborted) return;
        deadline = performance.now() + 8;
      }
    }
  } catch (err) {
    if (!refresh.signal.aborted && activeRefresh === refresh) {
      document.getElementById("meta").textContent = "fetch error: " + err;
    }
  } finally {
    if (activeRefresh === refresh) {
      activeRefresh = null;
      scheduleNext();
    }
  }
}

// Pause/resume: pausing stops the refresh cycle so the page freezes for
// inspection. All elements stay interactive (collapse, scroll, hover details)
// because no re-render occurs while paused. Cancel both downloads and unfinished
// render batches; a resumed cycle must not inherit work from the canceled cycle.
(function () {
  var btn = document.getElementById("pauseBtn");
  btn.addEventListener("click", function () {
    paused = !paused;
    btn.textContent = paused ? "Resume" : "Pause";
    btn.title = paused ? "Resume auto-refresh" : "Pause auto-refresh to inspect the current state";
    btn.classList.toggle("paused", paused);
    if (paused) {
      if (pending) { clearTimeout(pending); pending = null; }
      if (activeRefresh) {
        var refresh = activeRefresh;
        activeRefresh = null;
        refresh.abort();
      }
      var meta = document.getElementById("meta");
      if (!meta.querySelector(".paused-tag")) {
        var tag = document.createElement("span");
        tag.className = "paused-tag";
        tag.textContent = "  \u00b7  paused";
        meta.appendChild(tag);
      }
    } else {
      tick(); // resume immediately, then keep scheduling
    }
  });
})();

tick();
`

const sysViewTail = "</script>\n</body>\n</html>"

var sysViewHTML = sysViewHead + sysviewui.Style + sysViewBody +
	sysviewui.RenderJS + sysViewLiveDriver + sysViewTail

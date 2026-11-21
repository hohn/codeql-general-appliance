"""Capture rendered CGA fragments and export a self-contained replay page."""

from __future__ import annotations

import argparse
import fcntl
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cgalib"))

from command_help import enhance_parser

COMPONENT_ROUTES = {
    "cgasv": ("header",),
    "cgadl": ("overview", "detail"),
    "cgaql": ("overview", "detail"),
    "cgamr": ("overview", "detail"),
    "cgamu": ("overview", "detail"),
    "cgasi": ("overview", "detail"),
    "cgaex": ("overview", "detail"),
}

PORT_ENV = {
    "cgasv": ("CGA_CGASV_PORT", 8601),
    "cgadl": ("CGA_CGADL_PORT", 8602),
    "cgaql": ("CGA_CGAQL_PORT", 8603),
    "cgamr": ("CGA_CGAMR_PORT", 8604),
    "cgamu": ("CGA_CGAMU_PORT", 8605),
    "cgasi": ("CGA_CGASI_PORT", 8606),
    "cgaex": ("CGA_CGAEX_PORT", 8608),
}


def _cga_root() -> Path:
    configured = os.environ.get("CGA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _fragment_urls() -> dict[str, str]:
    urls: dict[str, str] = {}
    for component, routes in COMPONENT_ROUTES.items():
        env_name, default_port = PORT_ENV[component]
        port = os.environ.get(env_name, str(default_port))
        for route in routes:
            urls[f"{component}/{route}"] = (
                f"http://127.0.0.1:{port}/{route}"
            )
    return urls


def _fetch_fragment(url: str, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-store"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def capture_snapshot(label: str, timeout: float) -> dict[str, Any]:
    """Fetch every dashboard route as one all-or-nothing snapshot."""
    urls = _fragment_urls()
    fragments: dict[str, str] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        futures = {
            executor.submit(_fetch_fragment, url, timeout): (key, url)
            for key, url in urls.items()
        }
        for future in as_completed(futures):
            key, url = futures[future]
            try:
                fragments[key] = future.result()
            except (
                OSError,
                TimeoutError,
                UnicodeError,
                ValueError,
                http.client.HTTPException,
                urllib.error.URLError,
            ) as exc:
                failures.append(f"{url}: {exc}")
    if failures:
        raise RuntimeError(
            "dashboard capture failed:\n  " + "\n  ".join(sorted(failures))
        )
    return {
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": label,
        "fragments": {key: fragments[key] for key in sorted(fragments)},
    }


def append_snapshot(dump_path: Path, snapshot: dict[str, Any]) -> None:
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(snapshot, ensure_ascii=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    with dump_path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0, os.SEEK_END)
        if stream.tell() > 0:
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b"\n":
                stream.seek(0, os.SEEK_END)
                stream.write(b"\n")
        stream.write(line)
        stream.flush()
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def read_snapshots(dump_path: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    with dump_path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(value, dict)
                and isinstance(value.get("fragments"), dict)
            ):
                snapshots.append(value)
    return snapshots


REPLAY_STYLE = """
<style>
  .cga-replay-wrap {
    display: flex;
    align-items: flex-start;
    gap: 14px;
  }
  .cga-replay-controls {
    position: sticky;
    top: 12px;
    flex: 0 0 178px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    min-height: calc(100vh - 24px);
    padding: 12px 10px;
    background: var(--cga-panel);
    border: 1px solid var(--cga-line);
    border-radius: 6px;
  }
  #cga-progress {
    writing-mode: vertical-lr;
    direction: ltr;
    width: 28px;
    height: 62vh;
    cursor: pointer;
    touch-action: none;
    accent-color: var(--cga-accent);
  }
  .cga-replay-count {
    color: var(--cga-accent);
    font-weight: 700;
  }
  .cga-replay-time,
  .cga-replay-label {
    width: 100%;
    color: var(--cga-dim);
    font-size: 11px;
    overflow-wrap: anywhere;
    text-align: center;
  }
  .cga-replay-label {
    color: var(--cga-fg);
  }
  .cga-replay-dashboard {
    flex: 1 1 auto;
    min-width: 0;
  }
  @media (max-width: 760px) {
    .cga-replay-controls {
      flex-basis: 118px;
    }
  }
</style>
"""

REPLAY_CONTROLS = """
<aside class="cga-replay-controls">
  <div class="cga-replay-count" id="cga-progress-count">0 / 0</div>
  <input id="cga-progress" type="range" min="0" max="0" step="1" value="0"
    aria-label="Captured dashboard progress" />
  <div class="cga-replay-time" id="cga-progress-time">&mdash;</div>
  <div class="cga-replay-label" id="cga-progress-label">&mdash;</div>
</aside>
"""

REPLAY_DRIVER = r"""
<script>
"use strict";

const SNAPSHOTS = window.CGA_DASHBOARD_SNAPSHOTS || [];
const OVERVIEWS = [
  "cgadl", "cgaql", "cgamr", "cgamu", "cgasi", "cgaex"
];
let current = 0;
let selectedDetail = "cgamu";

const progress = document.getElementById("cga-progress");
const count = document.getElementById("cga-progress-count");
const time = document.getElementById("cga-progress-time");
const label = document.getElementById("cga-progress-label");
const detail = document.getElementById("cga-detail");
const THEME_STORAGE_KEY = "cga.theme";

function setTheme(theme, persist) {
  const value = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = value;
  const button = document.getElementById("cga-theme-toggle");
  const next = value === "dark" ? "light" : "dark";
  button.textContent = next + " theme";
  button.setAttribute("aria-label", "switch to " + next + " theme");
  button.title = "switch to " + next + " theme";
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, value);
    } catch (_error) {
      // The visual choice still applies when storage is disabled.
    }
  }
}

let storedTheme = "dark";
try {
  storedTheme = localStorage.getItem(THEME_STORAGE_KEY) || "dark";
} catch (_error) {
  // Storage can be disabled; the explicit dark default remains usable.
}
setTheme(storedTheme, false);
document.getElementById("cga-theme-toggle").addEventListener("click", function () {
  setTheme(
    document.documentElement.dataset.theme === "dark" ? "light" : "dark",
    true
  );
});

function fragment(snapshot, component, route) {
  const fragments = snapshot && snapshot.fragments;
  return fragments && fragments[component + "/" + route]
    ? fragments[component + "/" + route]
    : '<div class="cga-err">fragment missing from capture</div>';
}

function showDetail(component) {
  const snapshot = SNAPSHOTS[current] || {};
  selectedDetail = component;
  document.getElementById("cga-detail-which").textContent = component;
  detail.dataset.comp = component;
  detail.dataset.route = "/detail";
  detail.innerHTML = fragment(snapshot, component, "detail");
  detail.querySelectorAll(".cga-apply").forEach(function (button) {
    button.disabled = true;
    button.title = "Captured replay is read-only";
  });
}

function show(index) {
  if (!SNAPSHOTS.length) {
    count.textContent = "0 / 0";
    time.textContent = "\u2014";
    label.textContent = "No valid captures";
    return;
  }
  current = Math.max(0, Math.min(index, SNAPSHOTS.length - 1));
  const snapshot = SNAPSHOTS[current];
  progress.value = String(current);
  count.textContent = (current + 1) + " / " + SNAPSHOTS.length;
  time.textContent = snapshot.captured_at || "\u2014";
  label.textContent = snapshot.label || "\u2014";
  document.getElementById("cga-header").innerHTML =
    fragment(snapshot, "cgasv", "header");
  OVERVIEWS.forEach(function (component) {
    const slot = document.querySelector(
      '.cga-box[data-comp="' + component + '"]'
    );
    if (slot) slot.innerHTML = fragment(snapshot, component, "overview");
  });
  showDetail(selectedDetail);
}

function step(delta) {
  show(current + delta);
}

progress.min = "0";
progress.max = String(Math.max(0, SNAPSHOTS.length - 1));
progress.addEventListener("input", function () {
  show(parseInt(progress.value, 10) || 0);
});
progress.addEventListener("change", function () {
  show(parseInt(progress.value, 10) || 0);
});

document.querySelectorAll(".cga-flow").forEach(function (flow) {
  flow.addEventListener("click", function (event) {
    const box = event.target.closest(".cga-box[data-comp]");
    if (box) showDetail(box.dataset.comp);
  });
});
document.getElementById("cga-reload").addEventListener("click", function () {
  show(current);
});
document.querySelector(".cga-replay-controls").addEventListener(
  "wheel",
  function (event) {
    step(event.deltaY > 0 ? 1 : -1);
    event.preventDefault();
  },
  { passive: false }
);
document.addEventListener("keydown", function (event) {
  const target = event.target;
  if (
    target &&
    (target.tagName === "INPUT" || target.tagName === "TEXTAREA") &&
    target !== progress
  ) {
    return;
  }
  switch (event.key) {
    case "ArrowUp":
    case "ArrowLeft":
    case "PageUp":
      step(-1);
      event.preventDefault();
      break;
    case "ArrowDown":
    case "ArrowRight":
    case "PageDown":
      step(1);
      event.preventDefault();
      break;
    case "Home":
      show(0);
      event.preventDefault();
      break;
    case "End":
      show(SNAPSHOTS.length - 1);
      event.preventDefault();
      break;
  }
});

show(0);
</script>
"""


def build_export(snapshots: list[dict[str, Any]], cga_root: Path) -> str:
    index_path = cga_root / "web" / "index.html"
    css_path = cga_root / "web" / "cga.css"
    source = index_path.read_text(encoding="utf-8")
    css = css_path.read_text(encoding="utf-8")

    body_match = re.search(r"<body>(.*)</body>", source, flags=re.DOTALL)
    if body_match is None:
        raise RuntimeError(f"cannot find <body> in {index_path}")
    dashboard = re.sub(
        r'\s*<script src="(?:cga-config|cga)\.js(?:\?[^"]*)?"></script>',
        "",
        body_match.group(1),
    ).strip()

    title = "cga - captured dashboard replay"
    payload = json.dumps(snapshots, ensure_ascii=True, separators=(",", ":"))
    payload = payload.replace("<", r"\u003c")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
{css}
</style>
{REPLAY_STYLE}
</head>
<body>
<div class="cga-replay-wrap">
{REPLAY_CONTROLS}
<main class="cga-replay-dashboard">
{dashboard}
</main>
</div>
<script>window.CGA_DASHBOARD_SNAPSHOTS = {payload};</script>
{REPLAY_DRIVER}
</body>
</html>
"""


def export_replay(
    dump_path: Path,
    output_path: Path,
    cga_root: Path | None = None,
) -> int:
    snapshots = read_snapshots(dump_path)
    if not snapshots:
        raise RuntimeError(f"no valid dashboard captures in {dump_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page = build_export(snapshots, cga_root or _cga_root())
    output_path.write_text(page, encoding="utf-8")
    return len(snapshots)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cga view",
        description=(
            "Capture the rendered CGA dashboard or export its JSONL dump "
            "as one self-contained HTML replay."
        ),
    )
    parser.add_argument(
        "--dump",
        default="cga-dashboard-dump",
        help="dashboard capture dump (JSONL)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--capture",
        action="store_true",
        help="fetch all live CGA fragments and append one capture",
    )
    mode.add_argument(
        "--export",
        metavar="HTML",
        help="write a self-contained offline replay and exit",
    )
    parser.add_argument(
        "--label",
        default="manual capture",
        help="progress label stored with a capture",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="per-fragment capture timeout in seconds (default: 5)",
    )
    return enhance_parser(parser, "view")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dump_path = Path(args.dump).expanduser().resolve()
    try:
        if args.capture:
            snapshot = capture_snapshot(args.label, args.timeout)
            append_snapshot(dump_path, snapshot)
            print(
                f"cga view: captured {len(snapshot['fragments'])} fragments "
                f"to {dump_path}",
                file=sys.stderr,
            )
            return 0
        output_path = Path(args.export).expanduser().resolve()
        count = export_replay(dump_path, output_path)
        print(
            f"cga view: exported {count} captures to {output_path}",
            file=sys.stderr,
        )
        return 0
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        print(f"cga view: {exc}", file=sys.stderr)
        return 1

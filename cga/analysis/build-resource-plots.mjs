#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const VERSION = "1.6.32";
const BASE_URL = `https://cdn.jsdelivr.net/npm/uplot@${VERSION}/dist`;
const ASSETS = [
  ["uPlot.min.css", "df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04"],
  ["uPlot.iife.min.js", "19c8d4c6ad88929a79f4ae49d6f7161566dfd0ba3d15cc495e974f787eb78f1f"],
];

const here = dirname(fileURLToPath(import.meta.url));
const runDir = resolve(process.argv[2] ?? join(here, "run-system-10-2026-08-24"));
const inputPath = join(runDir, "pass1-resources.tsv");
const outputPath = join(runDir, "resource-plots.html");

async function loadAsset([name, expected]) {
  const response = await fetch(`${BASE_URL}/${name}`);
  if (!response.ok) throw new Error(`failed to download ${name}: HTTP ${response.status}`);
  const content = await response.text();
  const actual = createHash("sha256").update(content).digest("hex");
  if (actual !== expected) throw new Error(`${name} checksum mismatch: expected ${expected}, got ${actual}`);
  return content;
}

function parseTimestamp(text) {
  const millis = Date.parse(text.replace(",", "."));
  if (!Number.isFinite(millis)) throw new Error(`invalid timestamp: ${text}`);
  return millis / 1000;
}

function aggregate(tsv) {
  const lines = tsv.trimEnd().split("\n");
  const columns = lines.shift().split("\t");
  const column = Object.fromEntries(columns.map((name, index) => [name, index]));
  for (const name of ["timestamp", "rss_kib", "pcpu", "comm"]) {
    if (!(name in column)) throw new Error(`missing required column: ${name}`);
  }

  const byTime = new Map();
  for (const line of lines) {
    const fields = line.split("\t");
    const timestamp = fields[column.timestamp];
    let sample = byTime.get(timestamp);
    if (!sample) {
      sample = { timestamp, epoch: parseTimestamp(timestamp), cores: 0, rssGiB: 0, processes: 0 };
      byTime.set(timestamp, sample);
    }
    if (fields[column.comm] !== "java") continue;
    sample.cores += Number(fields[column.pcpu]) / 100;
    sample.rssGiB += Number(fields[column.rss_kib]) / 1048576;
    sample.processes += 1;
  }
  return [...byTime.values()].sort((a, b) => a.epoch - b.epoch);
}

const round = (value) => Number(value.toFixed(3));

function buildHtml(samples, css, js) {
  const raw = {
    epoch: samples.map((sample) => sample.epoch),
    cpu: samples.map((sample) => round(sample.cores)),
    memory: samples.map((sample) => round(sample.rssGiB)),
    processes: samples.map((sample) => sample.processes),
  };
  const maxCpu = Math.max(...raw.cpu);
  const maxMemory = Math.max(...raw.memory);

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MRVA collection analysis resource use</title>
<style>
${css}
:root {
  color-scheme: light;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --page-pad-y: 12px;
  --page-pad-x: clamp(10px, 1.2vw, 20px);
  --chart-h: 34vh;
}
* { box-sizing: border-box; }
body { margin: 0; background: #eef0f2; color: #1e2937; }
main { padding: var(--page-pad-y) var(--page-pad-x) 18px; }
h1 { margin: 0 0 4px; font-size: clamp(18px, 2.1vh, 25px); font-weight: 650; }
.subtitle { margin: 0 0 10px; color: #526174; font-size: 13px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin-bottom: 10px; }
button {
  border: 1px solid #b8c0cc; background: white; color: #1e2937; border-radius: 5px;
  padding: 5px 10px; font: inherit; cursor: pointer;
}
button:hover { border-color: #78889c; }
.hint { color: #64748b; font-size: 12px; }
.chart {
  margin-bottom: 10px; padding: 8px 10px; border: 1px solid #cbd1d8; border-radius: 7px;
  background: white; box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08); overflow: hidden;
}
.u-title { font-size: 15px; font-weight: 600; }
.notes {
  margin-top: 2px; padding: 10px 12px; border-left: 3px solid #7d8da3; background: #f8fafc;
  color: #465568; font-size: 12px; line-height: 1.45;
}
.notes p { margin: 0 0 5px; }
.notes p:last-child { margin-bottom: 0; }
.tooltip {
  position: fixed; z-index: 20; min-width: 205px; padding: 7px 9px; border: 1px solid #aeb8c5;
  border-radius: 5px; background: rgba(255, 255, 255, 0.97); box-shadow: 0 6px 14px rgba(15, 23, 42, 0.14);
  color: #1e2937; font-size: 12px; line-height: 1.45; pointer-events: none; opacity: 0;
}
.tooltip.visible { opacity: 1; }
.tooltip strong { display: block; font-weight: 650; }
@media (max-width: 640px) {
  :root { --chart-h: 31vh; }
  .chart { padding-left: 4px; padding-right: 4px; }
  .hint { flex-basis: 100%; }
}
</style>
</head>
<body>
<main>
  <h1>MRVA collection analysis resource use</h1>
  <p class="subtitle">Six workers · CodeQL 2.23.9 · 16 GiB / 4 evaluator threads per job · ${samples.length} samples</p>
  <div class="toolbar">
    <button id="reset" type="button">Reset zoom</button>
    <span class="hint">Drag horizontally in either plot to zoom; hover for synchronized values.</span>
  </div>
  <section class="chart" id="cpu"></section>
  <section class="chart" id="memory"></section>
  <aside class="notes">
    <p><strong>CPU:</strong> sum of <code>ps %CPU / 100</code> for concurrent CodeQL Java evaluators. This is each process’s lifetime-average CPU use, not an instantaneous five-second CPU counter. Peak recorded sum: ${maxCpu.toFixed(2)} cores.</p>
    <p><strong>Memory:</strong> sum of resident-set size for concurrent CodeQL Java evaluators. It excludes wrappers, agents, the MRVA server, PostgreSQL, page cache, and other host use. Peak recorded sum: ${maxMemory.toFixed(2)} GiB.</p>
    <p>Window: ${samples[0].timestamp} through ${samples.at(-1).timestamp}. Source: <code>${basename(inputPath)}</code>. Values are embedded; this file has no runtime network dependency. Plotting library: uPlot ${VERSION}.</p>
  </aside>
</main>
<div class="tooltip" id="tooltip"></div>
<script>
${js}
</script>
<script>
const raw = ${JSON.stringify(raw)};
const plots = [];
const tooltip = document.getElementById("tooltip");
const fullRange = [raw.epoch[0], raw.epoch.at(-1)];
let syncingScale = false;

function dimensions() {
  const chartHeight = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--chart-h"));
  return {
    width: Math.max(300, document.getElementById("cpu").clientWidth - 20),
    height: Math.max(220, Math.floor(window.innerHeight * chartHeight / 100)),
  };
}

function options(title, yLabel, color, decimals) {
  const dims = dimensions();
  return {
    title, width: dims.width, height: dims.height,
    cursor: { drag: { x: true, y: false }, sync: { key: "resources" } },
    legend: { show: false },
    scales: { x: { time: true }, y: { auto: true, range: (u, min, max) => [0, Math.max(max * 1.08, 1)] } },
    hooks: {
      setScale: [(u, key) => syncZoom(u, key)],
      setCursor: [(u) => showTooltip(u)],
    },
    axes: [
      { values: (u, vals) => vals.map((value) => uPlot.fmtDate("{HH}:{mm}:{ss}")(new Date(value * 1000))) },
      { label: yLabel, size: 65, values: (u, vals) => vals.map((value) => value.toFixed(decimals)) },
    ],
    series: [
      {},
      { label: yLabel, stroke: color, width: 2, points: { show: false }, spanGaps: true },
    ],
  };
}

const cpu = new uPlot(options("CPU use", "Average cores", "#1479b8", 1), [raw.epoch, raw.cpu], document.getElementById("cpu"));
plots.push(cpu);
const memory = new uPlot(options("Memory use", "Java RSS (GiB)", "#c35422", 0), [raw.epoch, raw.memory], document.getElementById("memory"));
plots.push(memory);

function syncZoom(source, key) {
  if (key !== "x" || syncingScale) return;
  syncingScale = true;
  const range = { min: source.scales.x.min, max: source.scales.x.max };
  for (const plot of plots) if (plot !== source) plot.setScale("x", range);
  syncingScale = false;
}

function showTooltip(plot) {
  const index = plot.cursor.idx;
  if (index == null || index < 0) {
    tooltip.classList.remove("visible");
    return;
  }
  const when = new Date(raw.epoch[index] * 1000).toLocaleString(undefined, { timeZoneName: "short" });
  tooltip.innerHTML = "<strong>" + when + "</strong>CPU: " + raw.cpu[index].toFixed(2) +
    " average cores<br>Memory: " + raw.memory[index].toFixed(2) +
    " GiB RSS<br>Java evaluators: " + raw.processes[index];
  const rect = plot.root.getBoundingClientRect();
  const x = Math.min(window.innerWidth - tooltip.offsetWidth - 12, rect.left + plot.cursor.left + 18);
  const y = Math.max(10, Math.min(window.innerHeight - tooltip.offsetHeight - 10, rect.top + plot.cursor.top - 34));
  tooltip.style.left = Math.max(10, x) + "px";
  tooltip.style.top = y + "px";
  tooltip.classList.add("visible");
}

document.getElementById("reset").addEventListener("click", () => {
  for (const plot of plots) plot.setScale("x", { min: fullRange[0], max: fullRange[1] });
});
window.addEventListener("resize", () => {
  const dims = dimensions();
  for (const plot of plots) plot.setSize(dims);
});
</script>
</body>
</html>
`;
}

const [tsv, css, js] = await Promise.all([
  readFile(inputPath, "utf8"),
  loadAsset(ASSETS[0]),
  loadAsset(ASSETS[1]),
]);
const samples = aggregate(tsv);
if (samples.length === 0) throw new Error(`no samples found in ${inputPath}`);
await writeFile(outputPath, buildHtml(samples, css, js));
console.log(`wrote ${outputPath} (${samples.length} samples)`);

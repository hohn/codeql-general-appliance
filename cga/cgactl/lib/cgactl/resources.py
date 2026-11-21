from __future__ import annotations

import datetime
import html
import json
import os
import resource
import subprocess
import time
from pathlib import Path


def _process_group(pgid: int) -> dict:
    ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    page = os.sysconf("SC_PAGE_SIZE")
    count = rss = cpu_ticks = read_bytes = write_bytes = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().split()
            if int(fields[4]) != pgid:
                continue
            count += 1
            cpu_ticks += int(fields[13]) + int(fields[14])
            rss += int((entry / "statm").read_text().split()[1]) * page
            io = {}
            for line in (entry / "io").read_text().splitlines():
                key, value = line.split(":", 1)
                io[key] = int(value)
            read_bytes += io.get("read_bytes", 0)
            write_bytes += io.get("write_bytes", 0)
        except (FileNotFoundError, PermissionError, ProcessLookupError,
                ValueError, IndexError):
            continue
    return {"processes": count, "rss_bytes": rss,
            "cpu_seconds": cpu_ticks / ticks,
            "read_bytes": read_bytes, "write_bytes": write_bytes}


def _report(path: Path, summary: dict, samples: list[dict]) -> None:
    maximum = max((sample["rss_bytes"] for sample in samples), default=1)
    width, height = 900, 220
    points = []
    for index, sample in enumerate(samples):
        x = index * width / max(len(samples) - 1, 1)
        y = height - sample["rss_bytes"] * height / max(maximum, 1)
        points.append(f"{x:.1f},{y:.1f}")
    command = " ".join(html.escape(part) for part in summary["command"])
    body = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Resource report</title><style>
body{{font:14px system-ui,sans-serif;max-width:1000px;margin:2rem auto}}
table{{border-collapse:collapse}}td,th{{padding:.35rem .7rem;border:1px solid #bbb}}
svg{{border:1px solid #bbb;width:100%;height:220px}}code{{overflow-wrap:anywhere}}
</style></head><body><h1>Build resource report</h1>
<p><code>{command}</code></p><table>
<tr><th>exit</th><td>{summary['exit_code']}</td></tr>
<tr><th>wall seconds</th><td>{summary['wall_seconds']:.3f}</td></tr>
<tr><th>CPU seconds</th><td>{summary['cpu_seconds']:.3f}</td></tr>
<tr><th>CPU utilization</th><td>{summary['cpu_percent']:.1f}%</td></tr>
<tr><th>peak sampled RSS</th><td>{summary['peak_rss_bytes']}</td></tr>
<tr><th>maximum child RSS</th><td>{summary['max_child_rss_bytes']}</td></tr>
<tr><th>samples</th><td>{summary['samples']}</td></tr></table>
<h2>Aggregate process-group RSS</h2>
<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">
<polyline fill="none" stroke="#2563eb" stroke-width="2" points="{' '.join(points)}"/>
</svg><p>Raw one-sample-per-line data: <a href="resource_samples.jsonl">resource_samples.jsonl</a>.</p>
</body></html>"""
    path.write_text(body, encoding="utf-8")


def measure(command: list[str], output_dir: Path, interval: float,
            log_path: Path | None = None,
            passthrough_stdout: bool = False) -> tuple[int, dict]:
    if not command:
        raise ValueError("measure requires a command after --")
    if interval < 0.2:
        raise ValueError("sample interval must be at least 0.2 seconds")
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_path = output_dir / "resource_samples.jsonl"
    summary_path = output_dir / "resource_summary.json"
    report_path = output_dir / "resource_report.html"
    samples_path.write_text("", encoding="utf-8")
    log = log_path.open("wb") if log_path else None
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    proc = subprocess.Popen(
        command,
        stdout=None if passthrough_stdout else log,
        stderr=log if passthrough_stdout else subprocess.STDOUT,
        start_new_session=True)
    samples = []
    previous_cpu = previous_wall = 0.0
    try:
        while True:
            elapsed = time.monotonic() - started
            sample = {"timestamp": datetime.datetime.now(
                datetime.timezone.utc).isoformat(), "wall_seconds": elapsed,
                **_process_group(proc.pid)}
            delta_wall = elapsed - previous_wall
            sample["cpu_percent"] = (
                100 * (sample["cpu_seconds"] - previous_cpu) / delta_wall
                if delta_wall > 0 else 0)
            samples.append(sample)
            with samples_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(sample, sort_keys=True) + "\n")
            previous_cpu, previous_wall = sample["cpu_seconds"], elapsed
            try:
                exit_code = proc.wait(timeout=interval)
                break
            except subprocess.TimeoutExpired:
                pass
    finally:
        if log:
            log.close()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall = time.monotonic() - started
    cpu = ((after.ru_utime + after.ru_stime) -
           (before.ru_utime + before.ru_stime))
    summary = {
        "schema_version": 1, "command": command, "started_at": started_at,
        "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "exit_code": exit_code, "wall_seconds": wall, "cpu_seconds": cpu,
        "cpu_percent": 100 * cpu / wall if wall else 0,
        "peak_rss_bytes": max((x["rss_bytes"] for x in samples), default=0),
        "max_child_rss_bytes": after.ru_maxrss * 1024,
        "samples": len(samples), "sample_interval_seconds": interval,
        "raw_samples": str(samples_path.resolve()),
        "report": str(report_path.resolve()),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    _report(report_path, summary, samples)
    return exit_code, summary

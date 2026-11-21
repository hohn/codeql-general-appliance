"""Scenario-specific input checks and observations; CGA owns workflow operations."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


CGA_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CGA_ROOT / "cgalib"))
import cgast


def cga(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [str(CGA_ROOT / "cga"), *args], check=True, capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr, file=sys.stderr, end="")
        raise


def state() -> dict:
    return json.loads(cga("--json", "state", "show").stdout)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_version() -> str:
    runtime = subprocess.check_output(
        [os.environ.get("CODEQL_CLI_PATH", "codeql"), "version", "--format=json"],
        text=True,
    )
    return json.loads(runtime)["version"]


def selection(current: dict) -> list[dict]:
    rows = load(cgast.resolve(current["cgadl-selection"]))["databases"]
    identities = [(row["git_owner"], row["git_repo"]) for row in rows]
    if len(rows) < 200:
        raise ValueError(f"need 200+ distinct C/C++ databases, selected {len(rows)}")
    if len(set(identities)) != len(rows):
        raise ValueError("selection contains duplicate owner/repo identities")
    if any(not owner or not repo or row["primary_language"] != "cpp"
           for (owner, repo), row in zip(identities, rows)):
        raise ValueError("selection must contain named C/C++ repositories")
    hashes = [row["content_hash"] for row in rows]
    if any(not value for value in hashes) or len(set(hashes)) != len(rows):
        raise ValueError("selection must contain distinct archive content hashes")
    return rows


def check_archives(rows: list[dict], dbdir: Path) -> None:
    for row in rows:
        owner, repo = row["git_owner"], row["git_repo"]
        archive = dbdir / owner / repo / f"{owner}_{repo}_db.zip"
        if sha256(archive) != row["content_hash"]:
            raise ValueError(f"database archive hash mismatch: {archive}")


def freeze(args) -> None:
    current = state()
    rows = selection(current)
    packs = current["cgaql-pack"]
    if len(packs) != 1:
        raise ValueError("expected exactly one Fprintf query pack")
    pack = cgast.resolve(packs[0])
    check_archives(rows, cgast.resolve(current["cgadl-dbdir"]))
    document = {
        "codeql_version": runtime_version(),
        "database_versions": dict(Counter(row["tool_version"] for row in rows)),
        "databases": rows,
        "pack": str(pack),
        "pack_sha256": sha256(pack),
    }
    with args.inputs.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2)
        stream.write("\n")
    print(f"Frozen {len(rows)} databases and one pack: {args.inputs}")


def ready(args, current: dict | None = None) -> dict:
    current = state() if current is None else current
    frozen = load(args.inputs)
    if selection(current) != frozen["databases"]:
        raise ValueError("active database selection differs from frozen inputs")
    packs = current["cgaql-pack"]
    if len(packs) != 1 or sha256(cgast.resolve(packs[0])) != frozen["pack_sha256"]:
        raise ValueError("active query pack differs from frozen inputs")
    if runtime_version() != frozen["codeql_version"]:
        raise ValueError("CodeQL runtime differs from frozen inputs")
    if getattr(args, "check_archives", False):
        check_archives(frozen["databases"], cgast.resolve(current["cgadl-dbdir"]))
    return frozen


def workload(path: Path) -> list[tuple[str, str]]:
    rows = [tuple(line.split("\t")) for line in path.read_text().splitlines()]
    if not rows or any(len(row) != 2 or not all(row) for row in rows):
        raise ValueError(f"missing or invalid workload: {path}; run submit first")
    if len({row[0] for row in rows}) != len(rows):
        raise ValueError("workload contains duplicate submission names")
    return rows


def submissions(current: dict, planned: list[tuple[str, str]], frozen: dict) -> list[dict]:
    items = current.get("cgamr-submissions", {})
    if set(items) != {name for name, _ in planned}:
        raise ValueError("recorded submissions differ from workload; inspect cga mr info")
    wanted = {f"{row['git_owner']}/{row['git_repo']}" for row in frozen["databases"]}
    result = []
    for name, user in planned:
        item = items[name]
        repos = item["repositories"]
        if (item["user"] != user or item["language"] != "cpp"
                or set(repos) != wanted or len(repos) != len(wanted)
                or sha256(cgast.resolve(item["pack"])) != frozen["pack_sha256"]):
            raise ValueError(f"{name}: identity or repository set differs from inputs")
        result.append(item)
    if len({item["session_id"] for item in result}) != len(result):
        raise ValueError("submissions share a session ID")
    return result


def job_outcomes(items: list[dict], frozen: dict) -> tuple[Counter, set[str], list[dict]]:
    wanted = {f"{row['git_owner']}/{row['git_repo']}" for row in frozen["databases"]}
    terminal = {"succeeded", "failed", "canceled", "cancelled", "timed_out"}
    active = {"pending", "queued", "in_progress"}
    counts = Counter()
    unfinished = set()
    failures = []
    for item in items:
        scanned = item.get("status_response", {}).get("scanned_repositories", [])
        reported = [row["repository"]["full_name"] for row in scanned]
        if len(reported) != len(wanted) or set(reported) != wanted:
            raise ValueError(
                f"{item['name']}: status response repository set differs from frozen "
                f"inputs (expected {len(wanted)} distinct jobs, got {len(reported)} "
                f"rows/{len(set(reported))} distinct); refresh with cga mr status")
        for row in scanned:
            status = row.get("analysis_status")
            if status not in terminal | active:
                raise ValueError(
                    f"{item['name']}: unknown job status {status!r} for "
                    f"{row['repository']['full_name']}")
            counts[status] += 1
            if status in active:
                unfinished.add(item["name"])
            elif status != "succeeded":
                failures.append({
                    "submission": item["name"],
                    "repository": row["repository"]["full_name"],
                    "status": status,
                })
    return counts, unfinished, failures


def report_outcomes(items: list[dict], counts: Counter, failures: list[dict]) -> None:
    print(f"OBSERVATION COMPLETE: {len(items)} sessions, "
          f"{sum(counts.values())} terminal jobs; {json.dumps(dict(counts))}",
          flush=True)
    for failure in failures:
        print(f"  {failure['status']}: {failure['submission']} "
              f"{failure['repository']}", flush=True)


def wait(args) -> None:
    frozen = ready(args)
    planned = workload(args.workload)
    unfinished = {name for name, _ in planned}
    deadline = time.monotonic() + args.timeout_seconds
    while True:
        current = state()
        items = submissions(current, planned, frozen)
        for item in items:
            if item["name"] in unfinished:
                cga("mr", "status", "--name", item["name"])
        items = submissions(state(), planned, frozen)
        counts, unfinished, failures = job_outcomes(items, frozen)
        print(json.dumps({
            "sessions": dict(Counter(item["status"] for item in items)),
            "jobs": dict(counts),
        }), flush=True)
        if not unfinished:
            report_outcomes(items, counts, failures)
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("polling deadline exceeded; use wait/status to resume")
        time.sleep(min(args.poll_seconds, remaining))


def verify(args) -> None:
    current = state()
    frozen = ready(args, current)
    items = submissions(current, workload(args.workload), frozen)
    counts, unfinished, failures = job_outcomes(items, frozen)
    if unfinished:
        raise ValueError(f"jobs still active in {', '.join(sorted(unfinished))}; "
                         "run wait to observe completion")
    report_outcomes(items, counts, failures)


def sample(url: str, timeout: float) -> tuple[bytes, dict]:
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read()
        status = response.status
    return body, {
        "http_status": status,
        "response_ms": round((time.perf_counter() - started) * 1000, 3),
        "bytes": len(body),
    }


def observe(args) -> None:
    server = os.environ.get("CGA_MRVA_SERVER", "http://127.0.0.1:8081").rstrip("/")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = args.output_dir / f"{timestamp}.jsonl"
    print(f"sysview: {server}/sysview\nobservations: {output}", flush=True)
    with output.open("x", encoding="utf-8") as stream:
        for index in range(args.samples):
            record = {"observed_at": datetime.now(timezone.utc).isoformat(),
                      "server": server}
            try:
                if index == 0:
                    _, record["page"] = sample(server + "/sysview", args.request_timeout)
                body, metrics = sample(server + "/sysview/data", args.request_timeout)
                started = time.perf_counter()
                snapshot = json.loads(body)
                if not isinstance(snapshot, dict):
                    raise ValueError("sysview response must be a JSON object")
                metrics["json_parse_ms"] = round(
                    (time.perf_counter() - started) * 1000, 3)
                record["data"] = metrics
                if snapshot.get("error"):
                    raise ValueError(f"sysview snapshot error: {snapshot['error']}")
                metrics["generated_at"] = snapshot["generated_at"]
                metrics["refresh_ms"] = snapshot["refresh_ms"]
                metrics["shown"] = {
                    key: len(snapshot.get(key) or [])
                    for key in ("servers", "jobs", "workers", "spawns")
                }
                metrics["mode"] = snapshot.get("mode")
            except (OSError, ValueError, KeyError) as exc:
                record["error"] = str(exc)
                if isinstance(exc, urllib.error.HTTPError):
                    record["http_status"] = exc.code
                    exc.close()
                stream.write(json.dumps(record) + "\n")
                stream.flush()
                raise
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            print(json.dumps(record), flush=True)
            if index + 1 < args.samples:
                time.sleep(args.interval)
    cga("artifact", "add", str(output), "--name", f"sysview-observation-{timestamp}")


def positive(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def storage(args) -> None:
    checked = set()
    for path in args.paths:
        probe = path.expanduser().resolve()
        while not probe.exists():
            probe = probe.parent
        device = probe.stat().st_dev
        if device in checked:
            continue
        free = shutil.disk_usage(probe).free
        if free < 16 * 1024**3:
            raise ValueError(
                f"{path}: need at least 16 GiB free, have {free / 1024**3:.1f} GiB; "
                "set CGA_SYSTEM11_ROOT/TMPDIR and other runtime overrides "
                "to a larger filesystem")
        print(f"Storage: {probe} has {free / 1024**3:.1f} GiB free")
        checked.add(device)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selection").set_defaults(func=lambda _: selection(state()))
    sp = sub.add_parser("storage")
    sp.add_argument("paths", type=Path, nargs="+")
    sp.set_defaults(func=storage)
    for command, function in (("freeze", freeze), ("ready", ready),
                              ("wait", wait), ("verify", verify)):
        sp = sub.add_parser(command)
        sp.add_argument("--inputs", type=Path, required=True)
        if command == "ready":
            sp.add_argument("--check-archives", action="store_true")
        if command in ("wait", "verify"):
            sp.add_argument("--workload", type=Path, required=True)
        if command == "wait":
            sp.add_argument("--poll-seconds", type=positive, default=5)
            sp.add_argument("--timeout-seconds", type=positive, default=14400)
        sp.set_defaults(func=function)
    sp = sub.add_parser("observe")
    sp.add_argument("--output-dir", type=Path, required=True)
    sp.add_argument("--samples", type=int, default=60)
    sp.add_argument("--interval", type=positive, default=1)
    sp.add_argument("--request-timeout", type=positive, default=10)
    sp.set_defaults(func=observe)
    args = parser.parse_args()
    if args.command == "observe" and args.samples < 1:
        parser.error("--samples must be positive")
    try:
        args.func(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()

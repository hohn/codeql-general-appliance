#!/usr/bin/env python3
"""Download and extract vulnerable, fixed, and current Debian sources."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VARIANTS = {
    "vulnerable": "vulnerable",
    "patched": "fixed",
    "most-recent": "current",
}


def load_spec(directory: Path) -> dict:
    return json.loads((directory / "spec.json").read_text(encoding="utf-8"))


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def stage(directory: Path, variant: dict, extract: bool) -> str:
    name = VARIANTS[variant["name"]]
    root = directory / "tmp" / name
    archives = root / "archives"
    source = root / "source"
    marker = root / ".complete.json"
    archives.mkdir(parents=True, exist_ok=True)
    if marker.is_file() and (not extract or source.is_dir()):
        return f"SKIP  {directory.name}/{name}"

    url = variant["source"]["url"]
    run(["dget", "--download-only", "--allow-unauthenticated", url], archives)
    dscs = sorted(archives.glob("*.dsc"))
    if len(dscs) != 1:
        raise RuntimeError(
            f"{directory.name}/{name}: expected one .dsc, found {len(dscs)}"
        )
    if extract:
        shutil.rmtree(source, ignore_errors=True)
        run(["dpkg-source", "-x", str(dscs[0]), str(source)], archives)
    marker.write_text(json.dumps({
        "variant": name,
        "version": variant["version"],
        "dsc": dscs[0].name,
        "url": url,
        "extracted": extract,
    }, indent=2) + "\n", encoding="utf-8")
    return f"READY {directory.name}/{name}"


def jobs(cve: str | None) -> list[tuple[Path, dict]]:
    directories = (
        [ROOT / cve.lower()] if cve
        else sorted(p for p in ROOT.glob("cve-*") if (p / "spec.json").is_file())
    )
    result = []
    for directory in directories:
        if not (directory / "spec.json").is_file():
            raise SystemExit(f"unknown CVE sample: {directory.name}")
        cve_doc = load_spec(directory)["cves"][0]
        result.extend((directory, variant) for variant in cve_doc["variants"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cve")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--no-extract", action="store_true")
    args = parser.parse_args()
    failures = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, args.jobs)
    ) as executor:
        futures = {
            executor.submit(stage, directory, variant, not args.no_extract):
            (directory, variant)
            for directory, variant in jobs(args.cve)
        }
        for future in concurrent.futures.as_completed(futures):
            directory, variant = futures[future]
            try:
                print(future.result(), flush=True)
            except Exception as exc:
                failures.append(
                    f"{directory.name}/{VARIANTS[variant['name']]}: {exc}"
                )
                print(f"ERROR {failures[-1]}", file=sys.stderr, flush=True)
    if failures:
        print(f"{len(failures)} source set(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

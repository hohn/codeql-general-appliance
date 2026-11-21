#!/usr/bin/env python3
"""Summarize the six run-system-10 SARIF files for selected CVEs."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import sys


SELECTED_CVES = (
    "cve-2016-9843",
    "cve-2018-16554",
    "cve-2018-1000880",
)
VARIANT_MODE = re.compile(r"-(most-recent|patched|vulnerable)-(none|trace)\.sarif$")
VARIANT_ORDER = {"vulnerable": 0, "patched": 1, "most-recent": 2}
MODE_ORDER = {"none": 0, "trace": 1}


def arguments() -> argparse.Namespace:
    repository = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=repository.parent
        / "single-machine-mrva-artifacts"
        / "runs"
        / "run-system-10-2026-08-24",
    )
    parser.add_argument("--repository", type=Path, default=repository)
    return parser.parse_args()


def results_in(sarif: dict) -> list[dict]:
    return [result for run in sarif.get("runs", []) for result in run.get("results", [])]


def primary_location(result: dict) -> str:
    locations = result.get("locations", [])
    if not locations:
        return "?"
    physical = locations[0].get("physicalLocation", {})
    uri = physical.get("artifactLocation", {}).get("uri", "?")
    line = physical.get("region", {}).get("startLine")
    return f"{uri}:{line}" if line is not None else uri


def main() -> int:
    args = arguments()
    rows = []
    for cve_slug in SELECTED_CVES:
        spec_path = args.repository / "cga" / "examples" / "cves" / cve_slug / "spec.json"
        spec = json.loads(spec_path.read_text())["cves"][0]
        versions = {variant["name"]: variant["version"] for variant in spec["variants"]}
        query_id = spec["queries"][0]["id"]
        sarif_dir = args.artifact_root / "ingest" / f"e2e-{cve_slug}"
        sarif_paths = sorted(sarif_dir.glob("*.sarif"))
        if len(sarif_paths) != 6:
            raise RuntimeError(f"expected six SARIF files under {sarif_dir}, found {len(sarif_paths)}")
        for sarif_path in sarif_paths:
            match = VARIANT_MODE.search(sarif_path.name)
            if not match:
                raise RuntimeError(f"cannot parse variant and mode from {sarif_path.name}")
            variant, mode = match.groups()
            results = results_in(json.loads(sarif_path.read_text()))
            locations = Counter(primary_location(result) for result in results)
            rendered_locations = "; ".join(
                f"{location} x{count}" for location, count in sorted(locations.items())
            )
            rows.append(
                {
                    "cve": spec["id"],
                    "source_package": spec["debian"]["source_package"],
                    "variant": variant,
                    "mode": mode,
                    "version": versions[variant],
                    "query_id": query_id,
                    "result_count": len(results),
                    "primary_locations": rendered_locations or "-",
                    "sarif": str(sarif_path.relative_to(args.artifact_root)),
                }
            )

    rows.sort(key=lambda row: (row["cve"], VARIANT_ORDER[row["variant"]], MODE_ORDER[row["mode"]]))
    fields = list(rows[0])
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

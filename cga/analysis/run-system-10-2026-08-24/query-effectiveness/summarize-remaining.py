#!/usr/bin/env python3
"""Summarize the 16 run-system-10 cases not in the initial manual sample."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys


INITIAL_SAMPLE = {"CVE-2016-9843", "CVE-2018-16554", "CVE-2018-1000880"}
VARIANT_MODE = re.compile(r"-(most-recent|patched|vulnerable)-(none|trace)$")

# Fault sites are transcribed from each checked-in CVE README and confirmed
# against the vulnerable source tree. They make the SARIF location check
# deterministic; they do not change the result-count test.
FAULT_SITES = {
    "CVE-2018-1000052": ("fmt::print invalid-format-specifier handling", "src/format.cc"),
    "CVE-2018-1000127": ("item_free", "items.c"),
    "CVE-2018-10887": ("git_delta_apply", "src/delta.c"),
    "CVE-2018-12326": ("redis-cli command-line handling", "src/redis-cli.c"),
    "CVE-2018-12982": ("PdfVariant::DelayedLoad", "src/base/PdfVariant.h"),
    "CVE-2018-13785": ("png_check_chunk_length", "pngrutil.c"),
    "CVE-2018-17540": (
        "GMP certificate parsing",
        "src/libstrongswan/plugins/gmp/gmp_rsa_private_key.c",
    ),
    "CVE-2018-19886": ("huffcode", "libfaac/huff2.c"),
    "CVE-2018-20182": ("seamless_process_line", "seamless.c"),
    "CVE-2018-20534": ("testcase parser illegal access", "ext/testcase.c"),
    "CVE-2018-5205": ("incomplete escape-code handling", "src/fe-common/core/formats.c"),
    "CVE-2019-11072": ("burl_normalize_2F_to_slash_fix", "src/burl.c"),
    "CVE-2019-13115": (
        "kex_method_diffie_hellman_group_exchange_sha256_key_exchange",
        "src/kex.c",
    ),
    "CVE-2019-15296": ("faad_resetbits", "libfaad/bits.c"),
    "CVE-2019-15945": ("decode_bit_string", "src/libopensc/asn1.c"),
    "CVE-2019-5052": ("PCX loader allocation arithmetic", "IMG_pcx.c"),
}


def arguments() -> argparse.Namespace:
    repository = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=repository)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=repository.parent
        / "single-machine-mrva-artifacts"
        / "runs"
        / "run-system-10-2026-08-24",
    )
    return parser.parse_args()


def result_uris(sarif_path: Path) -> set[str]:
    sarif = json.loads(sarif_path.read_text())
    uris = set()
    for run in sarif.get("runs", []):
        for result in run.get("results", []):
            for location in result.get("locations", []):
                uri = location.get("physicalLocation", {}).get("artifactLocation", {}).get("uri")
                if uri:
                    uris.add(uri)
            for code_flow in result.get("codeFlows", []):
                for thread_flow in code_flow.get("threadFlows", []):
                    for step in thread_flow.get("locations", []):
                        uri = (
                            step.get("location", {})
                            .get("physicalLocation", {})
                            .get("artifactLocation", {})
                            .get("uri")
                        )
                        if uri:
                            uris.add(uri)
    return uris


def main() -> int:
    args = arguments()
    report_path = (
        args.repository / "cga" / "analysis" / "run-system-10-2026-08-24" / "report.json"
    )
    report = json.loads(report_path.read_text())
    rows = []
    for submission in report["submissions"]:
        cve_slug = submission["name"].removeprefix("e2e-")
        spec_path = args.repository / "cga" / "examples" / "cves" / cve_slug / "spec.json"
        spec = json.loads(spec_path.read_text())["cves"][0]
        if spec["id"] in INITIAL_SAMPLE:
            continue

        counts = {}
        vulnerable_or_patched_uris = set()
        for job in submission["jobs"]:
            match = VARIANT_MODE.search(job["repository"])
            if not match:
                raise RuntimeError(f"cannot parse variant and mode from {job['repository']}")
            variant, mode = match.groups()
            counts[(variant, mode)] = job["finding_count"]
            if variant in {"vulnerable", "patched"}:
                sarif_name = Path(job["artifacts"]["sarif"]).name
                sarif_path = args.artifact_root / "ingest" / submission["name"] / sarif_name
                vulnerable_or_patched_uris.update(result_uris(sarif_path))

        fault_site, fault_file = FAULT_SITES[spec["id"]]
        vulnerable_fault_file = (
            args.repository
            / "cga"
            / "examples"
            / "cves"
            / cve_slug
            / "tmp"
            / "vulnerable"
            / "source"
            / fault_file
        )
        if not vulnerable_fault_file.is_file():
            raise RuntimeError(f"known fault file is absent: {vulnerable_fault_file}")
        matching_uris = sorted(uri for uri in vulnerable_or_patched_uris if uri.endswith(fault_file))
        row = {
            "cve": spec["id"],
            "source_package": spec["debian"]["source_package"],
            "query_id": spec["queries"][0]["id"],
            "vulnerable_none": counts[("vulnerable", "none")],
            "vulnerable_trace": counts[("vulnerable", "trace")],
            "patched_none": counts[("patched", "none")],
            "patched_trace": counts[("patched", "trace")],
            "current_none": counts[("most-recent", "none")],
            "current_trace": counts[("most-recent", "trace")],
            "total_results": sum(counts.values()),
            "known_fault_site": fault_site,
            "known_fault_file": fault_file,
            "fault_file_in_vulnerable_or_patched_result_path": ";".join(matching_uris) or "no",
            "assessment": "not-found",
        }
        rows.append(row)

    if {row["cve"] for row in rows} != set(FAULT_SITES):
        raise RuntimeError("remaining-case set does not match FAULT_SITES")
    rows.sort(key=lambda row: row["cve"])
    writer = csv.DictWriter(
        sys.stdout, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

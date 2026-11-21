#!/usr/bin/env python3
"""Generate consistent CVE examples from the verified catalogue."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOGUE = ROOT / "catalogue.json"
CODEQL_ROOT = Path(
    "/opt/codeql-v2.23.9/codeql/qlpacks/codeql/cpp-queries/1.5.8"
)


def load_catalogue() -> dict:
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))


def query_relative(source: Path, cwe: str) -> Path:
    destination = ROOT / "queries" / cwe / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination.relative_to(ROOT)


def source_variant(item: dict, name: str) -> dict:
    source = item["sources"][name]
    return {
        "name": {
            "vulnerable": "vulnerable",
            "fixed": "patched",
            "current": "most-recent",
        }[name],
        "version": source["version"],
        "source": {
            "strategy": "debian-dsc",
            "url": source["archive_dsc_url"],
        },
    }


def spec(item: dict, query_path: Path) -> dict:
    query_source = ROOT / query_path
    relative_query = Path("..") / query_path
    return {
        "version": 1,
        "cves": [{
            "id": item["cve"],
            "url": f"https://www.cve.org/CVERecord?id={item['cve']}",
            "debian": {
                "source_package": item["package"],
                "tracker": item["debian_tracker_url"],
            },
            "language": "cpp",
            "variants": [
                source_variant(item, "vulnerable"),
                source_variant(item, "fixed"),
                source_variant(item, "current"),
            ],
            "build": {
                "dependencies": [[
                    "apt-get", "build-dep", "-y", item["package"],
                ]],
                "command": "dpkg-buildpackage -b -uc -us",
            },
            "queries": [{
                "id": item["codeql_query"]["id"],
                "name": item["codeql_query"]["id"],
                "filename": query_source.name,
                "path": str(relative_query),
            }],
        }],
    }


def source_rows(item: dict) -> str:
    rows = []
    for name, label in (
        ("vulnerable", "vulnerable"),
        ("fixed", "fixed"),
        ("current", "current"),
    ):
        source = item["sources"][name]
        rows.append(
            f"| {label} | `{source['version']}` | "
            f"[`{source['dsc_filename']}`]({source['archive_dsc_url']}) |"
        )
    return "\n".join(rows)


def readme(item: dict, query_path: Path) -> str:
    cve = item["cve"]
    query_link = Path("..") / query_path
    return f"""# {cve}: {item["package"]}

{item["description"]}

## Classification

- **CWE:** [{item["cwe"]}](https://cwe.mitre.org/data/definitions/{item["cwe"].split("-")[1]}.html)
- **Path-problem rationale:** {item["codeql_query"]["path_problem_rationale"]}
- **Buildability:** {item["buildability_assessment"]}

## References

- [CVE record](https://www.cve.org/CVERecord?id={cve})
- [Debian CVE tracker]({item["debian_tracker_url"]})
- [Local CVE specification](spec.json)
- [CVE-associated CodeQL query]({query_link.as_posix()})
- Installed query ID: `{item["codeql_query"]["id"]}`

## Debian source references

| Variant | Debian source version | Source archive |
| --- | --- | --- |
{source_rows(item)}

The vulnerable version is the highest ordinary snapshot source version below
Debian's fixed boundary, compared with `dpkg --compare-versions`.

## Source staging

Download and extract the three source archives without building:

```sh
./download-sources.sh
```

Artifacts and extracted trees are written under `tmp/`:

```text
tmp/
  vulnerable/{{archives,source}}
  fixed/{{archives,source}}
  current/{{archives,source}}
```

The `tmp/` tree is intentionally ignored by Git.
"""


def download_script(cve: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
exec python3 "${{HERE}}/../download-sources.py" --cve {cve} "$@"
"""


def overview(doc: dict) -> str:
    items = doc["catalogue"]
    cwes = doc["summary"]["by_cwe"]
    cwe_rows = "\n".join(
        f"| {cwe} | {count} |" for cwe, count in sorted(cwes.items())
    )
    cve_rows = "\n".join(
        f"| [{item['cve']}]({item['cve'].lower()}/README.md) | "
        f"`{item['package']}` | {item['cwe']} | "
        f"`{item['codeql_query']['id']}` |"
        for item in items
    )
    return f"""# C/C++ path-problem CVE catalogue

This catalogue contains {len(items)} verified Debian CVEs whose vulnerability
class is represented by an installed CodeQL C/C++ `@kind path-problem` query.
Every sample records vulnerable, fixed, and current Debian source versions and
stages all three source packages without building them.

The machine-readable research result is [`catalogue.json`](catalogue.json).
Regenerate sample metadata with `./generate.py`; download every source set with
`./download-sources.py`.

The shared query files under [`queries/`](queries/) are copied from the
installed CodeQL 2.23.9 C/C++ query pack. Each sample links to its exact query
and records the query ID in `spec.json`.

## Coverage

| CWE | CVEs |
| --- | ---: |
{cwe_rows}

## Samples

| CVE | Debian source package | CWE | CodeQL query |
| --- | --- | --- | --- |
{cve_rows}

## Existing location-only baseline

The earlier [CVE-2016-9843](cve-2016-9843/README.md) example is retained for
comparison. Its query identifies a review location rather than a source-to-sink
path, so it is not counted in the path-problem catalogue above.
"""


def main() -> None:
    doc = load_catalogue()
    readmes = []
    for item in doc["catalogue"]:
        query_source = Path(item["codeql_query"]["absolute_path"])
        if not query_source.is_file():
            raise SystemExit(f"CodeQL query not found: {query_source}")
        query_path = query_relative(query_source, item["cwe"])
        directory = ROOT / item["cve"].lower()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "spec.json").write_text(
            json.dumps(spec(item, query_path), indent=2) + "\n",
            encoding="utf-8",
        )
        readme_path = directory / "README.md"
        readme_path.write_text(
            readme(item, query_path), encoding="utf-8"
        )
        readmes.append(readme_path)
        script = directory / "download-sources.sh"
        script.write_text(download_script(item["cve"]), encoding="utf-8")
        script.chmod(0o755)
    overview_path = ROOT / "README.md"
    overview_path.write_text(overview(doc), encoding="utf-8")
    readmes.append(overview_path)

    prettier = shutil.which("prettier")
    if prettier is None:
        raise SystemExit("prettier is required to format generated Markdown")
    subprocess.run(
        [
            prettier,
            "--prose-wrap",
            "always",
            "--print-width",
            "80",
            "--write",
            *(str(path) for path in readmes),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()

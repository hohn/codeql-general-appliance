#!/usr/bin/env python3
"""Fixed, networked preparation-to-serving check using the SQLite teaching repo."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
from urllib.request import urlopen


COLLECTION = Path(__file__).resolve().parents[2]
CGA = COLLECTION / "cga"
SOURCE = "https://github.com/hohn/codeql-dataflow-sql-injection.git"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="new external artifact directory")
    parser.add_argument("--use-llm", action="store_true")
    args = parser.parse_args()
    root = args.directory.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment.setdefault("CODEQL_JAVA_HOME", "/usr")
    environment.pop("CGA_WORKFLOW_ACTIVE", None)
    environment.pop("CGA_DIR", None)
    preparation = root / "preparation"
    analysis = root / "analysis"

    def cga(directory, *arguments, capture=False):
        configured = environment.copy()
        configured.setdefault("CGA_TMPDIR", str(directory / ".cga/tmp/artifacts"))
        return subprocess.run(
            [str(CGA), "-C", str(directory), *map(str, arguments)],
            env=configured, check=True, text=True,
            stdout=subprocess.PIPE if capture else None,
        )

    for directory in (preparation, analysis):
        subprocess.run(
            [str(CGA), "init", str(directory)], env=environment, check=True)
        cga(directory, "chain", "start", "--name", "sqlite-toy")
    supervision = ["--use-llm"] if args.use_llm else []
    cga(preparation, "a", "d", "fetch", "--git", SOURCE,
        "--ref", "toy=master", "--language", "cpp", *supervision)
    build = ["a", "d", "build", "--mode", "bm-none", "--mode", "trace", *supervision]
    if not args.use_llm:
        build += ["--command", "./build.sh"]
    cga(preparation, *build)
    # A resumed command verifies completed artifacts instead of rebuilding them.
    cga(preparation, *build)
    cga(preparation, "a", "d", "index")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    local_collection = root / "collection"
    cga(preparation, "a", "d", "export", local_collection)
    cga(preparation, "catalog", "verify", "--catalog", local_collection / "metadata.sql",
        "--manifest", local_collection / "manifest.json")
    collection = root / "http-collection"
    url = f"http://127.0.0.1:{port}"
    cga(preparation, "a", "d", "export", collection, "--base-url", url)
    cga(preparation, "catalog", "verify", "--catalog", collection / "metadata.sql",
        "--manifest", collection / "manifest.json")
    with sqlite3.connect(collection / "metadata.sql") as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute("SELECT * FROM metadata")]
    assert len(rows) == 2, rows
    assert len({row["git_repo"] for row in rows}) == 2, rows
    manifest = json.loads((collection / "manifest.json").read_text())
    assert {item["mode"] for item in manifest["databases"]} == {"none", "trace"}
    for item in manifest["databases"]:
        if item["mode"] == "trace":
            assert item["trace_verification"]["intercepted_processes"] > 0
        if args.use_llm:
            assert item["supervision"]["attempts"][-1]["status"] == "succeeded"
    cga(preparation, "ds", "start", "--directory", collection,
        "--port", port, "--log", root / "archives.log")
    try:
        cga(preparation, "ds", "check")
        for row in rows:
            assert row["git_repo"] == "codeql-dataflow-sql-injection-" + row["content_hash"]
            with urlopen(row["result_url"]) as response:
                assert hashlib.sha256(response.read()).hexdigest() == row["content_hash"]
        cga(analysis, "dl", "getmeta", url + "/metadata.sql")
        cga(analysis, "dl", "select")
        cga(analysis, "dl", "download", "--output-dir", root / "downloaded")
        state = json.loads(cga(analysis, "--json", "state", "show", capture=True).stdout)
        selection = Path(state["cgadl-selection"])
        if not selection.is_absolute():
            selection = Path(environment.get(
                "CGAST_ROOT", environment.get("CGA_ROOT", str(COLLECTION)))) / selection
        downloaded = json.loads(selection.read_text())["databases"]
        assert {row["git_repo"] for row in downloaded} == {row["git_repo"] for row in rows}
        codeql = environment.get(
            "CGA_DB_CODEQL", environment.get("CGA_PREP_CGADB_CODEQL", "codeql"))
        for index, row in enumerate(rows):
            archive = (root / "downloaded" / row["git_owner"] / row["git_repo"] /
                       f"{row['git_owner']}_{row['git_repo']}_db.zip")
            subprocess.run(
                [codeql, "database", "unbundle", str(archive),
                 f"--target={root / 'unbundled'}", f"--name=db-{index}"],
                env=environment, check=True)
            assert (root / "unbundled" / f"db-{index}" / "codeql-database.yml").is_file()
    finally:
        cga(preparation, "ds", "stop")
    print(f"SQLite toy preparation/serving check passed: {root}")


if __name__ == "__main__":
    main()

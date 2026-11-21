"""Run explicit validation operations against built CodeQL databases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import cgast
import workflow
from command_help import enhance_parser

RECORDS_KEY = "cgadb-records"
RESULTS_KEY = "cgadbvalidate-results"
HISTORY_KEY = "cgadbvalidate-history"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _records(state) -> list[dict]:
    document = workflow.load_json(cgast.require_path(
        state, RECORDS_KEY, "run 'cga db build' first"))
    items = document.get("items")
    if not isinstance(items, list) or not items:
        raise workflow.WorkflowError("cgadb records contains no items")
    return items


def _sarif_count(path: Path) -> int:
    try:
        document = json.loads(path.read_text())
        return sum(
            len(run.get("results", [])) for run in document.get("runs", []))
    except (OSError, ValueError, TypeError) as exc:
        raise workflow.WorkflowError(
            f"cannot count SARIF results in {path}: {exc}") from exc


def cmd_query(state, args) -> None:
    query = Path(args.query).expanduser().resolve()
    if not query.is_file():
        raise workflow.WorkflowError(f"query does not exist: {query}")
    output = Path(args.output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise workflow.WorkflowError(
            f"validation output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    selected = set(args.record)
    records = []
    for record in _records(state):
        repository = f"{record.get('owner')}/{record.get('repo')}"
        if selected and record.get("id") not in selected and repository not in selected:
            continue
        if record.get("status") != "built":
            raise workflow.WorkflowError(
                f"database record is not built: {repository}")
        records.append(record)
    if not records:
        raise workflow.WorkflowError("no database records selected")
    codeql = os.environ.get(
        "CGA_DB_CODEQL",
        os.environ.get("CGA_PREP_CGADB_CODEQL", "codeql"))
    results = []
    for record in records:
        sarif = output / f"{record['id']}.sarif"
        workflow.run([
            codeql, "database", "analyze", record["database"], str(query),
            "--format=sarif-latest", f"--output={sarif}", "--rerun",
        ], cwd=query.parent)
        result = {
            "schema": "cga.database-validation.v1",
            "record_id": record["id"],
            "repository": f"{record['owner']}/{record['repo']}",
            "operation": "query",
            "status": "passed",
            "query": str(query),
            "query_sha256": digest(query),
            "sarif": str(sarif),
            "sarif_sha256": digest(sarif),
            "findings": _sarif_count(sarif),
        }
        results.append(result)
        cgast.info(
            f"  VALID   {result['repository']}: "
            f"{result['findings']} finding(s)")
    result_path = output / "validations.json"
    workflow.write_json(result_path, {
        "schema": "cga.database-validations.v1",
        "count": len(results),
        "items": results,
    })
    cgast.set_path(state, RESULTS_KEY, result_path)
    state.setdefault(HISTORY_KEY, []).append({
        "results": cgast.rel(result_path),
        "operation": "query",
        "count": len(results),
    })
    cgast.info(f"cgadbvalidate: results -> {cgast.rel(result_path)}")


def cmd_info(state, _args) -> None:
    path = cgast.get_path(state, RESULTS_KEY)
    cgast.info(
        f"cgadbvalidate: results={cgast.rel(path) if path else '(none)'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cga db validate")
    sub = parser.add_subparsers(dest="command", required=True)
    query = sub.add_parser("query")
    query.add_argument("--query", required=True)
    query.add_argument("--output-dir", required=True)
    query.add_argument("--record", action="append", default=[])
    query.set_defaults(func=cmd_query)
    sub.add_parser("info").set_defaults(func=cmd_info)
    return enhance_parser(parser, "db validate")


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    state = cgast.read()
    try:
        args.func(state, args)
    except workflow.WorkflowError as exc:
        cgast.die(f"cgadbvalidate: {exc}", 2)
    cgast.write(state)
    return 0

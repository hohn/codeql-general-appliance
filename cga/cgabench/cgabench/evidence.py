"""Read-only SQL browsing of one session's accepted evidence."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import cgast
from cgasi import store
from workflow import WorkflowError, load_json

from . import model

TABLES = {
    "D": ("databases", {
        "ordinal": "BIGINT", "repository": "VARCHAR", "language": "VARCHAR",
        "archive": "VARCHAR", "sha256": "VARCHAR",
    }),
    "Q": ("queries", {
        "ordinal": "BIGINT", "id": "VARCHAR", "name": "VARCHAR",
        "language": "VARCHAR", "path": "VARCHAR", "kind": "VARCHAR",
    }),
    "R": ("result_summaries", {
        "ordinal": "BIGINT", "repository": "VARCHAR", "finding_count": "BIGINT",
    }),
}


def entries(item: dict, stage: str) -> list[dict]:
    artifact = item[stage].get("artifact")
    if not artifact:
        return []
    if stage == "D":
        return artifact["archives"]
    if stage == "Q":
        return load_json(cgast.resolve(artifact["cgaql-selection"]))["queries"]
    if stage == "R":
        return [{"repository": job["repository"], "finding_count": job["finding_count"]}
                for job in artifact.get("ingestion", {}).get("jobs", [])]
    raise WorkflowError("evidence stage must be D, Q, or R")


def browse(state: dict, document: dict) -> dict:
    if document.get("session") is None:
        raise WorkflowError("select a session first")
    item = model.session(state, document["session"])
    stage = document.get("stage")
    if not isinstance(stage, str) or stage not in TABLES:
        raise WorkflowError("evidence stage must be D, Q, or R")
    artifact = item[stage].get("artifact")
    if artifact:
        path_key, hash_key = {
            "D": ("cgadl-selection", "sha256"),
            "Q": ("cgaql-selection", "selection_sha256"),
            "R": ("results", "sha256"),
        }[stage]
        if model.fingerprint(cgast.resolve(artifact[path_key])) != artifact[hash_key]:
            raise WorkflowError(f"session {stage} evidence snapshot has changed")
    values = [
        {**entry, "ordinal": ordinal}
        for ordinal, entry in enumerate(entries(item, stage), 1)
    ]
    if stage == "D":
        for value in values:
            value["language"] = artifact["language"]
    table, columns = TABLES[stage]
    default_sql = f"SELECT * FROM {table} ORDER BY ordinal"
    duckdb = shutil.which("duckdb")
    if not duckdb:
        raise WorkflowError("required command not found: duckdb")
    with tempfile.TemporaryDirectory(prefix="cgabench-evidence-") as directory:
        root = Path(directory)
        source, database = root / "rows.json", root / "evidence.duckdb"
        source.write_text(json.dumps(values), encoding="utf-8")
        def quote(text: str) -> str:
            return "'" + text.replace("'", "''") + "'"

        types = ", ".join(f"{quote(key)}: {quote(value)}" for key, value in columns.items())
        statement = (
            f"CREATE TABLE {table} AS SELECT * FROM read_json("
            f"{quote(str(source))}, columns = {{{types}}})")
        try:
            proc = subprocess.run(
                [duckdb, "-no-init", "-bail", str(database), "-c", statement],
                text=True, capture_output=True, timeout=15)
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError("preparing evidence SQL exceeded 15 seconds") from exc
        if proc.returncode:
            raise WorkflowError(f"cannot prepare evidence SQL: {proc.stderr.strip()}")
        try:
            page = store.query_page(
                database, document.get("sql", default_sql),
                document.get("offset", 0), document.get("limit", 30))
        except store.StoreError as exc:
            raise WorkflowError(f"cannot query session evidence: {exc}") from exc
    return {**page, "session": item["index"], "stage": stage,
            "table": table, "source_columns": list(columns), "default_sql": default_sql,
            "item_count": len(values), "status": item[stage]["status"]}

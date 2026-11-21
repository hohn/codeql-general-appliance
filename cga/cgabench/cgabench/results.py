"""Session-scoped, read-only browsing of already ingested cgasi results."""

from __future__ import annotations

import json
from pathlib import Path

import cgast
from cgasi import store
from workflow import WorkflowError

from . import model

FILTERS = ("file_name", "rule_id", "kind", "uri", "start_line")
DISPLAY = ("repository", "rule_id", "rule_name", "kind", "uri",
           "start_line", "start_column", "message")


def context(item: dict) -> dict:
    artifact = item["R"].get("artifact")
    if item["R"]["status"] != "complete" or not artifact:
        raise WorkflowError("results are not complete; advance this session first")
    if model.fingerprint(cgast.resolve(artifact["results"])) != artifact["sha256"]:
        raise WorkflowError("completed result snapshot has changed")
    db = cgast.get_path(item["engine"], "cgasi-db")
    if not db or not db.is_file():
        raise WorkflowError("session cgasi database is missing; restore its retained artifacts")
    jobs = artifact.get("ingestion", {}).get("jobs", [])
    return {"database": str(db), "snapshot": str(cgast.resolve(artifact["results"])),
            "jobs": jobs}


def browse(state: dict, document: dict) -> dict:
    if document.get("session") is None:
        raise WorkflowError("select a session first")
    item = model.session(state, document["session"])
    details = context(item)
    db = Path(details["database"])
    filters = document.get("filters", {})
    if not isinstance(filters, dict) or any(
            key not in FILTERS or not isinstance(value, str)
            for key, value in filters.items()):
        raise WorkflowError("filters must map supported finding columns to exact-match strings")
    sql = document.get("sql")
    if sql is not None and filters:
        raise WorkflowError("use either exact-match filters or SQL, not both")
    try:
        if sql is None:
            sql = store.selection_sql(
                db, [(key, value) for key, value in filters.items() if value],
                include_result=True)
        page = store.query_page(db, sql, document.get("offset", 0),
                                document.get("limit", 30))
    except store.StoreError as exc:
        raise WorkflowError(f"cannot query session results: {exc}") from exc
    repositories = [
        {"file_name": Path(job["artifacts"]["sarif"]).name,
         "repository": job["repository"],
         "finding_count": job["finding_count"],
         "sqlite": str(cgast.resolve(job["artifacts"]["sqlite"]))}
        for job in details["jobs"]]
    if document.get("sql") is None:
        by_file = {job["file_name"]: job["repository"] for job in repositories}
        for row in page["rows"]:
            try:
                result = json.loads(row.pop("result_json"))
            except (TypeError, json.JSONDecodeError) as exc:
                raise WorkflowError("ingested finding contains invalid SARIF JSON") from exc
            message = result.get("message", {})
            row["message"] = message.get("text") or message.get("markdown") or ""
            row["repository"] = by_file.get(row["file_name"], row["file_name"])
        page["columns"] = list(DISPLAY)
    return {**page, "session": item["index"],
            "mode": "sql" if document.get("sql") is not None else "search",
            "finding_count": item["R"]["artifact"]["finding_count"],
            "database": details["database"], "repositories": repositories}

"""Bounded MRVA advancement with recoverable operation checkpoints."""

from __future__ import annotations

import copy
import fcntl
import json
import subprocess
from pathlib import Path

import cgast
from cgawf.repository import utc_now
from workflow import WorkflowError, load_json

from . import compare, model

COLLECTION = Path(__file__).resolve().parents[2]
TOOLS = {"dl": "cgadl", "ql": "cgaql", "mr": "cgamr", "si": "cgasi", "mx": "cgamx"}
WORKSPACE_COMMANDS = {
    "D": {"getmeta", "keys", "values", "list", "select", "sql", "download", "info"},
    "Q": {"index", "keys", "values", "list", "select", "sql", "pack", "info"},
}


def run_tool(state: dict, tool: str, arguments: list[str], *, report: dict | None = None) -> dict:
    binary = COLLECTION / TOOLS[tool] / "bin" / TOOLS[tool]
    proc = subprocess.run([str(binary), *arguments], input=json.dumps(state),
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.stderr:
        cgast.info(proc.stderr.rstrip())
    if report is not None:
        report["tool_output"] = proc.stderr[:20000]
        report["tool_output_truncated"] = len(proc.stderr) > 20000
    if proc.returncode:
        raise WorkflowError(f"{TOOLS[tool]} {' '.join(arguments)} failed "
                            f"(exit {proc.returncode}): {proc.stderr.strip()}")
    try:
        output = json.loads(proc.stdout)
    except ValueError as exc:
        raise WorkflowError(f"{TOOLS[tool]} returned invalid CGAST") from exc
    if not isinstance(output, dict):
        raise WorkflowError(f"{TOOLS[tool]} returned a non-object CGAST")
    return output


def tool(item: dict, stage: str, arguments: list[str]) -> None:
    model.editable(item)
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    expected = "dl" if stage == "D" else "ql"
    if (len(arguments) < 2 or arguments[0] != expected
            or arguments[1] not in WORKSPACE_COMMANDS[stage]):
        raise WorkflowError(f"{stage} workspace expects -- {expected} "
                            f"({'|'.join(sorted(WORKSPACE_COMMANDS[stage]))}) ...")
    workspace = copy.deepcopy(item["workspace"])
    if arguments[1] in ("select", "sql"):
        workspace.pop("cgadl-dbdir" if stage == "D" else "cgaql-pack", None)
    item["workspace"] = run_tool(workspace, expected, arguments[1:], report=item)
    item[stage]["history"].append({"at": utc_now(), "action": "tool",
                                   "command": arguments})


def synchronize(item: dict) -> None:
    checkpoint = item.get("checkpoint")
    if not checkpoint:
        return
    record = load_json(cgast.resolve(checkpoint))
    if record.get("submission") != item["submission"]:
        raise WorkflowError("checkpoint belongs to a different bench session")
    if not record["engine"].get("cgamr-submissions") and record.get("operation") != "submit":
        return
    for stage in ("D", "Q"):
        item[stage] = record[stage]
    item["engine"] = record["engine"]
    for stage in ("J", "R"):
        item[stage] = record[stage]
    if record.get("completed_at"):
        item["completed_at"] = record["completed_at"]
    model.refresh(item)


def advance(state: dict, item: dict) -> None:
    synchronize(item)
    model.validate_session(state, item)
    model.refresh(item)
    if not item["D"]["artifact"] or not item["Q"]["artifact"]:
        return
    if not item.get("checkpoint"):
        path = cgast.new_tempfile(prefix="cgabench-checkpoint-", suffix=".json")
        item["checkpoint"] = cgast.rel(path)
        model.checkpoint(item)
    path = cgast.resolve(item["checkpoint"])
    with path.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        synchronize(item)
        model.validate_session(state, item, complete=True)
        if item["R"]["status"] == "complete":
            return
        record = load_json(path)
        if record.get("operation") == "submit":
            raise WorkflowError("submission outcome is uncertain: inspect the MRVA "
                                "server before starting a new session; automatic resubmit refused")
        if item["engine"].get("cgamr-submissions", {}).get(item["submission"], {}).get(
                "status") in {"failed", "cancelled", "canceled", "timed_out"}:
            return
        engine = item["engine"]
        name = item["submission"]

        def operation(label: str, stage: str, component: str, args: list[str]) -> None:
            item[stage].update(status="running", requirement=f"executing {label}", actions=[])
            model.checkpoint(item, label)
            try:
                item["engine"] = run_tool(item["engine"], component, args)
            except (WorkflowError, OSError) as exc:
                item[stage].update(status="failed", requirement=str(exc),
                                   actions=["advance"])
                item[stage]["history"].append({
                    "at": utc_now(), "action": label, "error": str(exc)})
                model.checkpoint(item, label if label == "submit" else None, str(exc))
                raise
            item[stage]["history"].append({"at": utc_now(), "action": label})
            model.checkpoint(item)

        if not engine.get("cgamr-submissions"):
            database, query = item["D"]["artifact"], item["Q"]["artifact"]
            model.verify_input("D", database)
            model.verify_input("Q", query)
            item["engine"] = {
                "cgadl-selection": database["cgadl-selection"],
                "cgadl-dbdir": database["cgadl-dbdir"],
                "cgaql-selection": query["cgaql-selection"],
                "cgaql-pack": query["cgaql-pack"],
            }
            args = ["submit", "--name", name, "--user", item["user"]]
            if item.get("server"):
                args += ["--server", item["server"]]
            operation("submit", "J", "mr", args)
        operation("status", "J", "mr", ["status", "--name", name])
        submission = item["engine"]["cgamr-submissions"][name]
        status = submission["status"]
        item["J"]["artifact"] = copy.deepcopy(submission)
        if status != "succeeded":
            failed = status in {"failed", "cancelled", "canceled", "timed_out"}
            item["J"].update(
                status="failed" if failed else "running",
                requirement=f"MRVA {status}; " + ("create a new session" if failed
                                                 else "advance to check again"),
                actions=[] if failed else ["advance"])
            model.checkpoint(item)
            model.refresh(item)
            return
        item["J"].update(status="complete", requirement="", actions=[])
        model.checkpoint(item)
        downloads = submission.get("downloads", [])
        repositories = submission["repositories"]
        if len(downloads) != len(repositories) or any(
                not cgast.resolve(path).is_file() for path in downloads):
            operation("download", "R", "mr", ["download", "--name", name])
            submission = item["engine"]["cgamr-submissions"][name]
        # cgamr follows server status order; cgasi pairs downloads with the
        # original repository order. Restore that order before ingestion.
        downloads_by_name = {
            Path(path).name: path for path in submission.get("downloads", [])}
        submission["downloads"] = [
            downloads_by_name[repository.replace("/", "-") + ".zip"]
            for repository in repositories
            if repository.replace("/", "-") + ".zip" in downloads_by_name]
        model.checkpoint(item)
        operation("verify", "R", "mr", ["verify", name])
        if name not in item["engine"].get("cgasi-ingestions", {}):
            operation("ingest", "R", "si", ["ingest", "--name", name])
        try:
            finding_rows = compare.findings(item["engine"], name)
            for finding in finding_rows:
                finding["provenance"].update(
                    bench_session=item["index"], bench_name=item["name"],
                    user=item["user"], submission=name,
                    mrva_session=submission["session_id"])
            out = cgast.new_tempfile(prefix="cgabench-results-", suffix=".json")
            ingestion = copy.deepcopy(item["engine"]["cgasi-ingestions"][name])
            model.save(out, {"version": 1, "session": item["index"],
                             "name": item["name"], "user": item["user"],
                             "findings": finding_rows, "ingestion": ingestion})
        except (WorkflowError, OSError, ValueError, KeyError, TypeError) as exc:
            item["R"].update(status="failed", requirement=str(exc), actions=["advance"])
            model.checkpoint(item, error=str(exc))
            raise WorkflowError(f"cannot freeze results: {exc}") from exc
        item["J"]["artifact"] = copy.deepcopy(
            item["engine"]["cgamr-submissions"][name])
        item["R"].update(status="complete", requirement="", actions=[],
                        artifact={"results": cgast.rel(out), "ingestion": ingestion,
                                  "finding_count": len(finding_rows),
                                  "sha256": model.fingerprint(out)})
        item["R"]["history"].append({"at": utc_now(), "action": "complete",
                                     "artifact": copy.deepcopy(item["R"]["artifact"])})
        item["completed_at"] = utc_now()
        model.checkpoint(item)
        model.refresh(item)

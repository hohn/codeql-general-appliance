"""Experiment state, fixed cell addresses, and artifact acceptance."""

from __future__ import annotations

import copy
import hashlib
import re
import uuid
from pathlib import Path

import cgast
from cgawf.repository import atomic_write, canonical_json, utc_now
from workflow import WorkflowError, load_json, require_safe_name
from vid_registry import reference

KEY = "cgabench-experiment"
STAGES = ("D", "Q", "J", "R")
MODES = {"query-changes": "D", "database-changes": "Q"}


def save(path: Path, value: dict) -> None:
    atomic_write(path, canonical_json(value))


def experiment(state: dict) -> dict:
    value = state.get(KEY)
    if (not isinstance(value, dict) or value.get("version") != 1
            or not isinstance(value.get("sessions"), list)):
        raise WorkflowError("initialize an experiment with 'cga bench init'")
    if value.get("mode") not in (None, *MODES):
        raise WorkflowError("invalid experiment mode")
    for index, item in enumerate(value["sessions"], 1):
        if (not isinstance(item, dict) or item.get("index") != index
                or any(not isinstance(item.get(stage), dict) for stage in STAGES)):
            raise WorkflowError(f"invalid bench session at S[{index}]")
    return value


def cell() -> dict:
    return {"status": "empty", "artifact": None, "requirement": "",
            "actions": [], "history": []}


def init(state: dict, name: str, mode: str | None = None) -> None:
    if KEY in state:
        raise WorkflowError("this CGAST already contains an experiment")
    require_safe_name(name, "experiment name")
    if mode is not None and mode not in MODES:
        raise WorkflowError("mode must be query-changes or database-changes")
    state[KEY] = {"version": 1, "name": name, "id": uuid.uuid4().hex,
                  "created_at": utc_now(), "sessions": [], "active": None,
                  "mode": mode, "reference": 1,
                  "C": {"status": "empty", "inputs": [], "history": []}}


def fixed_stage(state: dict) -> str:
    mode = experiment(state).get("mode")
    if mode not in MODES:
        raise WorkflowError("select an experiment mode with 'cga bench mode "
                            "query-changes|database-changes' before changing sessions")
    return MODES[mode]


def input_identity(stage: str, artifact: dict) -> dict:
    if stage == "D":
        return {"language": artifact["language"], "selection": artifact["sha256"],
                "archives": sorted([entry["repository"], entry["sha256"]]
                                   for entry in artifact["archives"])}
    return {"language": artifact["language"], "selection": artifact["selection_sha256"],
            "pack": artifact["sha256"]}


def verify_input(stage: str, artifact: dict) -> None:
    if stage == "D":
        files = [(artifact["cgadl-selection"], artifact["sha256"],
                  "accepted selection metadata changed")]
        files += [(entry["archive"], entry["sha256"],
                   "accepted database archive changed; create a new experiment")
                  for entry in artifact["archives"]]
    else:
        files = [(artifact["cgaql-selection"], artifact["selection_sha256"],
                  "accepted selection metadata changed"),
                 (artifact["cgaql-pack"][0], artifact["sha256"],
                  "accepted query pack changed")]
    for path, digest, error in files:
        if fingerprint(cgast.resolve(path)) != digest:
            raise WorkflowError(error)


def validate_database_identities(state: dict, archives: list[dict]) -> None:
    known = {}
    for item in experiment(state)["sessions"]:
        for record in item["D"]["history"]:
            for archive in (record.get("artifact") or {}).get("archives", []):
                known[archive["repository"]] = archive["sha256"]
    for archive in archives:
        previous = known.get(archive["repository"])
        if previous and previous != archive["sha256"]:
            raise WorkflowError(f"database identity {archive['repository']} has changed contents; "
                                "repository names must include a content hash")


def validate_fixed(exp: dict, stage: str, items: list[dict]) -> None:
    baseline = exp["sessions"][0][stage]["artifact"] if exp["sessions"] else None
    for item in items:
        artifact = item[stage]["artifact"]
        if item["index"] > 1 and artifact and (
                baseline is None
                or input_identity(stage, artifact) != input_identity(stage, baseline)):
            raise WorkflowError(f"S[{item['index']}].{stage} differs from S1's fixed input; "
                                "start a separate experiment")


def set_mode(state: dict, mode: str) -> None:
    exp = experiment(state)
    if mode not in MODES:
        raise WorkflowError("mode must be query-changes or database-changes")
    if exp.get("mode") and exp["mode"] != mode and exp["sessions"]:
        raise WorkflowError("experiment mode cannot change after sessions exist")
    stage = MODES[mode]
    validate_fixed(exp, stage, exp["sessions"])
    for item in exp["sessions"]:
        if item[stage]["artifact"]:
            verify_input(stage, item[stage]["artifact"])
    exp.update(mode=mode, reference=1)


def input_editable(state: dict, item: dict, stage: str) -> None:
    fixed = fixed_stage(state)
    editable(item)
    if stage == fixed:
        if item["index"] > 1:
            raise WorkflowError(f"{stage} is fixed; use Clone from a prior session, not Edit")
        if item[stage]["artifact"] and len(experiment(state)["sessions"]) > 1:
            raise WorkflowError(f"S1's fixed {stage} input is locked after variants exist")


def validate_session(state: dict, item: dict, *, complete: bool = False) -> None:
    stage = fixed_stage(state)
    validate_fixed(experiment(state), stage, [item])
    if item["index"] > 1 and not item[stage]["artifact"]:
        raise WorkflowError(f"clone S1's fixed {stage} input before running S[{item['index']}]")
    if complete and any(not item[value]["artifact"] for value in ("D", "Q")):
        raise WorkflowError(f"S[{item['index']}] needs accepted D and Q inputs")
    database, query = item["D"]["artifact"], item["Q"]["artifact"]
    if database and query and database["language"] != query["language"]:
        raise WorkflowError("database and accepted query languages differ")


def clone_input(state: dict, index: int, stage: str, source: int) -> tuple[dict, dict]:
    if stage != fixed_stage(state):
        raise WorkflowError("Clone is available only for the experiment's fixed D/Q input")
    if not isinstance(source, int) or isinstance(source, bool) or not 1 <= source < index:
        raise WorkflowError("clone source must be a prior session; S1 establishes both inputs")
    parent = session(state, source)
    artifact = parent[stage]["artifact"]
    if not artifact:
        raise WorkflowError(f"accept S[{source}].{stage} before cloning it")
    validate_fixed(experiment(state), stage, [parent])
    verify_input(stage, artifact)
    return copy.deepcopy(artifact), {
        "session": source, "stage": stage, "identity": input_identity(stage, artifact)}


def clone(state: dict, index: int | None, stage: str, source: int) -> dict:
    item = session(state, index)
    editable(item)
    artifact, provenance = clone_input(state, item["index"], stage, source)
    other = item["Q" if stage == "D" else "D"]["artifact"]
    if other and other["language"] != artifact["language"]:
        raise WorkflowError("cloned and accepted input languages differ")
    accept(item, stage, artifact, cloned_from=provenance)
    experiment(state)["active"] = item["index"]
    return item


def add(state: dict, name: str, user: str, server: str | None) -> dict:
    exp = experiment(state)
    stage = fixed_stage(state)
    require_safe_name(name, "session name")
    require_safe_name(user, "MRVA user")
    if any(item["name"] == name for item in exp["sessions"]):
        raise WorkflowError(f"session name already exists: {name}")
    inherited = clone_input(state, len(exp["sessions"]) + 1, stage, 1) \
        if exp["sessions"] else None
    workspace = {
        key: copy.deepcopy(value) for key, value in state.items()
        if key in {"cgadl-metadata", "cgaql-index", "cgaql-querydir"}
    }
    item = {"index": len(exp["sessions"]) + 1, "name": name, "user": user,
            "created_at": utc_now(), "status": "incomplete",
            "submission": f"bench-{uuid.uuid4().hex}",
            "workspace": workspace, "engine": {}, "checkpoint": None,
            **{stage: cell() for stage in STAGES}}
    if server:
        item["server"] = server
    item["checkpoint"] = cgast.rel(
        cgast.new_tempfile(prefix="cgabench-checkpoint-", suffix=".json"))
    if inherited:
        accept(item, stage, inherited[0], cloned_from=inherited[1])
    else:
        checkpoint(item)
    exp["sessions"].append(item)
    exp["active"] = item["index"]
    refresh(item)
    return item


def session(state: dict, index: int | None) -> dict:
    exp = experiment(state)
    index = index if index is not None else exp["active"]
    if not isinstance(index, int) or isinstance(index, bool) \
            or not 1 <= index <= len(exp["sessions"]):
        raise WorkflowError("select an existing session with --session N (one-based)")
    return exp["sessions"][index - 1]


def editable(item: dict) -> None:
    if item["engine"].get("cgamr-submissions") or item["J"]["status"] == "complete":
        raise WorkflowError("submitted sessions are evidence; create a new session")
    if item.get("checkpoint"):
        checkpoint = load_json(cgast.resolve(item["checkpoint"]))
        if checkpoint.get("engine", {}).get("cgamr-submissions") \
                or checkpoint.get("operation") == "submit":
            raise WorkflowError("submission has started; resume it or create a new session")


def refresh(item: dict) -> None:
    for stage, requirement in (("D", "need accepted database selection"),
                               ("Q", "need accepted query pack")):
        target = item[stage]
        if target["artifact"] is None:
            target["status"] = "blocked" if stage == "D" \
                or item["D"]["artifact"] else "empty"
            target["requirement"] = requirement
            target["actions"] = ["tool", "work", "database" if stage == "D" else "query"]
        else:
            target.update(status="complete", requirement="", actions=[])
    if item["D"]["artifact"] and item["Q"]["artifact"]:
        if item["J"]["status"] in ("empty", "blocked"):
            item["J"].update(status="blocked", requirement="advance to submit accepted inputs",
                             actions=["advance"])
        if item["J"]["status"] == "complete" and item["R"]["status"] == "empty":
            item["R"].update(status="blocked", requirement="advance to collect results",
                             actions=["advance"])
    if item["R"]["status"] == "complete":
        item["status"] = "complete"
    elif any(item[stage]["status"] == "failed" for stage in STAGES):
        item["status"] = "failed"
    elif item["J"]["status"] == "running":
        item["status"] = "running"
    else:
        item["status"] = "incomplete"


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot(source: Path, suffix: str) -> str:
    if not source.is_file():
        raise WorkflowError(f"artifact does not exist: {source}")
    destination = cgast.new_tempfile(prefix="cgabench-", suffix=suffix)
    destination.write_bytes(source.read_bytes())
    return cgast.rel(destination)


def rows(path: Path, key: str) -> list[dict]:
    value = load_json(path).get(key)
    if not isinstance(value, list) or not value \
            or any(not isinstance(row, dict) for row in value):
        raise WorkflowError(f"{path}: expected nonempty {key} array")
    return value


def accept_database(state: dict, item: dict, selection: str | None,
                    dbdir: str | None, source: str) -> None:
    input_editable(state, item, "D")
    inputs = {**state, **item["workspace"]}
    if selection:
        selection = str(Path(selection).expanduser().resolve())
    if dbdir:
        dbdir = str(Path(dbdir).expanduser().resolve())
    selection = selection or inputs.get("cgadl-selection")
    dbdir = dbdir or inputs.get("cgadl-dbdir")
    if not isinstance(selection, str) or not isinstance(dbdir, str):
        raise WorkflowError("database needs --selection FILE and --dbdir DIR, "
                            "or a cgadl selection/download")
    selected = cgast.resolve(selection)
    databases = rows(selected, "databases")
    archives, identities, languages, result_names = [], set(), set(), set()
    for row in databases:
        owner = require_safe_name(row.get("git_owner"), "database owner")
        repo = require_safe_name(row.get("git_repo"), "database repository")
        identity = f"{owner}/{repo}"
        if identity in identities:
            raise WorkflowError(f"duplicate database repository: {identity}")
        identities.add(identity)
        result_name = f"{owner}-{repo}.zip"
        if result_name in result_names:
            raise WorkflowError(f"MRVA result filename collision: {result_name}")
        result_names.add(result_name)
        language = row.get("primary_language")
        if not isinstance(language, str) or not language:
            raise WorkflowError(f"missing database language for {identity}")
        languages.add(language)
        archive = cgast.resolve(dbdir) / owner / repo / f"{owner}_{repo}_db.zip"
        if not archive.is_file():
            raise WorkflowError(f"database archive is missing: {archive}")
        archives.append({"repository": identity, "archive": cgast.rel(archive),
                         "sha256": fingerprint(archive)})
    if len(languages) != 1:
        raise WorkflowError("one session must select exactly one database language")
    language = next(iter(languages))
    query = item["Q"].get("artifact")
    if query and query["language"] != language:
        raise WorkflowError("database and accepted query languages differ")
    validate_database_identities(state, archives)
    frozen_selection = snapshot(selected, ".json")
    artifact = {"cgadl-selection": frozen_selection,
                "sha256": fingerprint(cgast.resolve(frozen_selection)),
                "cgadl-dbdir": cgast.rel(cgast.resolve(dbdir)),
                "language": language, "archives": archives, "source": source}
    accept(item, "D", artifact)


def accept_query(state: dict, item: dict, selection: str | None,
                 pack: str | None, pack_index: int, source: str) -> None:
    input_editable(state, item, "Q")
    inputs = {**state, **item["workspace"]}
    if selection:
        selection = str(Path(selection).expanduser().resolve())
    if pack:
        pack = str(Path(pack).expanduser().resolve())
    selection = selection or inputs.get("cgaql-selection")
    if not isinstance(selection, str):
        raise WorkflowError("query needs --selection FILE or a cgaql selection")
    selected = cgast.resolve(selection)
    queries = rows(selected, "queries")
    language_values = [row.get("language") for row in queries]
    if any(not isinstance(value, str) or not value for value in language_values):
        raise WorkflowError("query selection must have exactly one language")
    languages = set(language_values)
    if len(languages) != 1:
        raise WorkflowError("query selection must have exactly one language")
    packs = inputs.get("cgaql-pack", [])
    if pack is None:
        if not isinstance(packs, list) or not 0 <= pack_index < len(packs):
            raise WorkflowError("query needs --pack FILE or a valid --pack-index")
        if len(queries) != len(packs):
            raise WorkflowError("query selection/pack counts differ; repack the selection")
        # cgaql packs one entry point per bundle; preserve the actual chosen row.
        queries = [queries[pack_index]]
        pack = packs[pack_index]
    if not isinstance(pack, str):
        raise WorkflowError("pack path must be a string")
    language = next(iter(languages))
    database = item["D"].get("artifact")
    if database and database["language"] != language:
        raise WorkflowError("query and accepted database languages differ")
    query_snapshot = cgast.new_tempfile(prefix="cgabench-query-", suffix=".json")
    save(query_snapshot, {"version": 1, "queries": queries, "count": len(queries)})
    packed = snapshot(cgast.resolve(pack), ".tgz")
    artifact = {"cgaql-selection": cgast.rel(query_snapshot),
                "selection_sha256": fingerprint(query_snapshot),
                "cgaql-pack": [packed], "language": language,
                "sha256": fingerprint(cgast.resolve(packed)), "source": source}
    draft = item["workspace"].get("cgabench-query")
    if draft and draft.get("copied_from") and any(
            isinstance(query.get("path"), str)
            and cgast.resolve(query["path"]) == cgast.resolve(draft["editor_path"])
            for query in queries):
        artifact["copied_from"] = copy.deepcopy(draft["copied_from"])
    accept(item, "Q", artifact)


def accept(item: dict, stage: str, artifact: dict, *, cloned_from: dict | None = None) -> None:
    target = item[stage]
    entry = {"at": utc_now(), "action": "clone" if cloned_from else "accept",
             "artifact": copy.deepcopy(artifact)}
    if cloned_from:
        target["cloned_from"] = cloned_from
        entry["cloned_from"] = copy.deepcopy(cloned_from)
    else:
        target.pop("cloned_from", None)
    target["history"].append(entry)
    target["artifact"] = artifact
    item["engine"] = {}
    refresh(item)
    checkpoint(item)


def checkpoint(item: dict, operation: str | None = None, error: str | None = None) -> None:
    save(cgast.resolve(item["checkpoint"]), {
        "submission": item["submission"], "operation": operation, "error": error,
        "engine": item["engine"],
        **{stage: item[stage] for stage in STAGES},
        "completed_at": item.get("completed_at"),
    })


def address(exp: dict, target: str) -> dict:
    if target in ("E", exp["name"]):
        return exp
    if target == "E.C":
        return exp["C"]
    match = re.fullmatch(r"E\.S\[(\d+)\](?:\.([DQJR]))?|E\.([DQJR])\[(\d+)\]", target)
    if not match:
        raise WorkflowError("address must be E, E.C, E.S[N], E.S[N].D/Q/J/R, or E.D/Q/J/R[N]")
    index = int(match[1] or match[4])
    if not 1 <= index <= len(exp["sessions"]):
        raise WorkflowError(f"unknown address: {target}")
    item = exp["sessions"][index - 1]
    return item[match[2] or match[3]] if match[2] or match[3] else item


def projection(state: dict, target: str = "E") -> dict:
    from .engine import synchronize

    value = copy.deepcopy(state)
    exp = experiment(value)
    for item in exp["sessions"]:
        synchronize(item)
        refresh(item)
        item["vid"] = reference("sessions", item["index"])
        for stage in STAGES:
            item[stage]["vid"] = reference("sessions", item["index"], stage)
    exp["vid"] = reference("experiment")
    exp["C"]["vid"] = reference("comparison")
    return address(exp, target)

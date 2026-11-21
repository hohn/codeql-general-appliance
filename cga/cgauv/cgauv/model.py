"""Normalized read-only model for CGA Unified View."""

from __future__ import annotations

from collections import Counter
import json
import hashlib
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from cgawf.repository import Repository, WorkflowError
from cgawf.tags import matches as tags_match, normalize as normalize_tags
from vid import Space
from vid_registry import reference, step_reference


MODEL_SCHEMA = "cga.use.model.v1"
STEP_SCHEMA = "cga.use.step.v1"
OUTLINE_SCHEMA = "cga.use.outline.v1"
SEARCH_SCHEMA = "cga.use.search.v1"
COLLECTION_SCHEMA = "cga.use.collection.v1"
ARTIFACT_SCHEMA = "cga.use.artifact.v1"
MAX_PAGE_SIZE = 200
SEARCH_KINDS = {"step", "attempt", "artifact", "database", "query"}


STAGE_ORDER = (
    ("infrastructure", "Infrastructure"),
    ("inputs", "Input preparation"),
    ("execution", "MRVA execution"),
    ("results", "Result processing and export"),
    ("verification", "Verification"),
)

COMPONENT_PREFIX = {
    "mx": "cgamx",
    "local-mrva": "cgamx",
    "dl": "cgadl",
    "db-lib": "cgadl",
    "ql": "cgaql",
    "query-lib": "cgaql",
    "mr": "cgamr",
    "mrva-request": "cgamr",
    "si": "cgasi",
    "sarif-ingest": "cgasi",
    "ex": "cgaex",
    "export": "cgaex",
}

LABELS = {
    ("mx", "preflight"): "Check infrastructure",
    ("mx", "reset"): "Reset MRVA state",
    ("mx", "build"): "Build MRVA services",
    ("mx", "start"): "Start MRVA services",
    ("mx", "check"): "Verify MRVA logs",
    ("mx", "stop"): "Stop MRVA services",
    ("mx", "cleanup"): "Clean MRVA runtime",
    ("dl", "getmeta"): "Load database catalogue",
    ("dl", "sql"): "Select databases",
    ("dl", "download"): "Download databases",
    ("ql", "index"): "Index query library",
    ("ql", "select"): "Select query",
    ("ql", "pack"): "Build query pack",
    ("mr", "run"): "Run MRVA analysis",
    ("si", "ingest"): "Ingest SARIF results",
    ("si", "verify"): "Verify result store",
    ("ex", "human"): "Export human report",
    ("ex", "llm"): "Export LLM report",
}


def _flow_metadata(repository: Repository) -> dict[str, Any]:
    path = repository.root / "flow-view.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkflowError(f"invalid flow view metadata {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != "cga.flow-view.v1":
        raise WorkflowError(f"unsupported flow view metadata: {path}")
    if not isinstance(value.get("stages"), list):
        raise WorkflowError(f"flow view metadata has no stages: {path}")
    return value


def _rule_matches(rule: dict[str, Any], tool: str, action: str) -> bool:
    tools = rule.get("tool")
    actions = rule.get("action")
    return (
        (not isinstance(tools, list) or tool in tools)
        and (not isinstance(actions, list) or action in actions)
    )


def _stage(command: list[str], flow: dict[str, Any] | None = None) -> str:
    tool = command[1] if len(command) > 1 else ""
    action = command[2] if len(command) > 2 else ""
    for stage in (flow or {}).get("stages", []):
        if not isinstance(stage, dict):
            continue
        rules = stage.get("match")
        if isinstance(rules, list) and any(
            isinstance(rule, dict) and _rule_matches(rule, tool, action)
            for rule in rules
        ):
            return str(stage.get("id"))
    if tool in ("mx", "local-mrva"):
        return "verification" if action in ("check", "logs") else "infrastructure"
    if tool in ("dl", "db-lib", "ql", "query-lib"):
        return "inputs"
    if tool in ("mr", "mrva-request"):
        return "execution"
    if tool in ("si", "sarif-ingest"):
        return "verification" if action == "verify" else "results"
    if tool in ("ex", "export"):
        return "results"
    return "results"


def _label(command: list[str]) -> str:
    tool = command[1] if len(command) > 1 else ""
    action = command[2] if len(command) > 2 else ""
    return LABELS.get((tool, action), " ".join(command[1:3]) or "CGA command")


def _node_state(repository: Repository, node: dict[str, Any]) -> dict[str, Any]:
    reference = node.get("state")
    if not isinstance(reference, dict):
        raise WorkflowError(f"node {node.get('id')!r} has no state reference")
    return repository.load_state(reference)


def _parent_state(
    repository: Repository,
    manifest: dict[str, Any],
    node: dict[str, Any],
) -> dict[str, Any]:
    parent = node.get("parent")
    if isinstance(parent, str):
        value = manifest["nodes"].get(parent)
        if isinstance(value, dict):
            return _node_state(repository, value)
    chain = manifest["chains"].get(node.get("chain"))
    if isinstance(chain, dict) and isinstance(chain.get("base_state"), dict):
        return repository.load_state(chain["base_state"])
    return {}


def _delta_summary(
    repository: Repository,
    manifest: dict[str, Any],
    node: dict[str, Any],
) -> dict[str, list[str]]:
    before = _parent_state(repository, manifest, node)
    after = _node_state(repository, node)
    before_keys = set(before)
    after_keys = set(after)
    return {
        "added": sorted(after_keys - before_keys),
        "updated": sorted(
            key for key in before_keys & after_keys if before[key] != after[key]
        ),
        "removed": sorted(before_keys - after_keys),
    }


def _source_tooltip(source: dict[str, Any]) -> str:
    excerpt = source.get("excerpt")
    if not isinstance(excerpt, str):
        return ""
    return excerpt.strip()


def _step_summary(
    repository: Repository,
    manifest: dict[str, Any],
    value: dict[str, Any],
    kind: str,
    flow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    command = value.get("command")
    if not isinstance(command, list):
        command = []
    source = value.get("source")
    if not isinstance(source, dict):
        source = {}
    execution = value.get("execution")
    if not isinstance(execution, dict):
        execution = {}
    delta = (
        _delta_summary(repository, manifest, value)
        if kind == "node"
        else {"added": [], "updated": [], "removed": []}
    )
    return {
        "id": value.get("id"),
        "vid": step_reference(value),
        "kind": kind,
        "status": "failed" if kind == "attempt" else "succeeded",
        "parent": value.get("parent"),
        "label": _label(command),
        "command": command,
        "command_text": " ".join(command),
        "created_at": value.get("created_at"),
        "execution": execution,
        "tags": value.get("tags", {}),
        "delta": delta,
        "source": {
            **source,
            "preview": _source_tooltip(source),
        },
        "error": value.get("error"),
        "stage": _stage(command, flow),
    }


def workflow_model(repository: Repository) -> dict[str, Any]:
    manifest = repository.load_manifest()
    flow = _flow_metadata(repository)
    current = repository.head_chain()
    if not current:
        return {
            "schema": MODEL_SCHEMA,
            "workflow": repository.root.name,
            "root": str(repository.root),
            "chain": None,
            "vid_context": Space(repository).context(),
            "stages": [],
            "links": _links(flow),
        }
    chain_id, chain = repository.resolve_chain(manifest, current)
    values: list[tuple[str, dict[str, Any]]] = [
        ("node", node)
        for node in manifest["nodes"].values()
        if node.get("chain") == chain_id
    ]
    values.extend(
        ("attempt", attempt)
        for attempt in manifest["attempts"].values()
        if attempt.get("chain") == chain_id
    )
    values.sort(
        key=lambda item: (
            str(item[1].get("execution", {}).get("started_at", "")),
            str(item[1].get("created_at", "")),
            str(item[1].get("id", "")),
        )
    )
    summaries = [
        _step_summary(repository, manifest, value, kind, flow)
        for kind, value in values
    ]
    stage_order = (
        tuple(
            (str(stage["id"]), str(stage["label"]))
            for stage in flow.get("stages", [])
            if isinstance(stage, dict) and "id" in stage and "label" in stage
        )
        or STAGE_ORDER
    )
    by_stage = {key: [] for key, _label_value in stage_order}
    for step in summaries:
        by_stage.setdefault(step["stage"], []).append(step)
    stages = [
        {"id": key, "label": label, "steps": by_stage[key]}
        for key, label in stage_order
        if by_stage.get(key)
    ]
    current_state = repository.load_state(
        repository.state_reference(manifest, chain)
    )
    active = current_state.get("cgamr-active")
    submissions = current_state.get("cgamr-submissions")
    submission = (
        submissions.get(active)
        if isinstance(active, str) and isinstance(submissions, dict)
        else None
    )
    mrva_identity = {}
    if isinstance(submission, dict):
        mrva_identity = {
            "submission": active,
            "user": submission.get("user"),
            "session_id": submission.get("session_id"),
        }
    return {
        "schema": MODEL_SCHEMA,
        "vid_context": Space(repository).context(),
        "workflow": repository.root.name,
        "root": str(repository.root),
        "chain": {
            "id": chain_id,
            "name": chain.get("name"),
            "head": chain.get("head"),
            "created_at": chain.get("created_at"),
            "step_count": len(summaries),
        },
        "stages": stages,
        "flow": flow,
        "mrva": mrva_identity,
        "links": _links(flow),
    }


def _changed_values(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    return {
        "added": {key: after[key] for key in sorted(after_keys - before_keys)},
        "updated": {
            key: {"before": before[key], "after": after[key]}
            for key in sorted(before_keys & after_keys)
            if before[key] != after[key]
        },
        "removed": {key: before[key] for key in sorted(before_keys - after_keys)},
    }


def _component_state(command: list[str], state: dict[str, Any]) -> dict[str, Any]:
    token = command[1] if len(command) > 1 else ""
    prefix = COMPONENT_PREFIX.get(token)
    if not prefix:
        return {}
    return {
        key: value
        for key, value in state.items()
        if key == prefix or key.startswith(prefix + "-")
    }


def _transcript(
    repository: Repository,
    execution: dict[str, Any],
) -> str:
    reference = execution.get("transcript")
    if not isinstance(reference, dict):
        return ""
    return repository.store().read(reference).decode("utf-8", "replace")


def step_detail(repository: Repository, step_id: str) -> dict[str, Any]:
    manifest = repository.load_manifest()
    flow = _flow_metadata(repository)
    value = manifest["nodes"].get(step_id)
    kind = "node"
    if not isinstance(value, dict):
        value = manifest["attempts"].get(step_id)
        kind = "attempt"
    if not isinstance(value, dict):
        raise WorkflowError(f"unknown workflow step: {step_id!r}")
    summary = _step_summary(repository, manifest, value, kind, flow)
    execution = value.get("execution")
    if not isinstance(execution, dict):
        execution = {}
    children = sorted(
        node_id
        for node_id, node in manifest["nodes"].items()
        if node.get("parent") == step_id
    )
    children.extend(
        sorted(
            attempt_id
            for attempt_id, attempt in manifest["attempts"].items()
            if attempt.get("parent") == step_id
        )
    )
    artifacts = []
    for artifact_id in value.get("artifacts", []):
        artifact = manifest["artifacts"].get(artifact_id)
        if isinstance(artifact, dict) and artifact.get("source_node") == step_id:
            artifacts.append({**artifact, "vid": reference(
                "artifacts", int(artifact_id.removeprefix("artifact_")) + 1)})
    detail = {
        "schema": STEP_SCHEMA,
        **summary,
        "children": children,
        "artifacts": artifacts,
        "transcript": _transcript(repository, execution),
        "state_delta": {"added": {}, "updated": {}, "removed": {}},
        "component_state": {},
    }
    if kind == "node":
        before = _parent_state(repository, manifest, value)
        after = _node_state(repository, value)
        detail["state_delta"] = _changed_values(before, after)
        command = value.get("command")
        detail["component_state"] = _component_state(
            command if isinstance(command, list) else [],
            after,
        )
    return detail


def artifact_detail(repository: Repository, artifact_id: str) -> dict[str, Any]:
    manifest = repository.load_manifest()
    artifact = manifest["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict):
        raise WorkflowError(f"unknown artifact: {artifact_id!r}")
    return {
        "schema": ARTIFACT_SCHEMA,
        "vid": reference("artifacts", int(artifact_id.removeprefix("artifact_")) + 1),
        **artifact,
        "location": repository.store().location(str(artifact["key"])),
    }


def outline_model(
    repository: Repository,
    detail: str = "steps",
    wanted_tags: list[str] | None = None,
    include_sensitive: bool = False,
    include_runtime: bool = False,
) -> dict[str, Any]:
    if detail not in ("summary", "steps"):
        raise WorkflowError("outline detail must be 'summary' or 'steps'")
    normalize_tags(wanted_tags or [])
    model = workflow_model(repository)
    stages = []
    redacted_steps = 0
    for stage in model.get("stages", []):
        steps = []
        for step in stage["steps"]:
            if _is_secret(step.get("tags")) and not include_sensitive:
                redacted_steps += 1
                continue
            if tags_match(step.get("tags"), wanted_tags or []):
                steps.append(step)
        if not steps:
            continue
        value: dict[str, Any] = {
            "id": stage["id"],
            "label": stage["label"],
            "step_count": len(steps),
        }
        if detail == "steps":
            value["steps"] = [
                {
                    "id": step["id"],
                    "vid": step["vid"],
                    "kind": step["kind"],
                    "status": step["status"],
                    "label": step["label"],
                    "command": step["command_text"],
                    "tags": step.get("tags", {}),
                    "source": step.get("source", {}),
                    "delta": step.get("delta", {}),
                    "href": f"/api/step?id={step['id']}",
                }
                for step in steps
            ]
        stages.append(value)
    collections = {}
    if model.get("chain"):
        for kind in ("databases", "queries"):
            value = collection_model(repository, kind, limit=1)
            secret = _is_secret(value.get("tags")) and not include_sensitive
            collections[kind] = {
                "total": 0 if secret else value["page"]["total"],
                "redacted": secret,
                "tags": {} if secret else value.get("tags", {}),
                "href": f"/api/collections/{kind}",
            }
    manifest = repository.load_manifest()
    active_node_ids = {
        step["id"]
        for stage in model.get("stages", [])
        for step in stage["steps"]
        if step["kind"] == "node"
    }
    artifact_count = sum(
        1
        for artifact in manifest["artifacts"].values()
        if artifact.get("source_node") in active_node_ids
        and (include_sensitive or not _is_secret(artifact.get("tags")))
    )
    return {
        "schema": OUTLINE_SCHEMA,
        "detail": detail,
        "workflow": model["workflow"],
        "vid_context": model["vid_context"],
        "root": model["root"],
        "chain": model["chain"],
        "mrva": model.get("mrva", {}),
        "stages": stages,
        "collections": collections,
        "resources": {
            "artifacts": {
                "total": artifact_count,
                "href": "/api/search?kind=artifact",
            },
            "attempts": {
                "total": sum(
                    1
                    for stage in model.get("stages", [])
                    for step in stage["steps"]
                    if step["kind"] == "attempt"
                ),
                "href": "/api/search?kind=attempt",
            },
        },
        "system": runtime_summary(model.get("mrva", {})) if include_runtime else {},
        "redacted_steps": redacted_steps,
        "include_sensitive": include_sensitive,
        "links": model["links"],
    }


def outline_markdown(document: dict[str, Any]) -> str:
    chain = document.get("chain") or {}
    lines = [
        f"# CGA flow: {document.get('workflow', '(unknown)')}",
        "",
        f"- Schema: `{document['schema']}`",
        f"- Chain: `{chain.get('name') or chain.get('id') or '(none)'}`",
        f"- Steps: {chain.get('step_count', 0)}",
        f"- Redacted steps: {document.get('redacted_steps', 0)}",
        "- VIDs: `:a9x` (workflow), `:h7m` (commands), `:91c` (artifacts)",
        f"- VID context: `{json.dumps(document.get('vid_context', {}), sort_keys=True)}`",
        "",
        "## Collections",
        "",
    ]
    for name, value in document.get("collections", {}).items():
        redacted = " (redacted)" if value.get("redacted") else ""
        lines.append(f"- [{name}]({value['href']}): {value['total']}{redacted}")
    for name, value in document.get("resources", {}).items():
        lines.append(f"- [{name}]({value['href']}): {value['total']}")
    system = document.get("system")
    if isinstance(system, dict) and system:
        lines.extend([
            "",
            "## MRVA system summary",
            "",
            f"- Available: {str(system.get('available', False)).lower()}",
            f"- Servers online: {system.get('servers_online', 0)}",
            f"- Workers: {system.get('workers', 0)}",
            f"- Jobs: {system.get('jobs', 0)}",
            f"- Pending spawns: {system.get('spawns', 0)}",
            f"- [Full MRVA System View]({system.get('url', '')})",
        ])
    for stage in document.get("stages", []):
        lines.extend([
            "",
            f"## {stage['label']}",
            "",
        ])
        if "steps" not in stage:
            lines.append(f"- {stage['step_count']} step(s)")
            continue
        for step in stage["steps"]:
            tags = ", ".join(step.get("tags", {}).get("canonical", []))
            suffix = f" — tags: {tags}" if tags else ""
            lines.append(
                f"- **{step['label']}** (`{step['id']}`, `{step['vid']}`): "
                f"`{step['command']}`{suffix}"
            )
    return "\n".join(lines) + "\n"


def _load_collection_document(
    repository: Repository,
    kind: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    manifest = repository.load_manifest()
    state = repository.current_state(manifest)
    if kind == "databases":
        state_key = "cgadl-selection"
        item_key = "databases"
        commands = (("dl", "getmeta"), ("dl", "sql"), ("dl", "select"))
    elif kind == "queries":
        state_key = "cgaql-selection"
        item_key = "queries"
        commands = (("ql", "index"), ("ql", "select"))
    else:
        raise WorkflowError(f"unknown collection kind: {kind!r}")
    raw_path = state.get(state_key)
    if not isinstance(raw_path, str):
        return [], {}, []
    chain_id, chain = repository.resolve_chain(manifest, None)
    current = chain.get("head") or chain.get("root_parent")
    retained = None
    while current:
        node = manifest["nodes"][current]
        if repository.load_state(node["state"]).get(state_key) != raw_path:
            break
        retained = next((manifest["artifacts"][artifact_id]
                         for artifact_id in node.get("artifacts", [])
                         if manifest["artifacts"][artifact_id]["logical_name"] == state_key), None)
        if retained is not None:
            break
        current = node.get("parent")
    if retained is None:
        raise WorkflowError(f"{kind} selection has no retained immutable artifact")
    try:
        content = repository.store().read(retained)
        document = json.loads(content)
    except OSError as error:
        raise WorkflowError(f"cannot read retained {kind} selection: {error}") from error
    except json.JSONDecodeError as error:
        raise WorkflowError(f"invalid retained {kind} selection: {error}") from error
    items = document.get(item_key)
    if not isinstance(items, list):
        raise WorkflowError(f"{kind} selection has no {item_key!r} array")
    origin_steps = []
    tags: dict[str, Any] = {"profiles": [], "canonical": [], "values": {}}
    for node in sorted(
        (
            node
            for node in manifest["nodes"].values()
            if node.get("chain") == chain_id
        ),
        key=lambda node: int(node.get("sequence", 0)),
    ):
        command = node.get("command")
        if (
            isinstance(command, list)
            and len(command) >= 3
            and (command[1], command[2]) in commands
        ):
            origin_steps.append(str(node["id"]))
            tags = _merge_tags(tags, node.get("tags"))
    generation = hashlib.sha256(content).hexdigest()
    return [{**item, "_vid": reference(kind, "g" + generation, index)}
            for index, item in enumerate(items, 1) if isinstance(item, dict)], tags, origin_steps


def _merge_tags(left: dict[str, Any], right: Any) -> dict[str, Any]:
    if not isinstance(right, dict):
        return left
    profiles = list(dict.fromkeys(
        list(left.get("profiles", [])) + list(right.get("profiles", []))
    ))
    canonical = list(dict.fromkeys(
        list(left.get("canonical", [])) + list(right.get("canonical", []))
    ))
    values: dict[str, list[str]] = {}
    for source in (left.get("values", {}), right.get("values", {})):
        if not isinstance(source, dict):
            continue
        for key, items in source.items():
            if not isinstance(items, list):
                continue
            values.setdefault(key, [])
            for item in items:
                if isinstance(item, str) and item not in values[key]:
                    values[key].append(item)
    return {"profiles": profiles, "canonical": canonical, "values": values}


def _item_id(kind: str, item: dict[str, Any]) -> str:
    if kind == "databases":
        return f"{item.get('git_owner', '')}/{item.get('git_repo', '')}"
    return str(item.get("id") or item.get("relpath") or item.get("filename") or "")


def _scalar_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_scalar_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_scalar_text(item) for item in value)
    return str(value) if value is not None else ""


def collection_model(
    repository: Repository,
    kind: str,
    query: str = "",
    filters: dict[str, str] | None = None,
    sort_key: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    items, tags, origin_steps = _load_collection_document(repository, kind)
    query_text = query.strip().lower()
    wanted = filters or {}
    available_fields = {
        key
        for item in items
        for key in item
    }
    unknown_filters = sorted(set(wanted) - available_fields)
    if unknown_filters:
        raise WorkflowError(
            f"unknown {kind} filter field(s): {', '.join(unknown_filters)}"
        )
    filtered = []
    for item in items:
        item_id = _item_id(kind, item)
        searchable_text = f"{item_id} {_scalar_text(item)}".lower()
        if query_text and query_text not in searchable_text:
            continue
        if any(str(item.get(key, "")).lower() != value.lower()
               for key, value in wanted.items()):
            continue
        filtered.append({**item, "_id": item_id, "vid": item["_vid"]})
    if sort_key:
        if any(sort_key not in item for item in filtered):
            raise WorkflowError(f"cannot sort {kind} by unknown field {sort_key!r}")
        filtered.sort(key=lambda item: str(item.get(sort_key, "")).lower())
    else:
        filtered.sort(key=lambda item: item["_id"].lower())
    offset = max(0, int(offset))
    limit = min(MAX_PAGE_SIZE, max(1, int(limit)))
    total = len(filtered)
    page_items = filtered[offset:offset + limit]
    return {
        "schema": COLLECTION_SCHEMA,
        "kind": kind,
        "tags": tags,
        "origin_steps": origin_steps,
        "query": query,
        "filters": wanted,
        "sort": sort_key,
        "page": {
            "offset": offset,
            "limit": limit,
            "count": len(page_items),
            "total": total,
            "truncated": offset + len(page_items) < total,
        },
        "items": page_items,
    }


def search_model(
    repository: Repository,
    query: str = "",
    wanted_tags: list[str] | None = None,
    kinds: list[str] | None = None,
    offset: int = 0,
    limit: int = 50,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    normalize_tags(wanted_tags or [])
    query_text = query.strip().lower()
    wanted_kinds = set(kinds or ("step", "attempt", "artifact", "database", "query"))
    unknown_kinds = sorted(wanted_kinds - SEARCH_KINDS)
    if unknown_kinds:
        raise WorkflowError(
            f"unknown search kind(s): {', '.join(unknown_kinds)}"
        )
    results: list[dict[str, Any]] = []
    redacted = 0
    model = workflow_model(repository)
    for stage in model.get("stages", []):
        for step in stage["steps"]:
            kind = "attempt" if step["kind"] == "attempt" else "step"
            if _is_secret(step.get("tags")) and not include_sensitive:
                redacted += 1
                continue
            if kind not in wanted_kinds or not tags_match(
                step.get("tags"), wanted_tags or []
            ):
                continue
            text = " ".join((
                step["label"],
                step["command_text"],
                step.get("source", {}).get("preview", ""),
            ))
            if query_text and query_text not in text.lower():
                continue
            results.append({
                "kind": kind,
                "id": step["id"],
                "vid": step["vid"],
                "label": step["label"],
                "summary": step["command_text"],
                "tags": step.get("tags", {}),
                "href": f"/api/step?id={step['id']}",
            })
    manifest = repository.load_manifest()
    if "artifact" in wanted_kinds:
        active_sources = {
            step["id"]
            for stage in model.get("stages", [])
            for step in stage["steps"]
            if step["kind"] == "node"
        }
        for artifact in manifest["artifacts"].values():
            if artifact.get("source_node") not in active_sources:
                continue
            if _is_secret(artifact.get("tags")) and not include_sensitive:
                redacted += 1
                continue
            if not tags_match(artifact.get("tags"), wanted_tags or []):
                continue
            text = _scalar_text(artifact)
            if query_text and query_text not in text.lower():
                continue
            results.append({
                "kind": "artifact",
                "id": artifact.get("id"),
                "vid": reference("artifacts", int(artifact["id"].removeprefix("artifact_")) + 1),
                "label": artifact.get("logical_name"),
                "summary": (
                    f"{artifact.get('kind')} · {artifact.get('size', 0)} bytes"
                ),
                "tags": artifact.get("tags", {}),
                "href": f"/api/artifact?id={artifact.get('id')}",
            })
    for collection_kind, result_kind in (("databases", "database"), ("queries", "query")):
        if result_kind not in wanted_kinds:
            continue
        collection = collection_model(repository, collection_kind, query=query, limit=MAX_PAGE_SIZE)
        if _is_secret(collection.get("tags")) and not include_sensitive:
            redacted += collection["page"]["total"]
            continue
        if not tags_match(collection.get("tags"), wanted_tags or []):
            continue
        for item in collection["items"]:
            results.append({
                "kind": result_kind,
                "id": item["_id"],
                "vid": item["vid"],
                "label": item["_id"],
                "summary": _scalar_text(item)[:500],
                "tags": collection.get("tags", {}),
                "href": f"/api/collections/{collection_kind}?q={item['_id']}",
            })
    results.sort(key=lambda item: (item["kind"], str(item["label"]).lower()))
    offset = max(0, int(offset))
    limit = min(MAX_PAGE_SIZE, max(1, int(limit)))
    total = len(results)
    page = results[offset:offset + limit]
    return {
        "schema": SEARCH_SCHEMA,
        "query": query,
        "tags": wanted_tags or [],
        "kinds": sorted(wanted_kinds),
        "page": {
            "offset": offset,
            "limit": limit,
            "count": len(page),
            "total": total,
            "truncated": offset + len(page) < total,
            "redacted": redacted,
        },
        "include_sensitive": include_sensitive,
        "results": page,
    }


def search_markdown(document: dict[str, Any]) -> str:
    lines = [
        "# CGA search",
        "",
        f"- Schema: `{document['schema']}`",
        f"- Query: `{document.get('query', '')}`",
        f"- Total: {document['page']['total']}",
        f"- Returned: {document['page']['count']}",
        f"- Truncated: {str(document['page']['truncated']).lower()}",
        f"- Redacted: {document['page'].get('redacted', 0)}",
        "",
    ]
    for result in document.get("results", []):
        tags = ", ".join(result.get("tags", {}).get("canonical", []))
        suffix = f" — {tags}" if tags else ""
        lines.append(
            f"- **{result['kind']}** [{result['label']}]({result['href']}): "
            f"{result['summary']}{suffix}"
        )
    return "\n".join(lines) + "\n"


def _is_secret(tags: Any) -> bool:
    return (
        isinstance(tags, dict)
        and "sensitivity:secret" in tags.get("canonical", [])
    )


def flow_source_path(repository: Repository) -> Path:
    flow = _flow_metadata(repository)
    source = flow.get("source")
    if not isinstance(source, str) or not source:
        raise WorkflowError("flow view metadata has no source path")
    path = (repository.root / source).resolve()
    try:
        path.relative_to(repository.root)
    except ValueError as error:
        raise WorkflowError("flow source path escapes the workflow root") from error
    if not path.is_file():
        raise WorkflowError(f"flow source does not exist: {path}")
    return path


def _links(flow: dict[str, Any] | None = None) -> dict[str, str]:
    page_port = os.environ.get("CGA_PAGE_PORT", "8600")
    links = {
        "workflow_state": f"http://127.0.0.1:{page_port}/",
        "mrva_sysview": sysview_url(),
        "replay": "/existing/replay",
        "dfg": "/existing/dfg",
        "cfg": "/existing/cfg",
    }
    if isinstance((flow or {}).get("source"), str):
        links["source"] = "/existing/source"
    return links


def sysview_url() -> str:
    base = os.environ.get("CGA_MRVA_SERVER", "http://127.0.0.1:8081").rstrip("/")
    return f"{base}/sysview"


def fetch_sysview() -> tuple[int, dict[str, Any]]:
    page_url = sysview_url()
    url = f"{page_url}/data"
    request = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            value = json.load(response)
        if not isinstance(value, dict):
            raise ValueError("MRVA sysview returned a non-object document")
        return 200, {"available": True, "data": value, "url": page_url}
    except (OSError, ValueError, urllib.error.URLError) as error:
        jobs = Counter()
        return 503, {
            "available": False,
            "error": str(error),
            "data": {"servers": [], "workers": [], "jobs": [], "spawns": []},
            "summary": {"jobs": dict(jobs)},
            "url": page_url,
        }


def runtime_summary(identity: dict[str, Any] | None = None) -> dict[str, Any]:
    _status, payload = fetch_sysview()
    data = payload.get("data", {})
    if not isinstance(data, dict):
        data = {}
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        jobs = []
    identity = identity or {}
    if identity.get("user") is not None and identity.get("session_id") is not None:
        jobs = [
            job
            for job in jobs
            if isinstance(job, dict)
            and str(job.get("user")) == str(identity["user"])
            and str(job.get("session_id")) == str(identity["session_id"])
        ]
    servers = data.get("servers")
    workers = data.get("workers")
    spawns = data.get("spawns")
    servers = servers if isinstance(servers, list) else []
    workers = workers if isinstance(workers, list) else []
    spawns = spawns if isinstance(spawns, list) else []
    return {
        "available": bool(payload.get("available")),
        "error": payload.get("error"),
        "servers_online": sum(
            1 for server in servers
            if isinstance(server, dict) and server.get("online")
        ),
        "servers_total": len(servers),
        "workers": len(workers),
        "jobs": len(jobs),
        "spawns": len(spawns),
        "served_by": data.get("served_by"),
        "generated_at": data.get("generated_at"),
        "url": payload.get("url"),
    }

"""CLI for persistent .cga workflows."""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cgalib"))
from command_help import enhance_parser

from .repository import (
    ObjectStore,
    Repository,
    WorkflowError,
    atomic_write,
    canonical_json,
)
from . import tags as taglib


def _repository() -> Repository:
    return Repository.discover()


def _json_output() -> bool:
    return os.environ.get("CGA_OUTPUT_JSON") == "1"


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _state_for_revision(
    repository: Repository,
    manifest: dict[str, Any],
    revision: str | None,
) -> tuple[str, dict[str, Any]]:
    if revision:
        node_id, node = repository.resolve_node(manifest, revision)
        return node_id, repository.load_state(node["state"])
    chain_id, chain = repository.resolve_chain(manifest, None)
    label = chain.get("head") or chain_id
    return str(label), repository.load_state(
        repository.state_reference(manifest, chain)
    )


def _state_delta(previous: dict[str, Any], current: dict[str, Any]) -> str:
    previous_keys = set(previous)
    current_keys = set(current)
    added = sorted(current_keys - previous_keys)
    removed = sorted(previous_keys - current_keys)
    updated = sorted(
        key for key in previous_keys & current_keys if previous[key] != current[key]
    )
    parts = []
    if added:
        parts.append("+" + ",".join(added))
    if updated:
        parts.append("~" + ",".join(updated))
    if removed:
        parts.append("-" + ",".join(removed))
    return " ".join(parts) or "-"


def cmd_init(args: argparse.Namespace) -> int:
    repository = Repository.init(
        Path(args.directory), args.store or os.environ.get("CGA_OBJECT_STORE")
    )
    print(f"Initialized CGA workflow in {repository.cga_dir}")
    print(f"Object store: {repository.store().root}")
    return 0


def cmd_root(_args: argparse.Namespace) -> int:
    print(_repository().root)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    repository = _repository()
    manifest = repository.load_manifest()
    config = repository.load_config()
    current = repository.head_chain()
    chain = manifest["chains"].get(current, {}) if current else {}
    value = {
        "workflow": config.get("workflow", {}).get("name", repository.root.name),
        "root": str(repository.root),
        "cga_dir": str(repository.cga_dir),
        "object_store": repository.store().root,
        "current_chain": current,
        "head": chain.get("head"),
        "steps": int(chain.get("next_sequence", 0)),
        "chains": len(manifest["chains"]),
        "artifacts": len(manifest["artifacts"]),
    }
    if _json_output():
        _print_json(value)
    else:
        print(f"Workflow: {value['workflow']} ({value['root']})")
        print(f"CGA directory: {value['cga_dir']}")
        print(f"Object store: {value['object_store']}")
        print(f"Current chain: {current or '(none)'}")
        print(f"Head: {value['head'] or '(none)'}")
        print(f"Steps: {value['steps']}")
        print(f"Chains: {value['chains']}")
        print(f"Artifacts: {value['artifacts']}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    repository = _repository()
    errors = repository.verify()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"OK: {repository.root} ({len(repository.load_manifest()['nodes'])} steps)"
    )
    return 0


def cmd_chain_start(args: argparse.Namespace) -> int:
    print(_repository().start_chain(args.from_revision, args.name))
    return 0


def _chain_rows(
    repository: Repository, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    current = repository.head_chain()
    rows = []
    for chain_id, chain in sorted(
        manifest["chains"].items(), key=lambda item: int(item[1]["number"])
    ):
        rows.append(
            {
                "current": chain_id == current,
                "id": chain_id,
                "name": chain.get("name"),
                "steps": int(chain.get("next_sequence", 0)),
                "head": chain.get("head"),
                "from": chain.get("root_parent"),
                "created_at": chain.get("created_at"),
            }
        )
    return rows


def cmd_chain_list(_args: argparse.Namespace) -> int:
    repository = _repository()
    rows = _chain_rows(repository, repository.load_manifest())
    if _json_output():
        _print_json(rows)
        return 0
    if not rows:
        print("(no chains)")
        return 0
    for row in rows:
        marker = "*" if row["current"] else " "
        name = f" ({row['name']})" if row["name"] else ""
        origin = f" from {row['from']}" if row["from"] else ""
        print(
            f"{marker} {row['id']}{name}: {row['steps']} step(s), "
            f"head={row['head'] or '(none)'}{origin}"
        )
    return 0


def cmd_chain_current(_args: argparse.Namespace) -> int:
    current = _repository().head_chain()
    if not current:
        raise WorkflowError("no current chain; run 'cga chain start'")
    print(current)
    return 0


def cmd_chain_switch(args: argparse.Namespace) -> int:
    print(_repository().switch_chain(args.chain))
    return 0


def cmd_chain_rename(args: argparse.Namespace) -> int:
    chain_id = _repository().rename_chain(args.chain, args.name)
    print(f"{chain_id}: {args.name}")
    return 0


def _chain_nodes(
    manifest: dict[str, Any], chain_id: str
) -> list[dict[str, Any]]:
    return sorted(
        (
            node
            for node in manifest["nodes"].values()
            if node.get("chain") == chain_id
        ),
        key=lambda node: (int(node["sequence"]), str(node["id"])),
    )


def cmd_chain_show(args: argparse.Namespace) -> int:
    repository = _repository()
    manifest = repository.load_manifest()
    chain_id, chain = repository.resolve_chain(manifest, args.chain)
    nodes = _chain_nodes(manifest, chain_id)
    if _json_output():
        _print_json({"chain": chain, "nodes": nodes})
        return 0
    name = f" ({chain['name']})" if chain.get("name") else ""
    print(f"{chain_id}{name}")
    print(f"  created: {chain['created_at']}")
    print(f"  from: {chain.get('root_parent') or '(empty state)'}")
    print(f"  head: {chain.get('head') or '(none)'}")
    print(f"  steps: {len(nodes)}")
    previous = repository.load_state(chain["base_state"])
    for node in nodes:
        state = repository.load_state(node["state"])
        command = " ".join(node["command"])
        suffix = f"  {_state_delta(previous, state)}" if args.verbose else ""
        print(f"  {node['sequence']:>3}  {node['id']}  {command}{suffix}")
        if args.verbose:
            print(f"       source: {node['source_step']}")
            print(f"       created: {node['created_at']}")
            print(f"       artifacts: {len(node.get('artifacts', []))}")
        previous = state
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    repository = _repository()
    label, state = _state_for_revision(
        repository, repository.load_manifest(), args.revision
    )
    if not args.raw and not _json_output():
        print(f"# {label}")
    _print_json(state)
    return 0


def _states_for_diff(
    repository: Repository, left: str, right: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = repository.load_manifest()
    _, left_state = _state_for_revision(repository, manifest, left)
    _, right_state = _state_for_revision(repository, manifest, right)
    return left_state, right_state


def cmd_state_diff(args: argparse.Namespace) -> int:
    left, right = _states_for_diff(_repository(), args.left, args.right)
    before = json.dumps(left, indent=2, sort_keys=True).splitlines(keepends=True)
    after = json.dumps(right, indent=2, sort_keys=True).splitlines(keepends=True)
    sys.stdout.writelines(
        difflib.unified_diff(
            before, after, fromfile=args.left, tofile=args.right
        )
    )
    return 0


def cmd_state_validate(args: argparse.Namespace) -> int:
    repository = _repository()
    label, state = _state_for_revision(
        repository, repository.load_manifest(), args.revision
    )
    canonical_json(state)
    print(f"OK: {label}")
    return 0


def cmd_state_export(args: argparse.Namespace) -> int:
    repository = _repository()
    _, state = _state_for_revision(
        repository, repository.load_manifest(), args.revision
    )
    destination = Path(args.output).expanduser().resolve()
    atomic_write(destination, json.dumps(state, indent=2, sort_keys=True).encode() + b"\n")
    print(destination)
    return 0


def cmd_state_import(args: argparse.Namespace) -> int:
    source = Path(args.file).expanduser().resolve()
    try:
        state = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkflowError(f"cannot import {source}: {error}") from error
    if not isinstance(state, dict):
        raise WorkflowError("imported CGAST must be a JSON object")
    repository = _repository()
    chain_id = repository.start_chain(name=args.name)
    with repository.locked():
        manifest = repository.load_manifest()
        _, chain = repository.resolve_chain(manifest, chain_id)
        node = repository.record_state(
            manifest,
            chain_id,
            chain,
            state,
            ["cga", "state", "import", str(source)],
            "state-import",
        )
    print(f"{chain_id} {node}")
    return 0


def cmd_step_show(args: argparse.Namespace) -> int:
    repository = _repository()
    manifest = repository.load_manifest()
    node_id, node = repository.resolve_node(manifest, args.node)
    if _json_output():
        value = dict(node)
        if args.verbose:
            value["cgast"] = repository.load_state(node["state"])
        _print_json(value)
        return 0
    print(f"Step: {node_id}")
    print(f"Chain: {node['chain']}")
    print(f"Parent: {node.get('parent') or '(none)'}")
    print(f"Source: {node['source_step']}")
    print(f"Created: {node['created_at']}")
    print(f"Command: {' '.join(node['command'])}")
    print(f"State object: {node['state']['key']}")
    print(f"Artifacts: {len(node.get('artifacts', []))}")
    if args.verbose:
        _print_json(repository.load_state(node["state"]))
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    repository = _repository()
    manifest = repository.load_manifest()
    if args.all:
        nodes = list(manifest["nodes"].values())
    else:
        chain_id, _ = repository.resolve_chain(manifest, None)
        nodes = _chain_nodes(manifest, chain_id)
    nodes.sort(key=lambda node: (node["created_at"], node["id"]))
    if args.limit is not None:
        nodes = nodes[-args.limit :]
    if _json_output():
        _print_json(nodes)
        return 0
    for node in nodes:
        print(
            f"{node['id']}  {node['created_at']}  "
            f"{' '.join(node['command'])}"
        )
    return 0


def _tree_dot(manifest: dict[str, Any], control_flow: bool) -> str:
    lines = [
        "digraph cga {",
        '  graph [rankdir=TB, labelloc=t, label="CGA workflow forest"];',
        '  node [shape=box, fontname="monospace", fontsize=10];',
    ]
    for chain_id, chain in manifest["chains"].items():
        lines.append(f"  subgraph cluster_{chain['number']} {{")
        lines.append(f"    label={json.dumps(chain_id)};")
        for node in _chain_nodes(manifest, chain_id):
            rows = [
                f'<TR><TD ALIGN="LEFT"><B>{html.escape(node["id"])}</B></TD></TR>'
            ]
            if not control_flow:
                command = html.escape(" ".join(node["command"]))
                rows.append(f'<TR><TD ALIGN="LEFT">{command}</TD></TR>')
            label = (
                '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0">'
                + "".join(rows)
                + "</TABLE>>"
            )
            lines.append(f"    {json.dumps(node['id'])} [label={label}];")
        lines.append("  }")
    for node in manifest["nodes"].values():
        if node.get("parent"):
            lines.append(
                f"  {json.dumps(node['parent'])} -> {json.dumps(node['id'])};"
            )
    lines.append("}")
    return "\n".join(lines) + "\n"


def _tree_text(
    repository: Repository,
    manifest: dict[str, Any],
    verbose: bool,
    markdown: bool,
    control_flow: bool,
) -> str:
    children: dict[str | None, list[str]] = {}
    for chain_id, chain in manifest["chains"].items():
        parent_node = chain.get("root_parent")
        parent_chain = None
        if parent_node:
            parent = manifest["nodes"].get(parent_node, {})
            parent_chain = parent.get("chain")
        children.setdefault(parent_chain, []).append(chain_id)
    for values in children.values():
        values.sort(key=lambda item: int(manifest["chains"][item]["number"]))
    lines: list[str] = []

    def render(chain_id: str, depth: int) -> None:
        chain = manifest["chains"][chain_id]
        indent = "  " * depth
        name = f" ({chain['name']})" if chain.get("name") else ""
        marker = "*" if repository.head_chain() == chain_id else "-"
        if markdown:
            lines.append(
                f"{indent}- **{chain_id}**{name}: "
                f"{chain['next_sequence']} step(s)"
            )
        else:
            lines.append(
                f"{indent}{marker} {chain_id}{name} "
                f"[{chain['next_sequence']} step(s)]"
            )
        if verbose:
            previous = repository.load_state(chain["base_state"])
            for node in _chain_nodes(manifest, chain_id):
                command = " ".join(node["command"])
                state = repository.load_state(node["state"])
                detail = command if control_flow else (
                    f"{_state_delta(previous, state)}  {command}"
                )
                prefix = "  " * (depth + 1)
                lines.append(f"{prefix}{node['id']}: {detail}")
                previous = state
        for child in children.get(chain_id, []):
            render(child, depth + 1)

    for chain_id in children.get(None, []):
        render(chain_id, 0)
    return "\n".join(lines) + ("\n" if lines else "")


def cmd_tree_show(args: argparse.Namespace) -> int:
    repository = _repository()
    manifest = repository.load_manifest()
    output_format = args.format
    verbose = args.verbose or args.control_flow
    if output_format == "text":
        content = _tree_text(
            repository, manifest, verbose, False, args.control_flow
        )
    elif output_format == "markdown":
        content = _tree_text(
            repository, manifest, verbose, True, args.control_flow
        )
    elif output_format in ("dot", "pdf", "html"):
        content = _tree_dot(manifest, args.control_flow)
    else:
        raise WorkflowError(f"unsupported tree format: {output_format}")
    if output_format in ("pdf", "html"):
        if not args.output:
            raise WorkflowError(
                f"--output is required for {output_format.upper()} rendering"
            )
        destination = Path(args.output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            if output_format == "pdf":
                subprocess.run(
                    ["dot", "-Tpdf", "-o", str(destination)],
                    input=content.encode(),
                    check=True,
                )
            else:
                rendered = subprocess.run(
                    ["dot", "-Tsvg"],
                    input=content.encode(),
                    stdout=subprocess.PIPE,
                    check=True,
                ).stdout.decode()
                svg = rendered[rendered.index("<svg"):]
                document = (
                    '<!doctype html><html><head><meta charset="utf-8">'
                    "<title>CGA workflow forest</title>"
                    "<style>body{font-family:system-ui;margin:0;padding:1rem;"
                    "background:#f8fafc}main{overflow:auto}svg{height:auto;"
                    "max-width:none}</style></head><body><main>"
                    f"{svg}</main></body></html>\n"
                )
                atomic_write(destination, document.encode())
        except FileNotFoundError as error:
            raise WorkflowError(
                f"Graphviz 'dot' is required for {output_format.upper()} output"
            ) from error
        except ValueError as error:
            raise WorkflowError("Graphviz did not produce an SVG document") from error
        except subprocess.CalledProcessError as error:
            raise WorkflowError(f"Graphviz failed with status {error.returncode}") from error
        print(destination)
    elif args.output:
        destination = Path(args.output).expanduser().resolve()
        atomic_write(destination, content.encode())
        print(destination)
    else:
        sys.stdout.write(content)
    return 0


def _config_lookup(config: dict[str, Any], key: str) -> Any:
    value: Any = config
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise WorkflowError(f"unknown configuration key: {key}")
        value = value[part]
    return value


def cmd_config_list(_args: argparse.Namespace) -> int:
    _print_json(_repository().load_config())
    return 0


def cmd_config_get(args: argparse.Namespace) -> int:
    value = _config_lookup(_repository().load_config(), args.key)
    if isinstance(value, (dict, list)):
        _print_json(value)
    elif value is not None:
        print(str(value).lower() if isinstance(value, bool) else value)
    return 0


def _parse_config_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def cmd_config_set(args: argparse.Namespace) -> int:
    if args.key in ("format_version", "object_store.root"):
        raise WorkflowError(
            f"{args.key} is managed by the workflow format or 'cga store set'"
        )
    repository = _repository()
    with repository.locked():
        config = repository.load_config()
        value: Any = config
        parts = args.key.split(".")
        for part in parts[:-1]:
            child = value.setdefault(part, {})
            if not isinstance(child, dict):
                raise WorkflowError(
                    f"configuration key is not an object: {part!r}"
                )
            value = child
        value[parts[-1]] = _parse_config_value(args.value)
        repository.write_config(config)
    return 0


def cmd_config_unset(args: argparse.Namespace) -> int:
    if args.key in ("format_version", "object_store", "object_store.root"):
        raise WorkflowError(f"required configuration key cannot be removed: {args.key}")
    repository = _repository()
    with repository.locked():
        config = repository.load_config()
        value: Any = config
        parts = args.key.split(".")
        for part in parts[:-1]:
            if not isinstance(value, dict) or part not in value:
                raise WorkflowError(f"unknown configuration key: {args.key}")
            value = value[part]
        if not isinstance(value, dict) or parts[-1] not in value:
            raise WorkflowError(f"unknown configuration key: {args.key}")
        del value[parts[-1]]
        repository.write_config(config)
    return 0


def cmd_config_path(_args: argparse.Namespace) -> int:
    print(_repository().config_path)
    return 0


def cmd_store_show(_args: argparse.Namespace) -> int:
    repository = _repository()
    store = repository.store()
    value = {
        "configured": repository.load_config()["object_store"]["root"],
        "effective": store.root,
        "backend": store.kind,
        "overridden": bool(os.environ.get("CGA_OBJECT_STORE")),
    }
    if _json_output():
        _print_json(value)
    else:
        print(f"Configured root: {value['configured']}")
        print(f"Effective root: {value['effective']}")
        print(f"Backend: {value['backend']}")
        print(f"Environment override: {'yes' if value['overridden'] else 'no'}")
    return 0


def cmd_store_set(args: argparse.Namespace) -> int:
    repository = _repository()
    candidate = ObjectStore(args.root, repository.root)
    manifest = repository.load_manifest()
    missing = []
    for reference in repository.all_references(manifest):
        try:
            candidate.verify(reference)
        except WorkflowError as error:
            missing.append(str(error))
    if missing and not args.allow_missing:
        raise WorkflowError(
            f"new store is missing {len(missing)} referenced object(s); "
            "copy them first or pass --allow-missing"
        )
    with repository.locked():
        config = repository.load_config()
        config["object_store"]["root"] = args.root
        repository.write_config(config)
    print(candidate.root)
    return 0


def cmd_store_check(_args: argparse.Namespace) -> int:
    repository = _repository()
    store = repository.store()
    manifest = repository.load_manifest()
    references = repository.all_references(manifest)
    if references:
        store.verify(references[0])
    else:
        reference = store.put(canonical_json({}))
        store.verify(reference)
    print(f"OK: {store.root}")
    return 0


def cmd_store_verify(_args: argparse.Namespace) -> int:
    repository = _repository()
    store = repository.store()
    references = {
        reference["key"]: reference
        for reference in repository.all_references(repository.load_manifest())
    }
    for reference in references.values():
        store.verify(reference)
    print(f"OK: {len(references)} reference(s)")
    return 0


def cmd_artifact_add(args: argparse.Namespace) -> int:
    repository = _repository()
    path = Path(args.file).expanduser().resolve()
    with repository.locked():
        manifest = repository.load_manifest()
        artifact_id = repository.register_artifact(
            manifest,
            path,
            args.name or path.name,
            args.kind,
            None,
        )
        repository.write_manifest(manifest)
    print(artifact_id)
    return 0


def cmd_artifact_list(args: argparse.Namespace) -> int:
    repository = _repository()
    manifest = repository.load_manifest()
    artifacts = list(manifest["artifacts"].values())
    if args.chain:
        chain_id, _ = repository.resolve_chain(manifest, args.chain)
        node_ids = {node["id"] for node in _chain_nodes(manifest, chain_id)}
        artifacts = [
            artifact
            for artifact in artifacts
            if artifact.get("source_node") in node_ids
        ]
    artifacts.sort(key=lambda artifact: int(artifact["id"].split("_")[-1]))
    if _json_output():
        _print_json(artifacts)
        return 0
    for artifact in artifacts:
        print(
            f"{artifact['id']}  {artifact['kind']}  {artifact['size']:>10}  "
            f"{artifact['logical_name']}  {artifact['key']}"
        )
    return 0


def _artifact(
    manifest: dict[str, Any], artifact_id: str
) -> dict[str, Any]:
    artifact = manifest["artifacts"].get(artifact_id)
    if not isinstance(artifact, dict):
        raise WorkflowError(f"unknown artifact: {artifact_id!r}")
    return artifact


def cmd_artifact_show(args: argparse.Namespace) -> int:
    _print_json(_artifact(_repository().load_manifest(), args.artifact))
    return 0


def cmd_artifact_verify(args: argparse.Namespace) -> int:
    repository = _repository()
    manifest = repository.load_manifest()
    if args.artifact:
        artifacts = [_artifact(manifest, args.artifact)]
    else:
        artifacts = list(manifest["artifacts"].values())
    for artifact in artifacts:
        repository.store().verify(artifact)
    print(f"OK: {len(artifacts)} artifact(s)")
    return 0


def cmd_artifact_path(args: argparse.Namespace) -> int:
    repository = _repository()
    artifact = _artifact(repository.load_manifest(), args.artifact)
    print(repository.store().location(artifact["key"]))
    return 0


def cmd_artifact_materialize(args: argparse.Namespace) -> int:
    repository = _repository()
    artifact = _artifact(repository.load_manifest(), args.artifact)
    output = args.output or artifact.get("filename") or args.artifact
    destination = Path(output).expanduser().resolve()
    repository.store().materialize(artifact, destination)
    print(destination)
    return 0


def _source_metadata(repository: Repository) -> dict[str, Any]:
    value = os.environ.get("CGA_SOURCE_FILE")
    raw_line = os.environ.get("CGA_SOURCE_LINE")
    if not value or not raw_line:
        return {}
    try:
        start = int(raw_line)
    except ValueError:
        return {}
    path = Path(value).expanduser().resolve()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    if start < 1 or start > len(lines):
        return {}
    end = start
    while end < len(lines) and lines[end - 1].rstrip().endswith("\\"):
        end += 1
    try:
        display_path = str(path.relative_to(repository.root))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "start_line": start,
        "end_line": end,
        "excerpt": "\n".join(lines[start - 1:end]),
    }


def _timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _run_filter(
    command: list[str], environment: dict[str, str], input_data: bytes
) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
    except OSError as error:
        raise WorkflowError(f"cannot run {command[0]!r}: {error}") from error
    transcript = bytearray()

    def drain_stderr() -> None:
        assert process.stderr is not None
        while block := process.stderr.read1(8192):
            transcript.extend(block)
            binary = getattr(sys.stderr, "buffer", None)
            if binary is not None:
                binary.write(block)
                binary.flush()
            else:
                sys.stderr.write(block.decode("utf-8", "replace"))
                sys.stderr.flush()

    thread = threading.Thread(target=drain_stderr)
    thread.start()
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        process.stdin.write(input_data)
    except BrokenPipeError:
        pass
    finally:
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
    output = process.stdout.read()
    process.stdout.close()
    returncode = process.wait()
    thread.join()
    process.stderr.close()
    return returncode, output, bytes(transcript)


def _execution_metadata(
    repository: Repository,
    started_at: str,
    started_monotonic: float,
    exit_code: int,
    transcript: bytes,
) -> dict[str, Any]:
    execution: dict[str, Any] = {
        "started_at": started_at,
        "finished_at": _timestamp(),
        "duration_seconds": round(time.monotonic() - started_monotonic, 6),
        "exit_code": exit_code,
    }
    if transcript:
        execution["transcript"] = repository.store().put(transcript)
    return execution


def _capture_dashboard(command: list[str]) -> None:
    dump = os.environ.get("CGA_DASHBOARD_DUMP")
    executable = shutil.which("cga")
    if not dump or not executable:
        return
    for attempt in range(3):
        completed = subprocess.run(
            [
                executable,
                "view",
                "--dump",
                dump,
                "--capture",
                "--label",
                " ".join(command),
            ]
        )
        if completed.returncode == 0:
            return
        if attempt < 2:
            time.sleep(0.25)
    print(
        "WARNING: cga command succeeded, but dashboard capture failed: "
        + " ".join(command),
        file=sys.stderr,
    )


def cmd_run(args: argparse.Namespace) -> int:
    repository = _repository()
    normalized_tags = taglib.normalize(args.tag)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise WorkflowError("internal run command requires an executable")
    with repository.locked():
        manifest = repository.load_manifest()
        current = repository.head_chain()
        if current:
            chain_id, chain = repository.resolve_chain(manifest, current)
            state = repository.load_state(
                repository.state_reference(manifest, chain)
            )
        else:
            chain_id = ""
            chain = {}
            state = {}
        environment = os.environ.copy()
        environment["CGA_SESSION"] = str(repository.current_path)
        environment["CGAST_SESSION"] = str(repository.current_path)
        environment["CGA_WORKFLOW_ROOT"] = str(repository.root)
        environment["CGA_WORKFLOW_ACTIVE"] = "1"
        source = _source_metadata(repository)
        display_command = ["cga", args.display_token]
        component_arguments = command[1:]
        if args.display_action:
            display_command.append(args.display_action)
        elif component_arguments and not component_arguments[0].startswith("-"):
            display_command.append(component_arguments[0])
            component_arguments = component_arguments[1:]
        for raw_tag in args.tag:
            display_command.extend(["--tag", raw_tag])
        display_command.extend(component_arguments)
        started_at = _timestamp()
        started_monotonic = time.monotonic()
        try:
            returncode, output, transcript = _run_filter(
                command, environment, canonical_json(state)
            )
        except WorkflowError as error:
            execution = _execution_metadata(
                repository,
                started_at,
                started_monotonic,
                127,
                str(error).encode(),
            )
            repository.record_attempt(
                manifest,
                current,
                display_command,
                args.source_step,
                execution,
                source,
                str(error),
                normalized_tags,
            )
            raise
        execution = _execution_metadata(
            repository,
            started_at,
            started_monotonic,
            returncode,
            transcript,
        )
        if returncode != 0:
            attempt = repository.record_attempt(
                manifest,
                current,
                display_command,
                args.source_step,
                execution,
                source,
                f"command exited with status {returncode}",
                normalized_tags,
            )
            if os.environ.get("CGA_QUIET") != "1":
                print(f"CGAST attempt: {attempt}", file=sys.stderr)
            return returncode
        try:
            updated = json.loads(output)
        except json.JSONDecodeError as error:
            repository.record_attempt(
                manifest,
                current,
                display_command,
                args.source_step,
                execution,
                source,
                f"invalid CGAST JSON: {error}",
                normalized_tags,
            )
            raise WorkflowError(
                f"{args.display_token} produced invalid CGAST JSON: {error}"
            ) from error
        if not isinstance(updated, dict):
            repository.record_attempt(
                manifest,
                current,
                display_command,
                args.source_step,
                execution,
                source,
                "component produced a non-object CGAST",
                normalized_tags,
            )
            raise WorkflowError(
                f"{args.display_token} produced a non-object CGAST"
            )
        if current:
            node = repository.record_state(
                manifest,
                chain_id,
                chain,
                updated,
                display_command,
                args.source_step,
                execution,
                source,
                normalized_tags,
            )
        else:
            atomic_write(repository.current_path, canonical_json(updated))
            node = "untracked"
    if os.environ.get("CGA_QUIET") != "1":
        print(f"CGAST node: {node}", file=sys.stderr)
    _capture_dashboard(display_command)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cga", description="Persistent CGA workflow management"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser(
        "init",
        help="initialize a .cga workflow",
    )
    command.add_argument(
        "directory", nargs="?", default=".",
        help="workflow directory to initialize (default: current directory)",
    )
    command.add_argument(
        "--store",
        help="filesystem path or HTTP object-store root; overrides CGA_OBJECT_STORE",
    )
    command.set_defaults(func=cmd_init)

    sub.add_parser("root", help="print the workflow root").set_defaults(func=cmd_root)
    sub.add_parser("status", help="summarize the workflow").set_defaults(
        func=cmd_status
    )
    sub.add_parser("doctor", help="validate workflow metadata and objects").set_defaults(
        func=cmd_doctor
    )

    chain = sub.add_parser("chain", aliases=["cn"], help="manage immutable chains")
    chain_sub = chain.add_subparsers(dest="chain_command", required=True)
    command = chain_sub.add_parser("start")
    command.add_argument("--from", dest="from_revision")
    command.add_argument("--name")
    command.set_defaults(func=cmd_chain_start)
    chain_sub.add_parser("list", aliases=["ls"]).set_defaults(func=cmd_chain_list)
    chain_sub.add_parser("current").set_defaults(func=cmd_chain_current)
    command = chain_sub.add_parser("switch")
    command.add_argument("chain")
    command.set_defaults(func=cmd_chain_switch)
    command = chain_sub.add_parser("show")
    command.add_argument("-v", "--verbose", action="store_true")
    command.add_argument("chain", nargs="?")
    command.set_defaults(func=cmd_chain_show)
    command = chain_sub.add_parser("rename")
    command.add_argument("chain")
    command.add_argument("name")
    command.set_defaults(func=cmd_chain_rename)

    state = sub.add_parser("state", aliases=["st"], help="inspect CGAST states")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    command = state_sub.add_parser("show")
    command.add_argument("--raw", action="store_true")
    command.add_argument("revision", nargs="?")
    command.set_defaults(func=cmd_state_show)
    command = state_sub.add_parser("diff")
    command.add_argument("left")
    command.add_argument("right")
    command.set_defaults(func=cmd_state_diff)
    command = state_sub.add_parser("validate")
    command.add_argument("revision", nargs="?")
    command.set_defaults(func=cmd_state_validate)
    command = state_sub.add_parser("export")
    command.add_argument("revision", nargs="?")
    command.add_argument("-o", "--output", required=True)
    command.set_defaults(func=cmd_state_export)
    command = state_sub.add_parser("import")
    command.add_argument("file")
    command.add_argument("--name")
    command.set_defaults(func=cmd_state_import)

    step = sub.add_parser("step", help="inspect individual workflow steps")
    step_sub = step.add_subparsers(dest="step_command", required=True)
    command = step_sub.add_parser("show")
    command.add_argument("-v", "--verbose", action="store_true")
    command.add_argument("node")
    command.set_defaults(func=cmd_step_show)
    command = step_sub.add_parser("diff")
    command.add_argument("left")
    command.add_argument("right")
    command.set_defaults(func=cmd_state_diff)

    command = sub.add_parser("log", help="show chronological command history")
    command.add_argument("--all", action="store_true")
    command.add_argument("-n", "--limit", type=int)
    command.set_defaults(func=cmd_log)

    tree = sub.add_parser("tree", help="display the workflow forest")
    tree_sub = tree.add_subparsers(dest="tree_command", required=True)
    command = tree_sub.add_parser("show")
    command.add_argument("-v", "--verbose", action="store_true")
    command.add_argument("--control-flow", action="store_true")
    command.add_argument(
        "--format",
        choices=("text", "markdown", "dot", "html", "pdf"),
        default="text",
    )
    command.add_argument("-o", "--output")
    command.set_defaults(func=cmd_tree_show)

    config = sub.add_parser("config", help="manage workflow configuration")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("list").set_defaults(func=cmd_config_list)
    command = config_sub.add_parser("get")
    command.add_argument("key")
    command.set_defaults(func=cmd_config_get)
    command = config_sub.add_parser("set")
    command.add_argument("key")
    command.add_argument("value")
    command.set_defaults(func=cmd_config_set)
    command = config_sub.add_parser("unset")
    command.add_argument("key")
    command.set_defaults(func=cmd_config_unset)
    config_sub.add_parser("path").set_defaults(func=cmd_config_path)

    store = sub.add_parser("store", help="manage the content-addressed store")
    store_sub = store.add_subparsers(dest="store_command", required=True)
    store_sub.add_parser("show").set_defaults(func=cmd_store_show)
    command = store_sub.add_parser("set")
    command.add_argument("root")
    command.add_argument("--allow-missing", action="store_true")
    command.set_defaults(func=cmd_store_set)
    store_sub.add_parser("check").set_defaults(func=cmd_store_check)
    store_sub.add_parser("verify").set_defaults(func=cmd_store_verify)

    artifact = sub.add_parser("artifact", help="manage durable artifacts")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    command = artifact_sub.add_parser("add")
    command.add_argument("file")
    command.add_argument("--name")
    command.add_argument("--kind", default="file")
    command.set_defaults(func=cmd_artifact_add)
    command = artifact_sub.add_parser("list")
    command.add_argument("chain", nargs="?")
    command.set_defaults(func=cmd_artifact_list)
    command = artifact_sub.add_parser("show")
    command.add_argument("artifact")
    command.set_defaults(func=cmd_artifact_show)
    command = artifact_sub.add_parser("verify")
    command.add_argument("artifact", nargs="?")
    command.set_defaults(func=cmd_artifact_verify)
    command = artifact_sub.add_parser("path")
    command.add_argument("artifact")
    command.set_defaults(func=cmd_artifact_path)
    command = artifact_sub.add_parser("materialize")
    command.add_argument("artifact")
    command.add_argument("-o", "--output")
    command.set_defaults(func=cmd_artifact_materialize)

    command = sub.add_parser("run", help=argparse.SUPPRESS)
    command.add_argument("--display-token", required=True)
    command.add_argument("--display-action")
    command.add_argument("--source-step", default="interactive")
    command.add_argument("--tag", action="append", default=[])
    command.add_argument("command", nargs=argparse.REMAINDER)
    command.set_defaults(func=cmd_run)
    return enhance_parser(parser, "")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        function: Callable[[argparse.Namespace], int] = args.func
        return function(args)
    except WorkflowError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

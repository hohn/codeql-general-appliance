#!/usr/bin/env python3
"""Manage immutable whole-CGAST snapshots for the sample-05-i workflow."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "next_chain_id": 0,
            "active_chain": None,
            "head": None,
            "chains": {},
            "nodes": {},
        }
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    content = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    _atomic_write(path, content)


def _validated_cgast(path: Path) -> bytes:
    content = path.read_bytes()
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"CGAST must be a JSON object: {path}")
    return content


def _safe_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return token or "step"


class History:
    def __init__(self, history_dir: Path, session: Path) -> None:
        self.history_dir = history_dir
        self.session = session
        self.nodes_dir = history_dir / "nodes"
        self.manifest_path = history_dir / "manifest.json"
        self.lock_path = history_dir / ".lock"

    def locked(self):
        self.history_dir.mkdir(parents=True, exist_ok=True)
        lock = self.lock_path.open("a+")
        fcntl.flock(lock, fcntl.LOCK_EX)
        return lock

    def start(self, parent: str | None) -> str:
        with self.locked():
            manifest = _load_manifest(self.manifest_path)
            chain_id = manifest["next_chain_id"]
            if parent:
                try:
                    parent_metadata = manifest["nodes"][parent]
                except KeyError as error:
                    raise ValueError(f"unknown parent node: {parent}") from error
                base = _validated_cgast(self.history_dir / parent_metadata["snapshot"])
            else:
                base = b"{}\n"

            chain_key = str(chain_id)
            manifest["chains"][chain_key] = {
                "id": chain_id,
                "root_parent": parent,
                "next_sequence": 0,
            }
            manifest["next_chain_id"] = chain_id + 1
            manifest["active_chain"] = chain_id
            manifest["head"] = parent
            _atomic_write(self.session, base)
            _write_manifest(self.manifest_path, manifest)
        return f"cga_{chain_id}"

    def record(self, output: Path, source_step: str, command: list[str]) -> str:
        content = _validated_cgast(output)
        with self.locked():
            manifest = _load_manifest(self.manifest_path)
            chain_id = manifest["active_chain"]
            if chain_id is None:
                _atomic_write(self.session, content)
                return "untracked"

            chain = manifest["chains"][str(chain_id)]
            sequence = chain["next_sequence"]
            tool = _safe_token(command[0][3:] if command[0].startswith("cga") else command[0])
            action = _safe_token(command[1] if len(command) > 1 else "run")
            node_id = f"cga_{chain_id}_{tool}_{action}_{sequence}"
            snapshot = self.nodes_dir / f"{node_id}.json"
            if snapshot.exists():
                raise ValueError(f"node already exists: {node_id}")

            _atomic_write(snapshot, content)
            manifest["nodes"][node_id] = {
                "id": node_id,
                "chain_id": chain_id,
                "sequence": sequence,
                "parent": manifest["head"],
                "source_step": source_step,
                "command": command,
                "snapshot": str(snapshot.relative_to(self.history_dir)),
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            chain["next_sequence"] = sequence + 1
            manifest["head"] = node_id
            _atomic_write(self.session, content)
            _write_manifest(self.manifest_path, manifest)
        return node_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", type=Path, required=True)
    parser.add_argument("--session", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--parent")

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--output", type=Path, required=True)
    record_parser.add_argument("--source-step", required=True)
    record_parser.add_argument("command", nargs=argparse.REMAINDER)

    arguments = parser.parse_args()
    history = History(arguments.history_dir, arguments.session)
    if arguments.operation == "start":
        print(history.start(arguments.parent))
    else:
        command = arguments.command
        if command[:1] == ["--"]:
            command = command[1:]
        if not command:
            parser.error("record requires a command after --")
        print(history.record(arguments.output, arguments.source_step, command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
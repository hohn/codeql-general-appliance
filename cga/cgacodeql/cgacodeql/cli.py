"""Validate the CodeQL executable, host platform, and installed packs."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path

import cgast
import workflow
from command_help import enhance_parser

CHECK_KEY = "cgacodeql-check"
HISTORY_KEY = "cgacodeql-history"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _capture(argv: list[str]) -> str:
    try:
        completed = subprocess.run(
            argv, check=True, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise workflow.WorkflowError(f"command not found: {argv[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip()
        raise workflow.WorkflowError(
            f"command failed with exit {exc.returncode}: {argv!r}"
            + (f": {detail}" if detail else "")) from exc
    return completed.stdout


def _pack_path(codeql: Path, value: str) -> Path:
    if "@" not in value:
        raise workflow.WorkflowError(
            f"pack must have owner/name@version form: {value}")
    name, version = value.rsplit("@", 1)
    parts = name.split("/")
    if len(parts) != 2:
        raise workflow.WorkflowError(
            f"pack must have owner/name@version form: {value}")
    owner = workflow.require_safe_name(parts[0], "pack owner")
    pack = workflow.require_safe_name(parts[1], "pack name")
    version = workflow.require_safe_name(version, "pack version")
    return codeql.parent / "qlpacks" / owner / pack / version / "qlpack.yml"


def cmd_check(state, args) -> None:
    codeql = Path(
        os.environ.get("CGA_CODEQL", args.codeql or "codeql")).expanduser()
    executable = str(codeql.resolve()) if codeql.exists() else str(codeql)
    actual_version = _capture(
        [executable, "version", "--format=terse"]).strip()
    if args.version and actual_version != args.version:
        raise workflow.WorkflowError(
            f"CodeQL {args.version} is required; found {actual_version}")
    actual_system = platform.system()
    actual_machine = platform.machine()
    if args.system and actual_system != args.system:
        raise workflow.WorkflowError(
            f"host system {args.system} is required; found {actual_system}")
    if args.machine and actual_machine not in args.machine:
        raise workflow.WorkflowError(
            f"host machine must be one of {args.machine}; found {actual_machine}")
    required = []
    paths = [Path(value).expanduser().resolve() for value in args.require_file]
    paths.extend(_pack_path(Path(executable), value) for value in args.pack)
    for path in paths:
        if not path.is_file():
            raise workflow.WorkflowError(f"required file is missing: {path}")
        required.append({"path": cgast.rel(path), "sha256": digest(path)})
    out = cgast.new_tempfile(prefix="cgacodeql-check.", suffix=".json")
    workflow.write_json(out, {
        "version": 1,
        "codeql": executable,
        "codeql_version": actual_version,
        "host": {
            "system": actual_system,
            "machine": actual_machine,
            "release": platform.release(),
        },
        "required_files": required,
    })
    cgast.set_path(state, CHECK_KEY, out)
    state.setdefault(HISTORY_KEY, []).append({
        "check": cgast.rel(out),
        "codeql_version": actual_version,
    })
    cgast.info(f"cgacodeql: check passed -> {cgast.rel(out)}")


def cmd_info(state, _args) -> None:
    path = cgast.get_path(state, CHECK_KEY)
    cgast.info(
        f"cgacodeql: check={cgast.rel(path) if path else '(none)'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cga codeql")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--codeql")
    check.add_argument("--version")
    check.add_argument("--system")
    check.add_argument("--machine", action="append", default=[])
    check.add_argument("--pack", action="append", default=[])
    check.add_argument("--require-file", action="append", default=[])
    check.set_defaults(func=cmd_check)
    sub.add_parser("info").set_defaults(func=cmd_info)
    return enhance_parser(parser, "cq")


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    state = cgast.read()
    try:
        args.func(state, args)
    except workflow.WorkflowError as exc:
        cgast.die(f"cgacodeql: {exc}", 2)
    cgast.write(state)
    return 0

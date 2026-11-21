"""Recorded database-building porcelain over preparation filters."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse
import uuid

import cgast
import prep_llm
from workflow import SAFE_NAME, WorkflowError, load_json, require_safe_name, write_json


COLLECTION = Path(__file__).resolve().parents[2]
KEY = "cgaassist-database"
TOOLS = {
    "source": "cgasp", "plan": "cgadbplan", "build": "cgadb",
    "catalog": "cgacatalog",
}
PREFIXES = ("cgasp-", "cgadb-", "cgadbplan-", "cgacatalog-", "cgacodeql-")


def workspace(state: dict) -> dict:
    root = Path(os.environ["CGA_WORKFLOW_ROOT"]).resolve()
    scratch = root / ".cga/tmp/database-build"
    scratch.mkdir(parents=True, exist_ok=True)
    checkpoint = scratch / "checkpoint.json"
    if checkpoint.is_file():
        saved = load_json(checkpoint)
        if (saved.get("schema") != "cga.assist-database.v1" or
                saved.get("workflow") != str(root) or
                not isinstance(saved.get("state"), dict)):
            raise WorkflowError("database checkpoint belongs to a different workflow")
        generation = state.get(KEY, {}).get("generation")
        previous = saved["state"].get(KEY, {}).get("generation")
        if generation != previous:
            if generation != saved.get("base_generation"):
                raise WorkflowError(
                    "database checkpoint belongs to different preparation history")
            state.update(saved["state"])
    record = state.setdefault(KEY, {
        "scratch": str(scratch), "checkpoint": str(checkpoint),
        "exports": [],
    })
    record["base_generation"] = record.get("generation")
    record["generation"] = uuid.uuid4().hex
    return record


def checkpoint(state: dict) -> None:
    record = state[KEY]
    saved = {
        "schema": "cga.assist-database.v1",
        "workflow": str(Path(os.environ["CGA_WORKFLOW_ROOT"]).resolve()),
        "base_generation": record["base_generation"],
        "state": {key: value for key, value in state.items()
                  if key == KEY or key.startswith(PREFIXES)},
    }
    target = Path(record["checkpoint"])
    temporary = target.with_suffix(".tmp")
    write_json(temporary, saved)
    temporary.replace(target)


def tool(state: dict, component: str, arguments: list[str]) -> None:
    name = TOOLS[component]
    binary = COLLECTION / name / "bin" / name
    completed = subprocess.run(
        [str(binary), *arguments], input=json.dumps(state),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.stderr:
        cgast.info(completed.stderr.rstrip())
    if completed.returncode:
        raise WorkflowError(
            f"{name} failed (exit {completed.returncode}): {completed.stderr.strip()}")
    try:
        updated = json.loads(completed.stdout)
    except ValueError as exc:
        raise WorkflowError(f"{name} returned invalid CGAST") from exc
    if not isinstance(updated, dict):
        raise WorkflowError(f"{name} returned a non-object CGAST")
    for key in ("cgasp-plan", "cgasp-sources", "cgadbplan-jobs", "cgadb-records",
                "cgacatalog-catalog", "cgacatalog-manifest", "cgacodeql-check"):
        if key in updated:
            updated[key] = str(cgast.resolve(updated[key]))
    state.clear()
    state.update(updated)
    checkpoint(state)


def _named(value: str, number: int) -> tuple[str, str]:
    if "=" in value and SAFE_NAME.fullmatch(value.split("=", 1)[0]):
        label, value = value.split("=", 1)
    else:
        label = f"version-{number}"
    require_safe_name(label, "version label")
    if not value:
        raise WorkflowError("a version reference or archive location is required")
    return label, value


def fetch(state: dict, args, prompt) -> None:
    record = workspace(state)
    if record.get("jobs"):
        raise WorkflowError("sources are fixed after planning; use another preparation workflow")
    git = args.git
    archives = args.archive
    if not git and not archives:
        value = prompt("Git repository URL or archive URL/path")
        if urlparse(value).path.lower().endswith(
                (".zip", ".tar", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
            archives = [value]
        else:
            git = value
    if archives and args.ref:
        raise WorkflowError("--ref applies to Git sources, not archives")
    if git:
        location = urlparse(git).path if "://" in git else git.split(":", 1)[-1]
        parts = location.rstrip("/").removesuffix(".git").split("/")
        repo = args.repo or parts[-1]
        owner = args.owner or (parts[-2] if len(parts) > 1 and parts[-2] else "local")
        versions = [_named(value, index) for index, value in
                    enumerate(args.ref or ["current=HEAD"], 1)]
    else:
        repo = args.repo or prompt("Upstream repository/project name")
        owner = args.owner or prompt("Repository owner")
        versions = [_named(value, index) for index, value in enumerate(archives, 1)]
    repo = require_safe_name(repo, "repository")
    owner = require_safe_name(owner, "owner")
    language = args.language or prompt("CodeQL language (for example cpp)")
    require_safe_name(language, "language")
    if len({label for label, _value in versions}) != len(versions):
        raise WorkflowError("version labels must be unique")
    items = []
    for label, value in versions:
        source = ({"strategy": "git", "url": git, "ref": value} if git else
                  {"strategy": "archive", "url": value if urlparse(value).scheme
                   else str(Path(value).expanduser().resolve())})
        items.append({
            "id": f"{repo}--{label}", "owner": owner, "repo": repo,
            "upstream_repo": repo, "language": language,
            "variant": label, "version": value if git else label,
            "source": source, "dependencies": [],
        })
    manifest = Path(record["scratch"]) / "source-inputs.json"
    document = {"version": 1, "items": items}
    if manifest.exists() and load_json(manifest) != document:
        raise WorkflowError("source choices changed; use another preparation workflow")
    write_json(manifest, document)
    record["source_inputs"] = str(manifest)
    checkpoint(state)
    arguments = [
        "fetch", "--manifest", str(manifest),
        "--output-dir", str(Path(record["scratch"]) / "sources"),
        "--results", str(Path(record["scratch"]) / "source-results.json"),
    ]
    if args.use_llm:
        arguments += ["--use-llm", "--llm-attempts", str(args.llm_attempts)]
    tool(state, "source", arguments)
    cgast.info("Next: cga a d build")


def build(state: dict, args, prompt) -> None:
    record = workspace(state)
    sources = cgast.require_path(state, "cgasp-sources", "run cga a d fetch first")
    if not record.get("jobs"):
        modes = args.mode or prompt("Build modes: bm-none, trace, or both (space-separated)").split()
        if modes == ["both"]:
            modes = ["bm-none", "trace"]
        if not modes or set(modes) - {"bm-none", "trace"} or len(modes) != len(set(modes)):
            raise WorkflowError("choose distinct bm-none and/or trace modes")
        command = args.build_command
        if "trace" in modes and not command and not args.use_llm:
            command = prompt("Trace build command (for example ./build.sh)")
        document = load_json(sources)
        if command:
            for item in document["items"]:
                item["build_command"] = command
        prepared = Path(record["scratch"]) / f"build-inputs-{uuid.uuid4().hex}.json"
        write_json(prepared, document)
        cgast.set_path(state, "cgasp-sources", prepared)
        job_dir = Path(record["scratch"]) / "jobs" / uuid.uuid4().hex
        arguments = ["--output-dir", str(job_dir)]
        for mode in modes:
            arguments += ["--mode", mode]
        if args.use_llm:
            arguments.append("--use-llm")
        tool(state, "plan", arguments)
        record = state[KEY]
        record.update(jobs=str(job_dir / "jobs.json"), modes=modes, command=command,
                      use_llm=args.use_llm)
        checkpoint(state)
    elif ((args.mode and args.mode != record["modes"]) or
          (args.build_command and args.build_command != record["command"])):
        raise WorkflowError("build choices are fixed; use another preparation workflow")
    jobs = load_json(Path(record["jobs"]))["items"]
    for entry in jobs:
        records = cgast.get_path(state, "cgadb-records")
        existing = load_json(records)["items"] if records else []
        built = next((item for item in existing
                      if item["id"] == entry["id"] and item["status"] == "built"), None)
        if built:
            archive = Path(built["archive"])
            with archive.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != built["sha256"]:
                raise WorkflowError(f"completed database archive changed: {archive}")
            cgast.info(f"  VERIFIED {entry['id']} (already built)")
            continue
        arguments = [
            "--job", str(cgast.resolve(entry["job"])),
            "--trace" if entry["mode"] == "trace" else "--bm-none",
            "--output-dir", str(Path(record["scratch"]) / "databases" / uuid.uuid4().hex),
        ]
        if args.use_llm or record["use_llm"]:
            arguments += ["--use-llm", "--llm-attempts", str(args.llm_attempts)]
        tool(state, "build", arguments)
    cgast.info("Next: cga a d index")


def index(state: dict, args) -> None:
    record = workspace(state)
    if not record.get("jobs"):
        raise WorkflowError("run cga a d build before indexing")
    expected = {item["id"] for item in load_json(Path(record["jobs"]))["items"]}
    records = cgast.require_path(state, "cgadb-records", "run cga a d build first")
    built = {item["id"] for item in load_json(records)["items"] if item["status"] == "built"}
    if not args.allow_partial and expected - built:
        raise WorkflowError(
            "build matrix is incomplete; resume cga a d build or use --allow-partial")
    root = Path(record["scratch"]) / "index" / uuid.uuid4().hex
    tool(state, "catalog", [
        "create", "--output", str(root / "metadata.sql"),
        "--manifest", str(root / "manifest.json"),
    ])
    tool(state, "catalog", [
        "verify", "--catalog", str(root / "metadata.sql"),
        "--manifest", str(root / "manifest.json"),
    ])
    state[KEY]["indexed_jobs"] = sorted(built)
    checkpoint(state)
    cgast.info("Next: cga a d export DIRECTORY")


def export(state: dict, args, prompt) -> None:
    record = workspace(state)
    records = cgast.require_path(state, "cgadb-records", "run cga a d build first")
    built = {item["id"] for item in load_json(records)["items"] if item["status"] == "built"}
    if built != set(record.get("indexed_jobs", [])):
        raise WorkflowError("run cga a d index to index the current completed builds")
    directory = args.directory or prompt("Export collection directory")
    tool(state, "catalog", ["export", directory, *(
        ["--base-url", args.base_url] if args.base_url else [])])
    state[KEY]["exports"].append(str(Path(directory).expanduser().resolve()))
    checkpoint(state)
    cgast.info("Serving is separate: cga ds start --directory DIRECTORY --port PORT --log FILE")


def add_parser(groups, prompt) -> None:
    parser = groups.add_parser("database-build", aliases=["d"])
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch")
    inputs = fetch_parser.add_mutually_exclusive_group()
    inputs.add_argument("--git")
    inputs.add_argument("--archive", action="append", metavar="LABEL=URL_OR_PATH")
    fetch_parser.add_argument("--ref", action="append", metavar="LABEL=REF")
    fetch_parser.add_argument("--owner")
    fetch_parser.add_argument("--repo")
    fetch_parser.add_argument("--language")
    fetch_parser.set_defaults(func=lambda state, args: fetch(state, args, prompt))
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--mode", action="append", choices=("bm-none", "trace"))
    build_parser.add_argument("--command", dest="build_command")
    build_parser.set_defaults(func=lambda state, args: build(state, args, prompt))
    for command in (fetch_parser, build_parser):
        command.add_argument("--use-llm", action="store_true")
        command.add_argument("--llm-attempts", type=prep_llm.attempts, default=3)
    index_parser = commands.add_parser("index")
    index_parser.add_argument("--allow-partial", action="store_true")
    index_parser.set_defaults(func=index)
    export_parser = commands.add_parser("export")
    export_parser.add_argument("directory", nargs="?")
    export_parser.add_argument("--base-url")
    export_parser.set_defaults(func=lambda state, args: export(state, args, prompt))

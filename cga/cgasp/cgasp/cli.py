"""Plan and materialize source packages from cgacv work items."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import urlopen

import cgast
import prep_llm
import workflow
from command_help import enhance_parser

COMPONENT = "cgasp"
DEFAULT_PORT = 8502
WORK_KEY = "cgacv-work-items"
PLAN_KEY = "cgasp-plan"
SOURCES_KEY = "cgasp-sources"
HISTORY_KEY = "cgasp-history"


def tree_digest(root: Path) -> str:
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode()
        result.update(len(relative).to_bytes(8, "big"))
        result.update(relative)
        if path.is_symlink():
            data = os.readlink(path).encode()
            kind = b"L"
        elif path.is_file():
            data = path.read_bytes()
            kind = b"F"
        else:
            data = b""
            kind = b"D"
        result.update(kind)
        result.update(len(data).to_bytes(8, "big"))
        result.update(data)
    return result.hexdigest()


def _items(state, manifest: str | None = None) -> list[dict]:
    path = (Path(manifest).expanduser().resolve() if manifest else
            cgast.require_path(state, WORK_KEY,
                               "pass --manifest FILE or run 'cga cv expand' first"))
    doc = workflow.load_json(path)
    items = doc.get("items")
    if not isinstance(items, list) or not items:
        raise workflow.WorkflowError("cgacv work-items contains no items")
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise workflow.WorkflowError("source manifest items must be objects")
        item_id = workflow.require_safe_name(item.get("id"), "source id")
        if item_id in seen:
            raise workflow.WorkflowError(f"duplicate source id: {item_id}")
        seen.add(item_id)
        if manifest and isinstance(item.get("source"), dict):
            source = item["source"]
            if source.get("strategy") == "archive":
                value = source.get("url", "")
                if not urlparse(value).scheme:
                    source["url"] = str((path.parent / value).resolve())
    return items


def make_plan(items: list[dict]) -> dict:
    planned = []
    for item in items:
        source = item.get("source")
        if not isinstance(source, dict):
            raise workflow.WorkflowError(f"{item.get('id')}: missing source")
        strategy = source.get("strategy")
        if strategy == "git":
            commands = [
                ["git", "clone", "--no-checkout", source["url"], "{source_dir}"],
                ["git", "-C", "{source_dir}", "checkout", "--detach", source["ref"]],
            ]
        elif strategy == "debian-dsc":
            name = unquote(Path(urlparse(source["url"]).path).name)
            if not name.endswith(".dsc") or not workflow.SAFE_NAME.fullmatch(name):
                raise workflow.WorkflowError(
                    f"{item.get('id')}: debian-dsc URL must end in a safe .dsc filename")
            commands = [
                ["dget", "--download-only", source["url"]],
                ["dpkg-source", "-x", name, "{source_dir}"],
            ]
        elif strategy == "archive":
            if not isinstance(source.get("url"), str) or not source["url"]:
                raise workflow.WorkflowError(
                    f"{item.get('id')}: archive requires url or local path")
            commands = []
        else:
            raise workflow.WorkflowError(
                f"{item.get('id')}: unsupported source strategy {strategy!r}")
        planned.append({
            **item,
            "fetch_commands": commands,
            "dependency_argv": item.get("dependencies", []),
        })
    return {"version": 1, "count": len(planned), "items": planned}


def cmd_plan(state, args) -> None:
    plan = make_plan(_items(state, getattr(args, "manifest", None)))
    out = cgast.new_tempfile(prefix="cgasp-plan.", suffix=".json")
    workflow.write_json(out, plan)
    cgast.set_path(state, PLAN_KEY, out)
    state.setdefault(HISTORY_KEY, []).append(
        {"plan": cgast.rel(out), "count": plan["count"]})
    cgast.info(f"{COMPONENT}: planned {plan['count']} source package(s) -> "
               f"{cgast.rel(out)}")


def _extract_archive(source: dict, root: Path, destination: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="archive-", dir=root) as raw:
        staging = Path(raw)
        archive = staging / "download"
        value = source["url"]
        if urlparse(value).scheme:
            with urlopen(value) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        else:
            shutil.copyfile(Path(value).expanduser(), archive)
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if source.get("sha256") and actual != source["sha256"]:
            raise workflow.WorkflowError("source archive SHA-256 mismatch")
        extracted = staging / "extracted"
        extracted.mkdir()
        try:
            if zipfile.is_zipfile(archive):
                with zipfile.ZipFile(archive) as stream:
                    for member in stream.infolist():
                        target = workflow.under(extracted, member.filename)
                        mode = member.external_attr >> 16
                        if stat.S_ISLNK(mode):
                            raise workflow.WorkflowError(
                                f"source ZIP contains a symlink: {member.filename}")
                        if member.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with stream.open(member) as incoming, target.open("wb") as output:
                                shutil.copyfileobj(incoming, output)
                            if mode & 0o111:
                                target.chmod(0o755)
            else:
                with tarfile.open(archive) as stream:
                    stream.extractall(extracted, filter="data")
        except (tarfile.TarError, zipfile.BadZipFile) as exc:
            raise workflow.WorkflowError(f"cannot extract source archive: {exc}") from exc
        entries = list(extracted.iterdir())
        tree = entries[0] if len(entries) == 1 and entries[0].is_dir() else extracted
        tree.rename(destination)
    return actual


def _run_fetch(item: dict, root: Path, destination: Path, runner=None) -> dict:
    run = runner or workflow.run
    source = item["source"]
    strategy = source["strategy"]
    if strategy == "git":
        run(["git", "clone", "--no-checkout", source["url"], str(destination)])
        run(["git", "-C", str(destination), "checkout", "--detach", source["ref"]])
        try:
            commit = subprocess.check_output(
                ["git", "-C", str(destination), "rev-parse", "HEAD"],
                text=True, stderr=subprocess.PIPE).strip()
        except subprocess.CalledProcessError as exc:
            raise workflow.WorkflowError(f"cannot resolve fetched Git commit: {exc.stderr}") from exc
        return {"source": {**source, "requested_ref": source["ref"], "ref": commit},
                "resolved_commit": commit}
    if strategy == "archive":
        return {"archive_sha256": _extract_archive(source, root, destination)}
    staging = workflow.under(root, ".downloads", item["id"])
    staging.mkdir(parents=True, exist_ok=True)
    dsc_name = unquote(Path(urlparse(source["url"]).path).name)
    run(["dget", "--download-only", source["url"]], cwd=staging)
    dsc = workflow.under(staging, dsc_name)
    if not dsc.is_file():
        raise workflow.WorkflowError(f"dget did not produce {dsc}")
    run(["dpkg-source", "-x", str(dsc), str(destination)], cwd=staging)
    return {}


def cmd_fetch(state, args) -> None:
    manifest = getattr(args, "manifest", None)
    plan_path = None if manifest else cgast.get_path(state, PLAN_KEY)
    plan = (workflow.load_json(plan_path) if plan_path else
            make_plan(_items(state, manifest)))
    if plan_path is None:
        plan_path = cgast.new_tempfile(prefix="cgasp-plan.", suffix=".json")
        workflow.write_json(plan_path, plan)
        cgast.set_path(state, PLAN_KEY, plan_path)
        state.setdefault(HISTORY_KEY, []).append(
            {"plan": cgast.rel(plan_path), "count": plan["count"]})
    root = (Path(args.output_dir).expanduser().resolve() if args.output_dir
            else cgast.new_tempdir(prefix="cgasp-sources."))
    root.mkdir(parents=True, exist_ok=True)
    results = []
    errors = 0
    results_path = (Path(args.results).expanduser().resolve()
                    if getattr(args, "results", None) else
                    cgast.new_tempfile(prefix="cgasp-sources.", suffix=".json"))
    previous = (workflow.load_json(results_path).get("items", [])
                if results_path.is_file() and results_path.stat().st_size else [])
    for item in plan["items"]:
        destination = workflow.under(root, item["id"])
        result = {**item, "source_dir": cgast.rel(destination)}
        if args.dry_run:
            result["status"] = "planned"
            cgast.info(f"  PLANNED {item['id']} -> {cgast.rel(destination)}")
        else:
            try:
                if destination.exists():
                    old = next((entry for entry in previous
                                if entry["id"] == item["id"]
                                and entry.get("status") == "ready"), None)
                    original_source = dict(old["source"]) if old else {}
                    if original_source.get("requested_ref"):
                        original_source["ref"] = original_source.pop("requested_ref")
                    if (old and original_source == item["source"] and
                            old.get("source_tree_sha256") == tree_digest(destination)):
                        results.append(old)
                        cgast.info(f"  VERIFIED {item['id']} (already fetched)")
                        continue
                    raise workflow.WorkflowError(f"source destination already exists: {destination}")
                if getattr(args, "use_llm", False):
                    history = []
                    attempt_root = workflow.under(
                        root, ".attempts", item["id"], uuid.uuid4().hex)
                    for number in range(1, args.llm_attempts + 1):
                        attempt = attempt_root / f"{number:03d}"
                        attempt.mkdir(parents=True)
                        candidate = attempt / "source"
                        try:
                            recipe = prep_llm.recipe(
                                {"operation": "fetch", "item": item,
                                 "working_directory": str(attempt)}, attempt,
                                candidate, history)
                            for command in recipe["commands"]:
                                prep_llm.run(command, attempt, attempt / "commands.log")
                            result.update(_run_fetch(
                                item, attempt, candidate,
                                lambda arguments, cwd=None: prep_llm.run(
                                    arguments, cwd or attempt, attempt / "commands.log")))
                            if not candidate.is_dir():
                                raise workflow.WorkflowError(
                                    "acquisition did not create a source directory")
                            candidate.rename(destination)
                            workflow.write_json(attempt / "outcome.json",
                                                {"status": "succeeded"})
                            result["supervision"] = {
                                "attempts": [*history, {
                                    "directory": str(attempt), "status": "succeeded"}]}
                            break
                        except (workflow.WorkflowError, OSError) as exc:
                            history.append(prep_llm.failure(attempt, exc))
                            if number == args.llm_attempts:
                                raise workflow.WorkflowError(
                                    f"LLM acquisition failed after {number} attempts; "
                                    f"see {attempt_root}: {exc}") from exc
                else:
                    result.update(_run_fetch(item, root, destination))
                if not destination.is_dir():
                    raise workflow.WorkflowError(
                        f"source extraction did not create {destination}")
                actual = tree_digest(destination)
                if item.get("source_tree_sha256") and actual != item["source_tree_sha256"]:
                    raise workflow.WorkflowError("fetched source tree hash mismatch")
                result["status"] = "ready"
                result["source_tree_sha256"] = actual
                cgast.info(f"  READY   {item['id']} -> {cgast.rel(destination)}")
            except (workflow.WorkflowError, OSError, ValueError) as exc:
                result["status"] = "error"
                result["error"] = str(exc)
                errors += 1
                cgast.info(f"  ERROR   {item['id']}: {exc}")
        results.append(result)
    out = results_path
    workflow.write_json(out, {"version": 1, "count": len(results),
                              "output_dir": cgast.rel(root), "items": results})
    cgast.set_path(state, SOURCES_KEY, out)
    state.setdefault(HISTORY_KEY, []).append(
        {"sources": cgast.rel(out), "count": len(results),
         "dry_run": bool(args.dry_run)})
    cgast.info(f"{COMPONENT}: source results -> {cgast.rel(out)}")
    if errors:
        cgast.info(f"cgasp: failed acquisition details retained in {out}")
        raise SystemExit(1)


def cmd_adopt(state, args) -> None:
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = workflow.load_json(manifest_path)
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise workflow.WorkflowError(f"{manifest_path}: items must be a non-empty array")
    results = []
    seen = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise workflow.WorkflowError("source manifest items must be objects")
        item_id = workflow.require_safe_name(raw.get("id"), "item id")
        if item_id in seen:
            raise workflow.WorkflowError(f"duplicate source item id: {item_id}")
        seen.add(item_id)
        value = raw.get("source_dir")
        if not isinstance(value, str) or not value:
            raise workflow.WorkflowError(f"{item_id}: missing source_dir")
        source_dir = Path(value).expanduser()
        if not source_dir.is_absolute():
            source_dir = manifest_path.parent / source_dir
        source_dir = source_dir.resolve()
        if not source_dir.is_dir():
            raise workflow.WorkflowError(
                f"{item_id}: source directory does not exist: {source_dir}")
        expected = raw.get("source_tree_sha256")
        actual = tree_digest(source_dir)
        if expected is not None and expected != actual:
            raise workflow.WorkflowError(
                f"{item_id}: source tree hash mismatch: expected {expected}, found {actual}")
        result = {
            **raw,
            "id": item_id,
            "source_dir": cgast.rel(source_dir),
            "source_tree_sha256": actual,
            "status": "ready",
        }
        results.append(result)
        cgast.info(f"  ADOPTED {item_id} <- {cgast.rel(source_dir)}")
    out = cgast.new_tempfile(prefix="cgasp-sources.", suffix=".json")
    workflow.write_json(out, {
        "version": 1,
        "count": len(results),
        "manifest": cgast.rel(manifest_path),
        "items": results,
    })
    cgast.set_path(state, SOURCES_KEY, out)
    state.setdefault(HISTORY_KEY, []).append({
        "sources": cgast.rel(out),
        "count": len(results),
        "operation": "adopt",
    })
    cgast.info(f"{COMPONENT}: adopted {len(results)} local source tree(s) -> "
               f"{cgast.rel(out)}")


def cmd_info(state, _args) -> None:
    cgast.info(f"{COMPONENT}: source package materializer")
    for key in (PLAN_KEY, SOURCES_KEY):
        path = cgast.get_path(state, key)
        cgast.info(f"  {key}: {cgast.rel(path) if path else '(none)'}")


def cmd_serve(_state, _args) -> None:
    import cga_http as C
    from . import serve
    C.serve(COMPONENT, int(os.environ.get("CGA_PREP_CGASP_PORT", DEFAULT_PORT)),
            serve.routes())
    raise SystemExit(0)


def build_parser():
    parser = argparse.ArgumentParser(prog=COMPONENT)
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("plan")
    p.add_argument("--manifest")
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("fetch")
    p.add_argument("--manifest")
    p.add_argument("--results", help="durable source results; verified ready items resume")
    p.add_argument("--output-dir"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--use-llm", action="store_true")
    p.add_argument("--llm-attempts", type=prep_llm.attempts, default=3)
    p.set_defaults(func=cmd_fetch)
    p = sub.add_parser("adopt")
    p.add_argument("--manifest", required=True)
    p.set_defaults(func=cmd_adopt)
    p = sub.add_parser("info"); p.set_defaults(func=cmd_info)
    p = sub.add_parser("serve"); p.set_defaults(func=cmd_serve)
    return enhance_parser(parser, "sp")


def main(argv: list[str]) -> int:
    parser = build_parser()
    if not argv or argv[0] in ("help", "-h", "--help"):
        parser.print_help(sys.stderr); return 0
    args = parser.parse_args(argv)
    state = cgast.read()
    try:
        args.func(state, args)
    except workflow.WorkflowError as exc:
        cgast.die(f"{COMPONENT}: {exc}", 2)
    cgast.write(state)
    return 0

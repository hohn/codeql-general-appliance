"""Build and bundle exactly one CodeQL database."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

import cgast
import database_identity
import prep_llm
import workflow
from command_help import enhance_parser

COMPONENT = "cgadb"
DEFAULT_PORT = 8503
RECORDS_KEY = "cgadb-records"
HISTORY_KEY = "cgadb-history"


def cmd_zip(state, args) -> None:
    database = Path(args.db_dir).resolve()
    output = Path(args.output).resolve()
    if not (database / "codeql-database.yml").is_file():
        raise workflow.WorkflowError(
            f"not a CodeQL database (missing codeql-database.yml): {database}")
    if output.is_relative_to(database):
        raise workflow.WorkflowError("ZIP output must be outside the database")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
            staged = Path(tmp) / "database.zip"
            with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(database.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        archive.write(
                            path, Path(database.name) / path.relative_to(database))
            staged.replace(output)
    except OSError as exc:
        raise workflow.WorkflowError(f"cannot archive {database}: {exc}") from exc
    state.setdefault("cgadb-archives", []).append({
        "database": str(database), "archive": cgast.rel(output),
        "sha256": digest(output),
    })
    cgast.info(f"cgadb: archived {database} -> {output}")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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


def _codeql() -> str:
    return os.environ.get(
        "CGA_DB_CODEQL",
        os.environ.get("CGA_PREP_CGADB_CODEQL", "codeql"))


def _verify_traced_extraction(database: Path) -> dict:
    metadata = database / "codeql-database.yml"
    scan_commands = database / "log" / "extraction_commands.json"
    tracer_log = database / "log" / "build-tracer.log"
    if not metadata.is_file():
        raise workflow.WorkflowError(
            f"cannot verify traced extraction; metadata is missing: {metadata}")
    try:
        metadata_text = metadata.read_text(encoding="utf-8")
    except OSError as exc:
        raise workflow.WorkflowError(
            f"cannot read database metadata {metadata}: {exc}") from exc
    build_modes = re.findall(
        r"(?m)^buildMode:\s*([^#\s]+)", metadata_text)
    if scan_commands.is_file() or any(
            mode in {"none", "autobuild"} for mode in build_modes):
        raise workflow.WorkflowError(
            "trace mode produced a source-scanned database; refusing to "
            "bundle or record it")
    if not tracer_log.is_file():
        raise workflow.WorkflowError(
            "trace mode produced no build-tracer.log; refusing to bundle or "
            "record an unverified database")
    try:
        tracer_text = tracer_log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise workflow.WorkflowError(
            f"cannot read tracer evidence {tracer_log}: {exc}") from exc
    intercepted = tracer_text.count("Intercepted call to")
    if intercepted == 0:
        raise workflow.WorkflowError(
            "trace mode recorded no intercepted processes; refusing to "
            "bundle or record an unverified database")
    return {
        "schema": "cga.trace-verification.v1",
        "status": "verified",
        "tracer_log": str(tracer_log),
        "tracer_log_sha256": digest(tracer_log),
        "intercepted_processes": intercepted,
    }


def _load_records(state) -> list[dict]:
    path = cgast.get_path(state, RECORDS_KEY)
    if not path:
        return []
    document = workflow.load_json(path)
    items = document.get("items")
    if not isinstance(items, list):
        raise workflow.WorkflowError("cgadb records contains no items array")
    return items


def _write_records(state, records: list[dict]) -> Path:
    out = cgast.new_tempfile(prefix="cgadb-records.", suffix=".json")
    workflow.write_json(out, {
        "schema": "cga.database-records.v1",
        "count": len(records),
        "items": records,
    })
    cgast.set_path(state, RECORDS_KEY, out)
    return out


def _catalogue_record(job: dict, archive: Path, tool_version: str) -> dict:
    source = job.get("source", {})
    commit = source.get("ref") if isinstance(source, dict) else ""
    qualifiers = " ".join(
        value for value in (
            job.get("extraction_mode", ""), job.get("architecture", ""))
        if value)
    projname = (
        f"{job['owner']}/{job.get('package', job['base_repo'])}@"
        f"{job.get('version', '')}"
    )
    if qualifiers:
        projname += f" [{qualifiers}]"
    content_hash = digest(archive)
    return {
        "content_hash": content_hash,
        "build_cid": job["build_cid"],
        "git_branch": job.get("variant", ""),
        "git_commit_id": commit or job.get("version", ""),
        "git_owner": job["owner"],
        "git_repo": database_identity.repository(
            job.get("upstream_repo", job.get("package", job["base_repo"])),
            content_hash),
        "ingestion_datetime_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "primary_language": job["language"],
        "result_url": archive.resolve().as_uri(),
        "tool_name": "codeql",
        "tool_version": tool_version,
        "projname": projname,
        "db_file_size": archive.stat().st_size,
    }


def cmd_build(state, args) -> None:
    job_path = Path(args.job).expanduser().resolve()
    job = workflow.load_json(job_path)
    if job.get("schema") != "cga.database-job.v1":
        raise workflow.WorkflowError(f"unsupported database job: {job_path}")
    requested_mode = "trace" if args.trace else "bm-none"
    if job.get("mode") != requested_mode:
        raise workflow.WorkflowError(
            f"job mode is {job.get('mode')!r}, not {requested_mode!r}")
    item_id = workflow.require_safe_name(job.get("id"), "job id")
    owner = workflow.require_safe_name(job.get("owner"), "owner")
    repo = workflow.require_safe_name(job.get("repo"), "repo")
    records = _load_records(state)
    repository = f"{owner}/{repo}"
    if any(item.get("id") == item_id and item.get("status") == "built"
           for item in records):
        raise workflow.WorkflowError(
            f"database record already exists for job {item_id}")
    root = Path(args.output_dir).expanduser().resolve()
    job_dir = workflow.under(root, ".cgadb", item_id)
    source_dir = job_dir / "source"
    database = job_dir / "database"
    archive = job_dir / "bundle.zip"
    record_path = (
        Path(args.record).expanduser().resolve()
        if args.record else root / "records" / f"{item_id}.json")
    resources = (
        Path(args.resources).expanduser().resolve()
        if args.resources else None)
    if args.dry_run:
        record = {
            **job,
            "schema": "cga.database-record.v1",
            "job": str(job_path),
            "status": "planned",
            "archive": str(archive),
            "record": str(record_path),
        }
    else:
        source_input = cgast.resolve(job["source_dir"])
        if job.get("status") != "ready" or not source_input.is_dir():
            raise workflow.WorkflowError(
                f"source is not ready: {source_input}")
        source_hash = tree_digest(source_input)
        if job.get("source_tree_sha256") and job["source_tree_sha256"] != source_hash:
            raise workflow.WorkflowError(
                f"source tree hash changed since planning: {source_input}")
        use_llm = getattr(args, "use_llm", False) or job.get("use_llm", False)
        if job_dir.exists() and not use_llm:
            raise workflow.WorkflowError(
                f"build workspace already exists: {job_dir}")
        codeql = _codeql()
        tool_version = _capture(
            [codeql, "version", "--format=terse"]).strip()
        history = []
        attempt_root = job_dir / "attempts" / uuid.uuid4().hex if use_llm else job_dir
        count = getattr(args, "llm_attempts", 3) if use_llm else 1
        for number in range(1, count + 1):
            attempt = attempt_root / f"{number:03d}" if use_llm else job_dir
            source_dir = attempt / "source"
            database = attempt / "database"
            archive = attempt / "bundle.zip"
            attempt.mkdir(parents=True)
            shutil.copytree(source_input, source_dir, symlinks=True)
            command = job.get("build_command")
            try:
                if use_llm:
                    recipe = prep_llm.recipe(
                        {"operation": "build", "job": job, "codeql": codeql,
                         "tool_version": tool_version,
                         "working_directory": str(source_dir),
                         "database": str(database)}, attempt, source_dir, history)
                    for arguments in recipe["commands"]:
                        prep_llm.run(arguments, source_dir, attempt / "commands.log")
                    command = recipe.get("build_command") or command
                for dependency in workflow.command_list(
                        job.get("dependency_argv", []), "dependency_argv"):
                    if use_llm:
                        prep_llm.run(dependency, source_dir, attempt / "commands.log")
                    else:
                        workflow.run(dependency, cwd=source_dir)
                create = [
                    codeql, "database", "create", str(database),
                    f"--language={job['language']}",
                    f"--source-root={source_dir}",
                ]
                trace_verification = None
                if args.bm_none:
                    create.append("--build-mode=none")
                else:
                    if not isinstance(command, str) or not command.strip():
                        raise workflow.WorkflowError(
                            f"{item_id}: trace build requires build_command")
                    create.append(f"--command={command}")
                if use_llm:
                    prep_llm.run(create, source_dir, attempt / "commands.log")
                else:
                    workflow.run(create, cwd=source_dir)
                if args.trace:
                    trace_verification = _verify_traced_extraction(database)
                bundle = [codeql, "database", "bundle", "--output", str(archive),
                          str(database)]
                if use_llm:
                    prep_llm.run(bundle, source_dir, attempt / "commands.log")
                else:
                    workflow.run(bundle, cwd=source_dir)
                if not archive.is_file():
                    raise workflow.WorkflowError(
                        f"CodeQL did not create archive {archive}")
                if use_llm:
                    workflow.write_json(attempt / "outcome.json", {"status": "succeeded"})
                    history.append({"directory": str(attempt), "status": "succeeded"})
                break
            except (workflow.WorkflowError, OSError) as exc:
                history.append(prep_llm.failure(attempt, exc))
                if number == count:
                    raise workflow.WorkflowError(
                        f"database build failed; see {attempt}: {exc}") from exc
        row = _catalogue_record(job, archive, tool_version)
        repo = row["git_repo"]
        repository = f"{owner}/{repo}"
        published = workflow.under(root, owner, repo, f"{owner}_{repo}_db.zip")
        published.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(archive, published)
        except FileExistsError:
            if digest(published) != row["content_hash"]:
                raise workflow.WorkflowError(
                    f"content-addressed archive mismatch: {published}")
        archive.unlink()
        archive = published
        row["result_url"] = archive.as_uri()
        record = {
            **job,
            "schema": "cga.database-record.v1",
            "job": str(job_path),
            "status": "built",
            "repo": repo,
            "upstream_repo": job.get("upstream_repo", job.get("package", job["base_repo"])),
            "build_command": command if args.trace else None,
            "source_input": str(source_input),
            "source": str(source_dir),
            "source_tree_sha256": source_hash,
            "disposable_source_tree_sha256": tree_digest(source_dir),
            "database": str(database),
            "archive": str(archive),
            "sha256": row["content_hash"],
            "tool_version": tool_version,
            "resources": str(resources) if resources else "",
            "trace_verification": trace_verification,
            "supervision": {"attempts": history} if use_llm else None,
            "catalogue_record": row,
            "record": str(record_path),
        }
    workflow.write_json(record_path, record)
    records.append(record)
    records_path = _write_records(state, records)
    state.setdefault(HISTORY_KEY, []).append({
        "record": cgast.rel(record_path),
        "repository": repository,
        "status": record["status"],
    })
    cgast.info(
        f"cgadb: {record['status']} {repository} -> {cgast.rel(record_path)}")
    cgast.info(f"cgadb: records -> {cgast.rel(records_path)}")


def cmd_serve(_state, _args) -> None:
    import cga_http as C
    from . import serve
    C.serve(COMPONENT, int(os.environ.get("CGA_PREP_CGADB_PORT", DEFAULT_PORT)),
            serve.routes())
    raise SystemExit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cga db build",
        description="Build exactly one CodeQL database")
    parser.add_argument("--job", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--trace", action="store_true")
    modes.add_argument("--bm-none", action="store_true")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--record")
    parser.add_argument("--resources")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--llm-attempts", type=prep_llm.attempts, default=3)
    parser.set_defaults(func=cmd_build)
    return enhance_parser(parser, "db build")


def main(argv: list[str]) -> int:
    if argv and argv[0] == "serve":
        cmd_serve({}, None)
        return 0
    if argv and argv[0] == "zip":
        parser = argparse.ArgumentParser(
            prog="cga db zip", description="Archive an existing CodeQL database")
        parser.add_argument("--db-dir", required=True)
        parser.add_argument("--output", required=True)
        parser.set_defaults(func=cmd_zip)
        enhance_parser(parser, "db zip")
        args = parser.parse_args(argv[1:])
    else:
        args = build_parser().parse_args(argv)
    state = cgast.read()
    try:
        args.func(state, args)
    except workflow.WorkflowError as exc:
        cgast.die(f"cgadb: {exc}", 2)
    cgast.write(state)
    return 0

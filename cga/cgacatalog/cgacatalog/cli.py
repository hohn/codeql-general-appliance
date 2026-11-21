"""Create, merge, and verify CodeQL database catalogues."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import copy
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import cgast
import database_identity
import workflow
from command_help import enhance_parser

RECORDS_KEY = "cgadb-records"
VALIDATIONS_KEY = "cgadbvalidate-results"
CATALOG_KEY = "cgacatalog-catalog"
MANIFEST_KEY = "cgacatalog-manifest"
HISTORY_KEY = "cgacatalog-history"

META_COLUMNS = [
    "content_hash", "build_cid", "git_branch", "git_commit_id", "git_owner",
    "git_repo", "ingestion_datetime_utc", "primary_language", "result_url",
    "tool_name", "tool_version", "projname", "db_file_size",
]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_catalog(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        definitions = ", ".join(
            f"{column} INTEGER" if column == "db_file_size"
            else f"{column} TEXT"
            for column in META_COLUMNS)
        connection.execute(f"CREATE TABLE metadata ({definitions})")
        connection.executemany(
            f"INSERT INTO metadata ({', '.join(META_COLUMNS)}) VALUES "
            f"({', '.join('?' for _ in META_COLUMNS)})",
            [tuple(row[column] for column in META_COLUMNS) for row in rows])
        connection.commit()
    finally:
        connection.close()
    return path


def read_catalog(path: Path, query: str = "SELECT * FROM metadata") -> list[dict]:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = [dict(row) for row in connection.execute(query).fetchall()]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise workflow.WorkflowError(f"cannot read catalogue {path}: {exc}") from exc
    for row in rows:
        missing = set(META_COLUMNS) - set(row)
        if missing:
            raise workflow.WorkflowError(
                f"catalogue query is missing columns: {sorted(missing)}")
    return rows


def _validations(state) -> dict[str, dict]:
    path = cgast.get_path(state, VALIDATIONS_KEY)
    if not path:
        return {}
    document = workflow.load_json(path)
    return {
        item["record_id"]: item
        for item in document.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("record_id"), str)
    }


def _resource_files(value: str) -> dict:
    if not value:
        return {}
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise workflow.WorkflowError(f"resource directory is missing: {root}")
    return {
        path.name: {"path": str(path), "sha256": digest(path)}
        for path in sorted(root.iterdir()) if path.is_file()
    }


def _generated(state) -> tuple[list[dict], list[dict]]:
    document = workflow.load_json(cgast.require_path(
        state, RECORDS_KEY, "run 'cga db build' first"))
    validations = _validations(state)
    rows = []
    manifest_items = []
    for record in document.get("items", []):
        if record.get("status") != "built":
            continue
        row = record.get("catalogue_record")
        if not isinstance(row, dict):
            raise workflow.WorkflowError(
                f"{record.get('id')}: missing catalogue_record")
        archive = Path(record["archive"]).resolve()
        if not archive.is_file() or digest(archive) != row["content_hash"]:
            raise workflow.WorkflowError(
                f"generated archive mismatch: {record.get('id')}")
        row = database_identity.normalize(row)
        row["result_url"] = archive.as_uri()
        rows.append(row)
        item = {
            "repository": f"{row['git_owner']}/{row['git_repo']}",
            "upstream_repo": record.get("upstream_repo", record["repo"]),
            "variant": record.get("variant", ""),
            "mode": record.get("extraction_mode", ""),
            "architecture": record.get("architecture", ""),
            "source": record["source_input"],
            "source_tree_sha256": record.get("source_tree_sha256", ""),
            "disposable_source": record["source"],
            "disposable_source_tree_sha256": record[
                "disposable_source_tree_sha256"],
            "database": record["database"],
            "archive": str(archive),
            "sha256": row["content_hash"],
            "tool_version": row["tool_version"],
            "resources": _resource_files(record.get("resources", "")),
            "trace_verification": record.get("trace_verification"),
            "supervision": record.get("supervision"),
            "catalogue_record": row,
        }
        if record["id"] in validations:
            item["smoke"] = validations[record["id"]]
        manifest_items.append(item)
    if not rows:
        raise workflow.WorkflowError("no built database records are available")
    return rows, manifest_items


def _write_outputs(
        state, rows: list[dict], items: list[dict],
        output: str, manifest_value: str,
) -> tuple[Path, Path]:
    repositories = [
        f"{row['git_owner']}/{row['git_repo']}" for row in rows]
    if len(repositories) != len(set(repositories)):
        raise workflow.WorkflowError("catalogue contains duplicate repositories")
    rows.sort(key=lambda row: (row["git_owner"], row["git_repo"]))
    catalog = Path(output).expanduser().resolve()
    manifest = Path(manifest_value).expanduser().resolve()
    write_catalog(catalog, rows)
    workflow.write_json(manifest, {
        "schema": "cga.database-catalogue.v1",
        "created_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "catalogue": str(catalog),
        "catalogue_sha256": digest(catalog),
        "databases": items,
    })
    cgast.set_path(state, CATALOG_KEY, catalog)
    cgast.set_path(state, MANIFEST_KEY, manifest)
    state.setdefault(HISTORY_KEY, []).append({
        "catalog": cgast.rel(catalog),
        "manifest": cgast.rel(manifest),
        "count": len(rows),
    })
    return catalog, manifest


def cmd_create(state, args) -> None:
    rows, items = _generated(state)
    catalog, manifest = _write_outputs(
        state, rows, items, args.output, args.manifest)
    cgast.info(f"cgacatalog: created {len(rows)} row(s) -> "
               f"{cgast.rel(catalog)}")
    cgast.info(f"cgacatalog: manifest -> {cgast.rel(manifest)}")


def _descriptors(value: str | None) -> dict[str, dict]:
    if not value:
        return {}
    path = Path(value).expanduser().resolve()
    document = workflow.load_json(path)
    items = document.get("items")
    if not isinstance(items, list):
        raise workflow.WorkflowError(f"{path}: items must be an array")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise workflow.WorkflowError("descriptor items must be objects")
        repository = item.get("repository")
        if not isinstance(repository, str) or repository.count("/") != 1:
            raise workflow.WorkflowError(
                "descriptor repository must be owner/repo")
        if repository in result:
            raise workflow.WorkflowError(
                f"duplicate descriptor: {repository}")
        result[repository] = item
    return result


def _base(args) -> tuple[list[dict], list[dict]]:
    query_path = Path(args.base_query_file).expanduser().resolve()
    try:
        query = query_path.read_text()
    except OSError as exc:
        raise workflow.WorkflowError(
            f"cannot read base query {query_path}: {exc}") from exc
    rows = read_catalog(
        Path(args.base_catalog).expanduser().resolve(), query)
    archive_root = Path(args.base_archive_root).expanduser().resolve()
    descriptors = _descriptors(args.base_descriptors)
    items = []
    selected = set()
    for row in rows:
        owner = workflow.require_safe_name(row["git_owner"], "base owner")
        repo = workflow.require_safe_name(row["git_repo"], "base repo")
        repository = f"{owner}/{repo}"
        if repository in selected:
            raise workflow.WorkflowError(
                f"duplicate base repository: {repository}")
        selected.add(repository)
        archive = workflow.under(
            archive_root, owner, repo, f"{owner}_{repo}_db.zip")
        if not archive.is_file():
            raise workflow.WorkflowError(
                f"base archive does not exist: {archive}")
        actual_hash = digest(archive)
        if actual_hash != row["content_hash"]:
            raise workflow.WorkflowError(
                f"base archive hash mismatch: {repository}")
        if archive.stat().st_size != row["db_file_size"]:
            raise workflow.WorkflowError(
                f"base archive size mismatch: {repository}")
        if (args.require_base_tool_version and
                row["tool_version"] != args.require_base_tool_version):
            raise workflow.WorkflowError(
                f"{repository}: expected tool version "
                f"{args.require_base_tool_version}, found {row['tool_version']}")
        row.update(database_identity.normalize(row))
        row["result_url"] = archive.as_uri()
        descriptor = descriptors.get(repository, {})
        items.append({
            **descriptor,
            "repository": f"{row['git_owner']}/{row['git_repo']}",
            "archive": str(archive),
            "sha256": actual_hash,
            "tool_version": row["tool_version"],
            "catalogue_record": row,
            "source": "base-catalogue",
        })
    if descriptors and selected != set(descriptors):
        raise workflow.WorkflowError(
            "base descriptors do not exactly match selected repositories")
    return rows, items


def cmd_merge(state, args) -> None:
    generated_catalog = Path(args.catalog).expanduser().resolve()
    generated_manifest_path = Path(
        args.catalog_manifest).expanduser().resolve()
    verify(generated_catalog, generated_manifest_path)
    generated_manifest = workflow.load_json(generated_manifest_path)
    generated_rows = read_catalog(generated_catalog)
    generated_items = generated_manifest.get("databases")
    if not isinstance(generated_items, list):
        raise workflow.WorkflowError("generated manifest has no databases array")
    base_rows, base_items = _base(args)
    catalog, manifest = _write_outputs(
        state, base_rows + generated_rows, base_items + generated_items,
        args.output, args.manifest)
    cgast.info(
        f"cgacatalog: merged {len(base_rows)} base + "
        f"{len(generated_rows)} generated row(s) -> {cgast.rel(catalog)}")
    cgast.info(f"cgacatalog: manifest -> {cgast.rel(manifest)}")


def verify(catalog: Path, manifest: Path) -> int:
    rows = read_catalog(catalog)
    by_repository = {
        f"{row['git_owner']}/{row['git_repo']}": row for row in rows}
    document = workflow.load_json(manifest)
    if document.get("catalogue_sha256") != digest(catalog):
        raise workflow.WorkflowError("manifest catalogue hash mismatch")
    items = document.get("databases")
    if not isinstance(items, list) or len(items) != len(rows):
        raise workflow.WorkflowError(
            "manifest and catalogue database counts differ")
    for item in items:
        repository = item.get("repository")
        if repository not in by_repository:
            raise workflow.WorkflowError(
                f"manifest repository missing from catalogue: {repository}")
        archive = Path(item["archive"]).expanduser().resolve()
        if not archive.is_file() or digest(archive) != item["sha256"]:
            raise workflow.WorkflowError(
                f"manifest archive mismatch: {repository}")
        if item.get("catalogue_record") != by_repository[repository]:
            raise workflow.WorkflowError(
                f"manifest catalogue record mismatch: {repository}")
    if set(by_repository) != {
            item.get("repository") for item in items}:
        raise workflow.WorkflowError(
            "catalogue repositories do not exactly match manifest")
    return len(rows)


def cmd_verify(state, args) -> None:
    catalog = Path(args.catalog).expanduser().resolve()
    manifest = Path(args.manifest).expanduser().resolve()
    count = verify(catalog, manifest)
    cgast.set_path(state, CATALOG_KEY, catalog)
    cgast.set_path(state, MANIFEST_KEY, manifest)
    state.setdefault(HISTORY_KEY, []).append({
        "verify": cgast.rel(manifest),
        "count": count,
    })
    cgast.info(f"cgacatalog: verified {count} database(s)")


def cmd_export(state, args) -> None:
    catalog = (Path(args.catalog).expanduser().resolve() if args.catalog else
               cgast.require_path(state, CATALOG_KEY, "run cga catalog create first"))
    manifest = (Path(args.manifest).expanduser().resolve() if args.manifest else
                cgast.require_path(state, MANIFEST_KEY, "run cga catalog create first"))
    verify(catalog, manifest)
    destination = Path(args.directory).expanduser().resolve()
    if destination.exists():
        raise workflow.WorkflowError(f"export destination already exists: {destination}")
    base_url = getattr(args, "base_url", None)
    if base_url and not base_url.startswith(("http://", "https://")):
        raise workflow.WorkflowError("--base-url must be an HTTP(S) URL")
    destination.parent.mkdir(parents=True, exist_ok=True)
    original = workflow.load_json(manifest)
    sources = []
    with tempfile.TemporaryDirectory(
            prefix=".cga-export-", dir=destination.parent) as raw:
        staged = Path(raw) / "collection"
        staged.mkdir()
        rows, items = [], []
        for entry in original["databases"]:
            item = copy.deepcopy(entry)
            row = database_identity.normalize(item["catalogue_record"])
            owner = workflow.require_safe_name(row["git_owner"], "owner")
            repo = workflow.require_safe_name(row["git_repo"], "repo")
            relative = Path(owner) / repo / f"{owner}_{repo}_db.zip"
            source = Path(item["archive"]).expanduser().resolve()
            target = workflow.under(staged, *relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            row["result_url"] = (
                base_url.rstrip("/") + "/" + quote(relative.as_posix())
                if base_url else (destination / relative).as_uri())
            item.update(
                repository=f"{owner}/{repo}", archive=str(target),
                catalogue_record=row)
            rows.append(row)
            items.append(item)
            sources.append(source)
        temporary_state = {}
        output_catalog, output_manifest = _write_outputs(
            temporary_state, rows, items,
            str(staged / "metadata.sql"), str(staged / "manifest.json"))
        verify(output_catalog, output_manifest)
        exported = workflow.load_json(output_manifest)
        exported["catalogue"] = str(destination / "metadata.sql")
        for item in exported["databases"]:
            item["archive"] = str(
                destination / Path(item["archive"]).relative_to(staged))
        workflow.write_json(output_manifest, exported)
        staged.rename(destination)
    verify(destination / "metadata.sql", destination / "manifest.json")
    cgast.set_path(state, CATALOG_KEY, destination / "metadata.sql")
    cgast.set_path(state, MANIFEST_KEY, destination / "manifest.json")
    state.setdefault(HISTORY_KEY, []).append({
        "export": str(destination), "count": len(sources),
        "move": bool(args.move), "base_url": base_url,
    })
    if args.move:
        for source in set(sources):
            source.unlink()
    cgast.info(f"cgacatalog: exported {len(sources)} database(s) -> {destination}")


def cmd_info(state, _args) -> None:
    for key in (CATALOG_KEY, MANIFEST_KEY):
        path = cgast.get_path(state, key)
        cgast.info(f"cgacatalog: {key}="
                   f"{cgast.rel(path) if path else '(none)'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cga catalog")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--output", required=True)
    create.add_argument("--manifest", required=True)
    create.set_defaults(func=cmd_create)
    merge = sub.add_parser("merge")
    merge.add_argument("--catalog", required=True)
    merge.add_argument("--catalog-manifest", required=True)
    merge.add_argument("--base-catalog", required=True)
    merge.add_argument("--base-query-file", required=True)
    merge.add_argument("--base-archive-root", required=True)
    merge.add_argument("--base-descriptors")
    merge.add_argument("--require-base-tool-version")
    merge.add_argument("--output", required=True)
    merge.add_argument("--manifest", required=True)
    merge.set_defaults(func=cmd_merge)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--catalog", required=True)
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.set_defaults(func=cmd_verify)
    export = sub.add_parser("export")
    export.add_argument("directory")
    export.add_argument("--catalog")
    export.add_argument("--manifest")
    export.add_argument("--base-url")
    export.add_argument("--move", action="store_true")
    export.set_defaults(func=cmd_export)
    sub.add_parser("info").set_defaults(func=cmd_info)
    return enhance_parser(parser, "cat")


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    state = cgast.read()
    try:
        args.func(state, args)
    except (workflow.WorkflowError, OSError) as exc:
        cgast.die(f"cgacatalog: {exc}", 2)
    cgast.write(state)
    return 0

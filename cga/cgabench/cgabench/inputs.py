"""Library tables and named selection/development operations."""

from __future__ import annotations

import copy
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tarfile

import cgast
from cgadl import catalog as databases
from cgadl import selection as database_selection
from cgaql import catalog as queries
from cgaql import pack
from cgaql import selection as query_selection
from cgawf.repository import atomic_write, utc_now
from workflow import WorkflowError, require_safe_name
from vid_registry import reference

from . import engine, model

LIBRARIES = {
    "databases": ("cgadl-metadata", databases),
    "queries": ("cgaql-index", queries),
}
MAX_PAGE = 100


def discover_catalogues(workspace: Path) -> dict:
    roots = list(dict.fromkeys((workspace.resolve(), engine.COLLECTION.resolve())))
    paths = set()

    def scan_error(error: OSError) -> None:
        raise WorkflowError(f"cannot discover database catalogues: {error}") from error

    for root in roots:
        for directory, subdirectories, files in os.walk(root, onerror=scan_error,
                                                       followlinks=False):
            subdirectories[:] = [
                name for name in subdirectories
                if not name.startswith(".") and name not in {"node_modules", "__pycache__"}
            ]
            if "metadata.sql" in files:
                path = Path(directory) / "metadata.sql"
                if path.is_file():
                    paths.add(str(path))
    supplied = engine.COLLECTION / "cgadl" / "db-collection.global" / "metadata.sql"
    if supplied.is_file():
        paths.add(str(supplied))
    return {"schema": "cga.bench.catalogues.v1", "roots": [str(root) for root in roots],
            "paths": sorted(paths)}


def library(state: dict, kind: str, index: int | None = None,
            source: str = "list") -> tuple[Path, object]:
    if kind not in LIBRARIES:
        raise WorkflowError("collection must be databases or queries")
    key, catalog = LIBRARIES[kind]
    path = state.get(key)
    if index is not None:
        workspace = model.session(state, index)["workspace"]
        if source == "user":
            path = workspace.get("cgabench-libraries", {}).get("built", {}).get("cgadl-metadata") \
                if kind == "databases" else None
            path = path or workspace.get(key)
        else:
            path = workspace.get("cgabench-libraries", {}).get(key) or path or workspace.get(key)
    if not isinstance(path, str) or not path:
        raise WorkflowError("Load database catalogue first" if kind == "databases"
                            else "Index query library first")
    resolved = cgast.resolve(path)
    if not resolved.is_file():
        raise WorkflowError("library file is missing; load or index it again")
    return resolved, catalog


def collection(state: dict, kind: str, index: int | None = None,
               source: str = "list", search: str = "", offset: int = 0,
               limit: int = 50) -> dict:
    if offset < 0 or not 1 <= limit <= MAX_PAGE:
        raise WorkflowError(f"offset must be nonnegative; limit must be 1..{MAX_PAGE}")
    path, catalog = library(state, kind, index, source)
    try:
        connection = catalog.connect(path)
        try:
            columns = catalog.keys(connection)
            where, params = "", []
            if search:
                quoted = ['"' + column.replace('"', '""') + '"' for column in columns]
                where = " WHERE " + " OR ".join(
                    f"instr(lower(CAST({column} AS TEXT)), lower(?)) > 0" for column in quoted)
                params = [search] * len(columns)
            table = catalog.TABLE
            total = connection.execute(
                f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0]
            rows = connection.execute(
                f"SELECT rowid AS _row, * FROM {table}{where} "
                "ORDER BY rowid LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            generation = model.fingerprint(path)
            prefix = (index, source) if index is not None else ()
            return {"schema": "cga.bench.collection.v1", "kind": kind,
                    "generation": generation,
                    "rows": [{**dict(row), "vid": reference(
                        kind, *prefix, "g" + generation, row["_row"])} for row in rows], "total": total,
                    "offset": offset, "limit": limit, "has_more": offset + len(rows) < total}
        finally:
            connection.close()
    except (sqlite3.Error, databases.CatalogError, queries.CatalogError) as exc:
        raise WorkflowError(f"cannot read {kind} library: {exc}") from exc


def selected_rows(state: dict, kind: str, item: dict, generation: str,
                  row_ids: list[int], source: str) -> list[dict]:
    if not row_ids or len(row_ids) > MAX_PAGE or len(set(row_ids)) != len(row_ids):
        raise WorkflowError(f"choose 1..{MAX_PAGE} distinct library rows")
    path, catalog = library(state, kind, item["index"], source)
    if model.fingerprint(path) != generation:
        raise WorkflowError("library changed; reload the table before choosing")
    connection = catalog.connect(path)
    try:
        placeholders = ",".join("?" for _ in row_ids)
        found = connection.execute(
            f"SELECT rowid AS _row, * FROM {catalog.TABLE} WHERE rowid IN ({placeholders})",
            row_ids).fetchall()
        by_id = {row["_row"]: dict(row) for row in found}
        if len(by_id) != len(row_ids):
            raise WorkflowError("a chosen row no longer exists")
        result = []
        for row_id in row_ids:
            row = by_id[row_id]
            row.pop("_row")
            result.append(row)
        item["workspace"][LIBRARIES[kind][0]] = cgast.rel(path)
        return result
    except sqlite3.Error as exc:
        raise WorkflowError(f"cannot select library rows: {exc}") from exc
    finally:
        connection.close()


def choose(state: dict, index: int | None, kind: str, generation: str,
           row_ids: list[int], source: str, no_advance: bool) -> None:
    item = model.session(state, index)
    engine.synchronize(item)
    model.input_editable(state, item, "D" if kind == "databases" else "Q")
    rows = selected_rows(state, kind, item, generation, row_ids, source)
    path = cgast.new_tempfile(prefix="cgabench-selection-", suffix=".json")
    if kind == "databases":
        identities = set()
        for row in rows:
            owner = require_safe_name(row.get("git_owner"), "database owner")
            repository = require_safe_name(row.get("git_repo"), "database repository")
            identity = f"{owner}/{repository}"
            if identity in identities:
                raise WorkflowError("choose only one database version per repository")
            identities.add(identity)
        languages = {row.get("primary_language") for row in rows}
        if len(languages) != 1 or not all(languages):
            raise WorkflowError("choose databases with one language")
        query = item["Q"]["artifact"]
        if query and query["language"] not in languages:
            raise WorkflowError("chosen databases and accepted query languages differ")
        database_selection.write_selection(path, rows)
        workspace = copy.deepcopy(item["workspace"])
        workspace["cgadl-selection"] = cgast.rel(path)
        workspace.pop("cgadl-dbdir", None)
        args = ["download"]
        destination = state.get("cgamx", {}).get("db_serve_dir") \
            or os.environ.get("MRVA_DB_SERVE_DIR")
        if destination:
            args += ["--output-dir", destination]
        item["workspace"] = engine.run_tool(workspace, "dl", args)
        model.accept_database(state, item, None, None, source)
    else:
        if len(rows) != 1:
            raise WorkflowError("choose one query per session")
        database = item["D"]["artifact"]
        if database and rows[0].get("language") != database["language"]:
            raise WorkflowError("chosen query and accepted database languages differ")
        query_selection.write_selection(path, rows)
        workspace = copy.deepcopy(item["workspace"])
        workspace["cgaql-selection"] = cgast.rel(path)
        workspace.pop("cgaql-pack", None)
        item["workspace"] = engine.run_tool(workspace, "ql", ["pack"])
        model.accept_query(state, item, None, None, 0, source)
    model.experiment(state)["active"] = item["index"]
    if not no_advance:
        engine.advance(state, item)


def create_query(state: dict, index: int | None, directory: str,
                 name: str, language: str) -> None:
    item = model.session(state, index)
    engine.synchronize(item)
    model.input_editable(state, item, "Q")
    require_safe_name(name, "query name")
    if language not in pack.DEP_FOR_LANG:
        raise WorkflowError("choose a supported CodeQL language")
    root = Path(directory).expanduser().resolve()
    if root.exists():
        raise WorkflowError("query directory already exists; choose a new directory")
    try:
        pack.initialize_pack(root, language,
                             os.environ.get("CGA_CGAQL_CODEQL", "codeql"),
                             "cga/bench-query")
    except pack.PackError as exc:
        raise WorkflowError(str(exc)) from exc
    path = root / f"{name}.ql"
    path.write_text(
        "/**\n"
        f" * @name {name}\n"
        " * @description Replace this placeholder with your detector.\n"
        " * @kind problem\n"
        " * @problem.severity warning\n"
        f" * @id {language}/{name.lower()}\n"
        " */\n"
        f"import {language}\n\n"
        "from File file\n"
        "where false\n"
        'select file, "Replace this placeholder with your finding message."\n',
        encoding="utf-8")
    (root / "README.md").write_text(
        "# Query workspace\n\n"
        "Edit the query in CGA Bench or your editor. The starter intentionally "
        "finds nothing.\nReview and validate your detector before choosing it "
        "for analysis.\nThe dependency is pinned to your installed CodeQL bundle.\n",
        encoding="utf-8")
    record_query_workspace(item, path)
    item["Q"]["history"].append({"at": utc_now(), "action": "create-query",
                                 "name": name, "language": language})


def record_query_workspace(item: dict, path: Path, root: Path | None = None) -> None:
    root = root or path.parent
    item["workspace"]["cgabench-query"] = {
        "editor_path": cgast.rel(path), "directory": cgast.rel(root),
        "path": model.snapshot(path, ".ql"),
        "manifest": model.snapshot(root / "qlpack.yml", ".yml")}
    item["workspace"] = engine.run_tool(
        item["workspace"], "ql", ["index", str(root)])
    item["workspace"].pop("cgaql-pack", None)


def copy_query(state: dict, index: int | None, directory: str,
               source_session: int | None, generation: str | None,
               row: int | None, source: str) -> None:
    item = model.session(state, index)
    engine.synchronize(item)
    model.input_editable(state, item, "Q")
    root = Path(directory).expanduser().resolve()
    if root.exists():
        raise WorkflowError("query directory already exists; choose a new directory")
    provenance = {"action": "copy-query", "at": utc_now()}
    if source_session is not None:
        if not 1 <= source_session < item["index"]:
            raise WorkflowError("query source must be a prior session")
        parent = model.session(state, source_session)
        engine.synchronize(parent)
        artifact = parent["Q"]["artifact"]
        if not artifact:
            raise WorkflowError("accept the source query before copying it")
        model.verify_input("Q", artifact)
        selected = model.rows(cgast.resolve(artifact["cgaql-selection"]), "queries")
        if len(selected) != 1:
            raise WorkflowError("copying a session query requires one entry point")
        filename = selected[0].get("filename")
        if not filename:
            original = selected[0].get("path")
            filename = Path(original).name if isinstance(original, str) else None
        if not isinstance(filename, str) or not filename.endswith(".ql"):
            raise WorkflowError("accepted query selection must identify a .ql source file")
        try:
            with tarfile.open(cgast.resolve(artifact["cgaql-pack"][0]), "r:gz") as archive:
                members = archive.getmembers()
                entries = [member for member in members
                           if member.isfile() and PurePosixPath(member.name).name == filename]
                if len(entries) != 1:
                    raise WorkflowError("accepted pack must contain one matching query source")
                entry = PurePosixPath(entries[0].name)
                pack_root = next((parent for parent in entry.parents
                                  if any(PurePosixPath(member.name) == parent / manifest
                                         for member in members
                                         for manifest in ("qlpack.yml", "qlpack.yaml"))), None)
                if pack_root is None:
                    raise WorkflowError("accepted query pack has no pack configuration")
                files = []
                for member in members:
                    name = PurePosixPath(member.name)
                    if name.is_absolute() or ".." in name.parts or (
                            not member.isfile() and not member.isdir()):
                        raise WorkflowError("accepted query pack contains unsafe archive entries")
                    if member.isfile() and name.is_relative_to(pack_root):
                        relative = name.relative_to(pack_root)
                        if not relative.parts:
                            raise WorkflowError("accepted query pack contains unsafe archive entries")
                        if relative.parts[0] != ".codeql" and relative.name != ".packinfo" \
                                and relative.suffix != ".qlx":
                            files.append((member, relative))
                root.mkdir(parents=True)
                for member, relative in files:
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as stream:
                        atomic_write(path, stream.read())
                path = root / entry.relative_to(pack_root)
        except tarfile.TarError as exc:
            raise WorkflowError(f"cannot copy accepted query pack: {exc}") from exc
        if not (root / "qlpack.yml").is_file():
            shutil.copyfile(root / "qlpack.yaml", root / "qlpack.yml")
        provenance.update(session=source_session, pack_sha256=artifact["sha256"])
    else:
        if not generation or row is None:
            raise WorkflowError("copy-query needs a library generation and row")
        query = selected_rows(state, "queries", item, generation, [row], source)[0]
        language = query.get("language")
        if language not in pack.DEP_FOR_LANG:
            raise WorkflowError("choose a query with a supported CodeQL language")
        original = Path(query["path"])
        if not original.is_file():
            raise WorkflowError("query source is missing; index the library again")
        try:
            pack.initialize_pack(root, language,
                                 os.environ.get("CGA_CGAQL_CODEQL", "codeql"),
                                 "cga/bench-query")
        except pack.PackError as exc:
            raise WorkflowError(str(exc)) from exc
        path = root / original.name
        shutil.copyfile(original, path)
        for support in sorted(original.parent.glob("*.qll")):
            shutil.copyfile(support, root / support.name)
        provenance.update(source_path=str(original), source_sha256=model.fingerprint(path))
    record_query_workspace(item, path, root)
    item["workspace"]["cgabench-query"]["copied_from"] = copy.deepcopy(provenance)
    item["Q"]["history"].append(provenance)
    model.experiment(state)["active"] = item["index"]


def query_source(state: dict, index: int | None) -> dict:
    item = model.session(state, index)
    record = item["workspace"].get("cgabench-query")
    if not isinstance(record, dict):
        raise WorkflowError("create a user query workspace first")
    path = cgast.resolve(record["editor_path"])
    root = cgast.resolve(record["directory"])
    return {"name": path.name, "directory": str(root),
            "source": path.read_text(encoding="utf-8"),
            "manifest": (root / "qlpack.yml").read_text(encoding="utf-8")}


def edit_query(state: dict, index: int | None, source: str) -> None:
    item = model.session(state, index)
    engine.synchronize(item)
    model.input_editable(state, item, "Q")
    record = item["workspace"].get("cgabench-query")
    if not isinstance(record, dict):
        raise WorkflowError("create a user query workspace first")
    if not source.strip():
        raise WorkflowError("query source must not be empty")
    path = cgast.resolve(record["editor_path"])
    atomic_write(path, (source.rstrip() + "\n").encode("utf-8"))
    record["path"] = model.snapshot(path, ".ql")
    item["workspace"] = engine.run_tool(
        item["workspace"], "ql", ["index", str(cgast.resolve(record["directory"]))])
    item["workspace"].pop("cgaql-pack", None)
    item["Q"]["history"].append({"at": utc_now(), "action": "edit-query"})

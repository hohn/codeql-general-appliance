"""Query-authoring porcelain over existing recorded CGA components."""

from __future__ import annotations

import argparse
from contextlib import closing
import fcntl
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid

import cgast
import database_identity
from cgabench.engine import run_tool
from cgadl import catalog as db_catalog, download, selection
from cgaql import catalog as query_catalog, pack
from command_help import enhance_parser
from workflow import WorkflowError, require_safe_name, run, under, write_json

from . import database


COLLECTION = Path(__file__).resolve().parents[2]
KEY = "cgaassist-query"
TEMPLATE = COLLECTION.parent / "sample-query" / "Fprintf.ql"


def prompt(message: str) -> str:
    try:
        with open("/dev/tty", "r") as terminal, open("/dev/tty", "w") as output:
            output.write(message + ": ")
            output.flush()
            answer = terminal.readline()
    except OSError as exc:
        raise WorkflowError(
            "interactive input requires a terminal; provide the explicit argument") from exc
    if not answer:
        raise WorkflowError("input cancelled")
    answer = answer.strip()
    if not answer:
        raise WorkflowError("a non-empty answer is required")
    return answer


def authoring(state: dict) -> dict:
    value = state.get(KEY)
    if not isinstance(value, dict):
        raise WorkflowError("start an authoring workflow with cga a q start DIRECTORY")
    return value


def scratch(state: dict) -> Path:
    return Path(authoring(state)["scratch"])


def tool(state: dict, component: str, arguments: list[str]) -> None:
    updated = run_tool(state, component, arguments)
    for key in ("cgadl-metadata", "cgadl-query", "cgadl-selection", "cgadl-dbdir",
                "cgaql-index", "cgaql-querydir"):
        if key in updated:
            updated[key] = str(cgast.resolve(updated[key]))
    state.clear()
    state.update(updated)


def codeql() -> str:
    value = os.environ.get("CGA_CGAQL_CODEQL", "codeql")
    executable = shutil.which(value)
    if not executable:
        raise WorkflowError(f"CodeQL executable not found: {value}")
    return str(Path(executable).resolve())


def bootstrap(args: argparse.Namespace) -> int:
    directory = Path(args.directory).expanduser().resolve()
    if directory.exists():
        raise WorkflowError(f"authoring directory already exists: {directory}")
    directory.mkdir(parents=True)
    environment = os.environ.copy()
    environment["CGA_DIR"] = str(directory / ".cga")
    environment.pop("CGA_WORKFLOW_ACTIVE", None)
    for arguments in (["init"], ["chain", "start", "--name", "query-writing"]):
        subprocess.run(
            [str(COLLECTION / "cga"), *arguments], cwd=directory,
            env=environment, check=True,
        )
    return subprocess.run(
        [str(COLLECTION / "cgawf/bin/cgawf"), "run",
         "--display-token", "assist", "--",
         str(COLLECTION / "cgaassist/bin/cgaassist"),
         "query-writing", "start", str(directory)],
        cwd=directory, env=environment, check=False,
    ).returncode


def start(state: dict, args) -> None:
    if KEY in state:
        raise WorkflowError("this workflow already has an authoring session")
    directory = Path(args.directory).expanduser().resolve()
    workflow_root = Path(os.environ["CGA_WORKFLOW_ROOT"]).resolve()
    if directory != workflow_root:
        raise WorkflowError("authoring directory must be the current workflow root")
    root = directory / ".cga/tmp/query-writing"
    root.mkdir(parents=True)
    (root / "qlib").mkdir()
    state[KEY] = {"directory": str(directory), "scratch": str(root),
                  "working_tree": str(root / "working"),
                  "qlibdir": str(root / "qlib"), "prepared": False,
                  "saved": {}, "publications": []}
    cgast.info(f"Authoring workflow: {directory}")
    cgast.info(f"Next: cd {shlex.quote(str(directory))}")
    cgast.info("Then: cga a q catalogue")


def require_unprepared(state: dict) -> None:
    if authoring(state)["prepared"]:
        raise WorkflowError("editor databases are fixed after prepare; start a new workflow to change them")


def catalogue(state: dict, args) -> None:
    require_unprepared(state)
    source = args.index
    if source is None:
        candidates = [
            COLLECTION / "cgadl/db-collection.global/metadata.sql",
            COLLECTION / "db-collection.local/metadata.sql",
            Path.cwd() / "metadata.sql",
        ]
        candidates = list(dict.fromkeys(str(path.resolve()) for path in candidates if path.is_file()))
        for index, path in enumerate(candidates, 1):
            cgast.info(f"{index}: {path}")
        source = prompt("Catalogue number, local path, or URL")
        if source.isdigit():
            number = int(source)
            if not 1 <= number <= len(candidates):
                raise WorkflowError("catalogue number is out of range")
            source = candidates[number - 1]
    tool(state, "dl", ["getmeta", source])
    for key in ("cgadl-selection", "cgadl-dbdir"):
        state.pop(key, None)
    cgast.info("Next: cga a q select-databases")


def select_databases(state: dict, args) -> None:
    require_unprepared(state)
    metadata = cgast.require_path(state, "cgadl-metadata", "run cga a q catalogue")
    with closing(db_catalog.connect(metadata)) as connection:
        where = "primary_language = 'cpp'"
        parameters = []
        if args.search:
            where += " AND instr(lower(git_owner || '/' || git_repo || ' ' || tool_version), lower(?)) > 0"
            parameters.append(args.search)
        candidates = connection.execute(
            f"SELECT rowid AS catalogue_rowid, * FROM metadata WHERE {where} "
            "ORDER BY git_owner, git_repo, db_file_size, rowid LIMIT 100",
            parameters,
        ).fetchall()
        if not candidates:
            raise WorkflowError("no C++ databases match; adjust --search or choose another catalogue")
        for row in candidates:
            cgast.info(f"{row['catalogue_rowid']}: {row['git_owner']}/{row['git_repo']} "
                       f"CodeQL={row['tool_version']} bytes={row['db_file_size']}")
        chosen = args.rows
        if chosen is None:
            text = prompt("Select at least two catalogue rowids (space-separated); use --search to narrow the first 100 rows")
            try:
                chosen = [int(value) for value in text.split()]
            except ValueError as exc:
                raise WorkflowError("database rowids must be integers") from exc
        if not 2 <= len(chosen) <= 100 or len(set(chosen)) != len(chosen):
            raise WorkflowError("select 2..100 distinct database rowids")
        marks = ",".join("?" for _ in chosen)
        rows = connection.execute(
            f"SELECT * FROM metadata WHERE rowid IN ({marks}) ORDER BY git_owner, git_repo, rowid",
            chosen,
        ).fetchall()
    normalized = [database_identity.normalize(dict(row)) for row in rows]
    identities = [(row["git_owner"], row["git_repo"]) for row in normalized]
    if (len(rows) != len(chosen) or any(row["primary_language"] != "cpp" for row in rows)
            or len(set(identities)) != len(rows)):
        raise WorkflowError("choose existing C++ rows with distinct database contents")
    path = scratch(state) / "database-selection.sql"
    path.write_text(
        "SELECT * FROM metadata WHERE rowid IN (" + ",".join(map(str, chosen))
        + ") ORDER BY git_owner, git_repo, rowid;\n")
    tool(state, "dl", ["sql", "--query-file", str(path)])
    state.pop("cgadl-dbdir", None)
    cgast.info("Next: cga a q download")


def download_databases(state: dict, _args) -> None:
    authoring(state)
    tool(state, "dl", ["download", "--output-dir", str(scratch(state) / "archives")])
    cgast.info("Next: cga a q prepare")


def editor_databases(state: dict, requested: list[str] | None) -> list[dict]:
    path = cgast.require_path(state, "cgadl-selection", "run cga a q select-databases")
    rows = selection.read_selection(path)
    identities = [f"{row['git_owner']}/{row['git_repo']}" for row in rows]
    if requested is None:
        for index, identity in enumerate(identities, 1):
            cgast.info(f"{index}: {identity}")
        text = prompt("Choose at least two editor database numbers (space-separated)")
        try:
            numbers = [int(value) for value in text.split()]
        except ValueError as exc:
            raise WorkflowError("editor database numbers must be integers") from exc
        if any(not 1 <= number <= len(rows) for number in numbers):
            raise WorkflowError("editor database number is out of range")
        requested = [identities[number - 1] for number in numbers]
    else:
        resolved = []
        for value in requested:
            matches = [identity for row, identity in zip(rows, identities)
                       if value == identity or (
                           row.get("content_hash") and
                           identity == value + "-" + row["content_hash"])]
            if len(matches) != 1:
                raise WorkflowError(
                    f"editor database is missing or ambiguous: {value}; use its full identity")
            resolved.append(matches[0])
        requested = resolved
    if len(requested) < 2 or len(set(requested)) != len(requested):
        raise WorkflowError("choose at least two distinct editor databases")
    if not set(requested) <= set(identities):
        raise WorkflowError("editor databases must come from the downloaded selection")
    return [row for row in rows if f"{row['git_owner']}/{row['git_repo']}" in requested]


def prepare(state: dict, args) -> None:
    require_unprepared(state)
    archives = cgast.require_path(state, "cgadl-dbdir", "run cga a q download")
    rows = editor_databases(state, args.databases)
    executable = codeql()
    root = scratch(state)
    working = Path(authoring(state)["working_tree"])
    if working.exists():
        raise WorkflowError(f"working tree already exists: {working}")
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=root) as temporary:
        candidate = Path(temporary) / "working"
        search_path = pack.initialize_pack(candidate, "cpp", executable, "cga/author-query")
        shutil.copy2(TEMPLATE, candidate / TEMPLATE.name)
        search = [f"--search-path={search_path}"] if search_path else []
        run([executable, "pack", "install", *search], cwd=candidate)
        databases = []
        for index, row in enumerate(rows, 1):
            owner = require_safe_name(row["git_owner"], "database owner")
            repository = require_safe_name(row["git_repo"], "database repository")
            archive = download.db_dest(archives, owner, repository)
            if not archive.is_file():
                raise WorkflowError(f"database archive is missing: {archive}")
            name = f"db-{index:02d}-{owner}-{repository}"
            run([executable, "database", "unbundle", str(archive),
                 f"--target={candidate / 'databases'}", f"--name={name}"])
            database = candidate / "databases" / name
            if not (database / "codeql-database.yml").is_file():
                raise WorkflowError(f"extracted database has no codeql-database.yml: {database}")
            databases.append({"repository": f"{owner}/{repository}",
                              "directory": str(working / "databases" / name)})
        project = {
            "folders": [{"name": "Query authoring", "path": "."}],
            "settings": {"terminal.integrated.cwd": str(working),
                         "codeQL.cli.executablePath": executable,
                         "search.exclude": {"**/databases/**": True}},
            "extensions": {"recommendations": ["GitHub.vscode-codeql"]},
        }
        write_json(candidate / "query.code-workspace", project)
        write_json(candidate / "editor-databases.json", databases)
        (candidate / "EDITOR.txt").write_text(
            "Open query.code-workspace in VS Code with the CodeQL extension.\n"
            "In the CodeQL Databases view, add the local folders listed in\n"
            "editor-databases.json. Edit Fprintf.ql or another root-level .ql.\n"
            "Nothing here starts VS Code or executes a query automatically.\n")
        candidate.rename(working)
    record = authoring(state)
    record.update(prepared=True, editor_databases=databases,
                  search_path=str(search_path) if search_path else "")
    cgast.info(f"Workspace: {working / 'query.code-workspace'}")
    cgast.info(f"Open: code {shlex.quote(str(working / 'query.code-workspace'))}")
    cgast.info("Add the local database folders from editor-databases.json in the CodeQL Databases view.")
    cgast.info("After editing: cga a q save NAME [--source FILE]")


def package_files(working: Path, source: Path, destination: Path, name: str) -> None:
    if source.parent != working or source.suffix != ".ql" or not source.is_file():
        raise WorkflowError("choose an existing root-level .ql file in the working tree")
    for manifest in ("qlpack.yml", "codeql-pack.lock.yml"):
        path = working / manifest
        if path.is_file():
            shutil.copy2(path, destination / manifest)
    pack.copy_query_support(working, destination)
    text = source.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*\*\s*@id\s+)cpp-fprintf-call[ \t]*$",
                  lambda match: match[1] + f"cpp/{name.lower()}", text)
    text = re.sub(r"(?m)^(\s*\*\s*@name\s+)findPrintf[ \t]*$",
                  lambda match: match[1] + name, text)
    (destination / f"{name}.ql").write_text(text, encoding="utf-8")


def save(state: dict, args) -> None:
    record = authoring(state)
    if not record["prepared"]:
        raise WorkflowError("run cga a q prepare before saving a draft")
    name = require_safe_name(args.name or prompt("New query name"), "query name")
    working = Path(record["working_tree"])
    source = Path(args.source).expanduser().resolve() if args.source else working / TEMPLATE.name
    library = Path(record["qlibdir"])
    target = under(library, name)
    if target.exists() and name not in record["saved"]:
        raise WorkflowError(f"unowned staging directory already exists: {target}")
    with tempfile.TemporaryDirectory(prefix="save-", dir=scratch(state)) as temporary:
        candidate = Path(temporary) / name
        candidate.mkdir()
        package_files(working, source, candidate, name)
        history = scratch(state) / "saved-history"
        history.mkdir(exist_ok=True)
        snapshot = history / f"{name}-{uuid.uuid4().hex}"
        candidate.rename(snapshot)
        previous = Path(temporary) / "previous"
        if target.exists():
            target.rename(previous)
        try:
            shutil.copytree(snapshot, target)
            tool(state, "ql", ["index", str(library)])
        except (OSError, WorkflowError, SystemExit):
            if target.exists():
                shutil.rmtree(target)
            if previous.exists():
                previous.rename(target)
            shutil.rmtree(snapshot)
            raise
    for key in ("cgaql-selection", "cgaql-pack"):
        state.pop(key, None)
    record = authoring(state)
    record["saved"][name] = {
        "directory": str(snapshot), "entrypoint": f"{name}.ql",
        "files": [{"path": str(path)}
                  for path in sorted(snapshot.rglob("*")) if path.is_file()],
    }
    record["active_query"] = name
    cgast.info(f"Saved draft: {target}")
    cgast.info("Next: cga a q publish LIBRARY [--name NAME]")


def publish(state: dict, args) -> None:
    record = authoring(state)
    name = require_safe_name(args.name or record.get("active_query"), "saved query name")
    saved = record["saved"].get(name)
    if not saved:
        raise WorkflowError(f"query {name!r} has not been saved")
    library = Path(args.library or prompt("Permanent query-library directory")).expanduser().resolve()
    root = scratch(state)
    if library.is_relative_to(root) or root.is_relative_to(library):
        raise WorkflowError("choose a permanent library outside scratch and not an ancestor of scratch")
    target = under(library, name)
    if target.exists():
        raise WorkflowError(f"publication would overwrite {target}; choose a new query name or library")
    executable = codeql()
    search = [f"--search-path={record['search_path']}"] if record["search_path"] else []
    with tempfile.TemporaryDirectory(prefix="publish-", dir=root) as temporary:
        candidate = Path(temporary) / name
        shutil.copytree(Path(saved["directory"]), candidate)
        entrypoint = candidate / saved["entrypoint"]
        row = query_catalog.parse_query(entrypoint, candidate)
        if not row["id"] or row["language"] != "cpp" or row["kind"] not in ("problem", "path-problem"):
            raise WorkflowError("publication requires a C++ problem/path-problem query with a non-empty @id")
        run([executable, "pack", "install", *search], cwd=candidate)
        run([executable, "query", "compile", "--check-only", *search, str(entrypoint)],
            cwd=candidate)
        library.mkdir(parents=True, exist_ok=True)
        with (library / ".cga-publish.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if target.exists():
                raise WorkflowError(f"publication would overwrite {target}")
            for existing in library.rglob("*.ql"):
                if query_catalog.parse_query(existing, library)["id"] == row["id"]:
                    raise WorkflowError(f"query @id {row['id']!r} already exists in {existing}")
            target.mkdir()
            try:
                shutil.copytree(candidate, target, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(".cache", ".codeql", "*.qlo"))
                tool(state, "ql", ["index", str(library)])
            except (OSError, WorkflowError, SystemExit):
                shutil.rmtree(target)
                raise
    for key in ("cgaql-selection", "cgaql-pack"):
        state.pop(key, None)
    authoring(state)["publications"].append(
        {"name": name, "directory": str(target), "query_id": row["id"],
         "validation": "codeql query compile --check-only"})
    cgast.info(f"Published: {target / saved['entrypoint']}")
    cgast.info(f"Indexed permanent library: {library}")
    cgast.info("The library is ready for cga ql list/select/pack. No MRVA work was started.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cga assist")
    groups = parser.add_subparsers(dest="group", required=True)
    database.add_parser(groups, prompt)
    query = groups.add_parser("query-writing", aliases=["q"])
    commands = query.add_subparsers(dest="command", required=True)
    command = commands.add_parser("start")
    command.add_argument("directory")
    command.set_defaults(func=start)
    command = commands.add_parser("catalogue")
    command.add_argument("index", nargs="?", help="local metadata.sql or URL; omitted prompts")
    command.set_defaults(func=catalogue)
    command = commands.add_parser("select-databases")
    command.add_argument("--rows", nargs="+", type=int, help="original SQLite catalogue rowids")
    command.add_argument("--search", help="literal owner/repository/version substring")
    command.set_defaults(func=select_databases)
    commands.add_parser("download").set_defaults(func=download_databases)
    command = commands.add_parser("prepare")
    command.add_argument("--databases", nargs="+", help="two or more selected owner/repository identities")
    command.set_defaults(func=prepare)
    command = commands.add_parser("save")
    command.add_argument("name", nargs="?", help="safe query name; omitted prompts")
    command.add_argument("--source", help="root-level working-tree .ql file; defaults to Fprintf.ql")
    command.set_defaults(func=save)
    command = commands.add_parser("publish")
    command.add_argument("library", nargs="?", help="permanent library directory; omitted prompts")
    command.add_argument("--name", help="saved query name; defaults to the last saved query")
    command.set_defaults(func=publish)
    return enhance_parser(parser, "assist")


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    group = "database-build" if args.group in ("d", "database-build") else "query-writing"
    try:
        if args.command == "start" and os.environ.get("CGA_WORKFLOW_ACTIVE") != "1":
            return bootstrap(args)
        if os.environ.get("CGA_WORKFLOW_ACTIVE") != "1":
            raise WorkflowError("use assist commands inside an initialized workflow (cga init)")
        if group == "database-build":
            os.environ.setdefault(
                "CGAST_ROOT", os.environ.get("CGA_PREP_ROOT", str(cgast.cga_root())))
            os.environ.setdefault(
                "CGAST_TMPDIR",
                os.environ.get("CGA_PREP_TMPDIR", os.environ.get(
                    "CGA_TMPDIR", str(Path(os.environ["CGA_WORKFLOW_ROOT"]) /
                                      ".cga/tmp/database-build/artifacts"))))
        if not (os.environ.get("CGAST_TMPDIR") or os.environ.get("CGA_TMPDIR")):
            os.environ["CGA_TMPDIR"] = str(
                Path(os.environ["CGA_WORKFLOW_ROOT"]) / ".cga/tmp" /
                group / "artifacts")
        state = cgast.read()
        args.func(state, args)
        if group == "database-build":
            database.checkpoint(state)
        cgast.write(state)
    except (WorkflowError, OSError, ValueError, sqlite3.Error, db_catalog.CatalogError, pack.PackError,
            subprocess.CalledProcessError) as exc:
        cgast.die(f"cga assist {group}: {exc}", 2)
    return 0

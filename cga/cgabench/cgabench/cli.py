"""JSON-in/JSON-out bench commands shared by terminal and browser."""

from __future__ import annotations

import argparse
import getpass
import json

import cgast
from command_help import enhance_parser
from cgawf.repository import utc_now
from workflow import WorkflowError

from . import compare, engine, inputs, model, services


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cga bench", description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create an experiment in the CGAST")
    init.add_argument("name")
    init.add_argument("--mode", choices=model.MODES)
    mode = sub.add_parser("mode", help="select and validate the experiment's changing axis")
    mode.add_argument("mode", choices=model.MODES)
    new = sub.add_parser("session", help="append S1 or a variant inheriting its fixed input")
    new.add_argument("name", nargs="?", help="optional label; otherwise generated from the row number")
    new.add_argument("--user", help="MRVA identity; defaults to the bench identity or login username")
    new.add_argument("--server")
    clone = sub.add_parser("clone", help="reference a prior accepted fixed input")
    clone.add_argument("--session", type=int)
    clone.add_argument("--stage", choices=("D", "Q"), required=True)
    clone.add_argument("--from-session", type=int, default=1)
    clone.add_argument("--no-advance", action="store_true")
    infrastructure = sub.add_parser("infrastructure", help="manage bench-owned analysis services")
    infrastructure.add_argument("action", choices=("setup", *services.ACTIONS))
    catalogue = sub.add_parser("catalogue", help="load a database library")
    catalogue.add_argument("path")
    catalogue.add_argument("--session", type=int, help="load only for this session")
    catalogue.add_argument("--source", choices=("list", "user"), default="list")
    library = sub.add_parser("library", help="index a query library")
    library.add_argument("directory")
    library.add_argument("--session", type=int, help="index only for this session")
    for kind in ("databases", "query"):
        choose = sub.add_parser(f"choose-{kind}", help="select library table rows and prepare them")
        choose.add_argument("--session", type=int)
        choose.add_argument("--generation", required=True)
        choose.add_argument("--rows", nargs="+", type=int, required=True)
        choose.add_argument("--source", choices=("list", "user"), default="list")
        choose.add_argument("--no-advance", action="store_true")
    create = sub.add_parser("create-query", help="create a persistent editable query starter")
    create.add_argument("--session", type=int)
    create.add_argument("--directory", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--language", required=True)
    edit = sub.add_parser("edit-query", help="save and reindex a user query")
    edit.add_argument("--session", type=int)
    edit.add_argument("--source", required=True)
    draft = sub.add_parser("copy-query", help="copy query source into an isolated editable draft")
    draft.add_argument("--session", type=int)
    draft.add_argument("--directory", required=True)
    source = draft.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-session", type=int)
    source.add_argument("--generation")
    draft.add_argument("--row", type=int)
    draft.add_argument("--source", choices=("list", "user"), default="list")
    for command in ("database", "query", "advance", "work", "tool"):
        part = sub.add_parser(command)
        part.add_argument("--session", type=int)
        if command in ("database", "query"):
            part.add_argument("--selection")
            part.add_argument("--source", choices=("list", "user"), default="list")
            part.add_argument("--no-advance", action="store_true")
        if command == "database":
            part.add_argument("--dbdir")
        if command == "query":
            part.add_argument("--pack")
            part.add_argument("--pack-index", type=int, default=0)
        if command in ("work", "tool"):
            part.add_argument("--stage", choices=("D", "Q"), required=True)
        if command == "work":
            part.add_argument("--note", required=True)
        if command == "tool":
            part.add_argument("arguments", nargs=argparse.REMAINDER)
    show = sub.add_parser("show", help="inspect a canonical cell or column alias")
    show.add_argument("address", nargs="?", default="E")
    sub.add_parser("info", help="experiment summary")
    comparison = sub.add_parser("compare", help="explicitly compare complete variants against S1")
    comparison.add_argument("sessions", nargs="*", type=int)
    serve = sub.add_parser("serve", help="serve the mutable experiment grid on loopback")
    serve.add_argument("--port", type=int, default=8610)
    serve.add_argument("--editor-port", type=int, default=0,
                       help="VS Code base port: S1 uses PORT, S2 PORT+1, etc. "
                            "(default: 0, automatically allocated per session)")
    serve.add_argument("--session-file", help="CGAST file outside an initialized workflow")
    serve.add_argument("--no-services", action="store_true",
                       help="serve the UI without automatic infrastructure setup")
    serve.add_argument("--no-assistant", action="store_true",
                       help="do not prestart Copilot (the panel can still start it on demand)")
    stop = sub.add_parser("stop", help="stop this bench viewer and its editors, not MRVA services")
    stop.add_argument("--session-file", help="CGAST file outside an initialized workflow")
    return enhance_parser(root, "bench")


def execute(state: dict, arguments: list[str]) -> dict:
    args = parser().parse_args(arguments)
    if args.command == "init":
        model.init(state, args.name, args.mode)
    elif args.command == "mode":
        for item in model.experiment(state)["sessions"]:
            engine.synchronize(item)
        model.set_mode(state, args.mode)
    elif args.command == "clone":
        for item in model.experiment(state)["sessions"]:
            engine.synchronize(item)
        item = model.clone(state, args.session, args.stage, args.from_session)
        if not args.no_advance:
            engine.advance(state, item)
    elif args.command == "session":
        sessions = model.experiment(state)["sessions"]
        for item in sessions:
            engine.synchronize(item)
        name = args.name
        if name is None:
            prefix = f"session-{len(sessions) + 1}"
            name = prefix
            names = {item["name"] for item in sessions}
            suffix = 2
            while name in names:
                name = f"{prefix}-{suffix}"
                suffix += 1
        user = args.user
        if user is None:
            user = sessions[0]["user"] if sessions else getpass.getuser()
        model.add(state, name, user, args.server)
    elif args.command == "infrastructure":
        services.run(state, args.action)
    elif args.command in ("catalogue", "library"):
        model.fixed_stage(state)
        tool, arguments = ("dl", ["getmeta", args.path]) if args.command == "catalogue" \
            else ("ql", ["index", args.directory])
        if args.session is None:
            updated = engine.run_tool(state, tool, arguments)
            state.clear()
            state.update(updated)
        else:
            item = model.session(state, args.session)
            engine.synchronize(item)
            model.input_editable(state, item, "D" if tool == "dl" else "Q")
            engine.tool(item, "D" if tool == "dl" else "Q", [tool, *arguments])
            libraries = item["workspace"].setdefault("cgabench-libraries", {})
            key = "cgadl-metadata" if tool == "dl" else "cgaql-index"
            libraries[key] = item["workspace"][key]
            libraries["catalogue" if tool == "dl" else "query_directory"] = arguments[1]
            if args.command == "catalogue" and args.source == "user":
                libraries["built_catalogue"] = args.path
                libraries["built"] = {"cgadl-metadata": item["workspace"]["cgadl-metadata"]}
            model.experiment(state)["active"] = item["index"]
    elif args.command in ("choose-databases", "choose-query"):
        inputs.choose(state, args.session,
                      "databases" if args.command == "choose-databases" else "queries",
                      args.generation, args.rows, args.source, args.no_advance)
    elif args.command == "create-query":
        inputs.create_query(state, args.session, args.directory, args.name, args.language)
    elif args.command == "edit-query":
        inputs.edit_query(state, args.session, args.source)
    elif args.command == "copy-query":
        inputs.copy_query(state, args.session, args.directory, args.from_session,
                          args.generation, args.row, args.source)
    elif args.command in ("database", "query", "advance", "work", "tool"):
        item = model.session(state, args.session)
        engine.synchronize(item)
        if args.command == "database":
            model.accept_database(state, item, args.selection, args.dbdir, args.source)
        elif args.command == "query":
            model.accept_query(state, item, args.selection, args.pack,
                               args.pack_index, args.source)
        elif args.command == "work":
            model.input_editable(state, item, args.stage)
            item[args.stage]["history"].append({
                "at": utc_now(), "action": "work", "note": args.note})
        elif args.command == "tool":
            model.input_editable(state, item, args.stage)
            engine.tool(item, args.stage, args.arguments)
        if args.command == "advance" or args.command in ("database", "query") \
                and not args.no_advance:
            engine.advance(state, item)
        model.experiment(state)["active"] = item["index"]
    elif args.command == "compare":
        for item in model.experiment(state)["sessions"]:
            engine.synchronize(item)
        document = compare.compare(state, args.sessions)
        cgast.info(f"cgabench: {len(document['common'])} common finding(s)")
    elif args.command in ("show", "info"):
        view = model.projection(state, getattr(args, "address", "E"))
        cgast.info(json.dumps(view, indent=2))
    else:
        raise WorkflowError(f"{args.command} is not a CGAST filter")
    return state


def main(arguments: list[str]) -> int:
    args = parser().parse_args(arguments)
    if args.command in ("serve", "stop"):
        from . import lifecycle
        from .server import serve

        try:
            if args.command == "stop":
                lifecycle.stop(args.session_file)
            else:
                serve(args.port, args.session_file, not args.no_services,
                      editor_port=args.editor_port, start_assistant=not args.no_assistant)
        except (WorkflowError, OSError) as exc:
            cgast.die(f"cgabench: {exc}", 2)
        return 0
    state = cgast.read()
    try:
        execute(state, arguments)
    except (WorkflowError, OSError, ValueError) as exc:
        # Preserve successful operations even when a later one fails. The top-level
        # workflow keeps its failure journal; raw filters can save this stdout.
        cgast.write(state)
        cgast.die(f"cgabench: {exc}", 2)
    cgast.write(state)
    return 0

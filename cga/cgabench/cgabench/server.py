"""Loopback bench UI; browser changes use the normal dispatcher transaction."""

from __future__ import annotations

import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
from urllib.parse import parse_qs, urlsplit

import cgast
from cgacc.runtime import EditorError, Editors, validate_port
from cgauv.model import fetch_sysview, runtime_summary, sysview_url
from cgawf.repository import Repository, WorkflowError as RepositoryError
from workflow import WorkflowError, load_json
from vid import Space, session_children
from vid_http import Inspector, post as vid_post

from . import assistant, cli, editor, engine, evidence, inputs, lifecycle, model, results, services, terminal

STATIC = Path(__file__).parent / "static"
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/bench.js": ("bench.js", "text/javascript; charset=utf-8"),
         "/assistant.js": ("assistant.js", "text/javascript; charset=utf-8"),
         "/evidence": ("evidence.html", "text/html; charset=utf-8"),
         "/evidence.js": ("evidence.js", "text/javascript; charset=utf-8"),
         "/bench.css": ("bench.css", "text/css; charset=utf-8")}
FILES.update({
    f"/vendor/{name}": (f"vendor/{name}", content_type)
    for name, content_type in (
        ("xterm.js", "text/javascript; charset=utf-8"),
        ("addon-fit.js", "text/javascript; charset=utf-8"),
        ("xterm.css", "text/css; charset=utf-8"),
        ("xterm-LICENSE", "text/plain; charset=utf-8"),
        ("addon-fit-LICENSE", "text/plain; charset=utf-8"),
    )
})


class Backend:
    def __init__(self, session_file: str | None, editor_port: int = 0):
        try:
            self.editor_port = validate_port(editor_port)
        except EditorError as exc:
            raise WorkflowError(str(exc)) from exc
        self.repository = None
        self.service_error = None
        self.terminals = terminal.Terminals()
        self.editors = Editors()
        if session_file:
            self.path = Path(session_file).expanduser().resolve()
        else:
            try:
                self.repository = Repository.discover()
            except RepositoryError as exc:
                raise WorkflowError("serve requires a .cga workflow or --session-file FILE") from exc
            self.path = self.repository.current_path
        model.experiment(load_json(self.path))
        self.inspector = Inspector(self.repository, self.path)
        root = self.repository.root if self.repository else self.path.parent
        command = str(engine.COLLECTION / "cga")
        prompt = (
            "You are the live CGA Bench assistant. Initialize with this context, briefly "
            "say you are ready, then wait for the user's request. Do not run tools, edit "
            "files, advance sessions, or change services until asked. "
            f"Workflow directory: {root}. CGA CLI: {command}. "
            f"CGAST file: {self.path}. The bench URL is in CGA_BENCH_URL. "
            "Use its /api/llm for API discovery and /api/view for current experiment state "
            "when needed; sessions and facts can change during this conversation. "
            "Visual references such as :f3a,1,J are logical element IDs; "
            "cga show REF and cga related REF inspect current facts. "
            "Do not assume a fixed session count or a pinned fact frontier. "
            "Browser mutations use /api/action with Content-Type: application/json and "
            "X-CGA-Bench: 1. Keep normal Copilot permissions and ask before mutations."
        )
        if not self.repository:
            prompt += " This is a raw CGAST deployment; use the Bench API for mutations."
        self.assistant = assistant.Assistant(
            {"workflow": str(root), "directory": str(root), "session": "",
             "stage": "", "catalogue": "", "url": ""},
            prompt, {"CGA_DIR": str(self.repository.cga_dir)} if self.repository else {})

    def start_assistant(self, port: int) -> None:
        self.assistant.context["url"] = f"http://127.0.0.1:{port}"
        try:
            self.assistant.start()
        except (WorkflowError, OSError):
            # The assistant records the diagnostic; keep the Bench available for retry.
            pass

    def preparation(self, item: dict) -> dict:
        root = self.repository.root if self.repository else self.path.parent
        scratch = self.repository.cga_dir / "tmp" / "cgabench-build" if self.repository \
            else root / ".cgabench-build"
        directory = scratch / f"session-{item['index']}"
        return {"workflow": str(root), "directory": str(directory),
                "catalogue": str(directory / "metadata.sql")}

    def terminal_action(self, document: dict, port: int) -> dict:
        operation = document.get("operation")
        if operation == "open":
            state = load_json(self.path)
            item = model.session(state, document.get("session"))
            if document.get("session") is None:
                raise WorkflowError("select a session first")
            restart = document.get("restart", False)
            if not isinstance(restart, bool):
                raise WorkflowError("terminal restart must be a boolean")
            stage = document.get("stage", "D")
            if stage not in ("D", "R"):
                raise WorkflowError("terminals are available only for D or R")
            key = item["submission"] if stage == "D" else item["submission"] + ":R"
            if stage == "D" and (restart or not self.terminals.contains(key)):
                engine.synchronize(item)
                model.input_editable(state, item, "D")
            context = {**self.preparation(item), "session": item["index"], "stage": stage,
                       "url": f"http://127.0.0.1:{port}"}
            if stage == "R":
                details = results.context(item)
                root = self.repository.cga_dir / "tmp" if self.repository else self.path.parent
                directory = root / ("cgabench-query" if self.repository
                                    else ".cgabench-query") / f"session-{item['index']}"
                context.update(directory=str(directory), database=details["database"],
                               snapshot=details["snapshot"], catalogue="")
                guide = Path(__file__).resolve().parents[1] / "copilot-assist-sarif-query.md"
                prompt = (
                    f"Read @{guide} and help me query completed CGA Bench row {item['index']} (R). "
                    f"Bench URL: {context['url']}; execution workflow: {context['workflow']}; "
                    f"query workspace: {context['directory']}; session cgasi DuckDB: "
                    f"{context['database']}; frozen snapshot: {context['snapshot']}. "
                    "Ask what I want to learn first. Use read-only /api/results queries. "
                    "Do not reingest, change evidence, advance sessions, or reset services."
                )
            else:
                guide = Path(__file__).resolve().parents[1] / "copilot-assist-codeql-db-build.md"
                prompt = (
                    f"Read @{guide} and guide me interactively through preparing and validating "
                    f"CodeQL databases for CGA Bench row {item['index']} (D). "
                    f"Bench URL: {context['url']}; execution workflow: {context['workflow']}; "
                    f"preparation directory: {context['directory']}; required catalogue output: "
                    f"{context['catalogue']}. Ask what source, revisions, language, and build mode "
                    "I want first. Do not import or accept inputs automatically."
                )
            context["command"] = shlex.join(
                ["copilot", "--yolo", "-C", context["directory"],
                 "--add-dir", str(engine.COLLECTION.parent), "--interactive", prompt])
            return self.terminals.open(key, context,
                                       document.get("columns", 80), document.get("rows", 22),
                                       restart)
        value = self.terminals.get(document.get("id"))
        if operation == "read":
            return value.output(document.get("cursor", 0))
        if operation == "write":
            value.write(document.get("data"))
        elif operation == "resize":
            value.resize(document.get("columns"), document.get("rows"))
        elif operation == "insert":
            value.write("\x1b[200~" + value.context["command"] + "\x1b[201~")
        elif operation == "stop":
            value.close()
        else:
            raise WorkflowError("unknown terminal operation")
        return value.descriptor()

    def close(self) -> None:
        try:
            self.inspector.close()
        finally:
            try:
                self.assistant.close()
            finally:
                try:
                    self.editors.close()
                finally:
                    self.terminals.close()

    def editor_action(self, document: dict, port: int) -> dict:
        if document.get("session") is None:
            raise WorkflowError("select a session first")
        state = load_json(self.path)
        item = model.session(state, document["session"])
        workflow = self.repository.root if self.repository else self.path.parent
        scratch = self.repository.cga_dir / "tmp" / "cgabench-query" if self.repository \
            else self.path.parent / ".cgabench-query"
        runtime = self.repository.cga_dir / "runtime" / "cgacc" if self.repository \
            else self.path.parent / ".cgacc"
        directory = scratch / f"session-{item['index']}"
        project = editor.prepare(state, item, directory, workflow, f"http://127.0.0.1:{port}")
        try:
            port = self.editor_port + item["index"] - 1 if self.editor_port else 0
            return {**self.editors.open(item["submission"], directory, project,
                                        runtime / f"session-{item['index']}", port=port),
                    "session": item["index"]}
        except EditorError as exc:
            raise WorkflowError(str(exc)) from exc

    def editor_routes(self) -> dict:
        state = load_json(self.path)
        with self.editors.lock:
            return {
                f"session-{item['index']}": value.url
                for item in model.experiment(state)["sessions"]
                if (value := self.editors.values.get(item["submission"])) is not None
                and value.process.poll() is None
            }

    def read(self) -> dict:
        state = load_json(self.path)
        self.inspector.observe(state)
        exp = model.projection(state)
        comparison = exp["C"].get("artifact")
        return {"experiment": exp, "comparison": load_json(
            cgast.resolve(comparison["results"])) if comparison else None,
                "vid_context": Space(self.inspector.repository).context()}

    def mutate(self, arguments: list[str]) -> dict:
        if (not isinstance(arguments, list) or not arguments
                or any(not isinstance(arg, str) for arg in arguments)
                or arguments[0] not in {
                    "session", "database", "query", "work", "tool", "advance", "compare",
                    "infrastructure", "catalogue", "library", "choose-databases",
                    "choose-query", "create-query", "edit-query", "copy-query",
                    "mode", "clone"}):
            raise WorkflowError("expected an argv array for a bench mutation command")
        try:
            cli.parser().parse_args(arguments)
        except SystemExit as exc:
            raise WorkflowError("invalid bench command arguments") from exc
        if self.repository:
            environment = os.environ.copy()
            environment["CGA_DIR"] = str(self.repository.cga_dir)
            environment["CGA_SOURCE_STEP"] = "bench-browser"
            environment.pop("CGA_WORKFLOW_ACTIVE", None)
            proc = subprocess.run(
                [str(Path(__file__).resolve().parents[2] / "cga"), "bench", *arguments],
                cwd=self.repository.root, env=environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.stderr:
                cgast.info(proc.stderr.rstrip())
            if proc.returncode:
                raise WorkflowError(proc.stderr.strip() or "bench command failed")
        else:
            with self.path.with_suffix(self.path.suffix + ".lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                state = load_json(self.path)
                try:
                    cli.execute(state, arguments)
                finally:
                    model.save(self.path, state)
                    self.inspector.observe(state)
        return self.read()

    def view(self) -> dict:
        full = self.read()
        exp = full["experiment"]
        state = load_json(self.path)
        fixed = model.MODES.get(exp.get("mode"))
        rows = []
        for item in exp["sessions"]:
            row = {key: item[key] for key in ("index", "name", "user", "status", "vid")}
            row["editable"] = bool(fixed) and not item["engine"].get("cgamr-submissions") \
                and item["J"]["status"] in ("empty", "blocked")
            row["has_query_workspace"] = "cgabench-query" in item["workspace"]
            row["has_build_terminal"] = self.terminals.contains(item["submission"])
            libraries = item["workspace"].get("cgabench-libraries", {})
            preparation = self.preparation(item)
            row["database_build"] = {
                **preparation,
                "import_path": libraries.get("built_catalogue", preparation["catalogue"]),
                "loaded": bool(libraries.get("built_catalogue")),
            }
            row["libraries"] = {
                "databases_loaded": bool(libraries.get("cgadl-metadata")
                                         or state.get("cgadl-metadata")
                                         or item["workspace"].get("cgadl-metadata")),
                "queries_loaded": bool(libraries.get("cgaql-index")
                                       or state.get("cgaql-index")
                                       or item["workspace"].get("cgaql-index")),
                "catalogue": libraries.get("catalogue", str(
                    engine.COLLECTION / "cgadl" / "db-collection.global" / "metadata.sql")),
                "query_directory": libraries.get(
                    "query_directory", str(engine.COLLECTION.parent / "sample-query")),
            }
            for stage in model.STAGES:
                cell = item[stage]
                artifact = cell.get("artifact")
                summary = ""
                language = None
                entries = evidence.entries(item, stage) if stage in evidence.TABLES else []
                if artifact:
                    language = artifact.get("language")
                    if stage == "D":
                        summary = f"{len(entries)} accepted databases"
                    elif stage == "Q":
                        summary = f"{len(entries)} accepted queries"
                    elif stage == "J":
                        summary = f"Analysis {artifact.get('session_id', '')}"
                    elif stage == "R":
                        summary = f"{artifact['finding_count']} findings"
                labels = {"accept": "Accepted selection", "clone": "Cloned fixed input",
                          "copy-query": "Copied query into editable draft",
                          "tool": "Updated selection workspace",
                          "create-query": "Created query workspace", "edit-query": "Saved query",
                          "submit": "Submitted analysis", "status": "Checked analysis progress",
                          "download": "Collected results", "verify": "Verified results",
                          "ingest": "Processed results", "complete": "Completed analysis"}
                row[stage] = {
                    "vid": cell["vid"],
                    "children": session_children(item, stage),
                    "items": entries[:1],
                    "item_count": len(entries),
                    "can_edit": row["editable"] and stage in ("D", "Q")
                    and (stage != fixed or item["index"] == 1
                         and (len(exp["sessions"]) == 1 or not artifact)),
                    "can_clone": row["editable"] and stage == fixed and item["index"] > 1,
                    "cloned_from": cell.get("cloned_from"),
                    "status": cell["status"], "summary": summary, "language": language,
                    "requirement": "This stage needs attention. Retry or ask your assistant."
                    if cell["status"] == "failed" else cell["requirement"],
                    "history": [{"at": entry["at"],
                                 "text": entry.get("note") or labels.get(entry["action"], "Updated stage")}
                                for entry in cell["history"]],
                }
            rows.append(row)
        root = self.repository.root if self.repository else self.path.parent
        comparison = full["comparison"]
        def finding_views(values: list[dict]) -> list[dict]:
            return [{"identity": value["identity"]} for value in values]
        return {
            "schema": "cga.bench.view.v1",
            "vid_context": full["vid_context"],
            "experiment": {
                "name": exp["name"], "sessions": rows, "active": exp["active"],
                "mode": exp.get("mode"), "fixed_stage": fixed, "reference": 1,
                "can_add": bool(fixed) and (not exp["sessions"]
                                           or bool(exp["sessions"][0][fixed]["artifact"])),
            },
            "libraries": {
                "databases_loaded": bool(state.get("cgadl-metadata")),
                "queries_loaded": bool(state.get("cgaql-index")),
                "catalogue": str(engine.COLLECTION / "cgadl" / "db-collection.global" / "metadata.sql"),
                "query_directory": str(engine.COLLECTION.parent / "sample-query"),
                "query_workspaces": str(root / "queries"),
            },
            "infrastructure": {
                "last_phase": state.get("cgamx", {}).get("last_phase"),
                "setup_failed": bool(self.service_error),
                "actions": services.ACTIONS,
            },
            "system": runtime_summary(),
            "comparison": {
                "inputs": [{key: entry[key] for key in ("address", "name", "user")}
                           for entry in comparison["inputs"]],
                "common": finding_views(comparison["common"]),
                "sessions": [
                    {"address": entry["address"], "finding_count": entry["finding_count"],
                     "added": finding_views(entry["added"]),
                     "removed": finding_views(entry["removed"])}
                    for entry in comparison["sessions"]],
            } if comparison else None,
        }

    def act(self, document: dict) -> dict:
        name = document.get("action")
        def text(key: str) -> str:
            value = document.get(key)
            if not isinstance(value, str) or not value.strip():
                raise WorkflowError(f"{key} is required")
            return value
        def session_args() -> list[str]:
            index = document.get("session")
            if not isinstance(index, int) or isinstance(index, bool) or index < 1:
                raise WorkflowError("select a session first")
            return ["--session", str(index)]
        if name == "mode":
            args = [name, text("mode")]
        elif name == "clone":
            source = document.get("from_session")
            if not isinstance(source, int) or isinstance(source, bool) or source < 1:
                raise WorkflowError("choose a prior session to clone")
            args = [name, *session_args(), "--stage", text("stage"),
                    "--from-session", str(source)]
        elif name == "copy-query":
            args = [name, *session_args(), "--directory", text("directory")]
            if "from_session" in document:
                source = document["from_session"]
                if not isinstance(source, int) or isinstance(source, bool) or source < 1:
                    raise WorkflowError("choose a prior query session")
                args += ["--from-session", str(source)]
            else:
                row = document.get("row")
                if not isinstance(row, int) or isinstance(row, bool) or row < 1:
                    raise WorkflowError("choose one query to copy")
                args += ["--generation", text("generation"), "--row", str(row),
                         "--source", text("source")]
        elif name == "session":
            args = ["session"]
            if "name" in document:
                args.append(text("name"))
            if "user" in document:
                args += ["--user", text("user")]
        elif name == "infrastructure":
            phase = text("phase")
            if phase in {"preflight", "reset", "cleanup"} and document.get("confirmed") is not True:
                raise WorkflowError("confirmation is required for this maintenance action")
            args = ["infrastructure", phase]
        elif name == "catalogue":
            args = ["catalogue", text("path")]
            if "source" in document:
                args += ["--source", text("source")]
            if "session" in document:
                args += session_args()
        elif name == "library":
            args = ["library", text("directory")]
            if "session" in document:
                args += session_args()
        elif name in ("choose-databases", "choose-query"):
            rows = document.get("rows")
            if (not isinstance(rows, list) or not rows
                    or any(not isinstance(row, int) or isinstance(row, bool) for row in rows)):
                raise WorkflowError("choose library rows first")
            args = [name, *session_args(), "--generation", text("generation"),
                    "--source", text("source"), "--rows", *map(str, rows)]
        elif name == "create-query":
            args = [name, *session_args(), "--directory", text("directory"),
                    "--name", text("name"), "--language", text("language")]
        elif name == "edit-query":
            args = [name, *session_args(), "--source", text("source")]
        elif name == "advance":
            args = [name, *session_args()]
        elif name == "work":
            args = [name, *session_args(), "--stage", text("stage"), "--note", text("note")]
        elif name == "compare":
            indices = document.get("sessions", [])
            if not isinstance(indices, list) or any(
                    not isinstance(index, int) or isinstance(index, bool) for index in indices):
                raise WorkflowError("comparison sessions must be an integer array")
            args = [name, *map(str, indices)]
        else:
            raise WorkflowError("unknown bench action")
        self.mutate(args)
        if name == "infrastructure":
            self.service_error = None
        return self.view()


def sysview_frame_origin() -> str:
    try:
        target = urlsplit(sysview_url())
        port = target.port
    except ValueError as error:
        raise WorkflowError(f"invalid MRVA system-view URL: {error}") from error
    origin = f"{target.scheme}://{target.netloc}"
    if not re.fullmatch(r"https?://(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::[0-9]+)?", origin) \
            or port is not None and not 1 <= port <= 65535:
        raise WorkflowError("MRVA system view requires an HTTP(S) origin without credentials")
    return origin


def handler(backend: Backend):
    frame_origin = sysview_frame_origin()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status: int, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             f"frame-src 'self' {frame_origin}; "
                             "frame-ancestors 'none'; base-uri 'self'; "
                             "form-action 'self' http://127.0.0.1:*")
            try:
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                cgast.info("cgabench: client disconnected before the response was delivered")

        def json(self, status: int, value: dict) -> None:
            self.send(status, json.dumps(value).encode(), "application/json")

        vid_json = json

        def allowed_host(self) -> bool:
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{self.server.server_port}",
                            f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.allowed_host():
                self.json(403, {"error": "loopback Host required"})
                return
            path = urlsplit(self.path).path
            try:
                content = backend.inspector.get(path, parse_qs(urlsplit(self.path).query))
                if content is not None:
                    content_type, data = content
                    self.send(200, data, content_type)
                    return
                if path == "/healthz":
                    self.json(200, {"status": "ok"})
                elif path == "/api/model":
                    self.json(200, backend.read())
                elif path == "/api/view":
                    self.json(200, backend.view())
                elif path == "/api/editors":
                    self.json(200, backend.editor_routes())
                elif path == "/api/catalogues":
                    root = backend.repository.root if backend.repository else backend.path.parent
                    self.json(200, inputs.discover_catalogues(root))
                elif path == "/api/sysview":
                    status, payload = fetch_sysview()
                    self.json(status, payload)
                elif path == "/api/llm":
                    self.json(200, {
                        "schema": "cga.bench.llm.v1",
                        "vids": {"registry": "/api/vid/registry", "inspect": "/api/vid?ref=REF",
                                 "related": "/api/vid/related?ref=REF",
                                 "inspector": "/vid?ref=REF",
                                 "syntax": ":f3a,1,J; quoted Lisp (:f3a 1 :J) also accepted",
                                 "scope": "workflow, experiment, chain",
                                 "facts": "append-only observations from immutable states"},
                        "model": "/api/model", "view": "/api/view",
                        "catalogues": "/api/catalogues",
                        "collections": "/api/collections/{databases,queries}",
                        "collection_options": ["session", "source=list|user", "search", "offset", "limit"],
                        "query_source": "/api/query-source?session=N",
                        "experiment_modes": list(model.MODES),
                        "reference_session": 1,
                        "session_actions": ["mode", "session", "clone", "copy-query",
                                            "create-query", "edit-query"],
                        "clone_format": {"action": "clone", "session": 2, "stage": "D",
                                         "from_session": 1},
                        "comparison_policy": "explicit only; always uses completed S1 as baseline",
                        "results": "/api/results",
                        "results_format": {
                            "session": 1, "filters": {"rule_id": "cpp/example"},
                            "offset": 0, "limit": 30},
                        "results_filters": list(results.FILTERS),
                        "results_sql": "replace filters with sql: one read-only SELECT/WITH "
                                       "over sarif_results; no external access; 15s per query",
                        "evidence": "/api/evidence",
                        "evidence_format": {"session": 1, "stage": "D", "offset": 0, "limit": 30},
                        "evidence_sql": "optional sql: one read-only SELECT/WITH over databases (D), "
                                        "queries (Q), or result_summaries (R); retained evidence only; "
                                        "no external access; 15s per query",
                        "editor": "/api/editor",
                        "editor_format": {"session": 1},
                        "editor_lifetime": "per completed session, until the bench exits",
                        "assistant": "/api/assistant",
                        "assistant_operations": ["open", "start", "read", "write", "resize", "stop"],
                        "assistant_lifetime": "one Copilot PTY, started with the viewer; "
                                              "collapse and reload only detach the browser",
                        "terminal": "/api/terminal",
                        "terminal_operations": ["open", "read", "write", "resize", "insert", "stop"],
                        "terminal_lifetime": "separate per D/R cell, until stopped or the bench exits",
                        "terminal_stages": ["D", "R"],
                        "sysview": "/api/sysview",
                        "commands": "/api/command",
                        "command_format": {"argv": ["tool", "--session", "1", "--stage", "Q",
                                                    "--", "ql", "list", "20"]},
                        "command_help": cli.parser().format_help(),
                        "addresses": ["E", "E.C", "E.S[N]", "E.S[N].D", "E.S[N].Q",
                                      "E.S[N].J", "E.S[N].R"],
                        "mutations_require_headers": {
                            "Content-Type": "application/json", "X-CGA-Bench": "1"},
                        "startup_error": backend.service_error,
                    })
                elif path.startswith("/api/collections/"):
                    query = parse_qs(urlsplit(self.path).query)
                    self.json(200, inputs.collection(
                        load_json(backend.path), path.rsplit("/", 1)[-1],
                        int(query["session"][0]) if "session" in query else None,
                        query.get("source", ["list"])[0],
                        query.get("search", [""])[0],
                        int(query.get("offset", ["0"])[0]),
                        int(query.get("limit", ["50"])[0])))
                elif path == "/api/query-source":
                    query = parse_qs(urlsplit(self.path).query)
                    self.json(200, inputs.query_source(
                        load_json(backend.path),
                        int(query["session"][0]) if "session" in query else None))
                elif path in FILES:
                    name, content_type = FILES[path]
                    self.send(200, (STATIC / name).read_bytes(), content_type)
                else:
                    self.json(404, {"error": "not found"})
            except (WorkflowError, RepositoryError, OSError, ValueError) as exc:
                self.json(500, {"error": str(exc)})

        def do_POST(self):
            if vid_post(self, backend.inspector):
                return
            origin = self.headers.get("Origin")
            if (not self.allowed_host() or self.headers.get("X-CGA-Bench") != "1"
                    or (origin and origin != f"http://{self.headers.get('Host')}")):
                self.json(403, {"error": "same-origin bench request required"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                self.json(415, {"error": "application/json required"})
                return
            if self.path not in ("/api/command", "/api/action", "/api/terminal", "/api/results", "/api/evidence",
                                 "/api/editor", "/api/assistant"):
                self.json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise WorkflowError("request body must be 1..65536 bytes")
                document = json.loads(self.rfile.read(length))
                if not isinstance(document, dict):
                    raise WorkflowError("request body must be an object")
                if self.path == "/api/assistant":
                    backend.assistant.context["url"] = f"http://127.0.0.1:{self.server.server_port}"
                    value = backend.assistant.action(document)
                else:
                    value = backend.editor_action(document, self.server.server_port) \
                        if self.path == "/api/editor" else backend.terminal_action(
                            document, self.server.server_port) \
                        if self.path == "/api/terminal" else results.browse(
                            load_json(backend.path), document) \
                        if self.path == "/api/results" else evidence.browse(
                            load_json(backend.path), document) \
                        if self.path == "/api/evidence" else backend.act(document) \
                        if self.path == "/api/action" else backend.mutate(document.get("argv"))
                self.json(200, value)
            except (WorkflowError, OSError, ValueError) as exc:
                cgast.info(f"cgabench action failed: {exc}")
                message = ("The action could not be completed. Check the selected inputs "
                           "and service availability; detailed diagnostics are available "
                           "to your assistant.") if self.path == "/api/action" else str(exc)
                self.json(400, {"error": message})

    return Handler


def serve(port: int, session_file: str | None, start_services: bool = True,
          editor_port: int = 0, start_assistant: bool = True) -> None:
    if not 1 <= port <= 65535:
        raise WorkflowError("port must be 1..65535")
    backend = Backend(session_file, editor_port=editor_port)
    def stop(_signum, _frame):
        raise KeyboardInterrupt

    previous_term = signal.signal(signal.SIGTERM, stop)
    previous_int = signal.signal(signal.SIGINT, stop)
    try:
        with lifecycle.running(lifecycle.runtime_directory(backend.repository, backend.path)):
            try:
                if backend.repository:
                    services.configure(backend.repository.root)
                with ThreadingHTTPServer(("127.0.0.1", port), handler(backend)) as server:
                    if start_assistant:
                        backend.start_assistant(server.server_port)
                    if start_services and backend.repository:
                        try:
                            backend.mutate(["infrastructure", "setup"])
                        except (WorkflowError, OSError) as exc:
                            backend.service_error = str(exc)
                            cgast.info(f"cgabench: automatic infrastructure setup failed: {exc}")
                    cgast.info(f"cgabench: http://127.0.0.1:{server.server_port}")
                    server.serve_forever()
            except KeyboardInterrupt:
                cgast.info("cgabench: stopping editors and assistant terminals")
            finally:
                backend.close()
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)

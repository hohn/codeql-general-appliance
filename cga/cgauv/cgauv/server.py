"""HTTP server for CGA Unified View."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import signal
import threading
from urllib.parse import parse_qs, urlsplit

from cgawf.repository import Repository, WorkflowError
from command_help import enhance_parser
from vid_http import Inspector, post as vid_post

from .model import (
    artifact_detail,
    collection_model,
    fetch_sysview,
    flow_source_path,
    outline_markdown,
    outline_model,
    search_markdown,
    search_model,
    step_detail,
    workflow_model,
)


STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/cgauv.css": ("cgauv.css", "text/css; charset=utf-8"),
    "/cgauv.js": ("cgauv.js", "text/javascript; charset=utf-8"),
}
EXISTING_EXPORTS = {
    "/existing/replay": (
        "CGA_DASHBOARD_EXPORT",
        "mrva-flow-replay.html",
    ),
    "/existing/dfg": (
        "CGA_DFG_EXPORT",
        "mrva-flow-data-flow.html",
    ),
    "/existing/cfg": (
        "CGA_CFG_EXPORT",
        "mrva-flow-control-flow.html",
    ),
}


def _export_path(environment_name: str, default_name: str) -> Path:
    configured = os.environ.get(environment_name)
    if configured:
        return Path(configured).expanduser().resolve()
    repository = Repository.discover()
    tmp_dir = Path(
        os.environ.get("CGA_TMPDIR", repository.cga_dir / "tmp")
    ).expanduser().resolve()
    return tmp_dir / default_name


class Handler(BaseHTTPRequestHandler):
    server_version = "cgauv"
    inspector_lock = threading.Lock()

    def inspector(self):
        with self.inspector_lock:
            if not hasattr(self.server, "vid_inspector"):
                self.server.vid_inspector = Inspector(Repository.discover())
            return self.server.vid_inspector

    def log_message(self, *_args: object) -> None:
        pass

    def _send(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        try:
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            print("cgauv: client disconnected before the response was delivered", file=sys.stderr)

    def _json(self, status: int, value: object) -> None:
        self._send(
            status,
            (json.dumps(value, ensure_ascii=True) + "\n").encode(),
            "application/json",
        )

    vid_json = _json

    def do_POST(self) -> None:  # noqa: N802
        if not vid_post(self, self.inspector()):
            self._json(404, {"error": "no route"})

    def _text(self, status: int, value: str, content_type: str) -> None:
        self._send(status, value.encode(), content_type)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.startswith(("/vid", "/api/vid")):
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{self.server.server_port}",
                            f"localhost:{self.server.server_port}"}:
                self._json(403, {"error": "loopback Host required"})
                return
            try:
                content = self.inspector().get(path, parse_qs(parsed.query))
                if content is None:
                    self._json(404, {"error": "no VID route"})
                else:
                    mime, data = content
                    self._send(200, data, mime)
            except (WorkflowError, OSError, ValueError) as error:
                self._json(400, {"error": str(error)})
            return
        if path == "/healthz":
            self._send(200, b"ok", "text/plain; charset=utf-8")
            return
        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            try:
                content = (STATIC / filename).read_bytes()
            except OSError as error:
                self._json(500, {"error": str(error)})
                return
            self._send(200, content, content_type)
            return
        if path in EXISTING_EXPORTS:
            environment_name, default_name = EXISTING_EXPORTS[path]
            try:
                content = _export_path(environment_name, default_name).read_bytes()
            except (OSError, WorkflowError) as error:
                self._json(404, {"error": str(error)})
                return
            self._send(200, content, "text/html; charset=utf-8")
            return
        if path == "/existing/source":
            try:
                repository = Repository.discover()
                content = flow_source_path(repository).read_bytes()
            except (OSError, WorkflowError) as error:
                self._json(404, {"error": str(error)})
                return
            self._send(200, content, "text/plain; charset=utf-8")
            return
        try:
            repository = Repository.discover()
            if path == "/api/model":
                self._json(200, workflow_model(repository))
                return
            if path == "/api/outline":
                query = parse_qs(parsed.query)
                document = outline_model(
                    repository,
                    query.get("detail", ["steps"])[0],
                    query.get("tag", []),
                    _boolean(query, "include_sensitive", False),
                    True,
                )
                if query.get("format", ["json"])[0] == "markdown":
                    self._text(
                        200,
                        outline_markdown(document),
                        "text/markdown; charset=utf-8",
                    )
                else:
                    self._json(200, document)
                return
            if path == "/api/search":
                query = parse_qs(parsed.query)
                document = search_model(
                    repository,
                    query.get("q", [""])[0],
                    query.get("tag", []),
                    query.get("kind", []),
                    _integer(query, "offset", 0),
                    _integer(query, "limit", 50),
                    _boolean(query, "include_sensitive", False),
                )
                if query.get("format", ["json"])[0] == "markdown":
                    self._text(
                        200,
                        search_markdown(document),
                        "text/markdown; charset=utf-8",
                    )
                else:
                    self._json(200, document)
                return
            if path.startswith("/api/collections/"):
                kind = path.removeprefix("/api/collections/")
                query = parse_qs(parsed.query)
                filters = _filters(query.get("filter", []))
                self._json(200, collection_model(
                    repository,
                    kind,
                    query.get("q", [""])[0],
                    filters,
                    query.get("sort", [None])[0],
                    _integer(query, "offset", 0),
                    _integer(query, "limit", 50),
                ))
                return
            if path == "/api/step":
                step_id = parse_qs(parsed.query).get("id", [""])[0]
                if not step_id:
                    self._json(400, {"error": "missing step id"})
                    return
                self._json(200, step_detail(repository, step_id))
                return
            if path == "/api/artifact":
                artifact_id = parse_qs(parsed.query).get("id", [""])[0]
                if not artifact_id:
                    self._json(400, {"error": "missing artifact id"})
                    return
                self._json(200, artifact_detail(repository, artifact_id))
                return
            if path == "/api/sysview":
                status, value = fetch_sysview()
                self._json(status, value)
                return
        except WorkflowError as error:
            self._json(500, {"error": str(error)})
            return
        self._json(404, {"error": f"no route {path}"})


def _integer(query: dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(query.get(key, [str(default)])[0])
    except ValueError as error:
        raise WorkflowError(f"{key} must be an integer") from error


def _boolean(query: dict[str, list[str]], key: str, default: bool) -> bool:
    value = query.get(key)
    if not value:
        return default
    normalized = value[0].lower()
    if normalized in ("1", "true", "yes"):
        return True
    if normalized in ("0", "false", "no"):
        return False
    raise WorkflowError(f"{key} must be true or false")


def _filters(values: list[str]) -> dict[str, str]:
    filters = {}
    for value in values:
        if ":" not in value:
            raise WorkflowError(
                f"invalid filter {value!r}; expected field:value"
            )
        key, wanted = value.split(":", 1)
        if not key or not wanted:
            raise WorkflowError(
                f"invalid filter {value!r}; expected field:value"
            )
        filters[key] = wanted
    return filters


def serve() -> None:
    port = int(os.environ.get("CGA_CGAUV_PORT", "8609"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.vid_inspector = Inspector(Repository.discover())
    def stop(*_args):
        raise KeyboardInterrupt
    previous_term = signal.signal(signal.SIGTERM, stop)
    print(f"cgauv: CGA Unified View on http://127.0.0.1:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.vid_inspector.close()
        finally:
            server.server_close()
            signal.signal(signal.SIGTERM, previous_term)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cga uv")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve")
    outline = subparsers.add_parser("outline")
    outline.add_argument("--format", choices=("markdown", "json"), default="markdown")
    outline.add_argument("--detail", choices=("summary", "steps"), default="steps")
    outline.add_argument("--match-tag", action="append", default=[])
    outline.add_argument("--include-sensitive", action="store_true")
    search = subparsers.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--format", choices=("markdown", "json"), default="markdown")
    search.add_argument("--match-tag", action="append", default=[])
    search.add_argument("--kind", action="append", default=[])
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--include-sensitive", action="store_true")
    enhance_parser(parser, "uv")
    arguments = parser.parse_args(argv)
    if arguments.command == "serve":
        serve()
        return 0
    try:
        repository = Repository.discover()
        if arguments.command == "outline":
            document = outline_model(
                repository,
                arguments.detail,
                arguments.match_tag,
                arguments.include_sensitive,
                True,
            )
            if arguments.format == "json":
                print(json.dumps(document, indent=2, sort_keys=True))
            else:
                print(outline_markdown(document), end="")
            return 0
        document = search_model(
            repository,
            arguments.query,
            arguments.match_tag,
            arguments.kind,
            arguments.offset,
            arguments.limit,
            arguments.include_sensitive,
        )
        if arguments.format == "json":
            print(json.dumps(document, indent=2, sort_keys=True))
        else:
            print(search_markdown(document), end="")
        return 0
    except WorkflowError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

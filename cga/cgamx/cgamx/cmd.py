"""cgamx cmd: a localhost server that runs cga* commands as CGAST filters.

The composite page (cga/web) is a *view*: its inputs are scratch space until
the user applies them. Applying a change is defined to be *exactly* the same as
a user or LLM typing a new cga* command in the shell. This server is the bridge
that makes that literally true.

It accepts one command line over HTTP (POST /run), runs the named cga* program
with the shared session CGAST on stdin, and -- on success -- atomically replaces
the session with the program's stdout. In an initialized workflow it routes the
same component through the top-level ``cga`` dispatcher instead, so the command
advances the current immutable chain and updates the compatibility session.

Safety: only programs whose base name looks like a cga* binary *and* resolve on
PATH may run. The server binds to localhost only, matching the other cga*
servers. It is intentionally dependency-free (standard library only).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cgast

COMPONENT = "cgamx"

# Only base names matching this and resolvable on PATH may be executed.
_ALLOWED_NAME = re.compile(r"cga[a-z0-9-]*\Z")

# One command at a time: the atomic session swap must not interleave.
_RUN_LOCK = threading.Lock()
_WORKFLOW_TOKENS = {
    "cgadl": "dl",
    "cgaql": "ql",
    "cgamr": "mr",
    "cgasi": "si",
    "cgaex": "ex",
    "cgamx": "mx",
}


def _session_path() -> Path:
    """The shared session CGAST path, exactly as the serve viewers resolve it."""
    env = os.environ.get("CGA_SESSION")
    if env:
        return Path(env).expanduser()
    return cgast.cga_root() / "cga-tmp" / "session.json"


def _is_allowed(prog: str) -> bool:
    """True if ``prog`` is a cga* binary resolvable on PATH."""
    base = os.path.basename(prog)
    if not _ALLOWED_NAME.match(base):
        return False
    return shutil.which(prog) is not None


def _workflow_argv(argv: List[str]) -> List[str] | None:
    """Return the top-level cga command for an initialized workflow."""
    root_value = os.environ.get("CGA_WORKFLOW_ROOT")
    if not root_value:
        return None
    root = Path(root_value).expanduser().resolve()
    if not (root / ".cga" / "config").is_file():
        return None
    token = _WORKFLOW_TOKENS.get(Path(argv[0]).name)
    if token is None:
        return None
    dispatcher = cgast.cga_root() / "cga"
    if not dispatcher.is_file():
        return None
    return [str(dispatcher), "-C", str(root), token, *argv[1:]]


def run_argv(argv: List[str]) -> Tuple[bool, int, str]:
    """Run one cga* command as a CGAST filter over the shared session.

    Mirrors ``cga_step`` in sample-05-i/_common.sh: the session is fed on stdin,
    stdout is captured to a temp file, and the session is replaced only when the
    command succeeds. Returns ``(ok, exit_code, human_output)`` where
    ``human_output`` is the command's stderr (its human/progress channel).
    """
    if not argv:
        return False, 2, "cgamx cmd: empty command"
    prog = argv[0]
    if not _is_allowed(prog):
        return (False, 2,
                f"cgamx cmd: refusing to run {prog!r}; only cga* binaries on "
                "PATH may be executed")

    workflow_argv = _workflow_argv(argv)
    if workflow_argv is not None:
        with _RUN_LOCK:
            environment = os.environ.copy()
            environment["CGA_SOURCE_STEP"] = "dashboard"
            try:
                proc = subprocess.run(
                    workflow_argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                )
            except OSError as exc:
                return False, 1, f"cgamx cmd: {exc}"
        output = proc.stderr.decode("utf-8", "replace")
        if proc.stdout:
            output += proc.stdout.decode("utf-8", "replace")
        return proc.returncode == 0, proc.returncode, output

    session = _session_path()
    with _RUN_LOCK:
        session.parent.mkdir(parents=True, exist_ok=True)
        if not session.exists() or session.stat().st_size == 0:
            session.write_text("{}\n", encoding="utf-8")

        fd, tmp_name = tempfile.mkstemp(dir=str(session.parent),
                                        prefix=session.name + ".next.")
        tmp = Path(tmp_name)
        try:
            with open(session, "rb") as stdin, os.fdopen(fd, "wb") as stdout:
                proc = subprocess.run(argv, stdin=stdin, stdout=stdout,
                                      stderr=subprocess.PIPE)
            human = proc.stderr.decode("utf-8", "replace")
            if proc.returncode == 0:
                os.replace(tmp, session)
                return True, 0, human
            tmp.unlink(missing_ok=True)
            return False, proc.returncode, human
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            return False, 1, f"cgamx cmd: {exc}"


def _parse_body(raw: bytes) -> List[str]:
    """Turn a request body into an argv list.

    Accepts JSON ``{"argv": [...]}`` (preferred; no quoting ambiguity) or
    ``{"command": "..."}`` (shlex-split, never a shell). A bare non-JSON body is
    treated as a command line and shlex-split.
    """
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return shlex.split(text)
    if isinstance(obj, dict):
        if isinstance(obj.get("argv"), list):
            return [str(a) for a in obj["argv"]]
        if isinstance(obj.get("command"), str):
            return shlex.split(obj["command"])
    if isinstance(obj, list):
        return [str(a) for a in obj]
    if isinstance(obj, str):
        return shlex.split(obj)
    return []


def serve(port: int) -> None:
    """Start the localhost command server on ``port`` (never returns)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = f"cga-{COMPONENT}-cmd"

        def log_message(self, *_args):  # keep the skeleton quiet
            pass

        def _send(self, code: int, body: str, ctype: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_OPTIONS(self):  # noqa: N802 (CORS preflight)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):  # noqa: N802 (stdlib naming)
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path == "/healthz":
                self._send(200, "ok", "text/plain; charset=utf-8")
                return
            if path == "/":
                index = {"component": COMPONENT, "server": "cmd",
                         "routes": ["/healthz", "/run"]}
                self._send(200, json.dumps(index), "application/json")
                return
            self._send(404, json.dumps({"error": f"no route {path}"}),
                       "application/json")

        def do_POST(self):  # noqa: N802 (stdlib naming)
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path != "/run":
                self._send(404, json.dumps({"error": f"no route {path}"}),
                           "application/json")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                argv = _parse_body(raw)
            except ValueError as exc:
                self._send(400, json.dumps({"ok": False, "error": str(exc)}),
                           "application/json")
                return
            ok, code, human = run_argv(argv)
            result = {"ok": ok, "exit_code": code, "argv": argv, "output": human}
            self._send(200 if ok else 400, json.dumps(result),
                       "application/json")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{COMPONENT}: cmd server on http://127.0.0.1:{port} "
          "(POST /run runs cga* commands as CGAST filters)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

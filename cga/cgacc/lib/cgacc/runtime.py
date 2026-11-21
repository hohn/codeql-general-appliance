"""Password-authenticated, loopback-only browser editors owned by their launcher."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import signal
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

VERSION = "4.141.0"
DIGESTS = {
    "x86_64": ("amd64", "65bcd20b524d03eb1b5adb7f360244599ef0e5b74089a46a982d32c074b97a29"),
    "aarch64": ("arm64", "e5cc78da1d631c6cf6162f9b18eeaa8ee9d3239e1a88bb99d0602cdc5fa1852d"),
}


class EditorError(RuntimeError):
    pass


def validate_port(port: int) -> int:
    if type(port) is not int or not 0 <= port <= 65535:
        raise EditorError("editor port must be 0 (automatic) or 1..65535")
    return port


def distribution() -> tuple[str, str, Path]:
    if platform.system() != "Linux" or platform.machine() not in DIGESTS:
        raise EditorError("bundled installation supports Linux amd64/arm64; "
                          "install code-server separately and set CGACC_CODE_SERVER")
    arch, digest = DIGESTS[platform.machine()]
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return arch, digest, cache / "cga" / f"code-server-{VERSION}-linux-{arch}"


def executable() -> str:
    override = os.environ.get("CGACC_CODE_SERVER")
    if override:
        found = shutil.which(override)
        if not found:
            raise EditorError(f"CGACC_CODE_SERVER is not executable: {override}")
        return found
    found = shutil.which("code-server")
    if found:
        return found
    _, _, directory = distribution()
    binary = directory / "bin" / "code-server"
    if binary.is_file() and os.access(binary, os.X_OK):
        return str(binary)
    raise EditorError("code-server is missing; run 'cga cc install' "
                      "or set CGACC_CODE_SERVER to an installed executable")


def install() -> str:
    arch, digest, target = distribution()
    binary = target / "bin" / "code-server"
    if binary.is_file():
        return str(binary)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cgacc-", dir=target.parent) as scratch:
        archive = Path(scratch) / "release.tar.gz"
        url = (f"https://github.com/coder/code-server/releases/download/v{VERSION}/"
               f"code-server-{VERSION}-linux-{arch}.tar.gz")
        with urlopen(url, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with archive.open("rb") as downloaded:
            actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if actual != digest:
            raise EditorError("code-server release checksum mismatch")
        with tarfile.open(archive) as source:
            source.extractall(scratch, filter="data")
        extracted = Path(scratch) / target.name
        if not (extracted / "bin" / "code-server").is_file():
            raise EditorError("code-server release has no executable")
        extracted.rename(target)
    return str(binary)


class Editor:
    def __init__(self, binary: str, directory: Path, project: Path,
                 runtime: Path, password: str, port: int = 0):
        validate_port(port)
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise EditorError(f"cannot bind editor port {port}: {exc}") from exc
            port = listener.getsockname()[1]
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        runtime.chmod(0o700)
        config = runtime / "config.yaml"
        config.write_text("{}\n")
        self.url = f"http://127.0.0.1:{port}"
        self.project = project
        self.directory = directory
        self.password = password
        self.closed = False
        self.log = runtime / "code-server.log"
        environment = os.environ.copy()
        environment.pop("HASHED_PASSWORD", None)
        environment["PASSWORD"] = password
        with self.log.open("ab") as output:
            self.process = subprocess.Popen(
                [binary, "--config", str(config), "--bind-addr", f"127.0.0.1:{port}",
                 "--auth", "password", "--disable-telemetry", "--disable-update-check",
                 "--user-data-dir", str(runtime / "data"),
                 "--extensions-dir", str(runtime / "extensions"), str(project)],
                cwd=directory, env=environment, stdout=output, stderr=output,
                start_new_session=True)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise EditorError(f"code-server exited ({self.process.returncode}); "
                                      f"see {self.log}")
                try:
                    with urlopen(self.url + "/healthz", timeout=1) as response:
                        healthy = json.load(response).get("status") in ("alive", "expired")
                    if healthy and self.process.poll() is None:
                        break
                except (URLError, TimeoutError):
                    pass
                time.sleep(0.1)
            else:
                raise EditorError(f"code-server did not become ready; see {self.log}")
        except BaseException:
            self.close()
            raise

    def descriptor(self) -> dict:
        destination = "/?" + urlencode({"workspace": str(self.project)})
        return {"url": self.url + destination,
                "login": self.url + "/login?" + urlencode({"to": destination}),
                "password": self.password, "directory": str(self.directory),
                "project": str(self.project), "pid": self.process.pid}

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # The launcher can exit before its extension hosts.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()


class Editors:
    def __init__(self):
        self.values: dict[str, Editor] = {}
        self.lock = threading.Lock()
        self.password = secrets.token_urlsafe(32)
        self.closed = False

    def open(self, key: str, directory: Path, project: Path, runtime: Path,
             port: int = 0) -> dict:
        validate_port(port)
        with self.lock:
            if self.closed:
                raise EditorError("editor launcher is stopping")
            value = self.values.get(key)
            if value is None or value.process.poll() is not None:
                if value is not None:
                    value.close()
                value = Editor(executable(), directory, project, runtime, self.password, port)
                self.values[key] = value
            return value.descriptor()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            for value in self.values.values():
                value.close()
            self.values.clear()

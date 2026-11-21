"""Shared plumbing for CGA preparation's isolated, localhost service filters (Linux)."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

import cgast

_children = {}  # Retain/reap processes when start and stop share a caller.


def command(argv):
    subprocess.run([str(a) for a in argv], stdin=subprocess.DEVNULL,
                   stdout=sys.stderr, stderr=sys.stderr, check=True)


def free_port(port):
    if not 1 <= int(port) <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", int(port)))


def identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return [Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                fields[19]]
    except (FileNotFoundError, ProcessLookupError):
        return None


def owned(rt):
    pid = rt.get("pid")
    return bool(pid and rt.get("identity") and identity(pid) == rt["identity"])


def require(state, key):
    rt = state.get(key)
    if not isinstance(rt, dict):
        raise ValueError(f"Missing {key} state; initialize/start this service first")
    return rt


def stop(rt):
    """Never reclaim a port or signal a reused/unrecorded PID."""
    if owned(rt):
        pid = rt["pid"]
        if os.getpgid(pid) != pid:
            raise ValueError("Recorded service no longer owns its process group")
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                break
            # Reap when this process also launched the service (failed start).
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            time.sleep(0.1)
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    child = _children.pop(rt.get("pid"), None)
    if child is not None:
        child.wait(timeout=5)
    rt["status"] = "stopped"


def start(state, key, argv, port, log, extra=None, env=None):
    if key in state and owned(require(state, key)):
        raise ValueError(f"{key} is already running")
    free_port(port)
    log = Path(log).resolve()
    if log.exists():
        raise ValueError(f"Refusing to overwrite existing service log: {log}")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("xb") as output:
        proc = subprocess.Popen([str(a) for a in argv], stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT,
                                start_new_session=True, env=env)
    rt = {"pid": proc.pid, "identity": identity(proc.pid), "port": int(port),
          "log": str(log), "status": "starting", **(extra or {})}
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"{key} exited; see {log}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1):
                    pass
                rt["status"] = "running"
                _children[proc.pid] = proc
                state[key] = rt
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"{key} did not become ready; see {log}")
    except BaseException:
        stop(rt)
        proc.wait(timeout=5)
        raise


def check(rt):
    if not owned(rt):
        raise ValueError("Service is not running with its recorded identity")
    with urllib.request.urlopen(f"http://127.0.0.1:{rt['port']}/", timeout=2):
        pass


def dispatch(parser, argv, execute):
    args = parser.parse_args(argv)
    state = cgast.read()
    try:
        execute(state, args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        cgast.info(f"{parser.prog}: {exc}")
        return 1
    cgast.write(state)
    return 0

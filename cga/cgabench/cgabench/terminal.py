"""Persistent, bounded PTYs for the loopback preparation/query UI."""

from __future__ import annotations

import base64
import errno
import fcntl
import os
from pathlib import Path
import pty
import pwd
import secrets
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

import cgast
from workflow import WorkflowError

BUFFER_LIMIT = 1024 * 1024
READ_LIMIT = 65536
# Establish the controlling tty after exec, without a threaded preexec_fn.
BOOTSTRAP = (
    "import fcntl, os, sys, termios\n"
    "fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n"
    "os.execvpe(sys.argv[1], sys.argv[1:], os.environ)\n"
)


def dimensions(columns: int, rows: int) -> bytes:
    if (not isinstance(columns, int) or isinstance(columns, bool)
            or not isinstance(rows, int) or isinstance(rows, bool)
            or not 2 <= columns <= 500 or not 2 <= rows <= 200):
        raise WorkflowError("terminal size must be 2..500 columns and 2..200 rows")
    return struct.pack("HHHH", rows, columns, 0, 0)


class Terminal:
    def __init__(self, context: dict, columns: int, rows: int,
                 argv: list[str] | None = None, environment: dict[str, str] | None = None):
        size = dimensions(columns, rows)
        command = argv if argv is not None else [
            os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell, "-i"]
        executable = shutil.which(command[0])
        if not executable:
            raise WorkflowError(f"terminal executable not found: {command[0]}")
        self.context = context
        self.shell = executable
        self.id = secrets.token_urlsafe(32)
        self.condition = threading.Condition()
        self.input_lock = threading.Lock()
        self.close_lock = threading.Lock()
        self.buffer = bytearray()
        self.base = 0
        self.ended = False
        self.closing = False
        self.error = None
        directory = Path(context["directory"])
        directory.mkdir(parents=True, exist_ok=True)
        child_environment = os.environ.copy()
        for key in ("CGA_DIR", "CGA_WORKFLOW_ACTIVE", "CGA_SOURCE_STEP",
                    "CGAST_ROOT", "CGAST_TMPDIR"):
            child_environment.pop(key, None)
        child_environment.update({
            "TERM": "xterm-256color",
            "CGA_BENCH_URL": context["url"],
            "CGA_BENCH_SESSION": str(context["session"]),
            "CGA_BENCH_WORKFLOW": context["workflow"],
            "CGA_BENCH_CATALOGUE": context["catalogue"],
            "CGA_BENCH_CELL": context.get("stage", "D"),
            "CGA_BENCH_RESULTS_DB": context.get("database", ""),
        })
        child_environment.update(environment or {})
        self.master, slave = pty.openpty()
        try:
            os.set_blocking(self.master, False)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, size)
            self.process = subprocess.Popen(
                [sys.executable, "-c", BOOTSTRAP, executable, *command[1:]],
                stdin=slave, stdout=slave, stderr=slave, cwd=directory,
                env=child_environment, start_new_session=True)
        except OSError:
            os.close(self.master)
            raise
        finally:
            os.close(slave)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def descriptor(self) -> dict:
        return {**self.context, "id": self.id, "shell": self.shell,
                "running": not self.ended and self.process.poll() is None,
                "exit_code": self.process.poll()}

    def _read(self) -> None:
        try:
            while not self.closing:
                ready, _, _ = select.select([self.master], [], [], .5)
                if self.closing:
                    break
                if not ready:
                    continue
                try:
                    chunk = os.read(self.master, READ_LIMIT)
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                with self.condition:
                    self.buffer.extend(chunk)
                    extra = len(self.buffer) - BUFFER_LIMIT
                    if extra > 0:
                        del self.buffer[:extra]
                        self.base += extra
                    self.condition.notify_all()
        except OSError as exc:
            if exc.errno != errno.EIO and not self.closing:
                self.error = f"terminal output failed: {exc}"
                cgast.info(self.error)
        finally:
            with self.condition:
                self.ended = True
                self.condition.notify_all()

    def output(self, cursor: int) -> dict:
        if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
            raise WorkflowError("terminal cursor must be a nonnegative integer")
        with self.condition:
            if cursor > self.base + len(self.buffer):
                raise WorkflowError("terminal cursor is beyond available output")
            if cursor == self.base + len(self.buffer) and not self.ended:
                self.condition.wait(timeout=2)
            reset = cursor < self.base
            cursor = max(cursor, self.base)
            chunk = bytes(self.buffer[cursor - self.base:cursor - self.base + READ_LIMIT])
            return {"data": base64.b64encode(chunk).decode("ascii"),
                    "cursor": cursor + len(chunk), "reset": reset,
                    "more": cursor + len(chunk) < self.base + len(self.buffer),
                    "running": not self.ended and self.process.poll() is None,
                    "exit_code": self.process.poll(), "error": self.error}

    def write(self, text: str) -> None:
        if not isinstance(text, str) or not text or len(text.encode("utf-8")) > 32768:
            raise WorkflowError("terminal input must contain 1..32768 UTF-8 bytes")
        if self.ended or self.closing or self.process.poll() is not None:
            raise WorkflowError("terminal has exited; start a new shell")
        with self.input_lock:
            data = text.encode("utf-8")
            deadline = time.monotonic() + 5
            while data:
                if self.closing:
                    raise WorkflowError("terminal is stopping")
                try:
                    written = os.write(self.master, data)
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise WorkflowError("terminal input is blocked; interrupt or stop the foreground job")
                    select.select([], [self.master], [], .2)
                    continue
                data = data[written:]

    def resize(self, columns: int, rows: int) -> None:
        size = dimensions(columns, rows)
        if self.ended or self.closing:
            raise WorkflowError("terminal has exited")
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, size)

    def close(self) -> None:
        with self.close_lock:
            self._close()

    def _close(self) -> None:
        if self.closing:
            return
        self.closing = True
        groups = {self.process.pid}
        if self.process.poll() is None:
            try:
                groups.add(os.tcgetpgrp(self.master))
            except OSError as exc:
                if exc.errno not in (errno.EIO, errno.ENOTTY):
                    raise
            self._signal(groups, signal.SIGHUP)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._signal(groups, signal.SIGKILL)
                self.process.wait(timeout=2)
            self._signal(groups - {self.process.pid}, signal.SIGKILL)
        with self.input_lock:
            os.close(self.master)
        with self.condition:
            self.ended = True
            self.condition.notify_all()
        self.reader.join(timeout=2)

    @staticmethod
    def _signal(groups: set[int], value: int) -> None:
        for group in groups:
            if group > 0 and group != os.getpgrp():
                try:
                    os.killpg(group, value)
                except ProcessLookupError:
                    pass


class Terminals:
    def __init__(self):
        self.lock = threading.Lock()
        self.items: dict[str, Terminal] = {}

    def contains(self, submission: str) -> bool:
        with self.lock:
            return submission in self.items

    def open(self, submission: str, context: dict, columns: int, rows: int,
             restart: bool = False) -> dict:
        dimensions(columns, rows)
        with self.lock:
            previous = self.items.get(submission)
            if previous and not restart:
                if previous.descriptor()["running"]:
                    previous.resize(columns, rows)
                return previous.descriptor()
            if previous:
                if previous.descriptor()["running"]:
                    raise WorkflowError("stop the terminal before starting a new shell")
                previous.close()
            value = Terminal(context, columns, rows)
            self.items[submission] = value
            return value.descriptor()

    def get(self, identifier: str) -> Terminal:
        if not isinstance(identifier, str):
            raise WorkflowError("terminal id is required")
        with self.lock:
            for value in self.items.values():
                if secrets.compare_digest(value.id, identifier):
                    return value
        raise WorkflowError("terminal is no longer available; reconnect to its D or R cell")

    def close(self) -> None:
        with self.lock:
            errors = []
            for value in self.items.values():
                try:
                    value.close()
                except (OSError, WorkflowError, subprocess.TimeoutExpired) as exc:
                    message = f"cannot stop terminal for row {value.context['session']}: {exc}"
                    cgast.info(message)
                    errors.append(message)
            if errors:
                raise WorkflowError("; ".join(errors))

"""One warm, viewer-owned Copilot PTY, independent of browser connections."""

from __future__ import annotations

import secrets
import threading

import cgast
from workflow import WorkflowError

from .terminal import Terminal, dimensions


class Assistant:
    def __init__(self, context: dict, prompt: str, environment: dict[str, str]):
        self.context = context
        self.argv = ["copilot", "-C", context["directory"], "--interactive", prompt]
        self.environment = environment
        self.lock = threading.Lock()
        self.value: Terminal | None = None
        self.error: str | None = None
        self.closed = False

    def descriptor(self) -> dict:
        if self.value:
            return {**self.value.descriptor(), "error": self.error}
        return {**self.context, "id": None, "running": False,
                "exit_code": None, "error": self.error}

    def start(self, columns: int = 100, rows: int = 24) -> dict:
        dimensions(columns, rows)
        with self.lock:
            if self.closed:
                raise WorkflowError("bench assistant is shutting down")
            if self.value:
                if self.value.descriptor()["running"]:
                    raise WorkflowError("stop the assistant before starting a new session")
                self.value.close()
                self.value = None
            try:
                self.value = Terminal(self.context, columns, rows,
                                      argv=self.argv, environment=self.environment)
            except (WorkflowError, OSError) as exc:
                self.error = f"cannot start Bench assistant: {exc}"
                cgast.info(self.error)
                raise
            self.error = None
            return self.descriptor()

    def action(self, document: dict) -> dict:
        operation = document.get("operation")
        if operation == "start":
            return self.start(document.get("columns", 100), document.get("rows", 24))
        with self.lock:
            if operation == "open":
                return self.descriptor()
            identifier = document.get("id")
            value = self.value
            if (not value or not isinstance(identifier, str)
                    or not secrets.compare_digest(value.id, identifier)):
                raise WorkflowError("assistant session changed; reconnect to the current assistant")
            if operation == "stop":
                value.close()
                return self.descriptor()
        # A long-poll must not block input, resizing, or shutdown.
        if operation == "read":
            return value.output(document.get("cursor", 0))
        if operation == "write":
            value.write(document.get("data"))
        elif operation == "resize":
            value.resize(document.get("columns"), document.get("rows"))
        else:
            raise WorkflowError("unknown assistant operation")
        return value.descriptor()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.value:
                self.value.close()

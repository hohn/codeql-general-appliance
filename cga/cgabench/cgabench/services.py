"""Bench-owned infrastructure configuration and named lifecycle actions."""

from __future__ import annotations

import os
from pathlib import Path
import urllib.request

import cgast
from workflow import WorkflowError

from . import engine, model

ACTIONS = {
    "preflight": "Check infrastructure", "reset": "Reset MRVA state",
    "build": "Build MRVA services", "start": "Start MRVA services",
    "check": "Verify MRVA logs", "stop": "Stop MRVA services",
    "cleanup": "Clean MRVA runtime",
}


def configure(root: Path) -> None:
    defaults = {
        "CGA_WORKFLOW_ROOT": str(root),
        "CGA_ROOT": str(engine.COLLECTION),
        "CGA_TMPDIR": str(root / ".cga" / "tmp"),
        "RUN_TAG": "cga-bench",
        "MRVA_WORK_DIR": str(root / ".cga" / "runtime" / "mrva"),
        "MRVA_TMP_DIR": str(root / ".cga" / "runtime" / "services"),
        "MRVA_STANDALONE_STORAGE": "filesystem",
        "CODEQL_JAVA_HOME": "/usr",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    os.environ.setdefault("CGA_MRVA_SERVER",
                          f"http://127.0.0.1:{os.environ.get('PORT', '8081')}")


def ready(state: dict) -> bool:
    runtime = state.get("cgamx", {})
    pid = runtime.get("server_pid")
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
        base = os.environ.get("CGA_MRVA_SERVER", "http://127.0.0.1:8081")
        with urllib.request.urlopen(base.rstrip("/") + "/sysview/data", timeout=2):
            pass
        archive_base = os.environ.get("MRVA_DB_SERVER_URL",
                                      f"http://127.0.0.1:{os.environ.get('DB_SERVER_PORT', '9080')}")
        if archive_base:
            with urllib.request.urlopen(archive_base.rstrip("/") + "/", timeout=2):
                pass
        if runtime.get("storage") == "minio":
            endpoint = os.environ.get("MRVA_MINIO_ENDPOINT", "localhost:9000")
            with urllib.request.urlopen(f"http://{endpoint}/minio/health/live", timeout=2):
                pass
        return True
    except OSError:
        return False


def run(state: dict, action: str) -> None:
    if action != "setup" and action not in ACTIONS:
        raise WorkflowError("unknown infrastructure action")
    root = os.environ.get("CGA_WORKFLOW_ROOT")
    if root:
        configure(Path(root))
    if action == "setup":
        if ready(state):
            return
        has_submissions = any(item["engine"].get("cgamr-submissions")
                              for item in model.projection(state)["sessions"])
        if has_submissions and not state.get("cgamx", {}).get("work_dir"):
            raise WorkflowError("this experiment has external submissions; "
                                "configure its original services before continuing")
        actions = ("preflight", "build", "start") \
            if state.get("cgamx", {}).get("work_dir") \
            else ("preflight", "reset", "build", "start")
    else:
        actions = (action,)
    for phase in actions:
        updated = engine.run_tool(state, "mx", [phase])
        state.clear()
        state.update(updated)
        cgast.info(f"cgabench: {ACTIONS[phase]} complete")

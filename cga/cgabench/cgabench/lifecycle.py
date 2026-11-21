"""Workflow-local ownership and graceful shutdown of the foreground viewer."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import signal
import time

import cgast
from cgawf.repository import Repository, WorkflowError as RepositoryError
from service import identity
from workflow import WorkflowError, load_json

from . import model


def runtime_directory(repository: Repository | None, session_file: Path) -> Path:
    if repository:
        return repository.cga_dir / "runtime" / "cgabench"
    return session_file.parent / ".cgabench-runtime" / session_file.name


def available(lock) -> bool:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


@contextmanager
def running(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    record = directory / "serve.json"
    with (directory / "serve.lock").open("a+") as lock:
        if not available(lock):
            raise WorkflowError("bench viewer is already running; use 'cga bench stop' first")
        try:
            model.save(record, {"pid": os.getpid(), "identity": identity(os.getpid())})
            yield
        finally:
            record.unlink(missing_ok=True)


def stop(session_file: str | None, timeout: float = 30) -> None:
    if session_file:
        directory = runtime_directory(None, Path(session_file).expanduser().resolve())
    else:
        try:
            repository = Repository.discover()
        except RepositoryError as exc:
            raise WorkflowError("stop requires a .cga workflow or --session-file FILE") from exc
        directory = runtime_directory(repository, repository.current_path)
    if not directory.exists():
        cgast.info("cgabench: viewer is not running")
        return
    record = directory / "serve.json"
    deadline = time.monotonic() + timeout
    signalled = False
    with (directory / "serve.lock").open("a+") as lock:
        while not available(lock):
            if not signalled and record.is_file():
                owner = load_json(record)
                pid = owner.get("pid")
                if type(pid) is not int or pid <= 0 or pid == os.getpid() \
                        or not owner.get("identity"):
                    raise WorkflowError(f"invalid viewer ownership record: {record}")
                try:
                    descriptor = os.pidfd_open(pid)
                except ProcessLookupError:
                    signalled = True
                else:
                    try:
                        if identity(pid) != owner["identity"]:
                            raise WorkflowError("viewer PID identity changed; refusing to signal it")
                        try:
                            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        signalled = True
                    finally:
                        os.close(descriptor)
            if time.monotonic() >= deadline:
                raise WorkflowError(
                    f"bench viewer did not stop within {timeout:g}s; shutdown is still pending")
            time.sleep(0.05)
        record.unlink(missing_ok=True)
    cgast.info("cgabench: viewer stopped" if signalled else "cgabench: viewer is not running")

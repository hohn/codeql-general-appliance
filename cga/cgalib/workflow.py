"""Small stdlib-only helpers shared by complete-analysis CGA components."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class WorkflowError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def require_safe_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value):
        raise WorkflowError(f"{label} must be a safe non-empty name")
    return value


def argv(value: Any, label: str) -> list[str]:
    if (not isinstance(value, list) or not value or
            any(not isinstance(part, str) or not part for part in value)):
        raise WorkflowError(f"{label} must be a non-empty argv string array")
    return list(value)


def command_list(value: Any, label: str) -> list[list[str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WorkflowError(f"{label} must be an array of argv arrays")
    return [argv(item, f"{label}[{i}]") for i, item in enumerate(value)]


def under(root: Path, *parts: str) -> Path:
    root = Path(root).expanduser().resolve()
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkflowError(f"destination escapes output directory: {candidate}") from exc
    return candidate


def run(argv_value: Iterable[str], *, cwd: Path | None = None) -> None:
    args = list(argv_value)
    try:
        subprocess.run(args, cwd=str(cwd) if cwd else None, check=True,
                       stdout=sys.stderr, stderr=sys.stderr)
    except FileNotFoundError as exc:
        raise WorkflowError(f"command not found: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise WorkflowError(
            f"command failed with exit {exc.returncode}: {args!r}") from exc

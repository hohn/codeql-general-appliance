"""JSON recipe supervision for source acquisition and database builds."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess

import cgast
from workflow import WorkflowError, command_list, write_json


def context(root: Path) -> dict:
    files = []
    documents = {}
    if root.is_dir():
        for path in sorted(root.iterdir()):
            files.append(path.name + ("/" if path.is_dir() else ""))
            if (path.is_file() and not path.is_symlink()
                    and (path.name.lower().startswith(("readme", "install"))
                         or path.name in ("build", "build.sh", "Makefile",
                                          "CMakeLists.txt", "configure.ac"))):
                documents[path.name] = path.read_text(
                    encoding="utf-8", errors="replace")[:20000]
    return {"files": files[:200], "documents": documents}


def recipe(parameters: dict, directory: Path, source: Path,
           previous: list[dict]) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    request = {
        "schema": "cga.preparation-supervision.v1",
        "parameters": parameters,
        "source_dir": str(source),
        "source_context": context(source),
        "previous_attempts": previous,
    }
    write_json(directory / "request.json", request)
    prompt = (
        "Supervise the requested CGA source acquisition or CodeQL database build. "
        "Return ONLY a JSON object with commands (an array of argv arrays), "
        "build_command (a string or null), and notes (a string). "
        "The CGA executor will run your commands in the supplied working directory, "
        "capture their output, perform acquisition/build verification, and return "
        "failures to you for repair. You do not need to use tools yourself. "
        "For fetch, commands prepare acquisition prerequisites; CGA itself will "
        "materialize exactly the requested source into source_dir using the supplied "
        "acquisition plan. Do not clone or extract sources yourself or substitute versions. "
        "For build, inspect the supplied human documentation and build scripts, "
        "prepare dependencies or repair the disposable source using commands, "
        "and supply a build_command for trace mode. Compilation itself will run "
        "under CodeQL, not in preparation commands. Respect the requested mode. "
        "Each command is a separate subprocess: shell exports do not persist. "
        "CodeQL build_command is not a shell program; for exports, pipelines, "
        "or complex quoting, write a wrapper script and return its invocation. "
        "Do not run CodeQL, publish archives, modify pristine inputs, or change "
        "permission/trust/sandbox controls. An unavailable dependency must be "
        "reported, not hidden. Commands run under the caller's normal permissions. "
        "Use previous_attempts to fix failures. Paths in parameters are absolute.\n\n"
        + json.dumps(request, ensure_ascii=True)
    )
    configured = os.environ.get(
        "CGA_PREP_LLM_COMMAND",
        "copilot --silent --available-tools= --prompt")
    try:
        arguments = shlex.split(configured)
    except ValueError as exc:
        raise WorkflowError(f"invalid CGA_PREP_LLM_COMMAND: {exc}") from exc
    if not arguments:
        raise WorkflowError("CGA_PREP_LLM_COMMAND must name an LLM runner")
    cgast.info(f"LLM supervisor: {parameters['operation']} -> {directory}")
    try:
        completed = subprocess.run(
            [*arguments, prompt], cwd=directory, stdin=subprocess.DEVNULL,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise WorkflowError(f"cannot start LLM supervisor: {exc}") from exc
    (directory / "llm.stdout").write_text(completed.stdout, encoding="utf-8")
    (directory / "llm.stderr").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise WorkflowError(
            f"LLM supervisor failed (exit {completed.returncode}); see {directory}")
    try:
        result = json.loads(completed.stdout)
    except ValueError as exc:
        raise WorkflowError(
            f"LLM supervisor returned invalid JSON; see {directory / 'llm.stdout'}") from exc
    if not isinstance(result, dict):
        raise WorkflowError("LLM supervisor must return a JSON object")
    result["commands"] = command_list(result.get("commands"), "LLM commands")
    command = result.get("build_command")
    if command is not None and (not isinstance(command, str) or not command.strip()):
        raise WorkflowError("LLM build_command must be a nonempty string or null")
    if not isinstance(result.get("notes"), str):
        raise WorkflowError("LLM notes must be a string")
    write_json(directory / "recipe.json", result)
    return result


def run(arguments: list[str], cwd: Path, log: Path) -> None:
    cgast.info("  RUN " + shlex.join(arguments))
    with log.open("a", encoding="utf-8") as output:
        output.write("$ " + shlex.join(arguments) + "\n")
        output.flush()
        try:
            completed = subprocess.run(
                arguments, cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT)
        except OSError as exc:
            raise WorkflowError(f"cannot run {arguments[0]}: {exc}") from exc
    if completed.returncode:
        raise WorkflowError(
            f"command failed (exit {completed.returncode}): "
            f"{shlex.join(arguments)}; see {log}")


def failure(directory: Path, error: Exception) -> dict:
    log = directory / "commands.log"
    result = {
        "directory": str(directory), "status": "failed", "error": str(error),
        "output": log.read_text(encoding="utf-8", errors="replace")[-20000:]
        if log.is_file() else "",
    }
    write_json(directory / "outcome.json", result)
    return result


def attempts(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise ValueError("LLM attempts must be a positive integer") from exc
    if count < 1:
        raise ValueError("LLM attempts must be a positive integer")
    return count

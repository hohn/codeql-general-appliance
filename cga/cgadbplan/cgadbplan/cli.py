"""Expand prepared sources into immutable one-database job specifications."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cgast
import workflow
from command_help import enhance_parser

SOURCES_KEY = "cgasp-sources"
JOBS_KEY = "cgadbplan-jobs"
HISTORY_KEY = "cgadbplan-history"


def _sources(state) -> list[dict]:
    document = workflow.load_json(cgast.require_path(
        state, SOURCES_KEY, "run 'cga src-prep fetch/adopt' first"))
    items = document.get("items")
    if not isinstance(items, list) or not items:
        raise workflow.WorkflowError("cgasp sources contains no items")
    return items


def expand(
        items: list[dict],
        modes: list[str],
        architecture: str | None,
        repository_suffix: str | None,
        use_llm: bool = False,
) -> list[dict]:
    if not modes:
        raise workflow.WorkflowError("at least one --mode is required")
    if len(modes) != len(set(modes)):
        raise workflow.WorkflowError("database modes must be unique")
    if architecture:
        workflow.require_safe_name(architecture, "architecture")
    if repository_suffix:
        workflow.require_safe_name(repository_suffix, "repository suffix")
    jobs = []
    for item in items:
        if not isinstance(item, dict):
            raise workflow.WorkflowError("prepared source items must be objects")
        item_id = workflow.require_safe_name(item.get("id"), "source item id")
        workflow.require_safe_name(item.get("owner"), "owner")
        workflow.require_safe_name(item.get("language"), "language")
        base_repo = workflow.require_safe_name(item.get("repo"), "repo")
        source_dir = item.get("source_dir")
        if not isinstance(source_dir, str) or not source_dir:
            raise workflow.WorkflowError(f"{item_id}: missing source_dir")
        for mode in modes:
            label = "none" if mode == "bm-none" else "trace"
            build_command = item.get("build_command")
            if mode == "trace" and not use_llm and (
                    not isinstance(build_command, str) or
                    not build_command.strip()):
                raise workflow.WorkflowError(
                    f"{item_id}: trace mode requires build_command")
            dependencies = workflow.command_list(
                item.get(
                    f"{label}_dependencies",
                    item.get("dependencies", item.get("dependency_argv", []))),
                f"{item_id}.{label}_dependencies")
            repo_parts = [base_repo, label]
            if repository_suffix:
                repo_parts.append(repository_suffix)
            job_id = f"{item_id}--{label}"
            if architecture:
                job_id += f"--{architecture}"
            source_hash = item.get("source_tree_sha256", "")
            build_cid = job_id + (
                f"--{source_hash[:16]}" if source_hash else "")
            jobs.append({
                **item,
                "schema": "cga.database-job.v1",
                "id": job_id,
                "source_id": item_id,
                "base_repo": base_repo,
                "repo": "-".join(repo_parts),
                "mode": mode,
                "extraction_mode": label,
                "architecture": architecture or item.get("architecture", ""),
                "dependency_argv": dependencies,
                "build_command": build_command if mode == "trace" else None,
                "build_cid": build_cid,
                "use_llm": use_llm,
            })
    return jobs


def cmd_plan(state, args) -> None:
    root = Path(args.output_dir).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise workflow.WorkflowError(f"job output directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    jobs = expand(
        _sources(state), args.mode, args.architecture,
        args.repository_suffix, args.use_llm)
    manifest_items = []
    for job in jobs:
        path = root / f"{job['id']}.json"
        workflow.write_json(path, job)
        manifest_items.append({
            "id": job["id"],
            "repository": f"{job['owner']}/{job['repo']}",
            "mode": job["mode"],
            "architecture": job["architecture"],
            "job": cgast.rel(path),
        })
        cgast.info(f"  JOB     {job['id']} -> {cgast.rel(path)}")
    manifest = root / "jobs.json"
    workflow.write_json(manifest, {
        "schema": "cga.database-jobs.v1",
        "count": len(jobs),
        "items": manifest_items,
    })
    cgast.set_path(state, JOBS_KEY, manifest)
    state.setdefault(HISTORY_KEY, []).append({
        "jobs": cgast.rel(manifest),
        "count": len(jobs),
    })
    cgast.info(f"cgadbplan: planned {len(jobs)} database job(s) -> "
               f"{cgast.rel(manifest)}")


def cmd_info(state, _args) -> None:
    path = cgast.get_path(state, JOBS_KEY)
    cgast.info(f"cgadbplan: jobs={cgast.rel(path) if path else '(none)'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cga db plan")
    parser.add_argument("--mode", action="append",
                        choices=("bm-none", "trace"), required=True)
    parser.add_argument("--architecture")
    parser.add_argument("--repository-suffix")
    parser.add_argument("--use-llm", action="store_true",
                        help="plan supervised builds; permits an undiscovered trace command")
    parser.add_argument("--output-dir", required=True)
    parser.set_defaults(func=cmd_plan)
    return enhance_parser(parser, "db plan")


def main(argv: list[str]) -> int:
    if argv and argv[0] == "info":
        parser = argparse.ArgumentParser(prog="cga db plan info")
        enhance_parser(parser, "db plan info")
        parser.parse_args(argv[1:])
        state = cgast.read()
        cmd_info(state, None)
        cgast.write(state)
        return 0
    args = build_parser().parse_args(argv)
    state = cgast.read()
    try:
        args.func(state, args)
    except workflow.WorkflowError as exc:
        cgast.die(f"cgadbplan: {exc}", 2)
    cgast.write(state)
    return 0

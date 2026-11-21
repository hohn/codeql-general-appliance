"""Import, validate, select, and expand external complete-analysis CVE specs."""

from __future__ import annotations

import argparse
import copy
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cgast
import workflow
from command_help import enhance_parser

COMPONENT = "cgacv"
DEFAULT_PORT = 8501
SPEC_KEY = "cgacv-spec"
SELECTION_KEY = "cgacv-selection"
WORK_KEY = "cgacv-work-items"
HISTORY_KEY = "cgacv-history"
REQUIRED_VARIANTS = {"vulnerable", "patched", "most-recent"}
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")
LANGUAGES = {"cpp", "c", "python", "javascript", "java", "go", "csharp",
             "ruby", "swift"}


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise workflow.WorkflowError(f"{label} must be a non-empty string")
    if "\x00" in value:
        raise workflow.WorkflowError(f"{label} contains a NUL byte")
    return value.strip()


def _url(value: Any, label: str) -> str:
    result = _text(value, label)
    parsed = urlparse(result)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise workflow.WorkflowError(f"{label} must be an http(s) URL")
    return result


def _source(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise workflow.WorkflowError(f"{label} must be an object")
    strategy = value.get("strategy")
    if strategy == "git":
        return {"strategy": "git", "url": _url(value.get("url"), f"{label}.url"),
                "ref": _text(value.get("ref"), f"{label}.ref")}
    if strategy == "debian-dsc":
        return {"strategy": "debian-dsc",
                "url": _url(value.get("url"), f"{label}.url")}
    raise workflow.WorkflowError(
        f"{label}.strategy must be 'git' or 'debian-dsc'")


def _query(value: Any, label: str, base: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise workflow.WorkflowError(f"{label} must be an object")
    filename = workflow.require_safe_name(
        value.get("filename", f"Query-{label.rsplit('[', 1)[-1][:-1]}.ql"),
        f"{label}.filename")
    if not filename.endswith(".ql"):
        raise workflow.WorkflowError(f"{label}.filename must end in .ql")
    out = {
        "id": _text(value.get("id"), f"{label}.id"),
        "name": _text(value.get("name"), f"{label}.name"),
        "filename": filename,
    }
    has_path = "path" in value
    has_source = "source" in value
    if has_path == has_source:
        raise workflow.WorkflowError(
            f"{label} must contain exactly one of path or source")
    if has_path:
        raw_path = Path(_text(value["path"], f"{label}.path")).expanduser()
        path = raw_path.resolve() if raw_path.is_absolute() else (
            base / raw_path).resolve()
        if not path.is_file() and not raw_path.is_absolute():
            path = cgast.resolve(str(raw_path))
        if not path.is_file():
            raise workflow.WorkflowError(f"{label}.path not found: {path}")
        out["path"] = cgast.rel(path)
    else:
        out["source"] = _text(value["source"], f"{label}.source")
    return out


def normalize_spec(doc: dict[str, Any], base: Path) -> dict[str, Any]:
    if doc.get("version", 1) != 1:
        raise workflow.WorkflowError("spec.version must be 1")
    raw_cves = doc.get("cves")
    if raw_cves is None and "id" in doc:
        raw_cves = [doc]
    if not isinstance(raw_cves, list) or not raw_cves:
        raise workflow.WorkflowError("spec.cves must be a non-empty array")
    normalized = []
    seen_ids = set()
    for i, raw in enumerate(raw_cves):
        label = f"cves[{i}]"
        if not isinstance(raw, dict):
            raise workflow.WorkflowError(f"{label} must be an object")
        cve_id = _text(raw.get("id"), f"{label}.id").upper()
        if not CVE_RE.fullmatch(cve_id):
            raise workflow.WorkflowError(f"{label}.id is not a CVE identifier")
        if cve_id in seen_ids:
            raise workflow.WorkflowError(f"duplicate CVE id: {cve_id}")
        seen_ids.add(cve_id)
        debian = raw.get("debian")
        if not isinstance(debian, dict):
            raise workflow.WorkflowError(f"{label}.debian must be an object")
        language = _text(raw.get("language"), f"{label}.language")
        if language not in LANGUAGES:
            raise workflow.WorkflowError(f"{label}.language is unsupported")
        variants = raw.get("variants")
        if not isinstance(variants, list):
            raise workflow.WorkflowError(f"{label}.variants must be an array")
        names = []
        normalized_variants = []
        for j, variant in enumerate(variants):
            vlabel = f"{label}.variants[{j}]"
            if not isinstance(variant, dict):
                raise workflow.WorkflowError(f"{vlabel} must be an object")
            name = workflow.require_safe_name(variant.get("name"),
                                              f"{vlabel}.name")
            names.append(name)
            normalized_variants.append({
                "name": name,
                "version": _text(variant.get("version"), f"{vlabel}.version"),
                "source": _source(variant.get("source"), f"{vlabel}.source"),
            })
        if len(names) != len(set(names)):
            raise workflow.WorkflowError(f"{label} has duplicate variant names")
        if set(names) != REQUIRED_VARIANTS or len(names) != 3:
            raise workflow.WorkflowError(
                f"{label} variants must be exactly: "
                f"{', '.join(sorted(REQUIRED_VARIANTS))}")
        build = raw.get("build")
        if not isinstance(build, dict):
            raise workflow.WorkflowError(f"{label}.build must be an object")
        dependencies = workflow.command_list(
            build.get("dependencies", []), f"{label}.build.dependencies")
        build_command = _text(build.get("command"), f"{label}.build.command")
        queries = raw.get("queries", [])
        if not isinstance(queries, list):
            raise workflow.WorkflowError(f"{label}.queries must be an array")
        normalized_queries = [_query(q, f"{label}.queries[{j}]", base)
                              for j, q in enumerate(queries)]
        query_ids = [query["id"] for query in normalized_queries]
        filenames = [query["filename"] for query in normalized_queries]
        if len(query_ids) != len(set(query_ids)):
            raise workflow.WorkflowError(f"{label} has duplicate query ids")
        if len(filenames) != len(set(filenames)):
            raise workflow.WorkflowError(
                f"{label} has duplicate query filenames")
        normalized.append({
            "id": cve_id,
            "url": _url(raw.get("url"), f"{label}.url"),
            "debian": {
                "source_package": workflow.require_safe_name(
                    debian.get("source_package"),
                    f"{label}.debian.source_package"),
                "tracker": _url(debian.get("tracker"),
                                f"{label}.debian.tracker"),
            },
            "language": language,
            "variants": normalized_variants,
            "build": {"dependencies": dependencies, "command": build_command},
            "queries": normalized_queries,
            **({"upstream_fix": _text(raw["upstream_fix"],
                                      f"{label}.upstream_fix")}
               if "upstream_fix" in raw else {}),
        })
    return {"version": 1, "cves": normalized}


def _read_normalized(path: Path) -> dict[str, Any]:
    doc = workflow.load_json(path)
    return normalize_spec(doc, path.parent)


def cmd_import(state, args) -> None:
    source = Path(args.spec).expanduser().resolve()
    normalized = _read_normalized(source)
    out = cgast.new_tempfile(prefix="cgacv-spec.", suffix=".json")
    workflow.write_json(out, normalized)
    cgast.set_path(state, SPEC_KEY, out)
    cgast.info(f"{COMPONENT}: imported {len(normalized['cves'])} CVE(s) -> "
               f"{cgast.rel(out)}")


def cmd_validate(state, args) -> None:
    if args.spec:
        normalized = _read_normalized(Path(args.spec).expanduser().resolve())
    else:
        path = cgast.require_path(state, SPEC_KEY, "run 'cgacv import SPEC'")
        normalized = _read_normalized(path)
    cgast.info(f"{COMPONENT}: valid ({len(normalized['cves'])} CVE(s))")


def cmd_select(state, args) -> None:
    spec = workflow.load_json(cgast.require_path(
        state, SPEC_KEY, "run 'cgacv import SPEC' first"))
    cves = spec.get("cves", [])
    wanted = args.cve.upper() if args.cve else None
    selected = [copy.deepcopy(cve) for cve in cves
                if wanted is None or cve.get("id") == wanted]
    if not selected:
        cgast.die(f"{COMPONENT}: no CVE matched {args.cve!r}")
    out = cgast.new_tempfile(prefix="cgacv-selection.", suffix=".json")
    workflow.write_json(out, {"version": 1, "count": len(selected),
                              "cves": selected})
    cgast.set_path(state, SELECTION_KEY, out)
    history = state.setdefault(HISTORY_KEY, [])
    if not isinstance(history, list):
        cgast.die(f"{COMPONENT}: {HISTORY_KEY} must be an array", 2)
    history.append({"cves": [cve["id"] for cve in selected],
                    "selection": cgast.rel(out)})
    cgast.info(f"{COMPONENT}: selected {len(selected)} CVE(s) -> "
               f"{cgast.rel(out)}")


def cmd_expand(state, _args) -> None:
    selected = workflow.load_json(cgast.require_path(
        state, SELECTION_KEY, "run 'cgacv select' first"))
    items = []
    for cve in selected.get("cves", []):
        package = cve["debian"]["source_package"]
        for variant in cve["variants"]:
            item_id = f"{cve['id']}-{variant['name']}"
            items.append({
                "id": item_id,
                "cve": cve["id"],
                "cve_url": cve["url"],
                "tracker": cve["debian"]["tracker"],
                "package": package,
                "owner": "debian",
                "repo": f"{package}-{variant['name']}",
                "language": cve["language"],
                "variant": variant["name"],
                "version": variant["version"],
                "source": copy.deepcopy(variant["source"]),
                "dependencies": copy.deepcopy(cve["build"]["dependencies"]),
                "build_command": cve["build"]["command"],
                "queries": copy.deepcopy(cve.get("queries", [])),
            })
    out = cgast.new_tempfile(prefix="cgacv-work.", suffix=".json")
    workflow.write_json(out, {"version": 1, "count": len(items),
                              "items": items})
    cgast.set_path(state, WORK_KEY, out)
    state.setdefault(HISTORY_KEY, []).append(
        {"work_items": cgast.rel(out), "count": len(items)})
    cgast.info(f"{COMPONENT}: expanded {len(items)} work item(s) -> "
               f"{cgast.rel(out)}")


def cmd_info(state, _args) -> None:
    cgast.info(f"{COMPONENT}: CVE specification handler")
    for key in (SPEC_KEY, SELECTION_KEY, WORK_KEY):
        path = cgast.get_path(state, key)
        cgast.info(f"  {key}: {cgast.rel(path) if path else '(none)'}")


def cmd_serve(_state, _args) -> None:
    import cga_http as C
    from . import serve
    C.serve(COMPONENT, int(os.environ.get("CGA_PREP_CGACV_PORT", DEFAULT_PORT)),
            serve.routes())
    raise SystemExit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=COMPONENT)
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("import"); p.add_argument("spec"); p.set_defaults(func=cmd_import)
    p = sub.add_parser("validate"); p.add_argument("spec", nargs="?"); p.set_defaults(func=cmd_validate)
    p = sub.add_parser("select"); p.add_argument("--cve"); p.set_defaults(func=cmd_select)
    p = sub.add_parser("expand"); p.set_defaults(func=cmd_expand)
    p = sub.add_parser("info"); p.set_defaults(func=cmd_info)
    p = sub.add_parser("serve"); p.set_defaults(func=cmd_serve)
    return enhance_parser(parser, "cv")


def main(argv: list[str]) -> int:
    parser = build_parser()
    if not argv or argv[0] in ("help", "-h", "--help"):
        parser.print_help(sys.stderr); return 0
    args = parser.parse_args(argv)
    state = cgast.read()
    try:
        args.func(state, args)
    except workflow.WorkflowError as exc:
        cgast.die(f"{COMPONENT}: {exc}", 2)
    cgast.write(state)
    return 0

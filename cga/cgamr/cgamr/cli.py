"""cgamr: a real CGAST MRVA submit/status/download client.

Commands read one JSON CGAST object on stdin, merge their result, and write the
object to stdout. Human-readable monitoring output is written to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import cgast
from command_help import enhance_parser

from . import client, serve

COMPONENT = "cgamr"
DEFAULT_PORT = 8604
SUBMISSIONS_KEY = "cgamr-submissions"
ACTIVE_KEY = "cgamr-active"
TERMINAL = {"succeeded", "failed", "cancelled", "canceled", "timed_out"}


def _default(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback)


def _submissions(state: Dict[str, Any]) -> Dict[str, Any]:
    value = state.setdefault(SUBMISSIONS_KEY, {})
    if not isinstance(value, dict):
        cgast.die(f"{SUBMISSIONS_KEY!r} must be a JSON object")
    return value


def _submission(state: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = _submissions(state).get(name)
    if not isinstance(value, dict):
        cgast.die(f"{COMPONENT}: unknown submission {name!r}; run submit first")
    assert isinstance(value, dict)
    return value


def _packs(state: Dict[str, Any]) -> List[Path]:
    values = state.get("cgaql-pack", [])
    if not isinstance(values, list) or not values:
        cgast.die("cgamr submit: no cgaql-pack bundles (run 'cgaql pack')")
    result = [cgast.resolve(p) for p in values if isinstance(p, str)]
    if not result or any(not p.is_file() for p in result):
        cgast.die("cgamr submit: a cgaql-pack bundle is missing")
    return result


def _database_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    selection = cgast.require_path(
        state, "cgadl-selection", "run 'cgadl select/sql' and download first")
    doc: Any = {}
    try:
        doc = json.loads(selection.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        cgast.die(f"cgamr submit: cannot read database selection: {exc}")
    rows = doc.get("databases", [])
    if not isinstance(rows, list) or not rows:
        cgast.die("cgamr submit: cgadl-selection contains no databases")
    return rows


def _language(rows: List[Dict[str, Any]], requested: str | None) -> str:
    languages = {str(row.get("primary_language") or "") for row in rows}
    languages.discard("")
    if requested:
        wrong = sorted(lang for lang in languages if lang != requested)
        if wrong:
            cgast.die(f"cgamr submit: selected DB language(s) {wrong} do not "
                      f"match --language {requested!r}")
        return requested
    if len(languages) != 1:
        cgast.die("cgamr submit: cannot infer one language; pass --language")
    return next(iter(languages))


def _connection(args, record: Dict[str, Any] | None = None) -> Dict[str, Any]:
    record = record or {}
    return {
        "server": getattr(args, "server", None) or record.get("server") or
                  _default("CGA_MRVA_SERVER", "http://127.0.0.1:8081"),
        "controller_owner": getattr(args, "controller_owner", None) or
                            record.get("controller_owner") or
                            _default("CGA_MRVA_CONTROLLER_OWNER", "octo"),
        "controller_repo": getattr(args, "controller_repo", None) or
                           record.get("controller_repo") or
                           _default("CGA_MRVA_CONTROLLER_REPO", "ctl"),
        "bearer_token": getattr(args, "bearer_token", None) or
                        _default("CGA_MRVA_BEARER_TOKEN", "") or None,
    }


def _set_active(state: Dict[str, Any], name: str, stage: str,
                note: str) -> None:
    state[ACTIVE_KEY] = name
    state[serve.STATE_KEY] = stage
    state[serve.NOTE_KEY] = note
    item = _submissions(state).get(name, {})
    if isinstance(item, dict) and item.get("session_id") is not None:
        state[serve.SESSION_KEY] = item["session_id"]


def cmd_submit(state: Dict[str, Any], args) -> None:
    if args.name in _submissions(state):
        cgast.die(f"cgamr submit: submission {args.name!r} already exists; "
                  "inspect status before submitting again")
    explicit_pack = getattr(args, "pack", None)
    packs = [Path(explicit_pack).resolve()] if explicit_pack else _packs(state)
    if any(not path.is_file() for path in packs):
        cgast.die("cgamr submit: query pack does not exist")
    if args.pack_index < 0 or args.pack_index >= len(packs):
        cgast.die(f"cgamr submit: --pack-index must be 0..{len(packs)-1}", 2)
    pack = packs[args.pack_index]
    explicit_repos = getattr(args, "repos", None)
    if explicit_repos:
        if not args.language:
            cgast.die("cgamr submit: --repos requires --language", 2)
        for nwo in explicit_repos:
            if len(nwo.split("/")) != 2 or not all(nwo.split("/")):
                cgast.die(f"cgamr submit: expected owner/repo, got {nwo!r}", 2)
        rows = [{"git_owner": nwo.split("/")[0],
                 "git_repo": nwo.split("/")[1]} for nwo in explicit_repos]
        dbdir = None
    else:
        rows = _database_rows(state)
        dbdir = cgast.require_path(
            state, "cgadl-dbdir", "run 'cgadl download' before cgamr submit")
    language = _language(rows, args.language)
    conn = _connection(args)
    repositories: List[str] = []
    seen = set()

    cgast.info(f"{COMPONENT}: checking selected databases for {args.name}")
    for row in rows:
        owner = str(row.get("git_owner") or "")
        repo = str(row.get("git_repo") or "")
        nwo = f"{owner}/{repo}"
        if not owner or not repo or nwo in seen:
            continue
        seen.add(nwo)
        if dbdir is not None:
            archive = dbdir / owner / repo / f"{owner}_{repo}_db.zip"
            if not archive.is_file():
                cgast.die(f"cgamr submit: database archive missing: {archive}")
        repositories.append(nwo)
        cgast.info(f"  ready {nwo}")

    if not repositories:
        cgast.die("cgamr submit: selection has no usable repositories")
    response = client.submit(
        conn["server"], conn["controller_owner"], conn["controller_repo"],
        language, repositories, pack, args.user, conn["bearer_token"])
    if "id" not in response:
        cgast.die("cgamr submit: response has no session id")
    item = {
        "name": args.name,
        "user": args.user,
        "language": language,
        "session_id": response["id"],
        "repositories": repositories,
        "pack": cgast.rel(pack),
        "server": conn["server"],
        "controller_owner": conn["controller_owner"],
        "controller_repo": conn["controller_repo"],
        "status": response.get("status", "submitted"),
        "response": response,
    }
    _submissions(state)[args.name] = item
    _set_active(state, args.name, "submitting",
                f"submitted {len(repositories)} repositories")
    cgast.info(f"{COMPONENT}: {args.name} session={response['id']} "
               f"user={args.user} repos={len(repositories)}")


def cmd_attach(state: Dict[str, Any], args) -> None:
    if args.name in _submissions(state):
        cgast.die(f"cgamr attach: submission {args.name!r} already exists")
    conn = _connection(args)
    response = client.status(
        conn["server"], conn["controller_owner"], conn["controller_repo"],
        args.session_id, args.user, conn["bearer_token"])
    _submissions(state)[args.name] = {
        "name": args.name, "user": args.user, "session_id": args.session_id,
        "server": conn["server"], "controller_owner": conn["controller_owner"],
        "controller_repo": conn["controller_repo"],
        "repositories": [
            row["repository"]["full_name"]
            for row in response.get("scanned_repositories", [])],
        "status": response.get("status", ""),
        "status_response": response,
    }
    _set_active(state, args.name, "status-checking", "attached existing session")


def _print_status(name: str, response: Dict[str, Any]) -> None:
    cgast.info(f"{COMPONENT}: {name} overall={response.get('status', '')}")
    for scanned in response.get("scanned_repositories", []):
        repo = scanned.get("repository", {})
        cgast.info(f"  {repo.get('full_name', '?'):<40} "
                   f"{scanned.get('analysis_status', '?'):<12} "
                   f"results={scanned.get('result_count')} "
                   f"size={scanned.get('artifact_size_in_bytes')}")


def cmd_status(state: Dict[str, Any], args) -> None:
    item = _submission(state, args.name)
    conn = _connection(args, item)
    response = client.status(
        conn["server"], conn["controller_owner"], conn["controller_repo"],
        int(item["session_id"]), item.get("user"), conn["bearer_token"])
    item["status"] = response.get("status", "")
    item["status_response"] = response
    stage = "done" if item["status"] in TERMINAL else "status-checking"
    _set_active(state, args.name, stage, f"overall status: {item['status']}")
    _print_status(args.name, response)


def cmd_download(state: Dict[str, Any], args) -> None:
    item = _submission(state, args.name)
    conn = _connection(args, item)
    status_response = client.status(
        conn["server"], conn["controller_owner"], conn["controller_repo"],
        int(item["session_id"]), item.get("user"), conn["bearer_token"])
    output = Path(args.output_dir).resolve() if args.output_dir \
        else cgast.new_tempdir(prefix=f"cgamr-{args.name}-")
    output.mkdir(parents=True, exist_ok=True)
    files: List[str] = []
    for scanned in status_response.get("scanned_repositories", []):
        nwo = str(scanned.get("repository", {}).get("full_name") or "")
        if "/" not in nwo:
            continue
        owner, repo = nwo.split("/", 1)
        meta = client.download_metadata(
            conn["server"], conn["controller_owner"],
            conn["controller_repo"], int(item["session_id"]), owner, repo,
            item.get("user"), conn["bearer_token"])
        artifact_url = str(meta.get("artifact_url") or "")
        if not artifact_url:
            cgast.info(f"  no result for {nwo} "
                       f"({meta.get('analysis_status')})")
            continue
        destination = output / f"{owner}-{repo}.zip"
        size = client.download_artifact(
            artifact_url, conn["server"], destination, item.get("user"),
            conn["bearer_token"])
        files.append(cgast.rel(destination))
        cgast.info(f"  downloaded {nwo} -> {cgast.rel(destination)} "
                   f"({size} bytes)")
    item["status"] = status_response.get("status", "")
    item["status_response"] = status_response
    item["download_dir"] = cgast.rel(output)
    item["downloads"] = files
    _set_active(state, args.name, "done" if item["status"] in TERMINAL
                else "downloading", f"downloaded {len(files)} archive(s)")
    cgast.info(f"{COMPONENT}: {args.name} downloaded {len(files)}/"
               f"{len(item.get('repositories', []))} archive(s)")


def cmd_info(state: Dict[str, Any], args) -> None:
    items = _submissions(state)
    names = [args.name] if args.name else list(items)
    cgast.info(f"{COMPONENT}: MRVA requestor ({len(items)} submission(s))")
    if not names:
        cgast.info("  (no submissions)")
    for name in names:
        item = _submission(state, name)
        cgast.info(f"  {name}: user={item.get('user')} "
                   f"session={item.get('session_id')} status={item.get('status')} "
                   f"repos={len(item.get('repositories', []))} "
                   f"downloads={len(item.get('downloads', []))}")


def cmd_verify(state: Dict[str, Any], args) -> None:
    items = _submissions(state)
    names = args.names or list(items)
    if not names:
        cgast.die("cgamr verify: no submissions")
    ok = True
    for name in names:
        item = _submission(state, name)
        wanted = len(item.get("repositories", []))
        downloads = item.get("downloads", [])
        got = sum(1 for path in downloads
                  if isinstance(path, str) and cgast.resolve(path).is_file()) \
            if isinstance(downloads, list) else 0
        succeeded = item.get("status") == "succeeded"
        line_ok = succeeded and got == wanted and wanted > 0
        ok = ok and line_ok
        cgast.info(f"  {'PASS' if line_ok else 'FAIL'} {name}: "
                   f"status={item.get('status')} archives={got}/{wanted}")
    if not ok:
        raise SystemExit(1)
    cgast.info(f"{COMPONENT}: PASS ({len(names)} submission(s))")


def cmd_run(state: Dict[str, Any], args) -> None:
    """One submission, bounded polling, download and verification; keep checkpoints."""
    if args.poll_seconds <= 0 or args.timeout_seconds <= 0:
        cgast.die("cgamr run: poll and timeout seconds must be positive")
    if args.name in _submissions(state):
        cgast.die("cgamr run: submission already exists; use status/download to resume")
    log = Path(args.log_dir).resolve()
    if log.exists() and any(log.iterdir()):
        cgast.die("cgamr run: log directory must be empty (preserve previous checkpoints)")
    log.mkdir(parents=True, exist_ok=True)
    sequence = 0

    def operation(label, function, operation_args):
        nonlocal sequence
        sequence += 10
        base = log / f"{sequence:03d}-{label}"
        started = time.time()
        base.with_suffix(".state-in").write_text(json.dumps(state, indent=2) + "\n")
        error = None
        try:
            function(state, operation_args)
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            snapshot = json.dumps(state, indent=2) + "\n"
            base.with_suffix(".state-out").write_text(snapshot)
            (log / "latest.state").write_text(snapshot)
            base.with_suffix(".json").write_text(json.dumps({
                "operation": label, "started_unix": started,
                "finished_unix": time.time(), "error": error,
            }, indent=2) + "\n")

    operation("submit", cmd_submit, args)
    deadline = time.monotonic() + args.timeout_seconds
    while True:
        operation("status", cmd_status, args)
        status = _submission(state, args.name).get("status")
        if status in TERMINAL:
            if status != "succeeded":
                cgast.die(f"cgamr run: {args.name} finished with {status}; see {log}")
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            cgast.die(f"cgamr run: polling deadline exceeded; resume from {log / 'latest.state'}")
        time.sleep(min(args.poll_seconds, remaining))
    operation("download", cmd_download, args)
    operation("verify", cmd_verify, argparse.Namespace(names=[args.name]))


def cmd_reset(state: Dict[str, Any], args) -> None:
    if args.name:
        _submissions(state).pop(args.name, None)
        if state.get(ACTIVE_KEY) == args.name:
            state.pop(ACTIVE_KEY, None)
            for key in (serve.STATE_KEY, serve.SESSION_KEY, serve.NOTE_KEY):
                state.pop(key, None)
        cgast.info(f"{COMPONENT}: removed submission {args.name}")
    else:
        state.pop(SUBMISSIONS_KEY, None)
        for key in (ACTIVE_KEY, serve.STATE_KEY, serve.SESSION_KEY,
                    serve.NOTE_KEY):
            state.pop(key, None)
        cgast.info(f"{COMPONENT}: all submission state reset")


def cmd_serve(_state: Dict[str, Any], _args) -> None:
    import cga_http as C
    port = int(os.environ.get("CGA_CGAMR_PORT", DEFAULT_PORT))
    C.serve(COMPONENT, port, serve.routes())
    raise SystemExit(0)


def _add_connection(sp) -> None:
    sp.add_argument("--server", default=None, help="override the MRVA server URL")
    sp.add_argument("--controller-owner", default=None, help="override the controller owner")
    sp.add_argument("--controller-repo", default=None, help="override the controller repository")
    sp.add_argument("--bearer-token", default=None, help="optional server authentication token")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMPONENT, description="CGAST MRVA submit/status/download client")
    sub = parser.add_subparsers(dest="cmd")
    sp = sub.add_parser("submit", help="submit selected DBs and a query pack")
    sp.add_argument("--name", required=True, help="new local submission label")
    sp.add_argument("--user", required=True, help="MRVA request identity (X-MRVA-User)")
    sp.add_argument("--language", default=None,
                    help="query language; otherwise infer one database language")
    sp.add_argument("--pack-index", type=int, default=0,
                    help="zero-based cgaql-pack bundle index (default: 0)")
    sp.add_argument("--pack", help="prebuilt query pack instead of cgaql-pack")
    sp.add_argument("--repos", nargs="+", help="repositories in the configured DB store")
    _add_connection(sp)
    sp.set_defaults(func=cmd_submit)
    sp = sub.add_parser("attach", help="track a session submitted by another client")
    sp.add_argument("--name", required=True, help="unused local label for the existing session")
    sp.add_argument("--user", required=True, help="MRVA identity used to access the session")
    sp.add_argument("--session-id", type=int, required=True, help="existing server session ID")
    _add_connection(sp)
    sp.set_defaults(func=cmd_attach)
    sp = sub.add_parser("run", help="submit once, wait, download and verify selected DBs")
    sp.add_argument("--name", required=True, help="new local submission label")
    sp.add_argument("--user", required=True, help="MRVA request identity (X-MRVA-User)")
    sp.add_argument("--language", default=None,
                    help="query language; otherwise infer one database language")
    sp.add_argument("--pack-index", type=int, default=0,
                    help="zero-based cgaql-pack bundle index (default: 0)")
    sp.add_argument("--output-dir", required=True, help="destination for result ZIP archives")
    sp.add_argument("--log-dir", required=True, help="fresh directory for operation state checkpoints")
    sp.add_argument("--poll-seconds", type=float, default=5,
                    help="positive status-poll interval (default: 5)")
    sp.add_argument("--timeout-seconds", type=float, default=1800,
                    help="positive polling deadline in seconds (default: 1800)")
    _add_connection(sp)
    sp.set_defaults(func=cmd_run)
    for command, function in (("status", cmd_status), ("download", cmd_download)):
        sp = sub.add_parser(command, help="refresh one submission's status" if command == "status"
                            else "download available result archives")
        sp.add_argument("--name", required=True, help="recorded submission label")
        if command == "download":
            sp.add_argument("--output-dir", default=None,
                            help="result ZIP directory; otherwise allocate a managed directory")
        _add_connection(sp)
        sp.set_defaults(func=function)
    sp = sub.add_parser("info", help="summarize recorded submissions without a server request")
    sp.add_argument("--name", default=None, help="submission label; omitted means all")
    sp.set_defaults(func=cmd_info)
    sp = sub.add_parser("verify", help="check success and downloaded archive counts")
    sp.add_argument("names", nargs="*", help="submission labels; omitted means all")
    sp.set_defaults(func=cmd_verify)
    sp = sub.add_parser("reset", help="forget local submission state without cancelling server work")
    sp.add_argument("--name", default=None, help="label to forget; omitted resets all submissions")
    sp.set_defaults(func=cmd_reset)
    sp = sub.add_parser("serve", help="serve live submission fragments")
    sp.set_defaults(func=cmd_serve)
    return enhance_parser(parser, "mr")


def main(argv: List[str]) -> int:
    parser = build_parser()
    if not argv or argv[0] in ("-h", "--help", "help"):
        parser.print_help(sys.stderr)
        return 0
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return 0
    state = cgast.read()
    try:
        args.func(state, args)
    except client.ClientError as exc:
        cgast.die(f"{COMPONENT}: {exc}")
    cgast.write(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""cgamx: a real CGAST MRVA standalone-infrastructure controller.

Commands read one JSON CGAST object on stdin, run an infrastructure phase
(preflight/reset/build/start/logs/check/stop/cleanup), record any runtime state
(process ids, chosen ports/paths) under the ``cgamx`` key, and write the CGAST
back to stdout. All human-readable and progress output goes to stderr, so the
program composes as a filter with the other cga* commands.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

import cgast
from command_help import enhance_parser

from . import cmd as cmdserver
from . import infra

COMPONENT = "cgamx"
STATE_KEY = "cgamx"
DEFAULT_CMD_PORT = 8607


def _runtime(state: Dict[str, Any]) -> Dict[str, Any]:
    """The cgamx runtime sub-object (created on demand)."""
    value = state.setdefault(STATE_KEY, {})
    if not isinstance(value, dict):
        cgast.die(f"{STATE_KEY!r} must be a JSON object")
    return value


def _record_env(rt: Dict[str, Any]) -> None:
    """Snapshot the identifying config into the CGAST for visibility."""
    rt["port"] = int(os.environ["PORT"])
    rt["storage"] = os.environ["MRVA_STANDALONE_STORAGE"]
    rt["work_dir"] = os.environ["MRVA_WORK_DIR"]
    rt["tmp_dir"] = os.environ["MRVA_TMP_DIR"]
    rt["server_log"] = os.environ["SERVER_LOG"]
    rt["db_serve_dir"] = os.environ["MRVA_DB_SERVE_DIR"]


def cmd_preflight(state: Dict[str, Any], _args) -> None:
    rt = _runtime(state)
    rt["postgres_probe"] = infra.phase_preflight()
    _record_env(rt)
    rt["last_phase"] = "preflight"


def cmd_reset(state: Dict[str, Any], _args) -> None:
    rt = _runtime(state)
    infra.phase_reset(rt)
    _record_env(rt)
    rt["last_phase"] = "reset"


def cmd_build(state: Dict[str, Any], _args) -> None:
    rt = _runtime(state)
    infra.phase_build()
    rt["last_phase"] = "build"


def cmd_start(state: Dict[str, Any], _args) -> None:
    rt = _runtime(state)
    infra.server_start(rt)
    _record_env(rt)
    rt["last_phase"] = "start"


def cmd_logs(state: Dict[str, Any], _args) -> None:
    _runtime(state)
    infra.phase_logs()


def cmd_check(state: Dict[str, Any], _args) -> None:
    """Error gate: exit non-zero if the server log has non-benign errors."""
    _runtime(state)
    if not infra.error_check():
        cgast.info(f"FAIL: non-benign errors found in {os.environ['SERVER_LOG']}")
        raise SystemExit(1)
    cgast.info("PASS: no non-benign server errors.")


def cmd_stop(state: Dict[str, Any], _args) -> None:
    rt = _runtime(state)
    infra.server_stop(rt)
    rt["last_phase"] = "stop"


def cmd_cleanup(state: Dict[str, Any], _args) -> None:
    rt = _runtime(state)
    infra.phase_cleanup(rt)
    rt["last_phase"] = "cleanup"


def cmd_info(state: Dict[str, Any], _args) -> None:
    rt = _runtime(state)
    cgast.info(f"{COMPONENT}: standalone MRVA infrastructure")
    cgast.info(f"  storage:    {rt.get('storage', os.environ['MRVA_STANDALONE_STORAGE'])}")
    cgast.info(f"  server:     :{rt.get('port', os.environ['PORT'])} "
               f"pid={rt.get('server_pid', '(none)')}")
    if infra.storage_is_minio():
        cgast.info(f"  minio:      :{os.environ['MINIO_PORT']} "
                   f"pid={rt.get('minio_pid', '(none)')}")
    if infra.db_server_enabled():
        cgast.info(f"  db-server:  :{os.environ['DB_SERVER_PORT']} "
                   f"pid={rt.get('db_server_pid', '(none)')}")
    cgast.info(f"  work_dir:   {rt.get('work_dir', os.environ['MRVA_WORK_DIR'])}")
    cgast.info(f"  server_log: {rt.get('server_log', os.environ['SERVER_LOG'])}")
    cgast.info(f"  last_phase: {rt.get('last_phase', '(none)')}")


def cmd_cmd(_state: Dict[str, Any], _args) -> None:
    """Run the localhost command server (POST /run runs cga* commands).

    This is a long-running server, not a CGAST filter: it never returns and
    performs its own atomic session updates, so it does not read/write the
    CGAST on stdin/stdout like the infrastructure phases.
    """
    port = int(os.environ.get("CGA_CGAMX_PORT", DEFAULT_CMD_PORT))
    cmdserver.serve(port)
    raise SystemExit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMPONENT,
        description="CGAST standalone MRVA infrastructure controller")
    sub = parser.add_subparsers(dest="cmd")
    for name, func, helptext in (
        ("preflight", cmd_preflight,
         "check tools, ensure Postgres, free the ports"),
        ("reset", cmd_reset, "drop mrva tables, wipe work dir + logs"),
        ("build", cmd_build, "build mrvaserver + mrvaagent"),
        ("start", cmd_start, "start MinIO + DB server + mrvaserver"),
        ("logs", cmd_logs, "tail the server log + scan for errors"),
        ("check", cmd_check, "error gate (non-zero exit on real errors)"),
        ("stop", cmd_stop, "stop services, keep tables + work dir"),
        ("cleanup", cmd_cleanup, "stop services, drop tables, wipe work dir"),
        ("info", cmd_info, "print current infrastructure state"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.set_defaults(func=func)
    sp = sub.add_parser(
        "cmd", help="serve the localhost command server (runs cga* commands)")
    sp.set_defaults(func=cmd_cmd)
    return enhance_parser(parser, "mx")


def main(argv: List[str]) -> int:
    parser = build_parser()
    if not argv or argv[0] in ("-h", "--help", "help"):
        parser.print_help(sys.stderr)
        return 0
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return 0
    # The command server is a standalone daemon: it needs no MRVA infrastructure
    # config and is not a stdin/stdout CGAST filter (it swaps the session file
    # itself), so run it directly.
    if args.func is cmd_cmd:
        args.func({}, args)
        return 0
    # Resolve/propagate configuration before any phase runs.
    infra.config()
    state = cgast.read()
    args.func(state, args)
    cgast.write(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

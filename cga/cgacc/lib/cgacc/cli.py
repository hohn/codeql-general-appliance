"""Explicit installation and foreground editor launcher."""

import argparse
import json
from pathlib import Path
import signal
import sys
import time

from command_help import enhance_parser

from .runtime import EditorError, Editors, executable, install


def main() -> int:
    parser = argparse.ArgumentParser(description="Native Coder code-server for CGA")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install", help="install the pinned, checksum-verified native release")
    commands.add_parser("info", help="locate the installed code-server")
    serve = commands.add_parser("serve", help="serve a workspace until SIGINT/SIGTERM")
    serve.add_argument("project", type=Path, help="existing .code-workspace file")
    serve.add_argument("--runtime", type=Path, required=True,
                       help="private editor config, log, settings, and extensions directory")
    serve.add_argument("--port", type=int, default=0,
                       help="fixed loopback port (default: 0, automatically allocated)")
    enhance_parser(parser, "cc")
    args = parser.parse_args()
    try:
        if args.command in ("install", "info"):
            print(json.dumps({"executable": install() if args.command == "install"
                              else executable()}))
            return 0
        project = args.project.resolve(strict=True)
        editors = Editors()
        def stop(_signum, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            value = editors.open("workspace", project.parent, project, args.runtime.resolve(),
                                 port=args.port)
            print(json.dumps(value), flush=True)
            while True:
                time.sleep(1)
                if editors.values["workspace"].process.poll() is not None:
                    raise EditorError("code-server exited; inspect the runtime log")
        except KeyboardInterrupt:
            return 0
        finally:
            editors.close()
    except (EditorError, OSError, ValueError) as exc:
        print(f"cgacc: {exc}", file=sys.stderr)
        return 1

"""CGAST lifecycle for MRVA; PostgreSQL and archive services are independent."""
import argparse
import os
from pathlib import Path

import cgast
import service
from cgamx import infra
from command_help import enhance_parser

KEY = "cgamrva"


def execute(state, args):
    if args.cmd == "start":
        # Reuse existing configuration defaults, not the combined service lifecycle.
        infra.config()
        binary = args.binary.resolve()
        argv = [binary, "--mode=standalone", "--loglevel=info",
                f"--dbpath={os.environ['MRVA_QLDB_DIR']}"]
        if os.environ.get("MRVA_DBG_DUMP_SYSVIEW"):
            argv.append("--dbg-dump-sysview")
        service.start(state, KEY, argv, int(os.environ["PORT"]),
                      os.environ["SERVER_LOG"],
                      {"binary": str(binary), "work_dir": os.environ["MRVA_WORK_DIR"],
                       "archive_url": os.environ["MRVA_DB_SERVER_URL"]},
                      env=dict(os.environ))
    else:
        rt = service.require(state, KEY)
        if args.cmd == "stop":
            service.stop(rt)
        elif args.cmd == "check":
            service.check(rt)
            text = Path(rt["log"]).read_text(errors="replace")
            errors = [line for line in text.splitlines()
                      if any(word in line for word in ("ERROR", "panic", "fatal"))
                      and "mrva-project-resolver" not in line]
            if errors:
                raise ValueError("Non-benign MRVA log errors: " + "\n".join(errors[:10]))
        else:
            cgast.info(rt)


def main(argv):
    parser = argparse.ArgumentParser(prog=KEY, description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start").add_argument("--binary", type=Path, required=True)
    for name in ("check", "stop", "info"):
        sub.add_parser(name)
    enhance_parser(parser, "ms")
    return service.dispatch(parser, argv, execute)

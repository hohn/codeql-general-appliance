"""Serve CodeQL database archives to local MRVA workers."""

import argparse
from pathlib import Path
import sys

import cgast
import service
from command_help import enhance_parser

KEY = "cgadbserve"


def execute(state, args):
    if args.cmd == "start":
        directory = args.directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        service.start(state, KEY,
                      [sys.executable, "-m", "http.server", str(args.port),
                       "--bind", "127.0.0.1", "--directory", directory],
                      args.port, args.log, {"directory": str(directory)})
    else:
        runtime = service.require(state, KEY)
        if args.cmd == "stop":
            service.stop(runtime)
        elif args.cmd == "check":
            service.check(runtime)
        else:
            cgast.info(runtime)


def main(argv):
    parser = argparse.ArgumentParser(prog=KEY, description=__doc__)
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--directory", type=Path, required=True)
    start.add_argument("--port", type=int, required=True)
    start.add_argument("--log", type=Path, required=True)
    for name in ("check", "stop", "info"):
        subparsers.add_parser(name)
    enhance_parser(parser, "ds")
    return service.dispatch(parser, argv, execute)
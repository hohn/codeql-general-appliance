"""Lifecycle for the independent, loopback-only CGA viewer gateway."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

COLLECTION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COLLECTION / "lib"))

import service
from command_help import enhance_parser


def parser():
    result = argparse.ArgumentParser(prog="cga gateway", description=__doc__)
    actions = result.add_subparsers(dest="action", required=True)
    for action in ("start", "status", "stop"):
        command = actions.add_parser(action)
        if action == "start":
            command.add_argument("--port", type=int, default=os.environ.get("CGA_GATEWAY_PORT", "8599"))
            command.add_argument("--config", type=Path)
    return enhance_parser(result, "gateway")


def healthy(record):
    if record.get("docs_root") != str(COLLECTION.parent):
        raise RuntimeError(
            "gateway needs an upgrade or a different checkout; "
            "restart it with 'cga gateway stop' then 'cga gateway start'")
    opener = build_opener(ProxyHandler({}))
    with opener.open(
            f"http://127.0.0.1:{record['port']}/healthz", timeout=2) as response:
        if json.load(response) != {"service": "cga-gateway"}:
            raise RuntimeError("recorded gateway port is serving a different application")
    with opener.open(Request(
            f"http://127.0.0.1:{record['port']}/documentation/docs/cga-overview.html",
            method="HEAD"), timeout=2):
        pass


def main(argv=None):
    args = parser().parse_args(argv)
    directory = Path(os.environ.get(
        "CGA_GATEWAY_RUN_DIR", str(COLLECTION / ".run" / "gateway"))).expanduser().resolve()
    try:
        if args.action == "status" and not directory.exists():
            print("cga gateway: stopped")
            return 0
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "lifecycle.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = directory / "service.json"
            record = json.loads(path.read_text()) if path.exists() else {}
            if args.action == "status":
                if service.owned(record):
                    healthy(record)
                    print(f"cga gateway: http://127.0.0.1:{record['port']}/ (pid {record['pid']})")
                else:
                    print("cga gateway: stopped")
                return 0
            if args.action == "stop":
                service.stop(record)
                path.unlink(missing_ok=True)
                print("cga gateway: stopped")
                return 0
            if service.owned(record):
                healthy(record)
                if record["port"] != args.port or record.get("config") != (
                        str(args.config.expanduser().resolve()) if args.config else None):
                    raise ValueError("gateway is running with different settings; stop it first")
                print(f"cga gateway: http://127.0.0.1:{record['port']}/ (already running)")
                return 0
            service.free_port(args.port)
            config = args.config.expanduser().resolve() if args.config else None
            if config and not config.is_file():
                raise ValueError(f"gateway configuration not found: {config}")
            binary = directory / "cgagateway"
            subprocess.run(
                ["go", "build", "-o", str(binary), "."],
                cwd=COLLECTION / "cgagateway", check=True)
            command = [str(binary), "--port", str(args.port),
                       "--docs-root", str(COLLECTION.parent)]
            if config:
                command += ["--config", str(config)]
            log = directory / "gateway.log"
            with log.open("ab") as output:
                child = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=output,
                    stderr=subprocess.STDOUT, start_new_session=True)
            record = {"pid": child.pid, "identity": service.identity(child.pid),
                      "port": args.port, "config": str(config) if config else None,
                      "docs_root": str(COLLECTION.parent)}
            try:
                deadline = time.monotonic() + 15
                while True:
                    if child.poll() is not None:
                        raise RuntimeError(f"gateway exited; see {log}")
                    try:
                        healthy(record)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f"gateway did not become ready; see {log}")
                        time.sleep(0.1)
                path.write_text(json.dumps(record) + "\n")
            except BaseException:
                service.stop(record)
                child.wait(timeout=5)
                raise
            print(f"cga gateway: http://127.0.0.1:{args.port}/")
            return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"cga gateway: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

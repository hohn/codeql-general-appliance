"""CGAST filters for a private loopback-only PostgreSQL cluster."""
import argparse
from pathlib import Path

import cgast
import service
from command_help import enhance_parser

KEY = "cgapg"


def execute(state, args):
    if args.cmd == "init":
        if KEY in state:
            raise ValueError("PostgreSQL state already exists")
        data = args.data_dir.resolve()
        if data.exists():
            raise ValueError(f"Refusing to initialize existing path: {data}")
        service.free_port(args.port)
        binary = args.bin_dir.resolve()
        data.parent.mkdir(parents=True, exist_ok=True)
        service.command([binary / "initdb", "-D", data, "-U", args.user,
                         "-A", "trust", "--no-locale", "--encoding=UTF8"])
        state[KEY] = {"data_dir": str(data), "bin_dir": str(binary),
                      "port": args.port, "user": args.user, "status": "initialized",
                      "log": str(data.parent / (data.name + ".log"))}
        return
    rt = service.require(state, KEY)
    binary, data = Path(rt["bin_dir"]), Path(rt["data_dir"])
    if args.cmd == "start":
        if rt["status"] == "running":
            raise ValueError("PostgreSQL is already marked running")
        if (data / "postmaster.pid").exists():
            raise ValueError("Existing postmaster.pid; inspect the cluster before starting")
        service.free_port(rt["port"])
        try:
            service.command([binary / "pg_ctl", "-D", data, "-l", rt["log"], "-o",
                             f"-h 127.0.0.1 -p {rt['port']} -c unix_socket_directories=''",
                             "-w", "start"])
        except BaseException:
            # pg_ctl can time out after launching the private cluster.
            if (data / "postmaster.pid").exists():
                service.command([binary / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"])
            raise
        rt["pid"] = int((data / "postmaster.pid").read_text().splitlines()[0])
        rt["identity"] = service.identity(rt["pid"])
        rt["status"] = "running"
    elif args.cmd in ("createdb", "check"):
        if not service.owned(rt):
            raise ValueError("PostgreSQL is not running with its recorded identity")
        connection = ["-h", "127.0.0.1", "-p", str(rt["port"]), "-U", rt["user"]]
        if args.cmd == "createdb":
            service.command([binary / "createdb", *connection, "--", args.name])
            rt.setdefault("databases", []).append(args.name)
        else:
            service.command([binary / "pg_isready", *connection])
    elif args.cmd == "stop":
        if service.owned(rt):
            service.command([binary / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"])
        rt["status"] = "stopped"
    elif args.cmd == "info":
        cgast.info(rt)


def main(argv):
    parser = argparse.ArgumentParser(prog=KEY, description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init")
    init.add_argument("--data-dir", type=Path, required=True)
    init.add_argument("--bin-dir", type=Path, required=True)
    init.add_argument("--port", type=int, required=True)
    init.add_argument("--user", default="study")
    sub.add_parser("createdb").add_argument("name")
    for name in ("start", "check", "stop", "info"):
        sub.add_parser(name)
    enhance_parser(parser, "pg")
    return service.dispatch(parser, argv, execute)

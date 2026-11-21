"""Start existing CGA views together without running an analysis or seeding state."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener
from urllib.error import HTTPError

COLLECTION = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(COLLECTION / "lib"), str(COLLECTION / "cgawf")]

import gateway
import service
from cgawf.repository import Repository, WorkflowError, atomic_write, canonical_json
from command_help import enhance_parser

ANALYSIS = ("cgasv", "cgadl", "cgaql", "cgamr", "cgamu", "cgasi", "cgamx", "cgaex")
PREPARATION = ("cgacv", "cgasp", "cgadb", "cgaqg")
BASE_PORTS = {"analysis": 8600, "preparation": 8500, "bench": 8610, "flow": 8720}
OPENER = build_opener(ProxyHandler({}))


@dataclass
class Viewer:
    name: str
    command: list[str]
    port: int
    environment: dict[str, str]

    def fingerprint(self):
        environment = {key: value for key, value in self.environment.items()
                       if key.startswith(("CGA", "MRVA", "POSTGRES"))
                       or key in ("PORT", "DB_SERVER_PORT", "PATH")}
        return hashlib.sha256(canonical_json(
            {"command": self.command, "environment": environment})).hexdigest()


def port(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("viewer ports must be integers in 1..65535")
    number = int(value)
    if not 1 <= number <= 65535:
        raise ValueError("viewer ports must be integers in 1..65535")
    return number


def read_json(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def current_workflow():
    if os.environ.get("CGA_DIR"):
        return Repository.discover().root
    for root in (Path.cwd(), *Path.cwd().parents):
        if (root / ".cga/config").is_file():
            return root
    return None


def configuration(path):
    if path:
        path = path.expanduser().resolve()
        document, base = read_json(path), path.parent
    else:
        base = Path.cwd()
        document = {}
        workflow = current_workflow()
        if workflow:
            document["analysis"] = {"workflow": str(workflow)}
            document["bench"] = {"workflow": str(workflow)}
        if not workflow or "CGAST_SESSION" in os.environ or "CGA_SESSION" in os.environ:
            scratch = Path(os.environ.get("CGA_TMPDIR", str(COLLECTION / "cga-tmp")))
            document["analysis"] = {"session_file": os.environ.get(
                "CGAST_SESSION", os.environ.get("CGA_SESSION", str(scratch / "session.json")))}
        scratch = Path(os.environ.get("CGA_PREP_TMPDIR", str(COLLECTION / "cga-prep-tmp")))
        document["preparation"] = {"session_file": os.environ.get(
            "CGA_PREP_SESSION", str(scratch / "session.json"))}
        document["flow"] = {"workflow": str(COLLECTION / "mrva-flow")}
    unknown = document.keys() - {*BASE_PORTS, "gateway"}
    if unknown:
        raise ValueError(f"unknown viewer configuration fields: {', '.join(sorted(unknown))}")
    for name, options in document.items():
        if not isinstance(options, dict):
            raise ValueError(f"{name} must be a configuration object")
        allowed = {"port"} if name == "gateway" else {"workflow", "session_file", "port", "env"}
        if options.keys() - allowed:
            raise ValueError(f"unknown {name} options: {sorted(options.keys() - allowed)}")
        if name != "gateway":
            if bool(options.get("workflow")) == bool(options.get("session_file")):
                raise ValueError(f"{name} requires exactly one of workflow or session_file")
            environment = options.get("env", {})
            if not isinstance(environment, dict) or any(
                    not isinstance(key, str) or not isinstance(value, str)
                    for key, value in environment.items()):
                raise ValueError(f"{name}.env must map environment names to strings")
            for key in ("workflow", "session_file"):
                if key in options:
                    if not isinstance(options[key], str) or not options[key].strip():
                        raise ValueError(f"{name}.{key} must be a nonempty path string")
                    options[key] = str((base / Path(options[key]).expanduser()).resolve())
    return document


def profile_ports(name, options):
    environment = os.environ.copy()
    environment.update(options.get("env", {}))
    prefix = "CGA_PREP_" if name == "preparation" else "CGA_"
    base = port(options.get("port", environment.get(prefix + "PAGE_PORT", BASE_PORTS[name])
                            if name not in ("flow", "bench") else BASE_PORTS[name]))
    components = PREPARATION if name == "preparation" else ANALYSIS
    values = {prefix + "PAGE_PORT": base}
    if name == "bench":
        return {"bench": base}, environment
    for index, component in enumerate(components, 1):
        key = prefix + component.upper() + "_PORT"
        override = options.get("env", {}).get(key) if name == "flow" else environment.get(key)
        values[key] = port(override if override is not None else base + index)
    if name != "preparation":
        override = options.get("env", {}).get("CGA_CGAUV_PORT") if name == "flow" \
            else environment.get("CGA_CGAUV_PORT")
        values["CGA_CGAUV_PORT"] = port(override if override is not None else base + 9)
    environment.update({key: str(value) for key, value in values.items()})
    return values, environment


def plan(document, directory):
    viewers, skipped, routes = [], [], {}
    for name in BASE_PORTS:
        options = document.get(name, {})
        ports, environment = profile_ports(name, options)
        prefix = "CGA_PREP_" if name == "preparation" else "CGA_"
        mount = "/" + name + "/"
        if name == "bench":
            routes[mount] = ports["bench"]
        else:
            routes[mount] = ports[prefix + "PAGE_PORT"]
            components = PREPARATION if name == "preparation" else ANALYSIS
            for component in components:
                routes[mount + component + "/"] = ports[prefix + component.upper() + "_PORT"]
            if name != "preparation":
                routes["/unified/" if name == "analysis" else "/flow/unified/"] = ports["CGA_CGAUV_PORT"]
        if not options:
            skipped.append(f"{name}: not configured")
            continue
        workflow = Path(options["workflow"]) if "workflow" in options else None
        metadata = workflow / ".cga" if workflow else None
        if workflow and environment.get("CGA_DIR"):
            explicit = Path(environment["CGA_DIR"]).expanduser().resolve()
            if explicit.parent == workflow:
                metadata = explicit
        session = metadata / "current.json" if metadata else Path(options["session_file"])
        if metadata and not (metadata / "config").is_file():
            skipped.append(f"{name}: no initialized workflow at {workflow}")
            continue
        if not session.is_file():
            skipped.append(f"{name}: state file not found: {session}")
            continue
        state = read_json(session)
        if name == "bench" and "cgabench-experiment" not in state:
            skipped.append(f"{name}: no Bench experiment in {session}")
            continue
        root = workflow or Path(environment.get(
            "CGA_PREP_ROOT" if name == "preparation" else "CGAST_ROOT",
            environment.get("CGA_ROOT", COLLECTION))).expanduser().resolve()
        environment.update({
            "CGA_ROOT": str(root), "CGAST_ROOT": str(root),
            "CGA_SESSION": str(session), "CGAST_SESSION": str(session),
        })
        if workflow:
            environment["CGA_DIR"] = str(metadata)
            environment["CGA_WORKFLOW_ROOT"] = str(workflow)
            environment.setdefault("CGA_TMPDIR", str(metadata / "tmp"))
        else:
            environment.pop("CGA_DIR", None)
            environment.pop("CGA_WORKFLOW_ROOT", None)
        if name == "bench":
            command = [str(COLLECTION / "cgabench/bin/cgabench"), "serve",
                       "--port", str(ports["bench"]), "--no-services", "--no-assistant"]
            if not workflow:
                command += ["--session-file", str(session)]
            viewers.append(Viewer("bench", command, ports["bench"], environment))
            continue
        components = PREPARATION if name == "preparation" else ANALYSIS
        for component in components:
            binary = directory / "bin" / component if component in ("cgasv", "cgamu") \
                else COLLECTION / component / "bin" / component
            viewers.append(Viewer(
                f"{name}-{component}", [str(binary), "cmd" if component == "cgamx" else "serve"],
                ports[prefix + component.upper() + "_PORT"], environment))
        config_name = "cga-prep-config.js" if name == "preparation" else "cga-config.js"
        config = directory / name / config_name
        command = [
            sys.executable, str(COLLECTION / "cga-view/cgaview/static_server.py"),
            "--port", str(ports[prefix + "PAGE_PORT"]),
            "--directory", str(COLLECTION / ("web-prep" if name == "preparation" else "web")),
            "--config", str(config),
        ]
        viewers.append(Viewer(f"{name}-page", command, ports[prefix + "PAGE_PORT"], environment))
        if workflow and name != "preparation":
            viewers.append(Viewer(
                f"{name}-unified", [str(COLLECTION / "cgauv/bin/cgauv"), "serve"],
                ports["CGA_CGAUV_PORT"], environment))
        elif name != "preparation":
            skipped.append(f"{name}-unified: requires an initialized workflow, not a raw session")
    routes["/sysview"] = port(os.environ.get("PORT", 8081))
    routes["/archives/"] = port(os.environ.get("DB_SERVER_PORT", 9080))
    gateway_port = port(document.get("gateway", {}).get(
        "port", os.environ.get("CGA_GATEWAY_PORT", 8599)))
    claimed = {gateway_port: "gateway"}
    for viewer in viewers:
        if viewer.port in claimed:
            raise ValueError(f"port {viewer.port} is shared by {claimed[viewer.port]} and {viewer.name}")
        claimed[viewer.port] = viewer.name
    if gateway_port in routes.values():
        raise ValueError("a gateway route points back to the gateway port")
    return viewers, skipped, routes, gateway_port


def ready(record):
    with OPENER.open(f"http://127.0.0.1:{record['port']}{record.get('health', '/healthz')}", timeout=2):
        pass


def gateway_directory():
    return Path(os.environ.get(
        "CGA_GATEWAY_RUN_DIR", str(COLLECTION / ".run/gateway"))).expanduser().resolve()


def existing_gateway(gateway_port, routes):
    path = gateway_directory() / "service.json"
    record = read_json(path) if path.is_file() else {}
    if not service.owned(record):
        return None
    gateway.healthy(record)
    try:
        with OPENER.open(f"http://127.0.0.1:{record['port']}/api/routes", timeout=2) as response:
            actual = json.load(response)
    except HTTPError as error:
        error.close()
        raise ValueError("running gateway needs an upgrade; restart it with 'cga gateway stop/start'") from error
    if record["port"] != gateway_port or actual != routes:
        raise ValueError("gateway settings differ; stop it with 'cga gateway stop' before starting cga serve")
    return {**record, "gateway_record": str(path)}


def stop_one(name, record):
    if record.get("external"):
        print(f"EXTERNAL {name}: left running")
        return
    if not service.owned(record):
        print(f"UNOWNED {name}: already stopped or replaced; no signal sent")
        return
    service.stop(record)
    if name == "gateway":
        path = Path(record["gateway_record"])
        with (path.parent / "lifecycle.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = read_json(path) if path.is_file() else {}
            if current.get("pid") == record["pid"] and current.get("identity") == record["identity"]:
                path.unlink()
    print(f"STOPPED {name}")


def start(document, directory, record, record_path):
    viewers, skipped, routes, gateway_port = plan(document, directory)
    previous = record.setdefault("services", {})
    desired = {viewer.name for viewer in viewers} | {"gateway"}
    if any(service.owned(item) for name, item in previous.items() if name not in desired):
        raise ValueError("viewer selection changed; run 'cga serve stop' before changing configuration")
    for viewer in viewers:
        old = previous.get(viewer.name, {})
        if service.owned(old):
            if old.get("fingerprint") != viewer.fingerprint():
                raise ValueError(f"{viewer.name} settings changed; run 'cga serve stop' first")
            ready(old)
        else:
            service.free_port(viewer.port)
    joined = existing_gateway(gateway_port, routes)
    if not joined:
        service.free_port(gateway_port)
    for message in skipped:
        print("SKIP " + message)
    record["skipped"] = skipped
    record["routes"] = routes
    atomic_write(record_path, canonical_json(record))
    started = []
    try:
        for viewer in viewers:
            if service.owned(previous.get(viewer.name, {})):
                print(f"UP {viewer.name}: :{viewer.port} (already running)")
                continue
            if viewer.name.endswith(("-cgasv", "-cgamu")):
                binary = Path(viewer.command[0])
                if not binary.exists():
                    binary.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run(
                        ["go", "build", "-o", str(binary), "."],
                        cwd=COLLECTION / binary.name, check=True)
            if viewer.name.endswith("-page"):
                config = Path(viewer.command[-1])
                config.parent.mkdir(parents=True, exist_ok=True)
                profile = viewer.name.removesuffix("-page")
                components = PREPARATION if profile == "preparation" else ANALYSIS
                prefix = "CGA_PREP_" if profile == "preparation" else "CGA_"
                values = {component: "http://127.0.0.1:" + viewer.environment[
                    prefix + component.upper() + "_PORT"] for component in components}
                global_name = "CGA_PREP_CONFIG" if profile == "preparation" else "CGA_CONFIG"
                atomic_write(config, f"window.{global_name} = {json.dumps(values)};\n".encode())
            service.start(previous, viewer.name, viewer.command, viewer.port,
                          directory / f"{viewer.name}-{time.time_ns()}.log",
                          {"fingerprint": viewer.fingerprint(),
                           "health": "/" if viewer.name.endswith("-page") else "/healthz"},
                          env=viewer.environment)
            started.append(viewer.name)
            atomic_write(record_path, canonical_json(record))
            print(f"UP {viewer.name}: :{viewer.port}")
        if joined:
            if not service.owned(previous.get("gateway", {})):
                previous["gateway"] = {**joined, "external": True}
            print(f"UP gateway: http://127.0.0.1:{gateway_port}/ (already running)")
        else:
            config = directory / "gateway-routes.json"
            atomic_write(config, canonical_json(routes))
            if gateway.main(["start", "--port", str(gateway_port), "--config", str(config)]):
                raise RuntimeError("gateway failed to start")
            previous["gateway"] = {
                **read_json(gateway_directory() / "service.json"),
                "gateway_record": str(gateway_directory() / "service.json"),
            }
            started.append("gateway")
        atomic_write(record_path, canonical_json(record))
    except BaseException:
        for name in reversed(started):
            try:
                stop_one(name, previous[name])
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                print(f"cga serve: rollback failed for {name}: {error}", file=sys.stderr)
            else:
                del previous[name]
        atomic_write(record_path, canonical_json(record))
        raise
    report_infrastructure(routes)


def report_infrastructure(routes):
    for name, route, path in (("sysview", "/sysview", "/sysview"), ("archives", "/archives/", "/")):
        try:
            with OPENER.open(f"http://127.0.0.1:{routes[route]}{path}", timeout=2):
                print(f"EXTERNAL {name}: :{routes[route]}")
        except OSError as error:
            print(f"SKIP {name}: MRVA-owned service unavailable ({error})")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cga serve", description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "status", "stop"):
        command = actions.add_parser(action)
        command.add_argument("--config", type=Path, default=os.environ.get("CGA_SERVE_CONFIG"))
    enhance_parser(parser, "serve")
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments or ["start"])
    directory = Path(os.environ.get(
        "CGA_SERVE_RUN_DIR", str(COLLECTION / ".run/viewers"))).expanduser().resolve()
    path = directory / "services.json"
    try:
        if args.action != "start" and not path.is_file():
            print("cga serve: no managed viewers; independent services are unchanged")
            return 0
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "lifecycle.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            record = read_json(path) if path.exists() else {"services": {}}
            if args.action == "start":
                start(configuration(args.config), directory, record, path)
            elif args.action == "stop":
                failed = False
                for name in reversed(list(record["services"])):
                    try:
                        stop_one(name, record["services"][name])
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                        print(f"cga serve: cannot stop {name}: {error}", file=sys.stderr)
                        failed = True
                    else:
                        del record["services"][name]
                if failed:
                    atomic_write(path, canonical_json(record))
                    return 1
                path.unlink()
            else:
                failed = False
                for name, item in record["services"].items():
                    try:
                        if not service.owned(item):
                            raise RuntimeError("recorded process is no longer running")
                        ready(item)
                        print(f"{'EXTERNAL' if item.get('external') else 'UP'} {name}: :{item['port']}")
                    except (OSError, RuntimeError) as error:
                        print(f"DOWN {name}: {error}")
                        failed = True
                for message in record.get("skipped", []):
                    print("SKIP " + message)
                if record.get("routes"):
                    report_infrastructure(record["routes"])
                if failed:
                    return 1
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"cga serve: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

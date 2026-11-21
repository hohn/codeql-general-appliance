from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.request import urlopen

COLLECTION = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(COLLECTION / name) for name in ("cgalib", "cgawf", "cgabench")]

import gateway
import viewers
from cgabench import model
from cgawf.repository import Repository


class ViewerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cga-viewers-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("CGA", "MRVA", "POSTGRES")) and key not in (
                           "PORT", "DB_SERVER_PORT")}
        environment.update({
            "CGA_SERVE_RUN_DIR": str(self.root / "viewers"),
            "CGA_GATEWAY_RUN_DIR": str(self.root / "gateway"),
        })
        patch = mock.patch.dict(os.environ, environment, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.output = io.StringIO()

    def invoke(self, *args):
        with redirect_stdout(self.output), redirect_stderr(self.output):
            return viewers.main(list(args))

    def ports(self, *widths):
        starts = []
        with ExitStack() as stack:
            for width in widths:
                while True:
                    first = stack.enter_context(socket.socket())
                    first.bind(("127.0.0.1", 0))
                    base = first.getsockname()[1]
                    if base + width > 65535:
                        continue
                    try:
                        for offset in range(1, width):
                            listener = stack.enter_context(socket.socket())
                            listener.bind(("127.0.0.1", base + offset))
                    except OSError:
                        continue
                    starts.append(base)
                    break
        return starts

    def test_missing_state_is_reported_without_creating_workflows(self):
        missing = self.root / "missing"
        document = {
            "analysis": {"workflow": str(missing)},
            "bench": {"session_file": str(missing / "state.json")},
        }
        planned, skipped, _routes, _port = viewers.plan(document, self.root / "runtime")
        self.assertEqual(planned, [])
        self.assertTrue(any("no initialized workflow" in item for item in skipped))
        self.assertTrue(any("state file not found" in item for item in skipped))
        self.assertIn("preparation: not configured", skipped)
        self.assertFalse(missing.exists())
        self.assertFalse((self.root / "runtime").exists())

    def test_configuration_is_relative_strict_and_keeps_profiles_separate(self):
        state = self.root / "session.json"
        state.write_text("{}")
        config = self.root / "viewers.json"
        config.write_text(json.dumps({
            "analysis": {"session_file": "session.json", "port": 21000},
            "flow": {"session_file": "session.json", "port": 22000},
        }))
        document = viewers.configuration(config)
        self.assertEqual(document["analysis"]["session_file"], str(state))
        planned, skipped, routes, _port = viewers.plan(document, self.root / "runtime")
        self.assertEqual(routes["/analysis/cgadl/"], 21002)
        self.assertEqual(routes["/flow/cgadl/"], 22002)
        files = [item.command[-1] for item in planned if item.name.endswith("-page")]
        self.assertEqual(len(set(files)), 2)
        self.assertTrue(any("analysis-unified" in item for item in skipped))
        for invalid in (
                {"bench": {"workflow": ".", "session_file": "session.json"}},
                {"unknown": {}}, {"bench": {"workflow": ".", "typo": 1}}):
            config.write_text(json.dumps(invalid))
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                viewers.configuration(config)
        for invalid in (True, 1.5, 0, 65536, ""):
            with self.subTest(port=invalid), self.assertRaises(ValueError):
                viewers.port(invalid)

    def test_all_viewers_start_idempotently_stop_and_preserve_state(self):
        analysis_port, preparation_port, bench_port, flow_port, gateway_port = self.ports(10, 5, 1, 10, 1)

        class Infrastructure(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"servers":[],"workers":[],"jobs":[],"spawns":[]}')

            def log_message(self, *_):
                pass

        infrastructure = ThreadingHTTPServer(("127.0.0.1", 0), Infrastructure)
        threading.Thread(target=infrastructure.serve_forever, daemon=True).start()
        self.addCleanup(infrastructure.server_close)
        self.addCleanup(infrastructure.shutdown)
        origin = f"http://127.0.0.1:{infrastructure.server_port}"
        os.environ.update({
            "CGA_MRVA_SERVER": origin,
            "PORT": str(infrastructure.server_port),
            "DB_SERVER_PORT": str(infrastructure.server_port),
        })
        options = {"gateway": {"port": gateway_port}}
        retained = {}
        for name, port in (
                ("analysis", analysis_port), ("preparation", preparation_port),
                ("bench", bench_port), ("flow", flow_port)):
            repository = Repository.init(self.root / name)
            if name == "bench":
                state = {}
                model.init(state, "fixture", "query-changes")
                repository.current_path.write_text(json.dumps(state))
            options[name] = {"workflow": name, "port": port}
            for path in (repository.current_path, repository.config_path, repository.manifest_path):
                retained[path] = path.read_bytes()
        for path in (COLLECTION / "web/cga-config.js", COLLECTION / "web-prep/cga-prep-config.js"):
            retained[path] = path.read_bytes() if path.exists() else None
        config = self.root / "all.json"
        config.write_text(json.dumps(options))
        self.addCleanup(self.invoke, "stop")
        self.assertEqual(self.invoke("start", "--config", str(config)), 0, self.output.getvalue())
        ownership = self.root / "viewers/services.json"
        records = json.loads(ownership.read_text())["services"]
        self.assertEqual(self.invoke("start", "--config", str(config)), 0, self.output.getvalue())
        self.assertEqual(records, json.loads(ownership.read_text())["services"])
        self.assertEqual(self.invoke("status"), 0, self.output.getvalue())
        self.assertIn("UP analysis-unified", self.output.getvalue())
        self.assertIn("UP flow-unified", self.output.getvalue())
        self.assertIn("EXTERNAL sysview", self.output.getvalue())
        base = f"http://127.0.0.1:{gateway_port}"
        for route in (
                "/documentation/", "/documentation/docs/cga-overview.html",
                "/documentation/docs/cga-help.html", "/documentation/cga/README.html",
                "/documentation/docs/readme-layout.css",
                "/analysis/", "/analysis/cgadl/overview",
                "/preparation/", "/preparation/cgacv/overview",
                "/bench/", "/bench/api/editors", "/unified/api/model",
                "/flow/", "/flow/unified/api/model", "/sysview", "/archives/"):
            with self.subTest(route=route), urlopen(base + route, timeout=5) as response:
                self.assertEqual(response.status, 200)
        for direct, expected in ((analysis_port, analysis_port + 2), (flow_port, flow_port + 2)):
            with urlopen(f"http://127.0.0.1:{direct}/cga-config.js", timeout=5) as response:
                self.assertIn(f"http://127.0.0.1:{expected}".encode(), response.read())
        self.assertEqual(self.invoke("stop"), 0, self.output.getvalue())
        self.assertFalse(ownership.exists())
        for item in records.values():
            self.assertFalse(viewers.service.owned(item))
        for path, content in retained.items():
            self.assertEqual(path.read_bytes() if path.exists() else None, content, str(path))
        with urlopen(origin, timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_reuses_but_does_not_stop_an_independent_gateway(self):
        gateway_port, = self.ports(1)
        document = {"gateway": {"port": gateway_port}}
        config = self.root / "viewers.json"
        config.write_text(json.dumps(document))
        routes = viewers.plan(document, self.root / "viewers")[2]
        routes_path = self.root / "routes.json"
        routes_path.write_text(json.dumps(routes))
        with redirect_stdout(self.output), redirect_stderr(self.output):
            self.assertEqual(gateway.main(
                ["start", "--port", str(gateway_port), "--config", str(routes_path)]), 0)
        self.addCleanup(gateway.main, ["stop"])
        self.assertEqual(self.invoke("start", "--config", str(config)), 0, self.output.getvalue())
        self.assertIn("SKIP analysis: not configured", self.output.getvalue())
        self.assertEqual(self.invoke("stop"), 0, self.output.getvalue())
        with urlopen(f"http://127.0.0.1:{gateway_port}/healthz", timeout=5) as response:
            self.assertEqual(json.load(response), {"service": "cga-gateway"})
        with urlopen(f"http://127.0.0.1:{gateway_port}/documentation/", timeout=5) as response:
            self.assertIn(b"docs/cga-overview.html", response.read())

    def test_gateway_without_documentation_requires_an_explicit_restart(self):
        with self.assertRaisesRegex(RuntimeError, "restart it"):
            gateway.healthy({"port": 8599})

    def test_occupied_foreign_port_is_not_reused_or_signalled(self):
        state = self.root / "state.json"
        state.write_text("{}")
        with socket.socket() as foreign:
            foreign.bind(("127.0.0.1", 0))
            foreign.listen()
            occupied = foreign.getsockname()[1]
            config = self.root / "viewers.json"
            config.write_text(json.dumps({
                "analysis": {"session_file": str(state), "port": occupied - 1},
            }))
            self.assertEqual(self.invoke("start", "--config", str(config)), 1)
            self.assertEqual(foreign.getsockname()[1], occupied)
            self.assertFalse((self.root / "viewers/services.json").exists())

    def test_partial_start_failure_rolls_back_only_new_processes(self):
        preparation_port, gateway_port = self.ports(5, 1)
        state = self.root / "state.json"
        state.write_text("{}")
        config = self.root / "viewers.json"
        config.write_text(json.dumps({
            "preparation": {"session_file": str(state), "port": preparation_port},
            "gateway": {"port": gateway_port},
        }))
        original = viewers.service.start
        started = []

        def fail_second(records, name, *args, **kwargs):
            if started:
                raise RuntimeError("simulated viewer startup failure")
            original(records, name, *args, **kwargs)
            started.append(dict(records[name]))

        with mock.patch.object(viewers.service, "start", side_effect=fail_second):
            self.assertEqual(self.invoke("start", "--config", str(config)), 1)
        self.assertIn("simulated viewer startup failure", self.output.getvalue())
        self.assertEqual(len(started), 1)
        self.assertFalse(viewers.service.owned(started[0]))
        self.assertEqual(json.loads((self.root / "viewers/services.json").read_text())["services"], {})
        self.assertEqual(state.read_text(), "{}")


if __name__ == "__main__":
    unittest.main()

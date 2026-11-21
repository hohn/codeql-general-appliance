from __future__ import annotations

import copy
import base64
from contextlib import closing
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import shlex
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
COLLECTION = PROJECT.parent
sys.path[:0] = [str(PROJECT), str(COLLECTION / "cgalib"),
                str(COLLECTION / "cgawf"), str(COLLECTION / "cgadl"),
                str(COLLECTION / "cgaql"), str(COLLECTION / "cgauv"),
                str(COLLECTION / "cgasi")]
sys.path.insert(0, str(COLLECTION / "cgacc" / "lib"))
sys.path.insert(0, str(COLLECTION / "lib"))
sys.path.insert(0, str(COLLECTION / "tests"))

import cgast
from cgacc import runtime as editor_runtime
from cgabench import cli, compare, engine, evidence, inputs, lifecycle, model, results, server, services, terminal
from cgaql import pack
from cgawf.repository import Repository
from workflow import WorkflowError
from gateway_fixture import start_gateway


def sarif(rules: list[str]) -> dict:
    return {"version": "2.1.0", "runs": [{
        "tool": {"driver": {
            "name": "bench-test",
            "rules": [{"id": rule, "name": rule, "properties": {"kind": "problem"}}
                      for rule in rules]}},
        "results": [{"ruleId": rule, "kind": "problem",
                     "message": {"text": rule},
                     "locations": [{"physicalLocation": {
                         "artifactLocation": {"uri": "source.c"},
                         "region": {"startLine": 7}}}]} for rule in rules],
    }]}


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {
            "CGAST_ROOT": str(self.root), "CGAST_TMPDIR": str(self.root / "tmp"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.state = {"unrelated": {"preserve": True}}
        cli.execute(self.state, ["init", "test", "--mode", "query-changes"])
        cli.execute(self.state, ["session", "one", "--user", "alice"])
        self.item = model.session(self.state, 1)
        self.selection = self.root / "databases.json"
        model.save(self.selection, {"databases": [
            {"git_owner": "acme", "git_repo": "repo", "primary_language": "cpp"}]})
        self.dbdir = self.root / "dbs"
        self.archive = self.dbdir / "acme" / "repo" / "acme_repo_db.zip"
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(b"test database")
        self.query = self.root / "queries.json"
        model.save(self.query, {"queries": [{"id": "cpp/test", "language": "cpp"}]})
        self.pack = self.root / "query.tgz"
        self.pack.write_bytes(b"test query pack")
        self.catalogue = self.root / "metadata.sql"
        with closing(sqlite3.connect(self.catalogue)) as connection, connection:
            connection.execute("CREATE TABLE metadata "
                               "(git_owner TEXT, git_repo TEXT, primary_language TEXT, "
                               "result_url TEXT, tool_version TEXT)")
            connection.execute("INSERT INTO metadata VALUES (?, ?, ?, ?, ?)",
                               ("acme", "repo", "cpp", self.archive.as_uri(), "2.27.1"))
        self.query_directory = self.root / "query-library"
        self.query_directory.mkdir()
        (self.query_directory / "Example.ql").write_text(
            "/**\n * @id cpp/example\n * @name Example\n * @kind problem\n */\n"
            "import cpp\nfrom File f where false select f, \"Example\"\n")

    def accept(self, index=1):
        fixed = model.fixed_stage(self.state)
        if index == 1 or fixed != "D":
            cli.execute(self.state, [
                "database", "--session", str(index), "--selection", str(self.selection),
                "--dbdir", str(self.dbdir), "--source", "user", "--no-advance"])
        if index == 1 or fixed != "Q":
            cli.execute(self.state, [
                "query", "--session", str(index), "--selection", str(self.query),
                "--pack", str(self.pack), "--no-advance"])

    def result(self, index: int, rules: list[str]):
        item = model.session(self.state, index)
        if not item["D"]["artifact"] or not item["Q"]["artifact"]:
            self.accept(index)
        path = self.root / f"results-{index}.json"
        rows = [{"identity": {"rule": rule}, "result": {},
                 "provenance": {"session": index, "result_index": result_index}}
                for result_index, rule in enumerate(rules)]
        model.save(path, {"findings": rows})
        item["R"].update(status="complete", artifact={
            "results": str(path), "sha256": model.fingerprint(path)})

    def ingested_result(self, index: int, rules: list[str]):
        item = model.session(self.state, index)
        if not item["D"]["artifact"] or not item["Q"]["artifact"]:
            self.accept(index)
        archive = self.root / f"sarif-{index}.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("results.sarif", json.dumps(sarif(rules)))
        item["engine"] = engine.run_tool({"cgamr-submissions": {item["submission"]: {
            "status": "succeeded", "user": item["user"], "session_id": index,
            "language": "cpp", "repositories": [f"acme/repo-{index}"],
            "downloads": [str(archive)],
        }}}, "si", ["ingest", "--name", item["submission"]])
        self.result(index, rules)
        item["R"]["artifact"].update(
            finding_count=len(rules),
            ingestion=copy.deepcopy(item["engine"]["cgasi-ingestions"][item["submission"]]))

    def terminal_environment(self, persistent=False):
        directory = self.root / "terminal-bin"
        directory.mkdir(exist_ok=True)
        shell = directory / "shell"
        shell.write_text("#!/bin/sh\nexec /bin/bash --noprofile --norc -i\n")
        shell.chmod(0o755)
        copilot = directory / "copilot"
        marker = self.root / "copilot-started"
        copilot.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" > {shlex.quote(str(marker))}\n"
            "printf 'CGA_COPILOT_STUB_STARTED\\n'\n")
        if persistent:
            copilot.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, sys\n"
                f"marker = pathlib.Path({str(marker)!r})\n"
                "marker.write_text('\\n'.join(sys.argv[1:]))\n"
                "marker.with_suffix('.pid').write_text(str(os.getpid()))\n"
                "print('CGA_COPILOT_STUB_STARTED', os.environ['CGA_BENCH_URL'], flush=True)\n"
                "for line in sys.stdin:\n"
                "    print('ASSISTANT_REPLY:' + line.strip(), flush=True)\n")
        copilot.chmod(0o755)
        return {"SHELL": str(shell), "PATH": f"{directory}:{os.environ['PATH']}",
                "HISTFILE": str(self.root / "shell-history")}, marker


class BenchTest(Fixtures):
    def test_editor_base_port_startup_and_per_session_mapping(self):
        path = self.root / "fixed-editor.json"
        self.result(1, ["cpp/example"])
        cli.execute(self.state, ["session", "two"])
        self.result(2, ["cpp/example"])
        database = self.root / "results.duckdb"
        database.write_bytes(b"retained results")
        for index in (1, 2):
            model.session(self.state, index)["engine"]["cgasi-db"] = str(database)
        model.save(path, self.state)
        args = cli.parser().parse_args(["serve", "--editor-port", "8611", "--no-services"])
        self.assertEqual(args.editor_port, 8611)
        with mock.patch.object(server, "serve") as serve:
            cli.main(["serve", "--session-file", str(path), "--editor-port", "8611",
                      "--no-services"])
            serve.assert_called_once_with(
                8610, str(path), False, editor_port=8611, start_assistant=True)
        with mock.patch.object(server, "serve") as serve:
            cli.main(["serve", "--session-file", str(path), "--no-assistant"])
            self.assertFalse(serve.call_args.kwargs["start_assistant"])
        backend = server.Backend(str(path), editor_port=8611)
        self.addCleanup(backend.close)
        with mock.patch.object(backend.editors, "open", return_value={}) as launch:
            for index in (1, 2):
                backend.editor_action({"session": index}, 8610)
                self.assertEqual(launch.call_args.kwargs, {"port": 8610 + index})
        for port in (-1, 65536):
            with self.subTest(port=port), self.assertRaisesRegex(WorkflowError, "editor port"):
                server.Backend(str(path), editor_port=port)
        backend.editor_port = 65535
        with self.assertRaisesRegex(WorkflowError, "editor port"):
            backend.editor_action({"session": 2}, 8610)

    def test_explicit_mode_selection_validates_legacy_inputs_without_rewriting_evidence(self):
        state = {}
        cli.execute(state, ["init", "unclassified"])
        with self.assertRaisesRegex(WorkflowError, "select an experiment mode"):
            cli.execute(state, ["session"])
        self.assertEqual(model.experiment(state)["sessions"], [])
        cli.execute(state, ["mode", "query-changes"])
        cli.execute(state, ["session"])
        with self.assertRaisesRegex(WorkflowError, "cannot change"):
            cli.execute(state, ["mode", "database-changes"])
        self.accept()
        cli.execute(self.state, ["session", "two"])
        exp = model.experiment(self.state)
        exp.pop("mode")
        before = copy.deepcopy(exp["sessions"])
        cli.execute(self.state, ["mode", "query-changes"])
        self.assertEqual(exp["sessions"], before)
        exp.pop("mode")
        exp["sessions"][1]["D"]["artifact"]["archives"][0]["sha256"] = "different"
        with self.assertRaisesRegex(WorkflowError, "differs from S1"):
            cli.execute(self.state, ["mode", "query-changes"])
        self.assertNotIn("mode", exp)

    def test_query_changes_clone_only_fixed_inputs_and_block_all_fixed_edit_routes(self):
        self.accept()
        baseline = copy.deepcopy(self.item)
        cli.execute(self.state, ["session", "two"])
        second = model.session(self.state, 2)
        self.assertEqual(second["D"]["artifact"], baseline["D"]["artifact"])
        self.assertIsNot(second["D"]["artifact"], self.item["D"]["artifact"])
        for command in [
            ["database", "--session", "2"],
            ["catalogue", str(self.catalogue), "--session", "2"],
            ["choose-databases", "--session", "2", "--generation", "unused", "--rows", "1"],
            ["tool", "--session", "2", "--stage", "D", "--", "dl", "select", "git_owner", "acme"],
            ["work", "--session", "2", "--stage", "D", "--note", "edit"],
            ["database", "--session", "1"],
        ]:
            with self.subTest(command=command), mock.patch.object(engine, "run_tool") as run:
                with self.assertRaisesRegex(WorkflowError, "fixed"):
                    cli.execute(self.state, command)
                run.assert_not_called()
        cli.execute(self.state, ["session", "three"])
        cli.execute(self.state, ["clone", "--session", "3", "--stage", "D",
                                 "--from-session", "2", "--no-advance"])
        third = model.session(self.state, 3)
        self.assertEqual(third["D"]["cloned_from"]["session"], 2)
        self.assertEqual(third["D"]["cloned_from"]["identity"],
                         model.input_identity("D", baseline["D"]["artifact"]))
        self.assertTrue(all(third[stage]["artifact"] is None for stage in ("Q", "J", "R")))
        with self.assertRaisesRegex(WorkflowError, "fixed D/Q"):
            model.clone(self.state, 3, "Q", 1)
        with self.assertRaisesRegex(WorkflowError, "prior session"):
            model.clone(self.state, 2, "D", 3)
        self.assertEqual(self.item, baseline)
        third["D"]["artifact"]["archives"][0]["sha256"] = "changed"
        with mock.patch.object(engine, "run_tool") as run:
            with self.assertRaisesRegex(WorkflowError, "differs from S1"):
                cli.execute(self.state, ["advance", "--session", "3"])
            run.assert_not_called()

    def test_unclassified_prototype_can_finish_missing_reference_then_clone_existing_variant(self):
        exp = model.experiment(self.state)
        variant = copy.deepcopy(self.item)
        variant.update(index=2, name="legacy-variant", submission="legacy-variant",
                       checkpoint=cgast.rel(cgast.new_tempfile(suffix=".json")))
        model.checkpoint(variant)
        exp["sessions"].append(variant)
        exp["mode"] = None
        cli.execute(self.state, ["mode", "query-changes"])
        cli.execute(self.state, ["database", "--session", "1",
                                 "--selection", str(self.selection), "--dbdir", str(self.dbdir),
                                 "--no-advance"])
        cli.execute(self.state, ["clone", "--session", "2", "--stage", "D",
                                 "--from-session", "1", "--no-advance"])
        self.assertEqual(variant["D"]["artifact"], self.item["D"]["artifact"])
        self.assertIsNone(variant["Q"]["artifact"])
        with self.assertRaisesRegex(WorkflowError, "locked"):
            cli.execute(self.state, ["database", "--session", "1"])

    def test_database_changes_clone_queries_and_keep_database_editing_and_auto_advance(self):
        model.experiment(self.state)["mode"] = None
        cli.execute(self.state, ["mode", "database-changes"])
        self.accept()
        cli.execute(self.state, ["session", "two"])
        second = model.session(self.state, 2)
        self.assertEqual(second["Q"]["artifact"], self.item["Q"]["artifact"])
        self.assertEqual(second["Q"]["cloned_from"]["session"], 1)
        self.assertIsNone(second["D"]["artifact"])
        for command in [
            ["query", "--session", "2"],
            ["library", str(self.query_directory), "--session", "2"],
            ["edit-query", "--session", "2", "--source", "source"],
            ["create-query", "--session", "2", "--directory", str(self.root / "draft"),
             "--name", "Draft", "--language", "cpp"],
            ["copy-query", "--session", "2", "--directory", str(self.root / "copy"),
             "--from-session", "1"],
        ]:
            with self.subTest(command=command), self.assertRaisesRegex(WorkflowError, "fixed"):
                cli.execute(self.state, command)
        with mock.patch.object(engine, "advance") as advance:
            cli.execute(self.state, ["database", "--session", "2",
                                     "--selection", str(self.selection), "--dbdir", str(self.dbdir)])
            advance.assert_called_once_with(self.state, second)
        with self.assertRaisesRegex(WorkflowError, "fixed D/Q"):
            model.clone(self.state, 2, "D", 1)
        self.assertIsNone(model.experiment(self.state)["C"].get("artifact"))

    def test_database_changes_allow_distinct_content_identities_not_reused_names(self):
        model.experiment(self.state)["mode"] = None
        cli.execute(self.state, ["mode", "database-changes"])
        self.accept()
        cli.execute(self.state, ["session", "two"])
        revised = self.root / "revised"
        archive = revised / "acme" / "repo" / "acme_repo_db.zip"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"revised database")
        with self.assertRaisesRegex(WorkflowError, "content hash"):
            cli.execute(self.state, ["database", "--session", "2",
                                     "--selection", str(self.selection),
                                     "--dbdir", str(revised), "--no-advance"])
        archive = revised / "acme" / "repo-newhash" / "acme_repo-newhash_db.zip"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"revised database")
        selected = self.root / "revised.json"
        model.save(selected, {"databases": [
            {"git_owner": "acme", "git_repo": "repo-newhash", "primary_language": "cpp"}]})
        cli.execute(self.state, ["database", "--session", "2", "--selection", str(selected),
                                 "--dbdir", str(revised), "--no-advance"])
        self.result(1, ["old"])
        self.result(2, ["new"])
        comparison = compare.compare(self.state, [2])
        self.assertEqual(comparison["mode"], "database-changes")
        self.assertEqual(len(comparison["sessions"][1]["added"]), 1)
        self.assertEqual(len(comparison["sessions"][1]["removed"]), 1)
        self.assertEqual(model.session(self.state, 2)["Q"]["artifact"], self.item["Q"]["artifact"])

    def test_comparison_always_includes_completed_s1_and_checks_fixed_inputs(self):
        self.accept()
        cli.execute(self.state, ["session", "two"])
        cli.execute(self.state, ["session", "three"])
        for index in (1, 2, 3):
            self.result(index, [str(index)])
        document = compare.compare(self.state, [3, 2])
        self.assertEqual(document["baseline"], "E.S[1].R")
        self.assertEqual([entry["address"] for entry in document["inputs"]],
                         ["E.S[1].R", "E.S[3].R", "E.S[2].R"])
        self.assertEqual(len(compare.compare(self.state, [2])["inputs"]), 2)
        self.assertEqual(document["inputs"][1]["cloned_from"]["D"]["session"], 1)
        self.item["R"]["status"] = "blocked"
        with self.assertRaisesRegex(WorkflowError, "completed S1"):
            compare.compare(self.state, [2, 3])
        self.item["R"]["status"] = "complete"
        second = model.session(self.state, 2)
        second["D"]["artifact"]["sha256"] = "different"
        with self.assertRaisesRegex(WorkflowError, "differs from S1"):
            compare.compare(self.state, [1, 2])

    def test_query_copy_from_library_is_an_isolated_editable_draft_not_a_fixed_clone(self):
        self.accept()
        cli.execute(self.state, ["library", str(self.query_directory)])
        cli.execute(self.state, ["session", "two"])
        support = self.query_directory / "Support.qll"
        support.write_text("import cpp\n")
        original = self.query_directory / "Example.ql"
        baseline = copy.deepcopy(self.item["Q"])
        page = inputs.collection(self.state, "queries", 2)
        destination = self.root / "copy"
        with mock.patch.object(pack, "_dependency", return_value=("codeql/cpp-all", "1.2.3", None)):
            cli.execute(self.state, ["copy-query", "--session", "2",
                                     "--directory", str(destination),
                                     "--generation", page["generation"], "--row", "1"])
        self.assertEqual((destination / "Support.qll").read_bytes(), support.read_bytes())
        source = inputs.query_source(self.state, 2)["source"]
        cli.execute(self.state, ["edit-query", "--session", "2",
                                 "--source", source.replace("where false", "where true")])
        self.assertIn("where false", original.read_text())
        self.assertIn("where true", inputs.query_source(self.state, 2)["source"])
        self.assertEqual(self.item["Q"], baseline)
        self.assertIsNone(model.session(self.state, 2)["Q"]["artifact"])
        self.assertNotIn("cloned_from", model.session(self.state, 2)["Q"])
        selected = self.root / "copied-selection.json"
        model.save(selected, {"queries": inputs.collection(self.state, "queries", 2, "user")["rows"]})
        cli.execute(self.state, ["query", "--session", "2", "--selection", str(selected),
                                 "--pack", str(self.pack), "--source", "user", "--no-advance"])
        self.assertEqual(model.session(self.state, 2)["Q"]["artifact"]["copied_from"]["source_path"],
                         str(original))

    def test_query_copy_uses_frozen_pack_source_and_rejects_unsafe_archive_entries(self):
        original = self.query_directory / "Example.ql"
        source = original.read_text()
        model.save(self.query, {"queries": [{
            "language": "cpp", "filename": "Example.ql", "path": str(original)}]})

        def bundle(unsafe=False):
            with tarfile.open(self.pack, "w:gz") as archive:
                files = {"./package/qlpack.yml": "name: cga/test\nversion: 0.0.1\n",
                         "./package/Example.ql": source, "./package/Support.qll": "import cpp\n",
                         "./package/.codeql/libraries/vendor/Other.ql": source,
                         "./package/Example.qlx": "compiled cache"}
                if unsafe == "conflicting":
                    files["package"] = "unsafe"
                elif unsafe:
                    files["../escape"] = "unsafe"
                for name, text in files.items():
                    value = text.encode()
                    member = tarfile.TarInfo(name)
                    member.size = len(value)
                    archive.addfile(member, io.BytesIO(value))

        bundle()
        self.accept()
        cli.execute(self.state, ["session", "two"])
        baseline = copy.deepcopy(self.item["Q"])
        original.write_text("mutable source changed")
        destination = self.root / "frozen-copy"
        cli.execute(self.state, ["copy-query", "--session", "2", "--from-session", "1",
                                 "--directory", str(destination)])
        self.assertEqual(inputs.query_source(self.state, 2)["source"], source)
        self.assertEqual(inputs.collection(self.state, "queries", 2, "user")["total"], 1)
        self.assertFalse((destination / ".codeql").exists())
        self.assertFalse((destination / "Example.qlx").exists())
        cli.execute(self.state, ["edit-query", "--session", "2",
                                 "--source", source.replace("where false", "where true")])
        self.assertEqual(self.item["Q"], baseline)
        self.assertEqual(model.session(self.state, 2)["workspace"]["cgabench-query"]
                         ["copied_from"]["pack_sha256"], baseline["artifact"]["sha256"])
        for unsafe in ("traversal", "conflicting"):
            with self.subTest(unsafe=unsafe):
                bundle(unsafe=unsafe)
                cli.execute(self.state, ["query", "--session", "1", "--selection", str(self.query),
                                         "--pack", str(self.pack), "--no-advance"])
                destination = self.root / "unsafe-copy"
                with self.assertRaisesRegex(WorkflowError, "unsafe archive"):
                    cli.execute(self.state, ["copy-query", "--session", "2", "--from-session", "1",
                                             "--directory", str(destination)])
                self.assertFalse(destination.exists())
                self.assertFalse((self.root / "escape").exists())

    @unittest.skipUnless(shutil.which("chromium") and shutil.which("node")
                         and shutil.which("duckdb") and shutil.which("sqlite3"),
                         "browser smoke test requires Chromium, Node, DuckDB and SQLite")
    def test_browser_grid_actions_use_same_persistent_commands(self, gateway=False):
        websocket = subprocess.run(
            ["node", "-p", "typeof WebSocket"], text=True, capture_output=True, check=True)
        if websocket.stdout.strip() != "function":
            self.skipTest("browser smoke test requires Node's built-in WebSocket")
        frame_requests = []

        class SysviewPage(BaseHTTPRequestHandler):
            def do_GET(self):
                frame_requests.append(self.path)
                if self.path == "/sysview":
                    body = (
                        '<!doctype html><title>MRVA fixture</title><p id="system"></p>'
                        '<script>fetch("/sysview/data").then(r => r.json()).then(data => '
                        'document.querySelector("#system").textContent = data.label)</script>'
                    ).encode()
                    content_type = "text/html"
                elif self.path == "/sysview/data":
                    body = b'{"label":"Read-only MRVA system view"}'
                    content_type = "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        frame_http = ThreadingHTTPServer(("127.0.0.1", 0), SysviewPage)
        threading.Thread(target=frame_http.serve_forever, daemon=True).start()
        self.addCleanup(frame_http.server_close)
        self.addCleanup(frame_http.shutdown)
        frame_origin = f"http://127.0.0.1:{frame_http.server_port}"
        frame_environment = mock.patch.dict(os.environ, {"CGA_MRVA_SERVER": frame_origin})
        frame_environment.start()
        self.addCleanup(frame_environment.stop)
        self.ingested_result(1, [f"rule-{index:02}" for index in range(35)])
        path = self.root / "browser.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(backend))
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        preparation_state = {}
        cli.execute(preparation_state, ["init", "preparation"])
        preparation_path = self.root / "preparation.json"
        model.save(preparation_path, preparation_state)
        preparation_backend = server.Backend(str(preparation_path))
        self.addCleanup(preparation_backend.close)
        preparation_http = ThreadingHTTPServer(
            ("127.0.0.1", 0), server.handler(preparation_backend))
        threading.Thread(target=preparation_http.serve_forever, daemon=True).start()
        self.addCleanup(preparation_http.server_close)
        self.addCleanup(preparation_http.shutdown)
        main_url = f"http://127.0.0.1:{http.server_port}"
        preparation_url = f"http://127.0.0.1:{preparation_http.server_port}"
        if gateway:
            main_url = start_gateway(self, {
                "/bench/": http.server_port, "/sysview": frame_http.server_port,
            }) + "/bench"
            preparation_url = start_gateway(self, {
                "/bench/": preparation_http.server_port, "/sysview": frame_http.server_port,
            }) + "/bench"
        profile = self.root / "chromium"
        browser = subprocess.Popen([
            "chromium", "--headless", "--disable-gpu",
            "--disable-background-networking", "--disable-sync", "--no-first-run",
            "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def stop():
            if browser.poll() is None:
                browser.terminate()
            browser.wait(timeout=10)
        self.addCleanup(stop)
        active = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 10
        while not active.exists():
            if browser.poll() is not None or time.monotonic() > deadline:
                self.fail("Chromium failed to become ready")
            time.sleep(.05)
        port = active.read_text().splitlines()[0]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as response:
            target = next(item for item in json.load(response) if item["type"] == "page")
        environment, marker = self.terminal_environment(persistent=True)
        sysview = (200, {
            "available": True, "url": f"{frame_origin}/sysview",
            "data": {
                "servers": [{"role": "commander", "instance_id": "bench-test", "online": True}],
                "workers": [{"status": "idle"}, {"status": "working"}],
                "jobs": [{"status": "succeeded"}, {"status": "pending"}],
                "spawns": [{}], "served_by": "bench-test", "generated_at": "test time",
            },
        })

        def infrastructure(state, phase):
            if phase == "build":
                raise WorkflowError("simulated infrastructure failure")
            state.setdefault("cgamx", {})["last_phase"] = phase

        with mock.patch.dict(os.environ, environment), \
                mock.patch.object(server, "fetch_sysview", return_value=sysview), \
                mock.patch("cgauv.model.fetch_sysview", return_value=sysview), \
                mock.patch.object(services, "run", side_effect=infrastructure), \
                mock.patch.object(pack, "_dependency", return_value=("codeql/cpp-all", "1.2.3", None)):
            backend.start_assistant(http.server_port)
            assistant_pid = backend.assistant.value.process.pid
            try:
                editor_runtime.executable()
                native_editor = "yes"
            except editor_runtime.EditorError:
                native_editor = "no"
            proc = subprocess.run([
                "node", str(PROJECT / "tests" / "browser-smoke.mjs"),
                target["webSocketDebuggerUrl"], main_url,
                str(self.catalogue), str(self.query_directory), str(self.root / "MyQuery"),
                preparation_url, native_editor],
                text=True, capture_output=True, timeout=150)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("/sysview", frame_requests, "the real frame page must be loaded")
        self.assertIn("/sysview/data", frame_requests, "the framed dashboard must run its script")
        self.assertEqual(backend.assistant.value.process.pid, assistant_pid,
                         "navigation/editor actions must reuse the warm assistant")
        self.assertEqual(int(marker.with_suffix(".pid").read_text()), assistant_pid)
        state = json.loads(path.read_text())
        self.assertEqual(model.session(state, 2)["D"]["cloned_from"]["session"], 1)
        self.assertIn("cgabench-query", model.session(state, 2)["workspace"])
        self.assertEqual(model.session(state, 2)["name"], "session-2")
        self.assertEqual(model.session(state, 2)["user"], "alice")

    def test_gateway_browser_grid_actions_use_same_persistent_commands(self):
        self.test_browser_grid_actions_use_same_persistent_commands(gateway=True)

    def test_editor_discovery_lists_only_live_sessions_without_launching(self):
        path = self.root / "editor-discovery.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        self.assertEqual(backend.editor_routes(), {})
        live = mock.Mock(url="http://127.0.0.1:12345")
        live.process.poll.return_value = None
        backend.editors.values[self.item["submission"]] = live
        with mock.patch.object(backend.editors, "open") as launch:
            self.assertEqual(backend.editor_routes(), {"session-1": live.url})
            live.process.poll.return_value = 1
            self.assertEqual(backend.editor_routes(), {})
            launch.assert_not_called()

    def test_editor_project_context_and_session_guards_preserve_evidence(self):
        path = self.root / "editor.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        with self.assertRaisesRegex(WorkflowError, "results are not complete"):
            backend.editor_action({"session": 1}, 8610)
        with self.assertRaisesRegex(WorkflowError, "select a session"):
            backend.editor_action({}, 8610)
        self.result(1, ["cpp/example"])
        database = self.root / "results.duckdb"
        database.write_bytes(b"retained results")
        self.item["engine"]["cgasi-db"] = str(database)
        model.save(path, self.state)
        before = path.read_bytes()
        with mock.patch.object(backend.editors, "open", return_value={"pid": 123}) as launch:
            self.assertEqual(backend.editor_action({"session": 1}, 8610), {"pid": 123, "session": 1})
            _, directory, project, runtime = launch.call_args.args
            self.assertEqual(directory, self.root / ".cgabench-query" / "session-1")
            self.assertEqual(runtime, self.root / ".cgacc" / "session-1")
            context = json.loads((directory / "bench-context.json").read_text())
            self.assertEqual(context["session"]["index"], 1)
            self.assertEqual(context["results"]["database"], str(database))
            self.assertEqual(context["example_request"]["session"], 1)
            self.assertEqual(context["endpoints"]["results"], "http://127.0.0.1:8610/api/results")
            self.assertTrue(all(Path(value).is_file()
                                for value in context["documentation"].values()))
            self.assertEqual(json.loads(project.read_text())["folders"][0]["path"], ".")
            self.assertIn("AGENTS.md", (directory / ".github/copilot-instructions.md").read_text())
            (directory / "AGENTS.md").write_text("User additions\n")
            backend.editor_action({"session": 1}, 9876)
            self.assertEqual((directory / "AGENTS.md").read_text(), "User additions\n")
            context = json.loads((directory / "bench-context.json").read_text())
            self.assertEqual(context["endpoints"]["results"], "http://127.0.0.1:9876/api/results")
            with mock.patch.object(backend, "repository", mock.Mock(
                    root=self.root, cga_dir=self.root / ".cga")):
                backend.editor_action({"session": 1}, 8610)
                _, directory, project, runtime = launch.call_args.args
                self.assertEqual(directory, self.root / ".cga/tmp/cgabench-query/session-1")
                self.assertEqual(runtime, self.root / ".cga/runtime/cgacc/session-1")
                self.assertTrue(project.is_file())
        self.assertEqual(path.read_bytes(), before)
        with mock.patch.object(backend.editors, "open",
                               side_effect=editor_runtime.EditorError("code-server is missing")):
            with self.assertRaisesRegex(WorkflowError, "code-server is missing"):
                backend.editor_action({"session": 1}, 8610)
        Path(self.item["R"]["artifact"]["results"]).write_text("{}")
        with self.assertRaisesRegex(WorkflowError, "snapshot has changed"):
            backend.editor_action({"session": 1}, 8610)

    def test_editor_http_requires_same_origin_json_and_valid_session(self):
        path = self.root / "editor-http.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(backend))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        url = f"http://127.0.0.1:{http.server_port}/api/editor"
        for headers, status in (
                ({"Content-Type": "application/json"}, 403),
                ({"Content-Type": "application/json", "X-CGA-Bench": "1",
                  "Origin": "https://example.invalid"}, 403),
                ({"Content-Type": "text/plain", "X-CGA-Bench": "1"}, 415),
                ({"Content-Type": "application/json", "X-CGA-Bench": "1"}, 400)):
            with self.subTest(headers=headers), mock.patch.object(backend.editors, "open") as launch:
                request = urllib.request.Request(url, data=b'{"session":1}', headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, status)
                error.exception.close()
                launch.assert_not_called()

    def test_warm_assistant_io_reconnect_restart_and_failure(self):
        path = self.root / "assistant.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        environment, marker = self.terminal_environment(persistent=True)
        self.assertIsNone(backend.assistant.action({"operation": "open"})["id"])
        self.assertFalse(marker.exists(), "attach must not start Copilot")
        with mock.patch.dict(os.environ, environment):
            backend.start_assistant(8610)
            opened = backend.assistant.action({"operation": "open"})
            self.assertTrue(opened["running"])
            self.assertEqual(opened["id"], backend.assistant.action({"operation": "open"})["id"])
            cursor, output = 0, b""

            def until(text):
                nonlocal cursor, output
                deadline = time.monotonic() + 10
                while text not in output:
                    self.assertLess(time.monotonic(), deadline, output)
                    page = backend.assistant.action(
                        {"operation": "read", "id": opened["id"], "cursor": cursor})
                    self.assertIsNone(page["error"])
                    cursor = page["cursor"]
                    output += base64.b64decode(page["data"])

            until(b"CGA_COPILOT_STUB_STARTED http://127.0.0.1:8610")
            arguments = marker.read_text().splitlines()
            self.assertEqual(arguments[:3], ["-C", str(self.root), "--interactive"])
            self.assertNotIn("--yolo", arguments)
            self.assertNotIn("--allow-all-tools", arguments)
            self.assertNotIn("--allow-all-paths", arguments)
            self.assertIn(str(path), arguments[3])
            self.assertIn("raw CGAST", arguments[3])
            backend.assistant.action(
                {"operation": "resize", "id": opened["id"], "columns": 111, "rows": 31})
            backend.assistant.action(
                {"operation": "write", "id": opened["id"], "data": "hello\r"})
            until(b"ASSISTANT_REPLY:hello")
            with self.assertRaisesRegex(WorkflowError, "stop the assistant"):
                backend.assistant.action({"operation": "start"})
            with self.assertRaisesRegex(WorkflowError, "terminal size"):
                backend.assistant.action(
                    {"operation": "resize", "id": opened["id"], "columns": 0, "rows": 24})
            stopped = backend.assistant.action({"operation": "stop", "id": opened["id"]})
            self.assertFalse(stopped["running"])
            restarted = backend.assistant.action({"operation": "start"})
            self.assertNotEqual(restarted["id"], opened["id"])
            with self.assertRaisesRegex(WorkflowError, "session changed"):
                backend.assistant.action(
                    {"operation": "write", "id": opened["id"], "data": "stale\r"})
            process = backend.assistant.value.process
            backend.close()
            self.assertIsNotNone(process.poll())
            with self.assertRaisesRegex(WorkflowError, "shutting down"):
                backend.assistant.action({"operation": "start"})

        failed = server.Backend(str(path))
        self.addCleanup(failed.close)
        with mock.patch.object(terminal.shutil, "which", return_value=None):
            failed.start_assistant(8610)
            self.assertIn("executable not found", failed.assistant.action({"operation": "open"})["error"])
            with self.assertRaisesRegex(WorkflowError, "executable not found"):
                failed.assistant.action({"operation": "start"})

    def test_assistant_http_is_guarded_and_attach_does_not_start(self):
        path = self.root / "assistant-http.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(backend))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        url = f"http://127.0.0.1:{http.server_port}/api/assistant"
        headers = {"Content-Type": "application/json", "X-CGA-Bench": "1"}
        for invalid, status in [
                ({"Content-Type": "application/json"}, 403),
                ({**headers, "Origin": "http://example.org"}, 403),
                ({**headers, "Host": "example.org"}, 403),
                ({**headers, "Content-Type": "text/plain"}, 415)]:
            request = urllib.request.Request(url, data=b'{"operation":"start"}', headers=invalid)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, status)
            error.exception.close()
            self.assertIsNone(backend.assistant.value)
        request = urllib.request.Request(url, data=b'{"operation":"open"}', headers=headers)
        with urllib.request.urlopen(request) as response:
            self.assertIsNone(json.load(response)["id"])
        self.assertIsNone(backend.assistant.value)

    def test_assistant_prestarts_before_infrastructure_setup(self):
        repository = Repository.init(self.root / "assistant-workflow")
        model.save(repository.current_path, self.state)
        environment, marker = self.terminal_environment(persistent=True)
        process = None

        def setup(backend, arguments):
            nonlocal process
            self.assertEqual(arguments, ["infrastructure", "setup"])
            process = backend.assistant.value.process
            self.assertIsNone(process.poll())
            deadline = time.monotonic() + 10
            while not marker.exists():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)

        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        with mock.patch.dict(os.environ, {**environment, "CGA_DIR": str(repository.cga_dir)}), \
                mock.patch.object(server.Backend, "mutate", autospec=True, side_effect=setup), \
                mock.patch.object(services, "configure"), \
                mock.patch.object(ThreadingHTTPServer, "serve_forever", side_effect=KeyboardInterrupt):
            server.serve(port, None)
        self.assertIsNotNone(process)
        self.assertIsNotNone(process.poll(), "startup assistant survived viewer shutdown")

    def test_persistent_terminal_io_resize_command_insertion_and_shutdown(self):
        path = self.root / "terminal.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        environment, marker = self.terminal_environment()
        cursor, output = 0, b""

        def until(text):
            nonlocal cursor, output
            deadline = time.monotonic() + 10
            while text not in output:
                self.assertLess(time.monotonic(), deadline, output)
                page = backend.terminal_action(
                    {"operation": "read", "id": opened["id"], "cursor": cursor}, 8610)
                self.assertIsNone(page["error"])
                cursor = page["cursor"]
                output += base64.b64decode(page["data"])

        with mock.patch.dict(os.environ, environment):
            opened = backend.terminal_action(
                {"operation": "open", "session": 1, "columns": 90, "rows": 24}, 8610)
            command = shlex.split(opened["command"])
            self.assertEqual(command[:2], ["copilot", "--yolo"])
            self.assertIn("--interactive", command)
            self.assertIn("copilot-assist-codeql-db-build.md", command[-1])
            self.assertIn(opened["catalogue"], command[-1])
            backend.terminal_action(
                {"operation": "write", "id": opened["id"],
                 "data": "printf '\\x54ERMINAL_READY\\n'; tty; stty size\r"}, 8610)
            until(b"TERMINAL_READY")
            until(b"/dev/pts/")
            until(b"24 90")
            again = backend.terminal_action(
                {"operation": "open", "session": 1, "columns": 100, "rows": 30}, 8610)
            self.assertEqual(opened["id"], again["id"])
            backend.terminal_action(
                {"operation": "write", "id": opened["id"], "data": "stty size\r"}, 8610)
            until(b"30 100")
            backend.terminal_action({"operation": "insert", "id": opened["id"]}, 8610)
            until(b"copilot --yolo")
            self.assertFalse(marker.exists())
            backend.terminal_action(
                {"operation": "write", "id": opened["id"], "data": "\r"}, 8610)
            until(b"CGA_COPILOT_STUB_STARTED")
            self.assertIn("--yolo", marker.read_text())
            self.assertIn(opened["catalogue"], marker.read_text())
            stopped = backend.terminal_action({"operation": "stop", "id": opened["id"]}, 8610)
            self.assertFalse(stopped["running"])
            self.assertFalse(backend.terminal_action(
                {"operation": "open", "session": 1}, 8610)["running"])
            restarted = backend.terminal_action(
                {"operation": "open", "session": 1, "restart": True}, 8610)
            self.assertNotEqual(restarted["id"], opened["id"])
            with self.assertRaisesRegex(WorkflowError, "terminal size"):
                backend.terminal_action(
                    {"operation": "resize", "id": restarted["id"],
                     "columns": 0, "rows": 24}, 8610)
            backend.close()
            self.assertIsNotNone(backend.terminals.get(restarted["id"]).process.poll())

    def test_built_catalogue_handoff_is_separate_from_existing_catalogue_defaults(self):
        path = self.root / "build.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        initial = backend.view()["experiment"]["sessions"][0]["database_build"]
        self.assertFalse(initial["loaded"])
        self.assertNotEqual(initial["import_path"], backend.view()["libraries"]["catalogue"])
        self.assertEqual(Path(initial["import_path"]).name, "metadata.sql")
        built = Path(initial["import_path"])
        built.parent.mkdir(parents=True)
        shutil.copyfile(self.catalogue, built)
        with closing(sqlite3.connect(built)) as connection, connection:
            connection.execute("UPDATE metadata SET tool_version = '9.9.9'")
        view = backend.act({"action": "catalogue", "session": 1,
                            "source": "user", "path": str(built)})
        self.assertTrue(view["experiment"]["sessions"][0]["database_build"]["loaded"])
        self.assertIsNone(backend.read()["experiment"]["sessions"][0]["D"]["artifact"])
        state = json.loads(path.read_text())
        self.assertEqual(inputs.collection(state, "databases", 1, "user")["total"], 1)
        backend.act({"action": "catalogue", "session": 1, "path": str(self.catalogue)})
        state = json.loads(path.read_text())
        self.assertEqual(inputs.collection(
            state, "databases", 1, "user")["rows"][0]["tool_version"], "9.9.9")
        self.assertEqual(inputs.collection(
            state, "databases", 1, "list")["rows"][0]["tool_version"], "2.27.1")

    def test_terminal_bounds_output_and_stops_its_foreground_job(self):
        path = self.root / "bounded-terminal.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        environment, _marker = self.terminal_environment()
        pid_file = self.root / "foreground.pid"
        script = (
            "import os, pathlib, signal, time; "
            "signal.signal(signal.SIGHUP, signal.SIG_IGN); "
            f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
            "print('x' * 2000, flush=True); time.sleep(60)"
        )
        with mock.patch.dict(os.environ, environment), \
                mock.patch.object(terminal, "BUFFER_LIMIT", 256):
            opened = backend.terminal_action({"operation": "open", "session": 1}, 8610)
            value = backend.terminals.get(opened["id"])
            value.write(shlex.join([sys.executable, "-c", script]) + "\r")
            deadline = time.monotonic() + 10
            while not pid_file.exists() or value.base == 0:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            page = value.output(0)
            self.assertTrue(page["reset"])
            self.assertLessEqual(len(base64.b64decode(page["data"])), 256)
            value.close()
            pid = int(pid_file.read_text())
            deadline = time.monotonic() + 5
            while Path(f"/proc/{pid}/stat").exists():
                self.assertLess(time.monotonic(), deadline, "foreground job survived terminal stop")
                if Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z "):
                    break
                time.sleep(.01)

    def test_terminal_http_requires_same_origin_and_json(self):
        path = self.root / "terminal-http.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(backend))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        for headers, expected in (
            ({"Content-Type": "application/json"}, 403),
            ({"Content-Type": "application/json", "X-CGA-Bench": "1",
              "Origin": "http://untrusted.invalid"}, 403),
            ({"Content-Type": "text/plain", "X-CGA-Bench": "1"}, 415),
        ):
            request = urllib.request.Request(
                f"http://127.0.0.1:{http.server_port}/api/terminal",
                data=json.dumps({"operation": "open", "session": 1}).encode(), headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as result:
                urllib.request.urlopen(request)
            self.assertEqual(result.exception.code, expected)
            result.exception.close()
        self.assertFalse(backend.terminals.contains(self.item["submission"]))

    def test_bench_stop_stops_owned_terminal_without_service_reset(self):
        path = self.root / "shutdown.json"
        model.save(path, self.state)
        environment, marker = self.terminal_environment(persistent=True)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "-c",
             "import os,signal,sys; signal.signal(signal.SIGINT, signal.SIG_IGN); "
             "os.execv(sys.argv[1], sys.argv[1:])",
             str(PROJECT / "bin" / "cgabench"), "serve", "--session-file", str(path),
             "--port", str(port), "--no-services"],
            env={**os.environ, **environment}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        def stop():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
            process.stderr.close()
        self.addCleanup(stop)
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 10
        while True:
            self.assertIsNone(process.poll(), "bench viewer failed to start")
            self.assertLess(time.monotonic(), deadline)
            try:
                with urllib.request.urlopen(url + "/healthz", timeout=1):
                    break
            except urllib.error.URLError:
                time.sleep(.05)
        while not marker.with_suffix(".pid").exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        assistant_pid = int(marker.with_suffix(".pid").read_text())
        request = urllib.request.Request(
            url + "/api/assistant", data=b'{"operation":"open"}',
            headers={"Content-Type": "application/json", "X-CGA-Bench": "1"})
        with urllib.request.urlopen(request) as response:
            self.assertTrue(json.load(response)["running"])
        def post(document):
            request = urllib.request.Request(
                url + "/api/terminal", data=json.dumps(document).encode(),
                headers={"Content-Type": "application/json", "X-CGA-Bench": "1"})
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        opened = post({"operation": "open", "session": 1})
        pid_file = self.root / "owned-shell.pid"
        post({"operation": "write", "id": opened["id"],
              "data": f"printf '%s' $$ > {shlex.quote(str(pid_file))}\r"})
        while not pid_file.exists() or not pid_file.stat().st_size:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        pid = int(pid_file.read_text())
        stopped = subprocess.run(
            [str(COLLECTION / "cga"), "bench", "stop", "--session-file", str(path)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertEqual(process.wait(timeout=10), 0)
        self.assertFalse(Path(f"/proc/{pid}").exists(), "owned terminal survived viewer shutdown")
        self.assertFalse(Path(f"/proc/{assistant_pid}").exists(),
                         "warm assistant survived viewer shutdown")
        self.assertNotIn("cgamx", json.loads(path.read_text()))
        lifecycle.stop(str(path))

    def test_bench_stop_is_workflow_local_and_allows_same_port_restart(self):
        root = self.root / "workflow"
        repository = Repository.init(root)
        self.result(1, ["cpp/example"])
        database = self.root / "results.duckdb"
        database.write_bytes(b"retained results")
        self.item["engine"]["cgasi-db"] = str(database)
        model.save(repository.current_path, self.state)
        before = repository.current_path.read_bytes()
        manifest = repository.manifest_path.read_bytes()
        environment = {**os.environ, "CGA_DIR": str(repository.cga_dir)}
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        command = [str(COLLECTION / "cga"), "bench"]

        def start():
            process = subprocess.Popen(
                [*command, "serve", "--no-services", "--no-assistant", "--port", str(port)],
                cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            def cleanup():
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
                process.stderr.close()
            self.addCleanup(cleanup)
            deadline = time.monotonic() + 10
            while True:
                self.assertIsNone(process.poll(), "bench viewer failed to start")
                self.assertLess(time.monotonic(), deadline)
                try:
                    with urllib.request.urlopen(url + "/healthz", timeout=1):
                        return process
                except urllib.error.URLError:
                    time.sleep(.05)

        def stop(*arguments):
            result = subprocess.run(
                [*command, "stop", *arguments], cwd=root, env=environment,
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")

        process = start()
        stop("--session-file", str(self.root / "other.json"))
        self.assertIsNone(process.poll(), "stop affected a different bench")
        duplicate = subprocess.run(
            [*command, "serve", "--no-services", "--no-assistant", "--port", str(port)],
            cwd=root, env=environment, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("already running", duplicate.stderr)
        editor_pid = None
        try:
            editor_runtime.executable()
        except editor_runtime.EditorError:
            pass
        else:
            request = urllib.request.Request(
                url + "/api/editor", data=b'{"session":1}',
                headers={"Content-Type": "application/json", "X-CGA-Bench": "1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                editor_pid = json.load(response)["pid"]
        stop()
        self.assertEqual(process.wait(timeout=10), 0)
        if editor_pid:
            self.assertIsNone(lifecycle.identity(editor_pid), "editor survived bench stop")
        record = repository.cga_dir / "runtime/cgabench/serve.json"
        self.assertFalse(record.exists())
        stop()
        restarted = start()
        stop()
        self.assertEqual(restarted.wait(timeout=10), 0)
        self.assertEqual(repository.current_path.read_bytes(), before)
        self.assertEqual(repository.manifest_path.read_bytes(), manifest,
                         "stop must not record a workflow command")

    def test_bench_lifecycle_refuses_reused_pid_and_reports_shutdown_timeout(self):
        path = self.root / "ownership.json"
        directory = lifecycle.runtime_directory(None, path)
        directory.mkdir(parents=True)
        record = directory / "serve.json"
        model.save(record, {"pid": os.getpid(), "identity": ["stale", "identity"]})
        with mock.patch.object(lifecycle.signal, "pidfd_send_signal") as signal_process:
            lifecycle.stop(str(path))
            signal_process.assert_not_called()
        self.assertFalse(record.exists())
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        def cleanup():
            process.terminate()
            process.wait(timeout=5)
        self.addCleanup(cleanup)
        with lifecycle.running(directory):
            with self.assertRaisesRegex(WorkflowError, "already running"):
                with lifecycle.running(directory):
                    self.fail("duplicate viewer acquired the ownership lock")
            model.save(record, {"pid": process.pid, "identity": ["wrong", "identity"]})
            with mock.patch.object(lifecycle.signal, "pidfd_send_signal") as signal_process:
                with self.assertRaisesRegex(WorkflowError, "identity changed"):
                    lifecycle.stop(str(path), timeout=0)
                signal_process.assert_not_called()
                self.assertIsNone(process.poll())
                model.save(record, {"pid": process.pid, "identity": lifecycle.identity(process.pid)})
                with self.assertRaisesRegex(WorkflowError, "shutdown is still pending"):
                    lifecycle.stop(str(path), timeout=0)
                signal_process.assert_called_once()

    def test_add_session_uses_login_identity_then_reuses_it_and_avoids_name_collisions(self):
        state = {}
        cli.execute(state, ["init", "automatic", "--mode", "query-changes"])
        path = self.root / "automatic.json"
        model.save(path, state)
        backend = server.Backend(str(path))
        with mock.patch.object(cli.getpass, "getuser", return_value="login-user") as login:
            first = backend.act({"action": "session"})["experiment"]["sessions"][0]
            self.assertEqual((first["index"], first["name"], first["user"]),
                             (1, "session-1", "login-user"))
            backend.mutate(["database", "--selection", str(self.selection),
                            "--dbdir", str(self.dbdir), "--no-advance"])
            backend.mutate(["session", "session-3", "--user", "bob"])
            third = backend.act({"action": "session"})["experiment"]["sessions"][2]
            self.assertEqual((third["index"], third["name"], third["user"]),
                             (3, "session-3-2", "login-user"))
            login.assert_called_once_with()
        saved = model.experiment(json.loads(path.read_text()))["sessions"]
        self.assertEqual(saved[1]["user"], "bob")
        self.assertEqual(len({item["submission"] for item in saved}), 3)

    def test_library_tables_pagination_stale_selection_and_real_download(self):
        cli.execute(self.state, ["catalogue", str(self.catalogue)])
        cli.execute(self.state, ["library", str(self.query_directory)])
        self.item = model.session(self.state, 1)
        page = inputs.collection(self.state, "databases", search="acme", limit=1)
        self.assertEqual(page["total"], 1)
        self.assertEqual(inputs.collection(self.state, "databases", search="' OR 1=1")["total"], 0)
        self.assertEqual(inputs.collection(self.state, "queries")["rows"][0]["id"], "cpp/example")
        with self.assertRaisesRegex(WorkflowError, "changed"):
            inputs.choose(self.state, 1, "databases", "stale", [1], "list", True)
        inputs.choose(self.state, 1, "databases", page["generation"], [1], "list", True)
        self.assertEqual(self.item["D"]["status"], "complete")
        self.assertEqual(self.item["D"]["artifact"]["archives"][0]["repository"], "acme/repo")
        with self.assertRaisesRegex(WorkflowError, "distinct"):
            query_page = inputs.collection(self.state, "queries")
            # Duplicate indices are rejected before any packing work.
            inputs.choose(self.state, 1, "queries", query_page["generation"], [1, 1], "list", True)

    def test_library_query_choice_packs_only_the_selected_row(self):
        cli.execute(self.state, ["library", str(self.query_directory)])
        page = inputs.collection(self.state, "queries")
        def pack_query(state, tool, arguments):
            self.assertEqual((tool, arguments), ("ql", ["pack"]))
            selected = json.loads(cgast.resolve(state["cgaql-selection"]).read_text())
            self.assertEqual(selected["queries"][0]["id"], "cpp/example")
            state["cgaql-pack"] = [str(self.pack)]
            return state
        with mock.patch.object(engine, "run_tool", side_effect=pack_query):
            inputs.choose(self.state, 1, "queries", page["generation"], [1], "list", True)
        self.assertEqual(model.session(self.state, 1)["Q"]["artifact"]["language"], "cpp")

    def test_catalogue_discovery_includes_supplied_link_without_scanning_external_trees(self):
        collection = self.root / "components"
        workspace = collection / "workspace"
        nested = workspace / "nested" / "metadata.sql"
        nested.parent.mkdir(parents=True)
        shutil.copyfile(self.catalogue, workspace / "metadata.sql")
        shutil.copyfile(self.catalogue, nested)
        for name in (".cga", "node_modules", "__pycache__"):
            ignored = workspace / name
            ignored.mkdir()
            shutil.copyfile(self.catalogue, ignored / "metadata.sql")
        external = self.root / "external"
        external.mkdir()
        shutil.copyfile(self.catalogue, external / "metadata.sql")
        (external / "nested").mkdir()
        shutil.copyfile(self.catalogue, external / "nested" / "metadata.sql")
        (workspace / "external-link").symlink_to(external, target_is_directory=True)
        supplied = collection / "cgadl" / "db-collection.global"
        supplied.parent.mkdir()
        supplied.symlink_to(external, target_is_directory=True)
        with mock.patch.object(engine, "COLLECTION", collection):
            result = inputs.discover_catalogues(workspace)
        self.assertEqual(result["paths"], sorted(map(str, (
            workspace / "metadata.sql", nested, supplied / "metadata.sql"))))

    def test_catalogue_discovery_surfaces_scan_errors(self):
        def fail(_root, **options):
            options["onerror"](PermissionError("catalogue directory access denied"))
        with mock.patch.object(inputs.os, "walk", side_effect=fail):
            with self.assertRaisesRegex(WorkflowError, "access denied"):
                inputs.discover_catalogues(self.root)

    def test_library_search_matches_literal_metadata_substrings(self):
        with closing(sqlite3.connect(self.catalogue)) as connection, connection:
            connection.executemany("INSERT INTO metadata VALUES (?, ?, ?, ?, ?)", [
                ("discount_100%", "literal", "cpp", None, "2.27.1"),
                ("discountX100sale", "other", "cpp", None, "2.27.1")])
        cli.execute(self.state, ["catalogue", str(self.catalogue)])
        self.assertEqual(inputs.collection(self.state, "databases", search="%")["total"], 1)
        self.assertEqual(inputs.collection(
            self.state, "databases", search="DISCOUNT_100")["total"], 1)
        self.assertEqual(inputs.collection(
            self.state, "databases", search="2.27")["total"], 3)

    def test_detail_library_preparation_is_session_local_and_preserves_existing_queries(self):
        self.accept()
        cli.execute(self.state, ["catalogue", str(self.catalogue)])
        cli.execute(self.state, ["library", str(self.query_directory)])
        shared = {key: self.state[key] for key in ("cgadl-metadata", "cgaql-index")}
        catalogue = self.root / "private.sql"
        shutil.copyfile(self.catalogue, catalogue)
        with closing(sqlite3.connect(catalogue)) as connection, connection:
            connection.execute("UPDATE metadata SET git_owner = 'private'")
        directory = self.root / "private-queries"
        directory.mkdir()
        (directory / "Private.ql").write_text(
            (self.query_directory / "Example.ql").read_text().replace("Example", "Private")
            .replace("cpp/example", "cpp/private"))
        path = self.root / "detail.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        backend.act({"action": "catalogue", "session": 1, "path": str(catalogue)})
        view = backend.act({"action": "library", "session": 1, "directory": str(directory)})
        backend.act({"action": "session", "name": "two", "user": "bob"})
        state = json.loads(path.read_text())
        self.assertEqual({key: state[key] for key in shared}, shared)
        self.assertEqual(inputs.collection(state, "databases", 1)["rows"][0]["git_owner"],
                         "private")
        self.assertEqual(inputs.collection(state, "databases", 2)["rows"][0]["git_owner"],
                         "acme")
        self.assertEqual(inputs.collection(state, "queries", 1)["rows"][0]["id"],
                         "cpp/private")
        self.assertEqual(inputs.collection(state, "queries", 2)["rows"][0]["id"],
                         "cpp/example")
        self.assertEqual(view["experiment"]["sessions"][0]["libraries"]["catalogue"],
                         str(catalogue))
        self.assertEqual(view["experiment"]["sessions"][0]["libraries"]["query_directory"],
                         str(directory))
        with mock.patch.object(pack, "_dependency", return_value=("codeql/cpp-all", "1.2.3", None)):
            backend.act({"action": "create-query", "session": 1,
                         "directory": str(self.root / "Detector"),
                         "name": "Detector", "language": "cpp"})
        state = json.loads(path.read_text())
        self.assertEqual(inputs.collection(state, "queries", 1, "list")["rows"][0]["id"],
                         "cpp/private")
        self.assertEqual(inputs.collection(state, "queries", 1, "user")["rows"][0]["id"],
                         "cpp/detector")
        with self.assertRaisesRegex(WorkflowError, "select a session"):
            backend.act({"action": "catalogue", "session": 0, "path": str(catalogue)})
        model.session(state, 2)["engine"]["cgamr-submissions"] = {"submitted": {}}
        model.save(path, state)
        with self.assertRaisesRegex(WorkflowError, "submitted sessions"):
            backend.act({"action": "library", "session": 2, "directory": str(directory)})

    def test_starter_uses_shared_pack_manifest_and_can_be_edited(self):
        directory = self.root / "new-query"
        with mock.patch.object(pack, "_dependency", return_value=("codeql/cpp-all", "1.2.3", None)):
            cli.execute(self.state, ["create-query", "--directory", str(directory),
                                     "--name", "Detector", "--language", "cpp"])
        source = inputs.query_source(self.state, 1)
        self.assertIn('codeql/cpp-all: "1.2.3"', source["manifest"])
        self.assertIn("where false", source["source"])
        self.assertTrue((directory / "README.md").is_file())
        page = inputs.collection(self.state, "queries", 1, "user")
        self.assertEqual(page["rows"][0]["id"], "cpp/detector")
        edited = source["source"].replace("where false", "where true")
        cli.execute(self.state, ["edit-query", "--source", edited])
        self.assertIn("where true", inputs.query_source(self.state, 1)["source"])
        with self.assertRaisesRegex(WorkflowError, "already exists"):
            inputs.create_query(self.state, 1, str(directory), "Detector", "cpp")

    def test_session_evidence_uses_accepted_snapshots_and_each_sessions_results(self):
        self.result(1, ["cpp/test"])
        self.item["R"]["artifact"].update(
            finding_count=1, ingestion={"jobs": [
                {"repository": "acme/repo", "finding_count": 1}]})
        cli.execute(self.state, ["session", "two", "--user", "bob"])
        model.save(self.query, {"queries": [{"id": "cpp/changed", "language": "cpp"}]})
        path = self.root / "session-evidence.json"
        model.save(path, self.state)
        sessions = server.Backend(str(path)).view()["experiment"]["sessions"]
        first, second = sessions
        self.assertEqual(first["D"]["items"], self.item["D"]["artifact"]["archives"])
        self.assertEqual(first["Q"]["items"], [{"id": "cpp/test", "language": "cpp"}])
        self.assertEqual(first["R"]["items"], [
            {"repository": "acme/repo", "finding_count": 1}])
        self.assertEqual(first["R"]["summary"], "1 findings")
        self.assertEqual(second["D"]["items"], first["D"]["items"])
        self.assertEqual(second["Q"]["items"], [])
        self.assertEqual(second["R"]["items"], [])
        self.assertEqual(second["R"]["summary"], "")

    def test_evidence_http_requires_same_origin_and_browser_header(self):
        path = self.root / "evidence-http.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(backend))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        url = f"http://127.0.0.1:{http.server_port}/api/evidence"
        headers = {"Content-Type": "application/json", "X-CGA-Bench": "1"}
        with mock.patch.object(evidence, "browse", return_value={"rows": []}) as browse:
            for invalid in (
                    {"Content-Type": "application/json"},
                    {**headers, "Origin": "http://example.org"},
                    {**headers, "Host": "example.org"}):
                request = urllib.request.Request(
                    url, data=b'{"session":1,"stage":"D"}', headers=invalid)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            browse.assert_not_called()
            request = urllib.request.Request(
                url, data=b'{"session":1,"stage":"D"}', headers=headers)
            with urllib.request.urlopen(request) as response:
                self.assertEqual(json.load(response), {"rows": []})
            self.assertEqual(browse.call_args.args[1], {"session": 1, "stage": "D"})

    def test_named_actions_hide_commands_and_require_maintenance_confirmation(self):
        path = self.root / "view.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        backend.act({"action": "catalogue", "path": str(self.catalogue)})
        self.assertTrue(backend.view()["libraries"]["databases_loaded"])
        self.assertNotIn("tool_output", json.dumps(backend.view()))
        with self.assertRaisesRegex(WorkflowError, "confirmation"):
            backend.act({"action": "infrastructure", "phase": "reset"})
        with self.assertRaisesRegex(WorkflowError, "unknown"):
            backend.act({"action": "shell", "argv": ["rm"]})

    def test_service_setup_reuses_lifecycle_phases_and_preserves_restart_state(self):
        actions = []
        def run(state, tool, arguments):
            actions.extend(arguments)
            result = copy.deepcopy(state)
            result["cgamx"] = {"last_phase": arguments[0], "work_dir": str(self.root / "runtime")}
            return result
        with mock.patch.object(services, "ready", return_value=False), \
                mock.patch.object(engine, "run_tool", side_effect=run):
            services.run(self.state, "setup")
            self.assertEqual(actions, ["preflight", "reset", "build", "start"])
            actions.clear()
            services.run(self.state, "setup")
            self.assertEqual(actions, ["preflight", "build", "start"])

    def test_blocked_reference_and_inherited_sessions_and_column_addresses(self):
        cli.execute(self.state, ["advance"])
        self.assertEqual(self.item["D"]["status"], "blocked")
        self.assertEqual(self.item["Q"]["status"], "empty")
        with self.assertRaisesRegex(WorkflowError, "before cloning"):
            cli.execute(self.state, ["session", "two", "--user", "bob"])
        self.assertEqual(len(model.experiment(self.state)["sessions"]), 1)
        self.accept()
        cli.execute(self.state, ["session", "two", "--user", "bob"])
        self.assertEqual(len(model.experiment(self.state)["sessions"]), 2)
        self.assertEqual(model.session(self.state, 2)["D"]["cloned_from"]["session"], 1)
        self.assertIsNone(model.session(self.state, 2)["Q"]["artifact"])
        self.assertIsNone(model.session(self.state, 2)["J"]["artifact"])
        self.assertIsNone(model.session(self.state, 2)["R"]["artifact"])
        self.assertIs(model.address(model.experiment(self.state), "E.D[1]"), self.item["D"])
        self.assertIs(model.address(model.experiment(self.state), "E.S[1].Q"), self.item["Q"])
        with self.assertRaises(WorkflowError):
            model.address(model.experiment(self.state), "E.S[0].Q")
        self.assertEqual(self.state["unrelated"], {"preserve": True})

    def test_acceptance_snapshots_inputs_and_rejects_changed_databases(self):
        self.accept()
        self.query.write_text("{}")
        self.pack.write_bytes(b"changed")
        self.assertEqual(cgast.resolve(self.item["Q"]["artifact"]["cgaql-pack"][0]).read_bytes(),
                         b"test query pack")
        self.archive.write_bytes(b"changed database")
        with mock.patch.object(engine, "run_tool") as run:
            with self.assertRaisesRegex(WorkflowError, "database archive changed"):
                cli.execute(self.state, ["advance"])
            run.assert_not_called()

    def test_empty_and_mixed_language_inputs_are_rejected(self):
        model.save(self.selection, {"databases": []})
        with self.assertRaisesRegex(WorkflowError, "nonempty"):
            self.accept()
        model.save(self.selection, {"databases": [
            {"git_owner": "../escape", "git_repo": "repo", "primary_language": "cpp"}]})
        with self.assertRaisesRegex(WorkflowError, "safe"):
            self.accept()
        model.save(self.query, {"queries": [{"language": "cpp"}, {"language": "python"}]})
        with self.assertRaisesRegex(WorkflowError, "one language"):
            model.accept_query(self.state, self.item, str(self.query), str(self.pack), 0, "user")

    def test_chosen_pack_matches_its_query_row(self):
        second = self.root / "second.tgz"
        second.write_bytes(b"second")
        model.save(self.query, {"queries": [
            {"id": "one", "language": "cpp"}, {"id": "two", "language": "cpp"}]})
        self.state.update({"cgaql-selection": str(self.query),
                           "cgaql-pack": [str(self.pack), str(second)]})
        model.accept_query(self.state, self.item, None, None, 1, "list")
        artifact = self.item["Q"]["artifact"]
        document = json.loads(cgast.resolve(artifact["cgaql-selection"]).read_text())
        self.assertEqual(document["queries"][0]["id"], "two")
        self.assertEqual(cgast.resolve(artifact["cgaql-pack"][0]).read_bytes(), b"second")

    def test_comparison_multisets_defaults_and_immutable_evidence(self):
        self.accept()
        cli.execute(self.state, ["session", "two", "--user", "bob"])
        cli.execute(self.state, ["session", "unfinished", "--user", "eve"])
        self.result(1, ["common", "common", "old"])
        self.result(2, ["common", "new"])
        document = compare.compare(self.state, [])
        self.assertEqual(len(document["common"]), 1)
        self.assertEqual(len(document["sessions"][1]["added"]), 1)
        self.assertEqual(len(document["sessions"][1]["removed"]), 2)
        self.assertEqual(document["common"][0]["provenance"]["result_index"], 0)
        self.assertEqual(document["sessions"][1]["removed"][0]["provenance"]["result_index"], 1)
        self.assertEqual(len(document["inputs"]), 2)
        with self.assertRaises(WorkflowError):
            compare.compare(self.state, [1, 3])
        self.result(2, [])
        self.assertEqual(len(compare.compare(self.state, [1, 2])["sessions"][1]["removed"]), 3)
        path = cgast.resolve(model.session(self.state, 2)["R"]["artifact"]["results"])
        path.write_text('{"findings": []}\n')
        with self.assertRaisesRegex(WorkflowError, "evidence changed"):
            compare.compare(self.state, [1, 2])

    def test_sarif_index_locations_and_empty_results(self):
        path = self.root / "input.sarif"
        payload = sarif(["test"])
        run = payload["runs"][0]
        run["artifacts"] = [{"location": {"uri": "indexed.c"}}]
        result = run["results"][0]
        result.pop("ruleId")
        result["ruleIndex"] = 0
        result["locations"][0]["physicalLocation"]["artifactLocation"] = {"index": 0}
        model.save(path, payload)
        state = {"cgasi-ingestions": {"name": {"jobs": [
            {"repository": "acme/repo", "artifacts": {"sarif": str(path)}}]}}}
        findings = compare.findings(state, "name")
        self.assertEqual(findings[0]["identity"]["rule"], "test")
        self.assertEqual(findings[0]["identity"]["locations"][0]["uri"], "indexed.c")
        model.save(path, sarif([]))
        self.assertEqual(compare.findings(state, "name"), [])

    def test_workspace_selection_invalidates_stale_pack_and_keeps_accepted_inputs(self):
        self.accept()
        accepted = copy.deepcopy(self.item["Q"])
        self.item["workspace"]["cgaql-pack"] = ["old"]
        def run(state, tool, arguments, **kwargs):
            self.assertNotIn("cgaql-pack", state)
            return state
        with mock.patch.object(engine, "run_tool", side_effect=run):
            engine.tool(self.item, "Q", ["--", "ql", "select", "id", "new"])
        self.assertEqual(self.item["Q"], {
            **accepted, "history": accepted["history"] + [self.item["Q"]["history"][-1]]})
        with self.assertRaises(WorkflowError):
            engine.tool(self.item, "Q", ["ql", "clean"])

    def test_failed_status_can_resume_from_previous_workflow_state_without_resubmit(self):
        self.accept()
        previous = copy.deepcopy(self.state)
        count = {"submit": 0}
        def run(state, tool, arguments, **kwargs):
            if arguments[0] == "submit":
                count["submit"] += 1
                state["cgamr-submissions"] = {
                    self.item["submission"]: {"status": "submitted", "session_id": 10}}
                return state
            raise WorkflowError("network unavailable")
        with mock.patch.object(engine, "run_tool", side_effect=run):
            with self.assertRaisesRegex(WorkflowError, "network unavailable"):
                cli.execute(self.state, ["advance"])
            with self.assertRaises(WorkflowError):
                cli.execute(previous, ["advance"])
        self.assertEqual(count["submit"], 1)
        self.assertEqual(model.projection(previous)["sessions"][0]["J"]["status"], "failed")
        with self.assertRaisesRegex(WorkflowError, "evidence"):
            model.accept_query(previous, model.session(previous, 1),
                               str(self.query), str(self.pack), 0, "user")

    def test_uncertain_submit_is_not_retried(self):
        self.accept()
        with mock.patch.object(engine, "run_tool", side_effect=WorkflowError("lost response")) as run:
            with self.assertRaises(WorkflowError):
                cli.execute(self.state, ["advance"])
            with self.assertRaisesRegex(WorkflowError, "uncertain"):
                cli.execute(self.state, ["advance"])
            self.assertEqual(run.call_count, 1)

    def test_partial_download_retries_and_orders_results_for_ingestion(self):
        self.accept()
        name = self.item["submission"]
        first = self.root / "acme-repo.zip"
        second = self.root / "acme-other.zip"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        self.item["engine"] = {"cgamr-submissions": {name: {
            "status": "succeeded", "session_id": 1,
            "repositories": ["acme/repo", "acme/other"], "downloads": [str(first)]}}}
        model.checkpoint(self.item)
        called = []
        def run(state, tool, arguments, **kwargs):
            called.append(arguments[0])
            if arguments[0] == "download":
                state["cgamr-submissions"][name]["downloads"] = [str(second), str(first)]
            if arguments[0] == "ingest":
                self.assertEqual(state["cgamr-submissions"][name]["downloads"],
                                 [str(first), str(second)])
                state["cgasi-ingestions"] = {name: {"jobs": [], "finding_count": 0}}
            return state
        with mock.patch.object(engine, "run_tool", side_effect=run), \
                mock.patch.object(compare, "findings", return_value=[]):
            cli.execute(self.state, ["advance"])
        self.assertEqual(called, ["status", "download", "verify", "ingest"])
        self.assertEqual(self.item["R"]["status"], "complete")

    def test_sysview_frame_policy_is_scoped_to_configured_origin(self):
        path = self.root / "frames.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        with mock.patch.dict(os.environ, {"CGA_MRVA_SERVER": "https://mrva.example:9443/base"}):
            http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(backend))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        with urllib.request.urlopen(f"http://127.0.0.1:{http.server_port}/") as response:
            policy = response.headers["Content-Security-Policy"]
        directives = dict(part.strip().split(" ", 1) for part in policy.split(";") if part.strip())
        self.assertEqual(directives["frame-src"], "'self' https://mrva.example:9443")
        self.assertEqual(directives["default-src"], "'self'")
        self.assertEqual(directives["frame-ancestors"], "'none'")
        self.assertEqual(directives["form-action"], "'self' http://127.0.0.1:*")
        for origin in ["https://mrva.invalid; frame-src *", "http://user:pass@mrva.invalid",
                       "ftp://mrva.invalid", "http://mrva.invalid:99999"]:
            with self.subTest(origin=origin), mock.patch.dict(
                    os.environ, {"CGA_MRVA_SERVER": origin}), self.assertRaises(WorkflowError):
                server.handler(backend)

    def test_raw_http_mutations_persist_and_reject_cross_origin(self):
        self.accept()
        path = self.root / "session.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(backend))
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        url = f"http://127.0.0.1:{http.server_port}"
        with urllib.request.urlopen(url + "/api/catalogues") as response:
            self.assertIn(str(self.catalogue), json.load(response)["paths"])
        with urllib.request.urlopen(url + "/api/llm") as response:
            self.assertEqual(json.load(response)["catalogues"], "/api/catalogues")
        request = urllib.request.Request(
            url + "/api/command", data=json.dumps({
                "argv": ["session", "two", "--user", "bob"]}).encode(),
            headers={"X-CGA-Bench": "1", "Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(len(json.load(response)["experiment"]["sessions"]), 2)
        self.assertEqual(len(model.experiment(json.loads(path.read_text()))["sessions"]), 2)
        request.add_header("Origin", "http://evil.invalid")
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        with self.assertRaises(WorkflowError):
            backend.mutate(["serve"])


@unittest.skipUnless(shutil.which("duckdb") and shutil.which("sqlite3"),
                     "SARIF ingestion requires DuckDB and SQLite CLIs")
class IntegrationTest(Fixtures):
    def test_evidence_previews_and_sql_are_capped_read_only_and_session_scoped(self):
        databases = []
        for index in range(35):
            repo = f"repo-{index:02}"
            archive = self.dbdir / "acme" / repo / f"acme_{repo}_db.zip"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(f"database-{index}".encode())
            databases.append({"git_owner": "acme", "git_repo": repo, "primary_language": "cpp"})
        model.save(self.selection, {"databases": databases})
        model.save(self.query, {"queries": [
            {"id": f"cpp/query-{index:02}", "language": "cpp"} for index in range(35)]})
        self.result(1, ["cpp/test"] * 35)
        self.item["R"]["artifact"].update(
            finding_count=35, ingestion={"jobs": [
                {"repository": f"acme/repo-{index:02}", "finding_count": 1}
                for index in range(35)]})
        cli.execute(self.state, ["session", "two", "--user", "bob"])
        model.save(self.query, {"queries": [{"id": "cpp/other", "language": "cpp"}]})
        cli.execute(self.state, [
            "query", "--session", "2", "--selection", str(self.query),
            "--pack", str(self.pack), "--no-advance"])
        path = self.root / "evidence.json"
        model.save(path, self.state)
        before = copy.deepcopy(self.state)
        first = server.Backend(str(path)).view()["experiment"]["sessions"][0]
        for stage, table in (("D", "databases"), ("Q", "queries"), ("R", "result_summaries")):
            with self.subTest(stage=stage):
                self.assertEqual((first[stage]["item_count"], len(first[stage]["items"])), (35, 1))
                page = evidence.browse(self.state, {"session": 1, "stage": stage})
                self.assertEqual((page["total"], len(page["rows"]), page["has_more"]), (35, 30, True))
                last = evidence.browse(self.state, {"session": 1, "stage": stage, "offset": 30})
                self.assertEqual((len(last["rows"]), last["has_more"]), (5, False))
                self.assertEqual(last["rows"][0]["ordinal"], 31)
                grouped = evidence.browse(self.state, {"session": 1, "stage": stage,
                    "sql": f"WITH source AS (SELECT * FROM {table}) SELECT count(*) AS n FROM source"})
                self.assertEqual(grouped["rows"], [{"n": 35}])
                empty = evidence.browse(self.state, {"session": 1, "stage": stage,
                    "sql": f"SELECT ordinal FROM {table} WHERE false"})
                self.assertEqual((empty["columns"], empty["rows"]), (["ordinal"], []))
        second = evidence.browse(self.state, {"session": 2, "stage": "Q"})
        self.assertEqual((second["total"], second["rows"][0]["id"]), (1, "cpp/other"))
        empty = evidence.browse(self.state, {"session": 2, "stage": "R"})
        self.assertEqual((empty["total"], empty["rows"]), (0, []))
        for sql in ("DELETE FROM queries", "SELECT 1; SELECT 2",
                    "SELECT * FROM read_text('/etc/passwd')"):
            with self.subTest(sql=sql), self.assertRaises(WorkflowError):
                evidence.browse(self.state, {"session": 1, "stage": "Q", "sql": sql})
        for document in ({"session": True, "stage": "D"}, {"session": 1, "stage": "J"},
                         {"session": 1, "stage": ["D"]}, {"session": 1, "stage": "D", "limit": 101}):
            with self.subTest(document=document), self.assertRaises(WorkflowError):
                evidence.browse(self.state, document)
        self.assertEqual(self.state, before)
        cgast.resolve(self.item["Q"]["artifact"]["cgaql-selection"]).write_text("{}")
        with self.assertRaisesRegex(WorkflowError, "snapshot has changed"):
            evidence.browse(self.state, {"session": 1, "stage": "Q"})

    def test_results_exact_filters_sql_and_read_only_session_isolation(self):
        self.ingested_result(1, ["cpp/one", "cpp/one", "cpp/two", "literal_%'"])
        cli.execute(self.state, ["session", "two", "--user", "alice"])
        self.ingested_result(2, ["cpp/other"])
        before = copy.deepcopy(self.state)
        database = cgast.get_path(self.item["engine"], "cgasi-db")
        digest = model.fingerprint(database)
        first = results.browse(self.state, {"session": 1, "limit": 2})
        self.assertEqual((first["total"], len(first["rows"]), first["has_more"]), (4, 2, True))
        self.assertTrue(all(row["repository"] == "acme/repo-1" for row in first["rows"]))
        self.assertTrue(Path(first["repositories"][0]["sqlite"]).is_file())
        second = results.browse(self.state, {"session": 1, "offset": 2, "limit": 2})
        self.assertFalse(second["has_more"])
        exact = results.browse(self.state, {"session": 1, "filters": {
            "rule_id": "cpp/one", "uri": "source.c", "start_line": "7"}})
        self.assertEqual(exact["total"], 2)
        literal = results.browse(self.state, {"session": 1, "filters": {
            "rule_id": "literal_%'"}})
        self.assertEqual(literal["total"], 1)
        self.assertEqual(results.browse(self.state, {"session": 1, "filters": {
            "rule_id": "cpp/"}})["total"], 0)
        self.assertEqual(results.browse(self.state, {"session": 2})["total"], 1)
        grouped = results.browse(self.state, {"session": 1, "sql":
            "WITH counts AS (SELECT rule_id, count(*) AS n FROM sarif_results "
            "GROUP BY rule_id) SELECT * FROM counts ORDER BY n DESC; -- trailing comment"})
        self.assertEqual(grouped["columns"], ["rule_id", "n"])
        self.assertEqual(grouped["rows"][0], {"rule_id": "cpp/one", "n": 2})
        self.assertEqual(results.browse(self.state, {"session": 1, "sql":
            "SELECT 'a;b' AS message WHERE false;"})["columns"], ["message"])
        denied = [
            "DELETE FROM sarif_results",
            "SELECT 1; SELECT 2",
            "SELECT 1; ATTACH '/tmp/bench-side-effect.duckdb' AS other",
            "COPY sarif_results TO '/tmp/bench-side-effect.csv'",
            "SELECT * FROM read_text('/etc/passwd')",
            "SELECT * FROM read_csv('https://example.invalid/data.csv')",
            "SELECT * FROM sqlite_scan('/etc/passwd', 'sarif_results')",
        ]
        for sql in denied:
            with self.subTest(sql=sql), self.assertRaises(WorkflowError):
                results.browse(self.state, {"session": 1, "sql": sql})
        for document in ({"session": True}, {"session": 1, "offset": -1},
                         {"session": 1, "limit": 101},
                         {"session": 1, "filters": {"unknown": "x"}},
                         {"session": 1, "filters": {"kind": "problem"}, "sql": "SELECT 1"}):
            with self.subTest(document=document), self.assertRaises(WorkflowError):
                results.browse(self.state, document)
        self.assertEqual(self.state, before)
        self.assertEqual(model.fingerprint(database), digest)
        Path(self.item["R"]["artifact"]["results"]).write_text("{}")
        with self.assertRaisesRegex(WorkflowError, "snapshot has changed"):
            results.browse(self.state, {"session": 1})

    def test_empty_results_and_persistent_query_terminal_on_completed_cell(self):
        self.ingested_result(1, [])
        page = results.browse(self.state, {"session": 1})
        self.assertEqual((page["total"], page["rows"], page["finding_count"]), (0, [], 0))
        self.assertIn("message", page["columns"])
        path = self.root / "query-terminal.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        before = path.read_bytes()
        environment, marker = self.terminal_environment()
        with mock.patch.dict(os.environ, environment):
            opened = backend.terminal_action(
                {"operation": "open", "session": 1, "stage": "R"}, 8610)
            self.assertTrue(opened["running"])
            self.assertEqual(opened["stage"], "R")
            self.assertIn("copilot-assist-sarif-query.md", opened["command"])
            self.assertIn("--yolo", opened["command"])
            self.assertEqual(opened["database"], page["database"])
            reopened = backend.terminal_action(
                {"operation": "open", "session": 1, "stage": "R"}, 8610)
            self.assertEqual(reopened["id"], opened["id"])
            backend.terminal_action({"operation": "insert", "id": opened["id"]}, 8610)
            time.sleep(.1)
            self.assertFalse(marker.exists())
            with self.assertRaisesRegex(WorkflowError, "submitted sessions"):
                backend.terminal_action({"operation": "open", "session": 1, "stage": "D"}, 8610)
            with self.assertRaisesRegex(WorkflowError, "only for D or R"):
                backend.terminal_action({"operation": "open", "session": 1, "stage": "Q"}, 8610)
        self.assertEqual(path.read_bytes(), before)
        cli.execute(self.state, ["session", "waiting"])
        with self.assertRaisesRegex(WorkflowError, "results are not complete"):
            results.browse(self.state, {"session": 2})

    def test_results_http_endpoint_guards_and_query_errors(self):
        self.ingested_result(1, ["cpp/example"])
        path = self.root / "results-http.json"
        model.save(path, self.state)
        backend = server.Backend(str(path))
        self.addCleanup(backend.close)
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(backend))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        url = f"http://127.0.0.1:{http.server_port}"
        before = path.read_bytes()
        request = urllib.request.Request(url + "/api/results",
            data=json.dumps({"session": 1, "sql": "SELECT count(*) AS n FROM sarif_results"}).encode(),
            headers={"Content-Type": "application/json", "X-CGA-Bench": "1"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(json.load(response)["rows"], [{"n": 1}])
        request.data = json.dumps({"session": 1, "sql": "DROP TABLE sarif_results"}).encode()
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 400)
        self.assertIn("SELECT", json.load(error.exception)["error"])
        error.exception.close()
        request.add_header("Origin", "http://evil.invalid")
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.assertEqual(path.read_bytes(), before)

    def test_real_components_workflow_resume_compare_and_browser_mutation(self):
        calls = {"submit": 0, "status_fail": True, "ready": False}
        payloads = [["common", "old"], ["common", "new"]]

        class MRVA(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def response(self, status, value):
                data = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.assert_request = request
                calls["submit"] += 1
                self.response(200, {"id": calls["submit"], "status": "submitted"})

            def do_GET(self):
                if self.path.startswith("/artifact/"):
                    index = int(self.path.rsplit("/", 1)[-1]) - 1
                    stream = io.BytesIO()
                    with zipfile.ZipFile(stream, "w") as archive:
                        archive.writestr("results.sarif", json.dumps(sarif(payloads[index])))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(stream.getvalue())
                    return
                if "/repos/acme/repo" in self.path:
                    index = self.path.split("/variant-analyses/")[1].split("/")[0]
                    self.response(200, {"artifact_url": f"/artifact/{index}"})
                    return
                if calls["status_fail"]:
                    calls["status_fail"] = False
                    self.response(503, {"error": "temporary status failure"})
                    return
                status = "succeeded" if calls["ready"] else "in_progress"
                self.response(200, {"status": status, "scanned_repositories": [{
                    "repository": {"full_name": "acme/repo"},
                    "analysis_status": status, "result_count": 2}]})

        http = ThreadingHTTPServer(("127.0.0.1", 0), MRVA)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        url = f"http://127.0.0.1:{http.server_port}"
        root = self.root / "workflow"
        repository = Repository.init(root)
        repository.start_chain()
        environment = {**os.environ, "CGA_DIR": str(repository.cga_dir)}
        dispatcher = COLLECTION / "cga"

        def cga(*args, expected=0):
            proc = subprocess.run([str(dispatcher), *args], cwd=root, env=environment,
                                  text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(proc.returncode, expected, proc.stderr)
            return proc

        cga("bench", "init", "integration", "--mode", "query-changes")
        cga("bench", "session", "one", "--user", "alice", "--server", url)
        cga("bench", "database", "--selection", str(self.selection),
            "--dbdir", str(self.dbdir))
        # Query acceptance submits automatically. A failed status must not cause
        # a second submission when the pre-query workflow state is resumed.
        cga("bench", "query", "--selection", str(self.query),
            "--pack", str(self.pack), expected=2)
        self.assertEqual(calls["submit"], 1)
        cga("bench", "advance")
        self.assertEqual(calls["submit"], 1)
        state = json.loads(repository.current_path.read_text())
        self.assertEqual(model.session(state, 1)["J"]["status"], "running")
        calls["ready"] = True
        cga("bench", "advance")
        state = json.loads(repository.current_path.read_text())
        self.assertEqual(model.session(state, 1)["R"]["artifact"]["finding_count"], 2)
        cga("bench", "advance")
        self.assertEqual(calls["submit"], 1)
        frozen = copy.deepcopy(model.session(state, 1))
        with mock.patch.dict(os.environ, {"CGA_DIR": str(repository.cga_dir)}):
            backend = server.Backend(None)
            backend.mutate(["session", "two", "--user", "bob", "--server", url])
            backend.mutate(["query", "--selection", str(self.query),
                            "--pack", str(self.pack)])
            backend.mutate(["compare"])
            added = backend.act({"action": "session"})["experiment"]["sessions"][2]
            self.assertEqual((added["index"], added["name"], added["user"]),
                             (3, "session-3", "alice"))
            backend.mutate(["clone", "--session", "3", "--stage", "D",
                            "--from-session", "2", "--no-advance"])
            with self.assertRaisesRegex(WorkflowError, "fixed"):
                backend.act({"action": "catalogue", "session": 3,
                             "source": "user", "path": str(self.catalogue)})
            prepared = backend.view()
            self.assertEqual(prepared["experiment"]["sessions"][2]["D"]["status"], "complete")
            self.assertEqual(prepared["experiment"]["sessions"][2]["D"]["cloned_from"]["session"], 2)
            view = backend.read()
        self.assertEqual(calls["submit"], 2)
        self.assertEqual(len(view["comparison"]["common"]), 1)
        self.assertEqual(len(view["comparison"]["sessions"][1]["added"]), 1)
        self.assertEqual(len(view["comparison"]["sessions"][1]["removed"]), 1)
        state = json.loads(repository.current_path.read_text())
        self.assertEqual(model.session(state, 1), frozen)
        self.assertEqual(len(repository.load_manifest()["attempts"]), 2)
        self.assertTrue(any(artifact["kind"] == "results"
                            for artifact in repository.load_manifest()["artifacts"].values()))


if __name__ == "__main__":
    unittest.main()

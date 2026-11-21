from __future__ import annotations

import base64
import copy
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request

COLLECTION = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(COLLECTION / name) for name in (
    "cgalib", "cgawf", "cgauv", "cgabench", "cgadl", "cgaql", "cgasi")]
sys.path[:0] = [str(COLLECTION / "cgacc" / "lib"), str(COLLECTION / "lib")]
sys.path.insert(0, str(COLLECTION / "tests"))

from cgabench import model
from cgabench.server import Backend, handler
from cgauv.server import Handler
from cgawf.repository import Repository, WorkflowError
from cgawf.tags import normalize
from vid import MissingObject, RawRepository, Space
from vid_http import Inspector
from vid_registry import reference
from gateway_fixture import start_gateway


class VidTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = Repository.init(self.root / "workflow", "../objects")
        self.chain = self.repository.start_chain(name="main")
        self.environment = mock.patch.dict(os.environ, {
            "CGA_DIR": str(self.repository.cga_dir),
            "CGAST_ROOT": str(self.root), "CGAST_TMPDIR": str(self.root / "scratch"),
            "SHELL": "/bin/sh",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.state = {}
        model.init(self.state, "test", "query-changes")
        model.add(self.state, "reference", "alice", None)

    def record(self, state=None, tags=None):
        with self.repository.locked():
            manifest = self.repository.load_manifest()
            _, chain = self.repository.resolve_chain(manifest, self.chain)
            return self.repository.record_state(
                manifest, self.chain, chain, self.state if state is None else state,
                ["cga", "bench", "session"], "test", tags=normalize(tags or []))

    def test_comma_lisp_and_qualified_references_are_equivalent(self):
        self.record()
        space = Space(self.repository)
        value = space.inspect(":f3a,1,J")
        self.assertEqual(value, space.inspect("(:f3a 1 :J)"))
        self.assertEqual(value, space.inspect(":f3a,01,J"))
        self.assertEqual(value, space.inspect(value["qualified_ref"]))
        self.assertEqual(value, space.inspect(value["pinned_ref"]))
        self.assertEqual(value["context"]["experiment"], self.state["cgabench-experiment"]["id"])
        for bad in (":8x1p", ":f3a,0", ":f3a,1,X", ":f3a,,1", "(:f3a 1", ":f3a,1,J,1,2"):
            with self.subTest(bad=bad), self.assertRaises(WorkflowError):
                space.inspect(bad)

    def test_offline_help_references_are_not_workflow_objects(self):
        self.record()
        space = Space(self.repository)
        for ref in (":nrs", reference("help-pages", "help", "bash-tutorial-sql")):
            with self.subTest(ref=ref), self.assertRaisesRegex(WorkflowError, "offline help"):
                space.inspect(ref)

    def test_facts_accumulate_without_changing_existing_facts_or_evidence(self):
        first = self.record()
        old_space = Space(self.repository)
        old = old_space.inspect(":f3a,1,J")
        manifest_before = self.repository.manifest_path.read_bytes()
        self.assertEqual(manifest_before, self.repository.manifest_path.read_bytes())
        self.state["cgabench-experiment"]["sessions"][0]["J"]["status"] = "running"
        second = self.record()
        current = Space(self.repository).inspect(":f3a,1,J")
        self.assertEqual(current["facts"][:-1], old["facts"])
        self.assertEqual(current["properties"]["status"], "running")
        self.assertEqual(Space(self.repository).inspect(old["pinned_ref"]), old)
        manifest = self.repository.load_manifest()
        self.assertEqual(self.repository.load_state(manifest["nodes"][first]["state"])[
            "cgabench-experiment"]["sessions"][0]["J"]["status"], old["properties"]["status"])
        self.assertEqual(current["context"]["node"], second)

    def test_branch_qualification_does_not_follow_active_chain(self):
        origin = self.record()
        original = Space(self.repository).inspect(":f3a,1,J")
        branch = self.repository.start_chain(from_revision=origin, name="branch")
        self.chain = branch
        self.state["cgabench-experiment"]["sessions"][0]["J"]["status"] = "running"
        self.record()
        space = Space(self.repository)
        self.assertEqual(space.inspect(original["qualified_ref"]), original)
        self.assertEqual(space.inspect(":f3a,1,J")["properties"]["status"], "running")
        unrelated = self.repository.start_chain(name="other")
        self.chain = unrelated
        other = {}
        model.init(other, "other", "query-changes")
        model.add(other, "new-reference", "bob", None)
        self.record(other)
        self.assertEqual(Space(self.repository).inspect(original["pinned_ref"]), original)
        wrong = original["qualified_ref"].replace(
            original["context"]["experiment"], other["cgabench-experiment"]["id"])
        with self.assertRaisesRegex(WorkflowError, "different experiment"):
            Space(self.repository).inspect(wrong)

    def test_indexed_rows_resolve_retained_generation_not_reordered_live_files(self):
        path = self.root / "metadata.sql"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE metadata (git_owner TEXT, git_repo TEXT)")
            connection.executemany("INSERT INTO metadata VALUES (?,?)",
                                   [("owner", "one"), ("owner", "two")])
        self.state["cgadl-metadata"] = str(path)
        self.record()
        from cgabench.inputs import collection
        page = collection(self.state, "databases", search="two")
        row = page["rows"][0]
        self.assertEqual(row["_row"], 2)
        old = Space(self.repository).inspect(row["vid"])
        path.unlink()
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE metadata (git_owner TEXT, git_repo TEXT)")
            connection.execute("INSERT INTO metadata VALUES ('new','different')")
        resolved = Space(self.repository).inspect(row["vid"])
        self.assertEqual(old, resolved)
        self.assertEqual(resolved["properties"]["git_repo"], "two")

    def test_stage_relations_and_jobs_use_accepted_repository_order(self):
        item = self.state["cgabench-experiment"]["sessions"][0]
        item["D"]["artifact"] = {"archives": [
            {"repository": "acme/z"}, {"repository": "acme/a"}]}
        item["engine"]["cgamr-submissions"] = {item["submission"]: {
            "session_id": 42, "status": "in_progress", "status_response": {
                "scanned_repositories": [
                    {"repository": {"full_name": "acme/a"}, "analysis_status": "complete"},
                    {"repository": {"full_name": "acme/z"}, "analysis_status": "in_progress"}]}}}
        self.record()
        space = Space(self.repository)
        job = space.inspect(":f3a,1,J,1")
        self.assertEqual(job["properties"]["repository"], "acme/z")
        self.assertEqual(job["properties"]["status"]["analysis_status"], "in_progress")
        relations = space.inspect(":f3a,1,J")["relations"]
        self.assertIn(("query", ":f3a,1,Q"),
                      [(row["relation"], row["ref"]) for row in relations])
        self.assertIn(("contains", ":f3a,1,J,2"),
                      [(row["relation"], row["ref"]) for row in relations])
        control = space.inspect(":p9g,1")
        self.assertEqual(control["properties"]["target"], ":f3a,1")

    def test_late_objects_and_other_workflows_do_not_retarget_references(self):
        first = self.record()
        second = self.record()
        with self.assertRaisesRegex(WorkflowError, "no recorded facts"):
            Space(self.repository).inspect(":h7m,2", at=first)
        other = Repository.init(self.root / "other")
        with self.assertRaisesRegex(WorkflowError, "different workflow"):
            Space(other).inspect(Space(self.repository).inspect(":h7m,2")["qualified_ref"])
        self.assertEqual(Space(self.repository).inspect(":h7m,2")[
            "properties"]["id"], second)

    def test_secret_objects_are_not_exposed_by_vid_inspection(self):
        self.record(tags=["sensitivity:secret"])
        with self.assertRaisesRegex(WorkflowError, "sensitivity:secret"):
            Space(self.repository).inspect(":h7m,1")
        with self.assertRaisesRegex(WorkflowError, "sensitivity:secret"):
            Space(self.repository).inspect(":f3a,1,J")
        self.assertEqual(Space(self.repository).inspect(":h7m")["relations"], [])

    def test_metadata_frontier_pins_attempts_and_manual_artifacts_without_a_new_node(self):
        self.record()
        before = Space(self.repository).inspect(":r6t")
        file = self.root / "evidence.txt"
        file.write_text("immutable evidence")
        with self.repository.locked():
            manifest = self.repository.load_manifest()
            self.repository.record_attempt(
                manifest, self.chain, ["cga", "bench", "advance"], "test", {})
            self.repository.register_artifact(manifest, file, "manual", "text", None)
            self.repository.write_manifest(manifest)
        space = Space(self.repository)
        self.assertEqual(space.inspect(before["pinned_ref"]), before)
        self.assertEqual(space.inspect(":r6t,1")["properties"]["chain"], self.chain)
        self.assertEqual(space.inspect(":91c,1")["properties"]["logical_name"], "manual")
        for ref in (":r6t,1", ":91c,1"):
            with self.subTest(ref=ref), self.assertRaises(MissingObject):
                space.inspect(ref, at=before["context"]["frontier"])
        original = space.inspect(":r6t,1")
        self.repository.start_chain(name="other")
        with self.assertRaises(MissingObject):
            Space(self.repository).inspect(":r6t,1")
        self.assertEqual(Space(self.repository).inspect(original["pinned_ref"]), original)

    def test_raw_sessions_append_observations_without_changing_source_file(self):
        path = self.root / "raw.json"
        model.save(path, self.state)
        inspector = Inspector(session_file=path)
        self.addCleanup(inspector.close)
        source_before = path.read_bytes()
        old = Space(inspector.repository).inspect(":f3a,1,J")
        self.assertEqual(source_before, path.read_bytes())
        state = copy.deepcopy(self.state)
        state["cgabench-experiment"]["sessions"][0]["J"]["status"] = "running"
        inspector.observe(state)
        current = Space(inspector.repository).inspect(":f3a,1,J")
        self.assertEqual(current["facts"][:-1], old["facts"])
        self.assertEqual(Space(RawRepository(path)).inspect(old["pinned_ref"]), old)
        self.assertEqual(source_before, path.read_bytes())
        path.unlink()
        mime, content = inspector.get("/api/vid", {"ref": [old["pinned_ref"]]})
        self.assertEqual(mime, "application/json")
        self.assertEqual(json.loads(content), old)
        result = subprocess.run(
            [COLLECTION / "cga", "show", old["pinned_ref"], "--json"],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), old)

    def test_cli_show_related_and_open_use_the_shared_resolver(self):
        self.record()
        for command in ("show", "related"):
            result = subprocess.run(
                [COLLECTION / "cga", command, ":f3a,1,J", "--json"],
                text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            expected = Space(self.repository).inspect(":f3a,1,J")
            self.assertEqual(value, expected if command == "show" else expected["relations"])
        opened = subprocess.run(
            [COLLECTION / "cga", "open", ":f3a,1,J", "--url", "http://127.0.0.1:9999",
             "--print-url"], text=True, capture_output=True, timeout=15)
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.assertTrue(opened.stdout.startswith("http://127.0.0.1:9999/vid?ref="))

    def test_raw_relative_artifacts_use_the_cgast_collection_root(self):
        collection = self.root / "collection"
        collection.mkdir()
        metadata = collection / "metadata.sql"
        with sqlite3.connect(metadata) as connection:
            connection.execute("CREATE TABLE metadata (git_repo TEXT)")
            connection.execute("INSERT INTO metadata VALUES ('retained')")
        self.state["cgadl-metadata"] = "metadata.sql"
        source = self.root / "raw-relative.json"
        model.save(source, self.state)
        with mock.patch.dict(os.environ, {"CGAST_ROOT": "", "CGA_ROOT": ""}), \
                mock.patch("vid.cga_root", return_value=collection):
            inspector = Inspector(session_file=source)
        self.addCleanup(inspector.close)
        ref = reference("databases", "g" + model.fingerprint(metadata), 1)
        self.assertEqual(Space(inspector.repository).inspect(ref)["properties"][
            "git_repo"], "retained")

    def test_cli_registry_and_completion_discover_the_same_roots_without_a_workflow(self):
        result = subprocess.run(
            [COLLECTION / "cga", "show", "--registry", "--json"],
            cwd=self.root, env={key: value for key, value in os.environ.items() if key != "CGA_DIR"},
            text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        roots = {item["vid"] for item in json.loads(result.stdout)["elements"]}
        completed = subprocess.run([
            "bash", "-c", 'source "$1"; COMP_WORDS=("$2" show ":f"); COMP_CWORD=2; '
            '_cga; printf "%s\\n" "${COMPREPLY[@]}"',
            "_", str(COLLECTION / "completions" / "cga.bash"), str(COLLECTION / "cga")],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(set(completed.stdout.splitlines()),
                         {root for root in roots if root.startswith(":f")})

    def test_separate_popup_terminals_insert_only_and_close_independently(self):
        self.record()
        inspector = Inspector(self.repository, lease_seconds=120)
        self.addCleanup(inspector.close)
        first = inspector.terminal({"operation": "open", "ref": ":f3a,1,J"},
                                   "http://127.0.0.1:1234")
        second = inspector.terminal({"operation": "open", "ref": ":f3a,1,J"},
                                    "http://127.0.0.1:1234")
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["directory"], second["directory"])
        context = json.loads(Path(first["context_file"]).read_text())
        self.assertIn("at=", context["pinned_ref"])
        self.assertNotIn("--yolo", shlex.split(first["command"]))
        terminal = inspector.terminals[first["id"]][0]
        with mock.patch.object(terminal, "write", wraps=terminal.write) as write:
            inspector.terminal({"operation": "insert", "id": first["id"]},
                               "http://127.0.0.1:1234")
            inserted = write.call_args.args[0]
            self.assertTrue(inserted.startswith("\x1b[200~copilot"))
            self.assertTrue(inserted.endswith("\x1b[201~"))
            self.assertNotIn("\n", inserted)
        inspector.terminal({"operation": "stop", "id": first["id"]}, "")
        self.assertIsNotNone(terminal.process.poll())
        self.assertTrue(inspector.terminals[second["id"]][0].descriptor()["running"])
        inspector.expire(time.monotonic() + 121)
        self.assertEqual(inspector.terminals, {})

    def start_http(self, server_handler, inspector):
        server = ThreadingHTTPServer(("127.0.0.1", 0), server_handler)
        server.vid_inspector = inspector
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            inspector.close()
        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_port}"

    def test_bench_and_unified_inspector_apis_and_terminal_origin_guards(self):
        self.record()
        backend = Backend(None)
        self.addCleanup(backend.close)
        for server_handler, inspector in (
                (handler(backend), backend.inspector), (Handler, Inspector(self.repository))):
            url = self.start_http(server_handler, inspector)
            with self.subTest(handler=server_handler.__name__):
                with urllib.request.urlopen(url + "/api/vid?ref=:f3a,1,J") as response:
                    value = json.load(response)
                self.assertEqual(value, Space(self.repository).inspect(":f3a,1,J"))
                for route in ("/vid", "/vid-ui.js", "/vid-vendor/xterm.js"):
                    with urllib.request.urlopen(url + route) as response:
                        self.assertEqual(response.status, 200)
                document = json.dumps({"operation": "open", "ref": ":f3a,1,J"}).encode()
                request = urllib.request.Request(
                    url + "/api/vid/terminal", data=document,
                    headers={"Content-Type": "application/json", "X-CGA-VID": "1",
                             "Origin": "http://unrelated.invalid"})
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(request)
                self.assertEqual(failure.exception.code, 403)
                failure.exception.close()
                request.remove_header("Origin")
                with urllib.request.urlopen(request) as response:
                    terminal = json.load(response)
                request.data = json.dumps({"operation": "stop", "id": terminal["id"]}).encode()
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 200)

    @unittest.skipUnless(shutil.which("chromium") and shutil.which("node"),
                         "VID browser test requires Chromium and Node")
    def test_both_views_open_independent_interactive_pinned_inspectors(self, gateway=False):
        websocket = subprocess.run(
            ["node", "-p", "typeof WebSocket"], text=True, capture_output=True, check=True)
        if websocket.stdout.strip() != "function":
            self.skipTest("VID browser test requires Node's built-in WebSocket")
        self.record()
        backend = Backend(None)
        self.addCleanup(backend.close)
        unified_inspector = Inspector(self.repository)
        bench = self.start_http(handler(backend), backend.inspector)
        unified = self.start_http(Handler, unified_inspector)
        if gateway:
            origin = start_gateway(self, {
                "/bench/": int(bench.rsplit(":", 1)[1]),
                "/unified/": int(unified.rsplit(":", 1)[1]),
            })
            bench, unified = origin + "/bench", origin + "/unified"
        binaries = self.root / "bin"
        binaries.mkdir()
        marker = self.root / "copilot-executed"
        copilot = binaries / "copilot"
        copilot.write_text(f"#!/bin/sh\nprintf executed > {shlex.quote(str(marker))}\n")
        copilot.chmod(0o755)
        home = self.root / "home"
        home.mkdir()
        (home / ".bashrc").write_text("PS1='vid-test> '\nbind 'set enable-bracketed-paste on'\n")
        profile = self.root / "browser-profile"
        browser = subprocess.Popen([
            "chromium", "--headless", "--disable-gpu", "--disable-background-networking",
            "--disable-sync", "--no-first-run", "--remote-debugging-port=0",
            f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            if browser.poll() is None:
                browser.terminate()
            browser.wait(timeout=10)
        self.addCleanup(stop)
        active = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 10
        while not active.exists():
            if browser.poll() is not None or time.monotonic() >= deadline:
                self.fail("Chromium failed to become ready")
            time.sleep(.05)
        port, socket = active.read_text().splitlines()
        with mock.patch.dict(os.environ, {
                "SHELL": "/bin/bash", "HOME": str(home),
                "PATH": str(binaries) + os.pathsep + os.environ["PATH"]}):
            process = subprocess.run([
                "node", str(COLLECTION / "tests" / "vid-browser.mjs"),
                f"ws://127.0.0.1:{port}{socket}", bench, unified],
                text=True, capture_output=True, timeout=90)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(marker.exists(), "pasting must not execute Copilot")
        deadline = time.monotonic() + 5
        while backend.inspector.terminals or unified_inspector.terminals:
            if time.monotonic() >= deadline:
                self.fail("closing popup windows did not stop their owned terminals")
            time.sleep(.05)

    def test_gateway_views_open_independent_interactive_pinned_inspectors(self):
        self.test_both_views_open_independent_interactive_pinned_inspectors(gateway=True)


if __name__ == "__main__":
    unittest.main()

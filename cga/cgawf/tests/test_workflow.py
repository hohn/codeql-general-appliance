from __future__ import annotations

import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
COLLECTION = PROJECT.parent
sys.path.insert(0, str(PROJECT))

from cgawf import cli  # noqa: E402
from cgawf import tags as taglib  # noqa: E402
from cgawf.repository import (  # noqa: E402
    ObjectStore,
    Repository,
    WorkflowError,
    normalize_key,
)


class _ObjectHandler(BaseHTTPRequestHandler):
    root: Path

    def _path(self) -> Path:
        relative = self.path.removeprefix("/store/")
        return self.root.joinpath(*relative.split("/"))

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(200 if self._path().is_file() else 404)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        if not path.is_file():
            self.send_error(404)
            return
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_PUT(self) -> None:  # noqa: N802
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.rfile.read(int(self.headers["Content-Length"]))
        path.write_bytes(content)
        self.send_response(201)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        pass


class RepositoryTest(unittest.TestCase):
    def test_init_help_explains_workflow_setup_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            completed = subprocess.run(
                [COLLECTION / "cga", "init", "-h"],
                cwd=raw,
                check=True,
                capture_output=True,
                text=True,
            )
            text = completed.stdout
            sections = [
                "Name:", "Synopsis:", "Positional Arguments:",
                "Options:", "Description:", "Environment Variables:", "Example:",
            ]
            positions = [text.index(section) for section in sections]
            self.assertEqual(positions, sorted(positions))
            self.assertIn("default: current directory", text)
            self.assertIn("overrides CGA_OBJECT_STORE", " ".join(text.split()))
            self.assertIn("CGA_OBJECT_STORE\n", text)
            self.assertIn("Defaults to .cga/objects", text)
            self.assertIn("cga chain start --name baseline", text)
            self.assertIn("cga status", text)
            self.assertEqual(list(Path(raw).iterdir()), [])

    @unittest.skipUnless(sys.version_info >= (3, 14), "argparse color requires Python 3.14")
    def test_init_help_styles_all_headings_with_native_argparse_colors(self) -> None:
        completed = subprocess.run(
            [COLLECTION / "cga", "init", "-h"],
            env={**os.environ, "PYTHON_COLORS": "1"},
            check=True,
            capture_output=True,
            text=True,
        )
        text = completed.stdout
        headings = [
            "Name", "Synopsis", "Positional Arguments", "Options",
            "Description", "Environment Variables", "Example",
        ]
        for heading in headings:
            with self.subTest(heading=heading):
                self.assertRegex(text, rf"\x1b\[[0-9;]+m{re.escape(heading)}:")

    def test_filter_forwards_progress_before_the_component_exits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            acknowledged = Path(raw) / "progress-seen"

            class ProgressSink(io.StringIO):
                def write(self, text: str) -> int:
                    if "progress\n" in text:
                        acknowledged.touch()
                    return super().write(text)

            script = (
                "import pathlib, sys, time\n"
                "sys.stdin.buffer.read()\n"
                "sys.stderr.write('progress\\n'); sys.stderr.flush()\n"
                "ack = pathlib.Path(sys.argv[1])\n"
                "deadline = time.monotonic() + 3\n"
                "while not ack.exists() and time.monotonic() < deadline:\n"
                "    time.sleep(0.01)\n"
                "if not ack.exists(): raise SystemExit(7)\n"
                "sys.stdout.write('{}')\n"
            )
            sink = ProgressSink()
            with mock.patch.object(sys, "stderr", sink):
                code, output, transcript = cli._run_filter(
                    [sys.executable, "-c", script, str(acknowledged)],
                    os.environ.copy(), b"{}",
                )
            self.assertEqual(code, 0)
            self.assertEqual(output, b"{}")
            self.assertEqual(transcript, b"progress\n")
            self.assertEqual(sink.getvalue(), "progress\n")

    def test_chain_states_are_content_addressed_and_branchable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root, "../objects")
            first = repository.start_chain(name="main")
            with repository.locked():
                manifest = repository.load_manifest()
                _, chain = repository.resolve_chain(manifest, first)
                node = repository.record_state(
                    manifest,
                    first,
                    chain,
                    {"answer": 42},
                    ["cga", "test", "set"],
                    "unit-test",
                )
            second = repository.start_chain(from_revision=node, name="branch")

            manifest = repository.load_manifest()
            _, branch = repository.resolve_chain(manifest, second)
            self.assertEqual(branch["root_parent"], node)
            self.assertEqual(repository.current_state(manifest), {"answer": 42})
            state_reference = manifest["nodes"][node]["state"]
            self.assertEqual(
                state_reference["key"],
                f"objects/sha256/{state_reference['sha256'][:2]}/"
                f"{state_reference['sha256']}",
            )
            self.assertFalse(Path(state_reference["key"]).is_absolute())

    def test_chain_names_are_unique(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository = Repository.init(Path(raw) / "workflow")
            repository.start_chain(name="main")
            with self.assertRaisesRegex(WorkflowError, "already exists"):
                repository.start_chain(name="main")

    def test_artifact_reference_is_relative_to_store_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root, "../objects")
            artifact = root / "result.sarif"
            artifact.write_text('{"runs":[]}\n', encoding="utf-8")
            with repository.locked():
                manifest = repository.load_manifest()
                artifact_id = repository.register_artifact(
                    manifest, artifact, "results/job-1.sarif", "sarif", None
                )
                repository.write_manifest(manifest)

            record = repository.load_manifest()["artifacts"][artifact_id]
            self.assertFalse(Path(record["key"]).is_absolute())
            self.assertNotIn(str(Path(raw)), record["key"])
            self.assertEqual(
                Path(repository.store().location(record["key"])).read_bytes(),
                artifact.read_bytes(),
            )
            materialized = root / "copy.sarif"
            repository.store().materialize(record, materialized)
            self.assertEqual(materialized.read_bytes(), artifact.read_bytes())

    def test_discovery_follows_json_manifests_to_archives(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            archive = root / "database.zip"
            archive.write_bytes(b"database")
            record = root / "record.json"
            record.write_text(
                json.dumps({"archive": str(archive)}), encoding="utf-8"
            )
            manifest = repository.load_manifest()
            artifacts = repository.register_discovered_artifacts(
                manifest,
                {"cgadb-records": str(record)},
                "cga_0_db_build_0",
                tags=taglib.normalize(["user:viewable"]),
            )
            self.assertEqual(len(artifacts), 2)
            kinds = {
                manifest["artifacts"][artifact_id]["kind"]
                for artifact_id in artifacts
            }
            self.assertEqual(kinds, {"archive", "cgadb-records"})
            self.assertTrue(all(
                "audience:user"
                in manifest["artifacts"][artifact_id]["tags"]["canonical"]
                for artifact_id in artifacts
            ))

    def test_artifact_occurrences_keep_producer_tags_separate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            artifact = root / "result.json"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest = repository.load_manifest()
            first = repository.register_artifact(
                manifest,
                artifact,
                "result",
                "path",
                "node_1",
                taglib.normalize(["audience:user"]),
            )
            second = repository.register_artifact(
                manifest,
                artifact,
                "result",
                "path",
                "node_2",
                taglib.normalize(["audience:system"]),
            )
            self.assertNotEqual(first, second)
            self.assertEqual(
                manifest["artifacts"][first]["tags"]["canonical"],
                ["audience:user"],
            )
            self.assertEqual(
                manifest["artifacts"][second]["tags"]["canonical"],
                ["audience:system"],
            )
            self.assertEqual(
                manifest["artifacts"][first]["key"],
                manifest["artifacts"][second]["key"],
            )

    def test_store_root_can_change_without_rewriting_references(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root, "../objects-a")
            repository.start_chain()
            before = repository.load_manifest()
            old_store = repository.store()
            new_root = Path(raw) / "objects-b"
            shutil.copytree(old_store.path, new_root)

            with repository.locked():
                config = repository.load_config()
                config["object_store"]["root"] = "../objects-b"
                repository.write_config(config)

            self.assertEqual(before, repository.load_manifest())
            self.assertEqual(repository.current_state(), {})
            self.assertEqual(repository.verify(), [])

    def test_object_keys_reject_traversal(self) -> None:
        for value in (
            "/absolute",
            "../escape",
            "a/../escape",
            "a//unnormalized",
            r"a\b",
        ):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                normalize_key(value)

    def test_http_store_streams_files_and_materializes_them(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            handler = type("ObjectHandler", (_ObjectHandler,), {"root": root / "http"})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                store = ObjectStore(
                    f"http://127.0.0.1:{server.server_port}/store", root
                )
                source = root / "source.bin"
                source.write_bytes(b"large artifact" * 1000)
                reference = store.put_file(source)
                destination = root / "destination.bin"
                store.materialize(reference, destination)
                self.assertEqual(destination.read_bytes(), source.read_bytes())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class CliTest(unittest.TestCase):
    def test_run_records_component_state_and_discovered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            repository.start_chain()
            artifact = root / "result.sarif"
            component = root / "component.py"
            component.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "state = json.load(sys.stdin)\n"
                f"path = pathlib.Path({str(artifact)!r})\n"
                "path.write_text('{\"runs\":[]}\\n', encoding='utf-8')\n"
                "state['artifacts'] = {'sarif': str(path)}\n"
                "sys.stderr.write('component progress\\n')\n"
                "json.dump(state, sys.stdout)\n",
                encoding="utf-8",
            )
            component.chmod(0o755)
            source = root / "flow.sh"
            source.write_text(
                "#!/usr/bin/env bash\ncga test \\\n  --flag\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with mock.patch.dict(
                    os.environ,
                    {
                        "CGA_SOURCE_FILE": str(source),
                        "CGA_SOURCE_LINE": "2",
                    }), \
                    mock.patch.object(Path, "cwd", return_value=root), \
                    mock.patch.object(sys, "stderr", stderr):
                result = cli.main(
                    [
                        "run",
                        "--display-token",
                        "test",
                        "--source-step",
                        "unit-test",
                        "--tag",
                        "user:show-progress",
                        "--",
                        str(component),
                    ]
                )

            self.assertEqual(result, 0)
            manifest = repository.load_manifest()
            self.assertEqual(len(manifest["nodes"]), 1)
            self.assertEqual(len(manifest["artifacts"]), 1)
            node = next(iter(manifest["nodes"].values()))
            self.assertEqual(
                node["command"],
                ["cga", "test", "--tag", "user:show-progress"],
            )
            self.assertEqual(node["tags"]["canonical"], [
                "audience:user",
                "presentation:progress",
            ])
            self.assertEqual(node["source_step"], "unit-test")
            self.assertIn("CGAST node:", stderr.getvalue())
            self.assertEqual(node["source"]["path"], "flow.sh")
            self.assertEqual(node["source"]["start_line"], 2)
            self.assertEqual(node["source"]["end_line"], 3)
            self.assertEqual(node["execution"]["exit_code"], 0)
            transcript = repository.store().read(node["execution"]["transcript"])
            self.assertEqual(transcript, b"component progress\n")

    def test_failed_command_records_attempt_without_advancing_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            repository.start_chain()
            component = root / "component.py"
            component.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stderr.write('failed visibly\\n')\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )
            component.chmod(0o755)
            with mock.patch.object(Path, "cwd", return_value=root):
                result = cli.main(
                    [
                        "run",
                        "--display-token",
                        "test",
                        "--source-step",
                        "unit-test",
                        "--tag",
                        "user:show-progress",
                        "--",
                        str(component),
                    ]
                )
            self.assertEqual(result, 7)
            manifest = repository.load_manifest()
            self.assertEqual(manifest["nodes"], {})
            self.assertEqual(len(manifest["attempts"]), 1)
            attempt = next(iter(manifest["attempts"].values()))
            self.assertEqual(attempt["execution"]["exit_code"], 7)
            self.assertEqual(attempt["tags"]["canonical"], [
                "audience:user",
                "presentation:progress",
            ])
            self.assertEqual(repository.current_state(), {})
            transcript = repository.store().read(
                attempt["execution"]["transcript"]
            )
            self.assertEqual(transcript, b"failed visibly\n")

    def test_run_records_multi_level_display_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            repository.start_chain()
            component = root / "component.py"
            component.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "assert os.environ['CGA_WORKFLOW_ACTIVE'] == '1'\n"
                "sys.stdout.write(sys.stdin.read())\n",
                encoding="utf-8",
            )
            component.chmod(0o755)
            with mock.patch.object(Path, "cwd", return_value=root):
                result = cli.main(
                    [
                        "run",
                        "--display-token",
                        "db",
                        "--display-action",
                        "plan",
                        "--",
                        str(component),
                        "--mode",
                        "trace",
                    ]
                )
            self.assertEqual(result, 0)
            node = next(iter(repository.load_manifest()["nodes"].values()))
            self.assertEqual(
                node["command"], ["cga", "db", "plan", "--mode", "trace"]
            )

    def test_status_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            Repository.init(root)
            output = io.StringIO()
            with mock.patch.object(Path, "cwd", return_value=root), \
                    mock.patch.dict(os.environ, {"CGA_OUTPUT_JSON": "1"}), \
                    contextlib.redirect_stdout(output):
                result = cli.main(["status"])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())["chains"], 0)

    def test_dashboard_capture_retries(self) -> None:
        failed = mock.Mock(returncode=1)
        succeeded = mock.Mock(returncode=0)
        with mock.patch.dict(
                os.environ, {"CGA_DASHBOARD_DUMP": "/tmp/capture.jsonl"}), \
                mock.patch.object(cli.shutil, "which",
                                  return_value="/usr/bin/cga"), \
                mock.patch.object(cli.subprocess, "run",
                                  side_effect=[failed, succeeded]) as run, \
                mock.patch.object(cli.time, "sleep"):
            cli._capture_dashboard(["cga", "mx", "info"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args.args[0][-2:], ["--label", "cga mx info"])
        self.assertEqual(run.call_args.args[0][:2], ["/usr/bin/cga", "view"])

    def test_tree_dot_uses_left_aligned_multiline_labels(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            chain_id = repository.start_chain()
            with repository.locked():
                manifest = repository.load_manifest()
                _, chain = repository.resolve_chain(manifest, chain_id)
                repository.record_state(
                    manifest,
                    chain_id,
                    chain,
                    {"answer": 42},
                    ["cga", "test", "set"],
                    "unit-test",
                )
            dot = cli._tree_dot(repository.load_manifest(), False)
            self.assertIn('<TD ALIGN="LEFT"><B>cga_0_test_set_0</B>', dot)
            self.assertIn('<TD ALIGN="LEFT">cga test set</TD>', dot)
            self.assertNotIn(r"\n", dot)

    def test_tree_html_embeds_graphviz_svg(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "workflow"
            repository = Repository.init(root)
            repository.start_chain()
            output = root / "tree.html"
            with mock.patch.object(Path, "cwd", return_value=root):
                result = cli.main(
                    ["tree", "show", "-v", "--format", "html", "-o", str(output)]
                )
            document = output.read_text(encoding="utf-8")
            self.assertEqual(result, 0)
            self.assertIn("<svg", document)
            self.assertIn("class=\"graph\"", document)
            self.assertNotIn("<pre>", document)


class DispatcherTest(unittest.TestCase):
    def test_dispatcher_strips_and_records_tags_after_action(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            workflow = root / "workflow"
            cga = COLLECTION / "cga"
            subprocess.run(
                [cga, "init", workflow],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            subprocess.run(
                [cga, "-C", workflow, "chain", "start"],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    cga,
                    "-C",
                    workflow,
                    "mx",
                    "info",
                    "--tag",
                    "user:viewable",
                    "--tag=subject:infrastructure",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            manifest = json.loads(
                (workflow / ".cga" / "manifest.json").read_text()
            )
            node = next(iter(manifest["nodes"].values()))
            self.assertEqual(node["command"][:4], [
                "cga", "mx", "info", "--tag",
            ])
            self.assertEqual(node["tags"]["profiles"], ["user:viewable"])
            self.assertEqual(node["tags"]["canonical"], [
                "audience:user",
                "prominence:detail",
                "subject:infrastructure",
            ])

    def test_run_and_view_are_public_dispatcher_commands(self) -> None:
        cga = COLLECTION / "cga"
        run_commands = subprocess.run(
            [cga, "__subs", "run"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        self.assertEqual(
            run_commands, ["start", "stop", "status", "build", "seed"]
        )
        completed = subprocess.run(
            [cga, "view", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--capture", completed.stdout)
        unified_commands = subprocess.run(
            [cga, "__subs", "uv"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        self.assertEqual(
            unified_commands,
            ["start", "stop", "status", "outline", "search"],
        )
        completed = subprocess.run(
            [cga, "uv", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("cga uv", completed.stdout)

    def test_preparation_and_nested_measure_commands_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            workflow = root / "workflow"
            store = root / "store"
            cga = COLLECTION / "cga"
            environment = os.environ.copy()
            environment.pop("CGA_WORKFLOW_ACTIVE", None)
            environment["PATH"] = f"{COLLECTION}:{environment['PATH']}"
            subprocess.run(
                [cga, "init", workflow, "--store", store],
                check=True,
                stdout=subprocess.DEVNULL,
                env=environment,
            )
            subprocess.run(
                [cga, "-C", workflow, "chain", "start"],
                check=True,
                stdout=subprocess.DEVNULL,
                env=environment,
            )
            subprocess.run(
                [cga, "-C", workflow, "db", "plan", "info"],
                check=True,
                stdout=subprocess.DEVNULL,
                env=environment,
            )
            subprocess.run(
                [
                    cga,
                    "-C",
                    workflow,
                    "control",
                    "measure",
                    "--cgast-filter",
                    "--output-dir",
                    root / "measure",
                    "--",
                    "cga",
                    "codeql",
                    "info",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                env=environment,
            )
            manifest = json.loads(
                (workflow / ".cga" / "manifest.json").read_text()
            )
            commands = [
                node["command"]
                for node in sorted(
                    manifest["nodes"].values(),
                    key=lambda node: node["sequence"],
                )
            ]
            self.assertEqual(commands[0], ["cga", "db", "plan", "info"])
            self.assertEqual(commands[1][:3], ["cga", "control", "measure"])


if __name__ == "__main__":
    unittest.main()

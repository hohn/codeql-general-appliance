from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

COLLECTION = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(COLLECTION / name) for name in ("cgalib", "cgawf", "cgabench")]

from cgabench import model
from cgawf.repository import Repository
from cgawf.tags import normalize


class ContextTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = Repository.init(self.root / "workflow", "../objects")
        self.chain = self.repository.start_chain(name="main")
        self.environment = os.environ.copy()
        for key in ("CGA_DIR", "CGA_OUTPUT_JSON", "CGA_CGAUV_PORT", "CGA_OBJECT_STORE"):
            self.environment.pop(key, None)
        self.environment["CGAST_ROOT"] = str(self.root)
        self.environment["CGAST_TMPDIR"] = str(self.root / "scratch")

    def run_cga(self, *args: str, cwd: Path | None = None,
                environment: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(COLLECTION / "cga"), *args], cwd=cwd or self.repository.root,
            env=environment or self.environment, text=True, capture_output=True,
            timeout=15,
        )

    def record(self, state: dict, command: list[str] | None = None,
               tags: list[str] | None = None) -> None:
        with self.repository.locked():
            manifest = self.repository.load_manifest()
            _, chain = self.repository.resolve_chain(manifest, self.chain)
            self.repository.record_state(
                manifest, self.chain, chain, state,
                command or ["cga", "bench", "session"], "test",
                tags=normalize(tags or []),
            )

    def bench_state(self) -> dict:
        state = {}
        with mock.patch.dict(os.environ, self.environment):
            model.init(state, "query-study", "query-changes")
            model.add(state, "reference", "alice", None)
        return state

    def snapshot(self) -> dict:
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_help_and_command_discovery_need_no_workflow(self) -> None:
        for arguments, expected in (
            (["--help"], "llm"),
            (["__subs", "llm"], "context\ncb\ncu\n"),
            (["llm"], "context"),
            (["llm", "context"], "bench"),
            (["llm", "context", "--help"], "--show-json-endpoint"),
            (["llm", "context", "bench", "--help"], "--session-file"),
            (["llm", "cu", "--help"], "--include-sensitive"),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cga(*arguments, cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout + result.stderr)

    def test_unified_context_reads_current_chain_without_writes(self) -> None:
        self.record({"answer": 42}, ["cga", "mx", "info"])
        before = self.snapshot()
        result = self.run_cga("llm", "context", "unified")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# CGA flow: workflow", result.stdout)
        self.assertIn("main", result.stdout)
        self.assertIn("cga mx info", result.stdout)
        document = self.run_cga("llm", "context", "unified", "--json")
        alias = self.run_cga("--json", "llm", "cu")
        self.assertEqual(document.returncode, 0, document.stderr)
        self.assertEqual(alias.returncode, 0, alias.stderr)
        value = json.loads(document.stdout)
        self.assertEqual(value, json.loads(alias.stdout))
        self.assertEqual(value["schema"], "cga.use.outline.v1")
        self.assertEqual(value["chain"]["id"], self.chain)
        self.assertEqual(value["system"], {})
        self.assertEqual(before, self.snapshot())

    def test_unified_preserves_secret_redaction(self) -> None:
        self.record({}, ["cga", "mx", "secret-command"], ["sensitivity:secret"])
        result = self.run_cga("llm", "cu")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Redacted steps: 1", result.stdout)
        self.assertNotIn("secret-command", result.stdout)
        included = self.run_cga("llm", "cu", "--include-sensitive")
        self.assertEqual(included.returncode, 0, included.stderr)
        self.assertIn("secret-command", included.stdout)

    def test_bench_context_and_alias_read_authoritative_state(self) -> None:
        state = self.bench_state()
        self.record(state)
        self.repository.current_path.write_text("{}\n")
        before = self.snapshot()
        result = self.run_cga("llm", "context", "bench")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# CGA Bench: query-study", result.stdout)
        self.assertIn("Fixed input: D", result.stdout)
        self.assertIn("E.S[1]: reference", result.stdout)
        self.assertIn("User: alice", result.stdout)
        self.assertIn("E.S[1].R:", result.stdout)
        self.assertIn("Comparison is explicit", result.stdout)
        alias = self.run_cga("llm", "cb")
        self.assertEqual(alias.returncode, 0, alias.stderr)
        self.assertEqual(result.stdout, alias.stdout)
        document = self.run_cga("llm", "cb", "--json")
        self.assertEqual(document.returncode, 0, document.stderr)
        value = json.loads(document.stdout)
        self.assertEqual(value["name"], "query-study")
        self.assertEqual(value["sessions"][0]["name"], "reference")
        self.assertEqual(before, self.snapshot())

    def test_session_file_and_explicit_workflow_location(self) -> None:
        state = self.bench_state()
        path = self.root / "raw.json"
        model.save(path, state)
        before = self.snapshot()
        result = self.run_cga("llm", "cb", "--session-file", str(path), cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("query-study", result.stdout)
        self.assertEqual(before, self.snapshot())
        self.record(state)
        result = self.run_cga(
            "--cga-dir", str(self.repository.cga_dir), "llm", "cb", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("query-study", result.stdout)
        result = self.run_cga(
            "-C", str(self.repository.root), "--store", str(self.root / "objects"),
            "llm", "cb", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("query-study", result.stdout)

    def test_projections_need_neither_state_nor_server(self) -> None:
        for scope, port, path in (
            ("bench", 8610, "/api/model"),
            ("unified", 8609, "/api/outline"),
        ):
            with self.subTest(scope=scope):
                result = self.run_cga(
                    "llm", "context", scope, "--show-json-endpoint", cwd=self.root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, f"http://127.0.0.1:{port}{path}\n")
                html = self.run_cga(
                    "llm", "context", scope, "--show-html-endpoint",
                    "--port", "9876", cwd=self.root)
                self.assertEqual(html.returncode, 0, html.stderr)
                self.assertEqual(html.stdout, "http://127.0.0.1:9876/\n")
                docs = self.run_cga(
                    "llm", "context", scope, "--show-docs", cwd=self.root)
                self.assertEqual(docs.returncode, 0, docs.stderr)
                self.assertTrue(all(Path(name).is_file() for name in docs.stdout.splitlines()))
        environment = {**self.environment, "CGA_CGAUV_PORT": "8729"}
        result = self.run_cga(
            "llm", "cu", "--show-json-endpoint", environment=environment)
        self.assertEqual(result.stdout, "http://127.0.0.1:8729/api/outline\n")
        result = self.run_cga(
            "llm", "cu", "--show-json-endpoint", "--port", "9001", environment=environment)
        self.assertEqual(result.stdout, "http://127.0.0.1:9001/api/outline\n")
        result = self.run_cga(
            "llm", "cu", "--show-json-endpoint", "--detail", "summary", "--include-sensitive")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "http://127.0.0.1:8609/api/outline?detail=summary&include_sensitive=true\n")

    def test_invalid_state_and_options_fail_explicitly(self) -> None:
        for arguments, message in (
            (["llm", "cu"], "no .cga directory"),
            (["llm", "cb", "--session-file", str(self.root / "missing")], "cannot read JSON"),
            (["llm", "cu", "--port", "0"], "port must be in 1..65535"),
            (["llm", "cu", "--port", "no"], "port must be an integer"),
            (["llm", "cb", "--show-docs", "--show-json-endpoint"], "not allowed"),
            (["llm", "context", "unknown"], "invalid choice"),
            (["llm", "cb", "--tag", "user:viewable"], "--tag applies only"),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cga(*arguments, cwd=self.root)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)
        uninitialized = self.run_cga("llm", "cb")
        self.assertEqual(uninitialized.returncode, 2, uninitialized.stderr)
        self.assertIn("cga bench init", uninitialized.stderr)
        environment = {**self.environment, "CGA_CGAUV_PORT": "invalid"}
        invalid_port = self.run_cga("llm", "cu", "--show-html-endpoint", environment=environment)
        self.assertEqual(invalid_port.returncode, 2)
        self.assertIn("port must be an integer", invalid_port.stderr)

    def test_unified_context_handles_workflow_without_chain(self) -> None:
        repository = Repository.init(self.root / "empty", "../objects")
        result = self.run_cga("llm", "cu", cwd=repository.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Chain: `(none)`", result.stdout)

    def test_completion_exposes_context_sources_and_projection_flags(self) -> None:
        for arguments, expected in (
            (["llm", ""], ["context", "cb", "cu"]),
            (["llm", "context", ""], ["bench", "unified"]),
            (["llm", "context", "bench", "--show"], ["--show-json-endpoint", "--show-docs"]),
            (["llm", "cu", "--"], ["--detail", "--include-sensitive"]),
        ):
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    ["bash", "-c",
                     'source "$1"; shift; COMP_WORDS=("$@"); '
                     'COMP_CWORD=$((${#COMP_WORDS[@]}-1)); _cga; '
                     'printf "%s\\n" "${COMPREPLY[@]}"',
                     "_", str(COLLECTION / "completions" / "cga.bash"),
                     str(COLLECTION / "cga"), *arguments],
                    env=self.environment, text=True, capture_output=True, timeout=15,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(set(expected).issubset(completed.stdout.splitlines()))


if __name__ == "__main__":
    unittest.main()

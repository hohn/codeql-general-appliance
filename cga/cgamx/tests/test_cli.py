from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CGA_ROOT / "cgalib"))

from cgamx import cli, infra  # noqa: E402


def _run_cli(argv, cgast_in, env):
    """Invoke cli.main with a CGAST on stdin, returning the stdout CGAST."""
    stdin = io.StringIO(json.dumps(cgast_in))
    stdin.isatty = lambda: False  # type: ignore[assignment]
    out = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(sys, "stdin", stdin), \
            mock.patch.object(sys, "stdout", out):
        rc = cli.main(argv)
    return rc, json.loads(out.getvalue())


class ConfigTest(unittest.TestCase):
    def test_workflow_roots_do_not_relocate_build_sources_or_default_agent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            environment = {
                "CGAST_ROOT": str(root / "workflow"),
                "CGA_ROOT": str(root / "other-workflow"),
                "MRVA_TMP_DIR": str(root / "runtime"),
                "POSTGRES_PORT": "5432",
            }
            with mock.patch.dict(os.environ, environment, clear=True), \
                 mock.patch.object(
                     infra, "_run", return_value=mock.Mock(returncode=0),
                 ) as run:
                infra.config()
                infra.phase_build()
                self.assertEqual(
                    os.environ["MRVA_ENVSIM_AGENT_BINARY"],
                    str(CGA_ROOT.parent / "agent-commander-argo" / "mrvaagent"),
                )
                self.assertEqual(infra.cgast.cga_root(), root / "workflow")
            run.assert_called_once_with(
                ["make", "-s", "-C", str(CGA_ROOT.parent / "server-commander"),
                 "mrvaserver", "mrvaagent"],
                check=False,
            )

    def test_explicit_agent_binary_is_preserved_with_workflow_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            environment = {
                "CGAST_ROOT": str(Path(raw) / "workflow"),
                "MRVA_TMP_DIR": str(Path(raw) / "runtime"),
                "POSTGRES_PORT": "5432",
                "MRVA_ENVSIM_AGENT_BINARY": "/custom/mrvaagent",
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                infra.config()
                self.assertEqual(
                    os.environ["MRVA_ENVSIM_AGENT_BINARY"], "/custom/mrvaagent",
                )

    def test_defaults_only_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ["USER"] = "tester"
            os.environ["MRVA_STANDALONE_STORAGE"] = "filesystem"  # override
            infra.config()
            # Override preserved.
            self.assertEqual(os.environ["MRVA_STANDALONE_STORAGE"], "filesystem")
            # Defaults filled in.
            self.assertEqual(os.environ["PORT"], "8081")
            self.assertEqual(os.environ["POSTGRES_DB"], "mrvadev")
            self.assertEqual(os.environ["PGPASSWORD"],
                             os.environ["POSTGRES_PASSWORD"])
            self.assertTrue(int(os.environ["MRVA_POOL_MAX_WORKERS"]) >= 1)
            self.assertTrue(os.environ["MRVA_DB_SERVE_DIR"].endswith("db-serve"))

    def test_active_local_postgres_cluster_port_is_default(self) -> None:
        clusters = mock.Mock(
            stdout=(
                "17 old 5432 down postgres /var/lib/postgresql/17/old log\n"
                "18 main 5433 online postgres /var/lib/postgresql/18/main log\n"
            )
        )
        with (
            mock.patch.object(infra.shutil, "which", return_value="/usr/bin/pg_lsclusters"),
            mock.patch.object(infra.subprocess, "run", return_value=clusters),
        ):
            self.assertEqual(infra._default_postgres_port("localhost"), "5433")
            self.assertEqual(infra._default_postgres_port("db.example"), "5432")

    def test_explicit_postgres_port_is_preserved(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"POSTGRES_PORT": "55440", "POSTGRES_HOST": "127.0.0.1"},
            clear=True,
        ):
            infra.config()
            self.assertEqual(os.environ["POSTGRES_PORT"], "55440")


class PostgresPresenceTest(unittest.TestCase):
    def test_reports_executable_clusters_and_likely_ports(self) -> None:
        postgres = Path("/usr/lib/postgresql/18/bin/postgres")
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            if command[-1] == "--version":
                return mock.Mock(
                    returncode=0,
                    stdout="postgres (PostgreSQL) 18.0\n",
                    stderr="",
                )
            if command[0] == "pg_lsclusters":
                return mock.Mock(
                    returncode=0,
                    stdout=(
                        "18 main 5433 online postgres "
                        "/var/lib/postgresql/18/main log\n"
                    ),
                    stderr="",
                )
            port = command[command.index("-p") + 1]
            return mock.Mock(
                returncode=0 if port == "5433" else 2,
                stdout=(
                    f"localhost:{port} - "
                    + ("accepting connections" if port == "5433" else "no response")
                    + "\n"
                ),
                stderr="",
            )

        def which(name):
            return {
                "pg_isready": "/usr/bin/pg_isready",
                "pg_lsclusters": "pg_lsclusters",
            }.get(name)

        with (
            mock.patch.dict(
                os.environ,
                {"POSTGRES_HOST": "localhost", "POSTGRES_PORT": "5433"},
                clear=True,
            ),
            mock.patch.object(infra, "_postgres_executable", return_value=postgres),
            mock.patch.object(infra.shutil, "which", side_effect=which),
            mock.patch.object(infra.subprocess, "run", side_effect=run),
        ):
            findings = infra.postgres_presence_check()

        self.assertTrue(findings["configured_endpoint_ready"])
        self.assertEqual(findings["version"], "postgres (PostgreSQL) 18.0")
        self.assertEqual(findings["clusters"][0]["port"], "5433")
        probed = {
            command[command.index("-p") + 1]
            for command in commands
            if command and command[0] == "/usr/bin/pg_isready"
        }
        self.assertEqual(probed, {"5432", "5433", "55432", "55440"})


class ErrorScanTest(unittest.TestCase):
    def test_benign_resolver_lines_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "server.log"
            log.write_text(
                "level=info ok\n"
                "ERROR mrva-project-resolver could not resolve\n", "utf-8")
            with mock.patch.dict(os.environ, {"SERVER_LOG": str(log)}):
                self.assertTrue(infra.error_check())

    def test_browser_favicon_probe_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "server.log"
            log.write_text(
                "ERROR Unhandled endpoint method=GET uri=/favicon.ico\n",
                "utf-8")
            with mock.patch.dict(os.environ, {"SERVER_LOG": str(log)}):
                self.assertTrue(infra.error_check())

    def test_real_errors_fail(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "server.log"
            log.write_text("panic: boom\n", "utf-8")
            with mock.patch.dict(os.environ, {"SERVER_LOG": str(log)}):
                self.assertFalse(infra.error_check())


class PortParseTest(unittest.TestCase):
    def test_pids_on_port_parses_ss_output(self) -> None:
        sample = (
            "State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
            "LISTEN 0      4096         127.0.0.1:8081       0.0.0.0:*    "
            "users:((\"mrvaserver\",pid=4242,fd=7))\n"
            "LISTEN 0      4096         127.0.0.1:9000       0.0.0.0:*    "
            "users:((\"minio\",pid=99,fd=3))\n")
        completed = mock.Mock(stdout=sample)
        with mock.patch.object(infra.subprocess, "run", return_value=completed):
            self.assertEqual(infra.pids_on_port("8081"), [4242])
            self.assertEqual(infra.pids_on_port("9000"), [99])
            self.assertEqual(infra.pids_on_port("1234"), [])


class FilterContractTest(unittest.TestCase):
    def test_info_preserves_other_keys_and_merges_cgamx(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            env = {"MRVA_TMP_DIR": d, "MRVA_WORK_DIR": f"{d}/work",
                   "RUN_TAG": "cgamx-unit"}
            rc, out = _run_cli(["info"], {"cgaql-index": "cga-tmp/x"}, env)
        self.assertEqual(rc, 0)
        self.assertEqual(out["cgaql-index"], "cga-tmp/x")  # untouched
        self.assertIn("cgamx", out)

    def test_check_gate_exits_nonzero_on_errors(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "server.log"
            log.write_text("fatal: nope\n", "utf-8")
            env = {"MRVA_TMP_DIR": d, "SERVER_LOG": str(log),
                   "RUN_TAG": "cgamx-unit"}
            with self.assertRaises(SystemExit) as ctx:
                _run_cli(["check"], {}, env)
        self.assertEqual(ctx.exception.code, 1)

    def test_reset_clears_stale_runtime_pids(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            env = {"MRVA_TMP_DIR": d, "MRVA_WORK_DIR": f"{d}/work",
                   "RUN_TAG": "cgamx-unit"}
            with mock.patch.object(infra, "_drop_tables"):
                rc, out = _run_cli(
                    ["reset"], {"cgamx": {"server_pid": 111}}, env)
        self.assertEqual(rc, 0)
        self.assertNotIn("server_pid", out["cgamx"])
        self.assertEqual(out["cgamx"]["last_phase"], "reset")


if __name__ == "__main__":
    unittest.main()

import argparse
import copy
from contextlib import closing, redirect_stdout
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCENARIO = Path(__file__).resolve().parents[1] / "run-system-11"
CGA = SCENARIO.parents[1]
SPEC = importlib.util.spec_from_file_location("system11", SCENARIO / "observe.py")
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


def database(index):
    return {
        "content_hash": hashlib.sha256(str(index).encode()).hexdigest(),
        "build_cid": f"build-{index}",
        "git_branch": "main",
        "git_commit_id": str(index),
        "git_owner": "owner",
        "git_repo": f"repo-{index:03d}",
        "ingestion_datetime_utc": "2026-01-01",
        "primary_language": "cpp",
        "result_url": f"file:///unused/{index}.zip",
        "tool_name": "codeql-cpp",
        "tool_version": "2.23.8" if index % 2 else "2.23.6",
        "projname": f"repo-{index}",
        "db_file_size": 10,
    }


class InputsTest(unittest.TestCase):
    def test_storage_rejects_small_filesystems_and_checks_shared_devices_once(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = argparse.Namespace(paths=[root / "databases", root / "tmp"])
            with patch.object(observer.shutil, "disk_usage",
                              return_value=SimpleNamespace(free=15 * 1024**3)):
                with self.assertRaisesRegex(ValueError, "at least 16 GiB"):
                    observer.storage(args)
            with patch.object(observer.shutil, "disk_usage",
                              return_value=SimpleNamespace(free=16 * 1024**3)) as usage, \
                    redirect_stdout(io.StringIO()):
                observer.storage(args)
                usage.assert_called_once()

    def test_real_dispatcher_selects_latest_distinct_snapshots(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            workflow = root / "workflow"
            workflow.mkdir()
            catalog = root / "metadata.sql"
            rows = [database(i) for i in range(200)]
            older = {**rows[0], "content_hash": "old", "tool_version": "2.10.0",
                     "ingestion_datetime_utc": "2020-01-01"}
            java = {**database(200), "primary_language": "java"}
            with closing(sqlite3.connect(catalog)) as connection, connection:
                connection.execute("CREATE TABLE metadata (" +
                                   ",".join(
                                       f"{key} INTEGER" if key == "db_file_size"
                                       else f"{key} TEXT" for key in rows[0]) + ")")
                connection.executemany(
                    "INSERT INTO metadata VALUES (" +
                    ",".join("?" for _ in rows[0]) + ")",
                    [tuple(row.values()) for row in [older, *rows, java]],
                )
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("CGA", "CGAST"))}
            env.update(CGA_ROOT=str(CGA), CGA_TMPDIR=str(root / "scratch"))

            def cga(*args):
                completed = subprocess.run(
                    [str(CGA / "cga"), "-C", str(workflow), *args],
                    env=env, capture_output=True, text=True,
                    timeout=30,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return completed

            cga("init", ".")
            cga("chain", "start", "--name", "sysview")
            cga("dl", "getmeta", str(catalog))
            cga("dl", "sql", "--user", "sysview", "--query-file",
                str(SCENARIO / "databases.sql"))
            current = json.loads(cga("--json", "state", "show").stdout)
            selected = observer.selection(current)
            self.assertEqual(selected, rows)
            self.assertTrue((workflow / ".cga/config").is_file())

            short_sql = root / "short.sql"
            short_sql.write_text("SELECT * FROM metadata LIMIT 199")
            experiment = root / "driver"
            result = subprocess.run(
                [str(SCENARIO / "run"), "prepare"],
                env={**env, "CGA_SYSTEM11_ROOT": str(experiment),
                     "CGA_SYSTEM11_CATALOGUE": str(catalog),
                     "CGA_SYSTEM11_SELECTION_SQL": str(short_sql)},
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("selected 199", result.stderr)
            self.assertFalse((experiment / "databases").exists())
            self.assertFalse((experiment / "mrva").exists())

    def test_selection_rejects_small_duplicate_and_non_cpp_inputs(self):
        rows = [database(i) for i in range(200)]
        cases = [
            rows[:199],
            [rows[0], *rows[0:199]],
            [{**rows[0], "content_hash": rows[1]["content_hash"]}, *rows[1:]],
            [{**rows[0], "primary_language": "java"}, *rows[1:]],
        ]
        for selected in cases:
            with self.subTest(first=selected[0]), \
                    tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / "selection.json"
                path.write_text(json.dumps({"databases": selected}))
                with self.assertRaises(ValueError):
                    observer.selection({"cgadl-selection": str(path)})

    def test_freeze_and_ready_detect_pack_selection_and_runtime_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            rows = [database(i) for i in range(200)]
            for index, row in enumerate(rows):
                archive = (root / "databases" / row["git_owner"] / row["git_repo"]
                           / f"{row['git_owner']}_{row['git_repo']}_db.zip")
                archive.parent.mkdir(parents=True)
                archive.write_bytes(str(index).encode())
            selection = root / "selection.json"
            selection.write_text(json.dumps({"databases": rows}))
            pack = root / "query.tgz"
            pack.write_bytes(b"pack")
            current = {"cgadl-selection": str(selection),
                       "cgadl-dbdir": str(root / "databases"),
                       "cgaql-pack": [str(pack)]}
            args = argparse.Namespace(inputs=root / "inputs.json")
            with patch.object(observer, "state", return_value=current), \
                    patch.object(observer, "runtime_version", return_value="2.27.1"), \
                    redirect_stdout(io.StringIO()):
                first_archive = root / "databases/owner/repo-000/owner_repo-000_db.zip"
                first_archive.write_bytes(b"corrupt")
                with self.assertRaisesRegex(ValueError, "archive hash mismatch"):
                    observer.freeze(args)
                self.assertFalse(args.inputs.exists())
                first_archive.write_bytes(b"0")
                observer.freeze(args)
                self.assertEqual(observer.ready(args)["database_versions"],
                                 {"2.23.8": 100, "2.23.6": 100})
                pack.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "query pack"):
                    observer.ready(args)
                pack.write_bytes(b"pack")
                with patch.object(observer, "runtime_version", return_value="3.0"):
                    with self.assertRaisesRegex(ValueError, "runtime"):
                        observer.ready(args)
                rows[0]["git_commit_id"] = "changed"
                selection.write_text(json.dumps({"databases": rows}))
                with self.assertRaisesRegex(ValueError, "selection"):
                    observer.ready(args)


class PollingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        pack = root / "pack.tgz"
        pack.write_bytes(b"pack")
        self.frozen = {"databases": [database(0)],
                       "pack_sha256": observer.sha256(pack)}
        self.item = {
            "name": "submission", "user": "sysview", "session_id": 1,
            "language": "cpp", "pack": str(pack),
            "repositories": ["owner/repo-000"], "status": "in_progress",
        }
        self.args = argparse.Namespace(
            inputs=root / "inputs.json", workload=root / "workload.tsv",
            poll_seconds=0.001, timeout_seconds=1,
        )
        self.args.workload.write_text("submission\tsysview\n")

    def current(self, status, job_status=None):
        item = {**self.item, "status": status, "status_response": {
            "scanned_repositories": [{
                "repository": {"full_name": "owner/repo-000"},
                "analysis_status": status if job_status is None else job_status,
            }],
        }}
        return {"cgamr-submissions": {"submission": item}}

    def test_wait_uses_cga_status_without_resubmitting(self):
        with patch.object(observer, "ready", return_value=self.frozen), \
                patch.object(observer, "state",
                             side_effect=[self.current("in_progress"),
                                          self.current("succeeded")]), \
                patch.object(observer, "cga") as cga, \
                redirect_stdout(io.StringIO()):
            observer.wait(self.args)
            cga.assert_called_once_with("mr", "status", "--name", "submission")

    def test_wait_fails_on_deadline(self):
        self.args.timeout_seconds = 0
        with patch.object(observer, "ready", return_value=self.frozen), \
                patch.object(observer, "state",
                             return_value=self.current("in_progress")), \
                patch.object(observer, "cga"), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "deadline exceeded"):
                observer.wait(self.args)

    def test_completed_mixed_outcomes_are_refreshed_and_reported_not_all_success(self):
        self.frozen["databases"].append(database(1))
        current = self.current("succeeded")
        item = current["cgamr-submissions"]["submission"]
        item["repositories"] = ["owner/repo-000", "owner/repo-001"]
        item["status_response"]["scanned_repositories"].append({
            "repository": {"full_name": "owner/repo-001"},
            "analysis_status": "failed",
        })
        with patch.object(observer, "ready", return_value=self.frozen), \
                patch.object(observer, "state", return_value=current), \
                patch.object(observer, "cga") as cga, \
                redirect_stdout(io.StringIO()) as output:
            observer.wait(self.args)
            cga.assert_called_once_with("mr", "status", "--name", "submission")
            observer.verify(self.args)
        self.assertIn('"succeeded": 1, "failed": 1', output.getvalue())
        self.assertIn("failed: submission owner/repo-001", output.getvalue())
        self.assertIn("2 terminal jobs", output.getvalue())
        self.assertNotIn("successful jobs", output.getvalue())

    def test_wait_uses_job_status_even_when_overall_says_succeeded(self):
        active = self.current("succeeded", "in_progress")
        finished = self.current("succeeded", "failed")
        with patch.object(observer, "ready", return_value=self.frozen), \
                patch.object(observer, "state",
                             side_effect=[active, active, active, finished]), \
                patch.object(observer, "cga") as cga, \
                patch.object(observer.time, "sleep"), \
                redirect_stdout(io.StringIO()) as output:
            observer.wait(self.args)
        self.assertEqual(cga.call_count, 2)
        self.assertIn("failed: submission owner/repo-000", output.getvalue())

    def test_verify_accepts_all_terminal_outcomes_but_rejects_bad_accounting(self):
        for status in ("succeeded", "failed", "canceled", "cancelled", "timed_out"):
            with self.subTest(status=status), \
                    patch.object(observer, "ready", return_value=self.frozen), \
                    patch.object(observer, "state",
                                 return_value=self.current(status)), \
                    redirect_stdout(io.StringIO()):
                observer.verify(self.args)

        for defect, error in (("active", "jobs still active"),
                              ("missing", "repository set differs"),
                              ("duplicate", "repository set differs"),
                              ("unexpected", "repository set differs"),
                              ("unknown", "unknown job status")):
            current = self.current("succeeded")
            scanned = current["cgamr-submissions"]["submission"][
                "status_response"]["scanned_repositories"]
            if defect == "active":
                scanned[0]["analysis_status"] = "in_progress"
            elif defect == "missing":
                scanned.clear()
            elif defect == "duplicate":
                scanned.append(copy.deepcopy(scanned[0]))
            elif defect == "unexpected":
                scanned[0]["repository"]["full_name"] = "unexpected/repo"
            else:
                scanned[0]["analysis_status"] = "unrecognized"
            with self.subTest(defect=defect), \
                    patch.object(observer, "ready", return_value=self.frozen), \
                    patch.object(observer, "state", return_value=current):
                with self.assertRaisesRegex(ValueError, error):
                    observer.verify(self.args)

        altered = self.current("succeeded")
        altered["cgamr-submissions"]["submission"]["user"] = "another-user"
        with self.assertRaisesRegex(ValueError, "identity"):
            observer.submissions(altered, [("submission", "sysview")], self.frozen)


class EndpointTest(unittest.TestCase):
    def test_endpoint_measurements_and_failures_are_retained(self):
        snapshot = {
            "generated_at": "12:34:56", "refresh_ms": 500,
            "jobs": [{"session_id": 1}], "workers": None,
        }
        response_status = 200
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(response_status)
                self.end_headers()
                body = b"<html></html>" if self.path == "/sysview" \
                    else json.dumps(snapshot).encode()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as raw, \
                    patch.dict(os.environ, {
                        "CGA_MRVA_SERVER": f"http://127.0.0.1:{server.server_port}"}), \
                    patch.object(observer, "cga") as cga, \
                    redirect_stdout(io.StringIO()):
                args = argparse.Namespace(output_dir=Path(raw), samples=2,
                                          interval=0.001, request_timeout=1)
                observer.observe(args)
                records = [json.loads(line) for line in next(
                    Path(raw).glob("*.jsonl")).read_text().splitlines()]
                self.assertEqual(requests, ["/sysview", "/sysview/data",
                                            "/sysview/data"])
                self.assertEqual(records[0]["data"]["shown"]["jobs"], 1)
                self.assertEqual(records[0]["data"]["shown"]["workers"], 0)
                self.assertEqual(records[0]["data"]["bytes"],
                                 len(json.dumps(snapshot).encode()))
                cga.assert_called_once()
                snapshot["error"] = "SQL query failed"
                with self.assertRaisesRegex(ValueError, "SQL query failed"):
                    observer.observe(args)
                response_status = 403
                with self.assertRaises(OSError):
                    observer.observe(args)
                failures = [json.loads(path.read_text().splitlines()[0])
                            for path in Path(raw).glob("*.jsonl")]
                self.assertTrue(any(row.get("http_status") == 403
                                    for row in failures))
                self.assertTrue(any("SQL query failed" in row.get("error", "")
                                    for row in failures))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()

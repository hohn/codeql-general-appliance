from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(CGA_ROOT / "cgalib"))

from cgamr import cli, serve  # noqa: E402


class LifecycleTest(unittest.TestCase):
    def test_submit_prebuilt_artifacts_and_attach_existing_session(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = Path(raw) / "query.tgz"
            pack.write_bytes(b"pack")
            args = cli.build_parser().parse_args([
                "submit", "--name", "one", "--user", "alice",
                "--pack", str(pack), "--language", "cpp",
                "--repos", "acme/one", "acme/one"])
            state = {}
            with mock.patch.object(cli.client, "submit",
                                   return_value={"id": 42}) as submit:
                cli.cmd_submit(state, args)
                self.assertEqual(submit.call_args.args[4], ["acme/one"])
                with self.assertRaises(SystemExit):
                    cli.cmd_submit(state, args)
                self.assertEqual(submit.call_count, 1)
            response = {
                "status": "succeeded", "scanned_repositories": [{
                    "repository": {"full_name": "acme/one"}}]}
            args = cli.build_parser().parse_args([
                "attach", "--name", "external", "--user", "alice",
                "--session-id", "43"])
            with mock.patch.object(cli.client, "status", return_value=response):
                cli.cmd_attach(state, args)
            self.assertEqual(state[cli.SUBMISSIONS_KEY]["external"]["session_id"], 43)
            self.assertEqual(state[cli.SUBMISSIONS_KEY]["external"]["repositories"],
                             ["acme/one"])

    def test_prebuilt_submit_rejects_invalid_repositories_before_http(self):
        with tempfile.TemporaryDirectory() as raw:
            pack = Path(raw) / "query.tgz"
            pack.write_bytes(b"pack")
            for repo, language in (("missing-owner", ["--language", "cpp"]),
                                   ("acme/one", [])):
                args = cli.build_parser().parse_args([
                    "submit", "--name", "one", "--user", "alice",
                    "--pack", str(pack), "--repos", repo, *language])
                with mock.patch.object(cli.client, "submit") as submit:
                    with self.assertRaises(SystemExit):
                        cli.cmd_submit({}, args)
                    submit.assert_not_called()

    def test_run_composes_lifecycle_and_preserves_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {}
            args = cli.build_parser().parse_args([
                "run", "--name", "one", "--user", "alice", "--output-dir", tmp,
                "--log-dir", str(Path(tmp) / "log"), "--poll-seconds", "0.01"])
            calls = []
            def submit(s, _a):
                calls.append("submit")
                s[cli.SUBMISSIONS_KEY]["one"] = {"session_id": 42, "status": "in_progress"}
            def status(s, _a):
                calls.append("status")
                s[cli.SUBMISSIONS_KEY]["one"]["status"] = "succeeded"
            with mock.patch.object(cli, "cmd_submit", side_effect=submit), \
                 mock.patch.object(cli, "cmd_status", side_effect=status), \
                 mock.patch.object(cli, "cmd_download", side_effect=lambda *_: calls.append("download")), \
                 mock.patch.object(cli, "cmd_verify", side_effect=lambda *_: calls.append("verify")):
                cli.cmd_run(state, args)
                self.assertEqual(calls, ["submit", "status", "download", "verify"])
                self.assertEqual(json.loads((Path(tmp) / "log/latest.state").read_text()), state)
                with self.assertRaises(SystemExit):
                    cli.cmd_run(state, args)
                self.assertEqual(calls.count("submit"), 1)

    def test_run_timeout_or_terminal_failure_retains_session_without_download(self):
        for outcome in ("in_progress", "failed"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                state = {}
                args = cli.build_parser().parse_args([
                    "run", "--name", "one", "--user", "alice", "--output-dir", tmp,
                    "--log-dir", str(Path(tmp) / "log"), "--timeout-seconds", "1"])
                def submit(s, _a):
                    s[cli.SUBMISSIONS_KEY]["one"] = {"session_id": 42, "status": outcome}
                with mock.patch.object(cli, "cmd_submit", side_effect=submit), \
                     mock.patch.object(cli, "cmd_status"), \
                     mock.patch.object(cli, "cmd_download") as download, \
                     mock.patch.object(cli.time, "monotonic", side_effect=[0, 2]):
                    with self.assertRaises(SystemExit):
                        cli.cmd_run(state, args)
                    download.assert_not_called()
                saved = json.loads((Path(tmp) / "log/latest.state").read_text())
                self.assertEqual(saved[cli.SUBMISSIONS_KEY]["one"]["session_id"], 42)

    def test_detail_distinguishes_submission_label_from_user(self) -> None:
        state = {"cgamr-submissions": {"bob-1": {
            "user": "bob", "session_id": 1, "status": "succeeded",
            "repositories": ["acme/one"],
        }}}
        with mock.patch.object(serve.cgast, "load_session",
                               return_value=state):
            detail = serve.detail_fragment()
        self.assertIn("caller-defined run label", detail)
        self.assertIn("MRVA authenticated identity", detail)
        self.assertIn("<th>submission</th><th>user</th>", detail)

    def test_named_submit_status_download_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            pack = root / "query.tgz"
            pack.write_bytes(b"pack")
            dbdir = root / "dbs"
            archive = dbdir / "acme" / "one" / "acme_one_db.zip"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"database")
            selection = root / "selection.json"
            selection.write_text(json.dumps({"databases": [{
                "git_owner": "acme",
                "git_repo": "one",
                "primary_language": "cpp",
            }]}))
            state = {
                "cgaql-pack": [str(pack)],
                "cgadl-selection": str(selection),
                "cgadl-dbdir": str(dbdir),
            }
            connection = {
                "server": None,
                "controller_owner": None,
                "controller_repo": None,
                "bearer_token": None,
            }
            submit_args = argparse.Namespace(
                name="test-1", user="alice", language="cpp", pack_index=0,
                **connection)

            with mock.patch.object(
                    cli.client, "submit",
                    return_value={"id": 42, "status": "in_progress"}):
                cli.cmd_submit(state, submit_args)

            item = state[cli.SUBMISSIONS_KEY]["test-1"]
            self.assertEqual(item["session_id"], 42)
            self.assertEqual(item["repositories"], ["acme/one"])
            self.assertEqual(state[cli.ACTIVE_KEY], "test-1")

            response = {
                "status": "succeeded",
                "scanned_repositories": [{
                    "repository": {"full_name": "acme/one"},
                    "analysis_status": "succeeded",
                    "result_count": 3,
                    "artifact_size_in_bytes": 12,
                }],
            }
            status_args = argparse.Namespace(name="test-1", **connection)
            with mock.patch.object(cli.client, "status",
                                   return_value=response):
                cli.cmd_status(state, status_args)
            self.assertEqual(item["status"], "succeeded")

            output = root / "downloads"
            download_args = argparse.Namespace(
                name="test-1", output_dir=str(output), **connection)

            def write_artifact(_url, _server, destination, _user, _token):
                destination.write_bytes(b"result")
                return 6

            with mock.patch.object(cli.client, "status",
                                   return_value=response), \
                 mock.patch.object(
                    cli.client, "download_metadata",
                    return_value={"artifact_url": "https://bad/artifact.zip"}), \
                 mock.patch.object(cli.client, "download_artifact",
                                   side_effect=write_artifact):
                cli.cmd_download(state, download_args)

            self.assertEqual(len(item["downloads"]), 1)
            self.assertTrue((output / "acme-one.zip").is_file())
            cli.cmd_verify(state, argparse.Namespace(names=["test-1"]))


if __name__ == "__main__":
    unittest.main()

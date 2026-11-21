from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
REPO_ROOT = CGA_ROOT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(REPO_ROOT / "cga" / "cgalib"))
from cgadb import cli  # noqa: E402


class CgadbTest(unittest.TestCase):
    def test_zip_preserves_database_root_and_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            database = root / "db"
            database.mkdir()
            (database / "codeql-database.yml").write_text("primaryLanguage: cpp\n")
            (database / "source").write_text("source")
            (database / "linked").symlink_to(database / "source")
            output = root / "db.zip"
            state = {}
            cli.cmd_zip(state, argparse.Namespace(
                db_dir=str(database), output=str(output)))
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()),
                                 {"db/codeql-database.yml", "db/source"})
            self.assertEqual(state["cgadb-archives"][0]["sha256"],
                             cli.digest(output))
            with self.assertRaises(cli.workflow.WorkflowError):
                cli.cmd_zip({}, argparse.Namespace(
                    db_dir=str(database), output=str(database / "nested.zip")))
            with self.assertRaises(cli.workflow.WorkflowError):
                cli.cmd_zip({}, argparse.Namespace(
                    db_dir=str(root), output=str(output)))

    def test_build_creates_exactly_one_record(self):
        scratch = CGA_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_ROOT),
                               "CGAST_TMPDIR": raw}):
            root = Path(raw)
            source = root / "source"
            source.mkdir()
            (source / "input.c").write_text("int main(void) { return 0; }\n")
            job = root / "job.json"
            cli.workflow.write_json(job, {
                "schema": "cga.database-job.v1",
                "id": "cve-1--vulnerable--none--arm64",
                "owner": "debian",
                "repo": "zlib-vulnerable-none-arm64",
                "base_repo": "zlib-vulnerable",
                "package": "zlib",
                "language": "cpp",
                "variant": "vulnerable",
                "version": "1",
                "source_dir": cli.cgast.rel(source),
                "source_tree_sha256": cli.tree_digest(source),
                "status": "ready",
                "mode": "bm-none",
                "extraction_mode": "none",
                "architecture": "arm64",
                "dependency_argv": [],
                "build_command": None,
                "build_cid": "build-1",
            })
            output = root / "output"

            def run(argv, cwd=None):
                if "bundle" in argv:
                    archive = Path(argv[argv.index("--output") + 1])
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    archive.write_bytes(b"database")

            state = {}
            with mock.patch.object(cli.workflow, "run", side_effect=run), \
                    mock.patch.object(cli, "_capture", return_value="2.27.1\n"):
                cli.cmd_build(state, argparse.Namespace(
                    job=str(job), trace=False, bm_none=True,
                    output_dir=str(output), record=None, resources=None,
                    dry_run=False))
            document = cli.workflow.load_json(
                cli.cgast.resolve(state[cli.RECORDS_KEY]))
            self.assertEqual(document["count"], 1)
            record = document["items"][0]
            self.assertEqual(record["status"], "built")
            self.assertEqual(
                record["catalogue_record"]["git_repo"],
                "zlib-" + record["sha256"])
            self.assertEqual(record["repo"], record["catalogue_record"]["git_repo"])
            self.assertEqual(record["upstream_repo"], "zlib")
            self.assertEqual(Path(record["archive"]).parent.name, record["repo"])
            self.assertEqual(record["tool_version"], "2.27.1")
            self.assertTrue(Path(record["archive"]).is_file())
            (source / "input.c").write_text("changed after planning")
            with self.assertRaisesRegex(cli.workflow.WorkflowError, "hash changed"):
                cli.cmd_build({}, argparse.Namespace(
                    job=str(job), trace=False, bm_none=True,
                    output_dir=str(root / "changed-output"), record=None,
                    resources=None, dry_run=False))

    def test_build_rejects_mode_mismatch(self):
        with tempfile.TemporaryDirectory() as raw:
            job = Path(raw) / "job.json"
            cli.workflow.write_json(job, {
                "schema": "cga.database-job.v1",
                "id": "job", "owner": "o", "repo": "r",
                "mode": "trace",
            })
            with self.assertRaisesRegex(
                    cli.workflow.WorkflowError, "job mode"):
                cli.cmd_build({}, argparse.Namespace(
                    job=str(job), trace=False, bm_none=True,
                    output_dir=raw, record=None, resources=None,
                    dry_run=True))

    def test_build_rejects_completed_job_before_writing_record(self):
        scratch = CGA_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_ROOT),
                               "CGAST_TMPDIR": raw}):
            root = Path(raw)
            job = root / "job.json"
            record = root / "record.json"
            records = root / "records.json"
            cli.workflow.write_json(job, {
                "schema": "cga.database-job.v1",
                "id": "job", "owner": "debian", "repo": "zlib",
                "mode": "bm-none",
            })
            cli.workflow.write_json(records, {
                "schema": "cga.database-records.v1",
                "count": 1,
                "items": [{"id": "job", "owner": "debian", "repo": "zlib",
                           "status": "built"}],
            })
            state = {cli.RECORDS_KEY: cli.cgast.rel(records)}
            with self.assertRaisesRegex(
                    cli.workflow.WorkflowError,
                    "database record already exists"):
                cli.cmd_build(state, argparse.Namespace(
                    job=str(job), trace=False, bm_none=True,
                    output_dir=str(root / "output"), record=str(record),
                    resources=None, dry_run=True))
            self.assertFalse(record.exists())

    def test_trace_verification_requires_intercepted_process(self):
        with tempfile.TemporaryDirectory() as raw:
            database = Path(raw)
            log = database / "log"
            log.mkdir()
            (database / "codeql-database.yml").write_text(
                "primaryLanguage: cpp\n")
            (log / "build-tracer.log").write_text(
                "Initializing tracer.\n"
                "Lua: === Intercepted call to /usr/bin/gcc ===\n")
            result = cli._verify_traced_extraction(database)
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["intercepted_processes"], 1)

    def test_trace_verification_rejects_scan_fallback(self):
        with tempfile.TemporaryDirectory() as raw:
            database = Path(raw)
            log = database / "log"
            log.mkdir()
            (database / "codeql-database.yml").write_text(
                "primaryLanguage: cpp\nbuildMode: none\n")
            (log / "build-tracer.log").write_text(
                "Lua: === Intercepted call to /usr/bin/gcc ===\n")
            with self.assertRaisesRegex(
                    cli.workflow.WorkflowError, "source-scanned"):
                cli._verify_traced_extraction(database)

    def test_trace_verification_rejects_scan_command_marker(self):
        with tempfile.TemporaryDirectory() as raw:
            database = Path(raw)
            log = database / "log"
            log.mkdir()
            (database / "codeql-database.yml").write_text(
                "primaryLanguage: cpp\n")
            (log / "extraction_commands.json").write_text("[]\n")
            (log / "build-tracer.log").write_text(
                "Lua: === Intercepted call to /usr/bin/gcc ===\n")
            with self.assertRaisesRegex(
                    cli.workflow.WorkflowError, "source-scanned"):
                cli._verify_traced_extraction(database)

    def test_trace_verification_rejects_missing_tracer_log(self):
        with tempfile.TemporaryDirectory() as raw:
            database = Path(raw)
            (database / "codeql-database.yml").write_text(
                "primaryLanguage: cpp\n")
            with self.assertRaisesRegex(
                    cli.workflow.WorkflowError, "no build-tracer.log"):
                cli._verify_traced_extraction(database)


if __name__ == "__main__":
    unittest.main()

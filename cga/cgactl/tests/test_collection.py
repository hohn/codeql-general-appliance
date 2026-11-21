import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "lib"))
sys.path.insert(0, str(PROJECT.parent / "cgalib"))

from cgactl import collection  # noqa: E402


class FakeDatabase:
    def __init__(self, value):
        self.value = value

    def json(self, _sql, variables=None):
        if variables == {"job": "job-1"}:
            return self.value
        if variables and variables.get("job") == "job-1" and \
                "collection" in variables:
            return {"recorded": True}
        else:
            raise AssertionError(variables)


class PromotionTest(unittest.TestCase):
    def test_promotes_to_content_addressed_qldbstore_and_catalogue(self):
        payload = b"database bundle"
        digest = hashlib.sha256(payload).hexdigest()
        record = {
            "job": {
                "job_id": "job-1", "status": "succeeded", "cve": "CVE-X",
                "variant": "vulnerable", "mode": "trace",
                "toolchain_digest": "codeql:2.23.9-ubu-noble-amd64",
                "spec": {"package": "zlib", "language": "cpp",
                         "version": "1.2.8"},
            },
            "attempt": {
                "status": "succeeded", "result": {"artifacts": {
                    "database": {"uri": "incus://ubu/tmp/database.zip",
                                 "sha256": digest,
                                 "size_bytes": len(payload)},
                    "build_log": {"uri": "incus://ubu/tmp/build.log",
                                  "sha256": digest,
                                  "size_bytes": len(payload)}}},
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            def fetch(_uri, destination):
                destination.write_bytes(payload)

            with mock.patch.object(collection, "_fetch", side_effect=fetch), \
                    mock.patch.object(collection, "_validate_bundle",
                                      return_value={"languages": ["cpp"]}):
                result = collection.promote(
                    FakeDatabase(record), "job-1", root)

            archive = (root / "databases" / "debian" /
                       f"zlib-{digest}" /
                       f"debian_zlib-{digest}_db.zip")
            self.assertEqual(archive.read_bytes(), payload)
            self.assertEqual(result["sha256"], digest)
            self.assertTrue((root / "provenance" / "job-1" /
                             "result.json").is_file())
            self.assertEqual(
                (root / "provenance" / "job-1" / "artifacts" /
                 "build_log.log").read_bytes(), payload)
            conn = sqlite3.connect(root / "metadata.sql")
            try:
                row = conn.execute(
                    "SELECT git_owner, git_repo, content_hash FROM metadata"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(row, ("debian", f"zlib-{digest}", digest))
            status = collection.collection_status(root, verify=True)
            self.assertEqual(status["catalogue_rows"], 1)
            self.assertEqual(status["archives"], 1)
            self.assertEqual(status["provenance_records"], 1)
            self.assertEqual(status["missing_artifacts"], [])
            self.assertEqual(status["digest_mismatches"], [])

    def test_reconcile_reports_pending_and_promoted(self):
        class ReconcileDatabase:
            def json(self, _sql):
                return [
                    {"job_id": "done", "status": "succeeded",
                     "artifact": {"uri": "file:///x", "sha256": "a"}},
                    {"job_id": "pending", "status": "succeeded",
                     "artifact": {"uri": "file:///y", "sha256": "b"}},
                ]

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            collection._catalogue(root / "metadata.sql", {
                "content_hash": "a", "build_cid": "done",
                "git_branch": "vulnerable", "git_commit_id": "1",
                "git_owner": "debian", "git_repo": "x",
                "ingestion_datetime_utc": "now", "primary_language": "cpp",
                "result_url": "file:///x", "tool_name": "codeql",
                "tool_version": "1", "projname": "x", "db_file_size": 1,
            })
            result = collection.reconcile(ReconcileDatabase(), root)
            self.assertEqual(result["promoted"], ["done"])
            self.assertEqual(result["pending_promotion"], ["pending"])


if __name__ == "__main__":
    unittest.main()

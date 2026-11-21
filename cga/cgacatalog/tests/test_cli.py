from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
CGA_ROOT = PROJECT.parent
REPO_ROOT = CGA_ROOT.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(REPO_ROOT / "cga" / "cgalib"))
from cgacatalog import cli  # noqa: E402


def row(archive, repo, version):
    return {
        "content_hash": cli.digest(archive),
        "build_cid": repo,
        "git_branch": "vulnerable",
        "git_commit_id": "1",
        "git_owner": "debian",
        "git_repo": repo,
        "ingestion_datetime_utc": "2026-01-01T00:00:00+00:00",
        "primary_language": "cpp",
        "result_url": "file:///stale.zip",
        "tool_name": "codeql",
        "tool_version": version,
        "projname": "debian/zlib@1",
        "db_file_size": archive.stat().st_size,
    }


class CgaCatalogTest(unittest.TestCase):
    def test_export_relocates_verified_legacy_collection_and_refuses_corruption(self):
        with tempfile.TemporaryDirectory() as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": raw, "CGAST_TMPDIR": raw}):
            root = Path(raw)
            source = root / "source.zip"
            source.write_bytes(b"database")
            original_row = row(source, "zlib", "2.27.1")
            original_row["result_url"] = source.as_uri()
            catalog, manifest = cli._write_outputs(
                {}, [original_row], [{
                    "repository": "debian/zlib", "archive": str(source),
                    "sha256": original_row["content_hash"],
                    "catalogue_record": original_row,
                }], str(root / "metadata.sql"), str(root / "manifest.json"))
            destination = root / "collection"
            args = argparse.Namespace(
                catalog=str(catalog), manifest=str(manifest), directory=str(destination),
                base_url="http://127.0.0.1:9080", move=False)
            state = {}
            cli.cmd_export(state, args)
            self.assertEqual(cli.verify(destination / "metadata.sql",
                                        destination / "manifest.json"), 1)
            exported = cli.read_catalog(destination / "metadata.sql")[0]
            repo = "zlib-" + original_row["content_hash"]
            archive = destination / "debian" / repo / f"debian_{repo}_db.zip"
            self.assertEqual(archive.read_bytes(), source.read_bytes())
            self.assertEqual(exported["git_repo"], repo)
            self.assertEqual(exported["content_hash"], original_row["content_hash"])
            self.assertEqual(
                exported["result_url"],
                f"http://127.0.0.1:9080/debian/{repo}/debian_{repo}_db.zip")
            self.assertTrue(source.exists())
            source.write_bytes(b"corrupted")
            args.directory = str(root / "corrupted-export")
            with self.assertRaisesRegex(cli.workflow.WorkflowError, "archive mismatch"):
                cli.cmd_export({}, args)
            self.assertFalse(Path(args.directory).exists())
            source.write_bytes(b"database")
            args.directory = str(root / "moved")
            args.move = True
            cli.cmd_export({}, args)
            self.assertFalse(source.exists())
            self.assertEqual(cli.verify(Path(args.directory) / "metadata.sql",
                                        Path(args.directory) / "manifest.json"), 1)

    def test_create_merge_and_verify(self):
        scratch = CGA_ROOT / "cga-prep-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as raw, mock.patch.dict(
                "os.environ", {"CGAST_ROOT": str(CGA_ROOT),
                               "CGAST_TMPDIR": raw}):
            root = Path(raw)
            generated_archive = (
                root / "generated/debian/zlib-vulnerable-none-arm64/"
                "debian_zlib-vulnerable-none-arm64_db.zip")
            generated_archive.parent.mkdir(parents=True)
            generated_archive.write_bytes(b"generated")
            resources = root / "resources"
            resources.mkdir()
            (resources / "resource_summary.json").write_text("{}\n")
            generated_row = row(
                generated_archive, "zlib-vulnerable-none-arm64", "2.27.1")
            records = root / "records.json"
            cli.workflow.write_json(records, {"items": [{
                "id": "generated", "owner": "debian",
                "repo": "zlib-vulnerable-none-arm64",
                "status": "built", "variant": "vulnerable",
                "extraction_mode": "none", "architecture": "arm64",
                "source_input": str(root), "source": str(root),
                "source_tree_sha256": "a" * 64,
                "disposable_source_tree_sha256": "b" * 64,
                "database": str(root), "archive": str(generated_archive),
                "resources": str(resources),
                "catalogue_record": generated_row,
            }]})
            validations = root / "validations.json"
            cli.workflow.write_json(validations, {"items": [{
                "record_id": "generated", "status": "passed",
                "findings": 1,
            }]})
            state = {
                cli.RECORDS_KEY: cli.cgast.rel(records),
                cli.VALIDATIONS_KEY: cli.cgast.rel(validations),
            }
            generated_catalog = root / "generated.sql"
            generated_manifest = root / "generated.json"
            cli.cmd_create(state, argparse.Namespace(
                output=str(generated_catalog),
                manifest=str(generated_manifest)))

            base_root = root / "base"
            base_archive = (
                base_root / "debian/zlib-vulnerable-none/"
                "debian_zlib-vulnerable-none_db.zip")
            base_archive.parent.mkdir(parents=True)
            base_archive.write_bytes(b"base")
            base_catalog = root / "base.sql"
            cli.write_catalog(base_catalog, [
                row(base_archive, "zlib-vulnerable-none", "2.23.9")])
            query = root / "base-query.sql"
            query.write_text("SELECT * FROM metadata;\n")
            descriptors = root / "descriptors.json"
            cli.workflow.write_json(descriptors, {"items": [{
                "repository": "debian/zlib-vulnerable-none",
                "variant": "vulnerable", "mode": "none",
                "architecture": "x86_64",
            }]})
            combined = root / "combined.sql"
            manifest = root / "manifest.json"
            cli.cmd_merge(state, argparse.Namespace(
                catalog=str(generated_catalog),
                catalog_manifest=str(generated_manifest),
                base_catalog=str(base_catalog),
                base_query_file=str(query),
                base_archive_root=str(base_root),
                base_descriptors=str(descriptors),
                require_base_tool_version="2.23.9",
                output=str(combined), manifest=str(manifest)))
            self.assertEqual(cli.verify(combined, manifest), 2)
            document = cli.workflow.load_json(manifest)
            self.assertEqual(
                {item["architecture"] for item in document["databases"]},
                {"x86_64", "arm64"})


if __name__ == "__main__":
    unittest.main()

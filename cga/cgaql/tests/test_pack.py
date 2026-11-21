from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from cgaql import pack  # noqa: E402


class PackTest(unittest.TestCase):
    def test_persistent_manifest_refuses_to_overwrite_existing_pack(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            directory = Path(raw_tmp) / "workspace"
            with mock.patch.object(pack, "_dependency",
                                   return_value=("codeql/cpp-all", "1.2.3", None)):
                pack.initialize_pack(directory, "cpp", name="cga/bench-query")
                before = (directory / "qlpack.yml").read_text()
                with self.assertRaises(FileExistsError):
                    pack.initialize_pack(directory, "cpp")
            self.assertEqual((directory / "qlpack.yml").read_text(), before)

    def test_uses_exact_dependency_from_codeql_bundle(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            binary = root / "codeql"
            binary.touch()
            manifest = (root / "qlpacks" / "codeql" / "cpp-all" /
                        "6.1.4" / "qlpack.yml")
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                "name: codeql/cpp-all\nversion: 6.1.4\nlibrary: true\n",
                encoding="utf-8")
            query = root / "Example.ql"
            query.write_text("import cpp\nselect 1\n", encoding="utf-8")
            (root / "qlpack.yml").write_text("name: cga/test\nversion: 0.0.1\n")
            support = root / "Support.qll"
            support.write_text("predicate support() { any() }\n",
                               encoding="utf-8")
            nested = root / "modules" / "Nested.qll"
            nested.parent.mkdir()
            nested.write_text("import cpp\n", encoding="utf-8")
            excluded = root / "databases" / "DatabaseScratch.qll"
            excluded.parent.mkdir()
            excluded.write_text("not a query module\n", encoding="utf-8")
            calls = []
            generated = {}

            def fake_run(cmd, cwd):
                calls.append(cmd)
                generated["qlpack"] = (cwd / "qlpack.yml").read_text(
                    encoding="utf-8")
                generated["support"] = (cwd / "Support.qll").read_text(
                    encoding="utf-8")
                generated["nested"] = (cwd / "modules/Nested.qll").read_text(
                    encoding="utf-8")
                self.assertFalse((cwd / "databases").exists())
                for arg in cmd:
                    if arg.startswith("-o="):
                        Path(arg[3:]).write_bytes(b"bundle")

            with mock.patch.object(pack.shutil, "which",
                                   return_value=str(binary)), \
                 mock.patch.object(pack, "_run", side_effect=fake_run):
                result = pack.build_query_pack(query, "cpp", "codeql")

            self.assertEqual(result, b"bundle")
            self.assertIn('codeql/cpp-all: "6.1.4"', generated["qlpack"])
            self.assertEqual(generated["support"], support.read_text(
                encoding="utf-8"))
            self.assertEqual(generated["nested"], nested.read_text(encoding="utf-8"))
            expected = f"--search-path={root / 'qlpacks'}"
            self.assertIn(expected, calls[0])
            self.assertIn(expected, calls[1])

    def test_missing_bundle_requires_exact_override(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            binary = Path(raw_tmp) / "codeql"
            binary.touch()
            with mock.patch.object(pack.shutil, "which",
                                   return_value=str(binary)), \
                 mock.patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(
                        pack.PackError, "CGA_CGAQL_CPP_DEP_VERSION"):
                    pack._dependency("cpp", "codeql")


if __name__ == "__main__":
    unittest.main()

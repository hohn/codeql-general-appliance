import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "lib"))

from cgactl.matrix import build_matrix  # noqa: E402


class MatrixTest(unittest.TestCase):
    def test_three_variants_two_modes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cve_dir = root / "cve-2020-0001"
            cve_dir.mkdir()
            spec = {"cves": [{
                "id": "CVE-2020-0001", "language": "cpp",
                "debian": {"source_package": "sample"},
                "variants": [{"name": name, "version": str(i),
                              "source": {"url": f"https://x/{i}"}}
                             for i, name in enumerate(
                                 ("vulnerable", "patched", "most-recent"))],
                "build": {"dependencies": [], "command": "make"},
            }]}
            (cve_dir / "spec.json").write_text(json.dumps(spec))
            for name in ("vulnerable", "fixed", "current"):
                source = cve_dir / "tmp" / name / "source"
                source.mkdir(parents=True)
                (source / "sample.c").write_text(f"/* {name} */\n")
            result = build_matrix(root, "sha256:toolchain")
            self.assertEqual(result["count"], 6)
            self.assertEqual(len({x["job_id"] for x in result["jobs"]}), 6)
            self.assertEqual({x["mode"] for x in result["jobs"]},
                             {"trace", "none"})
            self.assertTrue(all(x["source_digest"].startswith("tree-sha256:")
                                for x in result["jobs"]))


if __name__ == "__main__":
    unittest.main()

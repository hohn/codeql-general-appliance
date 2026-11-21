from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


VARIANT_ALIASES = {"fixed": "patched", "current": "most-recent"}
MODES = ("trace", "none")
SOURCE_DIRS = {
    "vulnerable": "vulnerable",
    "patched": "fixed",
    "most-recent": "current",
}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True,
                         separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"pristine source tree is missing: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if path.is_symlink():
            kind, content = b"symlink", os.readlink(path).encode()
        elif path.is_dir():
            kind, content = b"directory", b""
        elif path.is_file():
            kind, content = b"file", path.read_bytes()
        else:
            raise ValueError(f"unsupported source-tree entry: {path}")
        for field in (kind, str(mode).encode(), relative, content):
            digest.update(len(field).to_bytes(8, "big"))
            digest.update(field)
    return "tree-sha256:" + digest.hexdigest()


def build_matrix(cves_dir: Path, toolchain_digest: str,
                 source_identity: str = "tree") -> dict[str, Any]:
    jobs = []
    for spec_path in sorted(cves_dir.glob("cve-*/spec.json")):
        doc = json.loads(spec_path.read_text(encoding="utf-8"))
        for cve in doc.get("cves", []):
            for variant in cve.get("variants", []):
                name = VARIANT_ALIASES.get(variant["name"], variant["name"])
                source_descriptor = {
                    "cve": cve["id"], "version": variant.get("version"),
                    "source": variant.get("source", {}),
                }
                if source_identity == "tree":
                    source_dir = (spec_path.parent / "tmp" /
                                  SOURCE_DIRS[name] / "source")
                    source_digest = tree_digest(source_dir)
                elif source_identity == "descriptor":
                    source_digest = "descriptor-sha256:" + _digest(
                        source_descriptor)
                else:
                    raise ValueError(
                        f"unsupported source identity: {source_identity}")
                for mode in MODES:
                    identity = {
                        "cve": cve["id"], "variant": name, "mode": mode,
                        "source_digest": source_digest,
                        "toolchain_digest": toolchain_digest,
                    }
                    jobs.append({
                        **identity,
                        "job_id": (f"{cve['id'].lower()}--{name}--{mode}--" +
                                   _digest(identity)[:16]),
                        "priority": 100,
                        "spec": {
                            "language": cve.get("language"),
                            "package": cve.get("debian", {}).get(
                                "source_package"),
                            "version": variant.get("version"),
                            "source": variant.get("source", {}),
                            "build": cve.get("build", {}),
                            "spec_path": str(spec_path),
                        },
                    })
    return {"schema_version": 1, "count": len(jobs), "jobs": jobs}

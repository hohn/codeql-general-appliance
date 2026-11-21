"""Building CodeQL query-pack bundles.

``build_query_pack`` turns one ``.ql`` file into a real CodeQL pack bundle
using ``codeql pack install`` + ``codeql pack bundle``, so cgamr can submit
the result directly. The cgaql CLI records bundle paths in the CGAST.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

# Library pack per language. The exact version is resolved from the CodeQL
# bundle used to build the query pack; selecting registry "latest" is not
# reproducible and can select a manifest requiring a newer CLI.
DEP_FOR_LANG: Dict[str, str] = {
    "cpp": "codeql/cpp-all",
    "python": "codeql/python-all",
    "javascript": "codeql/javascript-all",
    "java": "codeql/java-all",
    "go": "codeql/go-all",
    "csharp": "codeql/csharp-all",
    "ruby": "codeql/ruby-all",
    "swift": "codeql/swift-all",
}

_VERSION_RE = re.compile(r"^version:\s*['\"]?([^'\"\s]+)")


class PackError(RuntimeError):
    """Raised when a pack cannot be built (bad query, codeql failure, ...)."""


def _run(cmd: List[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise PackError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def _version_key(value: str) -> tuple:
    """Return a deterministic key for the numeric CodeQL pack versions."""
    return tuple(int(part) if part.isdigit() else part
                 for part in re.split(r"[.-]", value))


def _pack_version(manifest: Path) -> str:
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = _VERSION_RE.match(line.strip())
        if match:
            return match.group(1)
    raise PackError(f"bundled dependency has no version: {manifest}")


def _dependency(language: str, codeql_binary: str) -> tuple[str, str, Path | None]:
    dep_name = DEP_FOR_LANG.get(language, "")
    if not dep_name:
        raise PackError(f"unknown/blank language {language!r}; "
                        f"cannot pick a codeql/<lang>-all dependency")

    override_name = f"CGA_CGAQL_{language.upper()}_DEP_VERSION"
    override = os.environ.get(override_name)
    resolved = shutil.which(codeql_binary)
    binary = Path(resolved or codeql_binary).expanduser().resolve()
    qlpacks = binary.parent / "qlpacks"
    namespace, name = dep_name.split("/", 1)
    manifests = list((qlpacks / namespace / name).glob("*/qlpack.yml"))
    manifests += list((qlpacks / namespace / name).glob("*/qlpack.yaml"))

    if override:
        return dep_name, override, qlpacks if qlpacks.is_dir() else None
    if not manifests:
        raise PackError(
            f"{dep_name} is not bundled with {binary}; install the CodeQL "
            f"bundle or set {override_name} to an exact compatible version")
    versions = [(_pack_version(path), path) for path in manifests]
    version, _ = max(versions, key=lambda item: _version_key(item[0]))
    return dep_name, version, qlpacks


def initialize_pack(directory: Path, language: str,
                    codeql_binary: str = "codeql",
                    name: str = "cga/cgaql-pack") -> Path | None:
    """Create a manifest with the selected bundle's exact language dependency."""
    dep_name, dep_version, search_path = _dependency(language, codeql_binary)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "qlpack.yml"
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write(
            f"name: {name}\n"
            "version: 0.0.1\n"
            "dependencies:\n"
            f'  {dep_name}: "{dep_version}"\n')
    return search_path


def copy_query_support(source: Path, destination: Path) -> None:
    """Preserve local QL modules without copying databases or editor scratch."""
    has_pack = any((source / name).is_file() for name in ("qlpack.yml", "qlpack.yaml"))
    modules = source.rglob("*.qll") if has_pack else source.glob("*.qll")
    for path in sorted(modules):
        relative = path.relative_to(source)
        if any(part in ("databases", ".git", ".codeql", ".vscode", ".cache")
               for part in relative.parts[:-1]):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise PackError(f"query support file escapes the source tree: {path}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def build_query_pack(query_path: Path, language: str,
                     codeql_binary: str = "codeql") -> bytes:
    """Return the bytes of a freshly-bundled query pack ``.tgz``.

    Materialise ``qlpack.yml`` + the query,
    ``codeql pack install`` to resolve the language dependency, then
    ``codeql pack bundle``.
    """
    qpath = Path(query_path).resolve()
    if not qpath.is_file():
        raise PackError(f"query not found: {qpath}")

    with tempfile.TemporaryDirectory(prefix="cgaql-pack-") as tdir:
        pack_dir = Path(tdir) / "pack"
        search_path = initialize_pack(pack_dir, language, codeql_binary)
        shutil.copy2(qpath, pack_dir / qpath.name)
        copy_query_support(qpath.parent, pack_dir)

        search = [f"--search-path={search_path}"] if search_path else []
        _run([codeql_binary, "pack", "install", *search], cwd=pack_dir)
        bundle = Path(tdir) / "pack.tgz"
        _run([codeql_binary, "pack", "bundle", *search, f"-o={bundle}"],
             cwd=pack_dir)
        return bundle.read_bytes()

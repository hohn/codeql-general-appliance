"""Persistent .cga workflow repositories and content-addressed objects."""

from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


FORMAT_VERSION = 1
EMPTY_STATE: dict[str, Any] = {}
ARTIFACT_FILE_KEYS = {
    "archive",
    "catalog",
    "cgacatalog-catalog",
    "cgacatalog-manifest",
    "cgacodeql-check",
    "cgadl-metadata",
    "cgadl-query",
    "cgadl-selection",
    "cgadb-records",
    "cgadbplan-jobs",
    "cgadbvalidate-results",
    "cgasi-db",
    "cgasp-plan",
    "cgasp-sources",
    "cgaql-index",
    "cgaql-pack",
    "cgaql-selection",
    "downloads",
    "job",
    "jobs",
    "manifest",
    "path",
    "pack",
    "record",
    "results",
    "sarif",
    "sources",
    "sqlite",
    "verify",
}
ARTIFACT_DIRECTORY_KEYS = {
    "cgadl-dbdir",
    "cgasi-root",
    "download_dir",
}


class WorkflowError(RuntimeError):
    """A workflow repository or object-store operation failed."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}."
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def normalize_key(key: str) -> str:
    if not key or "\\" in key:
        raise WorkflowError(f"invalid object key: {key!r}")
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise WorkflowError(f"object key must be relative and normalized: {key!r}")
    normalized = str(path)
    if normalized != key or "?" in normalized or "#" in normalized:
        raise WorkflowError(f"object key must be normalized and URL-safe: {key!r}")
    return normalized


def object_key(digest: str) -> str:
    return f"objects/sha256/{digest[:2]}/{digest}"


def merge_tag_documents(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    profiles = list(dict.fromkeys(
        list((left or {}).get("profiles", []))
        + list((right or {}).get("profiles", []))
    ))
    canonical = list(dict.fromkeys(
        list((left or {}).get("canonical", []))
        + list((right or {}).get("canonical", []))
    ))
    values: dict[str, list[str]] = {}
    for document in (left or {}, right or {}):
        raw_values = document.get("values", {})
        if not isinstance(raw_values, dict):
            continue
        for key, items in raw_values.items():
            if not isinstance(items, list):
                continue
            values.setdefault(key, [])
            for item in items:
                if isinstance(item, str) and item not in values[key]:
                    values[key].append(item)
    return {
        "profiles": profiles,
        "canonical": canonical,
        "values": values,
    }


class ObjectStore:
    """A filesystem or HTTP object-store root."""

    def __init__(self, root: str, workflow_root: Path) -> None:
        if not isinstance(root, str) or not root.strip():
            raise WorkflowError("object_store.root must be a non-empty string")
        self.spec = root
        self.workflow_root = workflow_root
        parsed = urllib.parse.urlsplit(root)
        if parsed.scheme in ("http", "https"):
            if parsed.query or parsed.fragment:
                raise WorkflowError(
                    "object-store root URL cannot contain a query or fragment"
                )
            self.kind = "http"
            self.root = root.rstrip("/")
            self.path = None
        elif parsed.scheme == "file":
            if parsed.netloc not in ("", "localhost") or not parsed.path.startswith("/"):
                raise WorkflowError("file object-store URL must be local and absolute")
            self.kind = "filesystem"
            raw_path = urllib.request.url2pathname(parsed.path)
            self.path = Path(raw_path).expanduser().resolve()
            self.root = self.path.as_uri()
        elif parsed.scheme:
            raise WorkflowError(
                f"unsupported object-store URL scheme {parsed.scheme!r}"
            )
        else:
            self.kind = "filesystem"
            path = Path(root).expanduser()
            if not path.is_absolute():
                path = workflow_root / path
            self.path = path.resolve()
            self.root = str(self.path)

    def location(self, key: str) -> str:
        key = normalize_key(key)
        if self.kind == "filesystem":
            assert self.path is not None
            return str(self.path.joinpath(*PurePosixPath(key).parts))
        return f"{self.root}/{key}"

    def _path(self, key: str) -> Path:
        if self.kind != "filesystem" or self.path is None:
            raise WorkflowError("operation requires a filesystem object store")
        key = normalize_key(key)
        destination = self.path.joinpath(*PurePosixPath(key).parts).resolve()
        try:
            destination.relative_to(self.path)
        except ValueError as error:
            raise WorkflowError(f"object key escapes store root: {key!r}") from error
        return destination

    def has(self, key: str) -> bool:
        key = normalize_key(key)
        if self.kind == "filesystem":
            return self._path(key).is_file()
        request = urllib.request.Request(self.location(key), method="HEAD")
        try:
            with urllib.request.urlopen(request):
                return True
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 404:
                return False
            raise WorkflowError(
                f"cannot inspect object {key!r}: HTTP {error.code}"
            ) from error
        except urllib.error.URLError as error:
            raise WorkflowError(f"cannot inspect object {key!r}: {error}") from error

    def put(self, content: bytes) -> dict[str, Any]:
        digest = hashlib.sha256(content).hexdigest()
        key = object_key(digest)
        if not self.has(key):
            if self.kind == "filesystem":
                destination = self._path(key)
                atomic_write(destination, content)
            else:
                request = urllib.request.Request(
                    self.location(key),
                    data=content,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "If-None-Match": "*",
                    },
                    method="PUT",
                )
                try:
                    with urllib.request.urlopen(request):
                        pass
                except urllib.error.HTTPError as error:
                    error.close()
                    if error.code != 412:
                        raise WorkflowError(
                            f"cannot write object {key!r}: HTTP {error.code}"
                        ) from error
                except urllib.error.URLError as error:
                    raise WorkflowError(
                        f"cannot write object {key!r}: {error}"
                    ) from error
        return {"key": key, "sha256": digest, "size": len(content)}

    def put_file(self, path: Path) -> dict[str, Any]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
                size += len(block)
        hexdigest = digest.hexdigest()
        key = object_key(hexdigest)
        if not self.has(key):
            if self.kind == "filesystem":
                destination = self._path(key)
                destination.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    dir=destination.parent, prefix=f".{destination.name}."
                )
                try:
                    with os.fdopen(descriptor, "wb") as output, path.open(
                        "rb"
                    ) as source:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary_name, destination)
                except BaseException:
                    Path(temporary_name).unlink(missing_ok=True)
                    raise
            else:
                try:
                    with path.open("rb") as source:
                        request = urllib.request.Request(
                            self.location(key),
                            data=source,
                            headers={
                                "Content-Type": "application/octet-stream",
                                "Content-Length": str(size),
                                "If-None-Match": "*",
                            },
                            method="PUT",
                        )
                        with urllib.request.urlopen(request):
                            pass
                except urllib.error.HTTPError as error:
                    error.close()
                    if error.code != 412:
                        raise WorkflowError(
                            f"cannot write object {key!r}: HTTP {error.code}"
                        ) from error
                except urllib.error.URLError as error:
                    raise WorkflowError(
                        f"cannot write object {key!r}: {error}"
                    ) from error
        return {"key": key, "sha256": hexdigest, "size": size}

    def read(self, reference: dict[str, Any]) -> bytes:
        try:
            key = normalize_key(str(reference["key"]))
            expected_digest = str(reference["sha256"])
            expected_size = int(reference["size"])
        except (KeyError, TypeError, ValueError) as error:
            raise WorkflowError("invalid object reference") from error
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
            or key != object_key(expected_digest)
        ):
            raise WorkflowError("object reference key does not match its SHA-256 digest")
        try:
            if self.kind == "filesystem":
                content = self._path(key).read_bytes()
            else:
                with urllib.request.urlopen(self.location(key)) as response:
                    content = response.read()
        except urllib.error.HTTPError as error:
            error.close()
            raise WorkflowError(
                f"cannot read object {key!r}: HTTP {error.code}"
            ) from error
        except (OSError, urllib.error.URLError) as error:
            raise WorkflowError(f"cannot read object {key!r}: {error}") from error
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != expected_digest or len(content) != expected_size:
            raise WorkflowError(
                f"object {key!r} failed digest or size verification"
            )
        return content

    def verify(self, reference: dict[str, Any]) -> None:
        self.read(reference)

    def materialize(self, reference: dict[str, Any], destination: Path) -> None:
        key = normalize_key(str(reference.get("key", "")))
        expected_digest = str(reference.get("sha256", ""))
        try:
            expected_size = int(reference["size"])
        except (KeyError, TypeError, ValueError) as error:
            raise WorkflowError("invalid object reference") from error
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
            or key != object_key(expected_digest)
        ):
            raise WorkflowError("object reference key does not match its SHA-256 digest")
        destination = destination.expanduser().resolve()
        if self.kind == "filesystem" and destination == self._path(key):
            self.verify(reference)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{destination.name}."
        )
        digest = hashlib.sha256()
        size = 0
        try:
            if self.kind == "filesystem":
                source_context = self._path(key).open("rb")
            else:
                source_context = urllib.request.urlopen(self.location(key))
            with source_context as source, os.fdopen(descriptor, "wb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
                    digest.update(block)
                    size += len(block)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != expected_digest or size != expected_size:
                raise WorkflowError(
                    f"object {key!r} failed digest or size verification"
                )
            os.replace(temporary_name, destination)
        except urllib.error.HTTPError as error:
            error.close()
            Path(temporary_name).unlink(missing_ok=True)
            raise WorkflowError(
                f"cannot materialize object {key!r}: HTTP {error.code}"
            ) from error
        except (OSError, urllib.error.URLError) as error:
            Path(temporary_name).unlink(missing_ok=True)
            raise WorkflowError(f"cannot materialize object {key!r}: {error}") from error
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise

class Repository:
    """A workflow repository rooted at a directory containing .cga."""

    def __init__(self, root: Path, cga_dir: Path | None = None) -> None:
        self.root = root.expanduser().resolve()
        self.cga_dir = (cga_dir or self.root / ".cga").expanduser().resolve()
        self.config_path = self.cga_dir / "config"
        self.manifest_path = self.cga_dir / "manifest.json"
        self.head_path = self.cga_dir / "HEAD"
        self.current_path = self.cga_dir / "current.json"
        self.lock_path = self.cga_dir / "lock"

    @classmethod
    def init(cls, directory: Path, store_root: str | None = None) -> "Repository":
        root = directory.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        repository = cls(root)
        if repository.cga_dir.exists() and any(repository.cga_dir.iterdir()):
            raise WorkflowError(f"workflow already initialized: {repository.cga_dir}")
        repository.cga_dir.mkdir(parents=True, exist_ok=True)
        config = {
            "format_version": FORMAT_VERSION,
            "workflow": {"name": root.name},
            "object_store": {"root": store_root or ".cga/objects"},
        }
        manifest = {
            "format_version": FORMAT_VERSION,
            "next_chain_id": 0,
            "next_artifact_id": 0,
            "next_attempt_id": 0,
            "chains": {},
            "nodes": {},
            "artifacts": {},
            "attempts": {},
        }
        atomic_write(repository.config_path, canonical_json(config))
        atomic_write(repository.manifest_path, canonical_json(manifest))
        atomic_write(repository.head_path, b"\n")
        atomic_write(repository.current_path, canonical_json(EMPTY_STATE))
        repository.lock_path.touch()
        repository.store().put(canonical_json(EMPTY_STATE))
        return repository

    @classmethod
    def discover(cls, start: Path | None = None) -> "Repository":
        explicit = os.environ.get("CGA_DIR")
        if explicit:
            cga_dir = Path(explicit).expanduser().resolve()
            if not (cga_dir / "config").is_file():
                raise WorkflowError(f"not a cga workflow: {cga_dir}")
            return cls(cga_dir.parent, cga_dir)
        current = (start or Path.cwd()).expanduser().resolve()
        for directory in (current, *current.parents):
            if (directory / ".cga" / "config").is_file():
                return cls(directory)
        raise WorkflowError(f"no .cga directory found from {current}")

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.cga_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def load_config(self) -> dict[str, Any]:
        config = self._load_json(self.config_path, "configuration")
        if config.get("format_version") != FORMAT_VERSION:
            raise WorkflowError(
                f"unsupported workflow format: {config.get('format_version')!r}"
            )
        if not isinstance(config.get("object_store"), dict):
            raise WorkflowError("configuration must contain object_store")
        return config

    def write_config(self, config: dict[str, Any]) -> None:
        atomic_write(self.config_path, canonical_json(config))

    def load_manifest(self) -> dict[str, Any]:
        manifest = self._load_json(self.manifest_path, "manifest")
        if manifest.get("format_version") != FORMAT_VERSION:
            raise WorkflowError(
                f"unsupported manifest format: {manifest.get('format_version')!r}"
            )
        manifest.setdefault("attempts", {})
        manifest.setdefault("next_attempt_id", 0)
        for key in ("chains", "nodes", "artifacts", "attempts"):
            if not isinstance(manifest.get(key), dict):
                raise WorkflowError(f"manifest {key!r} must be an object")
        return manifest

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        atomic_write(self.manifest_path, canonical_json(manifest))

    @staticmethod
    def _load_json(path: Path, description: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise WorkflowError(f"cannot read {description} {path}: {error}") from error
        except json.JSONDecodeError as error:
            raise WorkflowError(f"invalid JSON in {description} {path}: {error}") from error
        if not isinstance(value, dict):
            raise WorkflowError(f"{description} must be a JSON object")
        return value

    def store(self, root_override: str | None = None) -> ObjectStore:
        config = self.load_config()
        configured = config["object_store"].get("root")
        root = root_override or os.environ.get("CGA_OBJECT_STORE") or configured
        return ObjectStore(root, self.root)

    def head_chain(self) -> str | None:
        try:
            value = self.head_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise WorkflowError(f"cannot read {self.head_path}: {error}") from error
        return value or None

    def _set_head_chain(self, chain_id: str | None) -> None:
        atomic_write(self.head_path, ((chain_id or "") + "\n").encode())

    def resolve_chain(
        self, manifest: dict[str, Any], value: str | None
    ) -> tuple[str, dict[str, Any]]:
        requested = value or self.head_chain()
        if not requested:
            raise WorkflowError("no current chain; run 'cga chain start'")
        chains = manifest["chains"]
        candidates = [requested]
        if requested.isdigit():
            candidates.append(f"cga_{requested}")
        for candidate in candidates:
            chain = chains.get(candidate)
            if isinstance(chain, dict):
                return candidate, chain
        named = [
            (chain_id, chain)
            for chain_id, chain in chains.items()
            if isinstance(chain, dict) and chain.get("name") == requested
        ]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            raise WorkflowError(f"ambiguous chain name: {requested!r}")
        raise WorkflowError(f"unknown chain: {requested!r}")

    def resolve_node(
        self, manifest: dict[str, Any], value: str
    ) -> tuple[str, dict[str, Any]]:
        node = manifest["nodes"].get(value)
        if isinstance(node, dict):
            return value, node
        chain_id, chain = self.resolve_chain(manifest, value)
        head = chain.get("head")
        if not isinstance(head, str):
            raise WorkflowError(f"chain {chain_id} has no steps")
        node = manifest["nodes"].get(head)
        if not isinstance(node, dict):
            raise WorkflowError(f"chain {chain_id} references unknown head {head!r}")
        return head, node

    def state_reference(
        self, manifest: dict[str, Any], chain: dict[str, Any]
    ) -> dict[str, Any]:
        head = chain.get("head")
        if isinstance(head, str):
            node = manifest["nodes"].get(head)
            if not isinstance(node, dict) or not isinstance(node.get("state"), dict):
                raise WorkflowError(f"invalid chain head: {head!r}")
            return node["state"]
        reference = chain.get("base_state")
        if not isinstance(reference, dict):
            raise WorkflowError("chain has no valid base state")
        return reference

    def load_state(
        self, reference: dict[str, Any], store: ObjectStore | None = None
    ) -> dict[str, Any]:
        content = (store or self.store()).read(reference)
        try:
            value = json.loads(content)
        except json.JSONDecodeError as error:
            raise WorkflowError(f"state object is not valid JSON: {error}") from error
        if not isinstance(value, dict):
            raise WorkflowError("CGAST state object must be a JSON object")
        return value

    def current_state(
        self, manifest: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        document = manifest or self.load_manifest()
        _, chain = self.resolve_chain(document, None)
        return self.load_state(self.state_reference(document, chain))

    def start_chain(
        self, from_revision: str | None = None, name: str | None = None
    ) -> str:
        with self.locked():
            manifest = self.load_manifest()
            name = self._validate_chain_name(manifest, name)
            store = self.store()
            parent: str | None = None
            if from_revision:
                parent, node = self.resolve_node(manifest, from_revision)
                reference = node["state"]
            else:
                reference = store.put(canonical_json(EMPTY_STATE))
            number = int(manifest["next_chain_id"])
            chain_id = f"cga_{number}"
            manifest["next_chain_id"] = number + 1
            manifest["chains"][chain_id] = {
                "id": chain_id,
                "number": number,
                "name": name,
                "root_parent": parent,
                "head": None,
                "next_sequence": 0,
                "base_state": reference,
                "created_at": utc_now(),
            }
            self.write_manifest(manifest)
            self._set_head_chain(chain_id)
            atomic_write(self.current_path, store.read(reference))
            return chain_id

    def switch_chain(self, value: str) -> str:
        with self.locked():
            manifest = self.load_manifest()
            chain_id, chain = self.resolve_chain(manifest, value)
            content = self.store().read(self.state_reference(manifest, chain))
            self._set_head_chain(chain_id)
            atomic_write(self.current_path, content)
            return chain_id

    def rename_chain(self, value: str, name: str) -> str:
        with self.locked():
            manifest = self.load_manifest()
            chain_id, chain = self.resolve_chain(manifest, value)
            chain["name"] = self._validate_chain_name(manifest, name, chain_id)
            self.write_manifest(manifest)
            return chain_id

    @staticmethod
    def _validate_chain_name(
        manifest: dict[str, Any],
        name: str | None,
        current_chain: str | None = None,
    ) -> str | None:
        if name is None:
            return None
        name = name.strip()
        if not name:
            raise WorkflowError("chain name cannot be empty")
        for chain_id, chain in manifest["chains"].items():
            if chain_id != current_chain and chain.get("name") == name:
                raise WorkflowError(f"chain name already exists: {name!r}")
        return name

    def record_state(
        self,
        manifest: dict[str, Any],
        chain_id: str,
        chain: dict[str, Any],
        state: dict[str, Any],
        command: list[str],
        source_step: str,
        execution: dict[str, Any] | None = None,
        source: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> str:
        store = self.store()
        previous_state = self.load_state(
            self.state_reference(manifest, chain), store
        )
        state_reference = store.put(canonical_json(state))
        sequence = int(chain["next_sequence"])
        tool = self._safe_token(command[1] if len(command) > 1 else "cga")
        action = self._safe_token(command[2] if len(command) > 2 else "run")
        node_id = f"{chain_id}_{tool}_{action}_{sequence}"
        if node_id in manifest["nodes"]:
            raise WorkflowError(f"node already exists: {node_id}")
        parent = chain.get("head") or chain.get("root_parent")
        artifacts = self.register_discovered_artifacts(
            manifest, state, node_id, previous_state, tags
        )
        manifest["nodes"][node_id] = {
            "id": node_id,
            "chain": chain_id,
            "sequence": sequence,
            "parent": parent,
            "source_step": source_step,
            "command": command,
            "created_at": utc_now(),
            "state": state_reference,
            "artifacts": artifacts,
            "execution": execution or {},
            "source": source or {},
            "tags": tags or {},
        }
        chain["next_sequence"] = sequence + 1
        chain["head"] = node_id
        self.write_manifest(manifest)
        atomic_write(self.current_path, canonical_json(state))
        return node_id

    def record_attempt(
        self,
        manifest: dict[str, Any],
        chain_id: str | None,
        command: list[str],
        source_step: str,
        execution: dict[str, Any],
        source: dict[str, Any] | None = None,
        error: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> str:
        number = int(manifest.get("next_attempt_id", 0))
        attempt_id = f"attempt_{number}"
        manifest["next_attempt_id"] = number + 1
        parent = None
        if chain_id:
            chain = manifest["chains"].get(chain_id)
            if isinstance(chain, dict):
                parent = chain.get("head") or chain.get("root_parent")
        manifest["attempts"][attempt_id] = {
            "id": attempt_id,
            "chain": chain_id,
            "parent": parent,
            "command": command,
            "source_step": source_step,
            "source": source or {},
            "execution": execution,
            "error": error,
            "tags": tags or {},
            "created_at": utc_now(),
        }
        self.write_manifest(manifest)
        return attempt_id

    @staticmethod
    def _safe_token(value: str) -> str:
        token = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
        return token or "step"

    def register_artifact(
        self,
        manifest: dict[str, Any],
        path: Path,
        logical_name: str,
        kind: str,
        source_node: str | None,
        tags: dict[str, Any] | None = None,
    ) -> str:
        if not path.is_file():
            raise WorkflowError(f"artifact is not a regular file: {path}")
        reference = self.store().put_file(path)
        for artifact_id, artifact in manifest["artifacts"].items():
            if (
                artifact.get("logical_name") == logical_name
                and artifact.get("sha256") == reference["sha256"]
                and artifact.get("source_node") == source_node
            ):
                artifact["tags"] = merge_tag_documents(
                    artifact.get("tags"),
                    tags,
                )
                return artifact_id
        number = int(manifest["next_artifact_id"])
        artifact_id = f"artifact_{number}"
        manifest["next_artifact_id"] = number + 1
        manifest["artifacts"][artifact_id] = {
            "id": artifact_id,
            "logical_name": logical_name,
            "filename": path.name,
            "kind": kind,
            **reference,
            "source_node": source_node,
            "tags": tags or {},
            "created_at": utc_now(),
        }
        return artifact_id

    def register_discovered_artifacts(
        self,
        manifest: dict[str, Any],
        state: dict[str, Any],
        source_node: str,
        previous_state: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> list[str]:
        candidates: dict[Path, tuple[str, str]] = {}
        base = Path(
            os.environ.get("CGAST_ROOT")
            or os.environ.get("CGA_ROOT")
            or self.root
        ).expanduser().resolve()

        def resolve(value: str) -> Path:
            path = Path(value).expanduser()
            return path.resolve() if path.is_absolute() else (base / path).resolve()

        def add_candidate(path: Path, logical_name: str, kind: str) -> None:
            existing = candidates.get(path)
            if existing is None or len(logical_name) < len(existing[0]):
                candidates[path] = (logical_name, kind)

        def walk(
            value: Any,
            previous: Any = None,
            key: str | None = None,
            prefix: str = "",
        ) -> None:
            if isinstance(value, dict):
                previous_dict = previous if isinstance(previous, dict) else {}
                for child_key, child in value.items():
                    child_prefix = f"{prefix}.{child_key}" if prefix else child_key
                    walk(
                        child,
                        previous_dict.get(child_key),
                        child_key,
                        child_prefix,
                    )
            elif isinstance(value, list):
                previous_list = previous if isinstance(previous, list) else []
                for index, child in enumerate(value):
                    previous_child = (
                        previous_list[index] if index < len(previous_list) else None
                    )
                    walk(child, previous_child, key, f"{prefix}[{index}]")
            elif isinstance(value, str) and key in ARTIFACT_FILE_KEYS:
                if previous == value:
                    return
                path = resolve(value)
                if path.is_file():
                    add_candidate(path, prefix, key)
            elif isinstance(value, str) and key in ARTIFACT_DIRECTORY_KEYS:
                if previous == value:
                    return
                directory = resolve(value)
                if directory.is_dir():
                    for path in sorted(directory.rglob("*")):
                        if path.is_file():
                            relative = path.relative_to(directory).as_posix()
                            add_candidate(path, f"{key}/{relative}", key)

        walk(state, previous_state or {})
        scanned_json: set[Path] = set()
        while True:
            pending = [
                (path, logical_name)
                for path, (logical_name, _kind) in candidates.items()
                if path.suffix.lower() == ".json" and path not in scanned_json
            ]
            if not pending:
                break
            for path, logical_name in pending:
                scanned_json.add(path)
                try:
                    document = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                walk(document, None, prefix=f"{logical_name}#content")
        artifact_ids = []
        for path, (logical_name, kind) in sorted(
            candidates.items(), key=lambda item: item[1][0]
        ):
            artifact_ids.append(
                self.register_artifact(
                    manifest, path, logical_name, kind, source_node, tags
                )
            )
        return artifact_ids

    def all_references(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        for chain in manifest["chains"].values():
            reference = chain.get("base_state")
            if isinstance(reference, dict):
                references.append(reference)
        for node in manifest["nodes"].values():
            reference = node.get("state")
            if isinstance(reference, dict):
                references.append(reference)
        for artifact in manifest["artifacts"].values():
            if isinstance(artifact, dict):
                references.append(artifact)
        for node in manifest["nodes"].values():
            execution = node.get("execution")
            if isinstance(execution, dict):
                transcript = execution.get("transcript")
                if isinstance(transcript, dict):
                    references.append(transcript)
        for attempt in manifest["attempts"].values():
            execution = attempt.get("execution")
            if isinstance(execution, dict):
                transcript = execution.get("transcript")
                if isinstance(transcript, dict):
                    references.append(transcript)
        return references

    def verify(self) -> list[str]:
        errors: list[str] = []
        try:
            manifest = self.load_manifest()
            config = self.load_config()
            store = self.store()
        except WorkflowError as error:
            return [str(error)]
        head = self.head_chain()
        if head is not None and head not in manifest["chains"]:
            errors.append(f"HEAD references unknown chain {head!r}")
        for chain_id, chain in manifest["chains"].items():
            chain_head = chain.get("head")
            root_parent = chain.get("root_parent")
            if chain_head is not None and chain_head not in manifest["nodes"]:
                errors.append(
                    f"chain {chain_id!r} references unknown head {chain_head!r}"
                )
            if root_parent is not None and root_parent not in manifest["nodes"]:
                errors.append(
                    f"chain {chain_id!r} references unknown root parent "
                    f"{root_parent!r}"
                )
        for node_id, node in manifest["nodes"].items():
            parent = node.get("parent")
            if parent is not None and parent not in manifest["nodes"]:
                errors.append(f"node {node_id!r} references unknown parent {parent!r}")
            if node.get("chain") not in manifest["chains"]:
                errors.append(
                    f"node {node_id!r} references unknown chain {node.get('chain')!r}"
                )
        for artifact_id, artifact in manifest["artifacts"].items():
            source_node = artifact.get("source_node")
            if source_node is not None and source_node not in manifest["nodes"]:
                errors.append(
                    f"artifact {artifact_id!r} references unknown source node "
                    f"{source_node!r}"
                )
        for attempt_id, attempt in manifest["attempts"].items():
            chain_id = attempt.get("chain")
            parent = attempt.get("parent")
            if chain_id is not None and chain_id not in manifest["chains"]:
                errors.append(
                    f"attempt {attempt_id!r} references unknown chain {chain_id!r}"
                )
            if parent is not None and parent not in manifest["nodes"]:
                errors.append(
                    f"attempt {attempt_id!r} references unknown parent {parent!r}"
                )
        references = {
            reference.get("key"): reference
            for reference in self.all_references(manifest)
            if isinstance(reference.get("key"), str)
        }
        for reference in references.values():
            try:
                store.verify(reference)
            except WorkflowError as error:
                errors.append(str(error))
        if config["object_store"].get("root") is None:
            errors.append("object_store.root is not configured")
        return errors

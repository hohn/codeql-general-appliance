from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import database_identity
from workflow import WorkflowError

from .db import Database


SUCCESS = {"succeeded", "succeeded-after-repair"}
META_COLUMNS = [
    "content_hash", "build_cid", "git_branch", "git_commit_id",
    "git_owner", "git_repo", "ingestion_datetime_utc", "primary_language",
    "result_url", "tool_name", "tool_version", "projname", "db_file_size",
]

PROMOTION_SQL = r"""
SELECT jsonb_build_object(
  'job', to_jsonb(j),
  'attempt', to_jsonb(a)
)::text
FROM cgactl.jobs j
JOIN cgactl.attempts a
  ON a.job_id = j.job_id AND a.attempt = j.attempt_count
WHERE j.job_id = :'job';
"""

SUCCESSFUL_JOBS_SQL = r"""
SELECT COALESCE(jsonb_agg(jsonb_build_object(
  'job_id', j.job_id,
  'status', j.status,
  'artifact', a.result->'artifacts'->'database'
) ORDER BY j.job_id), '[]'::jsonb)::text
FROM cgactl.jobs j
JOIN cgactl.attempts a
  ON a.job_id = j.job_id AND a.attempt = j.attempt_count
WHERE j.status IN ('succeeded', 'succeeded-after-repair');
"""


class PromotionError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(argv: list[str]) -> None:
    proc = subprocess.run(argv, text=True, capture_output=True)
    if proc.returncode:
        raise PromotionError(proc.stderr.strip() or proc.stdout.strip() or
                             f"command failed: {argv[0]}")


def _fetch(uri: str, destination: Path) -> None:
    parsed = urlparse(uri)
    if parsed.scheme == "incus":
        if not parsed.netloc or not parsed.path.startswith("/"):
            raise PromotionError(f"invalid Incus artifact URI: {uri}")
        _run(["incus", "file", "pull",
              f"{parsed.netloc}{unquote(parsed.path)}", str(destination)])
    elif parsed.scheme == "file":
        shutil.copyfile(Path(unquote(parsed.path)), destination)
    else:
        raise PromotionError(f"unsupported artifact URI scheme: {uri}")


def _validate_bundle(bundle: Path, codeql: str, scratch: Path) -> dict:
    target = scratch / "unbundled"
    target.mkdir()
    _run([codeql, "database", "unbundle", f"--target={target}",
          str(bundle)])
    databases = list(target.glob("*/codeql-database.yml"))
    if len(databases) != 1:
        raise PromotionError("bundle does not contain exactly one database")
    database = databases[0].parent
    proc = subprocess.run(
        [codeql, "resolve", "database", "--format=json", str(database)],
        text=True, capture_output=True)
    if proc.returncode:
        raise PromotionError(proc.stderr.strip() or
                             "CodeQL could not resolve promoted database")
    return json.loads(proc.stdout)


def _catalogue(path: Path, row: dict) -> None:
    conn = sqlite3.connect(path)
    try:
        definitions = ", ".join(
            f"{name} INTEGER" if name == "db_file_size" else f"{name} TEXT"
            for name in META_COLUMNS)
        conn.execute(f"CREATE TABLE IF NOT EXISTS metadata ({definitions})")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM metadata WHERE build_cid = ?",
                     (row["build_cid"],))
        conn.execute(
            f"INSERT INTO metadata ({', '.join(META_COLUMNS)}) VALUES "
            f"({', '.join('?' for _ in META_COLUMNS)})",
            tuple(row[name] for name in META_COLUMNS))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def collection_status(collection: Path, verify: bool = False) -> dict:
    catalogue = collection / "metadata.sql"
    rows = []
    if catalogue.is_file():
        conn = sqlite3.connect(catalogue)
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM metadata ORDER BY build_cid")]
        finally:
            conn.close()
    missing, mismatched = [], []
    for row in rows:
        parsed = urlparse(row["result_url"])
        path = Path(unquote(parsed.path)) if parsed.scheme == "file" else None
        if path is None or not path.is_file():
            missing.append(row["build_cid"])
        elif verify and _sha256(path) != row["content_hash"]:
            mismatched.append(row["build_cid"])
    archives = list((collection / "databases").glob("**/*_db.zip")) \
        if (collection / "databases").is_dir() else []
    provenance = list((collection / "provenance").glob("*/result.json")) \
        if (collection / "provenance").is_dir() else []
    return {
        "collection": str(collection.resolve()),
        "catalogue": str(catalogue.resolve()),
        "catalogue_rows": len(rows),
        "archives": len(archives),
        "provenance_records": len(provenance),
        "missing_artifacts": missing,
        "digest_mismatches": mismatched,
        "verified": bool(verify),
    }


def reconcile(db: Database, collection: Path) -> dict:
    successful = db.json(SUCCESSFUL_JOBS_SQL) or []
    catalogue = collection / "metadata.sql"
    promoted = set()
    if catalogue.is_file():
        conn = sqlite3.connect(catalogue)
        try:
            promoted = {row[0] for row in conn.execute(
                "SELECT build_cid FROM metadata")}
        finally:
            conn.close()
    successful_ids = {item["job_id"] for item in successful}
    unavailable = sorted(
        item["job_id"] for item in successful
        if not (item.get("artifact") or {}).get("uri") or
        not (item.get("artifact") or {}).get("sha256"))
    return {
        "successful_jobs": len(successful),
        "promoted": sorted(successful_ids & promoted),
        "pending_promotion": sorted(successful_ids - promoted -
                                    set(unavailable)),
        "missing_artifact_metadata": unavailable,
        "catalogue_without_successful_job": sorted(promoted - successful_ids),
    }


def promote(db: Database, job_id: str, collection: Path,
            codeql: str = "codeql") -> dict:
    record = db.json(PROMOTION_SQL, {"job": job_id})
    if not record:
        raise PromotionError(f"unknown job or missing attempt: {job_id}")
    job, attempt = record["job"], record["attempt"]
    if job["status"] not in SUCCESS or attempt["status"] not in SUCCESS:
        raise PromotionError(f"job is not successful: {job['status']}")
    result = attempt.get("result") or {}
    artifact = (result.get("artifacts") or {}).get("database") or {}
    uri, expected = artifact.get("uri"), artifact.get("sha256")
    if not uri or not expected:
        raise PromotionError("successful attempt lacks database URI/SHA-256")

    spec = job.get("spec") or {}
    package = spec.get("package")
    language = spec.get("language")
    if not package or not language:
        raise PromotionError("job specification lacks package or language")
    owner = "debian"
    try:
        repo = database_identity.repository(package, expected)
    except WorkflowError as exc:
        raise PromotionError(str(exc)) from exc
    destination = (collection / "databases" / owner / repo /
                   f"{owner}_{repo}_db.zip")
    provenance = collection / "provenance" / job_id / "result.json"
    collection.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
            prefix=".promote-", dir=collection) as raw:
        scratch = Path(raw)
        staged = scratch / "database.zip"
        _fetch(uri, staged)
        actual = _sha256(staged)
        if actual != expected:
            raise PromotionError(
                f"artifact digest mismatch: expected {expected}, got {actual}")
        expected_size = artifact.get("size_bytes")
        if expected_size is not None and staged.stat().st_size != expected_size:
            raise PromotionError("artifact size does not match result record")
        staged_extras = {}
        for name, extra in (result.get("artifacts") or {}).items():
            if name == "database":
                continue
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                raise PromotionError(f"unsafe artifact name: {name}")
            extra_uri, extra_digest = extra.get("uri"), extra.get("sha256")
            if not extra_uri or not extra_digest:
                raise PromotionError(f"artifact lacks URI/SHA-256: {name}")
            extra_staged = scratch / f"artifact-{name}"
            _fetch(extra_uri, extra_staged)
            if _sha256(extra_staged) != extra_digest:
                raise PromotionError(f"artifact digest mismatch: {name}")
            extra_size = extra.get("size_bytes")
            if (extra_size is not None and
                    extra_staged.stat().st_size != extra_size):
                raise PromotionError(f"artifact size mismatch: {name}")
            staged_extras[name] = (extra_staged, extra, extra_uri)
        resolved = _validate_bundle(staged, codeql, scratch)

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if _sha256(destination) != actual:
                raise PromotionError(f"collection collision: {destination}")
        else:
            os.replace(staged, destination)

        preserved_artifacts = {}
        artifact_dir = provenance.parent / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for name, (extra_staged, extra, extra_uri) in staged_extras.items():
            suffix = Path(unquote(urlparse(extra_uri).path)).suffix
            extra_destination = artifact_dir / f"{name}{suffix}"
            if extra_destination.exists():
                if _sha256(extra_destination) != extra["sha256"]:
                    raise PromotionError(
                        f"collection collision: {extra_destination}")
            else:
                os.replace(extra_staged, extra_destination)
            preserved_artifacts[name] = {
                "path": str(extra_destination.resolve()),
                "sha256": extra["sha256"],
                "size_bytes": extra_destination.stat().st_size,
            }

        promoted = {
            "schema_version": 1,
            "promoted_at": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
            "job": job,
            "attempt": attempt,
            "collection_artifact": {
                "path": str(destination.resolve()), "sha256": actual,
                "size_bytes": destination.stat().st_size,
                "codeql_database": resolved,
            },
            "preserved_artifacts": preserved_artifacts,
        }
        provenance.parent.mkdir(parents=True, exist_ok=True)
        staged_provenance = scratch / "result.json"
        staged_provenance.write_text(
            json.dumps(promoted, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        os.replace(staged_provenance, provenance)

    toolchain = job.get("toolchain_digest", "")
    tool_version = toolchain.split(":", 1)[1].split("-", 1)[0] \
        if toolchain.startswith("codeql:") else toolchain
    row = {
        "content_hash": expected,
        "build_cid": job_id,
        "git_branch": job["variant"],
        "git_commit_id": spec.get("version", ""),
        "git_owner": owner,
        "git_repo": repo,
        "ingestion_datetime_utc": promoted["promoted_at"],
        "primary_language": language,
        "result_url": destination.resolve().as_uri(),
        "tool_name": "codeql",
        "tool_version": tool_version,
        "projname": (f"debian/{package}@{spec.get('version', '')} "
                     f"[{job['mode']}]"),
        "db_file_size": destination.stat().st_size,
    }
    _catalogue(collection / "metadata.sql", row)
    report = preserved_artifacts.get("resource_report", {}).get("path")
    db.json(
        "SELECT cgactl.record_promotion(:'job', :'collection', :'archive', "
        ":'provenance', :'report')::text;",
        {"job": job_id, "collection": str(collection),
         "archive": str(destination.resolve()),
         "provenance": str(provenance.resolve()), "report": report or ""})
    return {
        "job_id": job_id, "status": "promoted", "owner": owner,
        "repo": repo, "archive": str(destination.resolve()),
        "provenance": str(provenance.resolve()),
        "catalogue": str((collection / "metadata.sql").resolve()),
        "sha256": expected, "size_bytes": destination.stat().st_size,
    }


def promote_pending(db: Database, collection: Path,
                    codeql: str = "codeql") -> dict:
    claimed = db.json("SELECT cgactl.claim_promotion()::text;")
    if not claimed:
        return {"claimed": False}
    job_id = claimed["job_id"]
    try:
        result = promote(db, job_id, collection, codeql)
        return {"claimed": True, "promoted": True, "result": result}
    except Exception as exc:
        db.json("SELECT cgactl.fail_promotion(:'job', :'error')::text;",
                {"job": job_id, "error": str(exc)})
        return {"claimed": True, "promoted": False, "job_id": job_id,
                "error": str(exc)}

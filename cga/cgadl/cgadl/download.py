"""Fetching bytes over HTTP(S): the catalogue index and the databases.

``getmeta`` pulls a ``metadata.sql`` from a URL (in case the catalogue is not
already present). ``download`` reads the selection file and fetches every
listed ``result_url`` into the qldbstore on-disk layout that the rest of MRVA
expects::

    <dbdir>/<owner>/<repo>/<owner>_<repo>_db.zip

Only the standard library is used (``urllib``), matching the cga skeleton.
"""

from __future__ import annotations

import hashlib
import http.client
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# A conservative timeout so a stuck origin doesn't hang the whole run.
_TIMEOUT = 60


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _fetch(url: str, dest: Path, *, resume: bool = False,
           expected_hash: str = "",
           progress: Callable[[int, Optional[int]], None] | None = None) -> int:
    """Retain partial bytes on failure; publish only a complete, verified file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    offset = tmp.stat().st_size if resume and expected_hash and tmp.exists() \
        and urllib.parse.urlsplit(url).scheme in ("http", "https") else 0
    headers = {"User-Agent": "cgadl", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=_TIMEOUT)
    except urllib.error.HTTPError as exc:
        if exc.code != 416 or not offset:
            exc.close()
            raise
        exc.close()
        if _sha256(tmp) == expected_hash:
            tmp.replace(dest)
            if progress:
                progress(offset, offset)
            return offset
        print(f"cgadl: resume rejected for {dest}; restarting transfer",
              file=sys.stderr, flush=True)
        offset = 0
        response = urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "cgadl", "Accept-Encoding": "identity"}),
            timeout=_TIMEOUT)
    with response as resp:
        if resp.status == 206:
            content_range = re.fullmatch(
                r"bytes (\d+)-(\d+)/(\d+)", resp.headers.get("Content-Range", ""))
            if (not offset or content_range is None
                    or int(content_range[1]) != offset
                    or int(content_range[2]) + 1 != int(content_range[3])
                    or int(content_range[3]) <= offset):
                raise ValueError(f"invalid resume Content-Range for {url}")
            total = int(content_range[3])
        else:
            if offset:
                print(f"cgadl: server ignored Range for {dest}; restarting transfer",
                      file=sys.stderr, flush=True)
            offset = 0
            length = resp.headers.get("Content-Length")
            total = int(length) if length is not None else None
        received = offset
        if progress:
            progress(received, total)
        last_report = time.monotonic()
        with tmp.open("ab" if offset else "wb") as out:
            while block := resp.read(1024 * 1024):
                out.write(block)
                received += len(block)
                now = time.monotonic()
                if progress and now - last_report >= 1:
                    progress(received, total)
                    last_report = now
        if total is not None and received != total:
            raise OSError(f"incomplete transfer for {url}: {received}/{total} bytes")
        if progress:
            progress(received, total)
    size = tmp.stat().st_size
    if expected_hash and _sha256(tmp) != expected_hash:
        raise ValueError(f"SHA-256 mismatch for {url}; partial file retained at {tmp}")
    tmp.replace(dest)
    return size


def getmeta(url: str, outdir: Path, filename: str = "metadata.sql") -> Path:
    """Fetch a catalogue index from ``url`` into ``outdir/filename``."""
    outdir = Path(outdir)
    dest = outdir / filename
    _fetch(url, dest)
    return dest


def getmeta_url(url: str, dest: Path) -> Path:
    """Fetch a catalogue index from ``url`` directly into ``dest``."""
    _fetch(url, Path(dest))
    return Path(dest)


def db_dest(dbdir: Path, owner: str, repo: str) -> Path:
    """qldbstore path for one database: <dbdir>/<owner>/<repo>/<o>_<r>_db.zip."""
    return Path(dbdir) / owner / repo / f"{owner}_{repo}_db.zip"


@dataclass
class DownloadResult:
    """Outcome for a single database in a download run."""
    owner: str
    repo: str
    url: str
    dest: Path
    status: str  # "downloaded" | "skipped" | "error" | "planned"
    size: int = 0
    error: str = ""


def download(rows: List[Dict[str, Any]],
             dbdir: Path,
             force: bool = False,
             dry_run: bool = False,
             progress: Optional[Any] = None,
             transfer_progress: Callable[[str, str, int, Optional[int]], None] | None = None
             ) -> List[DownloadResult]:
    """Download every selected database into the qldbstore layout.

    Verified existing files are skipped unless ``force``. Hash-addressed HTTP
    partials resume with Range; other transfers restart. ``progress`` reports
    completed files; ``transfer_progress`` reports byte counts during transfers.
    """
    results: List[DownloadResult] = []
    for row in rows:
        owner = str(row.get("git_owner") or "")
        repo = str(row.get("git_repo") or "")
        url = str(row.get("result_url") or "")
        expected_hash = str(row.get("content_hash") or "")
        dest = db_dest(dbdir, owner, repo)

        if not owner or not repo or not url:
            res = DownloadResult(owner, repo, url, dest, "error",
                                 error="missing git_owner/git_repo/result_url")
        elif dry_run:
            res = DownloadResult(owner, repo, url, dest, "planned")
        elif dest.exists() and not force:
            if expected_hash and _sha256(dest) != expected_hash:
                res = DownloadResult(owner, repo, url, dest, "error",
                                     error="cached archive SHA-256 mismatch; "
                                           "use download --force to replace it")
            else:
                res = DownloadResult(owner, repo, url, dest, "skipped",
                                     size=dest.stat().st_size)
        else:
            def report_bytes(received: int, total: Optional[int]) -> None:
                if transfer_progress:
                    transfer_progress(owner, repo, received, total)

            try:
                size = _fetch(url, dest, resume=not force,
                              expected_hash=expected_hash, progress=report_bytes)
                res = DownloadResult(owner, repo, url, dest, "downloaded",
                                     size=size)
            except (OSError, ValueError, http.client.HTTPException) as exc:
                res = DownloadResult(owner, repo, url, dest, "error",
                                     error=str(exc))

        results.append(res)
        if progress is not None:
            progress(res)
    return results

"""Standard-library HTTP client used by the cgamr CGAST commands."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict


class ClientError(RuntimeError):
    """A request failed or returned an unusable response."""


def _request(url: str, method: str = "GET", data: bytes | None = None,
             content_type: str | None = None, user: str | None = None,
             bearer_token: str | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    if user:
        req.add_header("X-MRVA-User", user)
    if bearer_token:
        req.add_header("Authorization", f"Bearer {bearer_token}")
    try:
        with urllib.request.urlopen(req) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise ClientError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ClientError(f"request failed for {url}: {exc.reason}") from exc


def _json_request(url: str, method: str = "GET", data: bytes | None = None,
                  content_type: str | None = None, user: str | None = None,
                  bearer_token: str | None = None) -> Dict[str, Any]:
    raw = _request(url, method, data, content_type, user, bearer_token)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError(f"invalid JSON from {url}: {exc}") from exc
    if not isinstance(value, dict):
        raise ClientError(f"expected a JSON object from {url}")
    return value


def submit(server: str, controller_owner: str, controller_repo: str,
           language: str, repositories: list[str], pack: Path,
           user: str | None = None,
           bearer_token: str | None = None) -> Dict[str, Any]:
    payload = {
        "action_repo_ref": "",
        "language": language,
        "query_pack": base64.b64encode(pack.read_bytes()).decode("ascii"),
        "repositories": repositories,
    }
    data = json.dumps(payload).encode("utf-8")
    url = (f"{server.rstrip('/')}/repos/{controller_owner}/{controller_repo}"
           "/code-scanning/codeql/variant-analyses")
    return _json_request(url, "POST", data, "application/json", user,
                         bearer_token)


def status(server: str, controller_owner: str, controller_repo: str,
           session_id: int, user: str | None = None,
           bearer_token: str | None = None) -> Dict[str, Any]:
    url = (f"{server.rstrip('/')}/repos/{controller_owner}/{controller_repo}"
           f"/code-scanning/codeql/variant-analyses/{session_id}")
    return _json_request(url, user=user, bearer_token=bearer_token)


def download_metadata(server: str, controller_owner: str,
                      controller_repo: str, session_id: int, owner: str,
                      repo: str, user: str | None = None,
                      bearer_token: str | None = None) -> Dict[str, Any]:
    url = (f"{server.rstrip('/')}/repos/{controller_owner}/{controller_repo}"
           f"/code-scanning/codeql/variant-analyses/{session_id}/repos/"
           f"{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}")
    return _json_request(url, user=user, bearer_token=bearer_token)


def download_artifact(artifact_url: str, server: str, destination: Path,
                      user: str | None = None,
                      bearer_token: str | None = None) -> int:
    """Fetch an artifact, rebasing the server's host/scheme for local runs."""
    parsed = urllib.parse.urlsplit(artifact_url)
    tail = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    data = _request(f"{server.rstrip('/')}{tail}", user=user,
                    bearer_token=bearer_token)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return len(data)

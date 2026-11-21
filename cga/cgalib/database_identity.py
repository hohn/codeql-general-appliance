"""Stable identities for bundled CodeQL databases."""

import re

from workflow import WorkflowError, require_safe_name


def repository(repo: str, content_hash: str) -> str:
    require_safe_name(repo, "repository")
    if not isinstance(content_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", content_hash):
        raise WorkflowError("database content_hash must be a SHA-256 digest")
    suffix = "-" + content_hash
    return repo if repo.endswith(suffix) else repo + suffix


def normalize(row: dict) -> dict:
    """Keep upstream catalogue rows intact; qualify identities in selections."""
    result = dict(row)
    if result.get("content_hash"):
        result["git_repo"] = repository(
            result["git_repo"], result["content_hash"])
    return result

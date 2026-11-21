"""Controlled CGA use tags and readable profile expansion."""

from __future__ import annotations

import re
from typing import Any

from .repository import WorkflowError


CONTROLLED_VALUES = {
    "audience": {"user", "operator", "system"},
    "prominence": {"primary", "detail", "diagnostic"},
    "searchable": {"true", "false"},
    "sensitivity": {"normal", "local-sensitive", "secret"},
    "presentation": {"progress", "collection", "summary"},
}
EXTENSIBLE_KEYS = {"subject"}
PROFILES = {
    "user:viewable": (
        "audience:user",
        "prominence:detail",
    ),
    "user:show-progress": (
        "audience:user",
        "presentation:progress",
    ),
    "user:primary-interest-data": (
        "audience:user",
        "prominence:primary",
        "subject:human-results",
    ),
}
TOKEN = re.compile(r"[a-z][a-z0-9-]*\Z")


def normalize(raw_tags: list[str] | None) -> dict[str, Any]:
    profiles: list[str] = []
    expanded: list[str] = []
    for raw in raw_tags or []:
        value = raw.strip().lower()
        if value in PROFILES:
            profiles.append(value)
            expanded.extend(PROFILES[value])
        else:
            expanded.append(value)

    canonical: list[str] = []
    values: dict[str, list[str]] = {}
    for tag in expanded:
        if tag.count(":") != 1:
            raise WorkflowError(
                f"invalid tag {tag!r}; expected a known profile or key:value"
            )
        key, value = tag.split(":", 1)
        if key in CONTROLLED_VALUES:
            if value not in CONTROLLED_VALUES[key]:
                allowed = ", ".join(sorted(CONTROLLED_VALUES[key]))
                raise WorkflowError(
                    f"invalid {key} tag value {value!r}; expected one of {allowed}"
                )
        elif key in EXTENSIBLE_KEYS:
            if not TOKEN.fullmatch(value):
                raise WorkflowError(
                    f"invalid {key} tag value {value!r}; use lowercase tokens"
                )
        else:
            allowed_keys = ", ".join(
                sorted(set(CONTROLLED_VALUES) | EXTENSIBLE_KEYS)
            )
            raise WorkflowError(
                f"unknown tag key {key!r}; expected one of {allowed_keys}"
            )
        normalized = f"{key}:{value}"
        if normalized not in canonical:
            canonical.append(normalized)
        values.setdefault(key, [])
        if value not in values[key]:
            values[key].append(value)

    return {
        "profiles": list(dict.fromkeys(profiles)),
        "canonical": canonical,
        "values": values,
    }


def merge(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    raw: list[str] = []
    profiles: list[str] = []
    for value in (left or {}, right or {}):
        for profile in value.get("profiles", []):
            if profile not in profiles:
                profiles.append(profile)
        raw.extend(value.get("canonical", []))
    result = normalize(raw)
    result["profiles"] = profiles
    return result


def matches(tags: dict[str, Any] | None, wanted: list[str]) -> bool:
    if not wanted:
        return True
    canonical = set((tags or {}).get("canonical", []))
    profiles = set((tags or {}).get("profiles", []))
    return all(tag in canonical or tag in profiles for tag in wanted)


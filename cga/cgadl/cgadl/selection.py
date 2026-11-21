"""The selected-for-download JSON file.

``cgadl select`` and ``cgadl sql`` write this file; ``cgadl download`` and the
``cgadl/detail`` fragment read it. It is deliberately simple JSON: a small
envelope plus one full catalogue row per selected database, so ``download`` has
the ``result_url`` and ``detail`` can show owner/repo/language/size/etc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from database_identity import normalize

SELECTION_VERSION = 1


def write_selection(path: Path, rows: List[Dict[str, Any]]) -> Path:
    """Write ``rows`` (list of full row dicts) to the selection file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": SELECTION_VERSION,
        "count": len(rows),
        "databases": [normalize(row) for row in rows],
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def read_selection(path: Path) -> List[Dict[str, Any]]:
    """Read the selection file and return its list of database rows."""
    path = Path(path)
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    dbs = doc.get("databases", [])
    if not isinstance(dbs, list):
        raise ValueError(f"{path}: 'databases' must be a list")
    return dbs

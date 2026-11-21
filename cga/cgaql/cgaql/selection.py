"""The selected-for-pack JSON file.

``cgaql select`` and ``cgaql sql`` write this file; ``cgaql pack`` and the
``cgaql/detail`` fragment read it. Like cgadl's selection it is deliberately
simple JSON: a small envelope plus one full catalogue row per selected query,
so ``pack`` has the query ``path``/``language`` and ``detail`` can show
id/name/kind/severity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

SELECTION_VERSION = 1


def write_selection(path: Path, rows: List[Dict[str, Any]]) -> Path:
    """Write ``rows`` (list of full query row dicts) to the selection file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": SELECTION_VERSION,
        "count": len(rows),
        "queries": rows,
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def read_selection(path: Path) -> List[Dict[str, Any]]:
    """Read the selection file and return its list of query rows."""
    path = Path(path)
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    queries = doc.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError(f"{path}: 'queries' must be a list")
    return queries

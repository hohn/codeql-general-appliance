"""cgaql -- CodeQL generic appliance: query library handler.

Mirrors cgadl, but over a catalogue of CodeQL *queries* instead of databases:
``index`` scans a tree of ``.ql`` files into a persisted SQLite catalogue;
``select``/``sql`` write a selection JSON; ``pack`` bundles the selected queries
into CodeQL pack bundles for cgamr. Every command is a CGAST (JSON-in/JSON-out)
filter -- see cgalib/cgast.py.

Following the cgadl convention, the executable lives under bin/ and the
logic lives in this sibling package (catalog/selection/pack/serve/cli).
"""

from __future__ import annotations

__all__ = ["catalog", "cli", "pack", "selection", "serve"]

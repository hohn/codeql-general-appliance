"""cgadl -- CodeQL generic appliance: DB library handler.

This package consumes a prebuilt ``metadata.sql`` catalogue (an SQLite index
of CodeQL databases, each with a ``result_url``): it lets a human or an LLM view
the keys, select a subset, persist that subset to a small JSON file, and then
download the selected databases into the qldbstore on-disk layout used by the
rest of MRVA.

Construction of ``metadata.sql`` belongs to CGA preparation; cgadl only reads it.
"""

from __future__ import annotations

__all__ = ["catalog", "selection", "download", "serve", "cli"]

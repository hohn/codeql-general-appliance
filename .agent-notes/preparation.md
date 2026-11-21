# Preparation notes

Start with [preparation usage](../cga/README-prep.md) and its explicit handoff,
not with the controller implementation.

- Preparation and analysis share a tool collection but use separate state.
  Preparation owns source acquisition, toolchain checks, planning, independent
  database builds, validation, catalogues, and query materialization. Analysis
  explicitly imports catalogues with `cgadl getmeta` and query trees with
  `cgaql index`.
- A `cga db build` invocation builds one independent source copy/database and
  emits one database record. `--trace` requires nonempty tracer evidence and
  intercepted processes, without a source-scan marker, before bundling.
- `cga a d` guides fetch/build/index/export over the same plumbing. Source
  manifests support Git, tar/ZIP, and Debian acquisition without requiring a
  CVE. Failed matrices resume from the retained preparation checkpoint; partial
  indexing requires `--allow-partial`. See
  [assistance](../cga/cgaassist/README.md).
- Final database repository identity is upstream name plus the full bundle
  SHA-256, assigned after bundling. Selection normalizes legacy catalogue rows
  without rewriting catalogues or existing selections. Export preserves identity
  and verifies relocated catalogue/manifest references before publication.
- `fetch`/`build --use-llm` uses `cgalib/prep_llm.py` for JSON recipe
  supervision, bounded attempts, command logs, and source/build repairs. Normal
  permissions and deterministic source/trace/bundle checks remain in force. The
  fixed real check is
  `python3 cga/cgaassist/tests/sqlite_toy.py EXTERNAL_NEW_DIR --use-llm`.
- `cga control measure --cgast-filter -- ...` preserves the child's CGAST
  stdout; telemetry must stay orthogonal to the command's state contract.
- Path-backed `.ql` queries may need sibling `.qll` modules. Materialization and
  packing preserve those siblings.
- `cga a q` owns independent recorded C++ authoring, not a Bench experiment.
  Editor databases are fixed after `prepare`. `save` permits unfinished drafts
  and retains source snapshots; `publish` checks a private copy with CodeQL
  `query compile --check-only`, refuses package/ID collisions, and indexes
  permanent paths. Query packing preserves nested local `.qll` modules while
  excluding database/editor scratch. See
  [authoring](../cga/cgaassist/README.md).
- `cgaql pack` pins the exact language library version from the selected CodeQL
  bundle and uses its `qlpacks/`. Do not restore `"*"` dependencies: registry
  latest may be unreadable by the installed CLI. Explicit overrides are
  `CGA_CGAQL_<LANGUAGE>_DEP_VERSION`.
- Architecture, toolchain, build mode, and source identity are experimental
  inputs, not incidental environment details. The
  [query-030 example](../cga/analysis/CVE-2016-9843/query-030/README.md)
  demonstrates explicit preparation and separate analysis.

## Controller and large artifacts

- [cgactl](../cga/cgactl/README.md) coordinates build campaigns with small
  PostgreSQL job/attempt/lease/artifact-reference records. Large sources, logs,
  products, and databases remain in external storage.
- Layout: `cga/cgactl/{bin,lib,doc,share}`. Python invokes `psql`; schema and
  queue functions are in `share/schema.sql`. Claims use fenced time-limited
  leases and `FOR UPDATE SKIP LOCKED`.
- Each build attempt prepares its registered container base snapshot and records
  effective resources/toolchain. Keep resource fencing and promotion separate
  from analysis execution.
- The promoted collection lives in the sibling
  `single-machine-mrva-artifacts/db-collection.local/`; the ignored
  `cga/db-collection.local` is a compatibility symlink.
- Large CVE `tmp` workspaces are ignored links into the external artifact tree,
  not disposable repository scratch. Preserved analyses have manifests anchored
  by `cga/analysis/ARTIFACTS.sha256`. See the
  [evidence index](../cga/analysis/README.md).

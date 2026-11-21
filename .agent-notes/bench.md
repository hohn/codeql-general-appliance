# Bench notes

The [Bench usage guide](../cga/cgabench/README.md) owns the experiment and
interaction contract. Read these notes for implementation or recovery work.

## Experiment invariants

- Exactly one input axis varies: queries with fixed databases, or databases with
  fixed queries. S1 is the reference. Humans/LLMs prepare D/Q; J/R are derived
  by running and must not be cloned as inputs.
- Later sessions inherit exactly one accepted fixed input. Copying editable
  query sources is distinct from cloning an accepted Q artifact. Fixed inputs
  must match S1 even when inherited through another session.
- Enforce the contract server-side before run/compare. Mode is explicit and
  immutable once sessions exist. Unclassified experiments remain readable, but
  do not silently migrate or grant mutation exemptions.
- Running may advance automatically after both ready inputs are accepted.
  Comparison is always explicit; creating/running sessions or opening a view
  must not compute it. Compare completed S1 first and preserve immutable
  evidence and source-session/digest provenance.
- MRVA identities remain `owner/repository`. Different database bytes need a
  different repository identity, including relevant revision, architecture, and
  build mode; never force-overwrite an accepted cached database.

## Recovery and service ownership

- `advance` uses real cgamr/cgasi operations and session checkpoints. A failed
  recorded command may still have completed a submission; recover from its
  checkpoint rather than retrying an uncertain submit.
- Submitted inputs are locked; completed results are immutable. Keep operational
  checkpoints and scratch needed for live-session resume.
- Browser mutations dispatch through `cga` for normal recording. Non-workflow
  use requires an explicit atomic `--session-file`.
- `serve` can manage its own MRVA/archive/MinIO infrastructure through cgamx.
  `--no-services` leaves that infrastructure alone. Bench and mrva-flow assume
  exclusive use of their MRVA ports/database.
- `cga bench stop` stops only the workflow-local viewer and its owned
  editors/assistant terminals, not MRVA or the experiment. It verifies process
  identity; never reclaim an arbitrary port owner.
- Editor ports are deterministic when requested and must not silently fall back.
  `cga/cgacc` owns native code-server integration. Opening an editor must not
  overwrite existing user instruction files.
- Results APIs use frozen SQLite/DuckDB evidence through `cgasi.store`, not
  mutations. Preserve read-only query limits and digest checks.

## Presentation and checks

- Apple outline and Classic share model, actions, element identities, and detail
  panels. Appearance changes are presentation-only and must preserve selection,
  drafts, and comparison state.
- Selecting a command or opening a panel must not execute it. Keep fixed-row
  Clone and changing-row Edit consistent across UI/CLI/API.
- Browser assets are on existing static routes; refresh is enough for static
  changes. Server policy changes need a viewer restart, preserving the original
  port/editor options and `--no-services` when appropriate.
- Tests: `cd cga/cgabench && python3 -m unittest discover -s tests`. Vendored
  browser assets use the existing `package-lock.json`; regenerate only when
  needed with `npm ci --ignore-scripts && npm run vendor`.

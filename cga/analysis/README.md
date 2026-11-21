# CGA preparation analysis evidence

This tracked tree contains compact, durable outputs and raw telemetry from
collection analyses. Large local artifacts live outside the Git worktree at
`/mnt/common/home/hohn/work-ghp/single-machine-mrva-artifacts/`.

The promoted collection is in that tree at `db-collection.local/`;
`cga/db-collection.local` is an ignored compatibility symlink. Complete run
artifacts are grouped under its `runs/` directory with separate SHA-256
manifests. The external CVE workspaces under `examples/cves/` have content and
symlink-target manifests as well. `ARTIFACTS.sha256` anchors all external
manifests in Git; run
`sha256sum -c cga/analysis/ARTIFACTS.sha256` before relying on them.

- [`run-system-10-2026-08-24/`](run-system-10-2026-08-24/) — completed
  19-CVE/114-database preparation-to-analysis analysis, including five-second status and
  resource samples, a standalone interactive CPU/memory plot, service logs,
  PostgreSQL state, reports, and checksums.

Run `node cga/analysis/build-resource-plots.mjs` from any directory to
regenerate the plot from the preserved resource samples.

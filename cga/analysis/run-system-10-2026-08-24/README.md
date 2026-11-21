# run-system-10 analysis evidence: 2026-08-24

This tracked directory is the compact evidence copy for the completed
collection analysis. The complete 338 MiB apparent-size runtime tree is stored
outside Git at
`/mnt/common/home/hohn/work-ghp/single-machine-mrva-artifacts/runs/run-system-10-2026-08-24/`.
It contains the 114 SARIF files, 114 per-job SQLite files, cumulative DuckDB,
downloaded archives, query packs, and intermediate state. `/tmp/cga-system-10`
is a compatibility symlink to that durable location for the absolute paths in
the preserved CGA session. The external run manifest is anchored by
`../ARTIFACTS.sha256` in Git.

The first pass used six standalone MRVA workers with CodeQL 2.23.9,
`MRVA_CODEQL_RAM_MB=16384`, and `MRVA_CODEQL_THREADS=4`. These are CodeQL
evaluator settings; standalone mode does not impose container cgroup limits.
All 114 analyses succeeded, so no 90 GiB/16-core retry pass was needed.

## Plot inputs

- `resource-plots.html` is a standalone, interactive uPlot 1.6.32 view of the
  aggregated CodeQL Java evaluator CPU and RSS series. It embeds both its data
  and plotting library, so it can be opened without a web server or network.
- `pass1-status.tsv` contains five-second samples with columns `timestamp`,
  `pending`, `in_progress`, `succeeded`, `failed`, and `queued`. Sampling began
  after the first six jobs had succeeded and continued until service shutdown.
- `pass1-resources.tsv` contains five-second per-process samples with columns
  `timestamp`, `mem_available_kib`, `pid`, `ppid`, `pgid`, `rss_kib`, `pcpu`,
  `comm`, and `args`. Filter `comm == "java"` for CodeQL evaluator processes,
  then sum `rss_kib` by timestamp for concurrent evaluator RSS.
- `job-status.csv` contains final per-job status, start/end timestamps, worker
  identity, and duration. MRVA status `2` means succeeded.
- `worker-pool.csv` contains the final worker records.

The measured resource envelope in the raw samples was:

- maximum individual CodeQL Java RSS: 10,082,240 KiB (9.62 GiB);
- maximum concurrent CodeQL Java RSS: 52,755,348 KiB (50.31 GiB);
- minimum host `MemAvailable`: 37,946,656 KiB (36.19 GiB); and
- maximum concurrent CodeQL Java process count: 6.

The first recorded completion was at 10:55:58 PDT and the last at 11:04:34
PDT. Per-job runtime ranged from 7.608 to 85.040 seconds, with a 21.748-second
median.

## Other evidence

- `query-effectiveness/` contains a source-to-SARIF validation study for all 19
  CVEs. It includes three detailed reports, a follow-up screen of the remaining
  16 cases, exact finding summaries, and regeneration scripts.
- `server.log` and `db-server.log` are the complete service logs.
- `mrvadev.pgdump` is the final MRVA PostgreSQL state.
- `cga-session.json`, `eligible.tsv`, `bindings.tsv`, and `pack-map.json`
  preserve the CGA control state.
- `../build-resource-plots.mjs` regenerates `resource-plots.html` from
  `pass1-resources.tsv`. It downloads pinned uPlot 1.6.32 assets and verifies
  their SHA-256 hashes before embedding them.
- `summary.json`, `report.md`, and `report.json` are the verified outputs.
- `kernel.log` is the kernel journal for the analysis window; it contains no
  OOM event.
- `SHA256SUMS` recursively covers every preserved evidence file except itself.

The earlier 80% fit figure came from experiments on 2,400 randomly selected
Debian projects. It is background data, not an expected fit rate for this CVE
collection.

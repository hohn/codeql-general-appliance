# cgaex — result exporter

`cgaex` is the terminal stage of the complete CGA workflow. It reads the
cumulative `cgasi-db` plus the explicit per-job records in `cgasi-ingestions`
and emits either a concise Markdown report for humans or a stable JSON document
for LLM consumers.

```sh
cgaex human [--output report.md]
cgaex llm [--output report.json]
cgaex info
cgaex serve
```

Both commands are ordinary CGAST filters. Generated files are recorded under
`cgaex-exports`; `/overview` and `/detail` render those artifacts from the live
session.

## LLM export schema

The JSON format is `cga.analysis-export.v2`. It is self-contained rather than a
dump of internal CGAST keys:

- `summary` counts submissions, jobs, findings, zero-finding jobs, users, rules,
  findings by user, and jobs by status;
- `submissions` retains each name, user, session, language, status, query pack,
  and explicit job list;
- every job records its repository, status, ingested finding count, MRVA result
  count, artifact size, and archive/SARIF/SQLite provenance;
- every finding includes its submission, session, job index, and repository in
  addition to the SARIF result fields.

Successful zero-finding jobs and users therefore remain first-class records;
consumers never need to infer them from missing findings or encoded filenames.
The exporter rejects missing jobs, malformed artifact records, inconsistent
counts, and findings that cannot be mapped to a recorded SARIF job.

# `cga db plan` — database job expansion

```sh
cga db plan \
  --mode bm-none \
  --mode trace \
  --architecture arm64 \
  --repository-suffix arm64 \
  --output-dir jobs
```

The command consumes `cgasp-sources` and writes one immutable
`cga.database-job.v1` JSON file for each source × mode combination plus
`jobs.json`. It validates names, dependencies, and trace build commands but
does not copy sources or invoke CodeQL. The jobs manifest is recorded as
`cgadbplan-jobs`.

`--use-llm` records supervised building and permits a missing trace command; the
supervisor discovers it from the prepared source documentation. Job IDs identify
planned work, not the database content: final database repository names are
assigned only after hashing the completed bundle.

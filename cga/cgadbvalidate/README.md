# `cga db validate` — explicit database validation

```sh
cga db validate query \
  --query query.ql \
  --output-dir validation
```

`query` consumes built records from `cgadb-records`, runs the supplied query
against each selected database, and writes SARIF plus `validations.json`.
`--record ID` or `--record owner/repo` may be repeated to select a subset.
Results are stored in `cgadbvalidate-results`. Validation never changes or
rebundles a database.

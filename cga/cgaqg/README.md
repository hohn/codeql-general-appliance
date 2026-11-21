# cgaqg — CVE query-library generator

`cgaqg` materializes query definitions carried by the selected CVE specs and
forms the standard query library consumed by `cgaql`.

```sh
cgaqg materialize [--output-dir DIR]
cgaqg index
cgaqg info
cgaqg serve
```

Queries may reference an existing `.ql` file or contain inline source.
`materialize` writes `cgaqg-querydir`, and `index` writes the preparation-only
`cgaqg-index`. Neither command changes a CGA query chooser. Pass the generated
directory to `cgaql index`, select queries, and run `cgaql pack` in a separate
CGA session.

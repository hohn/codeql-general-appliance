# `cga catalog` — database catalogue lifecycle

```sh
cga catalog create \
  --output generated-metadata.sql \
  --manifest generated-manifest.json

cga catalog merge \
  --catalog generated-metadata.sql \
  --catalog-manifest generated-manifest.json \
  --base-catalog existing-metadata.sql \
  --base-query-file preserved.sql \
  --base-archive-root databases \
  --base-descriptors preserved.json \
  --output metadata.sql \
  --manifest manifest.json

cga catalog verify --catalog metadata.sql --manifest manifest.json
cga catalog export /data/database-collection
```

`create` consumes `cgadb-records` and optional `cgadbvalidate-results`.
`merge` first verifies the generated catalogue/manifest, then selects preserved
rows from a base catalogue. Preserved `result_url` values are not trusted:
archives are resolved under the explicit root and verified by hash and size
before corrected URLs are written. Descriptors must exactly match the selected
base repositories.

`verify` checks catalogue hash, repository equality, catalogue records, archive
existence, and archive hashes. Outputs are stored in `cgacatalog-catalog` and
`cgacatalog-manifest`.

`export` uses those state references or explicit `--catalog`/`--manifest`
inputs. It verifies, copies archives into the existing qldbstore layout, and
publishes a new directory containing ZIPs, `metadata.sql`, and `manifest.json`.
Legacy repository names are qualified with the full bundle SHA-256. Exported
local URLs, archive paths, and catalogue hashes are updated, and the staged
collection is verified before publication. Existing destinations are refused.
`--base-url http://127.0.0.1:9080` supplies HTTP result URLs instead; it does
not start a server. `--move` removes original archives only after verified
publication, making the original catalogue's archive references obsolete.

Serve separately with
`cga ds start --directory /data/database-collection --port 9080 --log /data/archives.log`.
Analysis explicitly imports the exported catalogue; preparation never writes
chooser state.

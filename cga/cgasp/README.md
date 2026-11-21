# cgasp — source package materializer

`cgasp` turns `cgacv-work-items` or an explicit local-source manifest into
validated source trees. It supports upstream Git references, Debian `.dsc`
sources, generic tar/ZIP archives, and adoption of existing local trees.
Explicit source manifests do not require a CVE. Commands are executed as
argument arrays, never through a shell.

```sh
cga src-prep plan [--manifest FILE]
cga src-prep fetch [--manifest FILE] [--output-dir DIR] [--dry-run] [--use-llm]
cgasp adopt --manifest FILE
cgasp info
cgasp serve
```

`fetch` records one status and source directory per CVE variant in
`cgasp-sources`. Dependency commands are preserved for `cgadb`; source
fetching does not install packages.

Source manifests contain an `items` array; items preserve build metadata and
provide a safe `id` plus `source`:

```json
{
  "items": [
    {
      "id": "toy--pre",
      "owner": "hohn",
      "repo": "codeql-dataflow-sql-injection",
      "upstream_repo": "codeql-dataflow-sql-injection",
      "language": "cpp",
      "variant": "pre",
      "version": "master",
      "source": {
        "strategy": "git",
        "url": "https://github.com/hohn/codeql-dataflow-sql-injection.git",
        "ref": "master"
      },
      "build_command": "bash ./build.sh",
      "dependencies": []
    }
  ]
}
```

An archive source uses `{"strategy":"archive","url":"sources.tar.gz"}` and
optionally `sha256`; local paths resolve against the manifest. ZIP executability
is preserved, extraction rejects escaping paths, and an archive's single
top-level directory is stripped. Git acquisition records the resolved commit and
requested ref; all ready trees have a SHA-256. Existing destinations are never
removed. `--results FILE` enables verified resumption of matching ready items.

`--use-llm` supervises prerequisite discovery and failed acquisition repair,
with `--llm-attempts N` (default 3). Requests, JSON recipes, command logs, and
outcomes remain under the output's `.attempts/` directory. The normal
acquisition step still selects the requested source. See the shared
[supervisor contract](../cgaassist/README.md#llm-supervised-attempts).

`adopt` reads a JSON object with a non-empty `items` array. Every item must
contain a safe `id` and `source_dir`; the remaining build metadata is preserved.
Relative source paths resolve against the manifest directory. The command
requires each directory to exist, computes a deterministic source-tree
SHA-256, checks an optional `source_tree_sha256`, and records ready items in
`cgasp-sources`. It does not copy or modify the adopted trees. `cgadb` creates
an independent disposable copy for each planned database build.

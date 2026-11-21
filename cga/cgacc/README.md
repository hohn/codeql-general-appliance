# cgacc — browser VS Code

Native [Coder code-server](https://github.com/coder/code-server), using the host's
tools and paths rather than a container. `bin/` contains the command, `lib/cgacc/`
the reusable lifecycle, and [doc/usage.md](doc/usage.md) the runtime contract.

```sh
cga cc install             # explicit, checksum-verified Linux amd64/arm64 install
cga cc info                # PATH, CGACC_CODE_SERVER, or the installed cache
cga bench serve            # completed R cell: Open VS Code
cga bench serve --editor-port 8611  # S1: 8611, S2: 8612, ...
```

No download occurs when opening the editor. Installation caches the pinned
release under `${XDG_CACHE_HOME:-~/.cache}/cga/`; alternatively install code-server
yourself or set `CGACC_CODE_SERVER` to its executable. Requires Python 3.11+.

For a manually launched editor, `cga cc serve PROJECT --runtime DIR --port 8611`
chooses its fixed loopback port. Omit the port option (or use `0`) for automatic
allocation. See [SSH forwarding](doc/usage.md#ssh-forwarding) for Bench usage.

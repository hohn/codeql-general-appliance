# cgadfg: whole-CGAST data-flow and control-flow graphs

`cgadfg` is the legacy-manifest run-graph inspector behind
`cga dfg` / `cga data-flow-graph` and
`cga cfg` / `cga control-flow-graph`. It loads the immutable whole-CGAST
history produced by the former numbered-script flows without changing a CGAST.
Current `.cga/` workflows use `cga tree show -v` for data flow and
`cga tree show --control-flow` for control flow.

The two views deliberately answer different questions:

- **DFG:** nodes are immutable CGAST state snapshots. Each node shows the
  top-level data keys added (`+`), updated (`~`), or removed (`-`) relative to
  its parent. Edges are labelled with the command that produced the child
  state.
- **CFG:** nodes are command invocations in execution order. Parent edges
  preserve chain and branch topology. This is the graph formerly emitted by
  `cga dfg`.

```sh
cga dfg info
cga dfg show
cga dfg --dot show
cga dfg --render data-flow.pdf show
cga dfg --render-user data-flow.html show

cga cfg info
cga cfg show
cga cfg --dot show
cga cfg --render control-flow.pdf show
cga cfg --render-user control-flow.html show
```

The manifest defaults to `$CGA_HISTORY_DIR/manifest.json` when that variable is
set, otherwise to `cga-tmp/mrva-flow-history/manifest.json`. Use
`--manifest PATH` for any other run. `--session PATH` overrides the
current-head compatibility path displayed by `info`.

Both `show` commands sort nodes by chain and sequence. DOT output clusters
nodes by chain, draws every parent edge (including cross-chain edges), and
highlights the manifest's current head. `--markdown` emits a table suitable for
documentation or LLM input. `--render` requires Graphviz `dot` and writes a
PDF.

`-u FILE.html` / `--render-user FILE.html` writes a dependency-free,
top-to-bottom HTML/SVG forest for non-developer users. The DFG view renders
states as undecorated circles and producing commands as plain-language
rectangles such as `Build infrastructure` and `Fetch DB index`; the CFG view
renders those commands directly. Labels and synopsis text come from the
command-line help vocabulary. Hover or keyboard-focus a node to see the
synopsis followed by the complete literal command and arguments, or the
complete state delta. Root states have no producing-command box.
# CGA implementation summary

CGA owns analysis selection and execution. Its input boundary is a prepared
database catalogue plus database archives and a prepared query source tree. It
loads those inputs with `cgadl getmeta` and `cgaql index`; it does not create
them.

The active workflow is:

```text
cgadl + cgaql -> cgamr -> cgamu -> cgasi -> cgaex
```

`cgamx` manages the local standalone MRVA infrastructure and serves the web
command bridge. `cgasv` supplies the dashboard header. All components share the
CGAST JSON filter protocol and the dashboard session configured by
`CGA_SESSION`.

Database and query generation now live in [`../cga/`](../cga/README-prep.md), with
an independent session and web endpoint. CGA preparation state never becomes
CGA chooser state implicitly. A caller must pass the generated catalogue to
`cgadl getmeta` and query directory to `cgaql index`, then make its selections.

The CGA dashboard is served on port 8600, with component ports 8601–8608. The
CGA preparation dashboard is independently served on port 8500, with preparation components
on 8501–8504.

Direct selection/run examples are under `sample-05/` and the canonical
single-user `mrva-flow/mrva-flow.sh`; deprecated `sample-05-i/` remains as a
two-user reference. The complete `cga/system-tests/run-system-09` workflow uses two
state files and tests the explicit preparation-to-analysis handoff before real
MRVA analysis and result export.

`cga uv` serves CGA Unified View, a read-only projection that joins active
`.cga` workflow steps, state deltas, source/transcript provenance, artifacts,
component state, and a compact live MRVA system summary.

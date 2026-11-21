# CGA Bench: introductory outline

[Introductory guide](../../INTRODUCTORY-GUIDE.md) |
[Shell workflow](cli-workflow.md) |
[Full Bench reference](../../cga/cgabench/README.md)

Bench lets you vary queries against fixed databases, or databases against a
fixed query. Each session has four parts: **D** databases, **Q** query, **J**
jobs, and **R** results. Session 1 is the reference for comparison.

This is a short outline for expansion, following the current Bench guide.

## Start an experiment

Create a new directory; do not reinitialize an existing experiment:

```sh
mkdir -p "$HOME/cga-experiments"
mkdir "$HOME/cga-experiments/my-bench"
cd "$HOME/cga-experiments/my-bench"
cga init .
cga chain start
cga bench init query-study --mode query-changes
cga bench session baseline
cga bench serve
```

Open <http://127.0.0.1:8610/>. `serve` runs in the foreground; use another
terminal in the same experiment directory for further shell commands. It also
prepares Bench's analysis services. Do not run it alongside another Bench/MRVA
example using the same ports and PostgreSQL state.

Use `--mode database-changes` instead when databases are the changing input. The
mode cannot change after sessions exist.

## Work with inputs and sessions

In S1, choose prepared databases in **D** and a query in **Q**. Accepting the
second ready input starts analysis. **J** and **R** are produced by running, not
entered by hand.

For later sessions, retain the fixed input and edit the changing input. For a
query-change experiment:

```sh
cd "$HOME/cga-experiments/my-bench"
cga bench session refined
cga llm context bench
```

Add the variant only after S1's fixed input has been accepted. Choose or edit
its query in the viewer. `cga bench advance` continues a ready/pending session
when needed; it does not create a comparison.

To expand: choosing a catalogue, selecting databases, copying/editing a query,
and recognizing ready/running/completed cells.

## Inspect and compare

Select **R** to inspect a completed session. Once S1 and the variant are
complete, compare explicitly in the viewer or shell:

```sh
cga bench compare 1 2
```

Opening the comparison view does not recompute it.

To expand: reading findings, understanding additions/removals, and following
evidence back to the accepted inputs.

## Reconnect, stop, and restart

Closing a browser tab does not stop Bench. Reopen <http://127.0.0.1:8610/> to
reconnect to the same running viewer. Inspect retained experiment state without
a viewer:

```sh
cd "$HOME/cga-experiments/my-bench"
cga llm context bench
```

Stop the viewer from another terminal, or use Ctrl+C in its foreground terminal:

```sh
cga bench stop
```

This stops its owned editors/assistant terminals, not MRVA or the experiment.
Start the viewer again while leaving running analysis services alone:

```sh
cga bench serve --no-services
```

If analysis services have also been stopped, use `cga bench serve` without
`--no-services` to start them too. To stop both services and viewer while
retaining experiment state:

```sh
cga bench infrastructure stop
cga bench stop
```

Keep any custom `--port` or `--editor-port` options when restarting. For remote
access, follow the [port-forwarding guide](../../REMOTE-CONNECTION.md).

## Next

To expand: one small worked experiment, screenshots, and a short glossary. Use
the [shell workflow](cli-workflow.md) when inputs need preparation, or the
[advanced reading guide](../../READING-GUIDE.md) for deeper references.

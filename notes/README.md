# Early and special notes

This directory holds investigation notes, early design material, and special
operational findings that are useful to retain but are not yet full project
documentation.

These notes may describe historical branches, experiments, or implementation
details that have since changed. Each note should identify the code revision and
observation date when that context matters.

The notes have their own standalone
[mdBook](https://rust-lang.github.io/mdBook/), separate from the project book
under `docs/`. Requires mdBook 0.5 or newer. From this directory, run
`make book` to build it under `book/`, or `make view-book` to build and serve it
with live reload. Files under `src/` are only a summary and symlinks back to the
Markdown sources in this directory, keeping those sources canonical.

Pre-rendered HTML and PDF versions of math-heavy notes are intentionally checked
in beside their Markdown sources. From this directory, run `make render` to
rebuild both formats or `make html` / `make pdf` separately. The default target
does not render them, keeping repository-wide `make all` free of optional Pandoc
and TeX dependencies.

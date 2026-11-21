# Sample 05: one query, five databases

Use the supplied `Fprintf.ql` with five prepared C++ databases, one user
(`bob`), and one cumulative DuckDB result store. No interactive selections are
required. Database archives are downloaded using the repository catalogue; this
sample does not build CodeQL databases.

Start with the
[visual worked example](../../../docs/cga-overview.html#reference-architecture)
in section 03 of the CGA overview for a three-lane diagram and five learning
milestones. It opens offline, uses these fixed inputs, and runs no commands; the
numbered recipes below remain the execution reference.

Requires Linux, `cga` on `PATH`, and the
[host dependencies](../../../INSTALL.md), including CodeQL with C++ libraries
and DuckDB. Allow network access and disk space for downloads. Preflight can
reclaim shared ports; reset clears MRVA's PostgreSQL state. Do not execute
alongside Bench or another MRVA scenario.

## Display or execute one step

```sh
cga help sample 05            # overview
cga help sample-05            # same overview
cga h s 05 00                 # display step 00
cga help sample 05 start      # same step, by name
cga h s 05 00 r               # execute exactly the displayed Bash commands
```

`h`/`help`, `s`/`sample`, and `r`/`run` are exact aliases. Step numbers have two
digits; step names are exact, not prefixes. Every display form, including `-h`
after a run request, is read-only. There is no run-all command.

Step 00 explicitly creates `cga/cga-tmp/help-sample-05/` under this checkout and
initializes its `.cga/` workflow. It copies the two SQL recipes into `inputs/`
and links the repository catalogue and query tree. Runtime environment overrides
supplied at step 00 are saved in the private `.cga/sample-05.env`. Later steps
load that file, so each command works from a fresh shell or Jupyter `!` cell
without carrying previous exports or directory changes.

The directory must not already exist. Step 00 never reuses or resets an existing
workflow. If interrupted after submission, inspect status rather than repeating
submit. An uncertain submit outcome needs investigation, not automatic retry.

## Execute stepwise

Steps are numbered consecutively from 00 to 20. Run each line separately. At
step 13, repeat until the status is `succeeded`; investigate a failed submission
rather than proceeding.

```sh
cga h s 05 00 r  # create directory, save settings, initialize workflow
cga h s 05 01 r  # preflight
cga h s 05 02 r  # reset MRVA
cga h s 05 03 r  # build
cga h s 05 04 r  # start MRVA
cga h s 05 05 r  # import catalogue and index queries
cga h s 05 06 r  # list up to 5 queries
cga h s 05 07 r  # list up to 10 databases
cga h s 05 08 r  # select 5 databases
cga h s 05 09 r  # select Fprintf.ql
cga h s 05 10 r  # download database archives
cga h s 05 11 r  # pack query
cga h s 05 12 r  # submit once
cga h s 05 13 r  # observe status once; repeat until succeeded
cga h s 05 14 r  # download results; refuses a non-successful recorded status
cga h s 05 15 r  # verify downloaded archives
cga h s 05 16 r  # ingest into findings/all.duckdb
cga h s 05 17 r  # verify ingestion
cga h s 05 18 r  # show up to 4 findings per database using SQL
cga h s 05 19 r  # check server log
cga h s 05 20 r  # stop services, retain history and results
```

[`databases.sql`](databases.sql) selects one archive each for `dsvpn/dsvpn`,
`file/file`, `flex/flex`, `inotify-tools/inotify-tools`, and `nnn/nnn`, with
explicit ordering. [`results.sql`](results.sql) uses the per-job SARIF filenames
retained by ingestion to associate findings with those databases. It returns the
first four findings per database in stable source-location order, with total
counts and an explicit row for any database with zero findings.

`Fprintf.ql` demonstrates the pipeline; findings are not proof of vulnerability
detection. Viewers and destructive cleanup are not part of this recipe.
[`sample-05-i`](../../sample-05-i/README.md) remains the separate two-user
experimental example.

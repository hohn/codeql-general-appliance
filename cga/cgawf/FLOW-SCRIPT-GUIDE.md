# CGA flow script guide

CGA flow scripts are authoritative executable specifications. Keep the
user-facing command sequence close to the numbered MRVA/CodeQL specification;
let `cga` record state, provenance, transcripts, attempts, artifacts, and tags.

## LLM input

Give the LLM:

1. the numbered workflow specification
2. available CGA command help
3. required inputs and outputs
4. runtime/lifecycle constraints
5. accepted tag profiles or canonical tags

Ask for one meaningful CGA operation per command and require a reviewable shell
script rather than a monolithic implementation.

## Recommended shape

```sh
#!/usr/bin/env bash
set -euo pipefail

# Resolve concise named inputs and runtime paths.

# Initialize/start infrastructure.

# User-facing flow.
cga dl getmeta --tag user:viewable "$CATALOGUE"
cga ql index --tag user:viewable "$QUERY_ROOT"
cga dl sql --user "$USER" --query-file "$DATABASE_SELECTION"
cga dl download --output-dir "$DATABASE_STORE"
cga ql select --user "$USER" relpath "$QUERY"
cga ql pack --tag user:show-progress

cga mr run --tag user:show-progress ...

cga si ingest ...
cga ex human --tag user:primary-interest-data ...
cga ex llm ...
cga si verify "$SUBMISSION"

# Export views.
```

## Style rules

- Keep one meaningful CGA operation per command.
- Use descriptive variables rather than repeating expanded paths/literals.
- Keep lifecycle/setup visually separate from the conceptual flow.
- Do not manually thread CGAST files.
- Do not duplicate provenance, transcript, artifact, or history plumbing.
- Avoid helper functions that hide multiple subsystem operations.
- Use bounded compound commands only when they are one user operation.
- Keep readable tag profiles when they improve the script; CGA stores expanded
  canonical tags.
- Put common `--tag` options before the first argument separator (`--`).
- Preserve component options such as `--user`; common tags do not replace them.

## Review checklist

- Does the command sequence still match the numbered specification?
- Is every mutable choice visible in the script or a clearly named input file?
- Are selection criteria explicit?
- Are polling, timeout, and output bounds explicit?
- Are user-important steps/resources tagged?
- Is setup secondary to the conceptual flow?
- Does every command have a clear success/failure boundary?
- Are generated outputs placed under the workflow root or configured store?
- Does `bash -n` pass?
- Does a real run produce the expected `.cga` nodes, attempts, collections, and
  exports?


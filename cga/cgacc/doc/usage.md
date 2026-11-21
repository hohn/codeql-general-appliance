# Runtime and workspace contract

Bench's **Open VS Code** button opens a pop-up and starts one native code-server
per completed session on an IPv4 loopback port (automatically allocated by
default). A generated
password authenticates the pop-up automatically; authentication is not disabled.
Passwords are returned only by Bench's guarded, non-cacheable JSON endpoint,
not placed in URLs, command arguments, project files, or logs. Pop-up blocking
and missing executables produce visible errors.

Editors survive navigation, pop-up closure and reloads; reopening reuses the
process. Graceful Bench shutdown terminates their process groups, including
integrated terminals, without stopping MRVA services. An editor that exits is
restarted on the next click. Runtime logs and isolated VS Code settings/extensions
live under `.cga/runtime/cgacc/session-N` (or `.cgacc/session-N` beside a raw
session file). These are disposable runtime files, not accepted experiment data.

The project folder and terminal working directory are the existing
`.cga/tmp/cgabench-query/session-N` (raw file: `.cgabench-query/session-N`).
Bench creates `query.code-workspace`, `AGENTS.md`, and
`.github/copilot-instructions.md` only if absent, preserving user edits.
`bench-context.json` is refreshed on each open with session identity, experiment
axis, accepted inputs, frozen result snapshot, DuckDB/per-job SQLite paths,
documentation paths, API URLs, headers, and a session-specific result request.
The instructions direct assistants to read that context first and use read-only
`/api/results` queries, without reingestion or workflow mutation.

The editor runs as the Bench OS account, not the session's MRVA user. Agent
instructions are guidance, not a filesystem sandbox. Use only on a trusted
single-user loopback host; do not publish/proxy either service to untrusted users.
Extensions and agent authentication are user-managed; no paid agent command
starts automatically and no agent permission controls are overridden.

For manual use, with an existing VS Code project:

```sh
cga cc serve /absolute/path/query.code-workspace --runtime /absolute/path/runtime --port 8611
```

This foreground launcher prints a JSON descriptor (including a login password);
treat it as sensitive. It owns the editor until SIGINT/SIGTERM.

## SSH forwarding

For normal remote use, start [CGA gateway](../../cgagateway/README.md) and forward
only port 8599. Open Bench at `http://127.0.0.1:8599/bench/`; its **Open VS Code**
control discovers each live session editor automatically, including automatically
allocated ports. Authentication remains enabled. Existing Bench processes must
be restarted after upgrading to gain the editor-discovery endpoint.

For direct-port development without the gateway:

Choose a predictable editor port range when starting Bench:

```sh
cd /path/to/bench-workflow
cga bench serve --no-services --editor-port 8611
```

S1 uses 8611, S2 uses 8612, and session N uses `8611 + N - 1`, regardless
of which session is opened first. Restarting Bench with the same option preserves
this mapping. Each session still has its own editor, settings and workspace.
An unavailable port is an error, never a fallback to a random port. Ports must
be within 1–65535; a session whose derived port exceeds 65535 cannot open.
`--editor-port 0` (the default) retains automatic allocation.

Forward Bench and every editor session you intend to open, using matching local
ports because the pop-up URLs contain those ports. For S1 and S2:

```sh
ssh -N -L 8610:127.0.0.1:8610 \
       -L 8611:127.0.0.1:8611 \
       -L 8612:127.0.0.1:8612 hohn@svm
```

Open `http://127.0.0.1:8610` locally. Keep all listeners on loopback;
password authentication remains enabled. Remote integrated-terminal agents can
use the Bench API URLs in `bench-context.json` directly on the remote host.

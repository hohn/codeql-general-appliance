# CGA gateway

One loopback URL joins the existing viewers, dashboards, native VS Code editors,
and live checkout documentation. It does not start workflows, MRVA, viewers, or
editors, and does not change their direct development ports.

For unified viewer startup, use `cga serve start` as described below. To run
only the gateway with independently managed viewers:

```sh
cga gateway start
cga gateway status
```

On your workstation:

```sh
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 \
  -L 8599:127.0.0.1:8599 hohn@svm
```

Open **http://127.0.0.1:8599/**. To reconnect, run the same SSH command and reopen
the URL. Add `-N -T` if you do not need an interactive remote shell. Exit SSH to
close the tunnel. To stop only the remote gateway:

```sh
cga gateway stop
```

Viewers, editors, MRVA, and experiment state are unaffected by stopping the
gateway. An unavailable viewer returns HTTP 502; start that viewer normally.
After upgrading, restart existing Bench/Unified View processes so they serve the
current code. Reloading alone does not update a running Python server.

## Documentation

The landing page links to the **CGA overview**, **CGA help**, and **Reference
manual**. `/documentation/` serves the repository's documentation entry point;
relative links to component references, installation guides, stylesheets, and
LLM sources stay behind the same gateway. No additional HTTP process or SSH
forward is needed, even when no viewer workspace is configured.
Component-directory links open their rendered `README.html` when no `index.html`
is present.

Files are read from the current checkout on each request, without browser
caching. Rebuild generated pages after editing their sources:

```sh
make -C docs html help
make -C docs book       # optional reference manual
```

The gateway does not build documentation on startup. It serves document/source
files and web assets, not directory listings, hidden runtime state, database
archives, or symlink targets outside the checkout. The `.agent-notes/` guide
sources remain available for LLM navigation.

After upgrading an already-running gateway, stop and start **only the gateway**
with its original `--port`/`--config` settings. Viewers and workflows need not
be restarted. If using `cga serve`, run `cga serve start` again with its
original environment/configuration to rejoin the replacement gateway; matching
viewers are retained. Older gateways cannot be reused until upgraded.

## Routes

| Browser path | Default remote loopback port |
| --- | ---: |
| `/documentation/` | Gateway itself (8599) |
| `/analysis/` | 8600 |
| `/analysis/{cgasv,cgadl,cgaql,cgamr,cgamu,cgasi,cgamx,cgaex}/` | 8601–8608 |
| `/preparation/` | 8500 |
| `/preparation/{cgacv,cgasp,cgadb,cgaqg}/` | 8501–8504 |
| `/unified/` | 8609 |
| `/bench/` | 8610 |
| `/editors/session-N/` | Live Bench editor for session N |
| `/flow/` | 8720 |
| `/flow/{cgasv,cgadl,cgaql,cgamr,cgamu,cgasi,cgamx,cgaex}/` | 8721–8728 |
| `/flow/unified/` | 8729 |
| `/sysview` and `/sysview/data` | 8081 |
| `/archives/` | 9080 |

Open editors using Bench's **Open VS Code** control. The gateway discovers
already-running editors from Bench's loopback, Host-guarded `GET /api/editors`;
it never launches an editor merely because a URL was requested. Automatic
editor ports work: no `--editor-port` or additional SSH forwards are needed.
Password authentication stays enabled. Login redirects, per-session cookie
paths, WebSockets, and editor assets remain behind the gateway.

The gateway keeps browser requests on one origin. It supplies mounted component
URLs for each dashboard and rewrites only the viewers' presentation links and
editor descriptors, not workflow evidence, transcripts, or artifact contents.
Bench/Unified View/VID browser assets use mount-relative paths and still work
at their direct ports. MRVA's `/sysview` paths remain unchanged.

## Unified viewer startup

```sh
cga serve start
cga serve status
cga serve stop
```

`start` launches all configured viewers plus the gateway, including
documentation serving. Missing or unconfigured state is printed as `SKIP`, not
created. By default it uses the current workflow for analysis/Unified View and,
if it contains an experiment, Bench; existing analysis/preparation session
files; and the existing `cga/mrva-flow/.cga/` workflow. Explicit
`CGAST_SESSION`/`CGA_SESSION`, `CGA_TMPDIR`, `CGA_PREP_SESSION`, and
`CGA_PREP_TMPDIR` are honored. There is no recursive workspace search.

To select separate workspaces, create a JSON file such as:

```json
{
  "analysis": {"workflow": "/path/to/analysis"},
  "preparation": {"workflow": "/path/to/preparation"},
  "bench": {"workflow": "/path/to/experiment"},
  "flow": {"workflow": "/path/to/mrva-flow"},
  "gateway": {"port": 8599}
}
```

```sh
cga serve start --config /path/to/viewers.json
cga serve status
cga serve stop
```

Paths are relative to the JSON file. Omitted profiles are skipped.
Each viewer profile accepts either `workflow` or `session_file` (an existing
raw CGAST), never both. Raw sessions support dashboards and Bench, but Unified
View requires a workflow. Bench requires an existing experiment.
`CGA_SERVE_CONFIG` selects the same file for future shells.

Optional profile `port` values select the first port of each block: analysis
8600–8609, preparation 8500–8504, flow 8720–8729, or Bench 8610. Optional `env`
objects supply per-profile string environment overrides. Existing analysis and
preparation component port variables remain supported. Flow uses its own block
instead of accidentally inheriting analysis ports; use its `env` for explicit
per-component overrides. The gateway's route map is generated from these ports.
`viewers.json` is a workspace map, distinct from the route-prefix port map used
by `cga gateway start --config`.

Startup does **not** initialize workflows, seed examples, start/reset MRVA,
execute queries, or launch assistants/editors. Bench uses
`--no-services --no-assistant`; its assistant and session editors remain
available on demand. Sysview and archives are reported as external services or
skipped when MRVA is unavailable.

Matching owned viewers are retained on repeat starts. Other occupied viewer
ports are errors, never reclaimed or silently reused. A running independent
gateway is reused only when its live route map matches, and is left running by
`cga serve stop`. Stop/status use recorded process identities, not a possibly
changed configuration or current directory. Stop closes aggregate-owned Bench
editors/shells but never stops MRVA or changes experiment data. Failed startup
rolls back only newly started viewers. Stop before changing active settings.

`CGA_SERVE_RUN_DIR` selects the aggregate's runtime directory (default
`cga/.run/viewers/`), containing ownership records, viewer logs, compiled Go
viewers, and independent generated configurations for analysis/flow/preparation.
Repository web configuration files are not overwritten. Use a separate runtime
directory **and separate ports** for a second aggregate.

The original direct viewer commands remain available for development.
`cga serve build`, `seed`, and `outputs` retain their explicit dashboard-only
behavior; `seed` deliberately replaces sample dashboard state.

## Configuration and implementation

Go and Python 3 are required; there are no additional packages or sudo steps.
`start` builds the standard-library Go reverse proxy in
`cga/.run/gateway/`, alongside its PID identity record and `gateway.log`.
`CGA_GATEWAY_RUN_DIR` overrides that runtime directory.
`CGA_GATEWAY_PORT` or `start --port PORT` changes the listener.

Existing `CGA_PAGE_PORT`, `CGA_CGAUV_PORT`, `CGA_<COMPONENT>_PORT`, `PORT`
(MRVA), `CGA_PREP_*_PORT`, and `DB_SERVER_PORT` overrides are honored. Start the gateway in the
appropriate environment, or supply an explicit port map:

```json
{
  "/analysis/": 8700,
  "/analysis/cgasv/": 8701,
  "/analysis/cgadl/": 8702,
  "/analysis/cgaql/": 8703,
  "/analysis/cgamr/": 8704,
  "/analysis/cgamu/": 8705,
  "/analysis/cgasi/": 8706,
  "/analysis/cgamx/": 8707,
  "/analysis/cgaex/": 8708,
  "/bench/": 18610
}
```

```sh
cga gateway start --config /absolute/path/gateway.json
```

The JSON object overrides the listed routes; omitted routes retain their
defaults/environment overrides. Unknown prefixes, invalid ports, and routes
back to the gateway's own listener are errors. Restart the gateway to apply
configuration changes. Flow overrides use the same explicit prefix map.

The listener and all proxy targets are IPv4 loopback-only, for the existing
trusted single-user SSH workflow, not public hosting or multi-user isolation.
The gateway rejects non-loopback Host and foreign Origin headers, translates
accepted same-origin requests to the backend's loopback origin, and preserves
the existing JSON/header guards. Direct development endpoints remain independent.
Stop verifies the recorded process identity and does not reclaim arbitrary ports.

Focused checks:

```sh
(cd cga/cgagateway && go test -race ./... && go vet ./...)
(cd cga/cgabench && python3 -m unittest discover -s tests)
(cd cga && python3 -m unittest discover -s tests -p test_viewers.py)
```

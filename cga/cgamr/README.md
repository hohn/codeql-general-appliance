# cgamr — CodeQL generic appliance: MRVA requestor

`cgamr` is the MRVA HTTP client for the CGA appliance. It provides the
submit/status/download lifecycle through CGA's JSON-in/JSON-out CGAST protocol.

Every command reads the CGAST from stdin and writes the merged object to stdout.
Human monitoring output goes to stderr. Multiple runs coexist in one CGAST as
named submissions.

The submission name (for example `bob-1`) is a caller-defined label that lets
one user retain multiple runs. The user (for example `bob`) is the authenticated
MRVA identity sent with server requests; the detail view shows both because
they are intentionally different identifiers.

## Commands

```sh
cgamr submit --name bob-1 --user bob [--language cpp]
cgamr submit --name ready --user bob --pack query.tgz --language cpp --repos octo/a
cgamr attach --name existing --user bob --session-id 42
cgamr run --name bob-1 --user bob --output-dir results --log-dir run-log
cgamr status --name bob-1
cgamr download --name bob-1 [--output-dir DIR]
cgamr info [--name bob-1]
cgamr verify [bob-1 eve-1]
cgamr reset [--name bob-1]
cgamr serve
```

`submit` consumes the current `cgaql-pack`, `cgadl-selection`, and
`cgadl-dbdir`. It verifies each selected qldbstore archive, submits the selected
repository names and pack through the variant-analysis endpoint, and records the
returned session ID. The server's configured database store must serve the same
`cgadl-dbdir`; `cgadl download --output-dir` makes this explicit for standalone
runs. `--user` supplies the standalone `X-MRVA-User` identity; `--bearer-token`
supports an authenticated deployment.

For already-prepared inputs, `submit --pack FILE --repos OWNER/REPO ...`
accepts an explicit query pack and repository set. `--language` is required
with `--repos`; those databases must already be available in the server's
configured database store. These options do not upload databases or construct
selection state. Without them, the existing CGA library selections are used.
An existing submission name is rejected to prevent accidental resubmission.

`attach` records an existing session after fetching its status, without
submitting work. This supports sessions created by external HTTP clients.
Subsequent `status` and `download` commands use its recorded connection and user.

Database archives are created with `cga db zip --db-dir DIR --output FILE`.
Serve them through CGA's database-serving workflow; MRVA reads databases from
its configured store. There is no `submit --db` upload API.

`status` performs one status request and stores both the overall status and the
full response. It does not poll. `download` performs a fresh status request,
asks for each repository's artifact metadata, and downloads every available
archive. `verify` checks that each requested submission succeeded and has one
downloaded archive per repository.

`run` composes submit, repeated status requests, download, and verify into one
CGAST command. It submits the selected database set once; MRVA executes the
analyses. `--poll-seconds` defaults to 5 and `--timeout-seconds` sets a polling
deadline (default 1800 seconds; an HTTP request in progress may outlast it).
Every operation preserves input/output CGAST under the fresh `--log-dir`,
including `latest.state` for recovery after failure or timeout. Resume using
`status`/`download` with that state; `run` refuses an existing submission name
or a nonempty log directory to avoid accidental duplicate submissions.

Connection options are overridable per command or through environment defaults:

| Option               | Environment                 | Default                 |
| -------------------- | --------------------------- | ----------------------- |
| `--server`           | `CGA_MRVA_SERVER`           | `http://127.0.0.1:8081` |
| `--controller-owner` | `CGA_MRVA_CONTROLLER_OWNER` | `octo`                  |
| `--controller-repo`  | `CGA_MRVA_CONTROLLER_REPO`  | `ctl`                   |
| `--bearer-token`     | `CGA_MRVA_BEARER_TOKEN`     | unset                   |

## CGAST keys

| Key                 | Meaning                                     |
| ------------------- | ------------------------------------------- |
| `cgamr-submissions` | map of name to connection/session/run state |
| `cgamr-active`      | submission most recently acted on           |
| `cgamr-state`       | active lifecycle stage for the overview     |
| `cgamr-session`     | active session ID                           |
| `cgamr-note`        | active action summary                       |

Each named submission records its user, language, server/controller, session ID,
repositories, pack, latest status response, download directory, and result
archive paths. The fragment server renders the named submissions live from the
shared session CGAST.

See [`../sample-05/`](../sample-05/README.md) for the complete interactive
two-user sequence.

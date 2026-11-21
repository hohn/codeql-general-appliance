# MRVA runtime notes

Read for execution-system changes, starting with the relevant section and
owning module or named symbol below. Investigate that module before widening
to the whole-project map.

## Modules and deployment

- `server-commander` builds `mrvaserver`; `agent-commander-argo` builds
  `mrvaagent`. Both locally replace the shared `mrvacommander` module. Build
  each with `cd <module> && go build ./...`.
- Standalone uses host PostgreSQL, local artifact storage, a filesystem CodeQL
  database store, and `LocalArgoClient` worker subprocesses. Container mode uses
  Argo integrations; it is another prototype deployment path, not a declaration
  of production readiness.
- Cluster URLs under `example.com`, image/package names, identity-exchange URNs,
  and annotation domains are generic placeholders. Configure endpoint/image
  overrides and adapt the buildpack and identity integration values before
  deploying container mode; standalone mode does not use these integrations.
- Legacy release examples use `enterprise-gh` and `/opt/example` as placeholder
  tool names and installation paths; adapt them to the host before use.
- `cgamx` resolves build sources and default executables from its source checkout,
  independently of `CGAST_ROOT`/`CGA_ROOT`, which anchor workflow artifacts.
  Preserve explicit executable overrides such as `MRVA_ENVSIM_AGENT_BINARY`.
- Docker Compose files and `cmd/{server,agent}` Dockerfiles are earlier
  implementation material, not the starting local workflow.
- Compose and MinIO upload examples require exported `MINIO_ROOT_PASSWORD`;
  demo editors also require `CODE_SERVER_PASSWORD`. `.env.container` performs
  interpolation and preserves explicit store overrides; it is not a password
  store. Do not reintroduce shared passwords in scripts, images, or examples.
  Run `python3 -m unittest discover -s cga/tests -p test_container_credentials.py`
  for the template/upload credential checks.

## Configuration and scheduling

- Defaults live in Go and are filled only when environment variables are unset.
  Harnesses expose overrides; do not move hidden policy into them.
- `server-commander/main.go: applyStandaloneResourceDefaults()` exports resource
  defaults so the manager and spawned agents share them. Check that function
  before changing worker count, threads, or polling defaults.
- Every server runs a pool manager, but only the holder of the renewable
  PostgreSQL `scheduler_lock` lease runs pool cycles. Keep leader checks shorter
  than the lease. `MRVA_SERVER_ID` is an operator label; ownership uses a
  separate process-unique token. Advisory locks provide additional fencing.
- Submit wakes scheduling via `PoolManager.TriggerScheduling()`. Do not assume
  workers appear only on periodic ticks.
- Worker states are Idle, Busy, Draining, Exited. Starting workers are
  `pending_spawns`, not a fifth status; stale heartbeats can make apparently
  idle/busy workers unavailable.
- Worker/job coupling uses `worker_pool.current_job` as `sessionID/owner/repo`
  plus `job_info.worker_id`, not foreign keys.

## Identity

MRVA identity comes from JWT `sub` in container authentication or `X-MRVA-User`
in standalone development authentication. Deployment wiring selects the
authenticator; local examples do not require JWT infrastructure.

## Storage

- PostgreSQL stores state and references, never large source/database/result
  blobs. Artifacts use MinIO/S3 or the filesystem.
- Container mode uses externally provided HEPC database endpoints. Local CGA
  workflows serve database archives with `cgadbserve` or `cgamx`; this plain HTTP
  service does not implement the HEPC metadata protocol.
- `deploy.InitStandaloneArtifactStore` selects
  `MRVA_STANDALONE_STORAGE=minio|filesystem`; `--storage` overrides it and is
  inherited by workers. The Go default is MinIO, while the shared standalone
  harness defaults to filesystem for run-system-02. Do not conflate them.
- Cloud MinIO initialization uses HTTPS and a pre-provisioned bucket. Local
  initialization uses HTTP/path-style requests and may create the bucket.
- The local harness owns MinIO startup/shutdown; Go connects to it. Use the
  community server rather than accidentally installing a license-gated
  enterprise build. `MINIO_BIN` can select the executable.

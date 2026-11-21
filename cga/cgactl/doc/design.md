# Controller design

`cgactl` is the deterministic coordinator for the CVE database campaign. A
single PostgreSQL database is authoritative for job state. Builders are
disposable clients and may own at most one leased job at a time.

## Invariants

- A job is immutable after it is loaded from the campaign manifest.
- Claiming is serialized with `FOR UPDATE SKIP LOCKED`.
- A partial unique index permits only one active job per builder.
- Every attempt has a random lease token. Mutations require the current job,
  builder, token, and an unexpired lease.
- Expiration closes the old attempt and requeues the job; it does not erase
  history.
- Database rows contain metadata and artifact references, never large blobs.
- The dashboard exposes GET routes only.
- Technical attempt status is separate from campaign `lane` and `disposition`.
- Every attempt records its base snapshot, resource profile, container, and
  effective environment; later sweeps never overwrite earlier attempts.
- An exclusive-host job can start only when no other build is active, and no
  other job can start while it is active.
- Successful attempts enter a durable promotion queue in the same transaction
  as their terminal result.

## Campaign lanes

The normal path is `static`. A static technical failure stops at
`awaiting-llm`; it does not immediately consume another attempt. A controller
sweep changes the job to `queued/llm-repair`, after which a new claim creates a
new attempt. An LLM failure stops at `escalated`. A master sweep may assign a
new snapshot, larger resource profile, and exclusive-host scheduling before a
`master-recovery` attempt. This makes campaign policy explicit and auditable.

Every claimed attempt must be prepared before execution. The host stops its
Incus container, restores the registered immutable snapshot, applies limits,
starts it, and records requested/effective resources. Snapshot toolchain
identity must equal the job toolchain identity. LLMs have unrestricted control
inside the resulting disposable container; the deterministic controller still
owns identity, leases, scheduling, validation, and promotion.
Claims require an active registered snapshot whose toolchain matches the job;
unconfigured jobs cannot be claimed. Resource profiles may cap concurrent
claims in addition to per-container CPU/RAM/disk limits. Claim selection holds
a scheduler advisory lock while checking normal profile concurrency and the
exclusive-host invariant.
When builder metadata includes `container`, claims are additionally restricted
to snapshots registered for that container. This prevents cloned workers from
claiming attempts they cannot reset to the recorded baseline.

## Trust boundary

The initial CLI connects directly to PostgreSQL, but all queue mutations are
implemented by schema functions. A deployment should give builder roles only
`EXECUTE` on `register_builder`, `claim_job_v2`, `renew_lease`, `set_phase`,
`record_attempt_environment`, and `finish_job`, plus only the read access
actually required. Schema installation,
manifest loading, reconciliation, and unrestricted table access remain
controller privileges.

The returned claim includes its opaque `lease_token`. A builder must persist
that token with its local attempt state and include it in every later command.
It should renew well before expiry. Losing a lease is terminal for that local
process: it may retain logs, but must not publish a database under the campaign
result identity.

The deployed builder functions are `SECURITY DEFINER` with a fixed search path.
The schema revokes public access; a builder role receives schema usage and
execute permission on only registration, claim, renewal, phase, and finish. It
receives no direct table privileges. Controller-only operations such as
manifest loading, retry, reconciliation, promotion, and dashboard reads use the
database owner.

## Master collection

Promotion is a host/controller operation. It never trusts an artifact merely
because a builder returned success: it fetches the recorded URI, verifies size
and digest, asks CodeQL to unbundle and resolve the database, then publishes by
atomic rename. The qldbstore repository identity is the upstream package name
plus the full database-bundle SHA-256. Variant and mode remain provenance, not
identity. The SQLite catalogue and provenance sidecar are written only after
bundle validation. Collection status and reconciliation commands are read-only
audits. The host promoter claims the durable queue and calls the same idempotent
promotion operation. A crash leaves either a completed promotion or a stale
claim that can be requeued; it never authorizes a builder to write the master
collection.

## Recovery

Run `cgactl requeue-expired` periodically from exactly one reconciler. The
operation itself is safe to repeat. PostgreSQL downtime pauses claims and
updates; it does not invalidate external artifacts. Restore coordination from
backup, reload the deterministic manifest, and reconcile published
`result.json` files when disaster recovery is required.

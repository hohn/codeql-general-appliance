# run-system-08

Two-server regression scenario for scheduling a fresh workload after every
worker from an earlier workload has exited.

Each wave concurrently submits one two-database analysis for `alice` and one
for `bob`, with the requests split across the two server endpoints. The test
waits for wave 1 to finish, downloads all four result archives, waits for the
worker pool to scale to zero, then repeats the same submission structure with
the endpoint assignments swapped.

```bash
cga/system-tests/run-system-08/run all
cga/system-tests/run-system-08/run stale-status-recovery
cga/system-tests/run-system-08/run evidence
cga/system-tests/run-system-08/run cleanup
```

`all` leaves the two servers and PostgreSQL running for inspection. If a wave
times out, the test writes PostgreSQL state, both sysview snapshots, process
state, and both server-log tails to `/tmp/mrva-queue-restart/`.

`stale-status-recovery` inserts four orphan Queued rows into `job_status`
between waves. The rows have no corresponding `analyze_jobs` or `job_info`
records. They remain present as evidence, but must not consume worker capacity,
be claimed as work, or prevent the four legitimate wave-2 jobs from completing.

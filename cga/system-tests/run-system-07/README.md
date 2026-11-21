# run-system-07

Two-server standalone test for the PostgreSQL lease-based pool-manager leader
election. It verifies initial leader/backup roles, failover, rejoin, stable roles
while one user's multi-job session runs, and both `/sysview/data` streams.

From any directory:

```sh
cga/system-tests/run-system-07/run all
cga/system-tests/run-system-07/run sysview
cga/system-tests/run-system-07/run cleanup
```

`all` intentionally leaves both servers running and PostgreSQL populated.
Scenario state is isolated under `/tmp/mrva-standalone-election` and
`/tmp/mrva-election`; the servers default to ports 8081 and 8082.

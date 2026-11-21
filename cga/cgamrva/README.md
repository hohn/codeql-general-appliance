# cgamrva — MRVA server and worker lifecycle

```sh
cgamrva start --binary /absolute/path/to/mrvaserver
cgamrva check
cgamrva stop
cgamrva info
```

Commands read and write CGAST; only `cgamrva` is changed. Start owns just
MRVA and its workers. PostgreSQL, the archive server and any external object
store must already be available; it neither starts nor stops those services.

Configuration uses the same environment defaults as `cgamx`, including
`PORT`, `POSTGRES_*`, `MRVA_WORK_DIR`, `MRVA_TMP_DIR`,
`MRVA_DB_SERVER_URL`, `MRVA_STANDALONE_STORAGE`, and worker/CodeQL limits.
Explicit environment settings take precedence. For the zlib study the artifact
store is `filesystem`, with separate `cgapg` and `cgadbserve` services.
The existing `cgamx` combined lifecycle remains available to older callers.

Start refuses an occupied port or existing log and rolls back its process on
failure. Check requires a live service and rejects non-benign server-log
errors (`mrva-project-resolver` warnings remain exempt). Stop targets only the
recorded Linux process identity and its process group, including workers;
it preserves database contents, artifacts and logs. No port reclamation,
table reset, database build or query submission happens here.

# cgapg — private PostgreSQL lifecycle

CGAST JSON-in/JSON-out filters; progress and PostgreSQL output go to stderr.
Only the `cgapg` state key is changed. Other keys pass through unchanged.

```sh
cgapg init --data-dir DIR --bin-dir PGBIN --port PORT [--user study]
cgapg start
cgapg createdb NAME
cgapg check
cgapg stop
cgapg info
```

`init` requires a new data directory. `start` uses loopback TCP only, with
Unix sockets disabled. This isolated development service uses trust auth:
any local user can connect. Do not expose it to a network or use it for
production data. The selected tools, paths, port, user, databases and process
identity are carried in CGAST. `stop` preserves the cluster and its log;
there is no reset/delete command and no port reclamation.

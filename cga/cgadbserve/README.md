# cgadbserve

## Name

`cgadbserve` - serve CodeQL database archives to local MRVA workers

## Synopsis

```sh
cgadbserve start --directory DIR --port PORT --log FILE
cgadbserve check
cgadbserve stop
cgadbserve info
```

## Description

`cgadbserve` runs a loopback-only HTTP service over an existing qldbstore
directory. MRVA workers fetch selected CodeQL database ZIP files from this
service during analysis.

Commands read and write CGAST; only `cgadbserve` is changed. The service does
not create, download, unpack, select, or evaluate databases. `cgadl download`
may populate the served directory after startup.

Start refuses an occupied port or existing log. Failed starts stop their own
process. Stop uses the recorded PID and Linux process identity, never an
unrelated listener found by port. It preserves database archives and logs. Use
a new log path when restarting. This is an unauthenticated local development
service bound to `127.0.0.1`.
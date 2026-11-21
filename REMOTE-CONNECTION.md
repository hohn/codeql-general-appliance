# Remote connection

Use SSH local forwarding when CGA runs on a remote Linux machine. The CGA
servers intentionally bind to remote loopback (`127.0.0.1`); they do not need to
be exposed through the remote firewall.

## One URL for viewers and documentation

On the remote host, start the configured viewers and gateway:

```sh
cga serve start
```

Use `cga gateway start` instead for documentation alone or independently managed
viewers. On your workstation, forward just the gateway port:

```sh
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 \
  -L 8599:127.0.0.1:8599 user@remote.example
```

Open **http://127.0.0.1:8599/**. The landing page links to viewers and the
remote checkout's **CGA overview**, **CGA help**, and **Reference manual**.
Documentation and its relative links render through the same tunnel; no local
checkout or extra documentation port is needed. Build the optional reference
manual on the remote host with `make -C docs book`.

Reconnect using the same SSH command. `cga serve stop` stops aggregate-owned
services; `cga gateway stop` stops only the gateway. See the
[gateway guide](cga/cgagateway/README.md) for configuration, ownership, and
documentation rebuild commands.

The direct-port forwarding below remains available for development and older
launchers; it is not required when using the gateway.

## CGA ports

The directly accessed composite page is not a reverse proxy. Its browser-side
JavaScript fetches each component fragment directly from a separate `127.0.0.1`
URL generated in `cga/web/cga-config.js`. Consequently, forwarding only the
composite page port loads the page shell but leaves its panels unavailable.

`cga/sample-05` uses these dedicated defaults:

| Port | Environment variable | Service               | Browser use      |
| ---: | -------------------- | --------------------- | ---------------- |
| 8700 | `CGA_PAGE_PORT`      | Composite static page | Main page        |
| 8701 | `CGA_CGASV_PORT`     | `cgasv`               | Header           |
| 8702 | `CGA_CGADL_PORT`     | `cgadl`               | Database library |
| 8703 | `CGA_CGAQL_PORT`     | `cgaql`               | Query library    |
| 8704 | `CGA_CGAMR_PORT`     | `cgamr`               | MRVA requestor   |
| 8705 | `CGA_CGAMU_PORT`     | `cgamu`               | MRVA user view   |
| 8706 | `CGA_CGASI_PORT`     | `cgasi`               | SARIF ingestion  |
| 8707 | `CGA_CGAMX_PORT`     | `cgamx`               | Command bridge   |
| 8708 | `CGA_CGAEX_PORT`     | `cgaex`               | Result exports   |

All nine ports are required to use the complete sample-05 page remotely.

The generic `cga run` command uses the same sequence at `8600`–`8608`. Use
the port family belonging to the launcher being run; do not forward both unless
both CGA instances are intentionally active.

## Forward sample-05

Run the numbered workflow on the remote host as usual, beginning with:

```sh
cd cga/sample-05
./00-start-cga.sh
```

On the local machine, open a second terminal and establish the tunnel. Replace
`user@remote.example` with the same SSH destination normally used to reach the
Linux host:

```sh
REMOTE_CGA_HOST=user@remote.example
ssh -N -T \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 8700:127.0.0.1:8700 \
  -L 8701:127.0.0.1:8701 \
  -L 8702:127.0.0.1:8702 \
  -L 8703:127.0.0.1:8703 \
  -L 8704:127.0.0.1:8704 \
  -L 8705:127.0.0.1:8705 \
  -L 8706:127.0.0.1:8706 \
  -L 8707:127.0.0.1:8707 \
  -L 8708:127.0.0.1:8708 \
  "$REMOTE_CGA_HOST"
```

`-N` runs no remote command, `-T` avoids allocating a terminal, and
`ExitOnForwardFailure` makes SSH fail immediately if any local port is already
occupied. Leave this SSH process running, then open:

```text
http://127.0.0.1:8700/
```

The local port numbers must match the remote CGA port numbers. The downloaded
`cga-config.js` tells the local browser to fetch, for example,
`http://127.0.0.1:8704/detail`; mapping that remote service to a different local
port would not change the generated browser URL.

If a local port is occupied, choose a different complete CGA port family on the
remote host before starting CGA, then forward the same numbers locally. For
example:

```sh
export CGA_PAGE_PORT=8800
export CGA_CGASV_PORT=8801
export CGA_CGADL_PORT=8802
export CGA_CGAQL_PORT=8803
export CGA_CGAMR_PORT=8804
export CGA_CGAMU_PORT=8805
export CGA_CGASI_PORT=8806
export CGA_CGAMX_PORT=8807
export CGA_CGAEX_PORT=8808
./00-start-cga.sh
```

Forward `8800`–`8808` one-for-one in that case.

## Forward the generic CGA dashboard

For `cga run start`, substitute the generic defaults:

```sh
REMOTE_CGA_HOST=user@remote.example
ssh -N -T \
  -o ExitOnForwardFailure=yes \
  -L 8600:127.0.0.1:8600 \
  -L 8601:127.0.0.1:8601 \
  -L 8602:127.0.0.1:8602 \
  -L 8603:127.0.0.1:8603 \
  -L 8604:127.0.0.1:8604 \
  -L 8605:127.0.0.1:8605 \
  -L 8606:127.0.0.1:8606 \
  -L 8607:127.0.0.1:8607 \
  -L 8608:127.0.0.1:8608 \
  "$REMOTE_CGA_HOST"
```

Then open `http://127.0.0.1:8600/` locally.

## Forward CGA preparation

CGA preparation has an independent page and session. To access it directly
without the gateway (for example, `cd cga && ./cga-prep-run start`), forward its
five ports:

```sh
REMOTE_CGA_HOST=user@remote.example
ssh -N -T \
  -o ExitOnForwardFailure=yes \
  -L 8500:127.0.0.1:8500 \
  -L 8501:127.0.0.1:8501 \
  -L 8502:127.0.0.1:8502 \
  -L 8503:127.0.0.1:8503 \
  -L 8504:127.0.0.1:8504 \
  "$REMOTE_CGA_HOST"
```

Then open `http://127.0.0.1:8500/` locally. Forwarding CGA preparation does not require
forwarding CGA unless both pages are in use.

## MRVA and storage ports

The sample-05 workflow starts supporting services in addition to the nine CGA
listeners. They communicate with each other on the remote machine and are not
required for the composite browser page:

| Remote port | Service                     | Forward when                                    |
| ----------: | --------------------------- | ----------------------------------------------- |
|        8081 | MRVA API and live sysview   | Viewing `/sysview` or calling the API locally   |
|        9000 | MinIO S3 API                | Inspecting objects with a local MinIO client    |
|        9080 | CodeQL database HTTP server | Never for normal use; MRVA accesses it remotely |
|        5432 | PostgreSQL                  | Inspecting the database with a local SQL client |

Add the MRVA sysview to the sample-05 tunnel with:

```sh
-L 8081:127.0.0.1:8081
```

and open `http://127.0.0.1:8081/sysview`. This forwarding is recommended for
operational visibility, but CGA's browser fragments do not depend on it.

MinIO can also use the same port locally:

```sh
-L 9000:127.0.0.1:9000
```

PostgreSQL commonly already occupies local port 5432, so use a different local
port when forwarding it:

```sh
-L 15432:127.0.0.1:5432
```

Then connect to `127.0.0.1:15432`. Unlike the CGA fragment ports, these
operational clients accept an arbitrary local port because no generated browser
configuration fixes their local URL.

The mdBook preview (`3000`) and sysview replay server (`8090`) are separate
tools, not part of a running CGA system. Forward them only when those tools are
started explicitly.

## Verify the tunnel

With the SSH process running, check the page and every fragment from the local
machine:

```sh
curl -fsS http://127.0.0.1:8700/index.html >/dev/null
for CGA_PORT in 8701 8702 8703 8704 8705 8706 8707 8708; do
  curl -fsS "http://127.0.0.1:${CGA_PORT}/healthz"
done
```

Every health check should print `ok`. A page shell with red “Failed to fetch”
panels usually means the `8700` page tunnel works but one or more fragment
tunnels are missing. On the remote host, check the sample-specific listeners
with:

```sh
cd cga/sample-05
. ./_common.sh
cga run status
```

That status output and local `ssh -v` diagnostics distinguish a stopped fragment
server from a tunnel failure.

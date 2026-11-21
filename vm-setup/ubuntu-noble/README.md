# Ubuntu Noble development machine setup

This directory provisions an Ubuntu 24.04 (Noble Numbat) amd64 or arm64
machine for CGA, CGA preparation, and standalone MRVA development. The
canonical cross-distribution dependency discussion remains in
[`INSTALL.md`](../../INSTALL.md).

## Usage

Inspect package candidates, installation status, cached tools, and optional
tools without changing the machine:

```sh
./vm-setup/ubuntu-noble/install-dependencies.sh --list
```

Install all required dependencies, enable PostgreSQL, and publish cached tools
under `/usr/local/bin`:

```sh
./vm-setup/ubuntu-noble/install-dependencies.sh
```

The script uses `sudo` when it is not already running as root and is
idempotent. Apt handles Ubuntu packages, while downloaded tools are retained
under the sibling `single-machine-mrva-artifacts/tools/` tree.

Optional packages and MinIO use the same explicit flags as the Sid setup:

```sh
./vm-setup/ubuntu-noble/install-dependencies.sh --with-table-tools
./vm-setup/ubuntu-noble/install-dependencies.sh --with-dev-tools
./vm-setup/ubuntu-noble/install-dependencies.sh --with-minio
./vm-setup/ubuntu-noble/install-dependencies.sh --with-optional
```

## Noble-specific differences

Ubuntu Noble supplies the required base, build, Debian-source, Java,
PostgreSQL, Python, and SQLite packages. Its repositories do not supply
DuckDB or mdBook, and its `golang-go` package is older than the repository's
Go 1.25 minimum. The installer therefore uses checksum-verified upstream
archives for:

| Tool | Pinned version | Installation |
| --- | --- | --- |
| Go | 1.25.12 fallback | Reuses an already-installed Go 1.25+; otherwise caches the official Go archive |
| DuckDB CLI | 1.5.5 | Caches the official GitHub release binary |
| mdBook | 0.5.4 | Caches the official GitHub release binary |
| CodeQL bundle | 2.27.1 | Caches the architecture-specific GitHub CodeQL bundle and checksum |

The cached binaries are linked into `/usr/local/bin`. CodeQL also receives
`CODEQL_JAVA_HOME=/usr` through `/etc/profile.d/mrva-codeql.sh`.

Override the artifact path when needed:

```sh
TOOLS_DIR=/srv/mrva-artifacts/tools \
  ./vm-setup/ubuntu-noble/install-dependencies.sh
```

## Required Ubuntu packages

The default installation requires these apt packages:

| Purpose | Packages |
| --- | --- |
| Shell and base utilities | `bash`, `bsdextrautils`, `ca-certificates`, `curl`, `gzip`, `less`, `procps`, `tar`, `unzip`, `util-linux`, `xz-utils`, `zip`, `zstd` |
| Native and Debian builds | `build-essential`, `devscripts`, `dpkg-dev` |
| Source and file transfer | `git`, `rsync` |
| Python | `python3`, `python3-pip`, `python3-venv` |
| CodeQL runtime | `default-jre-headless` |
| PostgreSQL | `postgresql`, `postgresql-client` |
| Data and SARIF tools | `jq`, `sqlite3` |
| Harness and port inspection | `iproute2`, `lsof` |

`devscripts` provides `dget`, and `dpkg-dev` provides `dpkg-source`; both are
used by CGA preparation's Debian source materialization workflow.

## Verification

The installer prints versions for Go, Python, PostgreSQL, SQLite, DuckDB,
mdBook, and CodeQL. Continue with the canonical non-destructive preflight:

```sh
cd cga/system-tests
./run-system-02 preflight
```

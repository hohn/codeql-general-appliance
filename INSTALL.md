# Install repository dependencies

These instructions prepare a Debian or Ubuntu Linux host for local development,
the standalone MRVA system tests, the CGA sample workflow, SARIF ingestion, and
the documentation build. The production/container paths have additional
infrastructure requirements, but they are not needed for the single-machine
workflow.

The shortest useful path is:

1. install the core Debian packages;
2. install Go 1.25 or newer and the CodeQL bundle;
3. start PostgreSQL;
4. install MinIO for the MinIO-backed samples;
5. install DuckDB for SARIF ingestion; and
6. install mdBook 0.5 or newer to build these docs.

For a dedicated Debian sid development VM, the required and optional package
groups below are automated by
[`vm-setup/debian-sid/install-dependencies.sh`](vm-setup/debian-sid/install-dependencies.sh).
Review candidates and cached downloads with `--list`, then run the script with
no options for the required CGA/MRVA environment. Its
[`README`](vm-setup/debian-sid/README.md) is the explicit Debian sid inventory.

Ubuntu 24.04 Noble hosts use the parallel
[`vm-setup/ubuntu-noble/install-dependencies.sh`](vm-setup/ubuntu-noble/install-dependencies.sh)
installer. Noble's apt repositories do not provide sufficiently recent Go or
mdBook packages, or a DuckDB CLI package, so that installer caches and verifies
pinned upstream archives for those tools. See its
[`README`](vm-setup/ubuntu-noble/README.md) for the exact inventory.

## Core Debian/Ubuntu packages

Install the compiler, Python, PostgreSQL, Java, and the command-line utilities
used directly by the Makefiles and test harnesses:

```sh
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  bash \
  build-essential \
  ca-certificates \
  curl \
  default-jre-headless \
  git \
  iproute2 \
  jq \
  lsof \
  postgresql \
  postgresql-client \
  procps \
  python3 \
  python3-pip \
  python3-venv \
  rsync \
  sqlite3 \
  tar \
  unzip \
  util-linux \
  xz-utils \
  zip \
  zstd
```

The less-obvious packages are intentional: `lsof` and `iproute2` reclaim
orphaned listener ports, `procps` provides `pgrep`, `default-jre-headless`
provides the native Java runtime needed by CodeQL on ARM64, and the archive
tools stage CodeQL databases and result bundles.

The CGA tools and SARIF-to-SQLite converter use only the Python
standard library.

## Go 1.25 or newer

Every Go module in this repository declares Go 1.25. First check the version
offered by the distribution:

```sh
apt-cache policy golang-go
```

If its candidate is 1.25 or newer, use apt:

```sh
sudo apt-get install -y golang-go
```

Older Debian and Ubuntu releases package an older Go toolchain. In that case,
install a current Go 1.25 patch release using the
[official Linux archive](https://go.dev/doc/install). This example supports the
two architectures used by this repository:

```sh
GO_VERSION=1.25.12
case "$(dpkg --print-architecture)" in
  amd64) GO_ARCH=amd64 ;;
  arm64) GO_ARCH=arm64 ;;
  *) echo "unsupported Go architecture" >&2; exit 1 ;;
esac
GO_ARCHIVE="go${GO_VERSION}.linux-${GO_ARCH}.tar.gz"
GO_TMPDIR="$(mktemp -d)"
curl -fL "https://go.dev/dl/${GO_ARCHIVE}" -o "${GO_TMPDIR}/${GO_ARCHIVE}"
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf "${GO_TMPDIR}/${GO_ARCHIVE}"
sudo ln -sfn /usr/local/go/bin/go /usr/local/bin/go
sudo ln -sfn /usr/local/go/bin/gofmt /usr/local/bin/gofmt
rm -rf "${GO_TMPDIR}"
go version
```

Go downloads the modules' library dependencies during `go build` or
`go mod download`; no system-wide installation is needed for those libraries.

## CodeQL bundle

The system tests require CodeQL 2.23.6 or newer. GitHub recommends the complete
[CodeQL bundle](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/scan-from-the-command-line/set-up-codeql-cli),
which keeps the CLI, queries, and libraries compatible. The repository pins
2.27.1 and selects the dedicated Linux ARM64 bundle on `arm64`/`aarch64`:

```sh
CODEQL_VERSION=v2.27.1
CODEQL_TAG="codeql-bundle-${CODEQL_VERSION}"
case "$(uname -m)" in
  aarch64|arm64) CODEQL_ARCHIVE=codeql-bundle-linux-arm64.tar.gz ;;
  x86_64|amd64) CODEQL_ARCHIVE=codeql-bundle-linux64.tar.gz ;;
  *) echo "unsupported CodeQL architecture" >&2; exit 1 ;;
esac
CODEQL_INSTALL_ROOT="/opt/codeql-${CODEQL_VERSION}"
CODEQL_TMPDIR="$(mktemp -d)"

curl -fL \
  "https://github.com/github/codeql-action/releases/download/${CODEQL_TAG}/${CODEQL_ARCHIVE}" \
  -o "${CODEQL_TMPDIR}/${CODEQL_ARCHIVE}"
curl -fL \
  "https://github.com/github/codeql-action/releases/download/${CODEQL_TAG}/${CODEQL_ARCHIVE}.checksum.txt" \
  -o "${CODEQL_TMPDIR}/${CODEQL_ARCHIVE}.checksum.txt"
(cd "${CODEQL_TMPDIR}" && sha256sum -c "${CODEQL_ARCHIVE}.checksum.txt")

sudo mkdir -p "${CODEQL_INSTALL_ROOT}"
sudo tar -C "${CODEQL_INSTALL_ROOT}" -xzf "${CODEQL_TMPDIR}/${CODEQL_ARCHIVE}"
sudo ln -sfn "${CODEQL_INSTALL_ROOT}/codeql/codeql" /usr/local/bin/codeql
rm -rf "${CODEQL_TMPDIR}"
```

The 2.27.1 ARM64 bundle contains native binaries. This repository still points
CodeQL at the host JRE for a consistent runtime across installations:

```sh
export CODEQL_JAVA_HOME=/usr
codeql version --format=terse
codeql resolve packs
```

On Debian specifically, the repository's provisioner performs the same bundle,
checksum, Java, and profile setup:

```sh
sudo env CODEQL_VERSION=v2.27.1 \
  ./vm-setup/lima-debian/scripts/provision-debian-codeql.sh
```

## PostgreSQL

The standalone server stores its state in a host PostgreSQL instance. Start it
and verify that the client can reach it:

```sh
sudo systemctl enable --now postgresql
pg_isready -h localhost -p 5432
```

The system-test preflight creates the current Unix user's PostgreSQL role and
the default `mrvadev` database when they do not exist. Override `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` when
using an existing server.

## MinIO for object-storage workflows

`run-system-03`, `run-system-04`, `run-system-05`, and `cga/sample-05` default
to the MinIO artifact backend. The repository needs the community server binary;
do not install the current `minio` Debian package, which may provide the
licensed AIStor build instead.

```sh
case "$(dpkg --print-architecture)" in
  amd64) MINIO_ARCH=amd64 ;;
  arm64) MINIO_ARCH=arm64 ;;
  *) echo "unsupported MinIO architecture" >&2; exit 1 ;;
esac
curl -fL "https://dl.min.io/server/minio/release/linux-${MINIO_ARCH}/minio" \
  -o /tmp/minio
sudo install -m 0755 /tmp/minio /usr/local/bin/minio
minio --version
```

The harness starts and stops MinIO itself. To avoid MinIO entirely where the
scenario permits it, set `MRVA_STANDALONE_STORAGE=filesystem`.

The optional MinIO client is useful for the object-inspection recipes in the
system-test documentation. It is installed as `mcli` to avoid colliding with
Midnight Commander's `mc` command:

```sh
curl -fL "https://dl.min.io/client/mc/release/linux-${MINIO_ARCH}/mc" \
  -o /tmp/mcli
sudo install -m 0755 /tmp/mcli /usr/local/bin/mcli
mcli --version
```

The legacy `populate-dbstore.sh` and `populate-qpstore.sh` scripts call the
client as `mc`; install the same binary under that name only when those scripts
are needed and it will not conflict with another `mc` command.

## SARIF ingestion

SQLite is installed by the core apt command. The cumulative SARIF database also
requires the DuckDB CLI. DuckDB's official installer supports both AMD64 and
ARM64 Linux:

```sh
curl -fsSL https://install.duckdb.org | sh
export PATH="$HOME/.duckdb/cli/latest:$PATH"
duckdb --version
sqlite3 --version
```

Persist the `PATH` addition in the shell profile used for MRVA. No Python DuckDB
package is needed; `sarif-ingest/bin/srfi` and `cgasi` invoke the CLI.

## Documentation and formatting

### mdBook

The documentation requires mdBook 0.5 or newer. Check the apt candidate first:

```sh
apt-cache policy mdbook
```

Use `sudo apt-get install -y mdbook` when the candidate is at least 0.5. Many
Debian/Ubuntu releases still package mdBook 0.4; for those, install current Rust
with rustup and then mdBook using its
[preferred Cargo installation](https://rust-lang.github.io/mdBook/guide/installation.html):

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
  | sh -s -- -y
. "$HOME/.cargo/env"
cargo install mdbook --version '^0.5.4' --locked
mdbook --version
```

Build or live-preview the book with:

```sh
make book
make view-book
```

### Recommended optional Markdown previewers

[Glow](https://github.com/charmbracelet/glow) provides a quick terminal preview;
[go-grip](https://github.com/chrishrb/go-grip) renders individual Markdown files
in a browser with automatic reload when they change. These are convenience
tools, not required for building, running, or testing the project.

Install Glow with your distribution's package manager (`sudo dnf install glow`
on Fedora). Install go-grip with Go:

```sh
go install github.com/chrishrb/go-grip@latest
export PATH="$(go env GOPATH)/bin:$PATH"
```

Preview a file with either tool:

```sh
glow -p README.md
go-grip README.md
```

go-grip opens the browser at `http://localhost:6419`; stop its server with
Ctrl-C. Use `make view-book` for the assembled project documentation instead.

### Markdown and VM checks

Repository-wide Markdown formatting uses Prettier. The VM setup checks also use
ShellCheck, shfmt, yamllint, Ruby mdl, and `markdownlint-cli`:

```sh
sudo apt-get install -y \
  nodejs \
  npm \
  ruby-mdl \
  shellcheck \
  shfmt \
  yamllint
sudo npm install -g prettier markdownlint-cli
```

Optional legacy document and dependency-graph Makefile targets use Pandoc and
Graphviz:

```sh
sudo apt-get install -y graphviz pandoc
go install github.com/kisielk/godepgraph@latest
```

The shared-library lint target expects golangci-lint:

```sh
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
```

Ensure the Go binary directory is on `PATH` for the two Go-installed tools:

```sh
export PATH="$(go env GOPATH)/bin:$PATH"
```

## Optional container and VM tooling

Standalone mode does not require Docker, Argo, Kubernetes, QEMU, or Lima. The
container Makefiles are legacy, while `vm-setup/` uses Lima and QEMU for
isolated CodeQL guests. Install only the path being exercised:

```sh
# Legacy container Makefile targets.
sudo apt-get install -y docker.io docker-compose

# Linux host dependencies for vm-setup/lima-*.
sudo apt-get install -y \
  devscripts \
  openssh-client \
  qemu-system-arm \
  qemu-utils \
  rsync \
  sshpass
```

Install Lima itself from its upstream release, then follow the detailed
`vm-setup/lima-debian` or `vm-setup/lima-void` instructions.

The legacy qldbtools metadata scripts use `yq` in addition to their Python
requirements:

```sh
sudo apt-get install -y yq
python3 -m venv mrvacommander/client/qldbtools/.venv
. mrvacommander/client/qldbtools/.venv/bin/activate
python3 -m pip install \
  -r mrvacommander/client/qldbtools/requirements.txt \
  -e mrvacommander/client/qldbtools
```

## Verify the prepared host

Start with version checks, then let the canonical harness validate PostgreSQL,
CodeQL, Go, and port management:

```sh
export CODEQL_JAVA_HOME=/usr
go version
python3 --version
psql --version
codeql version --format=terse
mdbook --version

cd cga/system-tests
./run-system-02 preflight
```

For the complete local workflow, continue with `./run-system-02 all`. MinIO and
SARIF ingestion are intentionally separate: use a MinIO-backed scenario and run
its `tolite`/`toduck` or `cgasi ingest` phase when those paths are needed.

## Installation complete: open CGA

With the `cga` command installed and on `PATH` (see
[dispatcher installation](README.md#cga-command-line-interface)), start the
documentation gateway on the CGA machine:

```sh
cga gateway start
cga gateway status
```

For a remote VM, keep an SSH tunnel open from your workstation. Replace
`hohn@svm` with your SSH destination:

```sh
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 \
  -L 8599:127.0.0.1:8599 hohn@svm
```

Open **http://127.0.0.1:8599/** in your workstation's browser, or directly on
the CGA machine for local use. Choose **CGA overview** and follow **Sample 05 in
section 03** for a first analysis.

No initialized workflow, running MRVA, or configured viewers are needed. The
overview and help are already rendered; no documentation build is required. The
reference manual is optional and built separately.

Reconnect with the same SSH command. Stop only the gateway with
`cga gateway stop`.

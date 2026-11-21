# Debian sid development VM setup

This directory provisions a Debian sid machine whose primary purpose is CGA,
CGA preparation, and standalone MRVA development. The canonical cross-distribution
dependency discussion remains in [`INSTALL.md`](../../INSTALL.md); this setup
turns its Debian requirements into one repeatable host installation.

## Usage

Inspect package candidates, installation status, cached tools, and optional
tools without changing the machine:

```sh
./vm-setup/debian-sid/install-dependencies.sh --list
```

Install all required dependencies, enable PostgreSQL, and publish cached tools
under `/usr/local/bin`:

```sh
./vm-setup/debian-sid/install-dependencies.sh
```

The script uses `sudo` when it is not already running as root. It is
idempotent: apt handles installed packages, and upstream tools are downloaded
only when their cached executable is absent.

Optional packages are reported by `--list` and installed only when requested:

```sh
./vm-setup/debian-sid/install-dependencies.sh --with-table-tools
./vm-setup/debian-sid/install-dependencies.sh --with-dev-tools
./vm-setup/debian-sid/install-dependencies.sh --with-optional
```

An optional package is passed to `apt-get install` only when `apt-cache policy`
reports a candidate in the VM's configured Debian repositories. The installer
does not fall back to Cargo, Go, pip, npm, or arbitrary release binaries for
optional tools.

## Required Debian packages

The default installation requires these system-wide apt packages:

| Purpose | Packages |
| --- | --- |
| Shell and base utilities | `bash`, `bsdextrautils`, `ca-certificates`, `curl`, `less`, `procps`, `tar`, `unzip`, `util-linux`, `xz-utils`, `zip`, `zstd` |
| Native and Debian builds | `build-essential`, `devscripts`, `dpkg-dev` |
| Source and file transfer | `git`, `rsync` |
| Go and Python | `golang-go`, `python3`, `python3-pip`, `python3-venv` |
| CodeQL runtime | `default-jre-headless` |
| PostgreSQL | `postgresql`, `postgresql-client` |
| Data and SARIF tools | `duckdb`, `jq`, `sqlite3` |
| Harness and port inspection | `iproute2`, `lsof` |
| Documentation | `mdbook` |

The script requires Go 1.25 or newer after apt installation. Debian sid
currently satisfies that requirement. It fails clearly if a configured mirror
offers an older version rather than silently installing a second Go toolchain.
It likewise verifies the repository's mdBook 0.5 minimum after installation.

`devscripts` provides `dget`, and `dpkg-dev` provides `dpkg-source`; both are
called directly by CGA preparation's Debian source materialization workflow. PostgreSQL
and DuckDB are intentionally system packages on this dedicated development VM.

## Cached upstream tools

CodeQL is required, and the community MinIO server is optional (`--with-minio`);
neither is installed from Debian packages. Downloads are retained under the
sibling artifact tree:

```text
single-machine-mrva-artifacts/tools/
|-- codeql-2.27.1/codeql/
|-- downloads/codeql-bundle-v2.27.1-codeql-bundle-linux-ARCH.tar.gz
`-- minio-ARCH/minio
```

The default artifact path is derived from the repository location. Override it
with `TOOLS_DIR` or `--tools-dir`:

```sh
TOOLS_DIR=/srv/mrva-artifacts/tools \
  ./vm-setup/debian-sid/install-dependencies.sh
```

The installer:

1. uses an existing complete CodeQL bundle without downloading it again;
2. otherwise downloads the pinned architecture-specific archive and checksum
   once (`linux-arm64` on ARM64, `linux64` on x86_64), verifies the archive,
   and extracts it atomically;
3. links the cached CodeQL binary as `/usr/local/bin/codeql`; and
4. writes `/etc/profile.d/mrva-codeql.sh` with `CODEQL_JAVA_HOME=/usr` and a
   `PATH` entry for the extracted CodeQL tree.

With `--with-minio` (also enabled by `--with-optional`) it additionally reuses
or downloads the architecture-specific community MinIO server once and links it
as `/usr/local/bin/minio`. Local runs do not need MinIO (they use filesystem
storage) and large deployments use a provided S3 service.

The CodeQL bundle is subject to GitHub's CodeQL terms. MinIO is fetched from
the community server download endpoint; the installer intentionally does not
install the Debian `minio` package because that name may refer to AIStor.

## Optional table tools

The names typed at the command line are not always Debian package names:

| Requested command | Debian package checked | Installed command | Sid status on 2026-09-16 |
| --- | --- | --- | --- |
| `vd` | `visidata` | `vd` | Available |
| `mlr` | `miller` | `mlr` | Available |
| `cvslens` | `csvlens` | `csvlens` | Unavailable; `cvslens` was also a typo |
| `tsv-utils` | `tsv-utils` | `tsv-summarize` and related tools | Unavailable |
| `xsv` | `xsv` | `xsv` | Unavailable |
| `qsv` | `qsv` | `qsv` | Unavailable |

Repository availability changes over time. Treat `--list` as authoritative;
the date-stamped status above explains the original failed `apt install`.

For simple viewing, the required `bsdextrautils` package provides `column`, and
the required `less` package supplies horizontal scrolling. No optional package
is needed for:

```sh
cut -f1-3,5 step-060.ram | column -t -s $'\t' | less -S
```

## Optional development packages

`--with-dev-tools` offers Debian-packaged repository checks and auxiliary
workflows: `shellcheck`, `shfmt`, `yamllint`, `nodejs`, `npm`, `ruby-mdl`,
`graphviz`, `pandoc`, `tmux`, and `yq`. Each is
candidate-checked before installation. Tools installed through language package
managers, such as `prettier`, `markdownlint-cli`, `golangci-lint`, and `go-grip`,
remain explicit follow-up steps in
[`INSTALL.md`](../../INSTALL.md).

## Verification

The installer finishes by printing versions for Go, Python, PostgreSQL,
SQLite, DuckDB, mdBook, and CodeQL (and MinIO when `--with-minio` is given).
Continue with the canonical
non-destructive preflight:

```sh
cd cga/system-tests
./run-system-02 preflight
```
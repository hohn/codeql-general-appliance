#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)
TOOLS_DIR=${TOOLS_DIR:-"$(dirname -- "${REPO_ROOT}")/single-machine-mrva-artifacts/tools"}
CODEQL_VERSION=${CODEQL_VERSION:-2.27.1}
GO_VERSION=1.25.12
DUCKDB_VERSION=1.5.5
MDBOOK_VERSION=0.5.4
MIN_GO_VERSION=${MIN_GO_VERSION:-1.25}
MIN_MDBOOK_VERSION=${MIN_MDBOOK_VERSION:-0.5}

required_packages=(
	bash
	bsdextrautils
	build-essential
	ca-certificates
	curl
	default-jre-headless
	devscripts
	dpkg-dev
	git
	gzip
	iproute2
	jq
	less
	lsof
	postgresql
	postgresql-client
	procps
	python3
	python3-pip
	python3-venv
	rsync
	sqlite3
	tar
	unzip
	util-linux
	xz-utils
	zip
	zstd
)

table_tool_specs=(
	"visidata|vd|interactive TSV viewer"
	"miller|mlr|record-oriented TSV transformer"
	"csvlens|csvlens|interactive delimited-text viewer"
	"tsv-utils|tsv-summarize|TSV filtering and statistics"
	"xsv|xsv|CSV/TSV command-line toolkit"
	"qsv|qsv|CSV/TSV command-line toolkit"
)

dev_tool_specs=(
	"shellcheck|shellcheck|shell lint"
	"shfmt|shfmt|shell formatting"
	"yamllint|yamllint|YAML lint"
	"nodejs|node|JavaScript runtime for Markdown checks"
	"npm|npm|prettier and markdownlint-cli installer"
	"ruby-mdl|mdl|Markdown lint"
	"graphviz|dot|dependency graph rendering"
	"pandoc|pandoc|legacy document conversion"
	"tmux|tmux|terminal session management"
	"yq|yq|legacy qldbtools metadata processing"
)

action=install
install_table_tools=0
install_dev_tools=0
with_minio=0

usage() {
	cat <<EOF
Usage: $(basename -- "$0") [options]

Install the Ubuntu 24.04 Noble dependencies for CGA, CGA preparation, and
standalone MRVA. Apt packages, pinned upstream tools, and PostgreSQL setup are
installed by default. Downloads are cached under:
  ${TOOLS_DIR}

Options:
  --list              List required and optional dependencies; install nothing.
  --with-table-tools  Install Ubuntu-packaged table tools when available.
  --with-dev-tools    Install Ubuntu-packaged lint and auxiliary tools.
  --with-minio        Download and link community MinIO.
  --with-optional     Enable all optional groups.
  --tools-dir DIR     Override the sibling artifact tools directory.
  -h, --help          Show this help text.

Environment:
  CODEQL_VERSION      CodeQL bundle version (default: ${CODEQL_VERSION}).
  MIN_GO_VERSION      Minimum accepted Go version (default: ${MIN_GO_VERSION}).
  MIN_MDBOOK_VERSION  Minimum accepted mdBook version (default: ${MIN_MDBOOK_VERSION}).
  TOOLS_DIR           Same override as --tools-dir.
EOF
}

log() {
	printf '\n==> %s\n' "$*"
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

run_as_root() {
	if [[ $(id -u) -eq 0 ]]; then
		"$@"
	elif [[ -r /proc/self/status ]] &&
		grep -q '^NoNewPrivs:[[:space:]]*1$' /proc/self/status; then
		die "root privileges are required, but NoNewPrivs prevents sudo; run this installer as root or from a shell that permits elevation"
	elif command -v sudo >/dev/null 2>&1; then
		sudo "$@"
	else
		die "root privileges are required; install sudo or run as root"
	fi
}

apt_candidate() {
	local package=$1 candidate
	candidate=$(LC_ALL=C apt-cache policy "${package}" 2>/dev/null |
		awk '/^[[:space:]]*Candidate:/ {print $2; exit}')
	if [[ -n ${candidate} && ${candidate} != "(none)" ]]; then
		printf '%s\n' "${candidate}"
		return 0
	fi
	return 1
}

package_status() {
	local package=$1
	if dpkg-query -W -f='${db:Status-Abbrev}' "${package}" 2>/dev/null |
		grep -q '^ii '; then
		printf 'installed'
	else
		printf 'not installed'
	fi
}

version_at_least() {
	local actual=$1 minimum=$2
	[[ $(printf '%s\n%s\n' "${minimum}" "${actual}" | sort -V | head -n 1) == "${minimum}" ]]
}

command_version_at_least() {
	local command=$1 minimum=$2 version
	command -v "${command}" >/dev/null 2>&1 || return 1
	case ${command} in
		go)
			version=$(go env GOVERSION 2>/dev/null)
			version=${version#go}
			;;
		mdbook) version=$(mdbook --version 2>/dev/null | awk '{print $2; exit}') ;;
		*) return 1 ;;
	esac
	[[ -n ${version} ]] && version_at_least "${version}" "${minimum}"
}

architecture() {
	case "$(dpkg --print-architecture 2>/dev/null || uname -m)" in
		amd64 | x86_64) printf 'amd64\n' ;;
		arm64 | aarch64) printf 'arm64\n' ;;
		*) die "unsupported architecture: $(uname -m)" ;;
	esac
}

download_verified() {
	local url=$1 destination=$2 expected=$3
	mkdir -p "$(dirname -- "${destination}")"
	if [[ ! -f ${destination} ]]; then
		curl -fL "${url}" -o "${destination}.partial"
		mv "${destination}.partial" "${destination}"
	fi
	printf '%s  %s\n' "${expected}" "${destination}" | sha256sum -c -
}

list_apt_packages() {
	local heading=$1
	shift
	local package candidate
	printf '\n%s\n' "${heading}"
	printf '%-24s %-20s %s\n' PACKAGE CANDIDATE STATUS
	for package in "$@"; do
		candidate=$(apt_candidate "${package}" || true)
		printf '%-24s %-20s %s\n' \
			"${package}" "${candidate:-unavailable}" "$(package_status "${package}")"
	done
}

list_optional_specs() {
	local heading=$1
	shift
	local spec package command purpose candidate
	printf '\n%s\n' "${heading}"
	printf '%-18s %-18s %-20s %s\n' PACKAGE COMMAND CANDIDATE PURPOSE
	for spec in "$@"; do
		IFS='|' read -r package command purpose <<<"${spec}"
		candidate=$(apt_candidate "${package}" || true)
		printf '%-18s %-18s %-20s %s\n' \
			"${package}" "${command}" "${candidate:-unavailable}" "${purpose}"
	done
}

list_dependencies() {
	local arch codeql_dir go_dir duckdb_path mdbook_path minio_path
	arch=$(architecture)
	codeql_dir="${TOOLS_DIR}/codeql-${CODEQL_VERSION}"
	go_dir="${TOOLS_DIR}/go-${GO_VERSION}-${arch}"
	duckdb_path="${TOOLS_DIR}/duckdb-${DUCKDB_VERSION}-${arch}/duckdb"
	mdbook_path="${TOOLS_DIR}/mdbook-${MDBOOK_VERSION}-${arch}/mdbook"
	minio_path="${TOOLS_DIR}/minio-${arch}/minio"

	printf 'Repository: %s\n' "${REPO_ROOT}"
	printf 'Artifact tools: %s\n' "${TOOLS_DIR}"
	list_apt_packages "Required Ubuntu packages" "${required_packages[@]}"
	printf '\nRequired upstream tools\n'
	printf '%-12s %-12s %s\n' TOOL VERSION STATUS
	printf '%-12s %-12s %s\n' Go "${GO_VERSION}" \
		"$([[ -x ${go_dir}/go/bin/go ]] && printf cached || { command_version_at_least go "${MIN_GO_VERSION}" && printf installed || printf missing; })"
	printf '%-12s %-12s %s\n' DuckDB "${DUCKDB_VERSION}" \
		"$([[ -x ${duckdb_path} ]] && printf cached || printf missing)"
	printf '%-12s %-12s %s\n' mdBook "${MDBOOK_VERSION}" \
		"$([[ -x ${mdbook_path} ]] && printf cached || { command_version_at_least mdbook "${MIN_MDBOOK_VERSION}" && printf installed || printf missing; })"
	printf '%-12s %-12s %s\n' CodeQL "${CODEQL_VERSION}" \
		"$([[ -x ${codeql_dir}/codeql/codeql && -d ${codeql_dir}/codeql/qlpacks/codeql/cpp-queries ]] && printf cached || printf missing)"
	printf '\nOptional upstream tools (installed only with --with-minio)\n'
	printf '%-12s %-12s %s\n' TOOL VERSION STATUS
	printf '%-12s %-12s %s\n' MinIO current \
		"$([[ -x ${minio_path} ]] && printf cached || printf absent)"
	list_optional_specs "Optional table tools" "${table_tool_specs[@]}"
	list_optional_specs "Optional development tools" "${dev_tool_specs[@]}"
}

available_optional_packages() {
	local spec package command purpose
	for spec in "$@"; do
		IFS='|' read -r package command purpose <<<"${spec}"
		if apt_candidate "${package}" >/dev/null; then
			printf '%s\n' "${package}"
		else
			printf 'Skipping optional package unavailable from configured Ubuntu repositories: %s\n' \
				"${package}" >&2
		fi
	done
}

install_apt_dependencies() {
	local missing=() optional=() package
	for package in "${required_packages[@]}"; do
		apt_candidate "${package}" >/dev/null || missing+=("${package}")
	done
	((${#missing[@]} == 0)) ||
		die "required Ubuntu packages have no apt candidate: ${missing[*]}"

	local packages=("${required_packages[@]}")
	if [[ ${install_table_tools} -eq 1 ]]; then
		mapfile -t optional < <(available_optional_packages "${table_tool_specs[@]}")
		packages+=("${optional[@]}")
	fi
	if [[ ${install_dev_tools} -eq 1 ]]; then
		mapfile -t optional < <(available_optional_packages "${dev_tool_specs[@]}")
		packages+=("${optional[@]}")
	fi

	log "installing Ubuntu packages"
	run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y \
		--no-install-recommends "${packages[@]}"
}

install_go() {
	local arch checksum archive go_dir partial
	if command_version_at_least go "${MIN_GO_VERSION}"; then
		log "using installed $(go version)"
		return
	fi
	arch=$(architecture)
	case ${arch} in
		amd64) checksum=234828b7a89e0e303d2556310ee549fbcf253d28de937bac3da13d6294262ac1 ;;
		arm64) checksum=8b5884aef89600aef5b0b051fb971f11f49bb996521e911f30f02a66884f7bd2 ;;
	esac
	archive="${TOOLS_DIR}/downloads/go${GO_VERSION}.linux-${arch}.tar.gz"
	go_dir="${TOOLS_DIR}/go-${GO_VERSION}-${arch}"
	if [[ ! -x ${go_dir}/go/bin/go ]]; then
		download_verified "https://go.dev/dl/go${GO_VERSION}.linux-${arch}.tar.gz" \
			"${archive}" "${checksum}"
		[[ ! -e ${go_dir} ]] || die "incomplete Go directory exists: ${go_dir}"
		partial="${go_dir}.partial.$$"
		mkdir -p "${partial}"
		tar -xzf "${archive}" -C "${partial}"
		[[ -x ${partial}/go/bin/go ]] || die "Go archive layout is unexpected"
		mv "${partial}" "${go_dir}"
	fi
	run_as_root mkdir -p /usr/local/bin
	run_as_root ln -sfn "${go_dir}/go/bin/go" /usr/local/bin/go
	run_as_root ln -sfn "${go_dir}/go/bin/gofmt" /usr/local/bin/gofmt
}

install_duckdb() {
	local arch checksum archive duckdb_dir
	arch=$(architecture)
	case ${arch} in
		amd64) checksum=c61f21485e6e41d3a0c28ce9904ea18346309cf427b4cf9479bc3564348dc885 ;;
		arm64) checksum=50c719e603a4e599d435e5321542458edc1cfc5f7eed65979fe9bc5ae4e3ba23 ;;
	esac
	archive="${TOOLS_DIR}/downloads/duckdb_cli-linux-${arch}-${DUCKDB_VERSION}.gz"
	duckdb_dir="${TOOLS_DIR}/duckdb-${DUCKDB_VERSION}-${arch}"
	if [[ ! -x ${duckdb_dir}/duckdb ]]; then
		download_verified \
			"https://github.com/duckdb/duckdb/releases/download/v${DUCKDB_VERSION}/duckdb_cli-linux-${arch}.gz" \
			"${archive}" "${checksum}"
		mkdir -p "${duckdb_dir}"
		gzip -dc "${archive}" >"${duckdb_dir}/duckdb.partial"
		chmod 0755 "${duckdb_dir}/duckdb.partial"
		mv "${duckdb_dir}/duckdb.partial" "${duckdb_dir}/duckdb"
	fi
	run_as_root mkdir -p /usr/local/bin
	run_as_root ln -sfn "${duckdb_dir}/duckdb" /usr/local/bin/duckdb
}

install_mdbook() {
	local arch target checksum archive mdbook_dir partial
	if command_version_at_least mdbook "${MIN_MDBOOK_VERSION}"; then
		log "using installed $(mdbook --version)"
		return
	fi
	arch=$(architecture)
	case ${arch} in
		amd64)
			target=x86_64-unknown-linux-gnu
			checksum=3f28de05dafca9d0f2eab99c662116b0e37b89b1d96a08f8f430b9eeae958cd7
			;;
		arm64)
			target=aarch64-unknown-linux-musl
			checksum=753e5c5c363ee8a56972344dcf91466f005a51db84a7aeffe427ae3ef83d6d44
			;;
	esac
	archive="${TOOLS_DIR}/downloads/mdbook-v${MDBOOK_VERSION}-${target}.tar.gz"
	mdbook_dir="${TOOLS_DIR}/mdbook-${MDBOOK_VERSION}-${arch}"
	if [[ ! -x ${mdbook_dir}/mdbook ]]; then
		download_verified \
			"https://github.com/rust-lang/mdBook/releases/download/v${MDBOOK_VERSION}/mdbook-v${MDBOOK_VERSION}-${target}.tar.gz" \
			"${archive}" "${checksum}"
		partial="${mdbook_dir}.partial.$$"
		mkdir -p "${partial}"
		tar -xzf "${archive}" -C "${partial}"
		[[ -x ${partial}/mdbook ]] || die "mdBook archive layout is unexpected"
		mv "${partial}" "${mdbook_dir}"
	fi
	run_as_root mkdir -p /usr/local/bin
	run_as_root ln -sfn "${mdbook_dir}/mdbook" /usr/local/bin/mdbook
}

install_codeql() {
	local version tag asset codeql_dir archive checksum partial expected profile arch
	version=${CODEQL_VERSION#codeql-bundle-}
	version=${version#v}
	[[ ${version} =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
		die "CODEQL_VERSION must have the form 2.27.1, v2.27.1, or codeql-bundle-v2.27.1"
	tag="codeql-bundle-v${version}"
	arch=$(architecture)
	case ${arch} in
		amd64) asset=codeql-bundle-linux64.tar.gz ;;
		arm64) asset=codeql-bundle-linux-arm64.tar.gz ;;
	esac
	codeql_dir="${TOOLS_DIR}/codeql-${version}"
	archive="${TOOLS_DIR}/downloads/${tag}-${asset}"
	checksum="${archive}.checksum.txt"

	if [[ -x ${codeql_dir}/codeql/codeql && -d ${codeql_dir}/codeql/qlpacks/codeql/cpp-queries ]]; then
		log "using cached CodeQL ${version} at ${codeql_dir}"
	else
		[[ ! -e ${codeql_dir} ]] || die "incomplete CodeQL directory exists: ${codeql_dir}"
		mkdir -p "${TOOLS_DIR}/downloads"
		if [[ ! -f ${archive} ]]; then
			curl -fL "https://github.com/github/codeql-action/releases/download/${tag}/${asset}" \
				-o "${archive}.partial"
			mv "${archive}.partial" "${archive}"
		fi
		if [[ ! -f ${checksum} ]]; then
			curl -fL "https://github.com/github/codeql-action/releases/download/${tag}/${asset}.checksum.txt" \
				-o "${checksum}.partial"
			mv "${checksum}.partial" "${checksum}"
		fi
		expected=$(awk '{print $1; exit}' "${checksum}")
		[[ -n ${expected} ]] || die "empty CodeQL checksum: ${checksum}"
		printf '%s  %s\n' "${expected}" "${archive}" | sha256sum -c -
		partial="${codeql_dir}.partial.$$"
		mkdir -p "${partial}"
		tar -xzf "${archive}" -C "${partial}"
		[[ -x ${partial}/codeql/codeql ]] || die "CodeQL archive layout is unexpected"
		mv "${partial}" "${codeql_dir}"
	fi

	run_as_root mkdir -p /usr/local/bin
	run_as_root ln -sfn "${codeql_dir}/codeql/codeql" /usr/local/bin/codeql
	profile=$(mktemp)
	{
		printf '%s\n' 'export CODEQL_JAVA_HOME=${CODEQL_JAVA_HOME:-/usr}'
		printf 'case ":${PATH}:" in\n'
		printf '  *":%s:"*) ;;\n' "${codeql_dir}/codeql"
		printf '  *) export PATH="%s:${PATH}" ;;\n' "${codeql_dir}/codeql"
		printf 'esac\n'
	} >"${profile}"
	run_as_root install -m 0644 "${profile}" /etc/profile.d/mrva-codeql.sh
	rm -f "${profile}"
	CODEQL_JAVA_HOME=/usr "${codeql_dir}/codeql/codeql" version --format=terse
}

install_minio() {
	local arch minio_dir minio_path
	arch=$(architecture)
	minio_dir="${TOOLS_DIR}/minio-${arch}"
	minio_path="${minio_dir}/minio"
	if [[ ! -x ${minio_path} ]]; then
		mkdir -p "${minio_dir}"
		curl -fL "https://dl.min.io/server/minio/release/linux-${arch}/minio" \
			-o "${minio_path}.partial"
		chmod 0755 "${minio_path}.partial"
		mv "${minio_path}.partial" "${minio_path}"
	fi
	run_as_root mkdir -p /usr/local/bin
	run_as_root ln -sfn "${minio_path}" /usr/local/bin/minio
}

start_postgresql() {
	log "enabling PostgreSQL"
	if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
		run_as_root systemctl enable --now postgresql
	else
		run_as_root service postgresql start
	fi
	pg_isready -h localhost -p 5432
}

while (($#)); do
	case $1 in
		--list) action=list ;;
		--with-table-tools) install_table_tools=1 ;;
		--with-dev-tools) install_dev_tools=1 ;;
		--with-minio) with_minio=1 ;;
		--with-optional)
			install_table_tools=1
			install_dev_tools=1
			with_minio=1
			;;
		--tools-dir)
			shift
			(($#)) || die "--tools-dir requires a path"
			TOOLS_DIR=$1
			;;
		-h | --help)
			usage
			exit 0
			;;
		*)
			usage >&2
			die "unknown option: $1"
			;;
	esac
	shift
done

[[ -r /etc/os-release ]] || die "cannot identify the operating system"
# shellcheck source=/dev/null
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_CODENAME:-} == noble ]] ||
	die "expected Ubuntu Noble, found ${PRETTY_NAME:-unknown}"
command -v apt-get >/dev/null 2>&1 || die "apt-get is required"
command -v apt-cache >/dev/null 2>&1 || die "apt-cache is required"
TOOLS_DIR=$(realpath -m -- "${TOOLS_DIR}")
[[ ${TOOLS_DIR} != / ]] || die "TOOLS_DIR cannot be /"

if [[ ${action} == list ]]; then
	list_dependencies
	exit 0
fi

log "refreshing Ubuntu package metadata"
run_as_root apt-get update
install_apt_dependencies
install_go
install_duckdb
install_mdbook
install_codeql
((with_minio)) && install_minio
start_postgresql

log "installed required versions"
go version
python3 --version
psql --version
sqlite3 --version
duckdb --version
mdbook --version
CODEQL_JAVA_HOME=/usr codeql version --format=terse
((with_minio)) && minio --version

log "dependency installation complete"
if [[ ${install_table_tools} -eq 0 || ${install_dev_tools} -eq 0 ]]; then
	printf '%s\n' "Run '$0 --list' to inspect optional tools."
fi

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)
TOOLS_DIR=${TOOLS_DIR:-"$(dirname -- "${REPO_ROOT}")/single-machine-mrva-artifacts/tools"}
CODEQL_VERSION=${CODEQL_VERSION:-2.27.1}
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
	duckdb
	git
	golang-go
	iproute2
	jq
	less
	lsof
	mdbook
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

Install the Debian sid dependencies for CGA, CGA preparation, and standalone MRVA.
Required apt packages, CodeQL, and PostgreSQL setup are installed by default.
MinIO is optional (local runs use filesystem storage; large deployments use a
provided S3 service). Upstream downloads are cached under:
  ${TOOLS_DIR}

Options:
  --list              List required and optional dependencies; install nothing.
  --with-table-tools  Install Debian-packaged table tools when available.
  --with-dev-tools    Install Debian-packaged lint and auxiliary tools.
  --with-minio        Download and link community MinIO (S3-compatible storage).
  --with-optional     Enable all optional groups (table tools, dev tools, MinIO).
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
	local package=$1
	local candidate
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

normalized_codeql_version() {
	local version=${CODEQL_VERSION#codeql-bundle-}
	version=${version#v}
	[[ ${version} =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
		die "CODEQL_VERSION must have the form 2.27.1, v2.27.1, or codeql-bundle-v2.27.1"
	printf '%s\n' "${version}"
}

list_dependencies() {
	local codeql_version codeql_dir minio_arch minio_path
	codeql_version=$(normalized_codeql_version)
	codeql_dir="${TOOLS_DIR}/codeql-${codeql_version}"
	case "$(dpkg --print-architecture 2>/dev/null || uname -m)" in
		amd64 | x86_64) minio_arch=amd64 ;;
		arm64 | aarch64) minio_arch=arm64 ;;
		*) minio_arch=unsupported ;;
	esac
	minio_path="${TOOLS_DIR}/minio-${minio_arch}/minio"

	printf 'Repository: %s\n' "${REPO_ROOT}"
	printf 'Artifact tools: %s\n' "${TOOLS_DIR}"
	list_apt_packages "Required Debian packages" "${required_packages[@]}"
	printf '\nRequired cached upstream tools\n'
	printf '%-12s %-12s %s\n' TOOL VERSION STATUS
	printf '%-12s %-12s %s\n' CodeQL "${codeql_version}" \
		"$([[ -x ${codeql_dir}/codeql/codeql && -d ${codeql_dir}/codeql/qlpacks/codeql/cpp-queries ]] && printf present || printf missing)"
	printf '\nOptional cached upstream tools (installed only with --with-minio)\n'
	printf '%-12s %-12s %s\n' TOOL VERSION STATUS
	printf '%-12s %-12s %s\n' MinIO current \
		"$([[ -x ${minio_path} ]] && printf present || printf absent)"
	list_optional_specs "Optional table tools (installed only with --with-table-tools)" \
		"${table_tool_specs[@]}"
	list_optional_specs "Optional development tools (installed only with --with-dev-tools)" \
		"${dev_tool_specs[@]}"
}

available_optional_packages() {
	local spec package command purpose
	for spec in "$@"; do
		IFS='|' read -r package command purpose <<<"${spec}"
		if apt_candidate "${package}" >/dev/null; then
			printf '%s\n' "${package}"
		else
			printf 'Skipping optional package unavailable from configured Debian repositories: %s\n' \
				"${package}" >&2
		fi
	done
}

install_apt_dependencies() {
	local missing=()
	local optional=()
	local package
	for package in "${required_packages[@]}"; do
		apt_candidate "${package}" >/dev/null || missing+=("${package}")
	done
	if ((${#missing[@]})); then
		die "required Debian packages have no apt candidate: ${missing[*]}"
	fi

	local packages=("${required_packages[@]}")
	if [[ ${install_table_tools} -eq 1 ]]; then
		mapfile -t optional < <(available_optional_packages "${table_tool_specs[@]}")
		packages+=("${optional[@]}")
	fi
	if [[ ${install_dev_tools} -eq 1 ]]; then
		mapfile -t optional < <(available_optional_packages "${dev_tool_specs[@]}")
		packages+=("${optional[@]}")
	fi

	log "installing Debian packages"
	run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y \
		--no-install-recommends "${packages[@]}"
}

version_at_least() {
	local actual=$1 minimum=$2
	[[ $(printf '%s\n%s\n' "${minimum}" "${actual}" | sort -V | head -n 1) == "${minimum}" ]]
}

verify_go() {
	local version
	version=$(go env GOVERSION 2>/dev/null || true)
	version=${version#go}
	[[ -n ${version} ]] || die "Go was not installed"
	version_at_least "${version}" "${MIN_GO_VERSION}" ||
		die "Go ${MIN_GO_VERSION} or newer is required; apt installed ${version}"
}

verify_mdbook() {
	local version
	version=$(mdbook --version 2>/dev/null | awk '{print $2; exit}')
	[[ -n ${version} ]] || die "mdBook was not installed"
	version_at_least "${version}" "${MIN_MDBOOK_VERSION}" ||
		die "mdBook ${MIN_MDBOOK_VERSION} or newer is required; apt installed ${version}"
}

install_codeql() {
	local version tag asset codeql_dir archive checksum partial expected arch
	version=$(normalized_codeql_version)
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
		[[ ! -e ${codeql_dir} ]] ||
			die "incomplete CodeQL directory exists: ${codeql_dir}"
		mkdir -p "${TOOLS_DIR}/downloads"
		if [[ ! -f ${archive} ]]; then
			log "downloading CodeQL ${version} once into the artifact cache"
			curl -fL \
				"https://github.com/github/codeql-action/releases/download/${tag}/${asset}" \
				-o "${archive}.partial"
			mv "${archive}.partial" "${archive}"
		fi
		if [[ ! -f ${checksum} ]]; then
			curl -fL \
				"https://github.com/github/codeql-action/releases/download/${tag}/${asset}.checksum.txt" \
				-o "${checksum}.partial"
			mv "${checksum}.partial" "${checksum}"
		fi
		expected=$(awk '{print $1; exit}' "${checksum}")
		[[ -n ${expected} ]] || die "empty CodeQL checksum: ${checksum}"
		printf '%s  %s\n' "${expected}" "${archive}" | sha256sum -c -

		partial="${codeql_dir}.partial.$$"
		rm -rf "${partial}"
		mkdir -p "${partial}"
		tar -xzf "${archive}" -C "${partial}"
		[[ -x ${partial}/codeql/codeql ]] || die "CodeQL archive layout is unexpected"
		mv "${partial}" "${codeql_dir}"
	fi

	run_as_root mkdir -p /usr/local/bin
	run_as_root ln -sfn "${codeql_dir}/codeql/codeql" /usr/local/bin/codeql
	local profile
	profile=$(mktemp)
	# Set the native Java home and put the extracted codeql tree on PATH (idempotently).
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
	local architecture minio_dir minio_path url
	case "$(dpkg --print-architecture)" in
		amd64) architecture=amd64 ;;
		arm64) architecture=arm64 ;;
		*) die "unsupported MinIO architecture: $(dpkg --print-architecture)" ;;
	esac
	minio_dir="${TOOLS_DIR}/minio-${architecture}"
	minio_path="${minio_dir}/minio"
	url="https://dl.min.io/server/minio/release/linux-${architecture}/minio"
	if [[ -x ${minio_path} ]]; then
		log "using cached community MinIO at ${minio_path}"
	else
		mkdir -p "${minio_dir}"
		log "downloading community MinIO once into the artifact cache"
		curl -fL "${url}" -o "${minio_path}.partial"
		chmod 0755 "${minio_path}.partial"
		mv "${minio_path}.partial" "${minio_path}"
	fi
	run_as_root mkdir -p /usr/local/bin
	run_as_root ln -sfn "${minio_path}" /usr/local/bin/minio
	"${minio_path}" --version
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
[[ ${ID:-} == debian ]] || die "expected Debian, found ${ID:-unknown}"
command -v apt-get >/dev/null 2>&1 || die "apt-get is required"
command -v apt-cache >/dev/null 2>&1 || die "apt-cache is required"
TOOLS_DIR=$(realpath -m -- "${TOOLS_DIR}")
[[ ${TOOLS_DIR} != / ]] || die "TOOLS_DIR cannot be /"

if [[ ${action} == list ]]; then
	list_dependencies
	exit 0
fi

log "refreshing Debian package metadata"
run_as_root apt-get update
install_apt_dependencies
verify_go
verify_mdbook
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
minio --version

log "dependency installation complete"
if [[ ${install_table_tools} -eq 0 || ${install_dev_tools} -eq 0 ]]; then
	printf '%s\n' "Run '$0 --list' to inspect optional tools."
fi
#!/bin/sh
set -eu

CODEQL_VERSION="${CODEQL_VERSION:-v2.27.1}"
CODEQL_ROOT="${CODEQL_ROOT:-/opt}"
CODEQL_DIR="${CODEQL_DIR:-${CODEQL_ROOT}/codeql}"
CODEQL_CLI_PATH="${CODEQL_CLI_PATH:-${CODEQL_DIR}/codeql}"
JAVA_PACKAGE="${JAVA_PACKAGE:-openjdk21-jre}"
XBPS_REPOSITORY="${XBPS_REPOSITORY:-}"
FULL_UPGRADE="${FULL_UPGRADE:-0}"
FORCE_CODEQL_INSTALL="${FORCE_CODEQL_INSTALL:-0}"

log() {
	printf '%s\n' "==> $*"
}

die() {
	printf '%s\n' "error: $*" >&2
	exit 1
}

need_cmd() {
	command -v "$1" > /dev/null 2>&1 || die "missing required command: $1"
}

has_codeql_bundle_queries() {
	[ -d "${CODEQL_DIR}/qlpacks/codeql/javascript-queries" ] || return 1
	find "${CODEQL_DIR}/qlpacks/codeql/javascript-queries" \
		-name javascript-code-scanning.qls -type f -print -quit |
		grep -q .
}

uid="$(id -u)"
if [ "${uid}" -ne 0 ]; then
	if command -v sudo > /dev/null 2>&1; then
		exec sudo -E /bin/sh "$0" "$@"
	fi
	die "run as root, or install sudo"
fi

[ -r /etc/os-release ] || die "cannot identify guest OS"
# shellcheck source=/dev/null
. /etc/os-release
[ "${ID:-}" = "void" ] || die "expected Void Linux, found ID=${ID:-unknown}"

need_cmd xbps-install

if [ -z "${XBPS_REPOSITORY}" ]; then
	case "$(uname -m)" in
		aarch64 | arm64)
			XBPS_REPOSITORY="https://repo-default.voidlinux.org/current/aarch64"
			;;
		*)
			XBPS_REPOSITORY="https://repo-default.voidlinux.org/current"
			;;
	esac
fi

log "configuring Void repository"
mkdir -p /etc/xbps.d
cat > /etc/xbps.d/00-repository-main.conf << EOF
repository=${XBPS_REPOSITORY}
EOF

if [ "${FULL_UPGRADE}" = "1" ]; then
	log "updating all installed packages"
	xbps-install -Syu
else
	log "syncing package metadata and updating package manager"
	xbps-install -Sy xbps
fi

log "installing CodeQL runtime dependencies"
xbps-install -Sy ca-certificates curl git tar xz bash "${JAVA_PACKAGE}"

if command -v update-ca-certificates > /dev/null 2>&1; then
	update-ca-certificates
fi

need_cmd curl
need_cmd tar
need_cmd sha256sum

[ -n "${CODEQL_DIR}" ] || die "CODEQL_DIR cannot be empty"
[ "${CODEQL_DIR}" != "/" ] || die "CODEQL_DIR cannot be /"
[ -n "${CODEQL_ROOT}" ] || die "CODEQL_ROOT cannot be empty"

case "$(uname -m)" in
	aarch64 | arm64) CODEQL_ASSET="codeql-bundle-linux-arm64.tar.gz" ;;
	x86_64 | amd64) CODEQL_ASSET="codeql-bundle-linux64.tar.gz" ;;
	*) die "unsupported CodeQL architecture: $(uname -m)" ;;
esac

if [ "${CODEQL_VERSION}" = "latest" ]; then
	tag="$(curl -fsL -o /dev/null -w '%{url_effective}' https://github.com/github/codeql-action/releases/latest | sed 's|.*/||')"
else
	case "${CODEQL_VERSION}" in
		codeql-bundle-*) TAG="${CODEQL_VERSION}" ;;
		v*) TAG="codeql-bundle-${CODEQL_VERSION}" ;;
		*) TAG="codeql-bundle-v${CODEQL_VERSION}" ;;
	esac
	tag="${TAG}"
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT INT TERM

log "resolving CodeQL release"
[ -n "${tag}" ] || die "could not resolve CodeQL release tag"
archive_url="https://github.com/github/codeql-action/releases/download/${tag}/${CODEQL_ASSET}"
sum_url="${archive_url}.checksum.txt"

installed_bundle=0
if [ "${FORCE_CODEQL_INSTALL}" != "1" ] && [ -x "${CODEQL_CLI_PATH}" ]; then
	set +e
	has_codeql_bundle_queries
	bundle_status=$?
	set -e
	if [ "${bundle_status}" -eq 0 ]; then
		installed_bundle=1
	fi
fi

if [ "${installed_bundle}" -eq 1 ]; then
	log "CodeQL bundle is already installed at ${CODEQL_DIR}"
else
	log "downloading CodeQL bundle ${tag}"
	curl -fL "${archive_url}" -o "${tmpdir}/${CODEQL_ASSET}"
	curl -fL "${sum_url}" -o "${tmpdir}/${CODEQL_ASSET}.checksum.txt"

	log "verifying CodeQL archive checksum"
	(
		cd "${tmpdir}"
		expected="$(awk '{print $1; exit}' "${CODEQL_ASSET}.checksum.txt")"
		[ -n "${expected}" ] || die "empty checksum file"
		printf '%s  %s\n' "${expected}" "${CODEQL_ASSET}" | sha256sum -c -
	)

	log "installing CodeQL into ${CODEQL_DIR}"
	rm -rf "${CODEQL_DIR}"
	mkdir -p "${CODEQL_ROOT}"
	tar -xzf "${tmpdir}/${CODEQL_ASSET}" -C "${CODEQL_ROOT}"
fi

[ -x "${CODEQL_CLI_PATH}" ] || die "CodeQL executable not found at ${CODEQL_CLI_PATH}"
set +e
has_codeql_bundle_queries
bundle_status=$?
set -e
[ "${bundle_status}" -eq 0 ] || die "CodeQL bundle JavaScript query suite not found under ${CODEQL_DIR}/qlpacks"

log "normalizing CodeQL bundle permissions"
chmod -R a+rX "${CODEQL_DIR}"

log "publishing CodeQL environment"
cat > /etc/profile.d/codeql.sh << EOF
export CODEQL_JAVA_HOME=\${CODEQL_JAVA_HOME:-/usr}
case ":\$PATH:" in
	*:${CODEQL_DIR}:*) ;;
	*) export PATH="${CODEQL_DIR}:\$PATH" ;;
esac
EOF

mkdir -p /usr/local/bin
ln -sfn "${CODEQL_CLI_PATH}" /usr/local/bin/codeql

log "installed versions"
java -version
CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME:-/usr}" "${CODEQL_CLI_PATH}" version

log "provisioning complete"

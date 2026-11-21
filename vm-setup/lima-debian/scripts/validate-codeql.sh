#!/bin/sh
set -eu

RUN_SMOKE=1
WORKDIR="${WORKDIR:-/tmp/codeql-smoke}"
CODEQL_CLI_PATH="${CODEQL_CLI_PATH:-/opt/codeql/codeql}"
PATH=/opt/codeql:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME:-/usr}"

usage() {
	cat << 'EOF'
Usage: validate-codeql.sh [--versions-only] [--smoke]

Validates the Debian CodeQL appliance baseline:
  - java -version
  - codeql version
  - tiny JavaScript database create/analyze smoke test

Environment:
  CODEQL_CLI_PATH=/path/to/codeql  default: /opt/codeql/codeql
  CODEQL_JAVA_HOME=/path/to/java   default: /usr
  WORKDIR=/tmp/codeql-smoke        default: /tmp/codeql-smoke
EOF
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--versions-only)
			RUN_SMOKE=0
			;;
		--smoke)
			RUN_SMOKE=1
			;;
		-h | --help)
			usage
			exit 0
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
	shift
done

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

need_cmd java
need_cmd "${CODEQL_CLI_PATH}"

log "checking Java"
java -version

log "checking CodeQL"
"${CODEQL_CLI_PATH}" version

if [ "${RUN_SMOKE}" -eq 0 ]; then
	log "skipping smoke test"
	exit 0
fi

need_cmd mkdir
need_cmd rm

SRC="${WORKDIR}/src"
DB="${WORKDIR}/db"
OUT="${WORKDIR}/results.sarif"

log "preparing tiny JavaScript repository in ${SRC}"
rm -rf "${WORKDIR}"
mkdir -p "${SRC}"

cat > "${SRC}/package.json" << 'EOF'
{
  "name": "codeql-smoke",
  "version": "1.0.0",
  "private": true,
  "type": "commonjs"
}
EOF

cat > "${SRC}/index.js" << 'EOF'
function greet(name) {
  return `hello ${name}`;
}

console.log(greet(process.argv[2] || "debian"));
EOF

log "creating CodeQL database"
"${CODEQL_CLI_PATH}" database create "${DB}" \
	--language=javascript \
	--source-root="${SRC}" \
	--overwrite

log "analyzing CodeQL database"
"${CODEQL_CLI_PATH}" database analyze "${DB}" \
	codeql/javascript-queries:codeql-suites/javascript-code-scanning.qls \
	--format=sarif-latest \
	--output="${OUT}"

[ -s "${OUT}" ] || die "analysis did not write SARIF output"

log "smoke test passed; SARIF output: ${OUT}"

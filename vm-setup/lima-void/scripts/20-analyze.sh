#!/usr/bin/env bash

set -euo pipefail

CODEQL_CLI_PATH=${CODEQL_CLI_PATH:-/opt/codeql/codeql}
PATH=/opt/codeql:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ARM compatibility (harmless on amd64)
export CODEQL_JAVA_HOME=${CODEQL_JAVA_HOME:-/usr}

ZIP_ROOT=${ZIP_ROOT:-/mnt/common/tank/qldbs-bmn/zips}
TMP_ROOT=${TMP_ROOT:-/mnt/common/tmp}
SARIF_ROOT=${SARIF_ROOT:-/mnt/common/tank/bmn-dba-2/bmn-dba-2-sarifs}
THREADS=${THREADS:-4}
RAM_MB=${RAM_MB:-120000}
ANALYZE_TIMEOUT_SECS=${ANALYZE_TIMEOUT_SECS:-3600}

dbdir=""

usage() {
	cat << 'EOF'
Usage: 20-analyze.sh [zip-list-file ...]

Analyze CodeQL database bundles and write SARIF output.

Input sources:
  - one or more list files passed on the command line, one zip path per line
  - stdin, when data is piped or redirected in
  - otherwise all *.zip files under $ZIP_ROOT

Environment variables:
  CODEQL_CLI_PATH       CodeQL executable path. Default: /opt/codeql/codeql
  ZIP_ROOT              Directory containing .zip database bundles
  TMP_ROOT              Temporary extraction root. Default: /mnt/common/tmp
  SARIF_ROOT            Output directory for SARIF files
  THREADS               codeql database analyze -j value. Default: 4
  RAM_MB                codeql database analyze --ram value. Default: 120000
  ANALYZE_TIMEOUT_SECS  Timeout for each analysis. Default: 3600
EOF
}

timestamp() {
	date '+%Y-%m-%d %H:%M:%S'
}

ts_field() {
	date '+%Y-%m-%dT%H:%M:%S'
}

log_line() {
	local tag=$1
	shift
	printf '[%s] [%s] %s\n' "$(timestamp)" "$tag" "$*"
}

timestamp_stream() {
	local label=$1
	while IFS= read -r line || [[ -n "$line" ]]; do
		printf '[%s] [%s] %s\n' "$(timestamp)" "$label" "$line"
	done
}

cleanup() {
	if [[ -n "${dbdir:-}" && -d "$dbdir" ]]; then
		rm -rf "$dbdir"
	fi
}

sanitize_name() {
	local raw=$1
	raw=${raw//\//_}
	raw=${raw// /_}
	printf '%s\n' "$raw"
}

analyze_one() {
	local zipfile=$1
	local zip_path base safe_base sarif actual_dbdir analyze_status start_ts

	if [[ "$zipfile" != /* ]]; then
		zip_path="${ZIP_ROOT}/${zipfile}"
	else
		zip_path="$zipfile"
	fi

	if [[ ! -e "$zip_path" ]]; then
		log_line fail "$zipfile -> missing zip file"
		return 1
	fi

	base=$(basename "$zip_path" .zip)
	safe_base=$(sanitize_name "$base")
	dbdir="${TMP_ROOT}/codeql-db-${safe_base}"
	sarif="${SARIF_ROOT}/${base}.sarif"

	if [[ -s "$sarif" ]]; then
		log_line skip "$base -> already analyzed"
		return 0
	fi

	log_line extract "$zip_path -> $dbdir"
	rm -rf "$dbdir"
	if ! unzip -q "$zip_path" -d "$dbdir"; then
		log_line fail "$base -> unzip failed"
		rm -rf "$dbdir"
		dbdir=""
		return 1
	fi

	actual_dbdir=$(find "$dbdir" -name codeql-database.yml -print -quit 2> /dev/null || true)
	if [[ -z "$actual_dbdir" ]]; then
		log_line fail "$base -> no CodeQL database found"
		rm -rf "$dbdir"
		dbdir=""
		return 1
	fi
	actual_dbdir=$(dirname "$actual_dbdir")

	start_ts=$(ts_field)
	log_line analyze "$base start_ts=${start_ts} db=${actual_dbdir} sarif=${sarif}"

	if timeout --kill-after=30s "${ANALYZE_TIMEOUT_SECS}s" \
		"$CODEQL_CLI_PATH" database analyze \
		--format=sarif-latest \
		--rerun \
		"-j${THREADS}" \
		--ram="$RAM_MB" \
		--output "$sarif" \
		-- "$actual_dbdir" cpp-security-and-quality.qls \
		> >(timestamp_stream analyze-stdout) \
		2> >(timestamp_stream analyze-stderr >&2); then
		log_line sarif "$base -> $sarif"
		rm -rf "$dbdir"
		dbdir=""
		return 0
	else
		analyze_status=$?
		rm -f "$sarif"

		if [[ $analyze_status -eq 124 || $analyze_status -eq 137 ]]; then
			log_line timeout "$base -> codeql database analyze exceeded ${ANALYZE_TIMEOUT_SECS}s"
		else
			log_line fail "$base -> codeql database analyze exited with status ${analyze_status}"
		fi

		rm -rf "$dbdir"
		dbdir=""
		return 1
	fi
}

process_stream() {
	local failures=0
	local zipfile

	while IFS= read -r zipfile || [[ -n "$zipfile" ]]; do
		[[ -z "$zipfile" ]] && continue
		[[ ${zipfile:0:1} == "#" ]] && continue
		if ! analyze_one "$zipfile"; then
			((failures += 1))
		fi
	done

	return "$failures"
}

main() {
	local list_file
	local failures=0

	if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
		usage
		exit 0
	fi

	mkdir -p "$SARIF_ROOT" "$TMP_ROOT"
	trap cleanup EXIT INT TERM

	if (($# > 0)); then
		for list_file in "$@"; do
			log_line list "$list_file"
			if process_stream < "$list_file"; then
				:
			else
				((failures += $?))
			fi
		done
	elif [[ ! -t 0 ]]; then
		log_line list stdin
		if process_stream; then
			:
		else
			((failures += $?))
		fi
	else
		if find "$ZIP_ROOT" -maxdepth 1 -type f -name '*.zip' -printf '%f\n' | sort | process_stream; then
			:
		else
			((failures += $?))
		fi
	fi

	if ((failures > 0)); then
		printf 'Completed with %d failures.\n' "$failures" >&2
		exit 1
	fi
}

main "$@"

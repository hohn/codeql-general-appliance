#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
INSTANCE=${INSTANCE:-void-codeql-16g-installed}
REMOTE_USER=${REMOTE_USER:-}
REMOTE_DIR=${REMOTE_DIR:-}
SSH_PASSWORD=${SSH_PASSWORD:-${SSHPASS:-}}

usage() {
	cat << 'EOF'
Usage: scripts/sync-to-void.sh [options]

Copy this repository from the host into a running Void Lima VM.

Options:
  -h, --help          Show this help text.
  -i, --instance NAME Lima instance name. Default: void-codeql-16g-installed.
  -u, --user USER     SSH user. Default: Lima user from ~/.lima/INSTANCE/ssh.config.
                      Use --user anon for the stock live ISO password login.
  -d, --dest DIR      Destination directory in the VM. Default: ~/void-runner.
  -p, --port PORT     SSH forwarded port. Default: read from ~/.lima/INSTANCE/ssh.config.

Environment:
  INSTANCE            Same as --instance.
  REMOTE_USER         Same as --user.
  REMOTE_DIR          Same as --dest.
  SSHPASS             Optional password for sshpass. Void live ISO default: voidlinux.
  SSH_PASSWORD        Same as SSHPASS.

The persistent VM must already be booted. The default instance is the
installed CodeQL VM, using Lima's generated SSH config by default. For the
stock Void live ISO before Lima key login is enabled, use --user anon and
SSHPASS=voidlinux.
EOF
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

need_cmd() {
	command -v "$1" > /dev/null 2>&1 || die "missing required command: $1"
}

shell_quote() {
	printf '%q' "$1"
}

PORT=""
user_set=0
port_set=0

while (($# > 0)); do
	case "$1" in
		-h | --help)
			usage
			exit 0
			;;
		-i | --instance)
			shift
			(($# > 0)) || die "--instance requires a value"
			INSTANCE=$1
			;;
		-u | --user)
			shift
			(($# > 0)) || die "--user requires a value"
			REMOTE_USER=$1
			user_set=1
			;;
		-d | --dest)
			shift
			(($# > 0)) || die "--dest requires a value"
			REMOTE_DIR=$1
			;;
		-p | --port)
			shift
			(($# > 0)) || die "--port requires a value"
			PORT=$1
			port_set=1
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
	shift
done

need_cmd rsync
need_cmd ssh

ssh_config="${HOME}/.lima/${INSTANCE}/ssh.config"
host_alias=""
use_lima_ssh_config=0

if [[ "${user_set}" -eq 0 && "${port_set}" -eq 0 && -r "${ssh_config}" ]]; then
	host_alias=$(awk '$1 == "Host" { print $2; exit }' "${ssh_config}")
	REMOTE_USER=$(awk '$1 == "User" { print $2; exit }' "${ssh_config}")
	PORT=$(awk '$1 == "Port" { print $2; exit }' "${ssh_config}")
	[[ -n "${host_alias}" ]] || die "could not find Host in ${ssh_config}"
	[[ -n "${REMOTE_USER}" ]] || die "could not find User in ${ssh_config}"
	[[ -n "${PORT}" ]] || die "could not find Port in ${ssh_config}"
	use_lima_ssh_config=1
elif [[ -z "${PORT}" ]]; then
	[[ -r "${ssh_config}" ]] || die "cannot read ${ssh_config}; pass --port PORT"
	PORT=$(awk '$1 == "Port" { print $2; exit }' "${ssh_config}")
	[[ -n "${PORT}" ]] || die "could not find Port in ${ssh_config}"
fi

if [[ -z "${REMOTE_USER}" ]]; then
	REMOTE_USER=anon
fi

if [[ "${use_lima_ssh_config}" -eq 1 ]]; then
	ssh_cmd=(ssh -F "${ssh_config}")
	rsync_ssh_cmd=(ssh -F "${ssh_config}")
	remote="${host_alias}"
	remote_display="${REMOTE_USER}@127.0.0.1"
else
	ssh_cmd=(
		ssh
		-o StrictHostKeyChecking=no
		-o UserKnownHostsFile=/dev/null
		-o NoHostAuthenticationForLocalhost=yes
		-p "${PORT}"
	)

	rsync_ssh_cmd=(
		ssh
		-o StrictHostKeyChecking=no
		-o UserKnownHostsFile=/dev/null
		-o NoHostAuthenticationForLocalhost=yes
		-p "${PORT}"
	)
	remote="${REMOTE_USER}@127.0.0.1"
	remote_display="${remote}"
fi

if [[ -n "${SSH_PASSWORD}" ]]; then
	if [[ "${use_lima_ssh_config}" -eq 1 ]]; then
		printf '%s\n' "warning: SSHPASS ignored when using Lima key-based SSH config" >&2
	elif command -v sshpass > /dev/null 2>&1; then
		ssh_cmd=(sshpass -e "${ssh_cmd[@]}")
		rsync_ssh_cmd=(sshpass -e "${rsync_ssh_cmd[@]}")
		export SSHPASS="${SSH_PASSWORD}"
	else
		printf '%s\n' "warning: SSH_PASSWORD/SSHPASS set but sshpass is not installed; SSH may prompt" >&2
	fi
fi

if [[ -z "${REMOTE_DIR}" ]]; then
	# shellcheck disable=SC2016
	remote_home=$("${ssh_cmd[@]}" "${remote}" 'printf %s "${HOME}"')
	[[ -n "${remote_home}" ]] || die "could not determine remote HOME"
	REMOTE_DIR="${remote_home}/void-runner"
fi

printf '==> checking remote rsync on %s port %s\n' "${remote_display}" "${PORT}"
"${ssh_cmd[@]}" "${remote}" '
	if ! command -v rsync >/dev/null 2>&1; then
		sudo xbps-install -Sy xbps || sudo xbps-install -u xbps
		sudo xbps-install -Sy rsync
	fi
'

printf '==> creating remote destination %s\n' "${REMOTE_DIR}"
quoted_remote_dir=$(shell_quote "${REMOTE_DIR}")
"${ssh_cmd[@]}" "${remote}" "mkdir -p ${quoted_remote_dir}"

printf '==> syncing %s to %s:%s\n' "${ROOT_DIR}" "${remote_display}" "${REMOTE_DIR}"
rsync -az --delete \
	--exclude .git/ \
	--exclude .DS_Store \
	-e "$(printf '%q ' "${rsync_ssh_cmd[@]}")" \
	"${ROOT_DIR}/" \
	"${remote}:${REMOTE_DIR}/"

printf '==> sync complete\n'
printf 'Run in the VM: cd %s && sudo sh ./scripts/provision-void-codeql.sh\n' "${REMOTE_DIR}"

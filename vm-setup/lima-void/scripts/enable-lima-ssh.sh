#!/usr/bin/env bash
set -euo pipefail

INSTANCE=${INSTANCE:-void-codeql-16g-1}
BOOT_USER=${BOOT_USER:-anon}
SSH_PASSWORD=${SSH_PASSWORD:-${SSHPASS:-}}

usage() {
	cat << 'EOF'
Usage: scripts/enable-lima-ssh.sh [options]

Create Lima's expected SSH user inside the temporary Void live-ISO builder
and complete Lima's bootstrap probes.

Options:
  -h, --help          Show this help text.
  -i, --instance NAME Lima instance name. Default: void-codeql-16g-1.
  -b, --boot-user USER
                      Existing live-ISO SSH user. Default: anon.
  -p, --port PORT     SSH forwarded port. Default: read from ~/.lima/INSTANCE/ssh.config.

Environment:
  INSTANCE            Same as --instance.
  BOOT_USER           Same as --boot-user.
  SSHPASS             Optional password for sshpass. Void live ISO default: voidlinux.
  SSH_PASSWORD        Same as SSHPASS.

Run this after the temporary Void live-ISO builder has booted but before
giving up on Lima's SSH readiness probe. It installs the public key from
Lima's generated cloud-config, mounts Lima's cidata ISO when present, starts
the guest agent, and writes the
current boot readiness markers expected by the hostagent.
EOF
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

need_cmd() {
	command -v "$1" > /dev/null 2>&1 || die "missing required command: $1"
}

yaml_value() {
	awk -v key="$1" '
		$1 == key ":" {
			$1 = ""
			sub(/^[[:space:]]+/, "")
			gsub(/^"|"$/, "")
			print
			exit
		}
	' "$2"
}

cloud_pubkey() {
	awk '
		/ssh-authorized-keys:/ {
			found = 1
			next
		}
		found && /^[[:space:]]*-[[:space:]]*"/ {
			sub(/^[[:space:]]*-[[:space:]]*"/, "")
			sub(/"$/, "")
			print
			exit
		}
	' "$1"
}

shell_quote() {
	printf '%q' "$1"
}

PORT=""

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
		-b | --boot-user)
			shift
			(($# > 0)) || die "--boot-user requires a value"
			BOOT_USER=$1
			;;
		-p | --port)
			shift
			(($# > 0)) || die "--port requires a value"
			PORT=$1
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
	shift
done

need_cmd awk
need_cmd ssh

lima_dir="${HOME}/.lima/${INSTANCE}"
ssh_config="${lima_dir}/ssh.config"
cloud_config="${lima_dir}/cloud-config.yaml"

[[ -r "${ssh_config}" ]] || die "cannot read ${ssh_config}; pass --port PORT"
[[ -r "${cloud_config}" ]] || die "cannot read ${cloud_config}"

if [[ -z "${PORT}" ]]; then
	PORT=$(awk '$1 == "Port" { print $2; exit }' "${ssh_config}")
	[[ -n "${PORT}" ]] || die "could not find Port in ${ssh_config}"
fi

lima_user=$(awk '$1 == "User" { print $2; exit }' "${ssh_config}")
lima_uid=$(yaml_value uid "${cloud_config}")
lima_home=$(yaml_value homedir "${cloud_config}")
lima_shell=$(yaml_value shell "${cloud_config}")
lima_pubkey=$(cloud_pubkey "${cloud_config}")

[[ -n "${lima_user}" ]] || die "could not find Lima user in ${ssh_config}"
[[ -n "${lima_uid}" ]] || die "could not find uid in ${cloud_config}"
[[ -n "${lima_home}" ]] || die "could not find homedir in ${cloud_config}"
[[ -n "${lima_shell}" ]] || die "could not find shell in ${cloud_config}"
[[ -n "${lima_pubkey}" ]] || die "could not find ssh public key in ${cloud_config}"

ssh_cmd=(
	ssh
	-o StrictHostKeyChecking=no
	-o UserKnownHostsFile=/dev/null
	-o NoHostAuthenticationForLocalhost=yes
	-p "${PORT}"
)

if [[ -n "${SSH_PASSWORD}" ]]; then
	if command -v sshpass > /dev/null 2>&1; then
		ssh_cmd=(sshpass -e "${ssh_cmd[@]}")
		export SSHPASS="${SSH_PASSWORD}"
	else
		printf '%s\n' "warning: SSH_PASSWORD/SSHPASS set but sshpass is not installed; SSH may prompt" >&2
	fi
fi

remote="${BOOT_USER}@127.0.0.1"
quoted_lima_user=$(shell_quote "${lima_user}")
quoted_lima_uid=$(shell_quote "${lima_uid}")
quoted_lima_home=$(shell_quote "${lima_home}")
quoted_lima_shell=$(shell_quote "${lima_shell}")
quoted_lima_pubkey=$(shell_quote "${lima_pubkey}")
remote_env=$(
	printf 'LIMA_USER=%s LIMA_UID=%s LIMA_HOME=%s LIMA_SHELL=%s LIMA_PUBKEY=%s' \
		"${quoted_lima_user}" \
		"${quoted_lima_uid}" \
		"${quoted_lima_home}" \
		"${quoted_lima_shell}" \
		"${quoted_lima_pubkey}"
)

printf '==> enabling Lima SSH user %s via %s port %s\n' "${lima_user}" "${remote}" "${PORT}"
"${ssh_cmd[@]}" "${remote}" "${remote_env} /bin/sh -s" << 'REMOTE'
set -eu

if ! id "${LIMA_USER}" >/dev/null 2>&1; then
	if getent passwd "${LIMA_UID}" >/dev/null 2>&1; then
		sudo useradd -m -o -u "${LIMA_UID}" -d "${LIMA_HOME}" -s "${LIMA_SHELL}" "${LIMA_USER}"
	else
		sudo useradd -m -u "${LIMA_UID}" -d "${LIMA_HOME}" -s "${LIMA_SHELL}" "${LIMA_USER}"
	fi
fi

sudo mkdir -p "${LIMA_HOME}/.ssh"
printf '%s\n' "${LIMA_PUBKEY}" | sudo tee "${LIMA_HOME}/.ssh/authorized_keys" >/dev/null
sudo chown -R "${LIMA_USER}:${LIMA_USER}" "${LIMA_HOME}/.ssh"
sudo chmod 700 "${LIMA_HOME}/.ssh"
sudo chmod 600 "${LIMA_HOME}/.ssh/authorized_keys"

sudo mkdir -p /etc/sudoers.d
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "${LIMA_USER}" |
	sudo tee "/etc/sudoers.d/99-lima-${LIMA_USER}" >/dev/null
sudo chmod 440 "/etc/sudoers.d/99-lima-${LIMA_USER}"

sudo /bin/sh << 'ROOT'
set -eu

log() {
	printf '%s\n' "==> $*"
}

warn() {
	printf '%s\n' "warning: $*" >&2
}

mount_lima_cidata() {
	mkdir -p /mnt/lima-cidata
	if grep -qs '[[:space:]]/mnt/lima-cidata[[:space:]]' /proc/mounts; then
		return 0
	fi

	cidata_device=""
	for device in /dev/disk/by-label/cidata /dev/sr0 /dev/vdb /dev/sdb; do
		[ -e "${device}" ] || continue
		label="$(blkid -o value -s LABEL "${device}" 2>/dev/null || true)"
		if [ "${label}" = "cidata" ]; then
			cidata_device="${device}"
			break
		fi
	done

	if [ -z "${cidata_device}" ]; then
		warn "could not find Lima cidata block device; skipping guestagent bootstrap"
		return 1
	fi

	log "mounting Lima cidata from ${cidata_device}"
	mount -t iso9660 -o ro "${cidata_device}" /mnt/lima-cidata
}

start_lima_guestagent() {
	[ -r /mnt/lima-cidata/lima.env ] || return 1
	while read -r line; do
		[ -n "${line}" ] && export "${line}"
	done </mnt/lima-cidata/lima.env

	: "${LIMA_CIDATA_DEBUG:=false}"
	: "${LIMA_CIDATA_GUEST_INSTALL_PREFIX:=/usr/local}"
	: "${LIMA_CIDATA_IID:=}"
	if [ -z "${LIMA_CIDATA_IID}" ] && [ -r /mnt/lima-cidata/meta-data ]; then
		LIMA_CIDATA_IID="$(cat /mnt/lima-cidata/meta-data)"
	fi
	: "${LIMA_CIDATA_VIRTIO_PORT:=}"
	: "${LIMA_CIDATA_VSOCK_PORT:=0}"

	if [ -n "${LIMA_CIDATA_IID}" ]; then
		printf '%s\n' "${LIMA_CIDATA_IID}" >/run/lima-ssh-ready
	fi

	mkdir -p "${LIMA_CIDATA_GUEST_INSTALL_PREFIX}/bin"
	install -m 755 /mnt/lima-cidata/lima-guestagent \
		"${LIMA_CIDATA_GUEST_INSTALL_PREFIX}/bin/lima-guestagent"

	agent_args="daemon --debug=${LIMA_CIDATA_DEBUG}"
	if [ "${LIMA_CIDATA_VSOCK_PORT}" != "0" ]; then
		agent_args="${agent_args} --vsock-port ${LIMA_CIDATA_VSOCK_PORT}"
	elif [ -n "${LIMA_CIDATA_VIRTIO_PORT}" ]; then
		agent_args="${agent_args} --virtio-port ${LIMA_CIDATA_VIRTIO_PORT}"
	fi

	if [ -d /etc/runit ] && [ -d /var/service ]; then
		log "installing runit service for Lima guestagent"
		mkdir -p /etc/sv/lima-guestagent
		cat >/etc/sv/lima-guestagent/run << EOF
#!/bin/sh
exec 2>&1
exec ${LIMA_CIDATA_GUEST_INSTALL_PREFIX}/bin/lima-guestagent ${agent_args}
EOF
		chmod 755 /etc/sv/lima-guestagent/run
		ln -sfn /etc/sv/lima-guestagent /var/service/lima-guestagent
		if command -v sv >/dev/null 2>&1; then
			sv up lima-guestagent >/dev/null 2>&1 || true
			sv restart lima-guestagent >/dev/null 2>&1 || true
		fi
	elif [ ! -S /run/lima-guestagent.sock ]; then
		log "starting Lima guestagent directly"
		nohup "${LIMA_CIDATA_GUEST_INSTALL_PREFIX}/bin/lima-guestagent" ${agent_args} \
			>/var/log/lima-guestagent.log 2>&1 &
	fi

	if [ -n "${LIMA_CIDATA_IID}" ]; then
		printf '%s\n' "${LIMA_CIDATA_IID}" >/run/lima-boot-done
	fi
}

if mount_lima_cidata; then
	start_lima_guestagent || warn "Lima guestagent bootstrap did not complete"
fi
ROOT
REMOTE

printf '==> Lima SSH user is ready; the hostagent should pass on its next retry\n'

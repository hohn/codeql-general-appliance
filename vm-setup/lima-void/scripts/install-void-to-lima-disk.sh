#!/usr/bin/env bash
set -euo pipefail

INSTANCE=${INSTANCE:-void-codeql-16g-1}
BOOT_USER=${BOOT_USER:-anon}
INSTALL_DISK=${INSTALL_DISK:-/dev/vdb}
TARGET_INSTANCE=${TARGET_INSTANCE:-void-codeql-16g-installed}
VOID_REPOSITORY=${VOID_REPOSITORY:-https://repo-default.voidlinux.org/current/aarch64}
VOID_ARCH=${VOID_ARCH:-aarch64}
SSH_PASSWORD=${SSH_PASSWORD:-${SSHPASS:-}}
FORCE=0

usage() {
	cat << 'EOF'
Usage: scripts/install-void-to-lima-disk.sh --force [options]

Destructively install Void Linux onto the temporary builder VM disk.

Options:
  -h, --help          Show this help text.
  -i, --instance NAME Lima instance name. Default: void-codeql-16g-1.
  -b, --boot-user USER
                      Existing live-ISO SSH user. Default: anon.
  -d, --disk DEVICE   Target guest disk. Default: /dev/vdb.
  -p, --port PORT     SSH forwarded port. Default: read from ~/.lima/INSTANCE/ssh.config.
  --repo URL          Void repository. Default: aarch64 glibc repository.
  --arch ARCH         XBPS architecture. Default: aarch64.
  --target-instance NAME
                      Installed Lima instance to create from this disk.
                      Default: void-codeql-16g-installed.
  --force             Required. Confirms DEVICE will be wiped.

Environment:
  INSTANCE            Same as --instance.
  BOOT_USER           Same as --boot-user.
  INSTALL_DISK        Same as --disk.
  TARGET_INSTANCE     Same as --target-instance.
  VOID_REPOSITORY     Same as --repo.
  VOID_ARCH           Same as --arch.
  SSHPASS             Optional password for sshpass. Void live ISO default: voidlinux.
  SSH_PASSWORD        Same as SSHPASS.

This script runs against the temporary live-ISO builder VM. It wipes the
target disk, creates an EFI System Partition and ext4 root filesystem,
bootstraps Void with XBPS, installs GRUB for aarch64 UEFI, enables
sshd/dhcpcd, and installs a runit service that satisfies Lima's cidata, SSH,
guestagent, and boot-done probes on each persistent boot. The installed qcow2
is then used as the boot image for the target CodeQL VM.
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
		-d | --disk)
			shift
			(($# > 0)) || die "--disk requires a value"
			INSTALL_DISK=$1
			;;
		-p | --port)
			shift
			(($# > 0)) || die "--port requires a value"
			PORT=$1
			;;
		--repo)
			shift
			(($# > 0)) || die "--repo requires a value"
			VOID_REPOSITORY=$1
			;;
		--arch)
			shift
			(($# > 0)) || die "--arch requires a value"
			VOID_ARCH=$1
			;;
		--target-instance)
			shift
			(($# > 0)) || die "--target-instance requires a value"
			TARGET_INSTANCE=$1
			;;
		--force)
			FORCE=1
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
	shift
done

[[ "${FORCE}" -eq 1 ]] || die "--force is required because ${INSTALL_DISK} will be wiped"

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

printf '==> installing persistent Void on %s:%s via %s port %s\n' \
	"${INSTANCE}" "${INSTALL_DISK}" "${remote}" "${PORT}"

quoted_install_disk=$(shell_quote "${INSTALL_DISK}")
quoted_void_repository=$(shell_quote "${VOID_REPOSITORY}")
quoted_void_arch=$(shell_quote "${VOID_ARCH}")
quoted_lima_user=$(shell_quote "${lima_user}")
quoted_lima_uid=$(shell_quote "${lima_uid}")
quoted_lima_home=$(shell_quote "${lima_home}")
quoted_lima_shell=$(shell_quote "${lima_shell}")
quoted_lima_pubkey=$(shell_quote "${lima_pubkey}")

{
	printf 'INSTALL_DISK=%s\n' "${quoted_install_disk}"
	printf 'VOID_REPOSITORY=%s\n' "${quoted_void_repository}"
	printf 'VOID_ARCH=%s\n' "${quoted_void_arch}"
	printf 'LIMA_USER=%s\n' "${quoted_lima_user}"
	printf 'LIMA_UID=%s\n' "${quoted_lima_uid}"
	printf 'LIMA_HOME=%s\n' "${quoted_lima_home}"
	printf 'LIMA_SHELL=%s\n' "${quoted_lima_shell}"
	printf 'LIMA_PUBKEY=%s\n' "${quoted_lima_pubkey}"
	cat << 'REMOTE'
set -eu

TARGET=/mnt/void-target

log() {
	printf '%s\n' "==> $*"
}

die() {
	printf '%s\n' "error: $*" >&2
	exit 1
}

need_cmd() {
	command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

partition_path() {
	case "$1" in
		*[0-9]) printf '%sp%s\n' "$1" "$2" ;;
		*) printf '%s%s\n' "$1" "$2" ;;
	esac
}

[ "$(id -u)" -eq 0 ] || die "remote installer must run as root"
[ -b "${INSTALL_DISK}" ] || die "target disk does not exist: ${INSTALL_DISK}"

for cmd in xbps-install sfdisk mkfs.vfat mkfs.ext4 blkid mount chroot grub-install; do
	need_cmd "${cmd}"
done

if ! findmnt -no FSTYPE / 2>/dev/null | grep -qx overlay; then
	die "expected to run from the Void live ISO overlay root"
fi

efi_part=$(partition_path "${INSTALL_DISK}" 1)
root_part=$(partition_path "${INSTALL_DISK}" 2)

log "wiping and partitioning ${INSTALL_DISK}"
umount -R "${TARGET}" 2>/dev/null || true
sfdisk --wipe always --wipe-partitions always "${INSTALL_DISK}" << EOF
label: gpt
unit: sectors

,1GiB,U
,,L
EOF

if command -v partprobe >/dev/null 2>&1; then
	partprobe "${INSTALL_DISK}" || true
fi
if command -v udevadm >/dev/null 2>&1; then
	udevadm settle || true
fi
sleep 2

[ -b "${efi_part}" ] || die "EFI partition was not created: ${efi_part}"
[ -b "${root_part}" ] || die "root partition was not created: ${root_part}"

log "creating filesystems"
mkfs.vfat -F 32 -n VOID_EFI "${efi_part}"
mkfs.ext4 -F -L void-root "${root_part}"

log "mounting target filesystems"
mkdir -p "${TARGET}"
mount "${root_part}" "${TARGET}"
mkdir -p "${TARGET}/boot/efi"
mount "${efi_part}" "${TARGET}/boot/efi"

log "bootstrapping Void base system from ${VOID_REPOSITORY}"
mkdir -p "${TARGET}/var/db/xbps/keys"
cp /var/db/xbps/keys/* "${TARGET}/var/db/xbps/keys/"
XBPS_ARCH="${VOID_ARCH}" xbps-install -Sy -r "${TARGET}" -R "${VOID_REPOSITORY}" \
	base-system linux grub-arm64-efi sudo openssh dhcpcd bash rsync \
	ca-certificates curl git tar xz

root_uuid=$(blkid -s UUID -o value "${root_part}")
efi_uuid=$(blkid -s UUID -o value "${efi_part}")

log "configuring installed system"
cat >"${TARGET}/etc/fstab" << EOF
UUID=${root_uuid} / ext4 defaults,noatime 0 1
UUID=${efi_uuid} /boot/efi vfat defaults 0 2
EOF

printf '%s\n' "void-codeql" >"${TARGET}/etc/hostname"
cat >"${TARGET}/etc/hosts" << 'EOF'
127.0.0.1 localhost
::1 localhost
127.0.1.1 void-codeql.localdomain void-codeql
EOF

mkdir -p "${TARGET}/etc/xbps.d"
cat >"${TARGET}/etc/xbps.d/00-repository-main.conf" << EOF
repository=${VOID_REPOSITORY}
EOF

if [ -e "${TARGET}/usr/share/zoneinfo/UTC" ]; then
	ln -sfn /usr/share/zoneinfo/UTC "${TARGET}/etc/localtime"
fi

mkdir -p "${TARGET}/dev" "${TARGET}/proc" "${TARGET}/sys" "${TARGET}/run"
for mountpoint in dev proc sys run; do
	mount --rbind "/${mountpoint}" "${TARGET}/${mountpoint}"
	mount --make-rslave "${TARGET}/${mountpoint}" 2>/dev/null || true
done

if ! chroot "${TARGET}" getent passwd "${LIMA_USER}" >/dev/null 2>&1; then
	chroot "${TARGET}" useradd -m -u "${LIMA_UID}" -d "${LIMA_HOME}" -s "${LIMA_SHELL}" "${LIMA_USER}"
fi

mkdir -p "${TARGET}${LIMA_HOME}/.ssh"
printf '%s\n' "${LIMA_PUBKEY}" >"${TARGET}${LIMA_HOME}/.ssh/authorized_keys"
chroot "${TARGET}" chown -R "${LIMA_USER}:${LIMA_USER}" "${LIMA_HOME}/.ssh"
chmod 700 "${TARGET}${LIMA_HOME}/.ssh"
chmod 600 "${TARGET}${LIMA_HOME}/.ssh/authorized_keys"

mkdir -p "${TARGET}/etc/sudoers.d"
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "${LIMA_USER}" \
	>"${TARGET}/etc/sudoers.d/99-lima-${LIMA_USER}"
chmod 440 "${TARGET}/etc/sudoers.d/99-lima-${LIMA_USER}"

log "installing persistent Lima guestagent runit service"
mkdir -p "${TARGET}/etc/sv/lima-guestagent"
cat >"${TARGET}/etc/sv/lima-guestagent/run" << 'EOF'
#!/bin/sh
set -eu

warn() {
	printf '%s\n' "warning: $*" >&2
}

mount_lima_cidata() {
	mkdir -p /mnt/lima-cidata
	if grep -qs '[[:space:]]/mnt/lima-cidata[[:space:]]' /proc/mounts; then
		return 0
	fi

	for device in /dev/disk/by-label/cidata /dev/sr0 /dev/vdb /dev/sdb; do
		[ -e "${device}" ] || continue
		label="$(blkid -o value -s LABEL "${device}" 2>/dev/null || true)"
		if [ "${label}" = "cidata" ]; then
			mount -t iso9660 -o ro "${device}" /mnt/lima-cidata
			return 0
		fi
	done

	return 1
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
	' /mnt/lima-cidata/user-data
}

if ! mount_lima_cidata; then
	warn "could not mount Lima cidata"
	sleep 5
	exit 1
fi

while read -r line; do
	[ -n "${line}" ] && export "${line}"
done </mnt/lima-cidata/lima.env

: "${LIMA_CIDATA_DEBUG:=false}"
: "${LIMA_CIDATA_GUEST_INSTALL_PREFIX:=/usr/local}"
: "${LIMA_CIDATA_HOME:=/home/${LIMA_CIDATA_USER}.guest}"
: "${LIMA_CIDATA_SHELL:=/bin/bash}"
: "${LIMA_CIDATA_UID:=1000}"
: "${LIMA_CIDATA_IID:=}"
if [ -z "${LIMA_CIDATA_IID}" ] && [ -r /mnt/lima-cidata/meta-data ]; then
	LIMA_CIDATA_IID="$(cat /mnt/lima-cidata/meta-data)"
fi
: "${LIMA_CIDATA_VIRTIO_PORT:=}"
: "${LIMA_CIDATA_VSOCK_PORT:=0}"

if ! id "${LIMA_CIDATA_USER}" >/dev/null 2>&1; then
	useradd -m -u "${LIMA_CIDATA_UID}" -d "${LIMA_CIDATA_HOME}" \
		-s "${LIMA_CIDATA_SHELL}" "${LIMA_CIDATA_USER}"
fi

pubkey="$(cloud_pubkey || true)"
if [ -n "${pubkey}" ]; then
	mkdir -p "${LIMA_CIDATA_HOME}/.ssh"
	printf '%s\n' "${pubkey}" >"${LIMA_CIDATA_HOME}/.ssh/authorized_keys"
	chown -R "${LIMA_CIDATA_USER}:${LIMA_CIDATA_USER}" "${LIMA_CIDATA_HOME}/.ssh"
	chmod 700 "${LIMA_CIDATA_HOME}/.ssh"
	chmod 600 "${LIMA_CIDATA_HOME}/.ssh/authorized_keys"
fi

mkdir -p /etc/sudoers.d
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "${LIMA_CIDATA_USER}" \
	>"/etc/sudoers.d/99-lima-${LIMA_CIDATA_USER}"
chmod 440 "/etc/sudoers.d/99-lima-${LIMA_CIDATA_USER}"

if [ -n "${LIMA_CIDATA_IID}" ]; then
	printf '%s\n' "${LIMA_CIDATA_IID}" >/run/lima-ssh-ready
	printf '%s\n' "${LIMA_CIDATA_IID}" >/run/lima-boot-done
fi

mkdir -p "${LIMA_CIDATA_GUEST_INSTALL_PREFIX}/bin"
install -m 755 /mnt/lima-cidata/lima-guestagent \
	"${LIMA_CIDATA_GUEST_INSTALL_PREFIX}/bin/lima-guestagent"

set -- daemon "--debug=${LIMA_CIDATA_DEBUG}"
if [ "${LIMA_CIDATA_VSOCK_PORT}" != "0" ]; then
	set -- "$@" --vsock-port "${LIMA_CIDATA_VSOCK_PORT}"
elif [ -n "${LIMA_CIDATA_VIRTIO_PORT}" ]; then
	set -- "$@" --virtio-port "${LIMA_CIDATA_VIRTIO_PORT}"
fi

exec "${LIMA_CIDATA_GUEST_INSTALL_PREFIX}/bin/lima-guestagent" "$@"
EOF
chmod 755 "${TARGET}/etc/sv/lima-guestagent/run"

mkdir -p "${TARGET}/etc/runit/runsvdir/default"
ln -sfn /etc/sv/dhcpcd "${TARGET}/etc/runit/runsvdir/default/dhcpcd"
ln -sfn /etc/sv/sshd "${TARGET}/etc/runit/runsvdir/default/sshd"
ln -sfn /etc/sv/acpid "${TARGET}/etc/runit/runsvdir/default/acpid"
ln -sfn /etc/sv/lima-guestagent "${TARGET}/etc/runit/runsvdir/default/lima-guestagent"

log "installing GRUB for aarch64 UEFI"
chroot "${TARGET}" grub-install \
	--target=arm64-efi \
	--efi-directory=/boot/efi \
	--bootloader-id=Void \
	--removable \
	--no-nvram
chroot "${TARGET}" xbps-reconfigure -fa
chroot "${TARGET}" grub-mkconfig -o /boot/grub/grub.cfg

sync
log "persistent Void install complete on ${INSTALL_DISK}"
log "create the target Lima instance from the installed qcow2"
REMOTE
} | "${ssh_cmd[@]}" "${remote}" "sudo /bin/sh -s"

printf '==> install complete\n'
printf 'Next:\n'
printf '  limactl stop %s\n' "${INSTANCE}"
image_set=".images = [{\"location\":\"file://${HOME}/.lima/${INSTANCE}/diffdisk\", \"arch\":\"aarch64\"}] | .provision = []"
printf '  limactl create --name=%s --tty=false --ssh-port=65393 --set=%q ./lima/void-codeql-16g.yaml\n' "${TARGET_INSTANCE}" "${image_set}"
printf '  limactl start %s\n' "${TARGET_INSTANCE}"

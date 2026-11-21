# Void CodeQL Lima Appliance Notes

These steps have been tested from a Linux VM and on the macOS Lima host.

## Files

- `lima/void-codeql.yaml`: minimal Lima target shape for a Void/glibc arm64 appliance.
- `lima/void-codeql-16g.yaml`: 16 GiB worker profile.
- `lima/void-codeql-74g.yaml`: 74 GiB worker profile.
- `lima/void-codeql-128g.yaml`: 128 GiB worker profile.
- `scripts/enable-lima-ssh.sh`: host-side helper that creates Lima's expected
  public-key SSH user in the live VM and completes the Lima live-ISO bootstrap
  probes.
- `scripts/install-void-to-lima-disk.sh`: destructive host-side installer that
  replaces the live ISO overlay with a persistent Void install on the Lima disk.
- `scripts/provision-void-codeql.sh`: idempotent Void provisioner for Java and CodeQL.
- `scripts/sync-to-void.sh`: host-side rsync helper for copying this tree into
  the VM.
- `scripts/validate-codeql.sh`: validates Java, CodeQL, and a tiny JavaScript analysis.

## Current upstream facts

- Void publishes live ISOs and rootfs tarballs at `https://repo-default.voidlinux.org/live/current/`.
- As of this handoff, the arm64/aarch64 glibc base ISO is `void-live-aarch64-20250202-base.iso`.
- CodeQL is pinned by default to the GitHub CodeQL Action bundle release
  `codeql-bundle-v2.27.1`, using `codeql-bundle-linux-arm64.tar.gz` on ARM64
  and `codeql-bundle-linux64.tar.gz` on x86_64.
- The provisioner intentionally installs the full bundle, not the CLI-only
  archive and not the generic bundle. The appliance follows the same runtime
  contract as `scripts/20-analyze.sh`: executable at
  `/opt/codeql/codeql`, `/opt/codeql` on `PATH`, and `CODEQL_JAVA_HOME=/usr`
  for ARM compatibility.

## Host prerequisites

### macOS

Install Lima, sync/SSH helpers, and the local check tools:

```sh
brew install lima rsync shellcheck shfmt yamllint node
brew install hudochenkov/sshpass/sshpass
sudo npm install -g prettier markdownlint-cli
```

Verify the VM tools:

```sh
limactl --version
qemu-system-aarch64 --version 2>/dev/null || true
```

### Linux

Install QEMU, KVM support, SSH helpers, and the local check tools:

```sh
sudo apt-get update
sudo apt-get install -y \
  ca-certificates \
  curl \
  devscripts \
  qemu-system-arm \
  qemu-utils \
  rsync \
  ruby-mdl \
  shellcheck \
  shfmt \
  sshpass \
  yamllint
sudo npm install -g prettier markdownlint-cli
```

Install Lima from the upstream Linux aarch64 tarball, then verify it:

```sh
limactl --version
limactl validate ./lima/void-codeql-16g.yaml
```

KVM must be available for a useful Linux reference run:

```sh
test -e /dev/kvm && ls -l /dev/kvm
qemu-system-aarch64 -accel help | grep -x kvm
```

If `/dev/kvm` is absent, enable nested virtualization in the outer host before
testing. Without KVM, Lima can boot through QEMU TCG, but it is too slow for
meaningful CodeQL appliance testing.

## Platform-specific first boot notes

### macOS first boot

The macOS Lima path has been tested with the stock Void live ISO. Lima boots the
VM, then waits on its SSH readiness probe because the ISO does not consume
Lima's injected user data. Use a short `limactl start` timeout, keep the
instance running, and connect with the direct `anon` SSH path in the basics
section.

### Linux first boot

Lima 2.1.4 does not provide a `limactl console` command. On Linux, boot progress
is visible in the instance serial logs under:

```sh
ls ~/.lima/void-codeql-16g-1/serial*.log
tail -f ~/.lima/void-codeql-16g-1/serial.log
```

Nested virtualization must be exposed by the outer host. With `/dev/kvm`
present, QEMU starts with KVM acceleration. Without `/dev/kvm`, Lima falls back
to QEMU TCG, which is not a useful reference setup for CodeQL workloads.

## Basics

### Start one worker

Start one worker profile from this repository:

```sh
limactl start --name=void-codeql-16g-1 \
  --timeout=90s --tty=false ./lima/void-codeql-16g.yaml || true
limactl start --name=void-codeql-74g-1 \
  --timeout=90s --tty=false ./lima/void-codeql-74g.yaml || true
limactl start --name=void-codeql-128g \
  --timeout=90s --tty=false ./lima/void-codeql-128g.yaml || true
```

The `|| true` is intentional for the stock Void live ISO. Lima has no start
option that makes the essential SSH readiness probe use `anon:voidlinux`, and
passing the correct live-ISO password is not supported by the probe. A short
timeout lets QEMU and the hostagent keep running; use the direct `anon` SSH
path below.

To make Lima's public-key login work, create the expected Lima user inside the
running live VM:

```sh
SSHPASS=voidlinux ./scripts/enable-lima-ssh.sh --instance void-codeql-16g-1
```

The helper reads `~/.lima/INSTANCE/cloud-config.yaml` and `ssh.config`, logs in
as `anon`, creates the Lima user, installs the generated public key, and grants
passwordless sudo. It also mounts Lima's cidata ISO, starts `lima-guestagent`
under runit when available, and writes `/run/lima-ssh-ready` plus
`/run/lima-boot-done` for the current boot. If the `limactl start` hostagent is
still retrying, it should pass the remaining requirements on the next retry. If
the start command already timed out, run it again with the instance name:

The stock Void live ISO uses a RAM-backed overlay for `/`, so these bootstrap
changes survive repeated `limactl start` checks during the same boot but do not
survive a cold reboot. Re-run the helper after each fresh live-ISO boot, or
install Void onto the Lima disk before treating guest-side changes as
persistent.

```sh
limactl start void-codeql-16g-1 --timeout=90s --tty=false
```

### Install persistent Void onto the Lima disk

The live ISO is useful for initial bootstrap, but its writable root is a
RAM-backed overlay. To make the VM persistent, install Void onto `/dev/vda`
from the running live VM:

```sh
SSHPASS=voidlinux ./scripts/install-void-to-lima-disk.sh \
  --instance void-codeql-16g-1 --force
```

This wipes `/dev/vda`, creates a 1 GiB EFI System Partition plus an ext4 root
partition, installs `base-system`, `linux`, `grub-arm64-efi`, `openssh`,
`dhcpcd`, `sudo`, and utility packages, and enables a persistent runit
`lima-guestagent` service. That service mounts Lima's cidata ISO on each boot,
refreshes the Lima user SSH key, starts the guest agent, and writes the current
`/run/lima-ssh-ready` and `/run/lima-boot-done` markers.

Restart the instance after the install:

```sh
limactl stop void-codeql-16g-1
limactl start void-codeql-16g-1
```

On the next boot, UEFI should find the GRUB fallback loader on `/dev/vda1`
before falling through to the live ISO. If the serial log still shows the live
ISO menu, inspect the ESP contents under `/boot/efi/EFI/BOOT/BOOTAA64.EFI` from
the live environment and rerun the installer.

The profiles are sized around the observed CodeQL database memory tiers from
2400+ database experiments: 16 GiB, 74 GiB, and 128 GiB. All profiles use 8
CPUs and a 1 TiB sparse disk.

### Access one worker

Useful Lima commands:

```sh
limactl list
limactl shell INSTANCE
limactl stop INSTANCE
limactl delete INSTANCE
limactl validate ./lima/void-codeql-16g.yaml
```

On the stock Void live ISO, Lima may keep waiting for key-based SSH because the
ISO does not consume the injected Lima user data. The live ISO still starts
password SSH. Use the forwarded port from `limactl list` and log in as:

```sh
ssh -p PORT anon@127.0.0.1
```

Password: `voidlinux`. The `anon` user is in `wheel` and can run passwordless
`sudo`.

If Lima reports `Waiting for the essential requirement 1 of 3: "ssh"` while
the host-agent log repeats `Permission denied` for the host username, the guest
has booted but Lima's injected user was not created. If it advances to
`user session is ready for ssh`, `/run/lima-ssh-ready` is missing. If it waits
for the guest agent or boot scripts, `lima-guestagent` or `/run/lima-boot-done`
is missing. Keep the instance running, open another terminal, and run
`scripts/enable-lima-ssh.sh` or use the direct `anon` login above. On macOS,
the forwarded port is also visible in:

```sh
grep Port ~/.lima/INSTANCE/ssh.config
```

### Copy repository into the VM

Run the sync helper from the host repository. It reads the SSH forwarded port
from `~/.lima/INSTANCE/ssh.config`, uses Lima's generated key-based SSH user by
default, installs `rsync` inside the Void guest if needed, and copies the full
tree into `~/void-runner`.
The helper updates `xbps` before installing guest-side `rsync`; Void refuses
most package installs until `xbps` itself is current.

```sh
./scripts/sync-to-void.sh --instance void-codeql-16g-1
```

For the stock live ISO before Lima key login is enabled, use the direct
password login:

```sh
SSHPASS=voidlinux ./scripts/sync-to-void.sh \
  --instance void-codeql-16g-1 --user anon
```

### Provision the worker

After syncing the repository, log into the VM and run the provisioner from the
copied tree:

```sh
limactl shell void-codeql-16g-1
cd ~/void-runner
sudo sh ./scripts/provision-void-codeql.sh
```

Or run it directly over SSH:

```sh
limactl shell void-codeql-16g-1 -- \
  sh -lc 'cd ~/void-runner && sudo sh ./scripts/provision-void-codeql.sh'
```

To pin CodeQL:

```sh
sudo CODEQL_VERSION=v2.27.1 sh ./scripts/provision-void-codeql.sh
```

`CODEQL_VERSION` accepts `v2.27.1`, `2.27.1`, or the full tag
`codeql-bundle-v2.27.1`. Set `FORCE_CODEQL_INSTALL=1` to replace an existing
`/opt/codeql` install.

If you are still testing directly from the live ISO instead of an installed
Void root filesystem, mount the Lima data disk before provisioning. The live
overlay is too small for the CodeQL bundle plus extracted queries.

```sh
sudo mkfs.ext4 -F /dev/vda
sudo mkdir -p /opt
sudo mount /dev/vda /opt
sudo sh ./scripts/provision-void-codeql.sh
```

The provisioner installs:

- `openjdk21-jre`
- `ca-certificates`
- `curl`
- `git`
- `tar`
- `xz`
- `bash`
- CodeQL under `/opt/codeql`
- `/usr/local/bin/codeql` symlink for convenience
- `/etc/profile.d/codeql.sh` setting `PATH` and `CODEQL_JAVA_HOME`

### Validate the worker

Run the baseline plus smoke test:

```sh
sh ./scripts/validate-codeql.sh
```

Run only the phase-1 version checks:

```sh
sh ./scripts/validate-codeql.sh --versions-only
```

Expected baseline commands:

```sh
java -version
codeql version
```

The smoke test writes a tiny JavaScript repository, creates a CodeQL database,
and analyzes it with:

```sh
codeql database create /tmp/codeql-smoke/db \
  --language=javascript \
  --source-root=/tmp/codeql-smoke/src \
  --overwrite
codeql database analyze /tmp/codeql-smoke/db \
  codeql/javascript-queries:codeql-suites/javascript-code-scanning.qls \
  --format=sarif-latest \
  --output=/tmp/codeql-smoke/results.sarif
```

### Clone a validated worker

After `void-codeql-16g-1` has a persistent Void install, a synced repository,
Java, CodeQL, and a passing validation run, stop it before cloning. Cloning a
stopped VM avoids copying a live filesystem.

```sh
limactl stop void-codeql-16g-1
```

Create two additional 16 GiB workers from the validated source and assign each
clone a unique Lima SSH port:

```sh
limactl clone void-codeql-16g-1 void-codeql-16g-2 --ssh-port 65393
limactl clone void-codeql-16g-1 void-codeql-16g-3 --ssh-port 65394
```

Start all three workers:

```sh
limactl start void-codeql-16g-1
limactl start void-codeql-16g-2
limactl start void-codeql-16g-3
```

Verify that all workers are running on distinct Mac-local SSH ports:

```sh
limactl list
```

Expected worker ports:

```text
void-codeql-16g-1    127.0.0.1:65392
void-codeql-16g-2    127.0.0.1:65393
void-codeql-16g-3    127.0.0.1:65394
```

Spot-check the cloned runtime on each worker:

```sh
for instance in void-codeql-16g-1 void-codeql-16g-2 void-codeql-16g-3; do
  limactl shell "${instance}" -- \
    sh -lc 'java -version 2>&1 | head -1; codeql version | head -1; sudo sv status acpid'
done
```

The expected baseline is OpenJDK 21, CodeQL 2.27.1, and `acpid` in `run`
state. `acpid` is required for `limactl stop` to complete cleanly.

## Regular use

### Remote access from another machine

Lima binds the guest SSH forward to `127.0.0.1` on the Mac host. From another
machine, tunnel through the Mac instead of exposing the VM SSH port to the LAN.

Set the target host and instance on the remote machine:

```sh
export MAC_HOST=m325.local
export INSTANCE=void-codeql-16g-1
```

Find the Lima SSH port on the Mac:

```sh
ssh "${MAC_HOST}" \
  "awk '\$1 == \"Port\" { print \$2; exit }' ~/.lima/${INSTANCE}/ssh.config"
```

If the instance is already running and `limactl list` reports
`127.0.0.1:65392`, tunnel that Mac-local port to a local port on this machine:

```sh
ssh -N -f -L 16592:127.0.0.1:65392 "${MAC_HOST}"
```

Then connect through the local tunnel:

```sh
ssh -p 16592 anon@127.0.0.1
```

Password for the stock live ISO is `voidlinux`.

If Lima public-key login is enabled and you want the Lima user directly, copy
the Lima private key once:

```sh
scp "${MAC_HOST}:~/.lima/_config/user" ~/.ssh/lima-m325-user
chmod 600 ~/.ssh/lima-m325-user
ssh -i ~/.ssh/lima-m325-user -p 16592 hohn@127.0.0.1
```

For predictable per-worker tunnels, the worker profiles assign fixed Lima SSH
ports before creating or recreating each instance:

```yaml
ssh:
   localPort: 65392
```

Use different Mac-local ports per worker, such as `65392`, `65393`, and
`65394`, then open all tunnels from the remote machine:

```sh
ssh -N -f \
  -L 16592:127.0.0.1:65392 \
  -L 16593:127.0.0.1:65393 \
  -L 16594:127.0.0.1:65394 \
  "${MAC_HOST}"
```

Connect through those local ports:

```sh
ssh -p 16592 anon@127.0.0.1
ssh -p 16593 anon@127.0.0.1
ssh -p 16594 anon@127.0.0.1
```

### Production run sequence

After a worker profile has booted, provisioned, and passed validation, run the
database corpus in memory tiers. Disk consumption varies by database, but Lima
disks are sparse, so the 1 TiB disk ceiling is useful without immediately
consuming 1 TiB on the host.

- Run six 16 GiB VMs first. This covers around 80% of databases.
- Run two 74 GiB VMs for the remaining larger databases. This covers about 18%
  more.
- Run one 128 GiB VM for the final roughly 2%; the rest usually fail for other
  reasons rather than memory.

### Rebuild loop

After changing the Lima YAML or wanting a clean appliance:

```sh
limactl stop void-codeql || true
limactl delete void-codeql
limactl start --name=void-codeql ./lima/void-codeql.yaml
```

Then provision and validate again.

### Known caveat

The remaining caveat is Lima SSH readiness, not guest boot. The stock Void ISO
does not create Lima's injected user, so `limactl shell` is not available until
you install or customize the guest. Use direct SSH as `anon` for live-ISO
provisioning.

Local Linux test note: Lima 2.1.4 and QEMU 9.2.1 validate this YAML on Ubuntu
25.04 aarch64. With `/dev/kvm` present, QEMU starts with
`-cpu host -machine virt,accel=kvm`. Without `/dev/kvm`, Lima starts QEMU with
TCG and is too slow for a useful reference run. The stock Void live ISO still
does not satisfy Lima's key-based SSH readiness check, but direct password SSH
to `anon@127.0.0.1` on the forwarded port works.

The Linux test uses the full native `codeql-bundle-linux-arm64.tar.gz` v2.27.1
bundle on Void aarch64, sets `CODEQL_JAVA_HOME=/usr`, and runs the JavaScript
`database create` plus `database analyze` smoke test. The former x86_64
`tools/linux64/scc` warning does not apply to this native ARM64 bundle.

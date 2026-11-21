# Debian CodeQL Lima Appliance Notes

These steps have been tested from a Linux VM and on the macOS Lima host.

Debian is a simpler target than Void: the Debian cloud image is Lima-ready, so
the VM boots straight into a persistent guest with working key-based SSH and
cloud-init. There is no live-ISO bootstrap and no separate disk-install step.

## Files

- `lima/debian-codeql.yaml`: default Lima target for a Debian 13 (trixie) appliance.
- `lima/debian-codeql-16g.yaml`: 16 GiB worker profile.
- `lima/debian-codeql-74g.yaml`: 74 GiB worker profile.
- `lima/debian-codeql-128g.yaml`: 128 GiB worker profile.
- `scripts/provision-debian-codeql.sh`: idempotent Debian provisioner for Java
  and CodeQL.
- `scripts/sync-to-debian.sh`: host-side rsync helper for copying this tree into
  the VM.
- `scripts/validate-codeql.sh`: validates Java, CodeQL, and a tiny JavaScript
  analysis.
- `scripts/20-analyze.sh`: CodeQL analysis driver script.

## Current upstream facts

- Debian publishes Lima-ready cloud images at
  `https://cloud.debian.org/images/cloud/trixie/`.
- The profiles pin the `20260623-2518` trixie release and fall back to the
  latest daily image if the pinned release is pruned. Run `limactl prune` to
  invalidate a stale cache.
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
  yamllint
sudo npm install -g prettier markdownlint-cli
```

Install Lima from the upstream Linux aarch64 tarball, then verify it:

```sh
limactl --version
limactl validate ./lima/debian-codeql-16g.yaml
```

KVM must be available for a useful Linux reference run:

```sh
test -e /dev/kvm && ls -l /dev/kvm
qemu-system-aarch64 -accel help | grep -x kvm
```

If `/dev/kvm` is absent, enable nested virtualization in the outer host before
testing. Without KVM, Lima can boot through QEMU TCG, but it is too slow for
meaningful CodeQL appliance testing.

## Basics

### Start one worker

Start one worker profile from this repository:

```sh
limactl start --name=debian-codeql-16g-1 \
  --timeout=600s --tty=false ./lima/debian-codeql-16g.yaml
limactl start --name=debian-codeql-74g-1 \
  --timeout=600s --tty=false ./lima/debian-codeql-74g.yaml
limactl start --name=debian-codeql-128g \
  --timeout=600s --tty=false ./lima/debian-codeql-128g.yaml
```

Unlike the Void live ISO, the Debian cloud image consumes Lima's injected user
data, so key-based SSH and `limactl shell` work as soon as the instance
finishes booting. Allow a generous timeout on the first start because Lima
downloads and unpacks the cloud image and runs the base `apt-get` provision
step.

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
limactl validate ./lima/debian-codeql-16g.yaml
```

Lima generates a key-based SSH config per instance. Connect either through
`limactl shell` or directly with the generated config:

```sh
ssh -F ~/.lima/debian-codeql-16g-1/ssh.config lima-debian-codeql-16g-1
```

On macOS, the forwarded port is visible in:

```sh
grep Port ~/.lima/INSTANCE/ssh.config
```

### Copy repository into the VM

Run the sync helper from the host repository. It reads the SSH forwarded port
from `~/.lima/INSTANCE/ssh.config`, uses Lima's generated key-based SSH user by
default, installs `rsync` inside the Debian guest if needed, and copies the
full tree into `~/debian-runner`.

```sh
./scripts/sync-to-debian.sh --instance debian-codeql-16g-1
```

### Provision the worker

After syncing the repository, log into the VM and run the provisioner from the
copied tree:

```sh
limactl shell debian-codeql-16g-1
cd ~/debian-runner
sudo sh ./scripts/provision-debian-codeql.sh
```

Or run it directly over SSH:

```sh
limactl shell debian-codeql-16g-1 -- \
  sh -lc 'cd ~/debian-runner && sudo sh ./scripts/provision-debian-codeql.sh'
```

To pin CodeQL:

```sh
sudo CODEQL_VERSION=v2.27.1 sh ./scripts/provision-debian-codeql.sh
```

`CODEQL_VERSION` accepts `v2.27.1`, `2.27.1`, or the full tag
`codeql-bundle-v2.27.1`. Set `FORCE_CODEQL_INSTALL=1` to replace an existing
`/opt/codeql` install.

The provisioner installs:

- `openjdk-21-jre-headless`
- `ca-certificates`
- `curl`
- `git`
- `tar`
- `xz-utils`
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

After `debian-codeql-16g-1` has a synced repository, Java, CodeQL, and a passing
validation run, stop it before cloning. Cloning a stopped VM avoids copying a
live filesystem.

```sh
limactl stop debian-codeql-16g-1
```

Create two additional 16 GiB workers from the validated source and assign each
clone a unique Lima SSH port:

```sh
limactl clone debian-codeql-16g-1 debian-codeql-16g-2 --ssh-port 65393
limactl clone debian-codeql-16g-1 debian-codeql-16g-3 --ssh-port 65394
```

Start all three workers:

```sh
limactl start debian-codeql-16g-1
limactl start debian-codeql-16g-2
limactl start debian-codeql-16g-3
```

Verify that all workers are running on distinct Mac-local SSH ports:

```sh
limactl list
```

Expected worker ports:

```text
debian-codeql-16g-1    127.0.0.1:65392
debian-codeql-16g-2    127.0.0.1:65393
debian-codeql-16g-3    127.0.0.1:65394
```

Spot-check the cloned runtime on each worker:

```sh
for instance in debian-codeql-16g-1 debian-codeql-16g-2 debian-codeql-16g-3; do
  limactl shell "${instance}" -- \
    sh -lc 'java -version 2>&1 | head -1; codeql version | head -1'
done
```

The expected baseline is OpenJDK 21 and CodeQL 2.27.1.

## Regular use

### Remote access from another machine

Lima binds the guest SSH forward to `127.0.0.1` on the Mac host. From another
machine, tunnel through the Mac instead of exposing the VM SSH port to the LAN.

Set the target host and instance on the remote machine:

```sh
export MAC_HOST=m325.local
export INSTANCE=debian-codeql-16g-1
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

Copy the Lima private key once, then connect through the local tunnel as the
Lima user:

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
limactl stop debian-codeql || true
limactl delete debian-codeql
limactl start --name=debian-codeql ./lima/debian-codeql.yaml
```

Then provision and validate again.

### Known caveat

The Debian cloud image satisfies Lima's key-based SSH readiness check on first
boot, so `limactl shell` is available without any manual bootstrap.

Local Linux test note: with `/dev/kvm` present, QEMU starts with
`-cpu host -machine virt,accel=kvm`. Without `/dev/kvm`, Lima starts QEMU with
TCG and is too slow for a useful reference run.

The ARM64 appliance uses the native `codeql-bundle-linux-arm64` asset, so the
former x86_64 `scc` and bundled-JRE compatibility warnings do not apply.
`CODEQL_JAVA_HOME=/usr` remains configured to keep the runtime consistent.

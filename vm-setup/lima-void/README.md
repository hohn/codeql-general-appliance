# Void CodeQL Lima Appliance VM

A reproducible, minimal, headless CodeQL appliance VM running on Void Linux
(glibc, arm64) using Lima.

For detailed setup instructions, troubleshooting, and platform-specific
caveats, see the [void-codeql.md](notes/void-codeql.md) documentation.

## Repository Overview

- **[lima/](lima/)**: Lima configuration profiles for the VM.
   - [void-codeql.yaml](lima/void-codeql.yaml): Default profile.
   - [void-codeql-16g.yaml](lima/void-codeql-16g.yaml): 16 GiB worker profile
     (covers ~80% of databases).
   - [void-codeql-74g.yaml](lima/void-codeql-74g.yaml): 74 GiB worker profile
     (covers ~18% of databases).
   - [void-codeql-128g.yaml](lima/void-codeql-128g.yaml):
     128 GiB worker profile (covers remaining ~2%).
- **[scripts/](scripts/)**: Automation shell scripts.
   - [enable-lima-ssh.sh](scripts/enable-lima-ssh.sh):
     Injects Lima's expected public-key SSH user and live-ISO bootstrap markers
     into the running live VM.
   - [install-void-to-lima-disk.sh](scripts/install-void-to-lima-disk.sh):
     Destructively installs persistent Void Linux onto the temporary builder disk.
   - [sync-to-void.sh](scripts/sync-to-void.sh):
     Synchronizes this repository directory into the installed target VM guest.
   - [provision-void-codeql.sh](scripts/provision-void-codeql.sh):
     Idempotently provisions Java (OpenJDK 21), CodeQL, and core packages on
     the guest.
   - [validate-codeql.sh](scripts/validate-codeql.sh):
     Validates the installation and performs a JavaScript database
     create/analyze smoke test.
   - [20-analyze.sh](scripts/20-analyze.sh):
     CodeQL analysis driver script.
- **[notes/](notes/)**: Documentation and local development checks.
   - [void-codeql.md](notes/void-codeql.md):
     Comprehensive instructions on booting, provisioning, validating, and
     managing the worker VMs.
   - [run-checks.sh](notes/run-checks.sh):
     Runs local formatting, linting (shellcheck, prettier, yamllint,
     markdownlint), and syntax check tools.

## Quick Start Summary

The goal is a persistent CodeQL worker named `void-codeql-16g-installed`.
The stock Void live ISO is only a temporary builder because Void does not
publish a ready-to-boot Lima qcow2 image for this appliance.

### 1. Start the Temporary Builder

Create and start the live-ISO builder instance:

```bash
limactl start --name=void-codeql-16g-1 --timeout=90s --tty=false \
  ./lima/void-codeql-16g.yaml || true
```

The `|| true` is expected: the stock live ISO does not consume Lima's injected
user data, so Lima may time out while the VM keeps running.

### 2. Bootstrap Builder SSH

Enable Lima key-based SSH inside the temporary builder using the live ISO
password `voidlinux`:

```bash
SSHPASS=voidlinux ./scripts/enable-lima-ssh.sh \
  --instance void-codeql-16g-1
```

This step is only for reaching the builder long enough to install Void onto the
Lima disk.

### 3. Install Persistent Void

Install Void onto the builder's blank Lima disk:

```bash
SSHPASS=voidlinux ./scripts/install-void-to-lima-disk.sh \
  --instance void-codeql-16g-1 --disk /dev/vdb --force
```

On native Linux/QEMU, `/dev/vda` is typically the live ISO and `/dev/vdb` is
the 1 TiB Lima disk. If `lsblk` shows a different blank 1 TiB disk, pass that
with `--disk`.

### 4. Create the Installed VM

Stop the temporary builder and create the persistent target VM from the
installed qcow2:

```bash
limactl stop void-codeql-16g-1
limactl create --name=void-codeql-16g-installed --tty=false --ssh-port=65393 \
  --set=".images = [{\"location\":\"file://${HOME}/.lima/void-codeql-16g-1/diffdisk\", \"arch\":\"aarch64\"}] | .provision = []" \
  ./lima/void-codeql-16g.yaml
limactl start void-codeql-16g-installed
```

From this point forward, use `void-codeql-16g-installed`. The builder instance
is no longer part of the worker flow.

### 5. Sync Repository

Sync this codebase into the installed VM:

```bash
./scripts/sync-to-void.sh
```

### 6. Provision CodeQL & Java

Install ARM OpenJDK and the pinned CodeQL bundle inside the installed VM:

```bash
limactl shell void-codeql-16g-installed -- \
  sh -lc 'cd ~/void-runner && sudo sh ./scripts/provision-void-codeql.sh'
```

### 7. Validate VM Installation

Verify Java, CodeQL, and a basic JavaScript database analysis:

```bash
limactl shell void-codeql-16g-installed -- \
  sh -lc 'cd ~/void-runner && sh ./scripts/validate-codeql.sh'
```

## Cloning Workers and LAN Access

Clone the installed VM when you need another worker. Give each clone a unique
Lima SSH port and unique LAN-facing service ports:

```bash
limactl stop void-codeql-16g-installed
limactl clone void-codeql-16g-installed void-codeql-16g-worker-1 \
  --ssh-port=65394 \
  --set='.portForwards = [{"guestPort": 8080, "hostPort": 18094, "hostIP": "0.0.0.0", "guestIP": "0.0.0.0", "guestIPMustBeZero": false}]' \
  --tty=false
limactl start void-codeql-16g-installed
limactl start void-codeql-16g-worker-1
```

Test SSH from `spark-e40c` using Lima's generated SSH configs:

```bash
ssh -F ~/.lima/void-codeql-16g-installed/ssh.config \
  lima-void-codeql-16g-installed 'hostname; id -un'
ssh -F ~/.lima/void-codeql-16g-worker-1/ssh.config \
  lima-void-codeql-16g-worker-1 'hostname; id -un'
```

Lima's SSH control ports are unique, but they bind to `127.0.0.1`. Lima also
rejects `portForwards` for guest port 22, so shell access from another machine
should hop through `spark-e40c`:

```bash
ssh spark-e40c
ssh -F ~/.lima/void-codeql-16g-worker-1/ssh.config \
  lima-void-codeql-16g-worker-1
```

For services running inside a worker, use `portForwards` with `hostIP:
"0.0.0.0"`. The host listener appears when a process inside the guest is
listening on the forwarded guest port. From another host on the local network,
reach the forwarded service through `spark-e40c`:

```text
http://spark-e40c:18094
```

Use a different `hostPort` for each clone and service. For example,
`void-codeql-16g-worker-2` could use `--ssh-port=65395` and `hostPort: 18095`.

## Running Local Integrity Checks

Before pushing commits, run the local linter/formatter script on the host to
check shell scripts, configuration yaml files, and markdown files:

```bash
./notes/run-checks.sh
```

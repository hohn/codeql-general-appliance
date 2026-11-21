# Debian CodeQL Lima Appliance VM

A reproducible, minimal, headless CodeQL appliance VM running on Debian 13
(trixie, glibc, arm64) using Lima.

For detailed setup instructions, troubleshooting, and platform-specific
caveats, see the [debian-codeql.md](notes/debian-codeql.md) documentation.

Debian is a simpler target than the sibling [lima-void](../lima-void) setup:
the Debian cloud image is Lima-ready, so the VM boots straight into a
persistent guest with working key-based SSH and cloud-init. There is no
live-ISO bootstrap and no separate disk-install step.

## Repository Overview

- **[lima/](lima/)**: Lima configuration profiles for the VM.
   - [debian-codeql.yaml](lima/debian-codeql.yaml): Default profile.
   - [debian-codeql-16g.yaml](lima/debian-codeql-16g.yaml): 16 GiB worker profile
     (covers ~80% of databases).
   - [debian-codeql-74g.yaml](lima/debian-codeql-74g.yaml): 74 GiB worker profile
     (covers ~18% of databases).
   - [debian-codeql-128g.yaml](lima/debian-codeql-128g.yaml):
     128 GiB worker profile (covers remaining ~2%).
- **[scripts/](scripts/)**: Automation shell scripts.
   - [sync-to-debian.sh](scripts/sync-to-debian.sh):
     Synchronizes this repository directory into the running VM guest.
   - [provision-debian-codeql.sh](scripts/provision-debian-codeql.sh):
     Idempotently provisions Java (OpenJDK 21), CodeQL, and core packages on
     the guest.
   - [validate-codeql.sh](scripts/validate-codeql.sh):
     Validates the installation and performs a JavaScript database
     create/analyze smoke test.
   - [20-analyze.sh](scripts/20-analyze.sh):
     CodeQL analysis driver script.
- **[notes/](notes/)**: Documentation and local development checks.
   - [debian-codeql.md](notes/debian-codeql.md):
     Comprehensive instructions on booting, provisioning, validating, and
     managing the worker VMs.
   - [run-checks.sh](notes/run-checks.sh):
     Runs local formatting, linting (shellcheck, prettier, yamllint,
     markdownlint), and syntax check tools.

## Quick Start Summary

The goal is a persistent CodeQL worker named `debian-codeql-16g-1`. Because
Debian publishes a Lima-ready cloud image, the worker is persistent from first
boot; there is no temporary builder instance.

### 1. Start the Worker

Create and start the worker instance:

```bash
limactl start --name=debian-codeql-16g-1 --timeout=600s --tty=false \
  ./lima/debian-codeql-16g.yaml
```

The Debian cloud image consumes Lima's injected user data, so key-based SSH and
`limactl shell` work as soon as the instance finishes booting.

### 2. Sync Repository

Sync this codebase into the VM:

```bash
./scripts/sync-to-debian.sh --instance debian-codeql-16g-1
```

### 3. Provision CodeQL & Java

Install OpenJDK and the pinned CodeQL bundle inside the VM:

```bash
limactl shell debian-codeql-16g-1 -- \
  sh -lc 'cd ~/debian-runner && sudo sh ./scripts/provision-debian-codeql.sh'
```

### 4. Validate VM Installation

Verify Java, CodeQL, and a basic JavaScript database analysis:

```bash
limactl shell debian-codeql-16g-1 -- \
  sh -lc 'cd ~/debian-runner && sh ./scripts/validate-codeql.sh'
```

## Cloning Workers and LAN Access

Clone the installed VM when you need another worker. Give each clone a unique
Lima SSH port and unique LAN-facing service ports:

```bash
limactl stop debian-codeql-16g-1
limactl clone debian-codeql-16g-1 debian-codeql-16g-worker-1 \
  --ssh-port=65394 \
  --set='.portForwards = [{"guestPort": 8080, "hostPort": 18094, "hostIP": "0.0.0.0", "guestIP": "0.0.0.0", "guestIPMustBeZero": false}]' \
  --tty=false
limactl start debian-codeql-16g-1
limactl start debian-codeql-16g-worker-1
```

Test SSH from `spark-e40c` using Lima's generated SSH configs:

```bash
ssh -F ~/.lima/debian-codeql-16g-1/ssh.config \
  lima-debian-codeql-16g-1 'hostname; id -un'
ssh -F ~/.lima/debian-codeql-16g-worker-1/ssh.config \
  lima-debian-codeql-16g-worker-1 'hostname; id -un'
```

Lima's SSH control ports are unique, but they bind to `127.0.0.1`. Lima also
rejects `portForwards` for guest port 22, so shell access from another machine
should hop through `spark-e40c`:

```bash
ssh spark-e40c
ssh -F ~/.lima/debian-codeql-16g-worker-1/ssh.config \
  lima-debian-codeql-16g-worker-1
```

For services running inside a worker, use `portForwards` with `hostIP:
"0.0.0.0"`. The host listener appears when a process inside the guest is
listening on the forwarded guest port. From another host on the local network,
reach the forwarded service through `spark-e40c`:

```text
http://spark-e40c:18094
```

Use a different `hostPort` for each clone and service. For example,
`debian-codeql-16g-worker-2` could use `--ssh-port=65395` and `hostPort: 18095`.

## Running Local Integrity Checks

Before pushing commits, run the local linter/formatter script on the host to
check shell scripts, configuration yaml files, and markdown files:

```bash
./notes/run-checks.sh
```

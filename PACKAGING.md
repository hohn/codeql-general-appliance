# Packaging CGA and MRVA for macOS

## Conclusion

CGA and standalone MRVA should be packaged as a Linux appliance, not as a set of
native macOS packages.

A single Mac-side installation command is feasible, but one hypervisor and one
artifact are not appropriate for every user. The product should have three
installation channels backed by the same guest provisioner:

1. a native Parallels `.pvm` graphical workstation for users who already use
   Parallels Desktop;
2. a Homebrew package that installs a headless `cga` launcher and Lima; and
3. a signed standalone macOS installer that bundles the launcher and Lima for
   users who have neither Parallels nor Homebrew.

The Parallels path should not install Lima. The two Lima paths should not
install or require Parallels.

There is an important distinction between one command and one download. One
command can install the launcher, create the VM, and provision the guest, but a
publicly distributed VM image should not contain the CodeQL CLI. The current
[GitHub CodeQL Terms and Conditions](https://github.com/github/codeql-cli-binaries/blob/main/LICENSE.md)
prohibit sharing or distributing the software for others to use. A public
appliance should download CodeQL from GitHub inside the guest after the user
explicitly accepts those terms. An organization may instead publish a complete
image internally if its separate GitHub agreement permits that distribution.

## Installation channels

### Existing Parallels Desktop users

The Parallels artifact should be a complete graphical Linux workstation. Its
users work inside the VM, including its terminal, file manager, browser, and
Wayland/X11 desktop. The host does not need a `cga` command, browser forwarding,
or access to the individual CGA service ports.

Publish two native-architecture disk images, each containing `CGA.pvm`:

```text
CGA-VERSION-parallels-arm64.dmg
CGA-VERSION-parallels-amd64.dmg
```

A DMG preserves the `.pvm` bundle and gives Parallels users a normal Finder
installation without requiring `zstd`, Homebrew, or a terminal.

Do not make x86 emulation on Apple Silicon the normal installation path.
Parallels documents that native ARM guests are supported on Apple Silicon and
native x86 guests on Intel Macs; its x86-on-ARM support is an expensive preview
with additional limitations. The installer or download page must select the
artifact using `uname -m`.

Use a regular `.pvm`, not the Parallels "template" feature. A `.pvm` can be
opened or dragged into Control Center, while Parallels templates require Pro
Edition. A graphical installation is therefore:

1. download and open the architecture-matched DMG;
2. drag `CGA.pvm` to the provided `~/Parallels` alias, then double-click it or
   drag it into Parallels Control Center;
3. select "Copied" if Parallels asks whether the VM was moved or copied;
4. start the VM and complete first-run CodeQL terms acceptance; and
5. use the CGA dashboard and terminal from the browser and desktop inside the
   guest.

Parallels documents both opening a `.pvm` directly and dragging it into Control
Center:
<https://docs.parallels.com/landing/pdfm-ug/parallels-desktop-for-mac-26-users-guide/install-or-import-windows/importing-from-an-earlier-version-of-parallels-desktop-or-another-virtualization-application>.

For managed or command-line installation, an optional small installer can put
the bundle under `~/Parallels` and register it using Parallels' supported CLI:

```sh
prlctl register "$HOME/Parallels/CGA.pvm" --regenerate-src-uuid
prlctl start CGA
```

The `prlctl register` contract is documented at
<https://docs.parallels.com/landing/parallels-desktop-developers-guide/command-line-interface-utility/manage-virtual-machines-from-cli/general-virtual-machine-management/register-unregister-a-virtual-machine>.

The graphical guest should use Debian 12 with GNOME, Wayland by default, an Xorg
fallback session, Firefox ESR or Chromium, a terminal, and Parallels Tools.
Debian 12 is supported by current Parallels releases on both Apple Silicon and
Intel Macs, which permits one OS baseline with two native builds. Current
Parallels system requirements are listed at
<https://kb.parallels.com/en/124223>.

This image has additional desktop-only guest dependencies:

- GNOME and GDM;
- Wayland and Xorg compatibility packages;
- a browser and terminal emulator;
- desktop keyring and secret storage;
- Parallels Tools for display resizing, clipboard, and shared-folder support;
  and
- a desktop shortcut that opens `http://127.0.0.1:8600/`.

The CGA and MRVA services remain bound to guest loopback. No Mac-side port
forwarding is required. A dedicated Parallels shared folder may be offered for
import and export, but the Mac home directory should not be shared wholesale
because analysis build commands execute inside the guest.

### Users with Homebrew

Publish a Homebrew tap formula whose only host runtime dependency is Lima:

```sh
brew install ORG/TAP/cga
cga install --provider=lima --accept-codeql-terms
```

For a literal one-line installation and launch:

```sh
brew install ORG/TAP/cga && cga install --provider=lima --accept-codeql-terms
```

The formula should install only the launcher, Lima dependency, versioned
appliance manifest, and license notices. The multi-gigabyte VM image remains a
release artifact downloaded and checksum-verified by `cga install`; it should
not be embedded in a Homebrew bottle.

The Lima guest is headless. The launcher starts the VM, establishes the required
local forwarding, waits for appliance health, and opens the dashboard in the Mac
browser. Subsequent use is through `cga start`, `cga stop`, `cga status`, and
`cga shell`.

### Users with neither Parallels nor Homebrew

Publish a signed and notarized universal macOS installer:

```text
CGA-Installer-VERSION.pkg
```

The package installs:

- `/Applications/CGA.app`, providing installation, lifecycle, resource, and
  update UI;
- `/usr/local/bin/cga`, exposing the same lifecycle through Terminal; and
- architecture-matched Lima host binaries and guest agents.

It should use Lima with Apple's Virtualization.framework and must not bundle
QEMU. On first launch, `CGA.app` should:

1. detect Apple Silicon or Intel architecture and available memory/disk;
2. let the user choose the VM data location and resource allocation;
3. present the CodeQL terms acceptance step;
4. download the matching versioned appliance image and verify its digest;
5. create and start the Lima VM;
6. provision CodeQL inside the guest; and
7. open the dashboard after its health check passes.

This gives a clean Mac a normal double-click installer without requiring a
package manager or terminal bootstrap. Apple recommends Developer ID signing and
notarization for packages distributed outside the Mac App Store:
<https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution>.

The public installer remains small because it does not contain the guest disk or
CodeQL. An optional architecture-specific offline installer may include the base
guest image for restricted networks, but CodeQL must still be separately
downloaded or supplied under an agreement that permits redistribution.

These installation commands and artifacts are proposed interfaces; they do not
exist yet.

## Why the VM is the correct boundary

The complete workflow already assumes Linux and Debian behavior:

- [`cga/cga-run`](cga/cga-run) uses `setsid` to detach its services.
- [`cga/cgamx/cgamx/infra.py`](cga/cgamx/cgamx/infra.py) uses `ss`, `systemctl`
  or `pg_ctlcluster`, and `sudo -u postgres`.
- [`cga/cgasp/cgasp/cli.py`](cga/cgasp/cgasp/cli.py) uses `dget` and
  `dpkg-source` for Debian source packages.
- [`cga/cgadb/cgadb/cli.py`](cga/cgadb/cgadb/cli.py) runs declared
  dependency commands and traces Linux build commands with CodeQL.
- The checked-in `cgasv` and `cgamu` binaries are currently Linux ELF
  executables, not macOS binaries.

Porting only the fixed tools to Homebrew would not solve the main problem: real
analyses build Debian source packages and may run `apt-get build-dep`. Keeping
that work in a disposable Linux guest also isolates package installs and source
build commands from the Mac host.

## Dependency inventory

### Required guest runtime

The Linux guest needs the following fixed dependencies:

| Area               | Dependencies                                                                                                              | Reason                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Base               | Debian/glibc, Bash, Python 3                                                                                              | Shell launchers and standard-library-only CGA components                |
| MRVA state         | PostgreSQL server and client                                                                                              | Job, worker, scheduler, and result state                                |
| Analysis           | CodeQL bundle and a native Java runtime                                                                                   | Query pack creation, database creation, and analysis                    |
| Build              | Go 1.25 or newer, `make`, compiler toolchain                                                                              | Current `cgamx build`, MRVA binaries, and CGA Go components             |
| Source acquisition | `git`, `devscripts` (`dget`), `dpkg-dev`                                                                                  | Git and Debian `.dsc` source strategies                                 |
| Debian builds      | `build-essential`, enabled `deb-src` repositories                                                                         | `apt-get build-dep` and traced package builds                           |
| SARIF              | `duckdb`, `sqlite3`                                                                                                       | Cumulative SARIF ingestion and inspection                               |
| Utilities          | `curl`, `ca-certificates`, `iproute2`, `lsof`, `procps`, `rsync`, `tar`, `unzip`, `zip`, `xz-utils`, `zstd`, `util-linux` | Health checks, port handling, transfer, archive, and process operations |
| Application        | CGA trees, MRVA server and agent, query samples, and SARIF tools                                                     | The appliance itself                                                    |

Most CGA and CGA preparation Python components do not require PyPI packages. In particular:

- `cgacv`, `cgasp`, `cgadb`, `cgaqg`, `cgadl`, `cgamr`, and `cgaex` use the
  Python standard library.
- `cgaql` uses the standard library and shells out to `codeql` when building a
  query pack.
- `cgasi` uses the repository's `sarif-ingest/bin/srfi` and shells out to the
  DuckDB CLI.
- `cgasv`, `cgamu`, `mrvaserver`, and `mrvaagent` are Go binaries.

The existing Linux installation inventory is in [`INSTALL.md`](INSTALL.md).

### Workload-specific dependencies

There is no finite package list that can satisfy every future CGA analysis.
`cgadb build` deliberately executes the dependency argument arrays carried in
the CVE specification before running `codeql database create`. For example, the
included real zlib specification declares:

```json
["apt-get", "build-dep", "-y", "zlib"]
```

The appliance must therefore retain a working Debian package manager and allow
controlled installation of analysis-specific dependencies. These packages should
not be modeled as Mac dependencies or preinstalled exhaustively.

Package installation also needs an explicit privilege model. The current zlib
specification invokes `apt-get` directly, so either the workflow runs that step
with appropriate guest privileges or dependency installation is moved behind a
small privileged broker. The latter is preferable for a long-running appliance.

### Dependencies that are not required

The standalone path does not require:

- Docker or Docker Desktop;
- Kubernetes or Argo Workflows;
- RabbitMQ;
- HEPC;
- Node.js or Python package environments; or
- MinIO when filesystem artifact storage is selected.

Set:

```sh
MRVA_STANDALONE_STORAGE=filesystem
```

The complete [`cga/system-tests/run-system-09`](cga/system-tests/run-system-09/run)
workflow already uses filesystem storage, proving that the CVE-to-SARIF-to-
export path does not require MinIO. MinIO can remain an optional compatibility
feature for scenarios that explicitly test the object-storage backend.

Go can also be omitted from a strictly runtime-only image if all Go binaries are
built during image production. Keeping Go inside the guest is recommended
initially because `cgamx build`, development, and system tests currently expect
it.

## Recommended appliance design

### Mac host

The headless appliance path should contain only:

- Lima;
- the small `cga` launcher; and
- a web browser already supplied by macOS.

The Parallels path instead requires the user's existing Parallels Desktop
installation and the downloaded `.pvm`; it does not require Lima or a host
launcher.

Homebrew is a convenient Lima installer but is not an architectural requirement.
Lima also publishes standalone macOS archives, which the signed installer can
bundle. Its documented install command is `brew install lima`, and
`limactl start` accepts a local YAML file or remote HTTPS URL:

- <https://lima-vm.io/docs/installation/>
- <https://lima-vm.io/docs/reference/limactl_start/>

### Lima guest

Create a new `vm-setup/lima-cga/` appliance rather than extending the worker
profiles in place. The existing `vm-setup/lima-debian/` profiles are useful
CodeQL worker images and should retain that focused purpose.

The headless CGA appliance template should:

1. Use Debian 13 with glibc. The shared guest provisioner should also support
   the Debian 12 graphical Parallels build.
2. Use `vmType: vz` on macOS so Lima uses Apple's Virtualization.framework
   rather than QEMU. Lima documents VZ as the default macOS driver on supported
   systems: <https://lima-vm.io/docs/config/vmtype/vz/>.
3. Publish architecture-matched ARM64 and x86-64 images. The current Debian
   profiles declare `arch: aarch64` even though they list images for both
   architectures.
4. Disable containerd because the standalone system does not use containers.
5. Forward host ports `8081`, `8500` through `8504`, and `8600` through `8608`
   to the same guest ports for compatibility with the current page. A later
   dashboard gateway can reduce this to one forwarded UI port. PostgreSQL and
   the internal CodeQL database server should not be exposed to the host.
6. Use filesystem artifact storage by default.
7. Start PostgreSQL, MRVA, the CGA fragment servers, and the CGA page inside the
   guest.
8. Persist PostgreSQL, CGAST state, downloaded sources, CodeQL databases, and
   results on the guest disk.
9. Mount only a dedicated import/export directory from the host. Do not mount
   the user's home directory or source checkout writable because analyzed build
   commands are not trusted.

### Image contents

The recommended public image contains:

- the fixed Debian packages;
- DuckDB;
- the application source or release payload;
- prebuilt native Go binaries for the guest architecture;
- systemd units and appliance configuration; and
- license and attribution files for redistributed components.

It excludes CodeQL. On first start, the guest provisioner should:

1. require an explicit CodeQL terms acceptance flag;
2. download a pinned platform-specific CodeQL bundle directly from GitHub;
3. verify the published checksum;
4. install the bundle under `/opt/codeql`;
5. set `CODEQL_JAVA_HOME=/usr` where required; and
6. record the installed bundle version in appliance state.

GitHub recommends using the complete CodeQL bundle so that the CLI, queries, and
libraries remain compatible:
<https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/scan-from-the-command-line/set-up-codeql-cli>.

For an internally licensed, fully prebuilt image, the same build pipeline can
install CodeQL before image publication and omit the first-start download.

### Release artifacts and shared build

One release should publish this matrix:

| Artifact                    | Architecture             | Consumer                                   |
| --------------------------- | ------------------------ | ------------------------------------------ |
| Headless Debian qcow2 image | ARM64                    | Lima on Apple Silicon                      |
| Headless Debian qcow2 image | x86-64                   | Lima on Intel Mac                          |
| Graphical Debian `.pvm` DMG | ARM64                    | Parallels on Apple Silicon                 |
| Graphical Debian `.pvm` DMG | x86-64                   | Parallels on Intel Mac                     |
| Homebrew formula/bottles    | ARM64 and x86-64         | Existing Homebrew users                    |
| Signed universal `.pkg`     | Universal host installer | Macs without a package manager             |
| Release manifest            | Architecture-neutral     | URLs, versions, sizes, and SHA-256 digests |

The VM artifacts should come from one idempotent provisioner with explicit
profiles:

```text
provision-cga-guest --profile=headless
provision-cga-guest --profile=parallels-desktop
```

The common profile installs PostgreSQL, CodeQL prerequisites, Go, DuckDB, MRVA,
and CGA. The Parallels profile adds GNOME, Wayland/Xorg, browser, terminal,
Parallels Tools, desktop launchers, and graphical first-run handling.

Use the existing Debian cloud-image pipeline for Lima. Build `.pvm` artifacts
with Packer and the Parallels-supported plugin; its `parallels-iso` builder can
install a new guest and export PVM format. Packer and Parallels Pro are release
engineering dependencies only, not end-user dependencies:
<https://developer.hashicorp.com/packer/integrations/Parallels/parallels>.

Every VM release must be shut down cleanly and generalized before publication:

- remove build-time SSH credentials, shell history, and package caches;
- regenerate machine ID, SSH host keys, and application instance identity on
  first boot;
- leave PostgreSQL and CGAST state empty;
- ensure no CodeQL payload or accepted-license marker is present in a public
  image; and
- verify the complete workflow independently on both architectures.

## Proposed launcher contract

The host launcher should own VM lifecycle without reproducing guest logic:

```text
cga install     create the headless Lima instance and provision CodeQL
cga start       start the instance and appliance services
cga stop        stop appliance services and the instance
cga status      report VM and service health
cga shell       open a guest shell for diagnostics
cga open        open the dashboard in the default browser
cga import      copy a specification or input into the guest
cga export      copy reports and result data to the host
cga reset       replace runtime state while retaining the installed image
cga uninstall   delete the instance and its persistent data after confirmation
```

`cga start` should be idempotent. The launcher should pin a template and image
version, verify image digests through the Lima template, and avoid executing a
mutable `main` or `latest` template URL.

## Existing repository assets and gaps

The repository already contains much of the needed foundation:

- [`vm-setup/lima-debian/`](vm-setup/lima-debian/) provides Debian Lima
  profiles, a CodeQL provisioner, repository synchronization, and validation.
- [`INSTALL.md`](INSTALL.md) documents the broader Linux dependencies.
- [`cga/cgamx/`](cga/cgamx/) owns the standalone PostgreSQL, artifact store,
  database HTTP server, MRVA server, and agent lifecycle.
- [`cga/system-tests/run-system-09`](cga/system-tests/run-system-09/run) verifies the
  full CGA and MRVA workflow using filesystem storage.

The current Debian VM path is not yet an installable CGA appliance:

- first boot installs only `ca-certificates`, `curl`, and `rsync`;
- the separate provisioner installs Java and CodeQL but not PostgreSQL, DuckDB,
  Go, MRVA, or CGA;
- setup requires separate start, sync, provision, and validation commands;
- the templates use QEMU, fixed ARM64, no application port forwards, and no
  import/export mount; and
- no graphical Debian/Parallels build exists;
- no versioned release image, architecture manifest, Homebrew launcher, or
  signed standalone installer exists.

Before public distribution, the repository also needs an explicit license for
the top-level CGA code and packaging assets. The three imported MRVA Go modules
have Apache-2.0 license files, but `cga/` and the repository root currently do
not have an equivalent license file.

## Implementation sequence

1. Add one idempotent Debian appliance provisioner with common, headless, and
   Parallels desktop profiles.
2. Install the fixed runtime dependencies, Go, DuckDB, PostgreSQL, and the
   application; make filesystem storage the appliance default.
3. Verify `cga/system-tests/run-system-09 all` in both a headless guest and a
   graphical Parallels guest.
4. Add explicit first-start CodeQL terms acceptance, download, checksum
   verification, and version recording in both interfaces.
5. Add a macOS VZ Lima template with architecture-specific images, fixed port
   forwards, a dedicated import/export mount, and digest pins.
6. Add Packer builds for native ARM64 and x86-64 Debian 12 GNOME `.pvm`
   appliances; verify Wayland, Xorg fallback, browser, clipboard, display
   resizing, and restricted shared-folder behavior.
7. Build and compact all four VM artifacts without CodeQL, then publish them
   with one signed release manifest and checksums.
8. Add the headless `cga` lifecycle launcher and test create, start, stop,
   restart, reset, export, and uninstall behavior on a clean Mac.
9. Publish a Homebrew tap formula that installs the launcher and declares Lima
   as its only runtime dependency.
10. Build, Developer ID-sign, notarize, and staple the universal `.pkg` that
    bundles the launcher and Lima.
11. Test the Parallels `.pvm` installation through Control Center using Standard
    Edition, and test managed registration through `prlctl`.
12. Add upgrade and migration tests before treating appliance state as durable
    across image versions.

This design minimizes native Mac dependencies while preserving the Linux and
Debian execution environment that the complete CGA workflow requires.

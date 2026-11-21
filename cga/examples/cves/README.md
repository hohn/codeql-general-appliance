# C/C++ path-problem CVE catalogue

This catalogue contains 60 verified Debian CVEs whose vulnerability class is
represented by an installed CodeQL C/C++ `@kind path-problem` query. Every
sample records vulnerable, fixed, and current Debian source versions and stages
all three source packages without building them.

The machine-readable research result is [`catalogue.json`](catalogue.json).
Regenerate sample metadata with `./generate.py`; download every source set with
`./download-sources.py`.

The large, critical per-CVE `tmp` workspaces live outside Git under
`/mnt/common/home/hohn/work-ghp/single-machine-mrva-artifacts/examples/cves/`.
Each populated sample has an ignored relative `tmp` symlink to its corresponding
external workspace, so existing scripts and documented paths continue to work.
The external artifact root contains content and symlink-target manifests whose
hashes are anchored by `cga/analysis/ARTIFACTS.sha256`.

The shared query files under [`queries/`](queries/) are copied from the
installed CodeQL 2.23.9 C/C++ query pack. Each sample links to its exact query
and records the query ID in `spec.json`.

## Coverage

| CWE     | CVEs |
| ------- | ---: |
| CWE-119 |   11 |
| CWE-120 |    9 |
| CWE-125 |    6 |
| CWE-134 |    4 |
| CWE-190 |   12 |
| CWE-22  |    2 |
| CWE-416 |    8 |
| CWE-787 |    8 |

## Samples

| CVE                                            | Debian source package | CWE     | CodeQL query                |
| ---------------------------------------------- | --------------------- | ------- | --------------------------- |
| [CVE-2021-41773](cve-2021-41773/README.md)     | `apache2`             | CWE-22  | `cpp/path-injection`        |
| [CVE-2023-39810](cve-2023-39810/README.md)     | `busybox`             | CWE-22  | `cpp/path-injection`        |
| [CVE-2023-39616](cve-2023-39616/README.md)     | `aom`                 | CWE-119 | `cpp/overrun-write`         |
| [CVE-2018-19886](cve-2018-19886/README.md)     | `faac`                | CWE-119 | `cpp/overrun-write`         |
| [CVE-2019-15296](cve-2019-15296/README.md)     | `faad2`               | CWE-119 | `cpp/overrun-write`         |
| [CVE-2021-25217](cve-2021-25217/README.md)     | `isc-dhcp`            | CWE-119 | `cpp/overrun-write`         |
| [CVE-2018-1000880](cve-2018-1000880/README.md) | `libarchive`          | CWE-119 | `cpp/overrun-write`         |
| [CVE-2018-12982](cve-2018-12982/README.md)     | `libpodofo`           | CWE-119 | `cpp/overrun-write`         |
| [CVE-2018-20534](cve-2018-20534/README.md)     | `libsolv`             | CWE-119 | `cpp/overrun-write`         |
| [CVE-2019-15945](cve-2019-15945/README.md)     | `opensc`              | CWE-119 | `cpp/overrun-write`         |
| [CVE-2018-20182](cve-2018-20182/README.md)     | `rdesktop`            | CWE-119 | `cpp/overrun-write`         |
| [CVE-2018-12326](cve-2018-12326/README.md)     | `redis`               | CWE-119 | `cpp/overrun-write`         |
| [CVE-2018-17540](cve-2018-17540/README.md)     | `strongswan`          | CWE-119 | `cpp/overrun-write`         |
| [CVE-2020-21531](cve-2020-21531/README.md)     | `fig2dev`             | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2020-23109](cve-2020-23109/README.md)     | `libheif`             | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2023-26767](cve-2023-26767/README.md)     | `liblouis`            | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2023-24809](cve-2023-24809/README.md)     | `nethack`             | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2020-27823](cve-2020-27823/README.md)     | `openjpeg2`           | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2020-8597](cve-2020-8597/README.md)       | `ppp`                 | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2020-25756](cve-2020-25756/README.md)     | `swupdate`            | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2021-43518](cve-2021-43518/README.md)     | `teeworlds`           | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2020-8955](cve-2020-8955/README.md)       | `weechat`             | CWE-120 | `cpp/unbounded-write`       |
| [CVE-2024-20290](cve-2024-20290/README.md)     | `clamav`              | CWE-125 | `cpp/invalid-pointer-deref` |
| [CVE-2021-34121](cve-2021-34121/README.md)     | `htmldoc`             | CWE-125 | `cpp/invalid-pointer-deref` |
| [CVE-2023-30362](cve-2023-30362/README.md)     | `libcoap3`            | CWE-125 | `cpp/invalid-pointer-deref` |
| [CVE-2022-46393](cve-2022-46393/README.md)     | `mbedtls`             | CWE-125 | `cpp/invalid-pointer-deref` |
| [CVE-2023-1916](cve-2023-1916/README.md)       | `tiff`                | CWE-125 | `cpp/invalid-pointer-deref` |
| [CVE-2022-43280](cve-2022-43280/README.md)     | `wabt`                | CWE-125 | `cpp/invalid-pointer-deref` |
| [CVE-2018-1000052](cve-2018-1000052/README.md) | `fmtlib`              | CWE-134 | `cpp/tainted-format-string` |
| [CVE-2018-5205](cve-2018-5205/README.md)       | `irssi`               | CWE-134 | `cpp/tainted-format-string` |
| [CVE-2018-16554](cve-2018-16554/README.md)     | `jhead`               | CWE-134 | `cpp/tainted-format-string` |
| [CVE-2018-17336](cve-2018-17336/README.md)     | `udisks2`             | CWE-134 | `cpp/tainted-format-string` |
| [CVE-2020-28009](cve-2020-28009/README.md)     | `exim4`               | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2021-3410](cve-2021-3410/README.md)       | `libcaca`             | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2020-0181](cve-2020-0181/README.md)       | `libexif`             | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2018-10887](cve-2018-10887/README.md)     | `libgit2`             | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2018-13785](cve-2018-13785/README.md)     | `libpng1.6`           | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2019-13115](cve-2019-13115/README.md)     | `libssh2`             | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2020-14401](cve-2020-14401/README.md)     | `libvncserver`        | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2019-11072](cve-2019-11072/README.md)     | `lighttpd`            | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2018-1000127](cve-2018-1000127/README.md) | `memcached`           | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2019-9959](cve-2019-9959/README.md)       | `poppler`             | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2019-5052](cve-2019-5052/README.md)       | `sdl-image1.2`        | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2021-31807](cve-2021-31807/README.md)     | `squid`               | CWE-190 | `cpp/tainted-arithmetic`    |
| [CVE-2024-23310](cve-2024-23310/README.md)     | `biosig`              | CWE-416 | `cpp/use-after-free`        |
| [CVE-2026-10536](cve-2026-10536/README.md)     | `curl`                | CWE-416 | `cpp/use-after-free`        |
| [CVE-2024-25062](cve-2024-25062/README.md)     | `libxml2`             | CWE-416 | `cpp/use-after-free`        |
| [CVE-2021-33796](cve-2021-33796/README.md)     | `mujs`                | CWE-416 | `cpp/use-after-free`        |
| [CVE-2020-18780](cve-2020-18780/README.md)     | `nasm`                | CWE-416 | `cpp/use-after-free`        |
| [CVE-2024-24990](cve-2024-24990/README.md)     | `nginx`               | CWE-416 | `cpp/use-after-free`        |
| [CVE-2024-0232](cve-2024-0232/README.md)       | `sqlite3`             | CWE-416 | `cpp/use-after-free`        |
| [CVE-2025-9385](cve-2025-9385/README.md)       | `tcpreplay`           | CWE-416 | `cpp/use-after-free`        |
| [CVE-2025-2151](cve-2025-2151/README.md)       | `assimp`              | CWE-787 | `cpp/invalid-pointer-deref` |
| [CVE-2024-45993](cve-2024-45993/README.md)     | `giflib`              | CWE-787 | `cpp/invalid-pointer-deref` |
| [CVE-2024-10918](cve-2024-10918/README.md)     | `libmodbus`           | CWE-787 | `cpp/invalid-pointer-deref` |
| [CVE-2026-44637](cve-2026-44637/README.md)     | `libsixel`            | CWE-787 | `cpp/invalid-pointer-deref` |
| [CVE-2025-7207](cve-2025-7207/README.md)       | `mruby`               | CWE-787 | `cpp/invalid-pointer-deref` |
| [CVE-2024-7538](cve-2024-7538/README.md)       | `ofono`               | CWE-787 | `cpp/invalid-pointer-deref` |
| [CVE-2024-55192](cve-2024-55192/README.md)     | `openimageio`         | CWE-787 | `cpp/invalid-pointer-deref` |
| [CVE-2026-0819](cve-2026-0819/README.md)       | `wolfssl`             | CWE-787 | `cpp/invalid-pointer-deref` |

## Existing location-only baseline

The earlier [CVE-2016-9843](cve-2016-9843/README.md) example is retained for
comparison. Its query identifies a review location rather than a source-to-sink
path, so it is not counted in the path-problem catalogue above.

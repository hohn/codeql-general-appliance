# Environment notes

Read for host setup or toolchain failures, not for every repository task.
Repository paths below are relative to the repository root.

- [INSTALL.md](../INSTALL.md) is the canonical dependency guide. The
  `vm-setup/debian-sid/` and `vm-setup/ubuntu-noble/` installers describe their
  host-specific package and cached-tool choices. Their `--list` mode is
  non-mutating. Keep inventories aligned with `INSTALL.md`.
- CodeQL 2.27.1 has a native Linux ARM64 bundle. Keep `CODEQL_JAVA_HOME=/usr`
  for the repository's host-Java runtime. Older x86_64/CodeQL 2.23.9 study
  inputs are distinct experimental inputs; do not replace their pinned
  toolchains without checking provenance.
- Host package installation may be unavailable under Linux `NoNewPrivs`; use an
  appropriate external administrative shell rather than changing agent
  permission controls.
- Fedora localhost PostgreSQL may default to `ident`. TCP connections need
  scoped authentication rules matching the configured database and role. Check
  the host configuration rather than assuming a harness password works.
- Git identity may need to be supplied explicitly on this development host:
  `git -c user.name="michael hohn" -c user.email="mhhohn@gmail.com" commit ...`.
  Include the required Copilot commit trailers.
- This repository does not use Git LFS. Generated databases and large captured
  payloads belong in external artifact storage; do not add LFS hooks.
- `.stfolder/` is an ignored Syncthing artifact, not repository material.
- Use [remote access instructions](../REMOTE-CONNECTION.md) for browser/editor
  port forwarding. Forward matching local/remote ports when the viewer contract
  requires it; do not assume one forwarded dashboard port exposes every
  component.

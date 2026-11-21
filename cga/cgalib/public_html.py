"""Prepare an independent documentation clone and print operator setup steps."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import subprocess
import sys
from urllib.parse import quote

from command_help import enhance_parser


ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ("index.html", "docs/cga-overview.html", "docs/cga-help.html")


def parser():
    result = argparse.ArgumentParser(prog="cga public-html")
    actions = result.add_subparsers(dest="action", required=True)
    actions.add_parser("setup")
    return enhance_parser(result, "public-html")


def clone(source: Path, destination: Path) -> None:
    if destination.is_symlink():
        raise ValueError(f"publication must be a separate checkout, not a symlink: {destination}")
    if destination.exists() and (
            not destination.is_dir() or any(destination.iterdir())):
        result = subprocess.run(
            ["git", "-C", str(destination), "rev-parse", "--show-toplevel"],
            check=True, capture_output=True, text=True,
        )
        if Path(result.stdout.strip()).resolve() != destination.resolve():
            raise ValueError(f"publication is not a Git checkout root: {destination}")
        if not all((destination / name).is_file() for name in DOCUMENTS):
            raise ValueError(f"existing checkout lacks pre-rendered CGA documentation: {destination}")
        print(f"cga public-html: reusing {destination}; no fetch, pull, or reset", file=sys.stderr)
        return
    destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--no-hardlinks", "--single-branch", "--",
         str(source), str(destination)],
        check=True, stdout=sys.stderr, stderr=sys.stderr, umask=0o022,
    )
    if not all((destination / name).is_file() for name in DOCUMENTS):
        raise ValueError(f"cloned HEAD lacks pre-rendered CGA documentation: {destination}")


def script(source: Path, home: Path, destination: Path, username: str) -> str:
    public = destination.parent
    prefix = f"/~{quote(username, safe='')}/"
    configuration = (source / "docs/lighttpd-public-html.conf").read_text()
    settings = {
        "var.cga-public-html-url": prefix,
        "var.cga-public-html-directory": str(public) + "/",
    }
    for name, value in settings.items():
        configuration, count = re.subn(
            rf"(?m)^{re.escape(name)} = .*$",
            lambda _match: f"{name} = {json.dumps(value, ensure_ascii=False)}",
            configuration,
        )
        if count != 1:
            raise ValueError(f"lighttpd template needs exactly one {name} assignment")
    url = f"http://127.0.0.1{prefix}{quote(destination.name, safe='')}/"
    return f"""#!/usr/bin/env bash
# Extra steps for a Debian/lighttpd documentation site. Review before running.
# cga public-html setup created/reused the clone; none of these steps were run.
# Prerequisites: make, mdBook, curl, lighttpd, acl (setfacl), and sudo.
# If missing: sudo apt-get install make mdbook curl lighttpd acl
# For Apache or another server, adapt the alias and access rules instead.
set -euo pipefail
umask 022

home={shlex.quote(str(home))}
public_html={shlex.quote(str(public))}
publication={shlex.quote(str(destination))}
url={shlex.quote(url)}
site_config=/etc/lighttpd/conf-available/50-cga-public-html.conf
config_tmp=$(mktemp)
trap 'rm -f -- "$config_tmp"' EXIT

# Scoped alias: HTML/README indexes, read-only requests, no symlink traversal,
# no Git/runtime metadata, and plain-text Markdown/Org for LLMs.
# Directory listings must remain disabled (Debian's default).
cat > "$config_tmp" <<'CGA_LIGHTTPD'
{configuration.rstrip()}
CGA_LIGHTTPD

# Never replace existing operator configuration without a manual review.
if {{ [ -e "$site_config" ] || [ -L "$site_config" ]; }} && ! sudo cmp -s "$config_tmp" "$site_config"; then
  printf 'Existing configuration differs: %s\\nReview and merge the configuration above before proceeding.\\n' "$site_config" >&2
  exit 1
fi

# Build the optional reference manual. Checked-in overview/help need no build.
make -C "$publication/docs" book

# Keep the home private: only the web account gains traversal/read access.
setfacl -m u:www-data:--x "$home"
setfacl -m u:www-data:r-x "$public_html"
# Skip Git metadata and symlinks; never grant access to external link targets.
find "$publication" -name .git -prune -o \\
  \\( -type d -o -type f \\) -exec setfacl -m u:www-data:rX {{}} +
setfacl -m u:www-data:--- "$publication/.git"

# Install only when absent; matching configurations and symlinks stay intact.
if [ ! -e "$site_config" ]; then
  sudo install -m 0644 "$config_tmp" "$site_config"
fi
# Validate before reloading or starting the server.
sudo lighty-enable-mod cga-public-html
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
# Reload a running lighttpd, or start it if inactive; leave other servers alone.
sudo systemctl reload-or-restart lighttpd

# Expect an entry page, but no readable Git metadata.
curl --fail --silent --show-error --retry 5 --retry-connrefused --head "$url"
for path in .git/config docs/src/; do
  status=$(curl --silent --show-error --output /dev/null \\
    --write-out '%{{http_code}}' "${{url}}${{path}}")
  if [ "$status" != 403 ]; then
    printf 'Expected HTTP 403 for %s, got %s\\n' "$path" "$status" >&2
    exit 1
  fi
done
# Open the URL in a browser too: its HTML redirect is not followed by curl.
# Replace 127.0.0.1 with the VM hostname for a remote browser; no tunnel needed.
# Updates are explicit, not performed by setup:
# git -C "$publication" pull --ff-only
# make -C "$publication/docs" book
"""


def main(argv=None):
    parser().parse_args(argv)
    home = Path.home().resolve()
    destination = (home / "public_html" / "single-machine-mrva").resolve()
    try:
        if (home / "public_html" / "single-machine-mrva").is_symlink():
            raise ValueError("publication must not be a symlink to another checkout")
        if (ROOT.resolve().is_relative_to(destination.parent)
                or destination.parent.is_relative_to(ROOT.resolve())):
            raise ValueError("public_html and the installed checkout must be separate directories")
        rendered = script(ROOT, home, destination, pwd.getpwuid(os.getuid()).pw_name)
        clone(ROOT, destination)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else None
        print(f"cga public-html: {detail.strip() if detail else error}", file=sys.stderr)
        return 1
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

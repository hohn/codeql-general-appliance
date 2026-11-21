"""Prepare GitHub Pages publishing without changing remote configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from command_help import enhance_parser


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs"))

from github_pages import github_repository


WORKFLOW = Path(".github/workflows/documentation.yml")


def workflow(branch: str) -> str:
    return """\
name: Documentation

on:
  push:
    branches: BRANCHES
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: github-pages
  cancel-in-progress: false

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - uses: actions/configure-pages@v5
      - name: Install reference book builder
        run: cargo install mdbook --version 0.5.4 --locked
      - name: Build and check documentation
        run: python3 docs/github_pages.py --output "$RUNNER_TEMP/cga-pages"
      # upload-pages-artifact excludes dot directories, including our public
      # .agent-notes documentation. Archive the filtered site explicitly.
      - name: Package documentation
        run: tar -C "$RUNNER_TEMP/cga-pages" -cf "$RUNNER_TEMP/artifact.tar" .
      - uses: actions/upload-artifact@v4
        with:
          name: github-pages
          path: ${{ runner.temp }}/artifact.tar
          if-no-files-found: error
      - name: Deploy documentation
        id: deployment
        uses: actions/deploy-pages@v4
""".replace("BRANCHES", json.dumps([branch]))


def setup(root: Path) -> str:
    repository = github_repository(root)
    branch = subprocess.check_output(
        ["git", "-C", str(root), "symbolic-ref", "--short", "HEAD"],
        text=True, stderr=subprocess.PIPE,
    ).strip()
    destination = root / WORKFLOW
    for path in (root / ".github", destination.parent, destination):
        if path.is_symlink():
            raise ValueError(f"refusing a symlink at {path}")
    rendered = workflow(branch)
    if destination.exists():
        if not destination.is_file() or destination.read_text() != rendered:
            raise ValueError(f"existing configuration differs: {destination}; review and merge manually")
        print(f"cga github.io: reusing {destination}", file=sys.stderr)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x") as output:
            output.write(rendered)
        print(f"cga github.io: created {destination}", file=sys.stderr)
    owner, name = repository.split("/")
    url = f"https://{owner}.github.io/"
    if name.lower() != f"{owner}.github.io".lower():
        url += f"{name}/"
    return f"""\
GitHub Pages documentation: {url}

Prepared: {WORKFLOW}
Publisher: docs/github_pages.py

1. Review and commit the setup implementation, documentation, and workflow.
   Push only {branch}; do not push private branches or tags.
2. Open https://github.com/{repository}/settings/pages
   Under Build and deployment, set Source to GitHub Actions.
3. Open https://github.com/{repository}/actions/workflows/documentation.yml
   Choose Run workflow, select {branch}, then Run workflow.
   Later pushes to {branch} publish automatically.
   If a push ran before Pages was enabled, rerun the workflow after step 2.

The workflow uses the github-pages environment and a short-lived GitHub token;
no personal access token, custom domain, Jekyll, or running CGA service is needed.
If environment protection rules restrict deployment branches, allow {branch}.
The site opens Overview, then Help, then the built Reference manual.

Optional local check (choose an absent or empty output directory):
  python3 docs/github_pages.py --output /tmp/cga-pages

Setup changed local configuration only. It did not build, commit, push, change
GitHub settings, or deploy the site.
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cga github.io")
    parser.add_subparsers(dest="action", required=True).add_parser("setup")
    enhance_parser(parser, "github.io").parse_args(argv)
    try:
        instructions = setup(ROOT)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else None
        print(f"cga github.io: {detail.strip() if detail else error}", file=sys.stderr)
        return 1
    print(instructions, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

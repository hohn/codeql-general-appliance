#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

usage() {
	cat << 'EOF'
Usage: notes/run-checks.sh [options]

Run the local lint, format, syntax, and lightweight runtime checks for this
handoff repository.

Options:
  -h, --help      Show this help text.
  --skip-network  Skip the CodeQL bundle release URL HEAD checks.

Expected tools:
  shellcheck shfmt prettier yamllint markdownlint mdl python3
  curl bash sh rsync

Optional tools:
  limactl        Validates all lima/*.yaml profiles when installed.

Install hints for this Ubuntu VM:
  sudo apt-get install -y shfmt yamllint ruby-mdl
  sudo npm install -g prettier markdownlint-cli

Notes:
  - apt package "markdownlint" installs Ruby mdl-style markdownlint; npm
    package "markdownlint-cli" provides the markdownlint command used here.
    - The network check verifies that the pinned CodeQL bundle archive and
    checksum URLs resolve; it does not download the archive.
EOF
}

log() {
	printf '\n==> %s\n' "$*"
}

need_cmd() {
	command -v "$1" > /dev/null 2>&1 || {
		printf 'missing required command: %s\n' "$1" >&2
		return 1
	}
}

skip_network=0

while (($# > 0)); do
	case "$1" in
		-h | --help)
			usage
			exit 0
			;;
		--skip-network)
			skip_network=1
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
	shift
done

cd "${ROOT_DIR}"

for cmd in shellcheck shfmt prettier yamllint markdownlint mdl python3 curl bash sh rsync; do
	need_cmd "${cmd}"
done

markdown_files=()
for file in README.md handoff.md notes/debian-codeql.md; do
	if [[ -f "${file}" ]]; then
		markdown_files+=("${file}")
	fi
done

log "ShellCheck"
shellcheck --enable=all -x -S style \
	scripts/provision-debian-codeql.sh \
	scripts/sync-to-debian.sh \
	scripts/validate-codeql.sh \
	notes/run-checks.sh
shellcheck -x -S style scripts/*.sh notes/run-checks.sh

log "Shell syntax and bashisms"
sh -n scripts/provision-debian-codeql.sh scripts/validate-codeql.sh
bash -n scripts/20-analyze.sh

log "Format checks"
shfmt -d -i 0 -ci -sr \
	scripts/provision-debian-codeql.sh \
	scripts/sync-to-debian.sh \
	scripts/validate-codeql.sh \
	scripts/20-analyze.sh \
	notes/run-checks.sh
prettier --check \
	"${markdown_files[@]}" \
	lima/*.yaml \
	../.markdownlint.yaml \
	../.prettierrc.yaml
prettier --check --parser yaml ../.yamllint

log "YAML and Markdown linters"
yamllint -s \
	lima/*.yaml \
	../.markdownlint.yaml \
	../.prettierrc.yaml \
	../.yamllint
markdownlint -c ../.markdownlint.yaml "${markdown_files[@]}"
mdl --style ../.mdl-style.rb "${markdown_files[@]}"

if command -v limactl > /dev/null 2>&1; then
	log "Lima YAML validation"
	for yaml in lima/*.yaml; do
		limactl validate "${yaml}"
	done
fi

log "YAML parse and Markdown shell blocks"
python3 - << 'PY'
from pathlib import Path
import subprocess
import tempfile
import yaml

yaml_paths = list(Path("lima").glob("*.yaml")) + [
    Path("../.markdownlint.yaml"),
    Path("../.prettierrc.yaml"),
    Path("../.yamllint"),
]

for path in yaml_paths:
    with path.open() as f:
        yaml.safe_load(f)
    print(f"YAML OK: {path}")

markdown_paths = [path for path in [Path("README.md"), Path("handoff.md")] if path.exists()]
markdown_paths.extend(Path("notes").glob("*.md"))

for md in markdown_paths:
    text = md.read_text()
    blocks = []
    in_block = False
    lang = ""
    buf = []

    for line in text.splitlines():
        if not in_block and line.startswith("```"):
            lang = line[3:].strip()
            in_block = True
            buf = []
        elif in_block and line.startswith("```"):
            if lang in {"sh", "bash"}:
                blocks.append("\n".join(buf) + "\n")
            in_block = False
        elif in_block:
            buf.append(line)

    for i, block in enumerate(blocks, 1):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sh") as f:
            f.write(block)
            name = f.name
        result = subprocess.run(["sh", "-n", name], text=True, capture_output=True)
        if result.returncode:
            raise SystemExit(f"{md} shell block {i} failed:\n{result.stderr}")

    print(f"Markdown shell blocks OK: {md} ({len(blocks)} blocks)")
PY

log "Script help"
scripts/validate-codeql.sh --help > /tmp/validate-codeql-help.txt
scripts/sync-to-debian.sh --help > /tmp/sync-to-debian-help.txt
bash scripts/20-analyze.sh --help > /tmp/20-analyze-help.txt
wc -l \
	/tmp/validate-codeql-help.txt \
	/tmp/sync-to-debian-help.txt \
	/tmp/20-analyze-help.txt

if [[ "${skip_network}" -eq 0 ]]; then
	log "CodeQL bundle release URL checks"
	tag="codeql-bundle-v2.27.1"
	case "$(uname -m)" in
		aarch64 | arm64) asset="codeql-bundle-linux-arm64.tar.gz" ;;
		*) asset="codeql-bundle-linux64.tar.gz" ;;
	esac
	curl -fsSI \
		"https://github.com/github/codeql-action/releases/download/${tag}/${asset}" \
		> /dev/null
	curl -fsSI \
		"https://github.com/github/codeql-action/releases/download/${tag}/${asset}.checksum.txt" \
		> /dev/null
	printf 'CodeQL URL checks OK: %s\n' "${tag}"
fi

log "All checks passed"

.PHONY: all clean msla standalone mrvaserver mrvaagent

all: msla

msla:
	GOOS=linux GOARCH=arm64 go build

mrvaserver:
	go build

# Build the agent binary that LocalArgoClient spawns in standalone mode.
# Named to match the binary it produces, mirroring the `mrvaserver` target.
mrvaagent:
	cd $(AGENT_DIR) && go build

# ----------------------------------------------------------------------
# Standalone (no Docker) dev mode.
#
# Brings up the server against a host Postgres, with filesystem-backed
# artifact and CodeQL DB stores, spawning agent-commander-argo as local
# subprocesses (LocalArgoClient).
#
# Required env vars (set them in your shell or override on the command
# line, e.g. `make standalone POSTGRES_DB=mrvadev`):
#   POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB
#   MRVA_ARTIFACT_DIR   (where artifacts persist)
#   MRVA_QLDB_DIR       (root of the CodeQL DB store)
#
# Defaults provided below match a typical `brew install postgresql@14`
# layout. Override any of them on the command line.
# ----------------------------------------------------------------------

# Host Postgres defaults.
POSTGRES_HOST     ?= localhost
POSTGRES_PORT     ?= 5432
POSTGRES_USER     ?= $(USER)
POSTGRES_PASSWORD ?=
POSTGRES_DB       ?= mrvadev

# Filesystem store locations.
MRVA_WORK_DIR     ?= /tmp/mrva-standalone
MRVA_ARTIFACT_DIR ?= $(MRVA_WORK_DIR)/artifacts
MRVA_QLDB_DIR     ?= $(MRVA_WORK_DIR)/qldbs

# Path to the built agent binary that LocalArgoClient will spawn.
AGENT_DIR    ?= $(CURDIR)/../agent-commander-argo
AGENT_BINARY ?= $(AGENT_DIR)/mrvaagent

# Path to the codeql CLI binary the agent invokes. Override e.g. via
# `make standalone CODEQL_CLI_PATH=/path/to/codeql`.
CODEQL_CLI_PATH ?= $(shell which codeql)

standalone: mrvaserver mrvaagent
	mkdir -p $(MRVA_ARTIFACT_DIR) $(MRVA_QLDB_DIR)
	POSTGRES_HOST=$(POSTGRES_HOST) \
	POSTGRES_PORT=$(POSTGRES_PORT) \
	POSTGRES_USER=$(POSTGRES_USER) \
	POSTGRES_PASSWORD="$(POSTGRES_PASSWORD)" \
	POSTGRES_DB=$(POSTGRES_DB) \
	MRVA_ARTIFACT_DIR=$(MRVA_ARTIFACT_DIR) \
	MRVA_QLDB_DIR=$(MRVA_QLDB_DIR) \
	MRVA_STANDALONE=true \
	MRVA_ENVSIM_AGENT_BINARY=$(AGENT_BINARY) \
	CODEQL_CLI_PATH=$(CODEQL_CLI_PATH) \
	./mrvaserver --mode=standalone --loglevel=info --dbpath=$(MRVA_QLDB_DIR)

clean:
	rm -f mrvaserver $(AGENT_BINARY)


# ----------------------------------------------------------------------
# Pretty-print all Markdown files in this directory tree with prettier.
# Uses the repo-wide convention: reflow prose to 80 columns.
# System-wide install: npm install -g prettier
# ----------------------------------------------------------------------
.PHONY: pretty
pretty:
	@command -v prettier >/dev/null 2>&1 || { echo "prettier not found; install with: npm install -g prettier"; exit 1; }
	@files=`find . -name '*.md' -not -path '*/node_modules/*' -not -path '*/.git/*'`; \
	if [ -n "$$files" ]; then \
		echo "$$files" | xargs prettier --prose-wrap always --print-width 80 --write; \
	else \
		echo "no Markdown files under $(CURDIR)"; \
	fi

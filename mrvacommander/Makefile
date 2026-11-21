.PHONY: all server agent fullbuild view

all:
	go build ./...

view: README.html
	open $<

html: README.html

%.html: %.md ../docs/Makefile ../docs/readme-layout.css ../docs/readme-fonts.py
	$(MAKE) -C ../docs ../mrvacommander/$@

# Build the qldbtools container image
dbt: mk.client-qldbtools-container
mk.client-qldbtools-container:
	cd client/containers/qldbtools && \
		docker build -t client-qldbtools-container:0.1.24 .
	touch $@

# Run a shell in the container with the qldbtools
dbt-run: mk.client-qldbtools-container
	docker run --rm -it client-qldbtools-container:0.1.24 /bin/bash

# Run one of the scripts in the container as check
dbt-check: mk.client-qldbtools-container
	docker run --rm -it client-qldbtools-container:0.1.24 mc-db-initial-info

dbt-push: mk.dbt-push
mk.dbt-push: mk.client-qldbtools-container
	docker tag client-qldbtools-container:0.1.24 ghcr.io/hohn/client-qldbtools-container:0.1.24 
	docker push ghcr.io/hohn/client-qldbtools-container:0.1.24
	touch $@

server:
	$(MAKE) -C ../server-commander

agent:
	$(MAKE) -C ../agent-commander-argo

fullbuild:
	go build -a ./...

sendsubmit:
	cd tools && sh ./submit-request.curl

# Requires
#		go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
lint:
	golangci-lint run ./...

deps:
	godepgraph -maxlevel 4 -nostdlib  -i github.com/minio/minio-go ./cmd/server | dot -Tpdf > deps-server.pdf && open deps-server.pdf

depa:
	godepgraph -maxlevel 4 -nostdlib  -i github.com/minio/minio-go ./cmd/agent | dot -Tpdf > deps-agent.pdf && open deps-agent.pdf

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

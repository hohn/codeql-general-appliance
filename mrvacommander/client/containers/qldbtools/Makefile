DBT_TARGET := client-qldbtools-container:0.1.24

# Build the qldbtools container image
dbt: mk.client-qldbtools-container
mk.client-qldbtools-container:
	docker build -t ${DBT_TARGET} .
	touch $@

# Run a shell in the container with the qldbtools
dbt-run: dbt
	docker run --rm -it ${DBT_TARGET} /bin/bash

# Run one of the scripts in the container as check.  Should exit with error. 
dbt-check: dbt
	docker run --rm -it ${DBT_TARGET} mc-db-initial-info

dbt-push: mk.dbt-push
mk.dbt-push: dbt
	docker tag ${DBT_TARGET} ghcr.io/hohn/${DBT_TARGET} 
	docker push ghcr.io/hohn/${DBT_TARGET}
	touch $@

dbt-test:
	docker pull ghcr.io/hohn/${DBT_TARGET}
	docker run --rm -it --name test-dbt-server ghcr.io/hohn/${DBT_TARGET} sh

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

ghm: mk.client-ghmrva-container
mk.client-ghmrva-container:
	docker build -t client-ghmrva-container:0.1.24 .
	touch $@

ghm-push: mk.ghm-push
mk.ghm-push: mk.client-ghmrva-container
	docker tag client-ghmrva-container:0.1.24 ghcr.io/hohn/client-ghmrva-container:0.1.24 
	docker push ghcr.io/hohn/client-ghmrva-container:0.1.24 
	touch $@

ghm-run:
	docker run --rm -it ghcr.io/hohn/client-ghmrva-container:0.1.24 /bin/bash

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

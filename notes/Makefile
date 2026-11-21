PANDOC ?= pandoc
PDF_ENGINE ?= lualatex
PRETTIER ?= prettier
MDBOOK ?= mdbook

SOURCE := d547859-stale-job-status.md
HTML := $(SOURCE:.md=.html)
PDF := $(SOURCE:.md=.pdf)
MD_FILES := $(wildcard *.md) src/SUMMARY.md

HTML_TITLE := d547859 stale job_status rows
PRETTIER_FLAGS := --prose-wrap always --print-width 80

.PHONY: all render html pdf book view-book clean pretty

# Rendered notes are checked in. Keep repository-wide `make all` free of
# optional Pandoc, TeX, and font dependencies; rebuild them explicitly.
all:
	@echo "notes: run 'make book' to build the notes book or 'make render' to rebuild checked-in HTML and PDF"

render: html pdf

html: $(HTML)

pdf: $(PDF)

# Render the standalone notes book to book/ without changing the checked-in
# Pandoc HTML and PDF artifacts.
book:
	@command -v $(MDBOOK) >/dev/null 2>&1 || { echo "$(MDBOOK) not found; install it (e.g. 'cargo install mdbook' or your package manager)"; exit 1; }
	$(MDBOOK) build

# Build and serve with live reload, opening a browser at
# http://localhost:3000 (or the next available port).
view-book:
	@command -v $(MDBOOK) >/dev/null 2>&1 || { echo "$(MDBOOK) not found; install it (e.g. 'cargo install mdbook' or your package manager)"; exit 1; }
	$(MDBOOK) serve --open

clean:
	rm -rf book

$(HTML): $(SOURCE) Makefile ../docs/Makefile ../docs/readme-layout.css ../docs/readme-fonts.py
	$(MAKE) -C ../docs ../notes/$@ PANDOC="$(PANDOC)"

# PDF rendering requires lualatex and the TeX libertinus package.
$(PDF): $(SOURCE) Makefile
	@command -v $(PANDOC) >/dev/null 2>&1 || { echo "$(PANDOC) not found"; exit 1; }
	@command -v $(PDF_ENGINE) >/dev/null 2>&1 || { echo "$(PDF_ENGINE) not found"; exit 1; }
	$(PANDOC) -s \
		--pdf-engine=$(PDF_ENGINE) \
		-V geometry:margin=1in \
		-V fontsize=11pt \
		-V 'header-includes=\usepackage{libertinus}' \
		$< -o $@

pretty:
	@command -v $(PRETTIER) >/dev/null 2>&1 || { echo "$(PRETTIER) not found"; exit 1; }
	$(PRETTIER) $(PRETTIER_FLAGS) --write $(MD_FILES)

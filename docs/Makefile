# Documentation (mdBook).
#
# The book assembles the per-component READMEs in place via symlinks under
# src/ (see README.md); it never copies or modifies them. Build output lands
# in book/ (gitignored).

MDBOOK ?= mdbook
PANDOC ?= pandoc
CGA ?= ../cga/cga

MARKDOWN_SOURCES := $(addprefix ../,$(filter-out docs/src/% notes/src/%,$(sort $(shell git -C .. ls-files --cached --others --exclude-standard -- '*.md'))))
MARKDOWN_HTML := $(MARKDOWN_SOURCES:.md=.html)
README_HTML := $(filter %/README.html,$(MARKDOWN_HTML))
CGA_REFERENCE_HTML := ../cga/README.html ../cga/cgauv/README.html ../cga/cgabench/README.html
HTML_FONTS := --variable mainfont=Synonym --variable monofont="CMU Typewriter Text"
MATHJAX_URL := https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js

HELP_GUIDES := \
	../cga/cgaassist/README.html \
	../cga/mrva-flow/README.html \
	../guides/introductory/bench.html \
	../guides/introductory/cli-workflow.html \
	../cga/sample-05-i/README.html \
	../cga/sample-05/README.html \
	../cga/analysis/CVE-2016-9843/query-030/README.html \
	../cga/system-tests/README.html

.PHONY: all help html readmes book view-book clean pretty test-overview test-html-links

# Keep the top-level `make all` free of an mdbook dependency: build the book
# explicitly with `make book`.
all:
	@echo "docs: start with cga-overview.html; run 'make html' for Markdown pages, 'make help' for command help, 'make book' for the reference manual, or 'make view-book' to preview it"

help: $(HELP_GUIDES)
	$(CGA) help --export cga-help.html

html: $(MARKDOWN_HTML)

readmes: $(README_HTML)

test-overview:
	@command -v chromium >/dev/null 2>&1 || { echo "overview checks require Chromium" >&2; exit 1; }
	@command -v node >/dev/null 2>&1 || { echo "overview checks require Node with built-in WebSocket support (22+)" >&2; exit 1; }
	@node -e 'if (typeof WebSocket !== "function") { console.error("overview checks require Node with built-in WebSocket support (22+)"); process.exit(1); }'
	python3 -m unittest discover -s ../cga/tests -p test_cga_overview.py -v

test-html-links:
	python3 -m unittest discover -s ../cga/tests -p test_html_links.py -v

readme-fonts.css: readme-fonts.py
	python3 "$<" > "$@.tmp" && mv "$@.tmp" "$@"

$(CGA_REFERENCE_HTML): REFERENCE_STYLE = --css "$$(realpath --relative-to="$(@D)" cga-reference.css)"
$(CGA_REFERENCE_HTML): cga-reference.css

$(MARKDOWN_HTML): %.html: %.md Makefile readme-fonts.css readme-layout.css html_links.py
	@title="$$(sed -n 's/^# //p' "$<" | head -n 1)"; \
	$(PANDOC) --standalone --toc $(HTML_FONTS) \
		--css "$$(realpath --relative-to="$(@D)" readme-fonts.css)" \
		--css "$$(realpath --relative-to="$(@D)" readme-layout.css)" \
		$(REFERENCE_STYLE) \
		--variable document-css=true \
		--math-method="mathjax:$(MATHJAX_URL)" \
		--metadata title="$${title:-$(*F)}" "$<" -o "$@" && \
	python3 html_links.py "$@"

# Render the book to book/.
book:
	@command -v $(MDBOOK) >/dev/null 2>&1 || { echo "mdbook not found; install it (e.g. 'cargo install mdbook' or your package manager)"; exit 1; }
	$(MDBOOK) build

# Build and serve with live reload, opening a browser at http://localhost:3000.
view-book:
	@command -v $(MDBOOK) >/dev/null 2>&1 || { echo "mdbook not found; install it (e.g. 'cargo install mdbook' or your package manager)"; exit 1; }
	$(MDBOOK) serve --open

# Remove the generated book output.
clean:
	rm -rf book


# ----------------------------------------------------------------------
# Pretty-print this directory's own Markdown with prettier (repo-wide
# convention: reflow prose to 80 columns). Only README.md and SUMMARY.md
# are owned here; the other src/*.md are symlinks to component READMEs and
# are formatted by their own subprojects.
# System-wide install: npm install -g prettier
# ----------------------------------------------------------------------
pretty:
	@command -v prettier >/dev/null 2>&1 || { echo "prettier not found; install with: npm install -g prettier"; exit 1; }
	prettier --prose-wrap always --print-width 80 --write README.md src/SUMMARY.md

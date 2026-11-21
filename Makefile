# Top-level Makefile: recurse into every subdirectory that has its own Makefile.

# All immediate subdirectories that contain a Makefile.
SUBDIRS := $(patsubst %/Makefile,%,$(wildcard */Makefile))

.PHONY: all clean $(SUBDIRS)

all: $(SUBDIRS)

# Build each subdirectory by running its default target.
$(SUBDIRS):
	$(MAKE) -C $@

# Run clean in each subdirectory that defines a clean target.
clean:
	@for dir in $(SUBDIRS); do \
		if $(MAKE) -C $$dir -n clean >/dev/null 2>&1; then \
			$(MAKE) -C $$dir clean; \
		else \
			echo "skipping $$dir (no clean target)"; \
		fi; \
	done

# ----------------------------------------------------------------------
# Documentation (mdBook in docs/). Delegated to docs/Makefile.
# ----------------------------------------------------------------------
.PHONY: book view-book

# Build the documentation book (docs/book/).
book:
	$(MAKE) -C docs book

# Build and serve the book with live reload, opening a browser.
view-book:
	$(MAKE) -C docs view-book

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

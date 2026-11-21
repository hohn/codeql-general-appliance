# CGA documentation

Choose the depth you need:

1. **[CGA overview](cga-overview.html)** — understand the appliance, follow the
   fixed Sample 05 example, and install CGA.
2. **[CGA help](cga-help.html)** — choose a task and look up instructions and
   commands.
3. **[Reference manual (book)](book/index.html)** — consult detailed workflows,
   components, and operations when needed.

The book is an [mdBook](https://rust-lang.github.io/mdBook/) reference, not a
second introductory course. Its chapters reuse canonical component READMEs
through `src/` symlinks **without duplicating or modifying their content**.
Editing a README updates its chapter on the next book build.

## CGA and MRVA entry point

Start with the [CGA overview](cga-overview.html): the appliance, future CVE case
studies, the fixed Sample 05 reference architecture, and click-through
installation steps. The
[worked example in section 03](cga-overview.html#reference-architecture) follows
one supplied query across five prepared databases and SARIF → SQLite → DuckDB.
This hand-maintained, standalone HTML page needs no viewer; commands are
displayed for execution in the shell. The earlier `cga-sample-05.html` URL
forwards to section 03 and preserves existing deep links.

Next, open the [CGA help browser](cga-help.html) for tasks and commands. Its
command reference is self-contained and separate from mdBook: reading it needs
no running service. Use the header search for plain-text or regex searches
across embedded help: press **Search** to highlight matching entries in **cga
index**. The **Start here** group links back to the visual overview and
reference manual before the existing command walkthroughs. Then browse **LLM
start here**, **Task groups**, or alphabetical **Reference** as needed. Each
start section is independently collapsible; **⊟** collapses every outline.

**getting started** opens the authoritative command walkthrough.
Every guide there also has chapter-sized command help:

```sh
cga help bash-tutorial-sql
cga help bash-tutorial-sql setup
cga help bash-tutorial-sql mrva
cga help bash-tutorial-sql compare
cga help mrva-flow
cga help bench-intro
cga help shell-workflow
cga help two-user-standalone
cga help two-user-workflow
cga help zlib-study
```

Each overview lists its chapters; append a chapter name, for example
`cga help mrva-flow inspect` or `cga help zlib-study results`. These commands
only display instructions; they never execute the guides. All original Markdown
and HTML remain unchanged and linked in the collapsible **Original write-ups**
group under **Reference**, alongside the [project book](book/index.html)
(`make -C docs book`). The collapsible **system tests** group sits below
**cga index** and links the system-test/sample-workflow guide. Document links
open in separate tabs, preserving the command-help panes. Sample 05's embedded
step recipes remain available as `cga help sample 05`; `cga help sample-05`
still aliases those recipes, not the older two-user guide.

**LLM start here** links the hand-maintained
[exploration guide](cga-help-llm.org), agent core, live context command help,
LLM-guided walkthrough instructions, flow-script guide, and advanced reading
map. Choose the relevant entry, not the entire list.

Small anchor symbols identify help controls, outline groups, document links,
command pages, and their sections. They reuse Bench's styling and click
semantics, but have fresh permanent VID roots: for example,
`:vy8,help,bash-tutorial-sql,mrva`. Hover or focus to see the reference.
Single-click copies only the reference; double-click also opens an independent
offline inspector without activating the adjacent control.

The inspector captures the help text and current UI properties at opening, shows
related help, and offers **Copy context** and **Copy link**. Its JSON is ready
to paste into an LLM conversation. Qualified `cga://help` references and file
links pin the normalized embedded help content, excluding the export timestamp;
stale snapshots are rejected rather than silently retargeted, as are
foreign-document references. These are offline documentation references, not
workflow `cga://vid` objects: no service or terminal starts, and `cga show` does
not resolve them. Clipboard failures are explicit and leave inspection
available. Presentation-only pane dividers have no anchors.

Rebuild the entry point and its linked human HTML guides with Pandoc and `cga`:

```sh
make -C docs help
```

Markdown remains the source of truth. The generated tutorial HTML is tracked
with the help browser. `cga help --export docs/cga-help.html` refreshes just the
command browser; it does not rebuild linked documents. Links are relative to the
export destination and preserve the checkout's layout. The embedded command
reference still works when copied alone; copy the linked guides too to retain
the full documentation entry point.

## Revising the CGA overview

`cga-overview.html` is the hand-maintained source, including its CSS and
JavaScript; it has no generator or runtime dependencies. Follow the
[overview revision contract](../.agent-notes/documentation.md#cga-overview-revision-contract)
for its structure, styling, fixed example, and read-only behavior.

Run the focused checks from the checkout:

```sh
make -C docs test-overview
```

Requires Python 3, Chromium, and Node with built-in WebSocket support (22+). No
npm packages, viewer, MRVA services, or external network access are needed. The
checks compare sample and installation commands with their canonical sources,
then exercise offline navigation, dialog focus, clipboard success/failure,
legacy links, and desktop/mobile layout. They also check the three CGA reference
pages' matching typography, section links, and responsive contents. They never
execute displayed shell commands; shell validation uses `bash -n`.

## Build / serve

For a headless VM, `cga gateway start` serves documentation directly from this
checkout. `cga serve start` includes the same gateway alongside configured
viewers. Forward port 8599 over SSH and open <http://127.0.0.1:8599/>; choose
the overview, help, or reference manual there. `/documentation/` preserves the
repository-relative layout, so linked component guides and assets also work on
the workstation without a local checkout. See the
[gateway guide](../cga/cgagateway/README.md#documentation) for the tunnel and
rebuild commands.

The repository's `index.html` and `docs/index.html` redirect to the canonical
`docs/cga-overview.html`, preserving query strings and fragments when JavaScript
is available. Without JavaScript, a native refresh opens the overview; ordinary
links remain as a fallback. These are navigation aliases, not copies of the
overview. `README.html` starts with overview, help, then the reference manual.

For static hosting, publish the repository-relative documentation tree, not
`docs/` alone: the overview links to sibling `cga/`, `vm-setup/`, and root
documentation. The checked-in HTML needs no CGA process or documentation build.
The optional `docs/book/` is not included in a clone; build it to enable the
reference-manual links:

```sh
make -C docs book
```

The book retains its existing reference chapters. Its first chapter is labelled
**Repository and implementation reference**, with links back to the overview and
help; compatibility redirects keep those links working inside the book. Its
system-font stylesheet is a book source asset, so the generated site needs no
optional font bundle from the mdBook installation.

### Static publication with lighttpd

Publish a separate clone rather than the development checkout:

```sh
cga public-html setup > /tmp/cga-public-html.sh
bash -n /tmp/cga-public-html.sh
less /tmp/cga-public-html.sh
bash /tmp/cga-public-html.sh
```

`setup` clones the installed CGA checkout's committed HEAD into
`~/public_html/single-machine-mrva` when absent or empty. It does not depend on
the current directory. Unpushed commits are included; uncommitted changes, saved
pages, and ignored runtime artifacts are not. An existing CGA documentation
checkout is reused without fetching, pulling, resetting, or changing its files.
Non-checkouts and symlink destinations are rejected.

Progress goes to stderr; stdout contains only a documented Bash script. Setup
itself does not build the book, change permissions, install configuration, or
start/reload any service. The printed Debian/lighttpd example uses the current
account and home, builds the optional book, grants scoped `www-data` access, and
validates configuration before applying it. It lists prerequisites and refuses
to replace an existing, differing configuration; review and merge that
configuration manually, or use only the applicable steps on an already
configured server.

The [lighttpd configuration](lighttpd-public-html.conf) is the shared policy;
its default variables illustrate `/~hohn/` and `/home/hohn/public_html/`. Only
the web-server account gains home-directory traversal and publication read
access; Git metadata remains denied at the filesystem level. The configuration
serves HTML indexes (falling back to `README.html`), disables symlink traversal,
and allows only GET/HEAD. Directory listings must remain disabled in the host
configuration (Debian's default). It denies hidden metadata and common
scratch/runtime directories while keeping `.agent-notes/`, Markdown, and Org
sources available for LLM navigation. Keep this clone for static publication
only; do not run CGA workflows in it.

On `svm`, open <http://svm/~hohn/single-machine-mrva/> from the workstation. The
root opens the overview; help and the built reference manual retain the same URL
prefix. This is independent of the loopback CGA gateway and needs no SSH tunnel.
A basic host-side check is:

```sh
curl -I http://127.0.0.1/~hohn/single-machine-mrva/
curl -I http://127.0.0.1/~hohn/single-machine-mrva/.git/config
```

Expect 200 for the entry page and 403 for Git metadata. Open the entry in a
browser as well: its HTML redirect is not followed by `curl`. For updates,
commit changes in the source checkout, then fast-forward the publication clone
and rebuild its book:

```sh
git -C "$HOME/public_html/single-machine-mrva" pull --ff-only
make -C "$HOME/public_html/single-machine-mrva/docs" book
```

Apache or another static server can publish the same repository-relative tree;
apply equivalent metadata exclusions, symlink restrictions, and disabled
directory listings. No CGI or CGA backend is needed.

### Regenerating standalone HTML

Generate standalone HTML beside canonical repository Markdown files, including
the introductory guides. Book-source aliases under `docs/src/` and `notes/src/`
are excluded so their standalone HTML cannot overwrite mdBook chapters:

```sh
make -C docs html
```

To regenerate only the README pages:

```sh
make -C docs readmes
```

Standalone rendering runs `html_links.py` after Pandoc. Local human-document
links point to `.html`, preserving query strings and section fragments; Markdown
sources keep their `.md` links. Links to `AGENTS.md`, `.agent-notes/`, and Org
guides retain their quieter source formats for LLM use. External links,
including GitHub-rendered Markdown, are unchanged. The same normalizer can
refresh legacy HTML without changing its layout:

```sh
python3 docs/html_links.py path/to/page.html
make -C docs test-html-links
```

The checks cover rewriting rules, human-document destinations and fragments, and
all tracked HTML, excluding source navigation inside agent-instruction pages.
When mdBook is installed, they also build a temporary book and check its entry
links and assets; otherwise that check is skipped. These checks require Python 3
and Git, not MRVA services or a browser.

Requires Pandoc. By default, HTML uses **Synonym** for prose and **CMU Typewriter
Text** for code. The shared `docs/readme-fonts.css` embeds the fonts as data URLs,
so Chrome and other browsers can load them from `file://` without relying on
system-font discovery or network access.

All Markdown pages also use `docs/readme-layout.css` to keep their table of
contents fixed on the left, with an inline layout on narrow screens and in print.
Keep both stylesheets with the HTML when copying the documentation.
Prose uses Synonym Regular; CMU code is scaled to match its lowercase x-height
rather than Pandoc's default reduced code size.

The [CGA](../cga/README.html), [Unified View](../cga/cgauv/README.html), and
[Bench](../cga/cgabench/README.html) references additionally use
`docs/cga-reference.css` to match the overview: sans-serif headings, white
background, fine borders, and neutral code/table panels. Their content and
anchors still come from Markdown. The `CGA_REFERENCE_HTML` list in the Makefile
limits this style to those three pages; keep the additional stylesheet with
them when copying documentation. To rebuild only these references:

```sh
make -C docs ../cga/README.html ../cga/cgauv/README.html ../cga/cgabench/README.html
```

Rebuilding `readme-fonts.css` requires Python 3 and the fonts under `~/.fonts`;
`make -C docs -B html` refreshes the embedded copies from those files.

Requires **mdBook >= 0.5** (for the sidebar heading navigation, see below).

```sh
cd docs
make book          # renders to docs/book/ (gitignored)
make view-book     # live-reloading preview at http://localhost:3000
```

## Multi-level table of contents

mdBook >= 0.5 shows the **current page's headings** (`h2`–`h6`) nested directly
in the left sidebar, so each chapter expands to a multi-level TOC while you read
it — without splitting the symlinked component READMEs (which stay the single
source of truth). Level 3+ headings start folded and expand on click.

This is enabled via `sidebar-header-nav = true` under `[output.html]` in
`book.toml` (the mdBook 0.5 default; set explicitly to document intent).

## Mathematics

The HTML renderer's built-in MathJax integration is enabled with
`mathjax-support = true`. Math source must use mdBook's escaped delimiters:
`\\( ... \\)` for inline math and `\\[ ... \\]` for display math. Within a
display block, a TeX row break is written as `\\\\` so it survives Markdown
processing. Markdown also consumes some TeX escapes: write a subscript as
`x\_i`, a literal TeX underscore as `\\_`, and punctuation commands such as
`\\{` and `\\,` with two source backslashes.

## Layout

- `book.toml` — book configuration (`src = "src"`, output to `book/`, MathJax,
  `sidebar-header-nav`).
- `src/SUMMARY.md` — the sidebar chapter list.
- `src/` — symlinks into canonical guides, example documentation, agent
  references, and component READMEs. Nested paths preserve repository-relative
  navigation from the reading guide.
- `book/` — generated output (not tracked).
- `cga-help.html` — generated, checked-in CGA/MRVA entry point and offline help.
- `cga-help-llm.org` — independent, hand-maintained LLM exploration entry point.

To add a chapter, symlink its canonical Markdown into `src/` and add an entry to
`src/SUMMARY.md`. When a chapter already has a shorter book-specific name,
`output.html.redirect` in `book.toml` can map its repository path to that
chapter; do not duplicate the source.

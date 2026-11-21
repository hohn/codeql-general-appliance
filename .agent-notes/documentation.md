# Documentation notes

- [READING-GUIDE.md](../READING-GUIDE.md) is advanced guidance for experienced
  CodeQL users and LLMs. [INTRODUCTORY-GUIDE.md](../INTRODUCTORY-GUIDE.md)
  routes to simpler usage outlines under `guides/introductory/`. Keep the two
  levels distinct; audience markers are not difficulty ratings. The agent core
  is the only mandatory agent-note read.
- All repository material is prototype work. Keep useful examples for future
  experimentation; remove obsolete explanations rather than archiving them.
  Usage examples and supporting code evolve together.
- Human entry order is overview, command help, then the reference book.
  Repository/docs `index.html` files redirect to `docs/cga-overview.html`; root,
  CGA, and docs READMEs introduce the same roles. The book remains detailed
  reference, not a competing introduction; preserve its substantive chapters.
  Keep the independent LLM onboarding route unchanged.
- For remote browsers, the CGA gateway serves the same checkout tree below
  `/documentation/` on 8599. Do not introduce absolute `file://` navigation or
  hand-maintained copies of pages; rebuild generated pages and the optional book
  normally. `cga public-html setup` prepares a static clone and prints the
  operator's documented setup script without running its steps. Static web
  servers can publish a separate clone with the full repository-relative layout;
  `docs/lighttpd-public-html.conf` is the scoped public_html example. Retain its
  metadata/scratch and symlink boundaries, keep directory listings off, and
  preserve public LLM sources. A fresh clone needs `make -C docs book` for
  reference-manual links, not a rebuild of checked-in HTML.
- Markdown uses Prettier with `--prose-wrap always --print-width 80`. Use
  targeted formatting rather than reformatting unrelated files.
- `make -C docs html` renders canonical repository Markdown beside its source
  as HTML; `make -C docs readmes` selects only READMEs. By default, both use
  Synonym and CMU Typewriter Text embedded in the shared
  `docs/readme-fonts.css` for reliable `file://` viewing. Rebuilding the CSS
  requires Python 3 and the fonts under `~/.fonts`. All Markdown pages share
  `docs/readme-layout.css`: fixed-left TOC, inline on narrow screens and in print.
  The CGA, Unified View, and Bench READMEs additionally opt into
  `docs/cga-reference.css` through `CGA_REFERENCE_HTML` in `docs/Makefile`,
  matching the overview's typography and neutral panels without changing other
  pages. Edit that stylesheet, not their generated HTML; preserve Markdown
  content, heading anchors, and reference navigation.
  Exclude `docs/src/` and `notes/src/` aliases: HTML siblings there overwrite
  mdBook chapters during asset copying.
- Standalone rendering runs `docs/html_links.py` after Pandoc: local human
  navigation targets HTML, while `AGENTS.md`, `.agent-notes/`, and Org guides
  retain source-format links for LLMs. Agent-instruction HTML retains source
  navigation throughout; external links are unchanged. Keep Markdown sources'
  links in Markdown form. Run `make -C docs test-html-links` to check the
  normalizer, human-document destinations/fragments, and all tracked HTML,
  including legacy pages without a Markdown owner. When mdBook is available, the
  same suite builds a temporary book and checks its entry links and assets.
- [docs/](../docs/README.md) assembles the project book from canonical Markdown
  via `docs/src/` symlinks. Add a symlink and a SUMMARY entry for a new chapter;
  do not copy its content. Build with `make -C docs book`.
- `docs/cga-overview.html` is the human front door; `docs/cga-help.html` is the
  self-contained task/command reference separate from mdBook.
  `make -C docs help` regenerates it and its tracked human tutorial HTML from
  canonical Markdown. `cga help --export docs/cga-help.html` refreshes only the
  command browser. Stage refreshed artifacts with their source changes.
- [docs/cga-help-llm.org](../docs/cga-help-llm.org) is the independent,
  hand-maintained LLM entry point. Keep it a selective task-routing layer,
  linking canonical help/contracts and read-only state projections, not a copy
  of the human tutorial or a generated command dump. `AGENTS.md` routes through
  the core to this guide for CGA work; broad project maps are a last resort, not
  an intervening onboarding step. Keep topic-note introductions from redirecting
  agents to entire manuals or root indexes.
- `docs/cga-overview.html` is a hand-maintained, standalone CGA introduction,
  not generated Markdown output. Follow the
  [revision contract](#cga-overview-revision-contract) below when changing it.
- [notes/](../notes/README.md) is a separate conceptual mdBook, not another
  project manual. `notes/src/` links canonical note sources. Its intentionally
  tracked rendered HTML/PDF are rebuilt explicitly, not incidental clutter.
- Math in the project book uses mdBook delimiters `\\( ... \\)` and
  `\\[ ... \\]`, not dollar delimiters. Keep Markdown escaping for TeX
  underscores, punctuation, and display-block row breaks; see
  [book mathematics](../docs/README.md#mathematics).
- [INSTALL.md](../INSTALL.md) owns Debian/Ubuntu dependencies; keep host
  installer inventories aligned. [REMOTE-CONNECTION.md](../REMOTE-CONNECTION.md)
  owns remote access details.
- Root `count-lines` reports tracked source by language, human docs, and LLM
  docs. It excludes symlinks and rendered/binary documentation; `--list` audits
  classification. Agent topic files remain LLM documentation.

## CGA overview revision contract

Make focused edits to `docs/cga-overview.html`, its inline CSS, and vanilla
JavaScript. Do not introduce a generator, framework, or external runtime assets
without an explicit request. Preserve these design and behavioral boundaries:

- Keep the four numbered chapters: CGA introduction, CVE case studies marked
  future work, Sample 05 reference architecture, and getting started. Preserve
  chapter and detail IDs, sticky section navigation, and existing deep links.
  `docs/cga-sample-05.html` forwards to section 03, retaining supplied
  fragments.
- Retain the restrained visual language: whitespace, regular-weight sans-serif
  headings, thin grey borders, no shadows, a dotted diagram canvas, pale-blue
  inputs, lavender workflow cards, and neutral result artifacts. Keep the linked
  OpenAI Defense Factory credit in the footer.
- Sample 05 is a fixed worked example: five prepared databases, `Fprintf.ql`,
  and SARIF to SQLite to cumulative DuckDB. Keep its five learning milestones;
  shell recipes remain authoritative in `cga/cgalib/sample_help.py`. Do not add
  configuration controls, database building, patching, or a run-all action.
- This is offline, read-only documentation, not a live dashboard or execution
  interface. Cards open explanations and commands; they do not install tools,
  launch services, or submit work. Label expected artifacts honestly and retain
  the distinction between pipeline completion and demonstrated CVE detection.
- Use semantic HTML, native expandable sections/dialogs, keyboard focus return,
  explicit clipboard-failure feedback, and a usable no-JavaScript fallback. Keep
  multi-line shell blocks in `<pre><code>` so formatting cannot merge commands.
  Match installation snippets to `INSTALL.md`, the host-installer READMEs, and
  `cga/README.md`; never execute snippets to test this page.

Run `make -C docs test-overview` after revisions. It checks canonical recipes,
local links, offline operation, navigation, dialogs, copied commands,
forwarding, desktop/mobile layout, and the three reference pages' matching
styles and responsive contents without running MRVA or installation commands.
Requires Python 3, Chromium, and Node with built-in WebSocket support
(22+); no npm packages are needed. For layout changes, also open the page at
desktop and narrow widths: smoke tests protect behavior, not visual design
quality.

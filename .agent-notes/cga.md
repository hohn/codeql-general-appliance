# CGA integration notes

Read these constraints for command integration or recorded-example changes.
Consult only the relevant named section of the [usage guide](../cga/README.md)
when the task needs its contract, not the whole manual as a prerequisite.

## Commands and state

- `cga/cga` owns command routing; Bash completion discovers the same routing
  table through `cga __tools|__subs|__long`. Keep both command and alias
  surfaces consistent. Database operations route to `cgadbplan`, `cgadb`, and
  `cgadbvalidate`; catalogues and CodeQL checks are separate components.
- Normal examples use the top-level dispatcher. Direct component commands remain
  CGAST JSON filters for pipelines and tests. Many use `bin/<component>`, a
  same-name package, and `tests/`.
- Public `-h` help uses `cgalib/command_help.py` and command-specific topics in
  `cgalib/help_topics/`: Name, Synopsis, native argument/option headings,
  Description, relevant Environment Variables, and contextual Example. Call
  `enhance_parser` after building the full parser tree; document new groups and
  leaves rather than falling back to generic text. Shell/Go dispatcher help uses
  `cgalib/dispatcher_help.py`. Help must not record attempts or start services.
  Coverage:
  `cd cga && python3 -m unittest discover -s tests -p test_command_help.py`.
- `cga public-html setup` clones committed HEAD into
  `~/public_html/single-machine-mrva` if needed and prints a documented Bash
  script on stdout; diagnostics go to stderr. Existing documentation clones
  remain untouched. Only the operator-run script builds the book, changes ACLs,
  or applies lighttpd configuration; preserve its differing-config guard and the
  shared `docs/lighttpd-public-html.conf` policy. Tests:
  `cd cga && python3 -m unittest discover -s tests -p test_public_html.py`.
- `cga help --export FILE.html` uses `cgalib/help_view.py` and its own
  `help_static/` assets to embed authoritative help in a standalone file. Bench
  is only a visual reference, never a runtime or styling dependency. Navigation
  is shallow: outline selects PR_t, its subcommands open in PR_b, and deeper
  help is a copyable shell command. Preserve offline operation, safe text
  rendering, independent scrolling, and read-only export collection. Reference
  is alphabetical; `help_view.py` owns the four overlapping task groups. Search
  covers all embedded pages, with literal/regex modes and safe DOM highlighting.
  Search runs only on submit and marks index entries for matching
  command/subcommand help; retain the two-pane depth boundary. Tests:
  `cd cga && python3 -m unittest discover -s tests -p test_help_view.py`. The
  viewer opens `cga help overview` before `cga help getting-started`. The
  overview's shared content lives in `help_topics/workflow.py`, with read-only
  CLI and HTML presentations. Collapsible Start here and LLM
  start here groups route to embedded help and checkout-relative document links;
  external guides open separately. `make -C docs help` rebuilds the linked human
  HTML guides and the entry point. `cgalib/tutorial_help.py` owns the shared
  Start here guide registry and source-backed read-only chapter help, including
  `cga help bash-tutorial-sql [CHAPTER]`. Keep declared chapters aligned with
  canonical Markdown headings outside code fences; preserve all fenced text,
  never execute it. Reference holds collapsible system tests and Original
  write-ups below cga index; linked HTML opens separately. Sample 05's
  individual step pages remain embedded read-only. `cgalib/sample_help.py` owns
  the shared displayed/executed Bash recipes; only an exact trailing `run`/`r`
  executes a step. `h` aliases `help`, `s` aliases `sample`, and `sample-05`
  normalizes to `sample 05`. Step 00 explicitly creates
  `cga-tmp/help-sample-05/` and saves private runtime settings for fresh
  shells/cells; later steps source those settings. Tests:
  `cd cga && python3 -m unittest discover -s tests -p test_sample_help.py`. The
  longer getting-started walkthrough remains available. `cga -hs` and
  `cga -h -s` print the identical guide; its Commands/Further Reading content
  lives in `help_topics/workflow.py`, not a separate HTML-only tutorial. Keep
  these help requests read-only even inside an active workflow.
- `cga/cgawf` owns immutable workflow history and artifact recording.
  `.cga/current.json` is a compatibility copy, not a second authoritative
  history. New workflows use `cga tree show`; `dfg`/`cfg` also support earlier
  manifest-based examples.
- `cga a q start DIRECTORY` bootstraps a fresh named authoring workflow; later
  `assist query-writing` operations use normal workflow recording. Prompt input
  uses `/dev/tty`, never CGAST stdin. Help remains read-only. Source snapshots
  use tracked `path` fields, and library artifact paths are absolute so ordinary
  `cga ql` commands work in later shells without authoring-specific exports.
- `cga a d fetch/build/index/export` operates inside an initialized preparation
  workflow. `cgaassist/database.py` owns guided choices and per-job recovery;
  operations stay in the source/build/catalogue plumbing. Respect explicit
  scratch overrides; otherwise keep artifacts under the workflow's `.cga/tmp/`.
- `.cga/` stores normalized relative `objects/sha256/...` keys. The configured
  object-store root supplies object bytes. `CGA_WORKFLOW_STORE` selects the
  initial store; `cga store set` verifies references when changing it.
- `cga/mrva-flow/mrva-flow.sh` is the starting single-user recorded example.
  `cga mr run` combines bounded submit/poll/download/verify into one operation
  while retaining recovery checkpoints. Do not duplicate submission after an
  uncertain outcome; inspect status and existing checkpoints.
- Follow the [flow script guide](../cga/cgawf/FLOW-SCRIPT-GUIDE.md): one
  meaningful operation per command, explicit choices, no duplicate provenance
  plumbing. Keep setup distinct from the conceptual experiment.
- `cgamx` owns the example's MRVA infrastructure lifecycle. Configuration
  defaults are supplied only when unset. `check` is the log-error gate.
  Component tests: `cd cga/cgamx && python3 -m unittest discover -s tests`.

## Assistant context and element references

- `cga llm context bench` and `cga llm context unified` read bounded state
  projections without a web service or recorded mutation. Implementation:
  `cga/cgalib/llm.py`. Endpoint/doc flags print references; they do not fetch
  them or prove a viewer is running. Tests:
  `cd cga && python3 -m unittest discover -s tests -p test_llm.py`.
- `cga/cgalib/vid_registry.py` owns permanent opaque VID roots; never reassign
  them. `vid.py` is the shared resolver for CLI, Bench, and Unified View. Facts
  derive from retained immutable states/CAS, not another mutable store.
- Offline help registers disjoint help roots in the same registry. Embedded
  `help_static/references.js` adapts shared VID badges to content-pinned
  `cga://help` inspectors, copyable JSON, and file deep links; it starts no
  service or terminal. Do not route these references through workflow VID
  resolution. Help page/section identities use canonical commands/headings,
  never filtered positions; document identities hash canonical source paths.
- Shared `vid_http.py` and `vid_static/` own inspectors and their terminals.
  Closing an inspector or expiring its lease owns that terminal, not the
  experiment. Copilot context insertion does not execute the command.
- Browser badge changes must preserve existing activation/clipboard behavior and
  stable layout. Presentation-only splitters must not receive badges. Tests:
  `cd cga && python3 -m unittest discover -s tests -p test_vid.py`.
- Preparation and analysis handoff is explicit. Selection history may retain
  multiple users, but singular selection/pack keys are active inputs. Submission
  labels and authenticated MRVA users are distinct identities.

"""Executable sample recipes: the displayed shell is also the executed shell."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
import shlex
import subprocess

from command_help import CommandHelpFormatter, topics


COLLECTION = Path(__file__).resolve().parents[1]
WORKSPACE = COLLECTION / "cga-tmp" / "help-sample-05"
INPUTS = COLLECTION / "samples" / "05"


@dataclass(frozen=True)
class Step:
    number: str
    name: str
    summary: str
    commands: str
    outcome: str


STEPS = (
    Step("00", "start", "Create the sample directory and recorded workflow.", "",
         "The sample directory contains .cga/ and a private sample-05.env."),
    Step("01", "preflight", "Check prerequisites and reclaim MRVA ports.",
         "cga mx preflight", "Preflight succeeds; no MRVA server is started."),
    Step("02", "reset", "Reset standalone MRVA state.",
         "cga mx reset", "MRVA runtime and PostgreSQL state are reset."),
    Step("03", "build", "Build the MRVA server and agent.",
         "cga mx build", "The local MRVA binaries are built."),
    Step("04", "start-mrva", "Start standalone MRVA.",
         "cga mx start", "MRVA and its database archive server are ready."),
    Step("05", "index-libraries", "Import the database catalogue and index queries.",
         'cga dl getmeta "$CGA_SAMPLE_INPUTS/catalogue.sql"\n'
         'cga ql index "$CGA_SAMPLE_INPUTS/queries"',
         "The database and query libraries are indexed; nothing is selected."),
    Step("06", "list-queries", "List up to five queries.",
         "cga ql list 5", "At most five query rows are displayed."),
    Step("07", "list-databases", "List up to ten CodeQL databases.",
         "cga dl list 10", "At most ten database catalogue rows are displayed."),
    Step("08", "select-databases", "Select five fixed C++ databases for bob.",
         'cga dl sql --user bob --query-file "$CGA_SAMPLE_INPUTS/databases.sql"',
         "One database each for dsvpn, file, flex, inotify-tools, and nnn is selected."),
    Step("09", "select-query", "Select the supplied Fprintf query for bob.",
         "cga ql select --user bob relpath Fprintf.ql",
         "q_p is Fprintf.ql, a pipeline demonstration rather than a vulnerability detector."),
    Step("10", "download-databases", "Download the five selected database archives.",
         'cga dl download --output-dir "$MRVA_DB_SERVE_DIR"',
         "The five archives are in the database store served to MRVA."),
    Step("11", "pack-query", "Build the selected query pack.",
         "cga ql pack", "The executable query pack is recorded."),
    Step("12", "submit", "Submit the query against the five databases.",
         "cga mr submit --name sample-05 --user bob --language cpp",
         "One named submission is recorded. Do not repeat submit after an uncertain outcome."),
    Step("13", "status", "Observe submission status once.",
         "cga mr status --name sample-05",
         "Repeat this step until status is succeeded; failed work must be investigated."),
    Step("14", "download", "Download results after successful completion.",
         """\
cga --json state show | python3 -c '
import json, sys
state = json.load(sys.stdin)
status = state.get("cgamr-submissions", {}).get("sample-05", {}).get("status")
if status != "succeeded":
    raise SystemExit(f"sample 05: status is {status!r}; run step 13 before download")
'
cga mr download --name sample-05 --output-dir "$PWD/downloads"
""",
         "Result archives for the five databases are downloaded."),
    Step("15", "verify", "Verify submission success and downloaded archives.",
         "cga mr verify sample-05", "All five downloaded result archives pass verification."),
    Step("16", "ingest", "Ingest results into one cumulative SQL database.",
         'cga si ingest --name sample-05 --output-dir "$PWD/findings"',
         "db_sql is findings/all.duckdb; per-job SQLite inputs retain provenance."),
    Step("17", "verify-ingestion", "Verify the cumulative result store.",
         "cga si verify sample-05", "Ingestion artifacts and cumulative row totals agree."),
    Step("18", "results", "Show up to four findings per database using SQL.",
         'cga si sql --query-file "$CGA_SAMPLE_INPUTS/results.sql"',
         "Each database has up to four ordered findings, or an explicit zero-findings row."),
    Step("19", "check", "Check the MRVA server error log.",
         "cga mx check", "The server log contains no non-benign errors."),
    Step("20", "stop", "Stop MRVA while retaining the sample and results.",
         "cga mx stop", "Services are stopped; workflow history and result files remain."),
)


def start_commands(workspace: Path) -> str:
    quote = shlex.quote
    defaults = {
        "CGA_TMPDIR": '"$PWD/.cga/tmp"',
        "MRVA_WORK_DIR": '"$PWD/.cga/runtime/mrva"',
        "MRVA_TMP_DIR": '"$PWD/.cga/runtime/services"',
        "MRVA_DB_SERVE_DIR": '"$MRVA_WORK_DIR/db-serve"',
        "MRVA_STANDALONE_STORAGE": "filesystem",
        "RUN_TAG": "cga-help-sample-05",
        "PORT": "8081",
        "CGA_MRVA_SERVER": '"http://127.0.0.1:$PORT"',
        "CODEQL_JAVA_HOME": "/usr",
    }
    exports = "\n".join(
        f"export {name}=${{{name}-{value}}}" for name, value in defaults.items()
    )
    return f"""\
umask 077
mkdir -p {quote(str(workspace.parent))}
mkdir {quote(str(workspace))}
cd {quote(str(workspace))}
export PATH={quote(str(COLLECTION))}:"$PATH"
export CGA_DIR="$PWD/.cga"
export CGA_WORKFLOW_ROOT="$PWD"
export CGA_SESSION="$CGA_DIR/current.json"
export CGAST_ROOT="$PWD"
export CGA_SAMPLE_INPUTS="$PWD/inputs"
{exports}
cga init
cga chain start --name sample-05
mkdir inputs
cp {quote(str(INPUTS / 'databases.sql'))} inputs/databases.sql
cp {quote(str(INPUTS / 'results.sql'))} inputs/results.sql
ln -s {quote(str(COLLECTION / 'cgadl/db-collection.global/metadata.sql'))} inputs/catalogue.sql
ln -s {quote(str(COLLECTION.parent / 'sample-query'))} inputs/queries
export -p | grep -E '^declare -x (CGA_|CGAST_|MRVA_|POSTGRES_|MINIO_|CODEQL_|DB_SERVER_|SERVER_|PORT=|RUN_TAG=|USER=)' > .cga/sample-05.env
printf 'Sample workspace: %s\\nSaved runtime settings: %s\\n' "$PWD" "$PWD/.cga/sample-05.env"
"""


def script(step: Step, workspace: Path = WORKSPACE) -> str:
    if step.number == "00":
        commands = start_commands(workspace)
    else:
        commands = (
            f"cd {shlex.quote(str(workspace))}\n"
            '. .cga/sample-05.env\n'
            f'export PATH={shlex.quote(str(COLLECTION))}:"$PATH"\n'
            f"export CGA_SOURCE_STEP=sample-05-{step.number}-{step.name}\n"
            + step.commands
        )
    return "set -euo pipefail\n" + commands.rstrip() + "\n"


def add_parser(subparsers) -> None:
    sample = subparsers.add_parser("sample", aliases=["s"])
    samples = sample.add_subparsers(dest="sample", metavar="SAMPLE")
    overview = samples.add_parser("05")
    overview.add_argument_group(
        "Workspace",
        f"{WORKSPACE}\nCreated explicitly by step 00. Displaying help creates nothing.",
    )
    steps = overview.add_subparsers(dest="sample_step", metavar="STEP")
    for step in STEPS:
        parser = steps.add_parser(step.number, aliases=[step.name])
        parser.add_argument(
            "action", nargs="?", choices=("run", "r"),
            help="execute the displayed Bash commands; omitted means display only",
        )
        parser.add_argument_group("Commands", script(step))
        parser.add_argument_group("Expected Outcome", step.outcome)
        parser.set_defaults(sample_recipe=step)


class RecipeHelpFormatter(CommandHelpFormatter):
    def _fill_text(self, text: str, width: int, indent: str) -> str:
        if text.startswith("set -euo pipefail\n"):
            return text
        return super()._fill_text(text, width, indent)


def format_recipes(parser) -> None:
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if not isinstance(choices, dict):
            continue
        for child in {id(child): child for child in choices.values()}.values():
            if "sample_recipe" in child._defaults:
                step = child._defaults["sample_recipe"]
                child.formatter_class = partial(
                    RecipeHelpFormatter,
                    topic=topics()[("help", "sample", "05", step.number)],
                )
            format_recipes(child)


def run(step: Step) -> int:
    return subprocess.run(["bash", "-c", script(step)], check=False).returncode

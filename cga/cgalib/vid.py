"""Shared CGA visual-reference resolver and cumulative immutable fact projection."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

COLLECTION = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(COLLECTION / name) for name in ("cgawf", "cgauv", "cgabench")]

from cgawf.repository import Repository, WorkflowError, canonical_json
from cgast import cga_root
from vid_registry import BY_ID, REGISTRY, reference

SCHEMA = "cga.vid.v1"


class MissingObject(WorkflowError):
    pass


def parse_reference(text: str) -> tuple[str, list[str]]:
    if not isinstance(text, str) or len(text) > 4096:
        raise WorkflowError("reference must contain at most 4096 characters")
    text = text.strip()
    if text.startswith("(") and text.endswith(")"):
        parts = text[1:-1].split()
    else:
        parts = text.split(",")
    if not parts or parts[0] not in BY_ID:
        raise WorkflowError(f"unknown VID root: {parts[0] if parts else text!r}")
    if BY_ID[parts[0]]["selectors"].get("help"):
        raise WorkflowError("offline help reference; inspect it in the CGA help browser")
    path = [part.removeprefix(":") for part in parts[1:]]
    if len(path) > 16 or any(
            not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path):
        raise WorkflowError("invalid VID path; use comma selectors or a quoted Lisp form")
    path = [str(int(part)) if part.isdecimal() else part for part in path]
    return ",".join([parts[0], *path]), path


def qualified(context: dict, ref: str, at: str | None = None) -> str:
    values = {key: context.get(key, "") for key in ("workflow", "chain", "experiment")}
    values["ref"] = ref
    if at is not None:
        values["at"] = at
    return "cga://vid?" + urlencode(values)


def decode(text: str) -> tuple[str, dict]:
    if not isinstance(text, str):
        raise WorkflowError("reference must be a string")
    if not text.startswith("cga://"):
        return text, {}
    parsed = urlsplit(text)
    if parsed.netloc != "vid" or parsed.path or parsed.fragment:
        raise WorkflowError("invalid qualified CGA reference")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if set(query) - {"workflow", "chain", "experiment", "ref", "at"} \
            or any(len(value) != 1 for value in query.values()) \
            or not all(key in query for key in ("workflow", "chain", "experiment", "ref")):
        raise WorkflowError("qualified reference requires workflow, chain, experiment, and ref")
    values = {key: value[0] for key, value in query.items()}
    return values.pop("ref"), values


def _index(value: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise WorkflowError("object indices must be positive, one-based integers")
    return int(value)


def _secret(value: dict) -> bool:
    return "sensitivity:secret" in value.get("tags", {}).get("canonical", [])


def _frontier(value: str) -> tuple[str, tuple[int, int] | None]:
    match = re.fullmatch(r"([^~]+)(?:~a(\d+)~r(\d+))?", value)
    if not match:
        raise WorkflowError("invalid fact frontier")
    bounds = (int(match[2]), int(match[3])) if match[2] is not None else None
    return match[1], bounds


def session_children(item: dict, stage: str) -> list[dict]:
    archives = (item["D"].get("artifact") or {}).get("archives", [])
    artifact = item[stage].get("artifact") or {}
    if stage == "Q":
        return [{"ref": reference("sessions", item["index"], stage, 1),
                 "label": "Accepted query"}] if artifact.get("selection_sha256") else []
    if stage == "J" and not item["engine"].get("cgamr-submissions", {}).get(item["submission"]):
        return []
    repositories = {job["repository"] for job in artifact.get("ingestion", {}).get("jobs", [])}
    return [{"ref": reference("sessions", item["index"], stage, index),
             "label": archive["repository"]}
            for index, archive in enumerate(archives, 1)
            if stage != "R" or archive["repository"] in repositories]


class Space:
    def __init__(self, repository: Repository):
        self.repository = repository
        self.workflow = str(getattr(repository, "source", repository.cga_dir))
        self.manifest = repository.load_manifest()

    def context(self, chain: str | None = None, at: str | None = None) -> dict:
        if not self.manifest["chains"]:
            if chain or at:
                raise MissingObject("workflow has no recorded chain or fact frontier")
            return {"workflow": self.workflow, "chain": "", "experiment": "", "frontier": ""}
        chain_id, item = self.repository.resolve_chain(self.manifest, chain)
        node, bounds = _frontier(at or item.get("head") or f"base-{chain_id}")
        if bounds is None:
            cutoff = None
            if at:
                source = item if node == f"base-{chain_id}" \
                    else self.manifest["nodes"].get(node, {})
                cutoff = source.get("created_at", "")
            bounds = tuple(max((int(value["id"].split("_")[1]) + 1
                                for value in self.manifest[kind].values()
                                if cutoff is None or value["created_at"] <= cutoff), default=0)
                           for kind in ("attempts", "artifacts"))
        if any(bound > self.manifest.get(key, 0) for bound, key in zip(
                bounds, ("next_attempt_id", "next_artifact_id"))):
            raise MissingObject("fact frontier includes unrecorded metadata")
        frontier = f"{node}~a{bounds[0]}~r{bounds[1]}"
        state = self._state(node, chain_id)
        experiment = state.get("cgabench-experiment", {})
        return {"workflow": self.workflow, "chain": chain_id,
                "experiment": experiment.get("id", ""), "frontier": frontier, "node": node}

    def _state(self, frontier: str, chain: str) -> dict:
        frontier, _bounds = _frontier(frontier)
        if frontier == f"base-{chain}":
            return self.repository.load_state(self.manifest["chains"][chain]["base_state"])
        node = self.manifest["nodes"].get(frontier)
        if node is None:
            raise MissingObject(f"unknown fact frontier: {frontier!r}")
        return self.repository.load_state(node["state"])

    def _lineage(self, context: dict) -> list[tuple[str, dict]]:
        chain = context["chain"]
        if not chain:
            return [("", {})]
        frontier = context["node"]
        result = []
        seen = set()
        current = self.manifest["chains"][chain].get("root_parent") \
            if frontier == f"base-{chain}" else frontier
        base_chain = chain
        while current and current in self.manifest["nodes"]:
            if current in seen:
                raise WorkflowError("cycle in workflow ancestry")
            seen.add(current)
            node = self.manifest["nodes"][current]
            base_chain = node["chain"]
            result.append((current, self.repository.load_state(node["state"])))
            current = node.get("parent")
        result.append((f"base-{base_chain}", self.repository.load_state(
            self.manifest["chains"][base_chain]["base_state"])))
        result.reverse()
        if frontier == f"base-{chain}" and result[-1][0] != frontier:
            result.append((frontier, self._state(frontier, chain)))
        return result

    def _collection(self, kind: str, path: list[str]) -> dict:
        if len(path) not in (2, 3, 4):
            raise WorkflowError("collection row requires [session,][source,]generation,row")
        generation, ordinal = path[-2:]
        if not re.fullmatch(r"g[0-9a-f]{64}", generation):
            raise WorkflowError("collection row requires its immutable g<SHA256> generation")
        row = _index(ordinal)
        if len(path) >= 3:
            _index(path[0])
        if len(path) == 4 and path[1] not in ("list", "user"):
            raise WorkflowError("collection source must be list or user")
        matches = [item for item in self.manifest["artifacts"].values()
                   if item["sha256"] == generation[1:] and self._metadata_visible(
                       "artifacts", item)]
        if not matches:
            raise MissingObject("collection generation is not retained in this workflow")
        artifact = matches[0]
        if _secret(artifact):
            raise WorkflowError("collection is sensitivity:secret")
        content = self.repository.store().read(artifact)
        if content.lstrip().startswith(b"{"):
            document = json.loads(content)
            rows = document.get(kind)
            if not isinstance(rows, list):
                raise WorkflowError(f"retained collection has no {kind} array")
            if row > len(rows):
                raise MissingObject("unknown collection row")
            if not isinstance(rows[row - 1], dict):
                raise WorkflowError("retained collection row must be an object")
            return rows[row - 1]
        try:
            with tempfile.TemporaryDirectory(prefix="cga-vid-") as directory:
                file = Path(directory) / "collection.sqlite"
                file.write_bytes(content)
                with sqlite3.connect(f"{file.as_uri()}?mode=ro&immutable=1", uri=True) as connection:
                    connection.row_factory = sqlite3.Row
                    table = "metadata" if kind == "databases" else "queries"
                    found = connection.execute(
                        f"SELECT rowid AS _row, * FROM {table} WHERE rowid = ?", (row,)).fetchone()
                    if found is None:
                        raise MissingObject("unknown collection row")
                    return dict(found)
        except sqlite3.Error as exc:
            raise WorkflowError(f"cannot read retained collection: {exc}") from exc

    def _value(self, root: str, path: list[str], state: dict, context: dict) -> dict:
        definition = BY_ID[root]
        kind = definition["kind"]
        exp = state.get("cgabench-experiment", {})
        if kind == "control":
            if path:
                index = _index(path[0])
                if not exp or exp.get("id") != context["experiment"] \
                        or index > len(exp["sessions"]):
                    raise MissingObject("control's session is not present")
                if len(path) > 2 or len(path) == 2 and path[1] not in ("D", "Q", "J", "R"):
                    raise WorkflowError("control path must be session[,stage]")
                return {**definition, "target": reference("sessions", *path)}
            return definition
        if kind == "workflow" and not path:
            return {"workflow": self.repository.root.name, "chain": context["chain"]}
        if kind in ("databases", "queries"):
            if not path:
                return definition
            if len(path) >= 3 and (
                    not exp or exp.get("id") != context["experiment"]
                    or _index(path[0]) > len(exp["sessions"])):
                raise MissingObject("collection's session is not present")
            return self._collection(kind, path)
        if kind in ("experiment", "comparison", "sessions"):
            if not exp or exp.get("id", "") != context["experiment"]:
                if not path:
                    return definition
                raise MissingObject("experiment is not present at this fact frontier")
            if kind == "experiment" and not path:
                return {key: value for key, value in exp.items() if key != "sessions"}
            if kind == "comparison" and not path:
                return exp["C"]
            if kind != "sessions":
                raise WorkflowError("use the Sessions VID to address sessions and cells")
            if not path:
                return {"name": exp["name"], "sessions": [
                    {"index": item["index"], "name": item["name"]} for item in exp["sessions"]]}
            index = _index(path[0])
            sessions = exp["sessions"]
            if index > len(sessions):
                raise MissingObject("unknown session")
            item = sessions[index - 1]
            if len(path) == 1:
                return item
            stage = path[1]
            if stage not in ("D", "Q", "J", "R"):
                raise WorkflowError("session child must be D, Q, J, or R")
            cell = item[stage]
            if len(path) == 2:
                return cell
            ordinal = _index(path[2])
            if len(path) != 3:
                raise WorkflowError("unexpected selectors after session job/item")
            archives = (item["D"].get("artifact") or {}).get("archives", [])
            if stage in ("D", "J", "R"):
                if ordinal > len(archives):
                    raise MissingObject("unknown session repository index")
                archive = archives[ordinal - 1]
                if stage == "D":
                    return archive
                if stage == "R":
                    jobs = (cell.get("artifact") or {}).get("ingestion", {}).get("jobs", [])
                    job = next((job for job in jobs
                                if job["repository"] == archive["repository"]), None)
                    if job is None:
                        raise MissingObject("repository results are not present yet")
                    return job
                submission = item["engine"].get("cgamr-submissions", {}).get(item["submission"], {})
                if not submission:
                    raise MissingObject("repository job has not been submitted yet")
                scanned = submission.get("status_response", {}).get("scanned_repositories", [])
                status = next((job for job in scanned if job.get("repository", {}).get(
                    "full_name") == archive["repository"]), {})
                return {"repository": archive["repository"],
                        "session_id": submission.get("session_id"),
                        "status": status or submission.get("status", cell["status"])}
            artifact = cell.get("artifact") or {}
            if not artifact.get("selection_sha256"):
                raise MissingObject("query selection is not present yet")
            return self._collection("queries", ["g" + artifact["selection_sha256"], str(ordinal)])
        if kind in ("steps", "attempts", "artifacts"):
            if not path:
                return definition
            if len(path) != 1:
                raise WorkflowError("expected one stable object index")
            index = _index(path[0]) - 1
            if kind == "steps":
                value = next((node for node in self.manifest["nodes"].values()
                              if node["chain"] == context["chain"] and node["sequence"] == index), None)
            else:
                key = f"attempt_{index}" if kind == "attempts" else f"artifact_{index}"
                value = self.manifest[kind].get(key)
            if value is None:
                raise MissingObject(f"unknown {kind} index")
            if kind == "steps" and value["id"] not in self._visible_nodes \
                    or kind != "steps" and not self._metadata_visible(kind, value):
                raise MissingObject("object is not present at this fact frontier")
            if _secret(value):
                raise WorkflowError("object is sensitivity:secret")
            return {key: item for key, item in value.items() if key != "tags"} \
                if kind == "artifacts" else value
        raise WorkflowError("unsupported VID selectors")

    def _metadata_visible(self, kind: str, value: dict) -> bool:
        bound = self._bounds[0 if kind == "attempts" else 1]
        if int(value["id"].split("_")[1]) >= bound:
            return False
        if kind == "attempts":
            return value.get("chain") == self._chain and (
                value.get("parent") is None or value["parent"] in self._visible_nodes)
        return value.get("source_node") is None or value["source_node"] in self._visible_nodes

    def inspect(self, text: str, *, chain: str | None = None, at: str | None = None) -> dict:
        short, qualifiers = decode(text)
        ref, path = parse_reference(short)
        root = ref.split(",")[0]
        if qualifiers.get("workflow", self.workflow) != self.workflow:
            raise WorkflowError("reference belongs to a different workflow")
        if "chain" in qualifiers and not qualifiers["chain"] and self.manifest["chains"]:
            raise WorkflowError("reference names a workflow without a chain")
        if chain and "chain" in qualifiers and self.repository.resolve_chain(
                self.manifest, qualifiers["chain"])[0] != self.repository.resolve_chain(
                    self.manifest, chain)[0]:
            raise WorkflowError("conflicting chain qualifiers")
        if at and qualifiers.get("at", at) != at:
            raise WorkflowError("conflicting fact frontiers")
        context = self.context(qualifiers.get("chain") or chain, qualifiers.get("at") or at)
        if qualifiers.get("experiment", context["experiment"]) != context["experiment"]:
            raise WorkflowError("reference belongs to a different experiment")
        if context["chain"] and context["node"] not in {
                name for name, _state in self._lineage(self.context(context["chain"]))}:
            raise WorkflowError("fact frontier is not on the qualified chain")
        frames = self._lineage(context)
        kind = BY_ID[root]["kind"]
        if kind in ("sessions", "experiment", "comparison") and any(
                _secret(self.manifest["nodes"].get(frontier, {})) for frontier, _state in frames):
            raise WorkflowError("element history includes sensitivity:secret evidence")
        self._chain = context["chain"]
        self._bounds = _frontier(context["frontier"])[1] if context["chain"] else (0, 0)
        facts = []
        latest = None
        self._visible_nodes = set()
        for frontier, state in frames:
            self._visible_nodes.add(frontier)
            try:
                value = self._value(root, path, state, context)
            except MissingObject:
                continue
            if value != latest:
                identity = {key: context[key] for key in ("workflow", "chain", "experiment")}
                digest = hashlib.sha256(canonical_json([ref, identity, frontier, value])).hexdigest()
                facts.append({"id": digest, "frontier": frontier, "value": value})
                latest = value
        if latest is None:
            raise MissingObject(f"no recorded facts for {ref}")
        return {"schema": SCHEMA, "ref": ref, "qualified_ref": qualified(context, ref),
                "pinned_ref": qualified(context, ref, context["frontier"]),
                "context": context, "kind": kind,
                "label": BY_ID[root]["label"], "properties": copy.deepcopy(latest),
                "facts": facts, "relations": self._relations(root, path, latest, context)}

    def _relations(self, root: str, path: list[str], value: dict, context: dict) -> list[dict]:
        links = []

        def add(relation, target):
            links.append({"relation": relation, "ref": target,
                          "qualified_ref": qualified(context, target, context["frontier"])})

        kind = BY_ID[root]["kind"]
        if path and kind not in ("databases", "queries"):
            add("parent", ",".join([root, *path[:-1]]))
        elif path:
            add("parent", root)
        if kind == "control" and path:
            add("target", value["target"])
        if kind == "sessions":
            if not path:
                for item in value.get("sessions", []):
                    add("contains", reference("sessions", item["index"]))
            elif len(path) == 1:
                for stage in ("D", "Q", "J", "R"):
                    add("contains", reference("sessions", path[0], stage))
            elif len(path) == 2:
                add("session", reference("sessions", path[0]))
                for stage, relation in (("D", "databases"), ("Q", "query"),
                                        ("J", "jobs"), ("R", "results")):
                    if stage != path[1]:
                        add(relation, reference("sessions", path[0], stage))
                state = self._state(context["frontier"], context["chain"])
                item = state["cgabench-experiment"]["sessions"][int(path[0]) - 1]
                for child in session_children(item, path[1]):
                    add("contains", child["ref"])
        if kind == "steps" and path:
            if value.get("parent"):
                parent = self.manifest["nodes"][value["parent"]]
                target = reference("steps", parent["sequence"] + 1)
                parent_context = self.context(parent["chain"], parent["id"])
                links.append({"relation": "previous", "ref": target,
                              "qualified_ref": qualified(
                                  parent_context, target, parent_context["frontier"])})
            for artifact in value.get("artifacts", []):
                if not _secret(self.manifest["artifacts"][artifact]):
                    add("produces", reference(
                        "artifacts", int(artifact.removeprefix("artifact_")) + 1))
        if kind == "artifacts" and path and value.get("source_node"):
            source = self.manifest["nodes"][value["source_node"]]
            if not _secret(source):
                source_context = self.context(source["chain"], source["id"])
                target = reference("steps", source["sequence"] + 1)
                links.append({"relation": "produced_by", "ref": target,
                              "qualified_ref": qualified(
                                  source_context, target, source_context["frontier"])})
        if kind == "experiment":
            add("sessions", reference("sessions"))
            add("comparison", reference("comparison"))
        if kind == "workflow":
            for child in ("steps", "attempts", "artifacts", "experiment"):
                add("contains", reference(child))
        if not path and kind in ("steps", "attempts", "artifacts"):
            for item in self.manifest[kind if kind != "steps" else "nodes"].values():
                if kind == "steps" and item["chain"] == context["chain"] \
                        and item["id"] in self._visible_nodes and not _secret(item):
                    add("contains", reference(kind, item["sequence"] + 1))
                elif kind == "attempts" and self._metadata_visible(kind, item) and not _secret(item):
                    add("contains", reference(kind, int(item["id"].removeprefix("attempt_")) + 1))
                elif kind == "artifacts" and self._metadata_visible(kind, item) and not _secret(item):
                    add("contains", reference(kind, int(item["id"].removeprefix("artifact_")) + 1))
        return links


class RawRepository(Repository):
    """Append observations of a legacy mutable session file without rewriting it."""

    def __init__(self, source: Path):
        self.source = source.expanduser().resolve()
        super().__init__(cga_root(),
                         self.source.parent / ".cgabench-runtime" / self.source.name / "vid")

    def load_config(self):
        return {"object_store": {"root": str(self.cga_dir / "objects")}}

    def observe(self, state: dict) -> None:
        with self.locked():
            if not self.manifest_path.exists():
                empty = self.store().put(canonical_json({}))
                manifest = {"format_version": 1, "nodes": {}, "attempts": {}, "artifacts": {},
                            "next_artifact_id": 0, "next_attempt_id": 0, "next_chain_id": 1,
                            "chains": {"raw": {"id": "raw", "number": 0, "head": None,
                                               "next_sequence": 0, "base_state": empty}}}
                self.write_manifest(manifest)
                self._set_head_chain("raw")
            manifest = self.load_manifest()
            chain = manifest["chains"]["raw"]
            if self.load_state(self.state_reference(manifest, chain)) != state:
                self.record_state(manifest, "raw", chain, state,
                                  ["cga", "bench", "observe"], "session-file")


def main(argv=None):
    from command_help import enhance_parser

    arguments = list(sys.argv[1:] if argv is None else argv)
    command = next((value for value in arguments if value in ("show", "related", "open")),
                   "show")
    parser = argparse.ArgumentParser(
        prog="cga", description=__doc__,
        epilog="Example: cga show :f3a,1,J; cga related '(:f3a 1 :J)'. "
               "Use cga show --registry to discover permanent root identifiers.")
    parser.add_argument("command", choices=("show", "related", "open"),
                        help=argparse.SUPPRESS)
    parser.add_argument("reference", nargs="?")
    parser.add_argument("--registry", action="store_true", help="list permanent VID roots (show only)")
    parser.add_argument("--session-file", help="observe a raw CGAST file outside a workflow")
    parser.add_argument("--chain")
    parser.add_argument("--at", help="pin inspection to a node or returned fact frontier")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--url", help="loopback Bench or Unified View origin for open")
    parser.add_argument("--print-url", action="store_true")
    enhance_parser(parser, command)
    args = parser.parse_args(arguments)
    try:
        if args.registry:
            if args.command != "show" or args.reference:
                raise WorkflowError("--registry is used as cga show --registry")
            if args.json or os.environ.get("CGA_OUTPUT_JSON") == "1":
                print(json.dumps({"schema": "cga.vid.registry.v1", "elements": REGISTRY}, indent=2))
            else:
                for entry in REGISTRY:
                    print(f"{entry['vid']}  {entry['label']}")
            return 0
        if not args.reference:
            raise WorkflowError("an element reference is required")
        _short, context = decode(args.reference)
        if args.session_file:
            repository = RawRepository(Path(args.session_file))
        elif context.get("workflow"):
            cga_dir = Path(context["workflow"]).resolve()
            raw = RawRepository(cga_dir)
            repository = raw if cga_dir.is_file() or raw.manifest_path.is_file() \
                else Repository(cga_dir.parent, cga_dir)
        else:
            repository = Repository.discover()
        if isinstance(repository, RawRepository) and not (context.get("at") or args.at):
            repository.observe(json.loads(repository.source.read_text()))
        document = Space(repository).inspect(args.reference, chain=args.chain, at=args.at)
        if args.command == "open":
            default = "http://127.0.0.1:8610" if document["kind"] in (
                "sessions", "experiment", "comparison") else \
                f"http://127.0.0.1:{os.environ.get('CGA_CGAUV_PORT', '8609')}"
            origin = args.url or os.environ.get("CGA_BENCH_URL") or default
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") \
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                raise WorkflowError("--url must be a loopback HTTP viewer origin")
            url = origin.rstrip("/") + "/vid?" + urlencode({"ref": document["pinned_ref"]})
            if args.print_url:
                print(url)
            elif not webbrowser.open(url, new=2):
                raise WorkflowError("could not open browser; use --print-url")
            return 0
        value = document["relations"] if args.command == "related" else document
        if args.json or os.environ.get("CGA_OUTPUT_JSON") == "1":
            print(json.dumps(value, indent=2, sort_keys=True))
        elif args.command == "related":
            for link in value:
                print(f"{link['relation']}: {link['ref']}\n  {link['qualified_ref']}")
        else:
            print(f"{document['ref']}  {document['label']}\n"
                  f"Reference: {document['pinned_ref']}\n"
                  f"Context: {json.dumps(document['context'], sort_keys=True)}\n"
                  f"Facts: {len(document['facts'])}\n")
            print(json.dumps(document["properties"], indent=2, sort_keys=True))
            print("\nRecorded facts:")
            print(json.dumps(document["facts"], indent=2, sort_keys=True))
        return 0
    except (WorkflowError, OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())

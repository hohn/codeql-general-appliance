"""Exact, provenance-preserving SARIF finding comparisons."""

from __future__ import annotations

import collections
import copy
import json

import cgast
from cgawf.repository import utc_now
from workflow import WorkflowError, load_json

from . import model


def findings(engine: dict, name: str) -> list[dict]:
    ingestion = engine.get("cgasi-ingestions", {}).get(name)
    if not isinstance(ingestion, dict) or not isinstance(ingestion.get("jobs"), list):
        raise WorkflowError("missing completed SARIF ingestion")
    output = []
    for job in ingestion["jobs"]:
        sarif_path = cgast.resolve(job["artifacts"]["sarif"])
        sarif = load_json(sarif_path)
        runs = sarif.get("runs")
        if not isinstance(runs, list):
            raise WorkflowError(f"{sarif_path}: runs must be an array")
        for run_index, run in enumerate(runs):
            if not isinstance(run, dict) or not isinstance(run.get("results", []), list):
                raise WorkflowError(f"{sarif_path}: invalid SARIF run")
            rules = run.get("tool", {}).get("driver", {}).get("rules", [])
            for result_index, result in enumerate(run.get("results", [])):
                if not isinstance(result, dict):
                    raise WorkflowError(f"{sarif_path}: invalid SARIF result")
                rule = result.get("ruleId")
                if rule is None and isinstance(result.get("ruleIndex"), int):
                    index = result["ruleIndex"]
                    if not 0 <= index < len(rules):
                        raise WorkflowError(f"{sarif_path}: invalid ruleIndex")
                    rule = rules[index].get("id")
                locations = []
                for location in result.get("locations", []):
                    physical = location.get("physicalLocation", {})
                    artifact = physical.get("artifactLocation", {})
                    uri = artifact.get("uri")
                    uri_base = artifact.get("uriBaseId")
                    if uri is None and isinstance(artifact.get("index"), int):
                        index = artifact["index"]
                        artifacts = run.get("artifacts", [])
                        if not 0 <= index < len(artifacts):
                            raise WorkflowError(f"{sarif_path}: invalid artifact index")
                        indexed = artifacts[index].get("location", {})
                        uri = indexed.get("uri")
                        uri_base = uri_base or indexed.get("uriBaseId")
                    locations.append({
                        "uri": uri,
                        "uriBaseId": uri_base,
                        "region": physical.get("region", {}),
                        "logicalLocations": location.get("logicalLocations", []),
                    })
                identity = {
                    "repository": job["repository"], "rule": rule,
                    "locations": locations, "message": result.get("message", {}),
                }
                output.append({
                    "identity": identity, "result": result,
                    "provenance": {"repository": job["repository"],
                                   "sarif": cgast.rel(sarif_path),
                                   "run_index": run_index, "result_index": result_index},
                })
    return output


def identity(finding: dict) -> str:
    return json.dumps(finding["identity"], sort_keys=True, separators=(",", ":"))


def compare(state: dict, indices: list[int]) -> dict:
    exp = model.experiment(state)
    model.fixed_stage(state)
    if not indices:
        indices = [item["index"] for item in exp["sessions"]
                   if item["R"]["status"] == "complete"]
    if len(set(indices)) != len(indices):
        raise WorkflowError("comparison needs at least two distinct complete sessions")
    if 1 not in indices:
        indices = [1, *indices]
    else:
        indices = [1, *(index for index in indices if index != 1)]
    if len(indices) < 2:
        raise WorkflowError("comparison needs at least two distinct complete sessions")
    selected = [model.session(state, index) for index in indices]
    if selected[0]["R"]["status"] != "complete":
        raise WorkflowError("comparison requires completed S1 reference results")
    if any(item["R"]["status"] != "complete" for item in selected):
        raise WorkflowError("comparison accepts only complete result cells")
    for item in selected:
        model.validate_session(state, item, complete=True)
        for stage in ("D", "Q"):
            model.verify_input(stage, item[stage]["artifact"])
        artifact = item["R"]["artifact"]
        if model.fingerprint(cgast.resolve(artifact["results"])) != artifact["sha256"]:
            raise WorkflowError(f"completed result evidence changed for S[{item['index']}]")
    documents = [load_json(cgast.resolve(item["R"]["artifact"]["results"]))
                 for item in selected]
    bags = [collections.Counter(identity(row) for row in doc["findings"])
            for doc in documents]
    common = bags[0].copy()
    for bag in bags[1:]:
        common &= bag
    baseline = documents[0]["findings"]

    def take(rows: list[dict], wanted: collections.Counter,
             matched: collections.Counter | None = None) -> list[dict]:
        remaining = wanted.copy()
        skipped = matched.copy() if matched is not None else collections.Counter()
        out = []
        for row in rows:
            key = identity(row)
            if skipped[key] > 0:
                skipped[key] -= 1
                continue
            if remaining[key] > 0:
                out.append(copy.deepcopy(row))
                remaining[key] -= 1
        return out

    document = {
        "version": 1, "created_at": utc_now(),
        "mode": exp["mode"], "reference": 1,
        "policy": "exact repository, rule, physical/logical locations and message; multiset",
        "baseline": f"E.S[{indices[0]}].R",
        "inputs": [{"address": f"E.S[{item['index']}].R", "name": item["name"],
                    "user": item["user"], "artifact": item["R"]["artifact"],
                    "database": item["D"]["artifact"], "query": item["Q"]["artifact"],
                    "cloned_from": {stage: copy.deepcopy(item[stage]["cloned_from"])
                                    for stage in ("D", "Q") if item[stage].get("cloned_from")},
                    "job": item["J"]["artifact"]} for item in selected],
        "common": take(baseline, common), "sessions": [],
    }
    for finding in document["common"]:
        key = identity(finding)
        finding["occurrences"] = [
            {"address": f"E.S[{item['index']}].R", "provenance": row["provenance"]}
            for item, doc in zip(selected, documents)
            for row in doc["findings"] if identity(row) == key
        ]
    for item, doc, bag in zip(selected, documents, bags):
        matched = bag & bags[0]
        document["sessions"].append({
            "address": f"E.S[{item['index']}].R",
            "finding_count": sum(bag.values()),
            "added": take(doc["findings"], bag - bags[0], matched),
            "removed": take(baseline, bags[0] - bag, matched),
        })
    path = cgast.new_tempfile(prefix="cgabench-comparison-", suffix=".json")
    model.save(path, document)
    comparison = exp["C"]
    comparison["status"] = "complete"
    comparison["inputs"] = [entry["address"] for entry in document["inputs"]]
    comparison["artifact"] = {"results": cgast.rel(path)}
    comparison["history"].append({"at": document["created_at"],
                                   "inputs": list(comparison["inputs"]),
                                   "artifact": comparison["artifact"].copy()})
    return document

"""Permanent opaque IDs. Retire entries rather than reassigning their IDs."""

import re


def entry(vid, kind, label, bench="", unified="", help_selector=""):
    selectors = {"bench": bench, "unified": unified}
    if help_selector:
        selectors["help"] = help_selector
    return {"vid": vid, "kind": kind, "label": label,
            "selectors": selectors}


REGISTRY = [
    entry(":f3a", "sessions", "Sessions", "#collapse-sessions"),
    entry(":8x1", "experiment", "Experiment", "#experiment"),
    entry(":a9x", "workflow", "Workflow", "#collapse-workflow", "#workflow-meta"),
    entry(":h7m", "steps", "Workflow commands", "", "#collapse-all"),
    entry(":r6t", "attempts", "Failed command attempts"),
    entry(":91c", "artifacts", "Retained artifacts"),
    entry(":6nb", "databases", "Database collection", "#database-input-source", "#show-databases"),
    entry(":u2q", "queries", "Query collection", "#query-input-source", "#show-queries"),
    entry(":b4z", "comparison", "Comparison", "#collapse-comparison"),
    entry(":2kf", "control", "Reload", "#reload", "#reload"),
    entry(":7vj", "control", "MRVA summary", "#collapse-system", "#collapse-system"),
    entry(":m3d", "control", "MRVA system view", "#sysview-link", "#sysview-link"),
    entry(":k81", "control", "Infrastructure", "#collapse-infrastructure"),
    entry(":z5b", "control", "Prepare services", '[data-phase="setup"]'),
    entry(":4nm", "control", "Check services", '[data-phase="check"]'),
    entry(":p6y", "control", "Stop services", '[data-phase="stop"]'),
    entry(":0cp", "control", "Infrastructure detail", "#show-infrastructure"),
    entry(":j92", "control", "Experiment mode", "#experiment-mode"),
    entry(":9hk", "control", "Add session", "#new-session"),
    entry(":v3e", "control", "Compare sessions", "#compare"),
    entry(":51w", "control", "Comparison detail", "#show-comparison"),
    entry(":e7n", "control", "Detail view", "#address", "#detail-title"),
    entry(":3ry", "control", "Clone fixed input", "#clone-input"),
    entry(":t5k", "control", "Input library source", "#input-source"),
    entry(":w8c", "control", "Catalogue discovery", "#catalogue-options"),
    entry(":q60", "control", "Rescan catalogues", "#rescan-catalogues"),
    entry(":n2a", "control", "Load catalogue", "#load-catalogue"),
    entry(":c4j", "control", "Index query library", "#index-library"),
    entry(":y9g", "control", "Copy query", "#copy-query"),
    entry(":1pd", "control", "Create query", "#create-query"),
    entry(":s7u", "control", "Save query", "#save-query"),
    entry(":5x8", "control", "Search library", "#collection-search"),
    entry(":l0f", "control", "Previous library page", "#previous-page"),
    entry(":d6v", "control", "Next library page", "#next-page"),
    entry(":83r", "control", "Accept selection", "#use-selection"),
    entry(":x2m", "control", "Record work", "#work"),
    entry(":g4p", "control", "Result filters", "#result-filters"),
    entry(":a75", "control", "Clear result filters", "#clear-result-filters"),
    entry(":6ts", "control", "Read-only result SQL", "#result-sql"),
    entry(":f0y", "control", "Previous result page", "#result-previous"),
    entry(":u9d", "control", "Next result page", "#result-next"),
    entry(":28h", "control", "Open result editor", "#open-editor"),
    entry(":o3b", "control", "Resize workflow pane"),
    entry(":97a", "control", "Workflow state viewer", "", "#workflow-state-link"),
    entry(":k5e", "control", "Dashboard replay", "", "#replay-link"),
    entry(":3wm", "control", "Data-flow graph", "", "#dfg-link"),
    entry(":z1r", "control", "Control-flow graph", "", "#cfg-link"),
    entry(":b8u", "control", "Flow source", "", "#source-link"),
    entry(":v6c", "control", "Theme", "", "#theme-select"),
    entry(":04n", "control", "Workflow search", "", "#workflow-search"),
    entry(":i2s", "control", "Audience filter", "", "#audience-filter"),
    entry(":8pq", "control", "Reveal selected command", "", "#detail-heading"),
    entry(":r0x", "control", "Resize transcript pane"),
    entry(":6ja", "control", "Command transcript", "", "#terminal-meta"),
    entry(":p9g", "control", "Continue or check session", '[data-mutation="advance"]'),
    entry(":w4n", "control", "Edit session input", '[data-mutation="edit"]'),
    entry(":7bs", "control", "Clone session input", '[data-mutation="clone"]'),
    entry(":j6q", "control", "Select session for comparison", 'input[data-session]'),
    entry(":e0v", "control", "Infrastructure preflight", '[data-phase="preflight"]'),
    entry(":9ca", "control", "Reset infrastructure", '[data-phase="reset"]'),
    entry(":0rx", "control", "Build infrastructure", '[data-phase="build"]'),
    entry(":s2n", "control", "Start infrastructure", '[data-phase="start"]'),
    entry(":c8k", "control", "Infrastructure logs", '[data-phase="logs"]'),
    entry(":y3p", "control", "Infrastructure info", '[data-phase="info"]'),
    entry(":4ul", "control", "Clean up infrastructure", '[data-phase="cleanup"]'),
    entry(":q8v", "control", "Copilot assistant", "#collapse-assistant"),
    entry(":n4k", "control", "Reconnect assistant", "#assistant-connect"),
    entry(":5pz", "control", "Start assistant", "#assistant-start"),
    entry(":c7w", "control", "Stop assistant", "#assistant-stop"),
    entry(":vy8", "help-pages", "Help pages", help_selector="[data-help-ref]:not([data-help-document-ref]):not([data-help-group-ref])"),
    entry(":fy5", "help-documents", "Help documents", help_selector="[data-help-document-ref]"),
    entry(":9qr", "help-groups", "Help task groups", help_selector="[data-help-group-ref]"),
    entry(":nno", "control", "Help browser", help_selector=".app-title h1"),
    entry(":ej5", "control", "Help collapse all", help_selector="#collapse-all"),
    entry(":ve1", "control", "Help search", help_selector="#help-search"),
    entry(":f1q", "control", "Help regex search", help_selector="#help-search label"),
    entry(":nrs", "control", "Help Start here", help_selector="#start-outline > summary"),
    entry(":efk", "control", "Help LLM start here", help_selector="#llm-start-outline > summary"),
    entry(":xnw", "control", "Help task groups", help_selector="#task-heading"),
    entry(":l2b", "control", "Help Reference", help_selector="#reference-heading"),
    entry(":e20", "control", "Help system tests", help_selector="#system-tests > summary"),
    entry(":02d", "control", "Help Original write-ups", help_selector="#tutorial-documents > summary"),
    entry(":9g2", "control", "Help command pane", help_selector="#top-title"),
    entry(":qlk", "control", "Help subcommand pane", help_selector="#bottom-title"),
]

BY_ID = {item["vid"]: item for item in REGISTRY}
ROOTS = {item["kind"]: item["vid"] for item in REGISTRY if item["kind"] != "control"}
if len(BY_ID) != len(REGISTRY) or any(
        not re.fullmatch(r":[0-9a-z]{3}", item["vid"]) for item in REGISTRY):
    raise RuntimeError("invalid or duplicate permanent CGA VID")


def reference(kind, *path):
    return ",".join([ROOTS[kind], *(str(part) for part in path)])


def step_reference(value):
    return reference("attempts", int(value["id"].removeprefix("attempt_")) + 1) \
        if value["id"].startswith("attempt_") \
        else reference("steps", int(value["sequence"]) + 1)

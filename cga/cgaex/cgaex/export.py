"""Render the cumulative SARIF store into stable exchange formats."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


class ExportError(RuntimeError):
    """The CGAST cannot form a complete analysis export."""


def _submissions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    ingestions = state.get("cgasi-ingestions", {})
    if not isinstance(ingestions, dict) or not ingestions:
        raise ExportError("cgasi-ingestions must be a non-empty object")
    result: List[Dict[str, Any]] = []
    for name in sorted(ingestions):
        item = ingestions[name]
        if not isinstance(item, dict):
            raise ExportError(f"ingestion {name!r} must be an object")
        raw_jobs = item.get("jobs", [])
        if not isinstance(raw_jobs, list) or not raw_jobs:
            raise ExportError(f"ingestion {name!r} has no jobs")
        jobs = []
        for index, job in enumerate(raw_jobs, start=1):
            if not isinstance(job, dict):
                raise ExportError(f"ingestion {name!r} job {index} "
                                  "must be an object")
            artifacts = job.get("artifacts")
            if not isinstance(artifacts, dict) or not all(
                    isinstance(artifacts.get(kind), str)
                    for kind in ("archive", "sarif", "sqlite")):
                raise ExportError(f"ingestion {name!r} job {index} has "
                                  "invalid artifacts")
            if not isinstance(job.get("repository"), str) \
                    or not isinstance(job.get("finding_count"), int):
                raise ExportError(f"ingestion {name!r} job {index} has "
                                  "invalid repository or finding count")
            jobs.append({
                "index": index,
                "repository": job["repository"],
                "status": job.get("status"),
                "finding_count": job["finding_count"],
                "mrva_result_count": job.get("mrva_result_count"),
                "artifact_size_bytes": job.get("artifact_size_bytes"),
                "artifacts": artifacts,
            })
        finding_count = item.get("finding_count")
        if not isinstance(finding_count, int) or finding_count != sum(
                job["finding_count"] for job in jobs):
            raise ExportError(f"ingestion {name!r} has inconsistent "
                              "finding count")
        result.append({
            "name": item.get("name", name),
            "user": item.get("user"),
            "session_id": item.get("session_id"),
            "language": item.get("language"),
            "status": item.get("status"),
            "query_pack": item.get("query_pack"),
            "job_count": len(jobs),
            "finding_count": finding_count,
            "jobs": jobs,
        })
    return result


def _finding_context(
        submissions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    context: Dict[str, Dict[str, Any]] = {}
    for submission in submissions:
        for job in submission["jobs"]:
            artifacts = job.get("artifacts", {})
            sarif = artifacts.get("sarif") if isinstance(artifacts, dict) \
                else None
            if not isinstance(sarif, str):
                continue
            context[Path(sarif).name] = {
                "submission": submission.get("name"),
                "session_id": submission.get("session_id"),
                "job_index": job.get("index"),
                "repository": job.get("repository"),
            }
    return context


def _enriched_findings(
        findings: List[Dict[str, Any]],
        submissions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    context = _finding_context(submissions)
    result = []
    for finding in findings:
        row = dict(finding)
        file_name = str(finding.get("file_name") or "")
        if file_name not in context:
            raise ExportError(f"finding references unknown SARIF {file_name!r}")
        row.update(context[file_name])
        result.append(row)
    return result


def llm_document(state: Dict[str, Any],
                 findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a self-contained analysis document with zero-result jobs."""
    submissions = _submissions(state)
    enriched = _enriched_findings(findings, submissions)
    users = sorted({str(item.get("user")) for item in submissions
                    if item.get("user")})
    findings_by_user = Counter(str(row.get("user")) for row in findings
                               if row.get("user"))
    for user in users:
        findings_by_user.setdefault(user, 0)
    jobs = [job for submission in submissions for job in submission["jobs"]]
    return {
        "schema": "cga.analysis-export.v2",
        "summary": {
            "submission_count": len(submissions),
            "job_count": len(jobs),
            "finding_count": len(findings),
            "zero_finding_job_count": sum(
                int(job.get("finding_count", 0)) == 0 for job in jobs),
            "users": users,
            "findings_by_user": dict(sorted(findings_by_user.items())),
            "rules": dict(sorted(Counter(
                str(row.get("rule_id")) for row in findings
                if row.get("rule_id")
            ).items())),
            "jobs_by_status": dict(sorted(Counter(
                str(job.get("status") or "unknown") for job in jobs
            ).items())),
        },
        "submissions": submissions,
        "findings": enriched,
    }


def render_llm(state: Dict[str, Any],
               findings: List[Dict[str, Any]]) -> str:
    return json.dumps(
        llm_document(state, findings),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"


def _cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", r"\|")


def render_human(state: Dict[str, Any],
                 findings: List[Dict[str, Any]]) -> str:
    """Return a compact Markdown report suitable for review or archival."""
    submissions = _submissions(state)
    users = Counter(str(row.get("user") or "(unknown)") for row in findings)
    for submission in submissions:
        users.setdefault(str(submission.get("user") or "(unknown)"), 0)
    rules = Counter(str(row.get("rule_id") or "(unknown)") for row in findings)
    lines = [
        "# CGA analysis results",
        "",
        f"Findings: **{len(findings)}**",
        "",
        "## Summary",
        "",
        "| Dimension | Value | Count |",
        "| --- | --- | ---: |",
    ]
    for user, count in sorted(users.items()):
        lines.append(f"| user | {_cell(user)} | {count} |")
    for rule, count in sorted(rules.items()):
        lines.append(f"| rule | {_cell(rule)} | {count} |")
    lines.extend([
        "",
        "## Jobs",
        "",
        "| Submission | User | Repository | Status | Findings |",
        "| --- | --- | --- | --- | ---: |",
    ])
    for submission in submissions:
        for job in submission["jobs"]:
            lines.append(
                f"| {_cell(submission.get('name'))} | "
                f"{_cell(submission.get('user'))} | "
                f"{_cell(job.get('repository'))} | "
                f"{_cell(job.get('status'))} | "
                f"{_cell(job.get('finding_count', 0))} |"
            )
    if not findings:
        lines.extend(["", "No findings were produced."])
        return "\n".join(lines) + "\n"
    context = _finding_context(submissions)
    lines.extend([
        "",
        "## Findings",
        "",
        "| Submission | User | Repository | Rule | Kind | Location |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in findings:
        location = f"{row.get('uri', '')}:{row.get('start_line', '')}"
        item = context.get(str(row.get("file_name") or ""), {})
        lines.append(
            f"| {_cell(item.get('submission'))} | {_cell(row.get('user'))} | "
            f"{_cell(item.get('repository'))} | {_cell(row.get('rule_id'))} | "
            f"{_cell(row.get('kind'))} | {_cell(location)} |"
        )
    return "\n".join(lines) + "\n"

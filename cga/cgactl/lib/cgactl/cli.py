from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

from command_help import enhance_parser

from .db import Database, DatabaseError
from .collection import (PromotionError, collection_status, promote,
                         promote_pending, reconcile)
from .incus import (IncusError, prepare as prepare_container,
                    verify_snapshot)
from .matrix import build_matrix
from .resources import measure
from .service import SNAPSHOT_SQL, serve

ROOT = Path(__file__).resolve().parents[2]
SHARE = ROOT / "share"


def _emit(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _json_file(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cgactl")
    p.add_argument("--database-url", help="PostgreSQL DSN; defaults to "
                   "CGACTL_DATABASE_URL/standard PG environment")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("db-init", help="install or upgrade the schema")
    m = sub.add_parser("matrix", help="generate the CVE job matrix")
    m.add_argument("--cves-dir", default="examples/cves")
    m.add_argument("--toolchain-digest", required=True)
    m.add_argument("--source-identity", choices=("tree", "descriptor"),
                   default="tree")
    m.add_argument("--output")
    load = sub.add_parser("jobs-load", help="idempotently load a manifest")
    load.add_argument("manifest")
    reg = sub.add_parser("builder-register")
    reg.add_argument("--builder", required=True)
    reg.add_argument("--metadata", default="{}")
    claim = sub.add_parser("claim", help="claim at most one job")
    claim.add_argument("--builder", required=True)
    claim.add_argument("--lease-seconds", type=int, default=300)
    claim.add_argument("--metadata", default="{}")
    claim.add_argument("--lane", choices=(
        "static", "llm-repair", "master-recovery"), default="static")
    renew = sub.add_parser("renew")
    _lease_args(renew)
    renew.add_argument("--lease-seconds", type=int, default=300)
    phase = sub.add_parser("phase")
    _lease_args(phase)
    phase.add_argument("--status", required=True,
                       choices=("preparing", "building", "validating"))
    finish = sub.add_parser("finish")
    _lease_args(finish)
    finish.add_argument("--status", required=True, choices=(
        "succeeded", "succeeded-after-repair", "failed-source",
        "failed-dependencies", "failed-build", "failed-extraction",
        "failed-validation", "timed-out", "infrastructure-error"))
    finish.add_argument("--result", default="{}",
                        help="result JSON object or @file")
    retry = sub.add_parser("retry", help="requeue one terminal job")
    retry.add_argument("--job-id", required=True)
    retry.add_argument("--reason", required=True)
    sweep = sub.add_parser(
        "sweep", help="advance failed jobs into the next execution lane")
    sweep.add_argument("--from-lane", required=True, choices=(
        "static", "llm-repair", "master-recovery"))
    sweep.add_argument("--to-lane", required=True, choices=(
        "llm-repair", "master-recovery"))
    sweep.add_argument("--reason", required=True)
    sweep.add_argument("--limit", type=int, default=100)
    sweep.add_argument("--resource-profile")
    sweep.add_argument("--base-snapshot")
    sweep.add_argument("--exclusive-host", action=argparse.BooleanOptionalAction,
                       default=None)
    configure = sub.add_parser("job-config")
    configure.add_argument("--job-id", required=True)
    configure.add_argument("--lane", required=True, choices=(
        "static", "llm-repair", "master-recovery"))
    configure.add_argument("--resource-profile", default="default")
    configure.add_argument("--base-snapshot")
    configure.add_argument("--exclusive-host", action="store_true")
    configure_all = sub.add_parser("jobs-config")
    configure_all.add_argument("--lane", required=True, choices=(
        "static", "llm-repair", "master-recovery"))
    configure_all.add_argument("--resource-profile", default="default")
    configure_all.add_argument("--base-snapshot", required=True)
    configure_all.add_argument("--exclusive-host", action="store_true")
    configure_all.add_argument("--limit", type=int, default=100000)
    snapshot = sub.add_parser("snapshot-register")
    snapshot.add_argument("--snapshot-id", required=True)
    snapshot.add_argument("--container", required=True)
    snapshot.add_argument("--snapshot", required=True)
    snapshot.add_argument("--toolchain-digest", required=True)
    snapshot.add_argument("--metadata", default="{}")
    snapshot.add_argument("--incus", default=os.environ.get(
        "CGACTL_INCUS", "incus"))
    profile = sub.add_parser("resource-profile-set")
    profile.add_argument("--name", required=True)
    profile.add_argument("--cpu", type=int)
    profile.add_argument("--memory-bytes", type=int)
    profile.add_argument("--disk-bytes", type=int)
    profile.add_argument("--exclusive-host", action="store_true")
    profile.add_argument("--max-concurrent", type=int)
    profile.add_argument("--metadata", default="{}")
    prep = sub.add_parser(
        "container-prepare", help="restore, limit, and start a claimed builder")
    _lease_args(prep)
    prep.add_argument("--container", required=True)
    prep.add_argument("--reserve-cpu", type=int, default=int(os.environ.get(
        "CGACTL_HOST_RESERVE_CPU", "2")))
    prep.add_argument("--reserve-memory-bytes", type=int, default=int(
        os.environ.get("CGACTL_HOST_RESERVE_MEMORY_BYTES", str(4 * 1024**3))))
    prep.add_argument("--reserve-disk-bytes", type=int, default=int(
        os.environ.get("CGACTL_HOST_RESERVE_DISK_BYTES", str(20 * 1024**3))))
    prep.add_argument("--incus", default=os.environ.get("CGACTL_INCUS", "incus"))
    promotion = sub.add_parser(
        "promote", help="verify and add a successful job to a collection")
    promotion.add_argument("--job-id", required=True)
    promotion.add_argument("--collection", default="db-collection.local")
    promotion.add_argument("--codeql", default=os.environ.get(
        "CGACTL_CODEQL", "codeql"))
    auto = sub.add_parser(
        "promote-auto", help="promote successful jobs from the host queue")
    auto.add_argument("--collection", default="db-collection.local")
    auto.add_argument("--codeql", default=os.environ.get(
        "CGACTL_CODEQL", "codeql"))
    auto.add_argument("--once", action="store_true")
    auto.add_argument("--interval", type=float, default=5.0)
    collection = sub.add_parser(
        "collection-status", help="summarize and optionally verify collection")
    collection.add_argument("--collection", default="db-collection.local")
    collection.add_argument("--verify", action="store_true")
    audit = sub.add_parser(
        "collection-reconcile",
        help="compare successful controller jobs with the collection")
    audit.add_argument("--collection", default="db-collection.local")
    sub.add_parser("requeue-expired")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    failures = sub.add_parser(
        "failures", help="export failed jobs and immutable attempt history")
    failures.add_argument("--disposition", choices=(
        "awaiting-llm", "escalated"))
    failures.add_argument("--lane", choices=(
        "static", "llm-repair", "master-recovery"))
    failures.add_argument("--output")
    web = sub.add_parser("serve")
    web.add_argument("--host", default=os.environ.get(
        "CGACTL_HOST", "127.0.0.1"))
    web.add_argument("--port", type=int, default=int(os.environ.get(
        "CGACTL_PORT", "8520")))
    web.add_argument("--collection", default="db-collection.local")
    measured = sub.add_parser(
        "measure", help="run a command with per-second CPU/RAM telemetry")
    measured.add_argument("--output-dir", required=True)
    measured.add_argument("--interval", type=float, default=1.0)
    measured.add_argument("--log")
    measured.add_argument(
        "--cgast-filter", action="store_true",
        help="pass child stdout through unchanged and emit summary to stderr")
    measured.add_argument("argv", nargs=argparse.REMAINDER)
    return enhance_parser(p, "ctl")


def _lease_args(p):
    p.add_argument("--builder", required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--lease-token", required=True)


def _value(raw: str):
    if raw.startswith("@"):
        return _json_file(raw[1:])
    return json.loads(raw)


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.command == "measure":
        command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        try:
            code, summary = measure(
                command, Path(args.output_dir).expanduser().resolve(),
                args.interval,
                Path(args.log).expanduser().resolve() if args.log else None,
                passthrough_stdout=args.cgast_filter)
            if args.cgast_filter:
                print(json.dumps(
                    summary, indent=2, sort_keys=True, default=str),
                    file=sys.stderr)
            else:
                _emit(summary)
            return code
        except (OSError, ValueError) as exc:
            print(f"cgactl: error: {exc}", file=sys.stderr)
            return 1
    db = Database(args.database_url)
    try:
        if args.command == "db-init":
            db.install_schema(SHARE / "schema.sql")
            print("cgactl: schema ready")
        elif args.command == "matrix":
            doc = build_matrix(Path(args.cves_dir), args.toolchain_digest,
                               args.source_identity)
            text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
        elif args.command == "jobs-load":
            doc = _json_file(args.manifest)
            result = db.json("SELECT cgactl.load_jobs(:'doc'::jsonb)::text;",
                             {"doc": doc})
            _emit(result)
        elif args.command == "builder-register":
            result = db.json(
                "SELECT cgactl.register_builder(:'builder', "
                ":'metadata'::jsonb)::text;",
                {"builder": args.builder, "metadata": _value(args.metadata)})
            _emit(result)
        elif args.command == "claim":
            result = db.json(
                "SELECT cgactl.claim_job_v2(:'builder', :'token', "
                ":'lease'::integer, :'lane', :'metadata'::jsonb)::text;",
                {"builder": args.builder, "token": secrets.token_hex(24),
                 "lease": args.lease_seconds,
                 "lane": args.lane,
                 "metadata": _value(args.metadata)})
            _emit(result)
        elif args.command == "renew":
            result = db.json(
                "SELECT cgactl.renew_lease(:'builder', :'job', :'token', "
                ":'lease'::integer)::text;", _lease_vars(args) | {
                    "lease": args.lease_seconds})
            _emit(result)
        elif args.command == "phase":
            result = db.json(
                "SELECT cgactl.set_phase(:'builder', :'job', :'token', "
                ":'status')::text;", _lease_vars(args) | {
                    "status": args.status})
            _emit(result)
        elif args.command == "finish":
            result = db.json(
                "SELECT cgactl.finish_job(:'builder', :'job', :'token', "
                ":'status', :'result'::jsonb)::text;", _lease_vars(args) | {
                    "status": args.status, "result": _value(args.result)})
            _emit(result)
        elif args.command == "retry":
            result = db.json(
                "SELECT cgactl.retry_job(:'job', :'reason')::text;",
                {"job": args.job_id, "reason": args.reason})
            _emit(result)
        elif args.command == "sweep":
            result = db.json(
                "SELECT cgactl.advance_failures(:'from_lane', :'to_lane', "
                ":'reason', :'limit'::integer, NULLIF(:'profile',''), "
                "NULLIF(:'snapshot',''), NULLIF(:'exclusive','')::boolean)::text;",
                {"from_lane": args.from_lane, "to_lane": args.to_lane,
                 "reason": args.reason, "limit": args.limit,
                 "profile": args.resource_profile or "",
                 "snapshot": args.base_snapshot or "",
                 "exclusive": ("" if args.exclusive_host is None else
                                args.exclusive_host)})
            _emit(result)
        elif args.command == "job-config":
            _emit(db.json(
                "SELECT cgactl.configure_job(:'job', :'lane', :'profile', "
                "NULLIF(:'snapshot',''), :'exclusive'::boolean)::text;",
                {"job": args.job_id, "lane": args.lane,
                 "profile": args.resource_profile,
                 "snapshot": args.base_snapshot or "",
                 "exclusive": args.exclusive_host}))
        elif args.command == "jobs-config":
            _emit(db.json(
                "SELECT cgactl.configure_queued_jobs(:'lane', :'profile', "
                ":'snapshot', :'exclusive'::boolean, :'limit'::integer)::text;",
                {"lane": args.lane, "profile": args.resource_profile,
                 "snapshot": args.base_snapshot,
                 "exclusive": args.exclusive_host, "limit": args.limit}))
        elif args.command == "snapshot-register":
            observed = verify_snapshot(
                args.container, args.snapshot, args.incus)
            metadata = _value(args.metadata)
            if not isinstance(metadata, dict):
                raise ValueError("snapshot metadata must be a JSON object")
            metadata["incus_created_at"] = observed.get("created_at")
            metadata["stateful"] = bool(observed.get("stateful"))
            _emit(db.json(
                "SELECT cgactl.register_snapshot(:'id', :'container', "
                ":'name', :'toolchain', :'metadata'::jsonb)::text;",
                {"id": args.snapshot_id, "container": args.container,
                 "name": args.snapshot, "toolchain": args.toolchain_digest,
                 "metadata": metadata}))
        elif args.command == "resource-profile-set":
            _emit(db.json(
                "SELECT cgactl.set_resource_profile(:'name', "
                "NULLIF(:'cpu','')::integer, NULLIF(:'memory','')::bigint, "
                "NULLIF(:'disk','')::bigint, :'exclusive'::boolean, "
                "NULLIF(:'concurrent','')::integer, :'metadata'::jsonb)::text;",
                {"name": args.name, "cpu": args.cpu or "",
                 "memory": args.memory_bytes or "",
                 "disk": args.disk_bytes or "",
                 "exclusive": args.exclusive_host,
                 "concurrent": args.max_concurrent or "",
                 "metadata": _value(args.metadata)}))
        elif args.command == "container-prepare":
            _emit(prepare_container(
                db, args.builder, args.job_id, args.lease_token,
                args.container, args.reserve_cpu, args.reserve_memory_bytes,
                args.reserve_disk_bytes, args.incus))
        elif args.command == "promote":
            _emit(promote(db, args.job_id,
                          Path(args.collection).expanduser().resolve(),
                          args.codeql))
        elif args.command == "promote-auto":
            collection_path = Path(args.collection).expanduser().resolve()
            db.json("SELECT cgactl.requeue_stale_promotions()::text;")
            while True:
                value = promote_pending(db, collection_path, args.codeql)
                if args.once:
                    _emit(value)
                    break
                if value.get("claimed"):
                    _emit(value)
                else:
                    time.sleep(max(args.interval, 0.2))
        elif args.command == "collection-status":
            _emit(collection_status(
                Path(args.collection).expanduser().resolve(), args.verify))
        elif args.command == "collection-reconcile":
            _emit(reconcile(
                db, Path(args.collection).expanduser().resolve()))
        elif args.command == "requeue-expired":
            _emit(db.json("SELECT cgactl.requeue_expired()::text;"))
        elif args.command == "status":
            value = db.json(SNAPSHOT_SQL)
            if args.json:
                _emit(value)
            else:
                counts = value.get("counts", {})
                print(" ".join(f"{key}={counts[key]}" for key in
                               sorted(counts)) or "no jobs")
        elif args.command == "failures":
            value = db.json(r"""
SELECT jsonb_build_object(
  'generated_at', clock_timestamp(),
  'count', count(*),
  'failures', COALESCE(jsonb_agg(jsonb_build_object(
    'job', to_jsonb(j),
    'latest_attempt', to_jsonb(a),
    'attempt_history', (SELECT jsonb_agg(to_jsonb(h) ORDER BY h.attempt)
      FROM cgactl.attempts h WHERE h.job_id = j.job_id)
  ) ORDER BY j.priority, j.job_id), '[]'::jsonb)
)::text
FROM cgactl.jobs j
JOIN cgactl.attempts a
  ON a.job_id = j.job_id AND a.attempt = j.attempt_count
WHERE j.disposition IN ('awaiting-llm', 'escalated')
  AND (NULLIF(:'disposition','') IS NULL OR
       j.disposition = NULLIF(:'disposition',''))
  AND (NULLIF(:'lane','') IS NULL OR j.lane = NULLIF(:'lane',''));
""", {"disposition": args.disposition or "", "lane": args.lane or ""})
            text = json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
        elif args.command == "serve":
            try:
                serve(db, SHARE, args.host, args.port,
                      Path(args.collection).expanduser().resolve())
            except KeyboardInterrupt:
                return 130
        return 0
    except (DatabaseError, IncusError, PromotionError, OSError, ValueError,
            json.JSONDecodeError) as exc:
        print(f"cgactl: error: {exc}", file=sys.stderr)
        return 1


def _lease_vars(args):
    return {"builder": args.builder, "job": args.job_id,
            "token": args.lease_token}

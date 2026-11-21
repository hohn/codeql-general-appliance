from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import Database


SNAPSHOT_SQL = r"""
SELECT jsonb_build_object(
  'generated_at', clock_timestamp(),
  'counts', COALESCE((
    SELECT jsonb_object_agg(status, n) FROM (
      SELECT status, count(*) AS n FROM cgactl.jobs GROUP BY status
    ) s), '{}'::jsonb),
  'dispositions', COALESCE((
    SELECT jsonb_object_agg(disposition, n) FROM (
      SELECT disposition, count(*) AS n FROM cgactl.jobs
      GROUP BY disposition
    ) s), '{}'::jsonb),
  'promotion_counts', COALESCE((
    SELECT jsonb_object_agg(status, n) FROM (
      SELECT status, count(*) AS n FROM cgactl.promotion_queue
      GROUP BY status
    ) s), '{}'::jsonb),
  'jobs', COALESCE((
    SELECT jsonb_agg(to_jsonb(j) ORDER BY cve, variant, mode)
    FROM cgactl.job_dashboard j), '[]'::jsonb),
  'builders', COALESCE((
    SELECT jsonb_agg(to_jsonb(b) ORDER BY builder_id)
    FROM cgactl.builder_dashboard b), '[]'::jsonb),
  'snapshots', COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY snapshot_id)
    FROM cgactl.base_snapshots s WHERE active), '[]'::jsonb),
  'resource_profiles', COALESCE((SELECT jsonb_agg(to_jsonb(r)
    ORDER BY profile_name) FROM cgactl.resource_profiles r), '[]'::jsonb)
)::text;
"""


class Dashboard:
    def __init__(self, db: Database, share: Path, collection: Path):
        self.db = db
        self.share = share
        self.collection = collection

    def snapshot(self) -> Any:
        return self.db.json(SNAPSHOT_SQL)

    def handler(self):
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                path = urlparse(self.path).path
                if path == "/healthz":
                    self._send(b"ok\n", "text/plain")
                elif path == "/api/snapshot":
                    try:
                        body = json.dumps(dashboard.snapshot()).encode()
                        self._send(body, "application/json")
                    except Exception as exc:  # HTTP boundary
                        self._send(json.dumps({"error": str(exc)}).encode(),
                                   "application/json", 503)
                elif path in ("/", "/index.html"):
                    self._file("index.html")
                elif path in ("/dashboard.css", "/dashboard.js"):
                    self._file(path[1:])
                elif path.startswith("/collection/"):
                    self._collection_file(path.removeprefix("/collection/"))
                else:
                    self._send(b"not found\n", "text/plain", 404)

            def do_POST(self):  # noqa: N802
                self._send(b"read-only\n", "text/plain", 405,
                           {"Allow": "GET"})

            def _file(self, name):
                path = dashboard.share / name
                if not path.is_file():
                    self._send(b"not found\n", "text/plain", 404)
                    return
                media = mimetypes.guess_type(path.name)[0] or (
                    "application/octet-stream")
                self._send(path.read_bytes(), media)

            def _collection_file(self, name):
                relative = Path(name)
                if (len(relative.parts) != 4 or
                        relative.parts[0] != "provenance" or
                        relative.parts[2] != "artifacts" or
                        relative.parts[3] not in {
                            "resource_report.html", "resource_samples.jsonl",
                            "resource_summary.json"}):
                    self._send(b"not found\n", "text/plain", 404)
                    return
                try:
                    path = (dashboard.collection / relative).resolve()
                    path.relative_to(dashboard.collection)
                except (ValueError, OSError):
                    self._send(b"not found\n", "text/plain", 404)
                    return
                if not path.is_file():
                    self._send(b"not found\n", "text/plain", 404)
                    return
                media = mimetypes.guess_type(path.name)[0] or (
                    "application/octet-stream")
                self._send(path.read_bytes(), media)

            def _send(self, body, media, status=200, headers=None):
                self.send_response(status)
                self.send_header("Content-Type", media)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        return Handler


def serve(db: Database, share: Path, host: str, port: int,
          collection: Path) -> None:
    server = ThreadingHTTPServer(
        (host, port), Dashboard(db, share, collection).handler())
    print(f"cgactl: dashboard http://{host}:{port}")
    server.serve_forever()

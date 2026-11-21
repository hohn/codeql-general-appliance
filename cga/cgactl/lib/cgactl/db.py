from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


class DatabaseError(RuntimeError):
    pass


class Database:
    def __init__(self, dsn: str | None = None, psql: str | None = None):
        self.dsn = dsn or os.environ.get("CGACTL_DATABASE_URL")
        self.psql = psql or os.environ.get("CGACTL_PSQL", "psql")

    def run(self, sql: str, variables: dict[str, Any] | None = None) -> str:
        argv = [self.psql, "-X", "--no-psqlrc", "--set=ON_ERROR_STOP=1",
                "--tuples-only", "--no-align", "--quiet"]
        if self.dsn:
            argv.extend(["--dbname", self.dsn])
        encoded = {}
        for name, value in (variables or {}).items():
            if not name.replace("_", "").isalnum():
                raise ValueError(f"unsafe psql variable name: {name}")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, separators=(",", ":"))
            marker = ("$cgactl_" +
                      hashlib.sha256(str(value).encode()).hexdigest() + "$")
            while marker in str(value):
                marker = marker[:-1] + "x$"
            encoded[name] = f"{marker}{value}{marker}"
        used = set(re.findall(r":'([A-Za-z0-9_]+)'", sql))
        if used != set(encoded):
            missing = used - set(encoded)
            unused = set(encoded) - used
            raise ValueError(f"psql variable mismatch: missing={missing}, "
                             f"unused={unused}")
        sql = re.sub(r":'([A-Za-z0-9_]+)'",
                     lambda match: encoded[match.group(1)], sql)
        proc = subprocess.run(argv, input=sql, text=True, capture_output=True)
        if proc.returncode:
            message = proc.stderr.strip() or "psql failed"
            raise DatabaseError(message)
        return proc.stdout.strip()

    def json(self, sql: str,
             variables: dict[str, Any] | None = None) -> Any:
        raw = self.run(sql, variables)
        return json.loads(raw) if raw else None

    def install_schema(self, schema: Path) -> None:
        self.run(schema.read_text(encoding="utf-8"))

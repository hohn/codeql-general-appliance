from __future__ import annotations

import datetime
import json
import os
import subprocess
from typing import Any

from .db import Database


class IncusError(RuntimeError):
    pass


PREPARE_SQL = r"""
SELECT jsonb_build_object(
  'job', to_jsonb(j),
  'snapshot', to_jsonb(s),
  'profile', to_jsonb(r)
)::text
FROM cgactl.jobs j
LEFT JOIN cgactl.base_snapshots s ON s.snapshot_id = j.base_snapshot
LEFT JOIN cgactl.resource_profiles r ON r.profile_name = j.resource_profile
WHERE j.job_id = :'job' AND j.claimed_by = :'builder'
  AND j.lease_token = :'token' AND j.lease_expires_at > clock_timestamp()
  AND j.status IN ('claimed', 'preparing', 'building', 'validating');
"""


def _run(argv: list[str], capture: bool = True) -> str:
    proc = subprocess.run(argv, text=True, capture_output=capture)
    if proc.returncode:
        raise IncusError((proc.stderr or proc.stdout or
                          f"command failed: {argv[0]}").strip())
    return proc.stdout.strip() if capture else ""


def _host_capacity() -> dict[str, int]:
    memory = 0
    with open("/proc/meminfo", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("MemTotal:"):
                memory = int(line.split()[1]) * 1024
                break
    return {"cpu_count": os.cpu_count() or 1, "memory_bytes": memory}


def _effective(profile: dict[str, Any], reserve_cpu: int,
               reserve_memory: int, storage: dict[str, int],
               reserve_disk: int) -> tuple[dict, dict]:
    host = _host_capacity()
    maximum_cpu = max(1, host["cpu_count"] - reserve_cpu)
    maximum_memory = max(256 * 1024**2,
                         host["memory_bytes"] - reserve_memory)
    maximum_disk = max(1024**3, storage["total"] - storage["used"] -
                       reserve_disk)
    requested = {
        "cpu_count": profile.get("cpu_count"),
        "memory_bytes": profile.get("memory_bytes"),
        "disk_bytes": profile.get("disk_bytes"),
        "exclusive_host": bool(profile.get("exclusive_host")),
    }
    effective = dict(requested)
    if requested["cpu_count"] is not None:
        effective["cpu_count"] = min(requested["cpu_count"], maximum_cpu)
    if requested["memory_bytes"] is not None:
        effective["memory_bytes"] = min(requested["memory_bytes"],
                                         maximum_memory)
    if requested["disk_bytes"] is not None:
        effective["disk_bytes"] = min(requested["disk_bytes"], maximum_disk)
    return requested, {**effective,
                        "host_capacity": {**host, "storage": storage},
                        "host_reserve": {"cpu_count": reserve_cpu,
                                         "memory_bytes": reserve_memory,
                                         "disk_bytes": reserve_disk}}


def _storage_capacity(incus: str, container: str) -> dict[str, Any]:
    config = json.loads(_run(
        [incus, "query", f"/1.0/instances/{container}?recursion=1"]))
    pool = config.get("expanded_devices", {}).get("root", {}).get("pool")
    if not pool:
        raise IncusError("could not resolve container root storage pool")
    resources = json.loads(_run(
        [incus, "query", f"/1.0/storage-pools/{pool}/resources"]))
    return {"total": int(resources["space"]["total"]),
            "used": int(resources["space"]["used"]), "pool": pool}


def _set_root_size(incus: str, container: str, size: int) -> None:
    """Set the root disk limit whether it is local or profile-inherited."""
    config = json.loads(_run(
        [incus, "query", f"/1.0/instances/{container}"]))
    devices = config.get("devices", {})
    command = "set" if "root" in devices else "override"
    _run([incus, "config", "device", command, container, "root",
          f"size={size}"])


def verify_snapshot(container: str, snapshot: str,
                    incus: str = "incus") -> dict[str, Any]:
    try:
        return json.loads(_run([
            incus, "query",
            f"/1.0/instances/{container}/snapshots/{snapshot}"]))
    except (IncusError, json.JSONDecodeError) as exc:
        raise IncusError(
            f"Incus snapshot does not exist: {container}/{snapshot}") from exc


def prepare(db: Database, builder: str, job_id: str, token: str,
            container: str, reserve_cpu: int = 2,
            reserve_memory: int = 4 * 1024**3,
            reserve_disk: int = 20 * 1024**3,
            incus: str = "incus") -> dict:
    record = db.json(PREPARE_SQL, {"job": job_id, "builder": builder,
                                  "token": token})
    if not record:
        raise IncusError("job lease is not current")
    snapshot = record.get("snapshot")
    profile = record.get("profile") or {}
    if not snapshot or not snapshot.get("active"):
        raise IncusError("job has no active base snapshot")
    if snapshot["container_name"] != container:
        raise IncusError("snapshot is registered for another container")
    if snapshot["toolchain_digest"] != record["job"]["toolchain_digest"]:
        raise IncusError("snapshot toolchain does not match job identity")
    if (reserve_cpu < 1 or reserve_memory < 1024**3 or
            reserve_disk < 5 * 1024**3):
        raise IncusError(
            "host reserve must retain at least 1 CPU, 1 GiB RAM, and 5 GiB disk")

    info = json.loads(_run(
        [incus, "query", f"/1.0/instances/{container}/state"]))
    storage = _storage_capacity(incus, container)
    requested, effective = _effective(
        profile, reserve_cpu, reserve_memory, storage, reserve_disk)
    if info.get("status") != "Stopped":
        _run([incus, "stop", container, "--force"])
    _run([incus, "snapshot", "restore", container,
          snapshot["snapshot_name"]])
    if effective.get("cpu_count") is not None:
        _run([incus, "config", "set", container, "limits.cpu",
              str(effective["cpu_count"])])
    if effective.get("memory_bytes") is not None:
        _run([incus, "config", "set", container, "limits.memory",
              str(effective["memory_bytes"])])
    if effective.get("disk_bytes") is not None:
        _set_root_size(incus, container, effective["disk_bytes"])
    _run([incus, "start", container])
    environment = {
        "schema_version": 1,
        "prepared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_snapshot": snapshot["snapshot_id"],
        "snapshot_name": snapshot["snapshot_name"],
        "toolchain_digest": snapshot["toolchain_digest"],
        "resource_profile": profile.get("profile_name", "default"),
        "requested_resources": requested,
        "effective_resources": effective,
    }
    result = db.json(
        "SELECT cgactl.record_attempt_environment(:'builder', :'job', "
        ":'token', :'container', :'environment'::jsonb)::text;",
        {"builder": builder, "job": job_id, "token": token,
         "container": container, "environment": environment})
    return {"job_id": job_id, "container": container,
            "environment": environment, "attempt": result}

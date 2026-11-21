import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "lib"))

from cgactl import incus  # noqa: E402


class FakeDatabase:
    def __init__(self):
        self.recorded = None

    def json(self, sql, variables=None):
        if "FROM cgactl.jobs" in sql:
            return {
                "job": {"job_id": "job-1", "toolchain_digest": "codeql:test"},
                "snapshot": {"snapshot_id": "base-v1", "active": True,
                             "container_name": "ubu", "snapshot_name": "clean",
                             "toolchain_digest": "codeql:test"},
                "profile": {"profile_name": "large", "cpu_count": 64,
                            "memory_bytes": 128 * 1024**3,
                            "disk_bytes": None, "exclusive_host": True},
            }
        self.recorded = variables
        return {"attempt": 1}


class IncusTest(unittest.TestCase):
    @mock.patch.object(incus, "_run")
    def test_root_size_sets_local_device(self, run):
        run.side_effect = ['{"devices":{"root":{"type":"disk"}}}', ""]
        incus._set_root_size("incus", "builder", 100)
        self.assertEqual(run.call_args_list[-1].args[0], [
            "incus", "config", "device", "set", "builder", "root",
            "size=100"])

    @mock.patch.object(incus, "_run")
    def test_root_size_overrides_inherited_device(self, run):
        run.side_effect = ['{"devices":{}}', ""]
        incus._set_root_size("incus", "builder", 100)
        self.assertEqual(run.call_args_list[-1].args[0], [
            "incus", "config", "device", "override", "builder", "root",
            "size=100"])

    @mock.patch.object(incus, "_run", return_value=(
        '{"name":"clean","stateful":false}'))
    def test_verify_snapshot_uses_instance_snapshot_api(self, run):
        result = incus.verify_snapshot("ubu", "clean")
        self.assertEqual(result["name"], "clean")
        self.assertEqual(run.call_args.args[0], [
            "incus", "query", "/1.0/instances/ubu/snapshots/clean"])

    @mock.patch.object(incus, "_host_capacity",
                       return_value={"cpu_count": 16,
                                     "memory_bytes": 64 * 1024**3})
    @mock.patch.object(incus, "_storage_capacity",
                       return_value={"total": 500 * 1024**3,
                                     "used": 100 * 1024**3, "pool": "default"})
    @mock.patch.object(incus, "_run")
    def test_prepare_restores_before_start_and_caps_host_resources(
            self, run, _storage, _capacity):
        run.side_effect = lambda argv, capture=True: (
            '{"status":"Running"}' if argv[1:] == [
                "query", "/1.0/instances/ubu/state"] else "")
        db = FakeDatabase()
        result = incus.prepare(db, "builder", "job-1", "token", "ubu",
                               reserve_cpu=2,
                               reserve_memory=4 * 1024**3)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertLess(commands.index(["incus", "stop", "ubu", "--force"]),
                        commands.index(["incus", "snapshot", "restore",
                                        "ubu", "clean"]))
        self.assertLess(commands.index(["incus", "snapshot", "restore",
                                        "ubu", "clean"]),
                        commands.index(["incus", "start", "ubu"]))
        effective = result["environment"]["effective_resources"]
        self.assertEqual(effective["cpu_count"], 14)
        self.assertEqual(effective["memory_bytes"], 60 * 1024**3)
        self.assertEqual(db.recorded["container"], "ubu")


if __name__ == "__main__":
    unittest.main()

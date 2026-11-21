from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from cgamx import infra  # noqa: E402


class ProcessTerminationTest(unittest.TestCase):
    def test_kill_terminates_detached_process_group(self):
        with mock.patch.object(infra.os, "killpg") as killpg, \
             mock.patch.object(infra.os, "kill") as kill:
            self.assertTrue(infra._kill(1234))
        killpg.assert_called_once_with(1234, infra.signal.SIGTERM)
        kill.assert_not_called()

    def test_kill_falls_back_for_non_group_leader(self):
        with mock.patch.object(
                infra.os, "killpg", side_effect=ProcessLookupError), \
             mock.patch.object(infra.os, "kill") as kill:
            self.assertTrue(infra._kill(1234))
        kill.assert_called_once_with(1234, infra.signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()

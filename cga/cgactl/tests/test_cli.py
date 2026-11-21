import subprocess
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "lib"))
sys.path.insert(0, str(PROJECT.parent / "cgalib"))

from cgactl import cli  # noqa: E402


class ControllerHelpTest(unittest.TestCase):
    def test_container_restore_help_warns_before_any_database_access(self):
        result = subprocess.run(
            [PROJECT / "bin" / "cgactl", "container-prepare", "--help"],
            input="", capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cga ctl container-prepare", result.stdout)
        self.assertIn("discarding changes since that snapshot", result.stdout)
        self.assertIn("CGACTL_HOST_RESERVE_CPU", result.stdout)
        for heading in ("Name:", "Synopsis:", "Description:", "Example:"):
            self.assertIn(heading, result.stdout)

    def test_recovery_and_promotion_commands_have_dedicated_help(self):
        parser = cli.parser()
        subcommands = next(
            action.choices for action in parser._actions
            if hasattr(action, "choices") and isinstance(action.choices, dict)
        )
        for command in (
            "sweep", "container-prepare", "promote", "promote-auto",
            "collection-status", "collection-reconcile", "failures",
        ):
            with self.subTest(command=command):
                help_text = subcommands[command].format_help()
                self.assertIn(f"cga ctl {command}", help_text)
                self.assertIn("Description:", help_text)
                self.assertIn("Example:", help_text)


if __name__ == "__main__":
    unittest.main()

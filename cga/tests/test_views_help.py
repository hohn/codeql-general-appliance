from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

COLLECTION = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(COLLECTION / name)
    for name in ("cgalib", "cgawf", "cgabench", "cgamx", "cgauv", "cgadl",
                 "cgaql", "cgasi", "cga-view", "cgacc/lib", "lib")
]

from cgabench import cli as bench
from cgaview import cli as view
from cgamx import cli as mx
from cgauv import server as unified
from help_topics.views import TOPICS
import llm
import vid


class ViewsHelpTest(unittest.TestCase):
    def assert_sections(self, text: str, command: str) -> None:
        self.assertIn(f"cga {command} - ", text)
        for heading in ("Name:", "Synopsis:", "Description:", "Example:"):
            self.assertIn(heading, text)

    def test_every_visible_parser_has_its_specific_topic(self) -> None:
        def check(parser: argparse.ArgumentParser, path: tuple[str, ...]) -> None:
            with self.subTest(path=path):
                text = parser.format_help()
                self.assert_sections(text, " ".join(path))
                self.assertIn("".join(TOPICS[path].description.split()),
                              "".join(text.split()))
                self.assertTrue(TOPICS[path].examples)
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for name, child in action.choices.items():
                        check(child, (*path, name))

        for family, parser in (("bench", bench.parser()), ("mx", mx.build_parser()),
                               ("llm", llm.parser()), ("view", view._parser())):
            check(parser, (family,))

    def test_uv_help_does_not_discover_state_or_start_a_service(self) -> None:
        with mock.patch.object(unified.Repository, "discover") as discover, \
                mock.patch.object(unified, "serve") as serve:
            for command in ("serve", "outline", "search"):
                with self.subTest(command=command), redirect_stdout(io.StringIO()) as output:
                    with self.assertRaises(SystemExit) as result:
                        unified.main([command, "--help"])
                    self.assertEqual(result.exception.code, 0)
                    self.assert_sections(output.getvalue(), f"uv {command}")
            discover.assert_not_called()
            serve.assert_not_called()

    def test_vid_help_names_each_public_command_without_observing_state(self) -> None:
        with mock.patch.object(vid.Repository, "discover") as discover, \
                mock.patch.object(vid, "RawRepository") as raw, \
                mock.patch.object(vid.webbrowser, "open") as browser:
            for command in ("show", "open", "related"):
                for flag in ("-h", "--help"):
                    with self.subTest(command=command, flag=flag), \
                            redirect_stdout(io.StringIO()) as output:
                        with self.assertRaises(SystemExit) as result:
                            vid.main([command, flag])
                        self.assertEqual(result.exception.code, 0)
                        text = output.getvalue()
                        self.assert_sections(text, command)
                        self.assertNotIn("{show,related,open}", text)
            discover.assert_not_called()
            raw.assert_not_called()
            browser.assert_not_called()

    def test_view_help_never_captures_or_exports(self) -> None:
        with mock.patch.object(view, "capture_snapshot") as capture, \
                mock.patch.object(view, "export_replay") as export:
            for arguments in (["--help"], ["--capture", "-h"],
                              ["--export", "replay.html", "--help"]):
                with self.subTest(arguments=arguments), \
                        redirect_stdout(io.StringIO()) as output:
                    with self.assertRaises(SystemExit) as result:
                        view.main(arguments)
                    self.assertEqual(result.exception.code, 0)
                    self.assert_sections(output.getvalue(), "view")
            capture.assert_not_called()
            export.assert_not_called()


if __name__ == "__main__":
    unittest.main()

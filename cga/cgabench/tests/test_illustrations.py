"""Focused checks for the full-text poster illustrations."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ILLUSTRATION = Path(__file__).resolve().parents[1] / "illustration"
SPEC = importlib.util.spec_from_file_location(
    "render_illustrations", ILLUSTRATION / "render_illustrations.py")
renderer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = renderer
SPEC.loader.exec_module(renderer)


class IllustrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.command_source = (ILLUSTRATION / "six-session-shell-equivalent.sh").read_text()
        cls.storage_source = (ILLUSTRATION / "six-session-storage-equivalent.md").read_text()
        cls.command = renderer.commands_poster(cls.command_source, "commands.sh")
        cls.storage = renderer.storage_poster(cls.storage_source, "storage.md")

    def test_both_posters_preserve_every_source_line_including_whitespace(self):
        for drawing in (self.command, self.storage):
            with self.subTest(poster=drawing.title):
                renderer.validate(drawing)
                root = ET.fromstring(drawing.svg())
                metadata = json.loads(root.find(f"{{{renderer.SVG}}}metadata").text)
                self.assertEqual(metadata["source_text"], drawing.source)
                lines = {}
                for element in root.findall(f"{{{renderer.SVG}}}text"):
                    if "data-source-line" in element.attrib:
                        lines.setdefault(int(element.attrib["data-source-line"]), []).append(
                            (int(element.attrib["data-source-column"]), element.text or ""))
                self.assertEqual(
                    ["".join(text for _, text in sorted(lines[number]))
                     for number in sorted(lines)],
                    drawing.source.splitlines())

    def test_command_glyphs_follow_one_path_and_fit_at_readable_size(self):
        self.assertGreaterEqual(self.command.details["font_points"], 8.5)
        self.assertLess(self.command.details["text_end_points"],
                        self.command.details["path_length_points"])
        path = next(command for command in self.command.commands
                    if command["attributes"].get("id") == "command-thread")
        self.assertEqual(sum(part[0] == "M" for part in path["points"]), 1)
        angles = {round(command["angle"] / 45)
                  for command in self.command.commands
                  if "data_source_line" in command["attributes"]}
        self.assertGreater(len(angles), 5)

    def test_storage_comparison_uses_frozen_json_not_sql_stores(self):
        edges = self.storage.details["edges"]
        compared = [edge for edge in edges if edge["relation"] == "compared"]
        self.assertEqual(len(compared), 6)
        lines = self.storage_source.splitlines()
        for number, edge in enumerate(compared, 1):
            self.assertEqual(edge["from"]["section"], f"s{number}-results")
            self.assertIn("| Frozen findings", lines[edge["from"]["line"] - 1])
            self.assertEqual(edge["to"]["section"], "comparison-c")
            self.assertIn(f"(#s{number}-results)", lines[edge["to"]["line"] - 1])

    def test_storage_cards_do_not_overlap_or_leave_unresolved_targets(self):
        cards = self.storage.details["cards"]
        anchors = {card["id"] for card in cards}
        for index, first in enumerate(cards):
            x, y, width, height = first["box"]
            for last in cards[index + 1:]:
                lx, ly, lw, lh = last["box"]
                self.assertFalse(x < lx + lw and lx < x + width
                                 and y < ly + lh and ly < y + height,
                                 (first["id"], last["id"]))
        for edge in self.storage.details["edges"]:
            self.assertIn(edge["from"]["section"], anchors)
            self.assertIn(edge["to"]["section"], anchors)

    def test_wrapping_keeps_long_paths_hashes_and_spaces(self):
        text = "  [same file](" + "../folder/" * 30 + "all.duckdb)  "
        self.assertEqual("".join(renderer.wrapped(text, 30)), text)
        self.assertEqual(renderer.wrapped("", 30), [""])

    @unittest.skipUnless(shutil.which("gs") and shutil.which("pdftotext"),
                         "Ghostscript and pdftotext are needed for PDF text checks")
    def test_pdf_keeps_literal_shell_and_markdown_punctuation(self):
        line = "`code` 'single' \"double\" path\\name (query) --output-dir -> result"
        source = f"{line}\n{line}\n"
        drawing = renderer.Drawing(900, 140, "Punctuation", source, "source")
        drawing.text(20, 40, line, size=12)
        drawing.text(20, 80, line, size=12, mono=False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postscript, pdf = root / "punctuation.ps", root / "punctuation.pdf"
            postscript.write_text(drawing.postscript(), encoding="ascii")
            subprocess.run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE",
                            "-sDEVICE=pdfwrite", f"-sOutputFile={pdf}", str(postscript)],
                           check=True, capture_output=True, timeout=30)
            text = subprocess.check_output(
                ["pdftotext", "-raw", str(pdf), "-"], text=True, timeout=30)
        self.assertEqual(text.strip(), source.strip())

    def test_wires_remain_visible_outside_document_cards(self):
        for edge in self.storage.details["edges"]:
            current = (0, 0)
            for part in edge["path"]:
                op, values = part[0], part[1:]
                if op == "M":
                    current = values
                    continue
                end = values[-2:]
                for step in range(1, 20):
                    t = step / 20
                    if op == "L":
                        point = tuple(current[i] + t * (end[i] - current[i])
                                      for i in (0, 1))
                    elif op == "Q":
                        point = tuple((1 - t) ** 2 * current[i]
                                      + 2 * (1 - t) * t * values[i]
                                      + t * t * end[i] for i in (0, 1))
                    else:
                        point = tuple((1 - t) ** 3 * current[i]
                                      + 3 * (1 - t) ** 2 * t * values[i]
                                      + 3 * (1 - t) * t * t * values[i + 2]
                                      + t ** 3 * end[i] for i in (0, 1))
                    for card in self.storage.details["cards"]:
                        x, y, width, height = card["box"]
                        self.assertFalse(
                            x + 0.01 < point[0] < x + width - 0.01
                            and y + 0.01 < point[1] < y + height - 0.01,
                            (edge["from"]["section"], edge["to"]["section"], card["id"]))
                current = end


if __name__ == "__main__":
    unittest.main()

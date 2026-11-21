#!/usr/bin/env python3
"""Render the complete command and storage illustrations as vector posters."""

from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import random
import re
import shutil
import subprocess
import textwrap
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
SVG = "http://www.w3.org/2000/svg"
INK = "#23313a"
PAPER = "#fffdf7"
COLORS = ("#226b63", "#325e91", "#8a5c24", "#79548a", "#974d49", "#596f30")
RELATIONS = {
    "uses": ("#226b63", ()),
    "derived": ("#426eaa", (8, 5)),
    "compared": ("#a54852", (12, 4, 2, 4)),
    "reference": ("#9a948a", (2, 6)),
}
Point = tuple[float, float]


def rgb(color: str) -> tuple[float, float, float]:
    return tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))


def ps_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def slug(text: str) -> str:
    return re.sub(r"[^\w -]", "", text.lower()).replace(" ", "-")


def wrapped(line: str, columns: int) -> list[str]:
    chunks = textwrap.wrap(
        line, width=columns, expand_tabs=False, replace_whitespace=False,
        drop_whitespace=False, break_on_hyphens=False,
    ) or [""]
    if "".join(chunks) != line:
        raise ValueError("wrapping changed source text")
    return chunks


@dataclass
class Drawing:
    width: float
    height: float
    title: str
    source: str
    source_name: str
    commands: list[dict] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def path(self, points: list[tuple], *, stroke: str = INK,
             fill: str = "none", width: float = 1,
             dash: tuple = (), **attributes) -> None:
        self.commands.append(dict(
            kind="path", points=points, stroke=stroke, fill=fill,
            width=width, dash=dash, attributes=attributes,
        ))

    def rect(self, x: float, y: float, width: float, height: float,
             *, fill: str = PAPER, stroke: str = "#d1cabd", **attributes) -> None:
        self.path([
            ("M", x, y), ("L", x + width, y), ("L", x + width, y + height),
            ("L", x, y + height), ("Z",),
        ], fill=fill, stroke=stroke, **attributes)

    def text(self, x: float, y: float, text: str, *, size: float = 10,
             color: str = INK, angle: float = 0, mono: bool = True,
             **attributes) -> None:
        self.commands.append(dict(
            kind="text", x=x, y=y, text=text, size=size, color=color,
            angle=angle, mono=mono, attributes=attributes,
        ))

    def audit(self) -> dict:
        return {
            "title": self.title,
            "source": self.source_name,
            "source_sha256": hashlib.sha256(self.source.encode()).hexdigest(),
            "source_lines": len(self.source.splitlines()),
            "page_points": [self.width, self.height],
            **self.details,
        }

    def svg(self) -> str:
        ET.register_namespace("", SVG)
        root = ET.Element(f"{{{SVG}}}svg", {
            "width": f"{self.width / 72:.5f}in",
            "height": f"{self.height / 72:.5f}in",
            "viewBox": f"0 0 {self.width:.3f} {self.height:.3f}",
        })
        ET.SubElement(root, f"{{{SVG}}}title").text = self.title
        ET.SubElement(root, f"{{{SVG}}}metadata", {"id": "source-data"}).text = (
            json.dumps({**self.audit(), "source_text": self.source}, sort_keys=True)
        )
        for command in self.commands:
            attributes = {
                key.replace("_", "-"): str(value)
                for key, value in command["attributes"].items()
            }
            tooltip = attributes.pop("tooltip", None)
            href = attributes.pop("href", None)
            parent = ET.SubElement(root, f"{{{SVG}}}a", {"href": href}) if href else root
            if command["kind"] == "text":
                attributes.update({
                    "x": str(command["x"]), "y": str(command["y"]),
                    "font-size": str(command["size"]), "fill": command["color"],
                    "font-family": ("Courier, Liberation Mono, monospace"
                                    if command["mono"] else "Helvetica, Arial, sans-serif"),
                    "{http://www.w3.org/XML/1998/namespace}space": "preserve",
                })
                if command["angle"]:
                    attributes["transform"] = (
                        f"rotate({command['angle']} {command['x']} {command['y']})"
                    )
                element = ET.SubElement(parent, f"{{{SVG}}}text", attributes)
                element.text = command["text"]
            else:
                attributes.update({
                    "d": " ".join(
                        part[0] + " ".join(f"{value:.3f}" for value in part[1:])
                        for part in command["points"]),
                    "stroke": command["stroke"], "fill": command["fill"],
                    "stroke-width": str(command["width"]),
                    "stroke-linejoin": "round", "stroke-linecap": "round",
                })
                if command["dash"]:
                    attributes["stroke-dasharray"] = " ".join(map(str, command["dash"]))
                element = ET.SubElement(parent, f"{{{SVG}}}path", attributes)
            if tooltip:
                ET.SubElement(element, f"{{{SVG}}}title").text = tooltip
        return ET.tostring(root, encoding="unicode", xml_declaration=True)

    def postscript(self) -> str:
        output = [
            "%!PS-Adobe-3.0",
            f"%%Title: {self.title}",
            f"%%BoundingBox: 0 0 {math.ceil(self.width)} {math.ceil(self.height)}",
            "%%Pages: 1", "%%EndComments",
            "/sourcefont {",
            "  findfont dup length dict begin",
            "  { 1 index /FID ne { def } { pop pop } ifelse } forall",
            "  /Encoding ISOLatin1Encoding dup length array copy def",
            "  Encoding 39 /quotesingle put Encoding 45 /hyphen put",
            "  Encoding 96 /grave put",
            "  currentdict end definefont pop",
            "} bind def",
            "/SourceCourier /Courier sourcefont",
            "/SourceHelvetica /Helvetica sourcefont",
            f"<< /PageSize [{self.width:.3f} {self.height:.3f}] >> setpagedevice",
            "%%Page: 1 1",
            f"0 {self.height:.3f} translate 1 -1 scale",
            "1 setlinejoin 1 setlinecap",
        ]
        for command in self.commands:
            if command["kind"] == "text":
                font = "SourceCourier" if command["mono"] else "SourceHelvetica"
                output += [
                    "gsave",
                    f"{command['x']:.3f} {command['y']:.3f} translate",
                    f"{command['angle']:.3f} rotate 1 -1 scale",
                    f"/{font} findfont {command['size']:.3f} scalefont setfont",
                    " ".join(f"{value:.5f}" for value in rgb(command["color"]))
                    + " setrgbcolor",
                    f"0 0 moveto ({ps_string(command['text'])}) show",
                    "grestore",
                ]
                continue
            output.append("newpath")
            current = (0.0, 0.0)
            for part in command["points"]:
                op, values = part[0], part[1:]
                if op in ("M", "L"):
                    output.append(f"{values[0]:.3f} {values[1]:.3f} "
                                  + ("moveto" if op == "M" else "lineto"))
                    current = values
                elif op == "Q":
                    control, end = values[:2], values[2:]
                    first = tuple(current[i] + 2 / 3 * (control[i] - current[i])
                                  for i in (0, 1))
                    second = tuple(end[i] + 2 / 3 * (control[i] - end[i])
                                   for i in (0, 1))
                    output.append(" ".join(f"{value:.3f}" for value in
                                           (*first, *second, *end)) + " curveto")
                    current = end
                elif op == "C":
                    output.append(" ".join(f"{value:.3f}" for value in values)
                                  + " curveto")
                    current = values[-2:]
                elif op == "Z":
                    output.append("closepath")
                else:
                    raise ValueError(f"unsupported path operation: {op}")
            if command["fill"] != "none":
                output += [
                    "gsave",
                    " ".join(f"{value:.5f}" for value in rgb(command["fill"]))
                    + " setrgbcolor fill grestore",
                ]
            if command["stroke"] != "none":
                output += [
                    " ".join(f"{value:.5f}" for value in rgb(command["stroke"]))
                    + " setrgbcolor",
                    f"{command['width']} setlinewidth",
                    "[" + " ".join(map(str, command["dash"])) + "] 0 setdash",
                    "stroke",
                ]
        output += ["showpage", "%%EOF"]
        return "\n".join(output) + "\n"


def hilbert(index: int, side: int = 32) -> Point:
    x = y = 0
    scale = 1
    while scale < side:
        rx, ry = (index // 2) & 1, (index ^ (index // 2)) & 1
        if not ry:
            if rx:
                x, y = scale - 1 - x, scale - 1 - y
            x, y = y, x
        x += scale * rx
        y += scale * ry
        index //= 4
        scale *= 2
    return x, y


def noodle(width: float, height: float) -> tuple[list[tuple], list[Point]]:
    rng = random.Random(11)
    vertices = [
        (130 + (x + rng.uniform(-0.14, 0.14)) * (width - 260) / 31,
         300 + (y + rng.uniform(-0.14, 0.14)) * (height - 510) / 31)
        for x, y in (hilbert(index) for index in range(32 * 32))
    ]
    path = [("M", *vertices[0])]
    samples = [vertices[0]]
    start = vertices[0]
    for index in range(1, len(vertices) - 1):
        control = vertices[index]
        end = tuple((control[i] + vertices[index + 1][i]) / 2 for i in (0, 1))
        path.append(("Q", *control, *end))
        for step in range(1, 17):
            t = step / 16
            samples.append(tuple((1 - t) ** 2 * start[i]
                                 + 2 * (1 - t) * t * control[i]
                                 + t * t * end[i] for i in (0, 1)))
        start = end
    path.append(("L", *vertices[-1]))
    samples.append(vertices[-1])
    return path, samples


def lengths(samples: list[Point]) -> list[float]:
    output = [0.0]
    for first, second in zip(samples, samples[1:]):
        output.append(output[-1] + math.dist(first, second))
    return output


def along(samples: list[Point], distances: list[float], position: float
          ) -> tuple[float, float, float]:
    if not 0 <= position <= distances[-1]:
        raise ValueError(f"text extends beyond path: {position}")
    index = max(1, bisect_left(distances, position))
    first, second = samples[index - 1:index + 1]
    span = distances[index] - distances[index - 1]
    t = (position - distances[index - 1]) / span
    return (
        first[0] + t * (second[0] - first[0]),
        first[1] + t * (second[1] - first[1]),
        math.degrees(math.atan2(second[1] - first[1], second[0] - first[0])),
    )


def commands_poster(source: str, name: str) -> Drawing:
    lines = source.splitlines()
    slots = sum(len(line) + 3 for line in lines)
    width, height = 2384.0, 3370.0
    path, samples = noodle(width, height)
    distances = lengths(samples)
    size = min(10.0, (distances[-1] - 80) / (slots * 0.6))
    if size < 8.5:
        scale = 8.5 / size
        width, height = width * scale, height * scale
        path, samples = noodle(width, height)
        distances = lengths(samples)
        size = min(10.0, (distances[-1] - 80) / (slots * 0.6))
    drawing = Drawing(width, height, "Commands: one long thread", source, name)
    drawing.rect(0, 0, width, height, fill=PAPER, stroke="none")
    drawing.text(100, 86, "COMMANDS / ONE LONG THREAD", size=36, mono=False)
    drawing.text(100, 120, "Six sessions in the UI. Every source line. No shortcuts.",
                 size=17, mono=False)
    drawing.text(100, 150, f"{len(lines)} lines / {len(source.encode()):,} bytes / "
                 f"{size:.1f} pt Courier / follow increasing line numbers",
                 size=14, mono=False)
    for index, color in enumerate(COLORS, 1):
        drawing.text(100 + (index - 1) * 330, 196, f"S{index}", color=color,
                     size=19, mono=False)
    drawing.path(path, stroke="#e8dfc5", width=size + 6, id="command-thread")
    drawing.path(path, stroke="#c9bea3", width=0.5)
    offset = 30.0
    color = INK
    for number, line in enumerate(lines, 1):
        match = re.match(r"# Session ([1-6]):", line)
        if match:
            color = COLORS[int(match[1]) - 1]
        if line.startswith("# Manual inspection"):
            color = INK
        x, y, angle = along(samples, distances, offset)
        radians = math.radians(angle)
        drawing.text(x + math.sin(radians) * 15, y - math.cos(radians) * 15,
                     f"{number:03d}", size=5.5, color="#80786a", angle=angle)
        if not line:
            drawing.text(x, y, "", size=size, data_source_line=number,
                         data_source_column=0)
        for column, character in enumerate(line):
            x, y, angle = along(samples, distances, offset)
            drawing.text(x, y, character, size=size, angle=angle, color=color,
                         data_source_line=number, data_source_column=column)
            offset += size * 0.6
        offset += size * 0.6 * 3
    first = along(samples, distances, 0)
    last = along(samples, distances, offset)
    for label, point, x in (("START / 001", first, 100), ("END", last, width - 230)):
        drawing.path([("M", x + 50, 255), ("L", point[0], point[1])],
                     stroke="#a49a80", width=0.6)
        drawing.rect(x, 230, 110, 24, fill=PAPER)
        drawing.text(x + 8, 246, label, size=10, color=INK)
    drawing.text(100, height - 110,
                 "One continuous PostScript path; letters turn with its tangent.",
                 size=16, mono=False)
    drawing.text(100, height - 80,
                 "Read upright, sideways, and upside down. Blank lines are gaps, not omissions.",
                 size=14, mono=False)
    drawing.text(100, height - 48, name, size=11)
    drawing.details = {
        "font_points": size, "path_length_points": distances[-1],
        "text_end_points": offset, "path_subpaths": 1,
    }
    return drawing


@dataclass
class Section:
    anchor: str
    title: str
    lines: list[tuple[int, str]]


def sections(source: str) -> list[Section]:
    output: list[Section] = []
    for number, line in enumerate(source.splitlines(), 1):
        match = re.match(r"#{1,3} (.+)", line)
        if match:
            title = match[1]
            anchor = slug(title)
            if any(section.anchor == anchor for section in output):
                raise ValueError(f"duplicate document section: {anchor}")
            output.append(Section(anchor, title, []))
        if not output:
            raise ValueError("storage document must start with a heading")
        output[-1].lines.append((number, line))
    return output


@dataclass
class Card:
    section: Section
    x: float
    y: float
    width: float
    color: str = INK
    size: float = 9
    zone: str = "top"
    rows: list[tuple[int, int, str]] = field(init=False)
    height: float = field(init=False)

    def __post_init__(self) -> None:
        self.rows = []
        columns = int((self.width - 64) / (self.size * 0.6))
        for number, line in self.section.lines:
            column = 0
            for chunk in wrapped(line, columns):
                self.rows.append((number, column, chunk))
                column += len(chunk)
        self.height = 64 + len(self.rows) * 12.5

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def port(self, pattern: str, *, right: bool, column: int | None = None) -> dict:
        matches = [
            (number, re.search(pattern, line))
            for number, line in self.section.lines if re.search(pattern, line)
        ]
        if not matches:
            raise ValueError(f"missing field {pattern!r} in {self.section.anchor}")
        number, match = matches[0]
        column = match.start() if column is None else column
        row = next(index for index, (line, start, text) in enumerate(self.rows)
                   if line == number and start <= column < start + max(1, len(text)))
        return {
            "x": self.x + self.width if right else self.x,
            "y": self.y + 50 + row * 12.5 - 3,
            "section": self.section.anchor, "line": number, "column": column,
            "side": "right" if right else "left", "zone": self.zone,
            "card_x": self.x, "card_width": self.width,
        }

    def draw(self, drawing: Drawing) -> None:
        drawing.rect(self.x + 5, self.y + 6, self.width, self.height,
                     fill="#e5e0d6", stroke="none")
        drawing.rect(self.x, self.y, self.width, self.height,
                     fill="#ffffff", id=self.section.anchor)
        drawing.rect(self.x, self.y, self.width, 5, fill=self.color, stroke="none")
        drawing.text(self.x + 22, self.y + 27, self.section.title,
                     size=13, color=self.color, mono=False)
        for index, (number, column, chunk) in enumerate(self.rows):
            drawing.text(
                self.x + 25, self.y + 50 + index * 12.5, chunk, size=self.size,
                data_source_line=number, data_source_column=column,
            )


def rounded_route(vertices: list[Point]) -> list[tuple]:
    vertices = [point for index, point in enumerate(vertices)
                if index == 0 or point != vertices[index - 1]]
    output = [("M", *vertices[0])]
    for previous, current, following in zip(vertices, vertices[1:], vertices[2:]):
        before, after = math.dist(previous, current), math.dist(current, following)
        radius = min(18, before / 2, after / 2)
        approach = tuple(current[i] + (previous[i] - current[i]) * radius / before
                         for i in (0, 1))
        departure = tuple(current[i] + (following[i] - current[i]) * radius / after
                          for i in (0, 1))
        output += [("L", *approach), ("Q", *current, *departure)]
    output.append(("L", *vertices[-1]))
    return output


def wire(drawing: Drawing, start: dict, end: dict, relation: str,
         index: int, layout: dict) -> list[tuple]:
    color, dash = RELATIONS[relation]
    sx, sy, ex, ey = start["x"], start["y"], end["x"], end["y"]
    channel = 14 + index * 7 % 32
    outside_start = sx + channel * (1 if start["side"] == "right" else -1)
    outside_end = ex + channel * (1 if end["side"] == "right" else -1)
    same_column = (start["card_x"] == end["card_x"]
                   and start["card_width"] == end["card_width"]
                   and start["zone"] == end["zone"])
    if same_column:
        path = [("M", sx, sy), ("C", outside_start, sy, outside_end, ey, ex, ey)]
    else:
        zones = {start["zone"], end["zone"]}
        if zones == {"top"}:
            bus = 220 - index % 15
        elif zones <= {"top", "sessions"}:
            bus = layout["above_folders"] + index * 7 % 140
        elif zones == {"sessions"}:
            bus = layout["below_queries"] + index * 7 % 130
        else:
            bus = layout["below_folders"] + index * 7 % 180
        vertices = [(sx, sy), (outside_start, sy), (outside_start, bus)]
        if zones == {"top", "notes"}:
            upper = layout["above_folders"] + index * 7 % 140
            lower = layout["below_folders"] + index * 7 % 180
            first_bus, last_bus = ((upper, lower) if start["zone"] == "top"
                                   else (lower, upper))
            rail = 35 if sx + ex < drawing.width else drawing.width - 35
            vertices = [
                (sx, sy), (outside_start, sy), (outside_start, first_bus),
                (rail, first_bus), (rail, last_bus), (outside_end, last_bus),
            ]
        else:
            vertices.append((outside_end, bus))
        vertices += [(outside_end, ey), (ex, ey)]
        path = rounded_route(vertices)
    drawing.path(path, stroke=PAPER, width=5)
    drawing.path(path, stroke=color, dash=dash,
                 width=0.9 if relation == "reference" else 1.8)
    theta = 0 if end["side"] == "left" else math.pi
    arrow = [
        ("M", ex, ey),
        ("L", ex - 9 * math.cos(theta - 0.4), ey - 9 * math.sin(theta - 0.4)),
        ("L", ex - 9 * math.cos(theta + 0.4), ey - 9 * math.sin(theta + 0.4)),
        ("Z",),
    ]
    drawing.path(arrow, fill=color, stroke="none")
    return path


def storage_poster(source: str, name: str) -> Drawing:
    parsed = sections(source)
    lookup = {section.anchor: section for section in parsed}
    cards: dict[str, Card] = {}
    width = 5260.0

    def card(anchor: str, x: float, y: float, span: float, color: str = INK) -> Card:
        if anchor not in lookup:
            raise ValueError(f"required storage section is missing: {anchor}")
        result = Card(lookup[anchor], x, y, span, color)
        cards[anchor] = result
        return result

    intro = card("six-session-storage-equivalent", 100, 245, 1460)
    index = card("experiment-and-session-index", 100, intro.bottom + 45, 1460)
    database = card("shared-database-d", 1650, 245, 1960, COLORS[0])
    context = card("common-submission-context", 3700, 245, 1460)
    folder_y = max(index.bottom, database.bottom, context.bottom) + 280
    headers, queries, jobs, results = [], [], [], []
    for session in range(1, 7):
        x = 100 + (session - 1) * 860
        color = COLORS[session - 1]
        headers.append(card(f"session-{session}", x, folder_y, 760, color))
        queries.append(card(f"s{session}-accepted-query", x,
                            headers[-1].bottom + 40, 760, color))
    job_y = max(item.bottom for item in queries) + 210
    for session in range(1, 7):
        jobs.append(card(f"s{session}-submission", 100 + (session - 1) * 860,
                         job_y, 760, COLORS[session - 1]))
    result_y = max(item.bottom for item in jobs) + 210
    for session in range(1, 7):
        results.append(card(f"s{session}-results", 100 + (session - 1) * 860,
                            result_y, 760, COLORS[session - 1]))
    folder_bottom = max(item.bottom for item in results) + 40
    notes_y = folder_bottom + 340
    notes = [
        card("what-each-result-representation-preserves", 100, notes_y, 960),
        card("sql-stores-and-their-scope", 1120, notes_y, 960),
        card("comparison-c", 2140, notes_y, 1740, "#a54852"),
        card("what-a-person-would-keep-rather-than-all-cgast-state",
             3940, notes_y, 1220),
    ]
    for item in headers + queries + jobs + results:
        item.zone = "sessions"
    for item in notes:
        item.zone = "notes"
    if set(cards) != set(lookup):
        raise ValueError(f"unplaced storage sections: {sorted(set(lookup) - set(cards))}")
    height = max(item.bottom for item in notes) + 150
    drawing = Drawing(width, height, "Storage: the wiring behind the grid", source, name)
    drawing.rect(0, 0, width, height, fill=PAPER, stroke="none")
    drawing.text(100, 86, "STORAGE / THE WIRING BEHIND THE GRID", size=40, mono=False)
    drawing.text(100, 124, f"{len(source.splitlines())} source lines, including every "
                 "path, hash, repeated filename, and caveat. Text is wrapped, never shortened.",
                 size=19, mono=False)
    for offset, (relation, label) in enumerate((
        ("uses", "input -> job"), ("derived", "derived from / produces"),
        ("compared", "frozen JSON -> comparison"), ("reference", "section reference"),
    )):
        x = 100 + offset * 1220
        color, dash = RELATIONS[relation]
        drawing.path([("M", x, 183), ("L", x + 90, 183)],
                     stroke=color, dash=dash, width=2)
        drawing.text(x + 110, 188, label, size=17, mono=False)
    for number, header in enumerate(headers, 1):
        drawing.rect(header.x - 18, folder_y - 24, 796, folder_bottom - folder_y + 42,
                     fill="#f1eee6", stroke="#b9b2a3")
        drawing.rect(header.x - 18, folder_y - 49, 220, 27,
                     fill="#f1eee6", stroke="#b9b2a3")
        drawing.text(header.x - 4, folder_y - 31, f"SESSION {number}",
                     color=COLORS[number - 1], size=13, mono=False)

    edges: list[dict] = []

    def connect(first: Card, pattern: str, last: Card, target: str,
                relation: str, *, column: int | None = None) -> None:
        right = last.x + last.width / 2 >= first.x + first.width / 2
        # Same-column derivations use the right-hand gutter of their folder.
        start = first.port(pattern, right=right, column=column)
        same_column = first.x == last.x and first.width == last.width
        end = last.port(target, right=not right if not same_column else True)
        edges.append({"from": start, "to": end, "relation": relation})

    comparison = cards["comparison-c"]
    for session, (query, job, result) in enumerate(zip(queries, jobs, results), 1):
        connect(database, r"\| Download \|", job, r"Connect \[D\]", "uses")
        connect(query, r"\| Submitted pack \|", job, rf"\*\*J{session}:", "uses")
        connect(job, rf"\*\*J{session}:", result, r"\| Downloaded result ZIP", "derived")
        connect(result, r"\| Downloaded result ZIP", result, r"\| Extracted raw SARIF", "derived")
        connect(result, r"\| Extracted raw SARIF", result, r"\| Ingested per-job SQLite", "derived")
        connect(result, r"\| Ingested per-job SQLite", result, r"\| Session findings DuckDB", "derived")
        connect(result, r"\| Extracted raw SARIF", result, r"\| Frozen findings", "derived")
        connect(result, r"\| Frozen findings", comparison, rf"\(#s{session}-results\)", "compared")
        if session >= 3:
            connect(queries[0], r"\| Submitted pack \|", query,
                    r"\(#s1-accepted-query\)", "derived")

    seen = set()
    for current in cards.values():
        for number, line in current.section.lines:
            for match in re.finditer(r"\[[^\]]+\]\(#([^)]+)\)", line):
                anchor = match[1]
                if anchor not in cards:
                    raise ValueError(f"unresolved section link: {anchor}")
                pair = (current.section.anchor, anchor)
                if anchor == current.section.anchor or pair in seen:
                    continue
                seen.add(pair)
                pattern = "^" + re.escape(line) + "$"
                connect(current, pattern, cards[anchor], r"^#{1,3} ",
                        "reference", column=match.start())

    # Wires are behind the documents; only their field-level ports are on top.
    layout = {
        "above_folders": folder_y - 235,
        "below_queries": max(item.bottom for item in queries) + 40,
        "below_folders": folder_bottom + 70,
    }
    for edge_index, edge in enumerate(
            sorted(edges, key=lambda item: item["relation"] != "reference")):
        edge["path"] = wire(drawing, edge["from"], edge["to"],
                            edge["relation"], edge_index, layout)
    for current in cards.values():
        current.draw(drawing)
    for edge in edges:
        color = RELATIONS[edge["relation"]][0]
        for endpoint in (edge["from"], edge["to"]):
            drawing.rect(endpoint["x"] - 3, endpoint["y"] - 3, 6, 6,
                         fill=color, stroke=PAPER,
                         href="#" + endpoint["section"],
                         tooltip=f"{edge['relation']}: {endpoint['section']}, "
                         f"source line {endpoint['line']}, column {endpoint['column'] + 1}")
    drawing.text(100, height - 85,
                 "Six folders, one fixed database, many representations. "
                 "The connections are the work.", size=22, mono=False)
    drawing.text(100, height - 50, name, size=12)
    drawing.details = {
        "font_points": 9,
        "cards": [
            {"id": item.section.anchor, "box": [item.x, item.y, item.width, item.height],
             "source_lines": [number for number, _ in item.section.lines]}
            for item in cards.values()
        ],
        "edges": edges,
    }
    return drawing


def validate(drawing: Drawing) -> None:
    expected = drawing.source.splitlines()
    found: dict[int, list[tuple[int, str]]] = {}
    for command in drawing.commands:
        attributes = command["attributes"]
        if "data_source_line" not in attributes:
            continue
        number = attributes["data_source_line"]
        found.setdefault(number, []).append(
            (attributes["data_source_column"], command["text"]))
        x, y = command["x"], command["y"]
        if not 0 < x < drawing.width or not 0 < y < drawing.height:
            raise ValueError(f"source line {number} falls outside the poster")
    if set(found) != set(range(1, len(expected) + 1)):
        raise ValueError("poster does not contain every source line")
    for number, line in enumerate(expected, 1):
        chunks = sorted(found[number])
        if "".join(text for _, text in chunks) != line:
            raise ValueError(f"poster changed source line {number}")


def render(drawing: Drawing, destination: Path, stem: str, gs: str) -> None:
    validate(drawing)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{stem}.svg").write_text(drawing.svg(), encoding="utf-8")
    postscript = destination / f"{stem}.ps"
    postscript.write_text(drawing.postscript(), encoding="ascii")
    (destination / f"{stem}.json").write_text(
        json.dumps(drawing.audit(), indent=2) + "\n", encoding="utf-8")
    for device, suffix, extra in (
        ("pdfwrite", "pdf", ["-dAutoRotatePages=/None", "-dEmbedAllFonts=true"]),
        ("png16m", "png", [f"-r{72 * 1800 / max(drawing.width, drawing.height):.6f}",
                          "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4"]),
    ):
        subprocess.run([
            gs, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", f"-sDEVICE={device}",
            *extra, f"-sOutputFile={destination / f'{stem}.{suffix}'}",
            str(postscript),
        ], check=True, timeout=180)
    print(f"{stem}: {drawing.width / 72:.1f} x {drawing.height / 72:.1f} inches, "
          f"{drawing.audit()['source_lines']} complete source lines")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE / "rendered")
    args = parser.parse_args()
    gs = shutil.which("gs")
    if not gs:
        parser.error("Ghostscript (gs) is required for PDF and PNG output")
    for filename, stem, builder in (
        ("six-session-shell-equivalent.sh", "six-session-command-spaghetti", commands_poster),
        ("six-session-storage-equivalent.md", "six-session-storage-wiring", storage_poster),
    ):
        source = (HERE / filename).read_text(encoding="ascii")
        render(builder(source, filename), args.output_dir, stem, gs)


if __name__ == "__main__":
    main()

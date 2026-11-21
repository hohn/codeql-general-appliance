from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from cgawf import tags  # noqa: E402
from cgawf.repository import WorkflowError  # noqa: E402


class TagsTest(unittest.TestCase):
    def test_profiles_expand_to_canonical_facets(self) -> None:
        value = tags.normalize([
            "user:viewable",
            "subject:database-catalogue",
            "searchable:true",
        ])
        self.assertEqual(value["profiles"], ["user:viewable"])
        self.assertEqual(value["canonical"], [
            "audience:user",
            "prominence:detail",
            "subject:database-catalogue",
            "searchable:true",
        ])
        self.assertEqual(value["values"]["audience"], ["user"])

    def test_duplicate_expansions_are_removed(self) -> None:
        value = tags.normalize(["user:viewable", "audience:user"])
        self.assertEqual(value["canonical"].count("audience:user"), 1)

    def test_unknown_keys_and_controlled_values_fail(self) -> None:
        for value in ("owner:user", "audience:everyone", "user:unknown"):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                tags.normalize([value])

    def test_matching_accepts_profiles_and_canonical_tags(self) -> None:
        value = tags.normalize(["user:primary-interest-data"])
        self.assertTrue(tags.matches(value, ["user:primary-interest-data"]))
        self.assertTrue(tags.matches(
            value,
            ["audience:user", "prominence:primary"],
        ))
        self.assertFalse(tags.matches(value, ["audience:system"]))


if __name__ == "__main__":
    unittest.main()

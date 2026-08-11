# do not pre load

import unittest

from .editor_project_search import (
    find_literal_matches,
    replace_selected_matches,
)


class TestEditorProjectSearch(unittest.TestCase):
    def test_literal_search_returns_line_context_and_respects_options(self):
        source = "alpha beta\nAlpha alphabet alpha\n"

        matches, truncated = find_literal_matches(
            source, "alpha", case_sensitive=False, whole_word=True
        )

        self.assertFalse(truncated)
        self.assertEqual([match["line"] for match in matches], [1, 2, 2])
        self.assertEqual([match["column"] for match in matches], [1, 1, 16])
        self.assertEqual(matches[1]["match"], "Alpha")
        self.assertNotIn("alphabet", [match["match"] for match in matches])

    def test_search_reports_when_a_per_file_limit_truncates_results(self):
        matches, truncated = find_literal_matches("x x x", "x", limit=2)

        self.assertEqual(len(matches), 2)
        self.assertTrue(truncated)

    def test_replace_only_changes_selected_verified_matches(self):
        source = "name and name and NAME"
        matches, _truncated = find_literal_matches(source, "name")

        updated, count = replace_selected_matches(
            source,
            "name",
            "client",
            [matches[0], matches[2]],
        )

        self.assertEqual(updated, "client and name and client")
        self.assertEqual(count, 2)

    def test_empty_replacement_is_supported(self):
        source = "remove me"
        matches, _truncated = find_literal_matches(source, "remove ")

        updated, count = replace_selected_matches(source, "remove ", "", matches)

        self.assertEqual(updated, "me")
        self.assertEqual(count, 1)

    def test_changed_or_overlapping_spans_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "no longer match"):
            replace_selected_matches(
                "new source", "old", "replacement", [{"start": 0, "end": 3}]
            )
        with self.assertRaisesRegex(ValueError, "overlap"):
            replace_selected_matches(
                "aaaa",
                "aa",
                "b",
                [{"start": 0, "end": 2}, {"start": 1, "end": 3}],
            )


if __name__ == "__main__":
    unittest.main()

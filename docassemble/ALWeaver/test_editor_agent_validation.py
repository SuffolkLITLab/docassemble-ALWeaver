# do not pre-load

"""Tests for confidence when attaching diagnostics to source blocks."""

import unittest

from .editor_agent_validation import annotate_lint_findings, resolve_lint_block_id


class TestLintFindingBlockResolution(unittest.TestCase):
    blocks = [
        {
            "id": "first",
            "type": "question",
            "title": "First screen",
            "line_start": 1,
            "line_end": 5,
            "yaml": "question: shared phrase\n",
        },
        {
            "id": "second",
            "type": "question",
            "title": "Second screen",
            "line_start": 6,
            "line_end": 10,
            "yaml": "question: shared phrase\n",
        },
    ]

    def test_repeated_problematic_text_does_not_create_a_confident_link(self):
        finding = {"problematic_text": "shared phrase", "message": "Ambiguous"}

        self.assertIsNone(resolve_lint_block_id(finding, self.blocks))

        annotated = annotate_lint_findings([finding], self.blocks)[0]
        self.assertNotIn("block_id", annotated)
        self.assertNotIn("block_title", annotated)
        self.assertNotIn("line_start", annotated)

    def test_unique_problematic_text_still_links_to_its_source_block(self):
        finding = {"problematic_text": "second-only text", "message": "Unique"}
        blocks = [
            self.blocks[0],
            dict(self.blocks[1], yaml="question: second-only text\n"),
        ]

        annotated = annotate_lint_findings([finding], blocks)[0]

        self.assertEqual(annotated["block_id"], "second")
        self.assertEqual(annotated["block_title"], "Second screen")

    def test_precise_line_mapping_precedes_ambiguous_text(self):
        finding = {
            "line_number": 8,
            "problematic_text": "shared phrase",
            "message": "Line identifies the second screen",
        }

        self.assertEqual(resolve_lint_block_id(finding, self.blocks), "second")


if __name__ == "__main__":
    unittest.main()

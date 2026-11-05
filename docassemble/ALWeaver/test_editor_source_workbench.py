# do not pre-load
"""Source previews must preserve exact text and never execute author code."""

import unittest

from .editor_source_workbench import (
    RECIPES,
    preview_source_action,
    python_offset,
    source_changes,
    utf16_offset,
)
from .source_document import parse_source_document


class TestSourceWorkbench(unittest.TestCase):
    def test_hunks_restore_unicode_and_final_newline(self):
        saved = '# 😀\nquestion: "Before"\n---\ncode: pass'
        working = '# 😀\nquestion: "After"\n---\ncode: pass\n# extra\n'
        hunks = source_changes(saved, working)
        result = working
        for hunk in reversed(hunks):
            start = python_offset(result, hunk["from"])
            end = python_offset(result, hunk["to"])
            self.assertEqual(result[start:end], hunk["before"])
            result = result[:start] + hunk["insert"] + result[end:]
        self.assertEqual(result, saved)
        self.assertEqual(source_changes("", "new\n")[0]["insert"], "")
        self.assertEqual(source_changes("old\n", "")[0]["before"], "")

    def test_recipe_inserts_at_document_boundary_preserving_comments(self):
        source = '# header\nid: authored\nquestion: "Original"\n---\n# untouched\ncode: pass\n'
        for recipe in RECIPES:
            result = preview_source_action(
                "main.yml", source, source, "recipe", recipe_id=recipe["id"], cursor=15
            )
            self.assertTrue(
                parse_source_document("main.yml", result["source"]).structurally_valid
            )
            self.assertTrue(
                result["source"].startswith(
                    '# header\nid: authored\nquestion: "Original"\n'
                )
            )
            self.assertTrue(result["source"].endswith("---\n# untouched\ncode: pass\n"))
            edit = result["edit"]
            pos = python_offset(source, edit["from"])
            self.assertEqual(
                source[:pos] + edit["insert"] + source[pos:], result["source"]
            )
            empty = preview_source_action(
                "main.yml", "", "", "recipe", recipe_id=recipe["id"], cursor=0
            )
            self.assertTrue(
                parse_source_document("main.yml", empty["source"]).structurally_valid
            )

    def test_recipe_rejects_duplicate_example_ids(self):
        recipe = RECIPES[-1]
        with self.assertRaisesRegex(ValueError, "Rename the existing"):
            preview_source_action(
                "main.yml",
                "",
                recipe["source"],
                "recipe",
                recipe_id=recipe["id"],
                cursor=0,
            )

    def test_invalid_source_and_cursor_cannot_insert(self):
        with self.assertRaises(ValueError):
            preview_source_action(
                "main.yml", "", "question: [", "recipe", recipe_id="text-template"
            )
        for cursor in (-1, 9999, True):
            with self.assertRaises(ValueError):
                preview_source_action(
                    "main.yml",
                    "",
                    "code: pass",
                    "recipe",
                    recipe_id="text-template",
                    cursor=cursor,
                )
        with self.assertRaises(ValueError):
            python_offset("😀", 1)
        self.assertEqual(python_offset("😀", utf16_offset("😀")), 1)

    def test_repairs_keep_author_source(self):
        source = '# keep\nquestion: "A question"\nfields:\n  - Answer: answer\n'
        result = preview_source_action("main.yml", source, source, "repair")
        self.assertGreater(result["repair_count"], 0)
        self.assertIn("# keep", result["source"])
        self.assertIn('question: "A question"', result["source"])
        self.assertIn("id:", result["source"])
        self.assertEqual(
            source, '# keep\nquestion: "A question"\nfields:\n  - Answer: answer\n'
        )

    def test_outline_reads_unsaved_blocks_without_evaluation(self):
        source = 'id: new\nquestion: Changed\nfields:\n  - Answer: answer\n---\ncode: |\n  raise RuntimeError("never execute")\n'
        result = preview_source_action("main.yml", "", source, "outline")
        self.assertEqual(result["blocks"][0]["id"], "new")
        self.assertEqual(result["blocks"][0]["line_start"], 1)
        self.assertEqual(len(result["blocks"]), 2)

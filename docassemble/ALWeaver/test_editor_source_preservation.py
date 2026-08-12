# do not pre-load
"""Regression tests for lossless graphical-editor block operations."""

import unittest

from .editor_utils import (
    comment_out_block_in_yaml,
    delete_block_from_yaml,
    enable_commented_block_in_yaml,
    insert_block_in_yaml,
    parse_interview_yaml,
    reorder_blocks_in_yaml,
    update_block_in_yaml,
)

SOURCE = (
    "# file header\n"
    "metadata:\n"
    "  title: 'Quoted' # metadata comment\n"
    "--- # separator annotation\n"
    "# question lead\n"
    "id: intro\n"
    "question: 'Original' # question comment\n"
    "fields:\n"
    "  - 'Name': user_name # field comment\n"
    "---\n"
    "\n"
    "---\n"
    "# code lead\n"
    "id: calculation\n"
    "code: |\n"
    "  # Python comment\n"
    "  answer = 'yes'\n"
)


class TestEditorSourcePreservation(unittest.TestCase):
    def test_parser_returns_exact_block_yaml(self):
        question = next(
            block
            for block in parse_interview_yaml(SOURCE)["blocks"]
            if block["id"] == "intro"
        )
        self.assertIn("# question lead", question["yaml"])
        self.assertIn("'Original' # question comment", question["yaml"])
        self.assertIn("'Name': user_name # field comment", question["yaml"])

    def test_graphical_value_edit_preserves_all_unchanged_annotations(self):
        graphical_yaml = (
            "id: intro\n" "question: |\n" "  Edited\n" "fields:\n" "- Name: user_name\n"
        )
        updated = update_block_in_yaml(
            SOURCE,
            "intro",
            graphical_yaml,
            preserve_unchanged_annotations=True,
        )
        self.assertEqual(
            updated,
            SOURCE.replace("'Original'", "|\n  Edited\n"),
        )

    def test_graphical_defaults_do_not_erase_explicit_field_annotations(self):
        source = SOURCE.replace(
            "  - 'Name': user_name # field comment\n",
            "  - 'Name': user_name # field comment\n    datatype: text\n",
        )
        graphical_yaml = (
            "id: intro\n" "question: Edited\n" "fields:\n" "- Name: user_name\n"
        )
        updated = update_block_in_yaml(
            source,
            "intro",
            graphical_yaml,
            preserve_unchanged_annotations=True,
        )
        self.assertIn("'Name': user_name # field comment", updated)
        self.assertIn("    datatype: text", updated)

    def test_graphical_edit_preserves_unchanged_literal_scalar_style(self):
        source = SOURCE.replace(
            "question: 'Original' # question comment\n",
            "question: 'Original' # question comment\n"
            "subquestion: |\n"
            "  Literal text.\n",
        )
        graphical_yaml = (
            "id: intro\n"
            "question: Edited\n"
            "subquestion: Literal text.\n"
            "fields:\n"
            "- Name: user_name\n"
        )
        updated = update_block_in_yaml(
            source,
            "intro",
            graphical_yaml,
            preserve_unchanged_annotations=True,
        )
        self.assertIn("subquestion: |\n  Literal text.\n", updated)

    def test_source_edit_replaces_only_target_document(self):
        edited = (
            "# new question lead\n"
            "id: intro\n"
            "question: Edited # new inline comment\n"
            "fields:\n"
            "  - Name: user_name\n"
        )
        updated = update_block_in_yaml(SOURCE, "intro", edited)
        before, rest = SOURCE.split("# question lead", 1)
        _old_question, after = rest.split("---\n\n---", 1)
        self.assertEqual(updated, before + edited + "---\n\n---" + after)

    def test_disable_then_enable_is_byte_exact(self):
        disabled = comment_out_block_in_yaml(SOURCE, "intro")
        self.assertIn("# # question lead", disabled)
        self.assertEqual(enable_commented_block_in_yaml(disabled, "intro"), SOURCE)

    def test_delete_preserves_every_other_source_byte(self):
        updated = delete_block_from_yaml(SOURCE, "intro")
        expected = SOURCE.replace(
            "--- # separator annotation\n"
            "# question lead\n"
            "id: intro\n"
            "question: 'Original' # question comment\n"
            "fields:\n"
            "  - 'Name': user_name # field comment\n",
            "",
        )
        self.assertEqual(updated, expected)

    def test_reorder_preserves_bodies_separators_and_empty_document(self):
        ids = [block["id"] for block in parse_interview_yaml(SOURCE)["blocks"]]
        updated = reorder_blocks_in_yaml(SOURCE, list(reversed(ids)))
        self.assertIn("--- # separator annotation\n", updated)
        self.assertIn("---\n\n---\n", updated)
        for annotation in (
            "# file header",
            "# metadata comment",
            "# question lead",
            "# question comment",
            "# field comment",
            "# code lead",
            "# Python comment",
        ):
            self.assertEqual(updated.count(annotation), 1)

    def test_reorder_rejects_an_incomplete_list(self):
        with self.assertRaisesRegex(ValueError, "every interview block"):
            reorder_blocks_in_yaml(SOURCE, ["intro"])

    def test_insert_after_block_preserves_every_existing_byte(self):
        inserted = "id: added\nquestion: Added\n"
        updated = insert_block_in_yaml(SOURCE, inserted, "intro")
        insertion_point = SOURCE.index("---\n\n---", SOURCE.index("id: intro"))
        self.assertEqual(
            updated,
            SOURCE[:insertion_point] + "---\n" + inserted + SOURCE[insertion_point:],
        )

    def test_insert_rejects_a_duplicate_id_without_changing_source(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            insert_block_in_yaml(
                SOURCE, "id: intro\nquestion: Duplicate\n", "calculation"
            )

    def test_duplicate_ids_are_refused_instead_of_replacing_two_blocks(self):
        duplicated = SOURCE + "---\nid: intro\nquestion: Other\n"
        with self.assertRaisesRegex(ValueError, "duplicated"):
            update_block_in_yaml(duplicated, "intro", "id: intro\nquestion: Edited\n")


if __name__ == "__main__":
    unittest.main()

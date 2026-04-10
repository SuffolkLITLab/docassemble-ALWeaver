import unittest

from .editor_utils import (
    comment_out_block_in_yaml,
    delete_block_from_yaml,
    enable_commented_block_in_yaml,
    parse_interview_yaml,
    reorder_blocks_in_yaml,
)


class TestEditorBlockActions(unittest.TestCase):
    def test_comment_out_block_in_yaml_prefixes_each_line(self):
        yaml_text = (
            "---\n"
            "id: first\n"
            "question: First\n"
            "---\n"
            "id: second\n"
            "question: Second\n"
        )

        updated = comment_out_block_in_yaml(yaml_text, "first")

        self.assertIn("# id: first", updated)
        self.assertIn("# question: |", updated)
        self.assertIn("#   First", updated)
        self.assertIn("id: second", updated)
        self.assertNotIn("question: First\n---\nid: second", updated)

        restored = enable_commented_block_in_yaml(updated, "first")
        self.assertIn("id: first", restored)
        self.assertIn("question: |", restored)

    def test_delete_and_reorder_block_helpers(self):
        yaml_text = (
            "---\n"
            "id: first\n"
            "question: First\n"
            "---\n"
            "id: second\n"
            "question: Second\n"
            "---\n"
            "id: third\n"
            "question: Third\n"
        )

        reordered = reorder_blocks_in_yaml(yaml_text, ["third", "first", "second"])
        deleted = delete_block_from_yaml(reordered, "first")

        self.assertTrue(reordered.startswith("id: third"))
        self.assertIn("id: first", reordered)
        self.assertNotIn("id: first", deleted)
        self.assertIn("id: third", deleted)
        self.assertIn("id: second", deleted)

    def test_parse_interview_yaml_preserves_commented_blocks_and_skips_empty_docs(self):
        yaml_text = (
            "---\n"
            "---\n"
            "# id: disabled\n"
            "# question: Disabled\n"
            "---\n"
            "id: active\n"
            "question: Active\n"
        )

        model = parse_interview_yaml(yaml_text)

        self.assertEqual(len(model["blocks"]), 2)
        self.assertEqual(model["blocks"][0]["type"], "commented")
        self.assertEqual(model["blocks"][0]["id"], "disabled")
        self.assertEqual(model["blocks"][0]["title"], "Disabled")
        self.assertEqual(model["blocks"][0]["data"]["_commented_type"], "question")
        self.assertIn("question", model["blocks"][0]["tags"])
        self.assertIn("# id: disabled", model["blocks"][0]["yaml"])
        self.assertEqual(model["blocks"][1]["id"], "active")


if __name__ == "__main__":
    unittest.main()

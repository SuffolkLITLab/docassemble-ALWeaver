import unittest

from .editor_utils import parse_interview_yaml


class TestEditorUtilsBlockTypes(unittest.TestCase):
    def test_detects_new_editor_block_types(self):
        source_yaml = (
            "id: inc\n"
            "include:\n"
            "  - other.yml\n"
            "---\n"
            "id: attach\n"
            "attachment:\n"
            "  name: Letter\n"
            "  filename: letter\n"
            "---\n"
            "id: review_1\n"
            "question: Review\n"
            "review:\n"
            "  - Edit name: user.name.first\n"
            "---\n"
            "id: table_1\n"
            "table: users.table\n"
            "rows: users\n"
            "columns:\n"
            "  - Name: row_item.name.full()\n"
            "---\n"
            "id: template_1\n"
            "template: help_text\n"
            "subject: |\n"
            "  Help\n"
            "content: |\n"
            "  Details\n"
            "---\n"
            "id: terms_1\n"
            "terms:\n"
            "  term one: |\n"
            "    Definition\n"
            "---\n"
            "id: sections_1\n"
            "sections:\n"
            "  - intro: Introduction\n"
        )

        model = parse_interview_yaml(source_yaml)
        types = [block["type"] for block in model["blocks"]]

        self.assertIn("includes", types)
        self.assertIn("attachment", types)
        self.assertIn("review", types)
        self.assertIn("table", types)
        self.assertIn("template", types)
        self.assertIn("terms", types)
        self.assertIn("sections", types)

    def test_review_block_takes_precedence_over_question(self):
        source_yaml = (
            "id: review_2\n"
            "question: Review this section\n"
            "review:\n"
            "  - Edit: some_var\n"
        )

        model = parse_interview_yaml(source_yaml)
        self.assertEqual(model["blocks"][0]["type"], "review")


if __name__ == "__main__":
    unittest.main()

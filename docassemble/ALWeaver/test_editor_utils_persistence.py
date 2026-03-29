import unittest

from .editor_utils import parse_interview_yaml, update_block_in_yaml


class TestEditorUtilsPersistence(unittest.TestCase):
    def test_update_block_in_yaml_persists_question_subquestion(self):
        source_yaml = (
            "id: intro\n"
            "question: Original question\n"
            "subquestion: |\n"
            "  Original subquestion\n"
            "---\n"
            "id: next\n"
            "question: Next question\n"
        )

        model = parse_interview_yaml(source_yaml)
        intro_id = model["blocks"][0]["id"]

        updated_block_yaml = (
            "id: intro\n"
            "question: Original question\n"
            "subquestion: |\n"
            "  Edited subquestion preview text\n"
        )

        updated_yaml = update_block_in_yaml(source_yaml, intro_id, updated_block_yaml)
        reparsed = parse_interview_yaml(updated_yaml)

        self.assertTrue(updated_yaml.endswith("\n"))
        self.assertEqual(
            reparsed["blocks"][0]["data"]["subquestion"].strip(),
            "Edited subquestion preview text",
        )
        self.assertEqual(
            reparsed["blocks"][1]["data"]["question"].strip(),
            "Next question",
        )

    def test_update_block_in_yaml_rejects_missing_block(self):
        source_yaml = "id: only\nquestion: One\n"
        with self.assertRaises(ValueError):
            update_block_in_yaml(source_yaml, "missing", "id: missing\nquestion: No\n")


if __name__ == "__main__":
    unittest.main()

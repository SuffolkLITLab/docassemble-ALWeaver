import unittest
import types
from unittest.mock import Mock, patch

import docassemble

from .editor_utils import (
    canonical_block_yaml,
    parse_interview_yaml,
    playground_interview_url,
    update_block_in_yaml,
)


class TestEditorUtilsPersistence(unittest.TestCase):
    def test_playground_interview_url_requests_fresh_session(self):
        base_mod = types.ModuleType("docassemble.base")
        functions_mod = types.ModuleType("docassemble.base.functions")
        functions_mod.url_of = Mock(return_value="/interview")
        base_mod.functions = functions_mod

        with patch.dict(
            "sys.modules",
            {
                "docassemble.base": base_mod,
                "docassemble.base.functions": functions_mod,
            },
        ), patch.object(docassemble, "base", base_mod, create=True):
            result = playground_interview_url(7, "ProjectA", "interview.yml")

        self.assertEqual(result, "/interview")
        functions_mod.url_of.assert_called_once_with(
            "interview",
            i="docassemble.playground7ProjectA:interview.yml",
            reset=1,
            cache=0,
        )

    def test_canonical_block_yaml_forces_literal_style_for_single_line_code(self):
        rendered = canonical_block_yaml(
            {
                "id": "code_1",
                "code": "some_var = 1",
            }
        )

        self.assertIn("code: |", rendered)
        self.assertIn("  some_var = 1", rendered)

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

    def test_update_block_in_yaml_preserves_question_fields_and_choices(self):
        source_yaml = (
            "id: intro\n"
            "question: Original question\n"
            "fields:\n"
            "  - name: Name\n"
            "---\n"
            "id: next\n"
            "question: Next question\n"
        )

        model = parse_interview_yaml(source_yaml)
        intro_id = model["blocks"][0]["id"]

        updated_block_yaml = (
            "id: intro\n"
            "question: Edited question\n"
            "fields:\n"
            "  - label: Favorite color\n"
            "    field: favorite_color\n"
            "    datatype: radio\n"
            "    choices:\n"
            "      - 1\n"
            "      - 2\n"
            "      - 3\n"
        )

        updated_yaml = update_block_in_yaml(source_yaml, intro_id, updated_block_yaml)
        reparsed = parse_interview_yaml(updated_yaml)

        first_block = reparsed["blocks"][0]["data"]
        self.assertEqual(first_block["question"].strip(), "Edited question")
        self.assertEqual(first_block["fields"][0]["field"], "favorite_color")
        self.assertEqual(first_block["fields"][0]["datatype"], "radio")
        self.assertEqual(first_block["fields"][0]["choices"], [1, 2, 3])

    def test_update_block_in_yaml_preserves_continue_button_metadata(self):
        source_yaml = (
            "id: intro\n"
            "question: Original question\n"
            "continue button field: intro_continue\n"
            "continue button label: Next\n"
            "---\n"
            "id: next\n"
            "question: Next question\n"
        )

        model = parse_interview_yaml(source_yaml)
        intro_id = model["blocks"][0]["id"]

        updated_block_yaml = (
            "id: intro\n"
            "question: Updated question\n"
            "continue button field: intro_continue\n"
            "continue button label: Continue\n"
        )

        updated_yaml = update_block_in_yaml(source_yaml, intro_id, updated_block_yaml)
        reparsed = parse_interview_yaml(updated_yaml)

        first_block = reparsed["blocks"][0]["data"]
        self.assertEqual(first_block["continue button field"], "intro_continue")
        self.assertEqual(first_block["continue button label"], "Continue")
        self.assertTrue(updated_yaml.endswith("\n"))

    def test_update_block_in_yaml_rejects_missing_block(self):
        source_yaml = "id: only\nquestion: One\n"
        with self.assertRaises(ValueError):
            update_block_in_yaml(source_yaml, "missing", "id: missing\nquestion: No\n")

    def test_update_block_in_yaml_keeps_code_literal_scalar_style(self):
        source_yaml = "id: block_1\n" "code: old_value = 0\n"

        model = parse_interview_yaml(source_yaml)
        block_id = model["blocks"][0]["id"]

        updated = update_block_in_yaml(
            source_yaml,
            block_id,
            "id: block_1\ncode: some_var = 1\n",
        )

        self.assertIn("code: |", updated)
        self.assertIn("  some_var = 1", updated)

    def test_parse_interview_yaml_builds_editor_metadata_for_multiline_objects(self):
        source_yaml = (
            "id: bundles\n"
            "objects:\n"
            "  - al_user_bundle: ALDocumentBundle.using(\n"
            "      elements=[instructions, attachment_one] + [item for item in extras],\n"
            '      filename="bundle",\n'
            '      title="All forms to download",\n'
            "      enabled=True\n"
            "      )\n"
        )

        model = parse_interview_yaml(source_yaml)
        block = model["blocks"][0]

        self.assertEqual(block["type"], "objects")
        self.assertEqual(block["yaml"], source_yaml.strip())
        self.assertIn("editor_objects", block)
        self.assertEqual(block["editor_objects"][0]["mode"], "using")
        self.assertEqual(block["editor_objects"][0]["class_name"], "ALDocumentBundle")
        self.assertIn('filename="bundle"', block["editor_objects"][0]["using_args"])
        self.assertTrue(block["editor_objects"][0]["is_document_bundle"])

    def test_update_block_in_yaml_preserves_multiline_objects_expression(self):
        source_yaml = (
            "id: bundles\n"
            "objects:\n"
            "  - al_user_bundle: ALDocumentBundle.using(elements=[attachment_one])\n"
            "---\n"
            "id: next\n"
            "question: Next question\n"
        )

        model = parse_interview_yaml(source_yaml)
        block_id = model["blocks"][0]["id"]
        updated_block_yaml = (
            "id: bundles\n"
            "objects:\n"
            "  - al_user_bundle: ALDocumentBundle.using(\n"
            "      elements=[instructions, attachment_one] + [item for item in extras],\n"
            '      filename="bundle",\n'
            '      title="All forms to download",\n'
            "      enabled=True\n"
            "      )\n"
        )

        updated_yaml = update_block_in_yaml(source_yaml, block_id, updated_block_yaml)
        reparsed = parse_interview_yaml(updated_yaml)

        self.assertIn("  - al_user_bundle: ALDocumentBundle.using(", updated_yaml)
        self.assertIn('      filename="bundle",', updated_yaml)
        self.assertIn("      enabled=True", updated_yaml)
        self.assertIn("      )", updated_yaml)
        self.assertEqual(reparsed["blocks"][0]["yaml"], updated_block_yaml.strip())
        self.assertEqual(reparsed["blocks"][1]["data"]["question"], "Next question")


if __name__ == "__main__":
    unittest.main()

# do not pre-load

"""Normalisation rules shared by the AI screen drafter and the editing agent.

Question text, subquestions and field labels are Markdown. The normaliser used
to collapse every run of whitespace, which flattened paragraph breaks and
bullet lists into one unreadable line — silent data loss for anyone editing an
existing screen. These tests pin the line structure that has to survive.
"""

import unittest

from .editor_ai_utils import (
    _safe_prose,
    _safe_text,
    normalize_generated_fields,
    normalize_generated_screen,
)
from .editor_utils import canonical_block_yaml


class TestProseNormalisation(unittest.TestCase):
    def test_paragraphs_and_lists_survive(self):
        source = "Tell us about:\n\n- your children\n- your income\n\nBe thorough."
        self.assertEqual(_safe_prose(source), source)

    def test_line_endings_are_normalised(self):
        self.assertEqual(_safe_prose("one\r\ntwo\rthree"), "one\ntwo\nthree")

    def test_trailing_whitespace_and_blank_runs_are_tidied(self):
        self.assertEqual(
            _safe_prose("  first line   \n\n\n\n  second   \n\n"),
            "  first line\n\n  second",
        )

    def test_markdown_indentation_is_left_alone(self):
        source = "Steps:\n\n1. First\n    - nested detail\n2. Second"
        self.assertEqual(_safe_prose(source), source)

    def test_single_line_values_are_still_collapsed(self):
        # Identifiers and datatypes must never gain a newline.
        self.assertEqual(_safe_text("  text \n type "), "text type")


class TestScreenNormalisation(unittest.TestCase):
    def test_a_multi_line_subquestion_is_preserved_end_to_end(self):
        screen = normalize_generated_screen(
            {
                "question": "Tell us about your children",
                "subquestion": (
                    "Please list **every** child, including:\r\n\r\n"
                    "- stepchildren\r\n- adopted children\r\n\r\n\r\n"
                    "If you are unsure, include them.   \n"
                ),
                "fields": [
                    {
                        "label": "Child's name\n\nAs it appears on the birth certificate",
                        "field": "children[0].name.first",
                    }
                ],
            }
        )
        self.assertEqual(
            screen["subquestion"],
            "Please list **every** child, including:\n\n"
            "- stepchildren\n- adopted children\n\n"
            "If you are unsure, include them.",
        )
        self.assertIn("\n", screen["fields"][0]["label"])

        serialized = canonical_block_yaml(
            {
                "id": "children",
                "question": screen["question"],
                "subquestion": screen["subquestion"],
                "fields": screen["fields"],
            }
        )
        # Block literals, not escaped one-liners.
        self.assertIn("subquestion: |\n", serialized)
        self.assertIn("  - stepchildren\n", serialized)
        self.assertNotIn("\\n", serialized)

    def test_a_continue_button_field_is_never_invented_from_nothing(self):
        screen = normalize_generated_screen({"question": "Anything?"})
        self.assertEqual(screen["continue_button_field"], "")

    def test_fields_and_continue_button_field_are_not_combined(self):
        screen = normalize_generated_screen(
            {
                "question": "Contact information",
                "fields": [{"label": "Email", "field": "email"}],
                "continue_button_field": "continue",
            }
        )
        self.assertEqual(screen["continue_button_field"], "")

    def test_field_variables_stay_on_one_line(self):
        fields = normalize_generated_fields(
            [{"label": "Name\nwith a break", "field": " users[0].name.first \n"}]
        )
        self.assertEqual(fields[0]["field"], "users[0].name.first")
        self.assertIn("\n", fields[0]["label"])


if __name__ == "__main__":
    unittest.main()

# do not pre-load
import unittest
from unittest.mock import patch

from . import interview_generator as interview_generator_module
from .interview_generator import (
    DAFieldGroup,
    DADataType,
    DAInterview,
    _field_type_from_definition,
    _get_continue_button_field,
    _merge_field_definitions_into_screens,
    get_question_file_variables,
)


class test_field_definition_types(unittest.TestCase):
    def test_field_type_from_enum(self):
        self.assertEqual(
            _field_type_from_definition({"field": "x", "datatype": DADataType.TEXT}),
            "text",
        )
        self.assertEqual(
            _field_type_from_definition({"field": "x", "datatype": DADataType.RADIO}),
            "multiple choice radio",
        )

    def test_field_type_from_legacy_input_type_key(self):
        self.assertEqual(
            _field_type_from_definition(
                {"field": "x", "input type": "skip_this_field"}
            ),
            "skip this field",
        )

    def test_merge_screens_accepts_snake_case_continue_button_field(self):
        screens = [
            {
                "question": "Screen 1",
                "continue_button_field": "agree_to_continue",
                "fields": [{"field": "petitioner_name"}],
            }
        ]
        merged = _merge_field_definitions_into_screens(screens)
        self.assertEqual(merged[0].get("continue button field"), "agree_to_continue")

    def test_get_question_file_variables_accepts_both_continue_field_keys(self):
        screens = [
            {
                "question": "Screen 1",
                "continue_button_field": "agree_one",
                "fields": [],
            },
            {
                "question": "Screen 2",
                "continue button field": "agree_two",
                "fields": [],
            },
        ]
        fields = get_question_file_variables(screens)
        self.assertEqual(fields, ["agree_one", "agree_two"])

    def test_get_continue_button_field_strips_and_ignores_blank(self):
        self.assertEqual(
            _get_continue_button_field({"continue_button_field": "  keep_going  "}),
            "keep_going",
        )
        self.assertEqual(
            _get_continue_button_field({"continue button field": "  next_step  "}),
            "next_step",
        )
        self.assertIsNone(
            _get_continue_button_field({"continue_button_field": "   "})
        )
        self.assertIsNone(
            _get_continue_button_field({"continue button field": "\n\t"})
        )

    def test_create_questions_from_screen_list_accepts_snake_case_continue(self):
        interview = DAInterview()
        interview.create_questions_from_screen_list(
            [
                {
                    "question": "Intro",
                    "continue_button_field": "intro_continue",
                    "fields": [],
                }
            ]
        )
        self.assertEqual(interview.questions[0].continue_button_field, "intro_continue")
        self.assertTrue(interview.questions[0].needs_continue_button_field)

    def test_create_questions_from_screen_list_skips_empty_screen(self):
        interview = DAInterview()
        interview.create_questions_from_screen_list(
            [
                {
                    "question": "   ",
                    "subquestion": "",
                    "continue_button_field": "   ",
                    "fields": [],
                }
            ]
        )
        self.assertEqual(len(interview.questions), 0)

    def test_auto_group_fields_skips_empty_groups(self):
        interview = DAInterview()
        field = interview.all_fields.appendObject()
        field.group = DAFieldGroup.CUSTOM
        field.variable = "petitioner_name"
        field.label = "Petitioner name"
        field.field_type = "text"
        field.final_display_var = "petitioner_name"
        field.has_label = True
        interview.all_fields.gathered = True

        with patch.object(
            interview_generator_module.formfyxer,
            "cluster_screens",
            return_value={"Empty screen": [], "Names": ["petitioner_name"]},
        ):
            interview.auto_group_fields()

        self.assertEqual(len(interview.questions), 1)
        self.assertEqual(interview.questions[0].question_text, "Petitioner name")


if __name__ == "__main__":
    unittest.main()

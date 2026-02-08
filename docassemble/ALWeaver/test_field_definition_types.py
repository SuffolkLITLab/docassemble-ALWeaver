# do not pre-load
import unittest

from .interview_generator import (
    DADataType,
    DAInterview,
    _field_type_from_definition,
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


if __name__ == "__main__":
    unittest.main()

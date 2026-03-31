import unittest
from unittest.mock import patch

from .editor_ai_utils import (
    normalize_generated_fields,
    normalize_generated_screen,
    pick_small_model_name,
    validate_yaml_with_dayamlchecker,
)


class _FakeLlmsWithDefault:
    @staticmethod
    def get_default_model(model_type="small"):
        return "gpt-5-nano"


class _FakeLlmsWithFirstSmall:
    @staticmethod
    def get_first_small_model():
        return "gpt-4o-mini"


class test_editor_ai_utils(unittest.TestCase):
    def test_pick_small_model_prefers_get_default_model(self):
        model = pick_small_model_name(_FakeLlmsWithDefault())
        self.assertEqual(model, "gpt-5-nano")

    def test_pick_small_model_falls_back_to_first_small(self):
        model = pick_small_model_name(_FakeLlmsWithFirstSmall())
        self.assertEqual(model, "gpt-4o-mini")

    def test_normalize_generated_fields_enforces_limits_and_types(self):
        fields = normalize_generated_fields(
            [
                {"label": "Name", "field": "name", "datatype": "text"},
                {"label": "Color", "field": "color", "datatype": "dropdown", "choices": ["Red", "Blue"]},
                {"label": "Bad Type", "field": "bad", "datatype": "notatype"},
                {"label": "Extra 1", "field": "e1", "datatype": "text"},
                {"label": "Extra 2", "field": "e2", "datatype": "text"},
                {"label": "Extra 3", "field": "e3", "datatype": "text"},
                {"label": "Extra 4", "field": "e4", "datatype": "text"},
                {"label": "Extra 5", "field": "e5", "datatype": "text"},
            ],
            allowed_datatypes=["text", "dropdown"],
        )
        self.assertEqual(len(fields), 7)
        self.assertEqual(fields[1]["datatype"], "dropdown")
        self.assertEqual(fields[1]["choices"], ["Red", "Blue"])
        self.assertEqual(fields[2]["datatype"], "text")

    def test_normalize_generated_screen_sets_fallbacks(self):
        screen = normalize_generated_screen(
            {
                "fields": [
                    {"label": "First name", "field": "first_name", "datatype": "text"}
                ]
            }
        )
        self.assertEqual(screen["question"], "Please answer the following questions.")
        self.assertEqual(screen["continue_button_field"], "first_name")
        self.assertEqual(len(screen["fields"]), 1)

    @patch("docassemble.ALWeaver.editor_ai_utils.subprocess.run")
    def test_validate_yaml_with_dayamlchecker_reports_success(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "ok"
        mock_run.return_value.stderr = ""
        ok, message = validate_yaml_with_dayamlchecker("id: good")
        self.assertTrue(ok)
        self.assertEqual(message, "ok")

    @patch("docassemble.ALWeaver.editor_ai_utils.subprocess.run")
    def test_validate_yaml_with_dayamlchecker_reports_failure(self, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "bad yaml"
        ok, message = validate_yaml_with_dayamlchecker("id: bad")
        self.assertFalse(ok)
        self.assertIn("bad yaml", message)


if __name__ == "__main__":
    unittest.main()

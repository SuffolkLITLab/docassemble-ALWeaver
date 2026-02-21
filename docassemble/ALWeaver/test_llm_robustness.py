import unittest
from types import MethodType
from unittest.mock import patch

import docassemble.base.functions

from . import interview_generator as ig
from .interview_generator import DAFieldGroup, DAInterview, DAQuestionList


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str):
        self._body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _max_bytes=None):
        return self._body


class _FakeLlms:
    def chat_completion(self, **kwargs):
        return {
            "screens": [
                {
                    "question": "LLM Screen",
                    "subquestion": "Generated",
                    "fields": ["custom_one"],
                }
            ]
        }


class TestLLMRobustness(unittest.TestCase):
    def setUp(self):
        docassemble.base.functions.this_thread.current_question = type("", (), {})()
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"

    def _build_interview_with_custom_field(self) -> DAInterview:
        interview = DAInterview()
        field = interview.all_fields.appendObject()
        field.group = DAFieldGroup.CUSTOM
        field.variable = "custom_one"
        field.label = "Custom one"
        field.field_type = "text"
        field.final_display_var = "custom_one"
        field.has_label = True
        interview.all_fields.gathered = True
        return interview

    def test_apply_llm_draft_payload_replaces_existing_questions(self):
        interview = self._build_interview_with_custom_field()
        interview.questions = DAQuestionList()
        old_screen = interview.questions.appendObject()
        old_screen.type = "question"
        old_screen.question_text = "Old screen"
        old_screen.field_list.gathered = True
        interview.questions.gathered = True

        payload = {
            "screen_list": [
                {
                    "question": "New screen",
                    "subquestion": "From payload",
                    "fields": [
                        {
                            "field": "custom_one",
                            "label": "Custom one",
                            "datatype": "text",
                        }
                    ],
                }
            ]
        }

        interview.apply_llm_draft_payload(payload)

        self.assertEqual(len(interview.questions), 1)
        self.assertEqual(interview.questions[0].question_text, "New screen")

    def test_llm_group_fields_apply_replaces_existing_questions(self):
        interview = self._build_interview_with_custom_field()
        interview.questions = DAQuestionList()
        old_screen = interview.questions.appendObject()
        old_screen.type = "question"
        old_screen.question_text = "Old screen"
        old_screen.field_list.gathered = True
        interview.questions.gathered = True

        interview._llm_context_text = MethodType(
            lambda self, **kwargs: "context", interview
        )
        interview._llm_default_model = MethodType(lambda self: "gpt-5-mini", interview)

        with patch.object(ig, "_load_llms_module", return_value=_FakeLlms()):
            result = interview.llm_group_fields(apply=True)

        self.assertTrue(result)
        self.assertEqual(len(interview.questions), 1)
        self.assertEqual(interview.questions[0].question_text, "LLM Screen")

    def test_extract_help_page_text_skips_non_html_content_type(self):
        fake_response = _FakeResponse(b"%PDF-1.7 fake", "application/pdf")
        with patch.object(
            ig.socket,
            "getaddrinfo",
            return_value=[(None, None, None, None, ("93.184.216.34", 0))],
        ):
            with patch.object(ig, "urlopen", return_value=fake_response):
                text = ig._extract_help_page_text("https://example.com/help.pdf")
        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()

# do not pre-load

import json
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


class _FakeFailingLlms:
    def chat_completion(self, **kwargs):
        raise RuntimeError("synthetic llm failure")


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

    def test_apply_llm_draft_payload_refreshes_stale_screen_field_labels(self):
        interview = self._build_interview_with_custom_field()
        payload = {
            "field_updates": {
                "custom_one": {"label": "Improved label", "datatype": "text"}
            },
            "screen_list": [
                {
                    "question": "Screen",
                    "subquestion": "",
                    "fields": [
                        {
                            "field": "custom_one",
                            "label": "Stale label",
                            "datatype": "text",
                        }
                    ],
                }
            ],
        }

        interview.apply_llm_draft_payload(payload)

        self.assertEqual(len(interview.questions), 1)
        self.assertEqual(interview.questions[0].field_list[0].label, "Improved label")

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

    def test_llm_generate_draft_payload_keeps_empty_results_on_failures(self):
        interview = self._build_interview_with_custom_field()
        interview._llm_context_text = MethodType(
            lambda self, **kwargs: "context", interview
        )
        interview._llm_default_model = MethodType(lambda self: "gpt-5-mini", interview)

        with (
            patch.object(ig, "_load_llms_module", return_value=_FakeFailingLlms()),
            patch.object(ig.DAInterview, "llm_prefill_metadata", return_value=False),
            patch.object(ig.DAInterview, "llm_predict_state", return_value=False),
            patch.object(ig.DAInterview, "_prefetch_reference_site", return_value=None),
        ):
            payload = interview.llm_generate_draft_payload()

        self.assertIsInstance(payload.get("field_updates"), dict)
        self.assertEqual(len(payload.get("field_updates", {})), 0)
        self.assertIsInstance(payload.get("screen_list"), list)
        self.assertEqual(len(payload.get("screen_list", [])), 0)


if __name__ == "__main__":
    unittest.main()


class _FakeChoiceLlms:
    """Suggests a radio for `custom_one`, with or without choices to pick from."""

    def __init__(self, choices):
        self.choices = choices

    def chat_completion(self, **kwargs):
        if "Group fields" in str(kwargs.get("system_message", "")):
            return {"screens": [{"question": "Fees", "fields": ["custom_one"]}]}
        suggestion = {"label": "How you will pay", "datatype": "radio"}
        if self.choices is not None:
            suggestion["choices"] = self.choices
        return {"custom_one": suggestion}


class TestLLMChoiceSuggestions(unittest.TestCase):
    setUp = TestLLMRobustness.setUp
    _build_interview_with_custom_field = (
        TestLLMRobustness._build_interview_with_custom_field
    )

    def _refine(self, choices):
        interview = self._build_interview_with_custom_field()
        interview.questions = DAQuestionList()
        interview.questions.gathered = True
        interview._llm_context_text = MethodType(
            lambda self, **kwargs: "context", interview
        )
        interview._llm_default_model = MethodType(lambda self: "gpt-5-mini", interview)
        with patch.object(
            ig, "_load_llms_module", return_value=_FakeChoiceLlms(choices)
        ):
            interview.llm_refine_field_labels(apply=True)
            interview.llm_group_fields(apply=True)
        return interview

    def test_suggested_choices_survive_refinement_and_regrouping(self):
        interview = self._refine(["Pay the fee", "Ask for a waiver: fee waiver"])

        field = interview.all_fields[0]
        self.assertEqual(field.field_type, "multiple choice radio")
        expected = '"Pay the fee": pay_the_fee\n"Ask for a waiver: fee waiver": ask_for_a_waiver_fee_waiver'
        self.assertEqual(field.choices, expected)
        regrouped = interview.questions[0].field_list[0]
        self.assertEqual(regrouped.field_type, "multiple choice radio")
        self.assertEqual(regrouped.choices, expected)

    def test_a_choice_type_without_choices_keeps_the_old_type(self):
        """This used to render `.choices` that was never defined, and crash."""
        interview = self._refine(None)

        self.assertEqual(interview.all_fields[0].field_type, "text")
        self.assertEqual(interview.all_fields[0].label, "How you will pay")
        self.assertEqual(interview.questions[0].field_list[0].field_type, "text")

    def test_a_screen_definition_without_choices_is_asked_as_text(self):
        interview = self._build_interview_with_custom_field()
        interview.questions = DAQuestionList()
        interview.questions.gathered = True
        interview.apply_llm_draft_payload(
            {
                "screen_list": [
                    {
                        "question": "Fees",
                        "fields": [
                            {"field": "custom_one", "label": "Pay", "datatype": "radio"}
                        ],
                    }
                ]
            }
        )
        self.assertEqual(interview.questions[0].field_list[0].field_type, "text")


class TestClassificationKey(unittest.TestCase):
    choices = {"appeal": "Part of an appeal", "other_form": "Not a court form"}

    def test_a_plain_key_is_used_as_is(self):
        self.assertEqual(ig._classification_key(" Appeal ", self.choices), "appeal")

    def test_an_echoed_choice_entry_still_names_its_key(self):
        """classify_text often answers `"{'appeal': '...'}"`; that was thrown away."""
        self.assertEqual(
            ig._classification_key(
                "{'appeal': 'Part of an appeal of a court case'}", self.choices
            ),
            "appeal",
        )
        self.assertEqual(
            ig._classification_key("{'MA': 'Massachusetts'}", {"MA": "Massachusetts"}),
            "MA",
        )

    def test_a_reply_naming_two_keys_is_not_guessed_at(self):
        reply = "'appeal' or 'other_form'"
        self.assertEqual(ig._classification_key(reply, self.choices), reply)


class _FakeRewriteLlms:
    def __init__(self):
        self.calls = 0

    def chat_completion(self, **kwargs):
        self.calls += 1
        texts = json.loads(kwargs["user_message"])
        return {
            "rewrites": [{"original": text, "rewrite": text.upper()} for text in texts]
        }


class TestPlainLanguageRewritesAreBatched(unittest.TestCase):
    def test_all_passages_are_rewritten_in_one_call(self):
        fake = _FakeRewriteLlms()
        with patch.object(ig, "_load_llms_module", return_value=fake):
            rewrites = ig._llm_rewrite_for_plain_language(
                ["Please submit forthwith.", "Herein lies the remedy.", "Hi ${ x }"]
            )
        self.assertEqual(fake.calls, 1)
        self.assertEqual(
            rewrites,
            {
                "Please submit forthwith.": "PLEASE SUBMIT FORTHWITH.",
                "Herein lies the remedy.": "HEREIN LIES THE REMEDY.",
            },
        )

    def test_an_invented_original_is_ignored(self):
        class Invents:
            def chat_completion(self, **kwargs):
                return {"rewrites": [{"original": "Not asked", "rewrite": "x"}]}

        with patch.object(ig, "_load_llms_module", return_value=Invents()):
            self.assertEqual(ig._llm_rewrite_for_plain_language(["Asked"]), {})


class TestTemplateBoundChoicesStayPut(unittest.TestCase):
    setUp = TestLLMRobustness.setUp
    _build_interview_with_custom_field = (
        TestLLMRobustness._build_interview_with_custom_field
    )

    def test_a_model_cannot_replace_the_choices_a_pdf_group_ticks(self):
        """It renamed `name_change_petition` and dropped `other` on a live draft."""
        interview = self._build_interview_with_custom_field()
        field = interview.all_fields[0]
        field.field_type = "multiple choice checkboxes"
        field.option_values = {"box_other": "other", "box_adoption": "adoption"}
        field.choice_options = ["adoption", "other"]
        field.choices = field.choices_string()
        before = field.choices

        interview.apply_llm_field_updates(
            {
                "custom_one": {
                    "label": "Type of proceeding",
                    "datatype": "multiple choice radio",
                    "choices": ['"Change of Name": change_of_name'],
                }
            }
        )
        self.assertEqual(field.label, "Type of proceeding")
        self.assertEqual(field.choices, before)
        self.assertEqual(field.field_type, "multiple choice checkboxes")


class TestEveryStageUsesTheConfiguredModel(unittest.TestCase):
    def test_rewrites_and_navigation_follow_weaver_llm_model(self):
        """These stages used a hard-coded gpt-5-mini whatever was configured."""
        seen = []

        class Recorder:
            def chat_completion(self, **kwargs):
                seen.append(kwargs.get("model"))
                return {}

        config = {"assembly line": {"weaver llm model": "gpt-6-luna"}}
        with patch.object(
            ig, "_load_llms_module", return_value=Recorder()
        ), patch.object(
            ig, "get_config", lambda key, default=None: config.get(key, default)
        ):
            ig._llm_rewrite_for_plain_language(["Please submit forthwith."])
            ig._llm_refine_section_catalog(["Screen one"], [{"id": "a", "label": "A"}])
        self.assertEqual(seen, ["gpt-6-luna", "gpt-6-luna"])

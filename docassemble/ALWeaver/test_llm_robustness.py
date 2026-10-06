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
        ig._next_request_at.clear()
        with patch.object(
            ig.socket,
            "getaddrinfo",
            return_value=[(None, None, None, None, ("93.184.216.34", 0))],
        ):
            with patch.object(ig, "urlopen", return_value=fake_response):
                text = ig._extract_help_page_text("https://example.com/help.pdf")
        self.assertEqual(text, "")

    def _fetch(self, responses):
        """Fetch a help page while `urlopen` answers with `responses` in turn."""
        calls, sleeps = [], []

        def fake_urlopen(request, timeout=None):
            calls.append(request)
            answer = responses.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        ig._next_request_at.clear()
        with (
            patch.object(
                ig.socket,
                "getaddrinfo",
                return_value=[(None, None, None, None, ("93.184.216.34", 0))],
            ),
            patch.object(ig, "urlopen", side_effect=fake_urlopen),
            patch.object(ig.time, "sleep", side_effect=sleeps.append),
        ):
            text = ig._extract_help_page_text("https://example.com/help")
        return text, calls, sleeps

    @staticmethod
    def _too_many_requests(retry_after):
        from email.message import Message
        from urllib.error import HTTPError

        headers = Message()
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        return HTTPError("https://example.com/help", 429, "Too Many", headers, None)

    def test_help_pages_are_fetched_with_the_default_user_agent(self):
        page = _FakeResponse(b"<p>Help</p>", "text/html")
        text, calls, _ = self._fetch([page])
        self.assertEqual(text, "Help")
        # A plain URL: urllib sends its own User-Agent, not a custom one
        self.assertEqual(calls, ["https://example.com/help"])

    def test_a_rate_limited_fetch_waits_as_asked_then_retries_once(self):
        page = _FakeResponse(b"<p>Help</p>", "text/html")
        text, calls, sleeps = self._fetch([self._too_many_requests("3"), page])
        self.assertEqual(text, "Help")
        self.assertEqual(len(calls), 2)
        self.assertIn(3.0, sleeps)

    def test_a_long_retry_after_gives_up_instead_of_waiting(self):
        text, calls, sleeps = self._fetch([self._too_many_requests("3600")])
        self.assertEqual(text, "")
        self.assertEqual(len(calls), 1)
        self.assertNotIn(3600.0, sleeps)

    def test_a_second_refusal_is_not_retried(self):
        refusals = [self._too_many_requests(None), self._too_many_requests(None)]
        text, calls, _ = self._fetch(refusals)
        self.assertEqual(text, "")
        self.assertEqual(len(calls), 2)

    def test_requests_to_one_site_are_spaced_out(self):
        ig._next_request_at.clear()
        sleeps = []
        with (
            patch.object(ig.time, "monotonic", return_value=100.0),
            patch.object(ig.time, "sleep", side_effect=sleeps.append),
        ):
            ig._wait_for_turn("example.com")
            ig._wait_for_turn("example.com")
            ig._wait_for_turn("other.example")
        self.assertEqual(sleeps, [ig._SECONDS_BETWEEN_REQUESTS])

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


class _CannedLlms:
    """Answers every call with `response` and records what it was asked."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _rewrites(pairs):
    return _CannedLlms(
        {"rewrites": [{"original": o, "rewrite": r} for o, r in pairs.items()]}
    )


class TestDraftTextQuality(unittest.TestCase):
    """What the user reads: no filler, no legalese, room for long answers."""

    setUp = TestLLMRobustness.setUp

    def _interview(self, variable="custom_one", source="docx", guess="text"):
        interview = DAInterview()
        field = interview.all_fields.appendObject()
        field.group = DAFieldGroup.CUSTOM
        field.variable = variable
        field.label = "Custom one"
        field.field_type = guess
        field.field_type_guess = guess
        field.final_display_var = variable
        field.source_document_type = source
        field.has_label = True
        interview._llm_context_text = MethodType(
            lambda self, **kwargs: "context", interview
        )
        interview._llm_default_model = MethodType(lambda self: "gpt-6-luna", interview)
        return interview, field

    def test_filler_subquestions_are_dropped(self):
        interview, _ = self._interview()
        interview.questions = DAQuestionList()
        screens = _CannedLlms(
            {
                "screens": [
                    {
                        "question": "Your contact information",
                        "subquestion": "Type your contact information below.",
                        "fields": ["custom_one"],
                    }
                ]
            }
        )
        with patch.object(ig, "_load_llms_module", return_value=screens):
            interview.llm_group_fields(apply=True)
        self.assertEqual(interview.questions[0].subquestion_text, "")

    def test_a_narrative_label_gets_a_text_area(self):
        interview, field = self._interview("appeal_arguments")
        interview.apply_llm_field_updates(
            {"appeal_arguments": {"label": "Legal arguments", "datatype": "text"}}
        )
        self.assertEqual(field.field_type, "area")

    def test_the_model_cannot_shrink_a_text_area(self):
        interview, field = self._interview("appeal_conclusion", guess="area")
        interview.apply_llm_field_updates(
            {"appeal_conclusion": {"label": "Result you want", "datatype": "text"}}
        )
        self.assertEqual(field.field_type, "area")

    def test_a_pdf_box_size_still_decides(self):
        interview, field = self._interview("reason", source="pdf")
        interview.apply_llm_field_updates(
            {"reason": {"label": "Reason for the request", "datatype": "text"}}
        )
        self.assertEqual(field.field_type, "text")

    def _plainer(self, fake, texts):
        with (
            patch.object(ig, "_load_llms_module", return_value=fake),
            patch.object(ig, "_configured_llm_model", return_value="gpt-6-luna"),
        ):
            return ig._plainer_wording(texts)

    def test_formal_words_are_rewritten(self):
        fake = _rewrites({"Date order obtained": "Date you got the order"})
        plainer = self._plainer(fake, ["Date order obtained", "Your email"])
        self.assertEqual(plainer, {"Date order obtained": "Date you got the order"})
        # Only the flagged text went to the model
        self.assertNotIn("Your email", fake.calls[0]["user_message"])

    def test_a_rewrite_that_keeps_the_word_is_rejected(self):
        fake = _rewrites({"Date order obtained": "Date the order was obtained"})
        self.assertEqual(self._plainer(fake, ["Date order obtained"]), {})

    def test_nothing_flagged_means_no_call(self):
        fake = _rewrites({})
        self.assertEqual(self._plainer(fake, ["Your email"]), {})
        self.assertEqual(fake.calls, [])

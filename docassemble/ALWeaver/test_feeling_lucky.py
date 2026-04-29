# do not pre-load
import unittest
from .interview_generator import (
    DAInterview,
)
from docassemble.base.util import DAStaticFile
import docassemble.base.functions
from pathlib import Path


class MockDAStaticFile(DAStaticFile):
    def init(self, *pargs, **kwargs):
        if "full_path" in kwargs:
            full_path = kwargs["full_path"]
            self.full_path = str(full_path)
            if isinstance(full_path, Path):
                kwargs["filename"] = full_path.name
                kwargs["extension"] = full_path.suffix[1:]
            else:
                kwargs["filename"] = self.full_path.split("/")[-1]
                kwargs["extension"] = self.full_path.split(".")[-1]
            if kwargs["extension"] == "pdf":
                kwargs["mimetype"] = "application/pdf"
        super().init(*pargs, **kwargs)

    def path(self):
        return self.full_path


class test_feeling_lucky(unittest.TestCase):
    def test_load_fields(self):
        test_lucky_pdf = (
            Path(__file__).parent / "test/test_petition_to_enforce_sanitary_code.pdf"
        )
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        da_pdf = MockDAStaticFile(
            full_path=str(test_lucky_pdf), extension="pdf", mimetype="application/pdf"
        )

        interview = DAInterview()
        # Skip slow grouping/LLM-dependent code paths; this test focuses on
        # deterministic field extraction and built-in/custom classification.
        interview.auto_assign_attributes_fast(input_file=da_pdf)
        self.assertEqual(len(interview.all_fields), 36)

        builtins = {field.variable for field in interview.all_fields.builtins()}
        custom = {field.variable for field in interview.all_fields.custom()}

        self.assertGreaterEqual(len(builtins), 20)
        self.assertGreaterEqual(len(custom), 10)

        self.assertTrue(
            {
                "court_name",
                "docket_number",
                "plaintiffs",
                "defendants",
                "signature_date",
            }.issubset(builtins)
        )
        self.assertIn("rent_amount", custom)

    def test_lucky_payload_applies_intro_metadata(self):
        interview = DAInterview()
        interview.title = "Old placeholder title"
        interview.short_title = interview.title
        interview.short_filename_with_spaces = interview.title
        interview.short_filename = "old_placeholder_title"
        interview.getting_started = "Before you get started, you need to..."
        interview.apply_llm_draft_payload(
            {
                "llm_draft_title": "Sanitary Code Petition",
                "llm_draft_intro_prompt": "Ask the court to enforce the sanitary code",
                "llm_draft_description": "Helps tenants ask a court to order repairs.",
                "llm_draft_can_i_use_this_form": (
                    "Use this if your landlord has not made repairs."
                ),
                "llm_draft_getting_started": (
                    "Gather your lease, repair requests, and inspection reports."
                ),
                "llm_draft_when_you_are_finished": "File the petition with the court.",
            }
        )

        self.assertEqual(interview.title, "Sanitary Code Petition")
        self.assertEqual(
            interview.intro_prompt, "Ask the court to enforce the sanitary code"
        )
        self.assertEqual(
            interview.getting_started,
            "Gather your lease, repair requests, and inspection reports.",
        )
        self.assertEqual(
            interview.can_I_use_this_form,
            "Use this if your landlord has not made repairs.",
        )
        self.assertEqual(
            interview.when_you_are_finished, "File the petition with the court."
        )

    def test_lucky_payload_applies_typical_role(self):
        """LLM-predicted role should override the heuristic role."""
        interview = DAInterview()
        interview.typical_role = "unknown"  # heuristic fallback
        interview.apply_llm_draft_payload({"llm_draft_typical_role": "plaintiff"})
        self.assertEqual(interview.typical_role, "plaintiff")

    def test_lucky_payload_does_not_override_heuristic_with_unknown_role(self):
        """An LLM 'unknown' prediction should not downgrade a confident heuristic role."""
        interview = DAInterview()
        interview.typical_role = "plaintiff"  # heuristic matched keyword
        interview.apply_llm_draft_payload({"llm_draft_typical_role": "unknown"})
        self.assertEqual(interview.typical_role, "plaintiff")

    def test_lucky_payload_applies_form_type_and_court_related(self):
        """LLM-predicted form_type should update both form_type and court_related."""
        interview = DAInterview()
        interview.form_type = "other"
        interview.court_related = False
        interview.apply_llm_draft_payload(
            {
                "llm_draft_form_type": "starts_case",
                "llm_draft_court_related": True,
            }
        )
        self.assertEqual(interview.form_type, "starts_case")
        self.assertTrue(interview.court_related)

    def test_lucky_payload_letter_form_type_not_court_related(self):
        """A 'letter' form_type predicted by LLM should set court_related to False."""
        interview = DAInterview()
        interview.form_type = "starts_case"
        interview.court_related = True
        interview.apply_llm_draft_payload({"llm_draft_form_type": "letter"})
        self.assertEqual(interview.form_type, "letter")
        self.assertFalse(interview.court_related)

    def test_fast_lucky_intro_fallback_is_form_specific(self):
        test_lucky_pdf = (
            Path(__file__).parent / "test/test_petition_to_enforce_sanitary_code.pdf"
        )
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        da_pdf = MockDAStaticFile(
            full_path=str(test_lucky_pdf), extension="pdf", mimetype="application/pdf"
        )

        interview = DAInterview()
        interview.auto_assign_attributes_fast(input_file=da_pdf)

        self.assertNotEqual(
            interview.getting_started, "Before you get started, you need to..."
        )
        self.assertIn("This interview will help you", interview.getting_started)
        self.assertIn(
            "petition to enforce sanitary code", interview.getting_started.lower()
        )


if __name__ == "__main__":
    unittest.main()

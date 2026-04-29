# do not pre-load
import unittest
from .interview_generator import (
    DAInterview,
    DAFieldList,
    _PersonObjectSpec,
    _PERSON_DEFAULT_PARAMS,
    _normalize_objects,
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

    # ---- objects block tests ----

    def test_guess_people_quantities_single(self):
        """Fields with only index [0] → quantity 'one'."""
        fields = DAFieldList.using(auto_gather=False)
        fields.gathered = True
        for var in ["users[0].name.first", "users[0].name.last", "users[0].signature"]:
            f = type("_F", (), {"final_display_var": var})()
            fields.append(f)
        quantities = fields._guess_people_quantities()
        self.assertEqual(quantities.get("users"), "one")

    def test_guess_people_quantities_multiple(self):
        """Fields with index [1] or higher → quantity 'more'."""
        fields = DAFieldList.using(auto_gather=False)
        fields.gathered = True
        for var in ["children[0].name.first", "children[1].name.last"]:
            f = type("_F", (), {"final_display_var": var})()
            fields.append(f)
        quantities = fields._guess_people_quantities()
        self.assertEqual(quantities.get("children"), "more")

    def test_guess_people_quantities_unknown_person_ignored(self):
        """Unrecognized person prefix like 'docket_numbers[0]' must not appear."""
        fields = DAFieldList.using(auto_gather=False)
        fields.gathered = True
        f = type("_F", (), {"final_display_var": "docket_numbers[0]"})()
        fields.append(f)
        quantities = fields._guess_people_quantities()
        # docket_numbers is not in RESERVED_PERSON_PLURALIZERS_MAP values
        self.assertNotIn("docket_numbers", quantities)

    def test_guess_objects_list_always_includes_users(self):
        """_guess_objects_list() always includes users even on empty field lists."""
        interview = DAInterview()
        interview.all_fields.gathered = True
        objects = interview._guess_objects_list()
        names = [o.name for o in objects]
        self.assertIn("users", names)

    def test_guess_objects_list_applies_default_params(self):
        """When quantity is unknown, defaults matching ql_baseline are applied."""
        interview = DAInterview()
        interview.all_fields.gathered = True
        # Manually insert a children field with no index signal
        f = type("_F", (), {"final_display_var": "children"})()
        f.variable = "children"
        f.source_document_type = "docx"
        interview.all_fields.append(f)
        objects = interview._guess_objects_list()
        by_name = {o.name: o for o in objects}
        self.assertIn("children", by_name)
        # Default for children is ask_number=True (matching ql_baseline.yml)
        self.assertEqual(by_name["children"].params, {"ask_number": True})

    def test_normalize_objects_fills_defaults(self):
        """_normalize_objects applies ql_baseline defaults for empty-param objects."""
        raw = [
            type("_O", (), {"name": "users", "type": "ALPeopleList", "params": {}})(),
            type("_O", (), {"name": "children", "type": "ALPeopleList", "params": {}})(),
        ]
        result = _normalize_objects(raw)
        by_name = {o.name: o for o in result}
        self.assertEqual(by_name["users"].params, _PERSON_DEFAULT_PARAMS["users"])
        self.assertEqual(by_name["children"].params, _PERSON_DEFAULT_PARAMS["children"])

    def test_normalize_objects_respects_explicit_params(self):
        """_normalize_objects should not override explicitly-set params."""
        raw = [
            type(
                "_O",
                (),
                {
                    "name": "users",
                    "type": "ALPeopleList",
                    "params": {"ask_number": True, "target_number": 1},
                },
            )()
        ]
        result = _normalize_objects(raw)
        self.assertEqual(result[0].params, {"ask_number": True, "target_number": 1})

    def test_lucky_mode_objects_block_generated(self):
        """Full lucky-mode flow: generated YAML must contain an objects: block with users."""
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

        from .interview_generator import generate_interview_artifacts, _LocalDAFileAdapter
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_out = _LocalDAFileAdapter(os.path.join(tmpdir, "interview.yml"))
            result = generate_interview_artifacts(
                interview=interview,
                include_download_screen=False,
                create_package_archive=False,
                yaml_output_file=yaml_out,
            )
        yaml_text = result.yaml_text
        self.assertIn("objects:", yaml_text)
        self.assertIn("users:", yaml_text)


if __name__ == "__main__":
    unittest.main()

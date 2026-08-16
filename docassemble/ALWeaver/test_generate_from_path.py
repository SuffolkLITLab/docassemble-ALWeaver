# do not pre-load

import os
import re

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from . import interview_generator as interview_generator_module
from .interview_generator import (
    _LocalDAFileAdapter,
    generate_interview_from_path,
    generate_interview_artifacts,
    _ensure_unique_question_ids,
    _with_progress_markers,
    _guard_indexed_reference,
)


class TestGenerateInterviewFromPath(unittest.TestCase):
    @staticmethod
    def _offline_cluster_screens(fields, tools_token=None):
        """Deterministic fallback grouping for test runs without OpenAI credentials."""
        del tools_token
        unique_fields = list(dict.fromkeys(fields or []))
        if not unique_fields:
            return {}
        grouped = {}
        chunk_size = 4
        for index in range(0, len(unique_fields), chunk_size):
            grouped[f"Screen {index // chunk_size + 1}"] = unique_fields[
                index : index + chunk_size
            ]
        return grouped

    def setUp(self):
        self._cluster_patch = None
        if not os.environ.get("OPENAI_API_KEY"):
            self._cluster_patch = patch.object(
                interview_generator_module.formfyxer,
                "cluster_screens",
                side_effect=self._offline_cluster_screens,
            )
            self._cluster_patch.start()

    def tearDown(self):
        if self._cluster_patch is not None:
            self._cluster_patch.stop()

    def _run_dayamlchecker(self, yaml_path: str) -> None:
        from dayamlchecker.yaml_structure import find_errors_from_string

        errors = find_errors_from_string(
            Path(yaml_path).read_text(encoding="utf-8"), input_file=yaml_path
        )
        details = "\n".join(
            str(getattr(error, "err_str", "") or error).strip() for error in errors
        )
        self.assertFalse(errors, details)

    def test_generate_from_pdf(self):
        pdf_path = (
            Path(__file__).parent / "test/test_petition_to_enforce_sanitary_code.pdf"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(pdf_path),
                output_dir=tmpdir,
                create_package_zip=True,
                include_next_steps=False,
                field_definitions=[
                    {
                        "field": "custom_text",
                        "label": "Custom text",
                        "datatype": "text",
                        "default": "Example",
                    },
                    {
                        "field": "skipped_field",
                        "datatype": "skip",
                        "value": "'skipped'",
                    },
                    {
                        "field": "computed_field",
                        "datatype": "code",
                        "value": "'computed'",
                    },
                ],
            )
            self.assertTrue(result.yaml_path)
            self.assertTrue(os.path.exists(result.yaml_path))
            self._run_dayamlchecker(result.yaml_path)
            self.assertTrue(result.package_zip_path)
            self.assertTrue(os.path.exists(result.package_zip_path))

    def test_ensure_unique_question_ids(self):
        sample = """---
id: Duplicate title
question: |
  First
---
id: Duplicate title
question: |
  Second
---
id: Duplicate title
question: |
  Third
"""
        fixed = _ensure_unique_question_ids(sample)
        self.assertIn("id: Duplicate title\n", fixed)
        self.assertIn("id: Duplicate title 2\n", fixed)
        self.assertIn("id: Duplicate title 3\n", fixed)

    def test_generate_from_docx(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(docx_path),
                output_dir=tmpdir,
                create_package_zip=False,
                include_next_steps=False,
                interview_overrides={
                    "state": "MA",
                    "jurisdiction": "NAM-US-US+MA",
                    "intro_prompt": "A person's interview",
                },
                field_definitions=[
                    {
                        "field": "custom_text",
                        "label": "Custom text",
                        "datatype": "text",
                        "default": "Example",
                    }
                ],
            )
            self.assertTrue(result.yaml_path)
            self.assertTrue(os.path.exists(result.yaml_path))
            # Ensure built-in fields that Weaver references (and/or adds to review screens)
            # are included in the interview order block so they are actually asked.
            yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")
            self.assertIn("id: interview_order_", yaml_text)
            self.assertIn("users.gather()", yaml_text)
            self.assertIn("docket_number", yaml_text)
            # This specific DOCX template includes a reference to users[1].email.
            # Ensure it shows up in the interview order so the generated interview
            # actually collects it, guarded so a lone user isn't forced to add a
            # second one just to get past the order block.
            self.assertIn("if users.number() > 1:\n    users[1].email", yaml_text)
            # Deterministic generation guards.
            self.assertIn("id: edit users", yaml_text)
            self.assertIn("docassemble.MassAccess:massaccess.yml", yaml_text)
            self.assertRegex(
                yaml_text,
                r"(?m)^  LIST_topics:\s*$\n\s+-\s+\".+\"",
            )
            self.assertRegex(yaml_text, r"(?m)^  jurisdiction:\s+\".+\"$")
            self.assertRegex(
                yaml_text,
                r"(?m)^  landing_page_url:\s*>-\s*$\n\s+https?://",
            )
            self.assertRegex(yaml_text, r"(?m)^sections:\n(?:\s+- .+\n)+")
            self.assertRegex(yaml_text, r'(?m)^  nav\.set_section\("[-a-z_]+"\)$')
            self.assertFalse(yaml_text.lstrip().startswith("---\n\n---"))
            self.assertIn(
                "template: interview_short_title\ncontent: |\n"
                "  A person's interview",
                yaml_text,
            )
            self.assertNotIn("interview_short_title =", yaml_text)
            self.assertIn("label=word('Edit answers')", yaml_text)
            self.assertIn(
                "template: test_docx_no_pdf_field_names_attachment.title\n"
                "content: |\n"
                "  Test docx no pdf field names",
                yaml_text,
            )
            self.assertIn(
                "template: al_user_bundle.title\n"
                "content: |\n"
                "  All forms to download for your records",
                yaml_text,
            )
            self.assertIn(
                "template: al_court_bundle.title\n"
                "content: |\n"
                "  All forms to deliver to court",
                yaml_text,
            )
            self.assertNotRegex(
                yaml_text,
                r"ALDocument(?:Bundle)?\.using\([^\n]*\btitle=",
            )
            self._run_dayamlchecker(result.yaml_path)

    def test_generate_from_docx_uses_exact_name_for_temp_paths(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        temp_input_path = None
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_handle:
            temp_handle.write(docx_path.read_bytes())
            temp_input_path = temp_handle.name
        try:
            with tempfile.TemporaryDirectory() as outdir:
                result = generate_interview_from_path(
                    temp_input_path,
                    output_dir=outdir,
                    exact_name=docx_path.name,
                    create_package_zip=False,
                    include_next_steps=False,
                )
                self.assertEqual(
                    os.path.basename(result.yaml_path),
                    "test_docx_no_pdf_field_names.yml",
                )
                yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")
                self.assertIn("test_docx_no_pdf_field_names_attachment", yaml_text)
                self.assertNotIn(Path(temp_input_path).stem, yaml_text)
        finally:
            if temp_input_path and os.path.exists(temp_input_path):
                os.remove(temp_input_path)

    def test_deterministic_package_contains_expected_files_including_next_steps(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(docx_path),
                output_dir=tmpdir,
                create_package_zip=True,
                include_next_steps=True,
                interview_overrides={
                    "state": "MA",
                    "jurisdiction": "NAM-US-US+MA",
                },
            )
            self.assertTrue(result.package_zip_path)
            self.assertTrue(os.path.exists(result.package_zip_path))
            with zipfile.ZipFile(result.package_zip_path) as package_zip:
                names = package_zip.namelist()

            self.assertTrue(
                any(
                    name.endswith("/data/questions/test_docx_no_pdf_field_names.yml")
                    for name in names
                )
            )
            self.assertTrue(
                any(
                    name.endswith("/data/templates/test_docx_no_pdf_field_names.docx")
                    for name in names
                )
            )
            self.assertTrue(
                any(
                    name.endswith(
                        "/data/templates/test_docx_no_pdf_field_names_next_steps.docx"
                    )
                    for name in names
                )
            )

    def test_generate_interview_artifacts_assigns_next_steps_when_missing(self):
        class MinimalInterview:
            def __init__(self):
                self.interview_label = "my_interview"
                self.package_title = "MyInterview"
                self.include_next_steps = True
                self.uploaded_templates = ["uploaded-template"]
                self.author = ""

            def package_info(self):
                return {}

            def draft_screen_order(self):
                return []

        interview = MinimalInterview()

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_output = _LocalDAFileAdapter(os.path.join(tmpdir, "my_interview.yml"))
            package_output = _LocalDAFileAdapter(os.path.join(tmpdir, "package.zip"))

            def _fake_assign(interview_obj):
                interview_obj.instructions = "generated-next-steps"

            with (
                patch.object(
                    interview_generator_module,
                    "_render_interview_yaml",
                    return_value="metadata:\n  title: test\n",
                ),
                patch.object(
                    interview_generator_module,
                    "_assign_next_steps_template",
                    side_effect=_fake_assign,
                ) as assign_patch,
                patch.object(
                    interview_generator_module,
                    "create_package_zip",
                    return_value=package_output,
                ) as package_patch,
            ):
                generate_interview_artifacts(
                    interview=interview,
                    include_download_screen=True,
                    create_package_archive=True,
                    yaml_output_file=yaml_output,
                    package_output_file=package_output,
                )

            assign_patch.assert_called_once_with(interview)
            package_patch.assert_called_once()
            folders_and_files = package_patch.call_args.args[3]
            self.assertEqual(
                folders_and_files["templates"],
                ["generated-next-steps", "uploaded-template"],
            )

    def test_progress_markers_climb_across_the_whole_interview(self):
        """Progress used to stall around 66% because the step size was too small."""
        entries = [("screen_%d" % index, True) for index in range(18)]
        entries.insert(0, ('nav.set_section("people")', False))
        lines = _with_progress_markers(entries)

        values = [
            int(line[len("set_progress(") : -1])
            for line in lines
            if line.startswith("set_progress(")
        ]
        self.assertEqual(values, sorted(set(values)), "must climb, never repeat")
        self.assertGreaterEqual(values[-1], 70)
        self.assertLessEqual(values[-1], 90)
        # A marker always introduces a screen; it never trails the block.
        self.assertFalse(lines[-1].startswith("set_progress("))

        # Interviews too short to have meaningful steps get no markers at all.
        self.assertEqual(
            [line for line in _with_progress_markers([("a", True), ("b", True)])],
            ["a", "b"],
        )

    def test_review_screen_follows_the_order_the_questions_are_asked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(
                    Path(__file__).parent
                    / "test/test_petition_to_enforce_sanitary_code.pdf"
                ),
                output_dir=tmpdir,
                create_package_zip=False,
                include_next_steps=False,
            )
            yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")

        asked = re.findall(r'(?m)^  - "[^"]*": (\w+)$', yaml_text)
        self.assertGreater(len(asked), 5, "expected several question screen fields")
        reviewed = re.findall(r"(?m)^  - Edit: (\w+)$", yaml_text)
        # Every reviewed field that is asked on a screen must keep its position.
        self.assertEqual(
            [name for name in reviewed if name in asked],
            [name for name in asked if name in reviewed],
        )

        # Signatures and the signature date belong to the signature flow, not to
        # a review screen "Edit" link -- but the date is still gathered.
        self.assertNotIn("- Edit: signature_date", yaml_text)
        self.assertIn("\n  signature_date\n", yaml_text)

    def test_generated_yaml_has_no_leading_or_trailing_blank_lines(self):
        """Mako's control-flow lines used to leave blank lines wrapping the file."""
        for source in (
            "test/test_docx_no_pdf_field_names.docx",
            "test/test_petition_to_enforce_sanitary_code.pdf",
        ):
            with self.subTest(source=source):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = generate_interview_from_path(
                        str(Path(__file__).parent / source),
                        output_dir=tmpdir,
                        create_package_zip=False,
                        include_next_steps=False,
                    )
                    yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")
                self.assertTrue(yaml_text.startswith("---\n"), repr(yaml_text[:40]))
                self.assertFalse(yaml_text.endswith("\n\n"), repr(yaml_text[-40:]))
                self.assertTrue(yaml_text.endswith("\n"))
                # No runs of blank lines anywhere in the file either.
                self.assertNotIn("\n\n\n", yaml_text)

    def test_attachment_comment_sits_in_the_block_it_describes(self):
        """The `i` placeholder comment documents the attachment, not the bundle title."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"),
                output_dir=tmpdir,
                create_package_zip=False,
                include_next_steps=False,
            )
            yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")

        marker = "# Each attachment defines a key in an ALDocument."
        self.assertEqual(yaml_text.count(marker), 1)
        comment_start = yaml_text.index(marker)
        # The nearest `---` above the comment must be the one that opens the
        # attachment block, and nothing but comment lines may sit between them.
        separator = yaml_text.rindex("\n---\n", 0, comment_start)
        between = yaml_text[separator + len("\n---\n") : comment_start]
        self.assertEqual(between.strip(), "")
        after = yaml_text[comment_start:].split("\n")
        self.assertEqual(
            [line for line in after[:5] if not line.startswith("#")][0],
            "attachment:",
        )

    def test_every_gathered_object_has_an_objects_block(self):
        """Anything the interview treats as an object needs a declaration to match."""
        # AssemblyLine declares and configures these itself; re-declaring them
        # would clobber its own setup.
        al_provided = {
            "users",
            "other_parties",
            "children",
            "courts",
            "trial_court",
            "plaintiffs",
            "defendants",
            "petitioners",
            "respondents",
            "witnesses",
            "docket_numbers",
            "case_numbers",
            "al_user_bundle",
            "al_court_bundle",
            "al_recipient_bundle",
            "nav",
        }
        for source in (
            "test/test_petition_to_enforce_sanitary_code.pdf",
            "test/test_docx_no_pdf_field_names.docx",
            "test/unmap_suffixes.docx",
        ):
            with self.subTest(source=source):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = generate_interview_from_path(
                        str(Path(__file__).parent / source),
                        output_dir=tmpdir,
                        create_package_zip=False,
                        include_next_steps=False,
                    )
                    yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")

                declared = set(re.findall(r"(?m)^  - (\w+):", yaml_text))
                order_block = yaml_text.split("id: interview_order_", 1)[1].split(
                    "\n---\n", 1
                )[0]
                referenced = set(
                    re.findall(
                        r"(?m)^  (\w+)(?:\.gather\(\)|\[\d+\]|\.\w)", order_block
                    )
                )
                undeclared = referenced - declared - al_provided
                self.assertEqual(undeclared, set(), f"undeclared in {source}")

        # The sanitary-code PDF is the concrete case that used to slip through:
        # `my_user` and `some_identifier_mail` were gathered but never declared.
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(
                    Path(__file__).parent
                    / "test/test_petition_to_enforce_sanitary_code.pdf"
                ),
                output_dir=tmpdir,
                create_package_zip=False,
                include_next_steps=False,
            )
            yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")
        self.assertIn("  - my_user: ALPeopleList", yaml_text)
        self.assertIn("  - some_identifier_mail: ALPeopleList", yaml_text)
        # `inspector_name` is a plain text field, so there is no `inspector` list.
        self.assertNotIn("  - inspector:", yaml_text)

    def test_custom_frontend_sections_respected(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(docx_path),
                output_dir=tmpdir,
                create_package_zip=False,
                include_next_steps=False,
                interview_overrides={
                    "enable_navigation": True,
                    "sections": [
                        {"key": "intro", "value": "Start Here"},
                        {"key": "details", "value": "Your Details"},
                        {"key": "finish", "value": "Finish Up"},
                    ],
                },
            )
            yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")
            self.assertIn("  - intro: Start Here", yaml_text)
            self.assertIn("  - details: Your Details", yaml_text)
            self.assertIn("  - finish: Finish Up", yaml_text)

    def test_navigation_can_be_disabled(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(docx_path),
                output_dir=tmpdir,
                create_package_zip=False,
                include_next_steps=False,
                interview_overrides={
                    "enable_navigation": False,
                },
            )
            yaml_text = Path(result.yaml_path).read_text(encoding="utf-8")
            self.assertNotIn('nav.set_section("', yaml_text)


if __name__ == "__main__":
    unittest.main()


class TestGuardIndexedReference(unittest.TestCase):
    KNOWN_LISTS = {"users", "other_parties"}

    def test_second_item_gets_a_guard(self):
        self.assertEqual(
            _guard_indexed_reference("users[1].email", self.KNOWN_LISTS),
            "if users.number() > 1:\n  users[1].email",
        )
        self.assertEqual(
            _guard_indexed_reference("users[2].address.address", self.KNOWN_LISTS),
            "if users.number() > 2:\n  users[2].address.address",
        )

    def test_first_item_is_left_alone(self):
        for line in ("users[0].email", "users.gather()", "docket_number"):
            with self.subTest(line=line):
                self.assertEqual(_guard_indexed_reference(line, self.KNOWN_LISTS), line)

    def test_unknown_lists_are_left_alone(self):
        """We can only call `.number()` on something we know is a list."""
        self.assertEqual(
            _guard_indexed_reference("previous_names[1].first", self.KNOWN_LISTS),
            "previous_names[1].first",
        )

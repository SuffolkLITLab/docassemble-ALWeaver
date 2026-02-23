import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from .interview_generator import (
    _LocalDAFileAdapter,
    generate_interview_from_path,
    generate_interview_artifacts,
    _ensure_unique_question_ids,
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
            self._cluster_patch = patch(
                "docassemble.ALWeaver.interview_generator.formfyxer.cluster_screens",
                side_effect=self._offline_cluster_screens,
            )
            self._cluster_patch.start()

    def tearDown(self):
        if self._cluster_patch is not None:
            self._cluster_patch.stop()

    def _run_dayamlchecker(self, yaml_path: str) -> None:
        if importlib.util.find_spec("dayamlchecker") is None:
            self.fail("dayamlchecker is not installed")
        subprocess.run(
            [sys.executable, "-m", "dayamlchecker", yaml_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

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
            # actually collects it.
            self.assertIn("users[1].email", yaml_text)
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
            self._run_dayamlchecker(result.yaml_path)

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
                any(name.endswith("/data/questions/test_docx_no_pdf_field_names.yml") for name in names)
            )
            self.assertTrue(
                any(name.endswith("/data/templates/test_docx_no_pdf_field_names.docx") for name in names)
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

        interview = MinimalInterview()

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_output = _LocalDAFileAdapter(os.path.join(tmpdir, "my_interview.yml"))
            package_output = _LocalDAFileAdapter(os.path.join(tmpdir, "package.zip"))

            def _fake_assign(interview_obj):
                interview_obj.instructions = "generated-next-steps"

            with (
                patch(
                    "docassemble.ALWeaver.interview_generator._render_interview_yaml",
                    return_value="metadata:\n  title: test\n",
                ),
                patch(
                    "docassemble.ALWeaver.interview_generator._assign_next_steps_template",
                    side_effect=_fake_assign,
                ) as assign_patch,
                patch(
                    "docassemble.ALWeaver.interview_generator.create_package_zip",
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

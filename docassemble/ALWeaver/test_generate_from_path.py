import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .interview_generator import generate_interview_from_path


class TestGenerateInterviewFromPath(unittest.TestCase):
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
            Path(__file__).parent
            / "test/test_petition_to_enforce_sanitary_code.pdf"
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
                    {"field": "skipped_field", "datatype": "skip", "value": "'skipped'"},
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

    def test_generate_from_docx(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(docx_path),
                output_dir=tmpdir,
                create_package_zip=False,
                include_next_steps=False,
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
            self._run_dayamlchecker(result.yaml_path)


if __name__ == "__main__":
    unittest.main()

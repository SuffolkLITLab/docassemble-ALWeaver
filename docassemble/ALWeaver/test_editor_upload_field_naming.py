# do not pre-load

"""The graphical editor's upload path must produce AssemblyLine variable names.

`api_editor.py` builds one exact set of generation options when an author drops a
PDF on the new-project screen.  These tests run `generate_interview_from_path()`
with that same set, against a template whose fields already carry canonical AL
labels, and assert the mapped names come out the other side.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import interview_generator as interview_generator_module
from .interview_generator import generate_interview_from_path

PDF_PATH = Path(__file__).parent / "test/test_petition_to_enforce_sanitary_code.pdf"

# The options `editor_api_new_project()` sends for a form project with every
# switch left at its default (api_editor.py, `generation_options`).
EDITOR_UPLOAD_OPTIONS = {
    "create_package_zip": False,
    "include_next_steps": True,
    "include_download_screen": True,
    "copy_baseline_questions": True,
    "use_llm_assist": False,
    "normalize_field_names": False,
    "interview_overrides": {"enable_navigation": True, "next_steps_enabled": True},
}

# PDF label -> the AssemblyLine variable it has to become.
EXPECTED_MAPPINGS = {
    "user_name_first": "users[0].name.first",
    # `_name_full` maps to the object itself, which renders as the full name.
    "user25_name_full": "users[24]",
    "other_party37_address_zip": "other_parties[36].address.zip",
    "plaintiff1_address_street": "plaintiffs[0].address.address",
    "plaintiff1_address_city": "plaintiffs[0].address.city",
    "plaintiff1_address_state": "plaintiffs[0].address.state",
    "plaintiff1_address_zip": "plaintiffs[0].address.zip",
    "plaintiff1_phone": "plaintiffs[0].phone_number",
    "plaintiff2_email": "plaintiffs[1].email",
    "plaintiff2_signature": "plaintiffs[1].signature",
    "court1_address_county": "courts[0].address.county",
}


class TestEditorUploadFieldNaming(unittest.TestCase):
    @staticmethod
    def _offline_cluster_screens(fields, tools_token=None):
        """Deterministic fallback grouping for test runs without OpenAI credentials."""
        del tools_token
        unique_fields = list(dict.fromkeys(fields or []))
        grouped = {}
        for index in range(0, len(unique_fields), 4):
            grouped[f"Screen {index // 4 + 1}"] = unique_fields[index : index + 4]
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

    def _generate(self, **overrides):
        options = dict(EDITOR_UPLOAD_OPTIONS)
        options.update(overrides)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_interview_from_path(
                str(PDF_PATH),
                output_dir=tmpdir,
                exact_name=PDF_PATH.name,
                **options,
            )
            self.assertTrue(result.yaml_path)
            return Path(result.yaml_path).read_text(encoding="utf-8")

    def test_al_labels_become_al_variables(self):
        yaml_text = self._generate()
        missing = [
            f"{raw} -> {mapped}"
            for raw, mapped in EXPECTED_MAPPINGS.items()
            if mapped not in yaml_text
        ]
        self.assertFalse(
            missing,
            "The editor's upload options did not map these AssemblyLine PDF labels:\n"
            + "\n".join(missing),
        )

    def test_raw_al_labels_are_not_left_as_variables(self):
        yaml_text = self._generate()
        leaked = [
            raw
            for raw in EXPECTED_MAPPINGS
            if f"field: {raw}" in yaml_text or f"\n  - {raw}:" in yaml_text
        ]
        self.assertFalse(
            leaked,
            "These raw PDF labels were used as interview variables: "
            + ", ".join(leaked),
        )


if __name__ == "__main__":
    unittest.main()

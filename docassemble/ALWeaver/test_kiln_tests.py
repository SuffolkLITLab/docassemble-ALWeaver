import unittest
from unittest.mock import patch

from . import kiln_tests


class TestKilnTests(unittest.TestCase):
    def test_default_feature_filename_is_flat_and_descriptive(self):
        self.assertEqual(
            kiln_tests.default_feature_filename("Petition for relief.yml"),
            "Petition_for_relief.feature",
        )

    def test_create_requests_screen_definitions_from_dashboard(self):
        seen = {}

        class FakeOptions:
            def __init__(self, **kwargs):
                seen["options"] = kwargs

        def fake_story(yaml_text, **kwargs):
            seen["yaml"] = yaml_text
            seen["story_kwargs"] = kwargs
            return {"feature_text": "Feature: test"}

        with patch.object(
            kiln_tests,
            "_dashboard_story_api",
            return_value=(FakeOptions, lambda _yaml: "download", fake_story, object()),
        ):
            result = kiln_tests.create_kiln_feature(
                "question: Hello", interview_filename="main.yml"
            )

        self.assertEqual(result["feature_text"], "Feature: test")
        self.assertTrue(seen["options"]["include_screen_definitions"])
        self.assertEqual(seen["options"]["question_id"], "download")
        self.assertEqual(seen["story_kwargs"]["source_path"], None)

    def test_default_workflow_uses_standard_alkiln_action_and_secrets(self):
        self.assertIn("SuffolkLITLab/ALKiln@v5", kiln_tests.DEFAULT_ALKILN_WORKFLOW)
        self.assertIn("secrets.SERVER_URL", kiln_tests.DEFAULT_ALKILN_WORKFLOW)
        self.assertIn(
            "secrets.DOCASSEMBLE_DEVELOPER_API_KEY",
            kiln_tests.DEFAULT_ALKILN_WORKFLOW,
        )

import unittest
from unittest.mock import patch

from . import kiln_tests


class TestKilnTests(unittest.TestCase):
    def test_default_feature_filename_is_the_reserved_managed_test(self):
        self.assertEqual(
            kiln_tests.default_feature_filename("Petition for relief.yml"),
            "weaver_it_runs.feature",
        )

    def test_create_omits_machine_screen_comments(self):
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
        self.assertNotIn("include_screen_definitions", seen["options"])
        self.assertEqual(seen["options"]["question_id"], "download")
        self.assertEqual(seen["story_kwargs"]["source_path"], None)

    def test_json_export_uses_dashboard_story_generator(self):
        seen = {}

        class FakeOptions:
            def __init__(self, **kwargs):
                seen["options"] = kwargs

        def fake_load(text):
            seen["json"] = text
            return {"variables": {"answer": 42}}

        def fake_story(data, **kwargs):
            seen["data"] = data
            seen["story_kwargs"] = kwargs
            return {"feature_text": "Feature: recorded"}

        import sys
        from types import SimpleNamespace

        fake_module = SimpleNamespace(
            StoryOptions=FakeOptions,
            load_docassemble_json_text=fake_load,
            story_from_docassemble_json=fake_story,
        )
        with patch.dict(
            sys.modules,
            {"docassemble.ALDashboard.alkiln_story": fake_module},
        ):
            result = kiln_tests.create_kiln_feature_from_json(
                '{"variables":{"answer":42}}',
                interview_filename="main.yml",
                question_id="done",
            )

        self.assertEqual(result["feature_text"], "Feature: recorded")
        self.assertEqual(seen["options"]["question_id"], "done")
        self.assertEqual(seen["options"]["yaml_file_name"], "main.yml")

    def test_default_workflow_uses_standard_alkiln_action_and_secrets(self):
        self.assertIn("SuffolkLITLab/ALKiln@v5", kiln_tests.DEFAULT_ALKILN_WORKFLOW)
        self.assertIn("secrets.SERVER_URL", kiln_tests.DEFAULT_ALKILN_WORKFLOW)
        self.assertIn(
            "secrets.DOCASSEMBLE_DEVELOPER_API_KEY",
            kiln_tests.DEFAULT_ALKILN_WORKFLOW,
        )

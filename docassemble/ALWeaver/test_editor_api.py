import unittest
from unittest.mock import patch

from . import api_editor


class TestEditorApiFileCreation(unittest.TestCase):
    def test_normalize_new_filename_adds_yaml_extension(self):
        self.assertEqual(api_editor._normalize_new_filename("draft"), "draft.yml")
        self.assertEqual(api_editor._normalize_new_filename("draft.yaml"), "draft.yaml")

    def test_new_file_route_creates_default_yaml(self):
        with patch.object(api_editor, "_editor_auth_check", return_value=True), patch.object(
            api_editor, "_current_user_id", return_value=7
        ), patch.object(api_editor, "playground_list_yaml_files", return_value=[]), patch.object(
            api_editor, "playground_write_yaml"
        ) as mock_write:
            with api_editor.app.test_request_context(
                "/al/editor/api/file/new",
                method="POST",
                json={"project": "Case1", "filename": "draft"},
            ):
                response = api_editor.editor_api_new_file()

        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["filename"], "draft.yml")
        self.assertEqual(payload["data"]["project"], "Case1")
        mock_write.assert_called_once()
        call_args = mock_write.call_args.args
        self.assertEqual(call_args[0], 7)
        self.assertEqual(call_args[1], "Case1")
        self.assertEqual(call_args[2], "draft.yml")
        self.assertIn("metadata:\n", call_args[3])
        self.assertIn("question: New question", call_args[3])


if __name__ == "__main__":
    unittest.main()

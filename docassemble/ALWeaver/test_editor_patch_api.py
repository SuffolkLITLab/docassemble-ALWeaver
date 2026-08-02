import unittest
from unittest.mock import patch
from pathlib import Path

from .test_editor_api import api_editor


class TestEditorPatchApi(unittest.TestCase):
    def test_patch_route_is_not_csrf_exempt_or_cross_origin(self):
        source = Path(api_editor.__file__).read_text()
        route_start = source.index(
            '@app.route(f"{EDITOR_BASE_PATH}/api/file/patch", methods=["POST"])'
        )
        function_start = source.index("def editor_api_patch_file", route_start)
        decorators = source[route_start:function_start]
        self.assertNotIn("@csrf.exempt", decorators)
        self.assertNotIn("@cross_origin", decorators)

    def _request(self, payload, source):
        write_patch = patch.object(api_editor, "playground_write_yaml")
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_patch_model_enabled", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=17),
            patch.object(api_editor, "playground_read_yaml", return_value=source),
            write_patch as mock_write,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/file/patch", method="POST", json=payload
            ):
                response = api_editor.editor_api_patch_file()
        return response, mock_write

    def test_patch_changes_only_the_requested_range(self):
        source = (
            "# header\n"
            "metadata:\n"
            "  title: 'Old title' # exact comment\n"
            "---\n"
            "id: intro\n"
            "question: |\n"
            "  Keep ${ expression } exactly.\n"
        )
        start = source.index("Old title")
        response, mock_write = self._request(
            {
                "project": "default",
                "filename": "main.yml",
                "expected_revision": "test-revision",
                "operations": [
                    {
                        "type": "replace-range",
                        "start": start,
                        "end": start + len("Old title"),
                        "text": "New title",
                    }
                ],
            },
            source,
        )

        expected = source.replace("Old title", "New title")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["raw_yaml"], expected)
        self.assertIn("-  title: 'Old title' # exact comment", payload["diff"])
        self.assertIn("+  title: 'New title' # exact comment", payload["diff"])
        mock_write.assert_called_once_with(17, "default", "main.yml", expected)

    def test_stale_revision_returns_three_way_conflict_without_writing(self):
        source = "id: current\nquestion: Current\n"
        response, mock_write = self._request(
            {
                "project": "default",
                "filename": "main.yml",
                "expected_revision": "stale-revision",
                "base_raw_yaml": "id: base\nquestion: Base\n",
                "operations": [
                    {"type": "replace-range", "start": 0, "end": 0, "text": "# local\n"}
                ],
            },
            source,
        )

        self.assertEqual(response.status_code, 409)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "revision_conflict")
        self.assertEqual(error["current_raw_yaml"], source)
        self.assertEqual(error["base_raw_yaml"], "id: base\nquestion: Base\n")
        mock_write.assert_not_called()

    def test_all_operations_fail_when_one_range_overlaps(self):
        source = "id: intro\nquestion: Hello\n"
        response, mock_write = self._request(
            {
                "project": "default",
                "filename": "main.yml",
                "expected_revision": "test-revision",
                "operations": [
                    {"type": "replace-range", "start": 0, "end": 4, "text": "id"},
                    {"type": "replace-range", "start": 2, "end": 6, "text": "bad"},
                ],
            },
            source,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_patch_request")
        mock_write.assert_not_called()

    def test_structurally_invalid_result_is_not_written(self):
        source = "id: intro\nquestion: Hello\n"
        start = source.index("Hello")
        response, mock_write = self._request(
            {
                "project": "default",
                "filename": "main.yml",
                "expected_revision": "test-revision",
                "operations": [
                    {
                        "type": "replace-range",
                        "start": start,
                        "end": start + len("Hello"),
                        "text": "[unterminated",
                    }
                ],
            },
            source,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_patched_source")
        mock_write.assert_not_called()

    def test_patch_endpoint_is_hidden_when_feature_is_disabled(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_patch_model_enabled", return_value=False),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/file/patch", method="POST", json={}
            ):
                response = api_editor.editor_api_patch_file()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "patch_model_disabled")


if __name__ == "__main__":
    unittest.main()

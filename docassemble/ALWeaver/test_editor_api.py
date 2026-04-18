from io import BytesIO
from pathlib import Path
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

    def test_new_project_route_uploads_docx_without_packaging(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        generated_yaml = "metadata:\n  title: Demand Letter\n---\n"

        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "get_list_of_projects", return_value=[]),
            patch.object(api_editor, "next_available_project_name", return_value="DocxSmoke"),
            patch.object(api_editor, "create_project") as mock_create_project,
            patch.object(api_editor, "generate_interview_from_bytes") as mock_generate,
            patch.object(api_editor, "playground_write_yaml") as mock_write,
            patch.object(api_editor, "_copy_files_to_section") as mock_copy_files,
        ):
            mock_generate.return_value = {
                "input_filename": docx_path.name,
                "yaml_text": generated_yaml,
                "yaml_filename": "generated.yml",
            }
            with api_editor.app.test_client() as client:
                with docx_path.open("rb") as docx_handle:
                    response = client.post(
                        "/al/editor/api/new-project",
                        data={
                            "project_name": "DocxSmoke",
                            "generation_notes": "Demand Letter",
                            "files": (
                                BytesIO(docx_handle.read()),
                                docx_path.name,
                            ),
                        },
                        content_type="multipart/form-data",
                    )

        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["project"], "DocxSmoke")
        self.assertEqual(payload["data"]["generated_from"], docx_path.name)
        self.assertEqual(payload["data"]["uploaded_count"], 1)
        mock_create_project.assert_called_once_with(7, "DocxSmoke")
        mock_generate.assert_called_once()
        generate_kwargs = mock_generate.call_args.kwargs
        self.assertEqual(generate_kwargs["generation_options"]["title"], "Demand Letter")
        self.assertFalse(generate_kwargs["generation_options"]["create_package_zip"])
        self.assertFalse(generate_kwargs["generation_options"]["include_next_steps"])
        self.assertTrue(generate_kwargs["include_yaml_text"])
        mock_write.assert_called_once_with(7, "DocxSmoke", "interview.yml", generated_yaml)
        mock_copy_files.assert_called_once()


if __name__ == "__main__":
    unittest.main()

from io import BytesIO
from contextlib import nullcontext
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

    def test_new_project_route_uploads_docx_queues_background_job(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"

        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "get_list_of_projects", return_value=[]),
            patch.object(api_editor, "next_available_project_name", return_value="DocxSmoke"),
            patch.object(api_editor, "create_project") as mock_create_project,
            patch.object(api_editor, "_start_new_project_upload_job") as mock_start_job,
        ):
            mock_start_job.return_value = {
                "job_id": "job-123",
                "job_url": "/al/editor/api/new-project/jobs/job-123",
                "state": {
                    "status": "queued",
                    "project": "DocxSmoke",
                    "generated_from": docx_path.name,
                    "uploaded_count": 1,
                },
            }
            with api_editor.app.test_client() as client:
                with docx_path.open("rb") as docx_handle:
                    response = client.post(
                        "/al/editor/api/new-project",
                        data={
                            "project_name": "DocxSmoke",
                            "generation_notes": "Demand Letter",
                            "help_source_text": "Demand letter context",
                            "help_page_url": "https://example.com/help",
                            "help_page_title": "Help page title",
                            "use_llm_assist": "true",
                            "files": (
                                BytesIO(docx_handle.read()),
                                docx_path.name,
                            ),
                        },
                        content_type="multipart/form-data",
                    )

        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["job_id"], "job-123")
        self.assertEqual(payload["job_url"], "/al/editor/api/new-project/jobs/job-123")
        self.assertEqual(payload["data"]["project"], "DocxSmoke")
        self.assertEqual(payload["data"]["generated_from"], docx_path.name)
        self.assertEqual(payload["data"]["uploaded_count"], 1)
        mock_create_project.assert_called_once_with(7, "DocxSmoke")
        mock_start_job.assert_called_once()
        start_kwargs = mock_start_job.call_args.kwargs
        self.assertEqual(start_kwargs["uid"], 7)
        self.assertEqual(start_kwargs["request_id"], payload["request_id"])
        self.assertEqual(start_kwargs["project_name"], "DocxSmoke")
        self.assertEqual(start_kwargs["generation_options"]["exact_name"], docx_path.name)
        self.assertEqual(start_kwargs["generation_options"]["help_source_text"], "Demand letter context")
        self.assertEqual(start_kwargs["generation_options"]["help_page_url"], "https://example.com/help")
        self.assertEqual(start_kwargs["generation_options"]["help_page_title"], "Help page title")
        self.assertTrue(start_kwargs["generation_options"]["use_llm_assist"])
        self.assertFalse(start_kwargs["generation_options"]["create_package_zip"])
        self.assertFalse(start_kwargs["generation_options"]["include_next_steps"])
        self.assertEqual(len(start_kwargs["uploaded_files"]), 1)
        self.assertEqual(start_kwargs["uploaded_files"][0]["filename"], docx_path.name)
        self.assertIsInstance(start_kwargs["uploaded_files"][0]["content_bytes"], bytes)
        self.assertEqual(start_kwargs["uploaded_files"][0]["mimetype"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    def test_complete_new_project_upload_job_writes_yaml(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        uploaded_files = [
            {
                "filename": docx_path.name,
                "content_bytes": docx_path.read_bytes(),
                "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        ]
        generated_yaml = "metadata:\n  title: Demand Letter\n---\n"

        with (
            patch.object(api_editor, "bg_context", return_value=nullcontext()),
            patch.object(api_editor, "_update_new_project_job_state") as mock_update,
            patch.object(api_editor, "generate_interview_from_bytes") as mock_generate,
            patch.object(api_editor, "playground_write_yaml") as mock_write,
            patch.object(api_editor, "_copy_files_to_section") as mock_copy_files,
        ):
            mock_generate.return_value = {
                "input_filename": docx_path.name,
                "yaml_text": generated_yaml,
                "yaml_filename": "generated.yml",
            }
            result = api_editor._complete_new_project_upload_job(
                job_id="job-1",
                uid=7,
                project_name="DocxSmoke",
                request_id="req-1",
                uploaded_files=uploaded_files,
                generation_options={
                    "create_package_zip": False,
                    "include_next_steps": False,
                    "exact_name": docx_path.name,
                    "help_source_text": "Demand letter context",
                    "help_page_url": "https://example.com/help",
                    "help_page_title": "Help page title",
                    "use_llm_assist": True,
                },
                debug_requested=False,
            )

        self.assertEqual(result["project"], "DocxSmoke")
        self.assertEqual(result["generated_from"], docx_path.name)
        self.assertEqual(result["uploaded_count"], 1)
        mock_generate.assert_called_once()
        generate_kwargs = mock_generate.call_args.kwargs
        self.assertEqual(generate_kwargs["generation_options"]["exact_name"], docx_path.name)
        self.assertEqual(generate_kwargs["generation_options"]["help_source_text"], "Demand letter context")
        self.assertEqual(generate_kwargs["generation_options"]["help_page_url"], "https://example.com/help")
        self.assertEqual(generate_kwargs["generation_options"]["help_page_title"], "Help page title")
        self.assertTrue(generate_kwargs["generation_options"]["use_llm_assist"])
        self.assertFalse(generate_kwargs["generation_options"]["create_package_zip"])
        self.assertFalse(generate_kwargs["generation_options"]["include_next_steps"])
        self.assertTrue(generate_kwargs["include_yaml_text"])
        mock_write.assert_called_once_with(7, "DocxSmoke", "interview.yml", generated_yaml)
        mock_copy_files.assert_called_once()
        self.assertTrue(mock_update.called)

    def test_new_project_job_status_route_returns_state(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(
                api_editor,
                "_load_new_project_job_state",
                return_value={
                    "status": "running",
                    "stage": "generate_interview",
                    "project": "DocxSmoke",
                    "message": "Generating interview from the uploaded document.",
                },
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/new-project/jobs/job-1", method="GET"
            ):
                response = api_editor.editor_api_new_project_job("job-1")

        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["job_id"], "job-1")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["data"]["stage"], "generate_interview")


if __name__ == "__main__":
    unittest.main()

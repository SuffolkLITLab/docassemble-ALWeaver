from io import BytesIO
from contextlib import nullcontext
from pathlib import Path
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch

from flask import Flask, jsonify


def _load_api_editor_for_tests():
    module_path = Path(__file__).with_name("api_editor.py")
    app = Flask("alweaver-api-editor-tests")

    class _CSRF:
        def exempt(self, fn):
            return fn

    current_user = types.SimpleNamespace(is_authenticated=False, id=None)

    app_object = types.ModuleType("docassemble.webapp.app_object")
    app_object.app = app
    app_object.csrf = _CSRF()

    server_mod = types.ModuleType("docassemble.webapp.server")

    def jsonify_with_status(payload, status):
        response = jsonify(payload)
        response.status_code = status
        return response

    server_mod.jsonify_with_status = jsonify_with_status
    server_mod.r = object()

    worker_common = types.ModuleType("docassemble.webapp.worker_common")
    worker_common.bg_context = nullcontext

    flask_cors = types.ModuleType("flask_cors")
    flask_cors.cross_origin = lambda *args, **kwargs: (lambda fn: fn)

    flask_login = types.ModuleType("flask_login")
    flask_login.current_user = current_user

    base_util = types.ModuleType("docassemble.base.util")
    base_util.log = lambda *args, **kwargs: None

    api_utils = types.ModuleType("docassemble.ALWeaver.api_utils")
    api_utils.generate_interview_from_bytes = lambda *args, **kwargs: {}
    api_utils.parse_bool = lambda value, default=False: (
        default
        if value is None
        else str(value).strip().lower() in {"1", "true", "yes", "on"}
    )
    api_utils.validate_upload_metadata = lambda **kwargs: (kwargs["filename"], ".docx")

    editor_utils = types.ModuleType("docassemble.ALWeaver.editor_utils")
    for name, func in {
        "canonical_block_yaml": lambda block: "id: block\n",
        "canonicalize_block_yaml": lambda yaml_text: yaml_text.strip(),
        "comment_out_block_in_yaml": lambda content, block_id: content,
        "delete_block_from_yaml": lambda content, block_id: content,
        "delete_saved_file": lambda *args, **kwargs: None,
        "generate_draft_order": lambda *args, **kwargs: {},
        "parse_interview_yaml": lambda *args, **kwargs: {
            "blocks": [],
            "metadata_blocks": [],
        },
        "parse_order_code": lambda *args, **kwargs: {},
        "playground_get_variables": lambda *args, **kwargs: {},
        "playground_interview_url": lambda *args, **kwargs: "/interview",
        "playground_list_projects": lambda *args, **kwargs: [],
        "playground_list_yaml_files": lambda *args, **kwargs: [],
        "playground_read_yaml": lambda *args, **kwargs: "",
        "playground_write_yaml": lambda *args, **kwargs: None,
        "rename_saved_file": lambda *args, **kwargs: None,
        "serialize_blocks_to_yaml": lambda *args, **kwargs: "",
        "serialize_order_steps": lambda *args, **kwargs: "",
        "enable_commented_block_in_yaml": lambda content, block_id: content,
        "reorder_blocks_in_yaml": lambda content, order: content,
        "update_block_in_yaml": lambda content, block_id, new_yaml: content,
    }.items():
        setattr(editor_utils, name, func)

    editor_ai_utils = types.ModuleType("docassemble.ALWeaver.editor_ai_utils")
    editor_ai_utils.DEFAULT_FIELD_TYPES = []
    editor_ai_utils.normalize_generated_fields = lambda *args, **kwargs: []
    editor_ai_utils.normalize_generated_screen = lambda *args, **kwargs: {}
    editor_ai_utils.pick_small_model_name = lambda *args, **kwargs: "gpt-5-nano"
    editor_ai_utils.validate_yaml_with_dayamlchecker = lambda *args, **kwargs: (
        True,
        "",
    )

    playground_publish = types.ModuleType("docassemble.ALWeaver.playground_publish")
    playground_publish.SECTION_TO_STORAGE = {
        "templates": "templates",
        "modules": "modules",
        "static": "static",
        "sources": "sources",
    }
    playground_publish._copy_files_to_section = lambda *args, **kwargs: None
    playground_publish.delete_project = lambda *args, **kwargs: None
    playground_publish.create_project = lambda *args, **kwargs: None
    playground_publish.get_list_of_projects = lambda *args, **kwargs: []
    playground_publish.next_available_project_name = (
        lambda base_name, existing=None: base_name
    )
    playground_publish.normalize_project_name = lambda raw_name: str(raw_name).strip()
    playground_publish.rename_project = lambda *args, **kwargs: None

    stubs = {
        "docassemble.base.util": base_util,
        "docassemble.webapp.app_object": app_object,
        "docassemble.webapp.server": server_mod,
        "docassemble.webapp.worker_common": worker_common,
        "flask_cors": flask_cors,
        "flask_login": flask_login,
        "docassemble.ALWeaver.api_utils": api_utils,
        "docassemble.ALWeaver.editor_utils": editor_utils,
        "docassemble.ALWeaver.editor_ai_utils": editor_ai_utils,
        "docassemble.ALWeaver.playground_publish": playground_publish,
    }
    previous = {name: sys.modules.get(name) for name in stubs}
    module_name = "docassemble.ALWeaver._test_api_editor"
    try:
        sys.modules.update(stubs)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load api_editor test module")
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


api_editor = _load_api_editor_for_tests()


class TestEditorApiFileCreation(unittest.TestCase):
    def test_normalize_new_filename_adds_yaml_extension(self):
        self.assertEqual(api_editor._normalize_new_filename("draft"), "draft.yml")
        self.assertEqual(api_editor._normalize_new_filename("draft.yaml"), "draft.yaml")

    def test_new_file_route_creates_default_yaml(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "playground_list_yaml_files", return_value=[]),
            patch.object(api_editor, "playground_write_yaml") as mock_write,
        ):
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
            patch.object(
                api_editor, "next_available_project_name", return_value="DocxSmoke"
            ),
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
        self.assertEqual(
            start_kwargs["generation_options"]["exact_name"], docx_path.name
        )
        self.assertEqual(
            start_kwargs["generation_options"]["help_source_text"],
            "Demand letter context",
        )
        self.assertEqual(
            start_kwargs["generation_options"]["help_page_url"],
            "https://example.com/help",
        )
        self.assertEqual(
            start_kwargs["generation_options"]["help_page_title"], "Help page title"
        )
        self.assertTrue(start_kwargs["generation_options"]["use_llm_assist"])
        self.assertFalse(start_kwargs["generation_options"]["create_package_zip"])
        self.assertFalse(start_kwargs["generation_options"]["include_next_steps"])
        self.assertEqual(len(start_kwargs["uploaded_files"]), 1)
        self.assertEqual(start_kwargs["uploaded_files"][0]["filename"], docx_path.name)
        self.assertIsInstance(start_kwargs["uploaded_files"][0]["content_bytes"], bytes)
        self.assertEqual(
            start_kwargs["uploaded_files"][0]["mimetype"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

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
        self.assertEqual(
            generate_kwargs["generation_options"]["exact_name"], docx_path.name
        )
        self.assertEqual(
            generate_kwargs["generation_options"]["help_source_text"],
            "Demand letter context",
        )
        self.assertEqual(
            generate_kwargs["generation_options"]["help_page_url"],
            "https://example.com/help",
        )
        self.assertEqual(
            generate_kwargs["generation_options"]["help_page_title"], "Help page title"
        )
        self.assertTrue(generate_kwargs["generation_options"]["use_llm_assist"])
        self.assertFalse(generate_kwargs["generation_options"]["create_package_zip"])
        self.assertFalse(generate_kwargs["generation_options"]["include_next_steps"])
        self.assertTrue(generate_kwargs["include_yaml_text"])
        mock_write.assert_called_once_with(
            7, "DocxSmoke", "interview.yml", generated_yaml
        )
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

    def test_editor_auth_return_target_rejects_protocol_relative_next(self):
        with api_editor.app.test_request_context("/al/editor?next=//evil.example"):
            self.assertEqual(
                api_editor._editor_auth_return_target(), api_editor.EDITOR_BASE_PATH
            )

    def test_comment_block_route_returns_structured_server_error(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor, "playground_read_yaml", return_value="id: block\n"
            ),
            patch.object(
                api_editor,
                "comment_out_block_in_yaml",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(api_editor, "log") as mock_log,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/block/comment",
                method="POST",
                json={"project": "default", "filename": "test.yml", "block_id": "b1"},
            ):
                response = api_editor.editor_api_comment_block()

        payload = response.get_json()
        self.assertEqual(response.status_code, 500)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["type"], "server_error")
        self.assertEqual(payload["error"]["message"], "boom")
        mock_log.assert_called_once_with(
            "ALWeaver editor: comment block error: RuntimeError('boom')", "error"
        )

    def test_enable_block_route_logs_enable_error(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor, "playground_read_yaml", return_value="id: block\n"
            ),
            patch.object(
                api_editor,
                "enable_commented_block_in_yaml",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(api_editor, "log") as mock_log,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/block/enable",
                method="POST",
                json={"project": "default", "filename": "test.yml", "block_id": "b1"},
            ):
                response = api_editor.editor_api_enable_block()

        payload = response.get_json()
        self.assertEqual(response.status_code, 500)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["type"], "server_error")
        self.assertEqual(payload["error"]["message"], "boom")
        mock_log.assert_called_once_with(
            "ALWeaver editor: enable block error: RuntimeError('boom')", "error"
        )


if __name__ == "__main__":
    unittest.main()

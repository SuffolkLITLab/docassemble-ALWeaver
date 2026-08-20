# do not pre-load

from io import BytesIO
from contextlib import nullcontext
from pathlib import Path
import os
import importlib
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch

from flask import Flask, jsonify


def _load_api_editor_for_tests():
    module_path = Path(__file__).with_name("api_editor.py")
    package_name = __package__ or "docassemble.ALWeaver"
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
    worker_common.workerapp = types.SimpleNamespace(
        send_task=lambda *args, **kwargs: None,
        AsyncResult=lambda *args, **kwargs: None,
    )

    flask_cors = types.ModuleType("flask_cors")
    flask_cors.cross_origin = lambda *args, **kwargs: (lambda fn: fn)

    flask_login = types.ModuleType("flask_login")
    flask_login.current_user = current_user

    base_util = types.ModuleType("docassemble.base.util")
    base_util.log = lambda *args, **kwargs: None

    api_utils = types.ModuleType(f"{package_name}.api_utils")
    api_utils.generate_interview_from_bytes = lambda *args, **kwargs: {}
    api_utils.parse_bool = lambda value, default=False: (
        default
        if value is None
        else str(value).strip().lower() in {"1", "true", "yes", "on"}
    )
    api_utils.validate_upload_metadata = lambda **kwargs: (kwargs["filename"], ".docx")

    editor_utils = types.ModuleType(f"{package_name}.editor_utils")
    for name, func in {
        "canonical_block_yaml": lambda block: "id: block\n",
        "canonicalize_block_yaml": lambda yaml_text: yaml_text.strip(),
        "comment_out_block_in_yaml": lambda content, block_id: content,
        "delete_block_from_yaml": lambda content, block_id: content,
        "delete_saved_file": lambda *args, **kwargs: None,
        "generate_draft_order": lambda *args, **kwargs: {},
        "insert_block_in_yaml": lambda content, block_yaml, insert_after_id=None: content,
        "inserted_block_id_by_position": lambda blocks, insert_after_id: None,
        "is_comment_only_yaml": lambda text: bool(
            [line for line in text.splitlines() if line.strip()]
        )
        and all(
            line.lstrip().startswith("#") for line in text.splitlines() if line.strip()
        ),
        "parse_interview_yaml": lambda *args, **kwargs: {
            "blocks": [],
            "metadata_blocks": [],
        },
        "metadata_source_slice": lambda *args, **kwargs: "",
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
        "source_revision": lambda text: "test-revision",
        "enable_commented_block_in_yaml": lambda content, block_id: content,
        "reorder_blocks_in_yaml": lambda content, order: content,
        "update_block_in_yaml": lambda content, block_id, new_yaml, **kwargs: content,
        "update_metadata_documents_in_yaml": lambda content, edited: content,
    }.items():
        setattr(editor_utils, name, func)
    # `document_bundles` and `template_analysis` are imported for real by
    # `api_editor`, and they read these from `editor_utils`.
    for name, value in {
        "BLOCK_TYPE_ATTACHMENT": "attachment",
        "BLOCK_TYPE_CODE": "code",
        "BLOCK_TYPE_OBJECTS": "objects",
        "BLOCK_TYPE_QUESTION": "question",
        "BLOCK_TYPE_TEMPLATE": "template",
        "_split_top_level_commas": lambda text: [part for part in str(text).split(",")],
    }.items():
        setattr(editor_utils, name, value)

    editor_ai_utils = types.ModuleType(f"{package_name}.editor_ai_utils")
    editor_ai_utils.DEFAULT_FIELD_TYPES = []
    editor_ai_utils.normalize_generated_fields = lambda *args, **kwargs: []
    editor_ai_utils.normalize_generated_screen = lambda *args, **kwargs: {}
    editor_ai_utils.pick_small_model_name = lambda *args, **kwargs: "gpt-5-nano"
    editor_ai_utils.validate_yaml_with_dayamlchecker = lambda *args, **kwargs: (
        True,
        "",
    )

    playground_publish = types.ModuleType(f"{package_name}.playground_publish")
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
    playground_publish.find_project_github_sync = lambda *args, **kwargs: None
    playground_publish.import_github_snapshot = lambda *args, **kwargs: {}
    playground_publish.merge_github_snapshot = lambda *args, **kwargs: {}
    playground_publish.next_available_project_name = (
        lambda base_name, existing=None: base_name
    )
    playground_publish.normalize_github_package_name = lambda raw_name: str(
        raw_name
    ).strip()
    playground_publish.normalize_project_name = lambda raw_name, **kwargs: str(
        raw_name
    ).strip()
    playground_publish.prepare_project_github_package = lambda **kwargs: {
        "package": kwargs["package_name"],
        "repository": "docassemble-" + kwargs["package_name"],
    }
    playground_publish.load_project_github_manifest = lambda **kwargs: ({}, "")
    playground_publish.record_project_github_sync = lambda *args, **kwargs: None
    playground_publish.rename_project = lambda *args, **kwargs: None

    stubs = {
        "docassemble.base.util": base_util,
        "docassemble.webapp.app_object": app_object,
        "docassemble.webapp.server": server_mod,
        "docassemble.webapp.worker_common": worker_common,
        "flask_cors": flask_cors,
        "flask_login": flask_login,
        f"{package_name}.api_utils": api_utils,
        f"{package_name}.editor_utils": editor_utils,
        f"{package_name}.editor_ai_utils": editor_ai_utils,
        f"{package_name}.playground_publish": playground_publish,
    }
    # `api_editor` imports this one for real. Import it before the stubs go in,
    # so it binds to the real `editor_utils` and the document endpoints can be
    # tested against actual YAML instead of a stub that returns nothing.
    importlib.import_module(f"{package_name}.document_bundles")
    previous = {name: sys.modules.get(name) for name in stubs}
    module_name = f"{package_name}._test_api_editor"
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


class _FakeRedis:
    """Just enough Redis for the editor's job-state records."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def pipeline(self):
        store = self.store

        class _Pipe:
            def __init__(self):
                self.pending = []

            def set(self, key, value):
                self.pending.append((key, value))
                return self

            def expire(self, key, seconds):
                return self

            def execute(self):
                for key, value in self.pending:
                    store[key] = value
                self.pending = []

        return _Pipe()


class TestEditorGithubApi(unittest.TestCase):
    def test_projects_only_marks_projects_with_a_github_manifest_as_synced(self):
        def find_sync(*, user_id, project_name):
            if project_name != "SyncedProject":
                return None
            return {
                "package": "SyncedProject",
                "repository_url": "https://github.com/LegalAid/docassemble-SyncedProject",
                "branch": "main",
                "commit": "base-sha",
            }

        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor,
                "playground_list_projects",
                return_value=["LocalOnly", "SyncedProject"],
            ),
            patch.object(api_editor, "find_project_github_sync", side_effect=find_sync),
        ):
            with api_editor.app.test_request_context("/al/editor/api/projects"):
                response = api_editor.editor_api_projects()

        data = response.get_json()["data"]
        self.assertEqual(data["projects"], ["LocalOnly", "SyncedProject"])
        self.assertNotIn("LocalOnly", data["github_syncs"])
        self.assertEqual(
            data["github_syncs"]["SyncedProject"]["repository_url"],
            "https://github.com/LegalAid/docassemble-SyncedProject",
        )

    def test_pull_uses_recorded_commit_as_a_three_way_merge_base(self):
        sync = {
            "package": "HousingForms",
            "repository_url": "https://github.com/LegalAid/docassemble-HousingForms",
            "branch": "main",
            "commit": "base-sha",
        }
        remote = {"sha": "remote-sha", "branch": "main", "files": {}}
        base = {"sha": "base-sha", "branch": "base-sha", "files": {}}
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "find_project_github_sync", return_value=sync),
            patch.object(
                api_editor, "get_github_repository_snapshot", side_effect=[remote, base]
            ) as snapshots,
            patch.object(
                api_editor,
                "merge_github_snapshot",
                return_value={"merged": True, "files": 3, "commit": "remote-sha"},
            ) as merge,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/github/pull", method="POST", json={"project": "Housing"}
            ):
                response = api_editor.editor_api_github_pull()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(snapshots.call_args_list[0].kwargs["ref"], "main")
        self.assertEqual(snapshots.call_args_list[1].kwargs["ref"], "base-sha")
        self.assertIs(merge.call_args.kwargs["base_snapshot"], base)
        self.assertIs(merge.call_args.kwargs["remote_snapshot"], remote)

    def test_pull_reports_conflicts_without_claiming_success(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor,
                "find_project_github_sync",
                return_value={
                    "package": "HousingForms",
                    "repository_url": "https://github.com/LegalAid/docassemble-HousingForms",
                    "branch": "main",
                    "commit": "same-sha",
                },
            ),
            patch.object(
                api_editor,
                "get_github_repository_snapshot",
                return_value={"sha": "same-sha", "branch": "main", "files": {}},
            ),
            patch.object(
                api_editor,
                "merge_github_snapshot",
                return_value={"merged": False, "conflicts": ["questions/main.yml"]},
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/github/pull", method="POST", json={"project": "Housing"}
            ):
                response = api_editor.editor_api_github_pull()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["type"], "merge_conflict")
        self.assertEqual(
            response.get_json()["error"]["details"]["conflicts"], ["questions/main.yml"]
        )

    def test_status_treats_stale_github_credentials_as_disconnected(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor,
                "get_native_github_integration",
                return_value={
                    "enabled": True,
                    "connected": True,
                    "organizations_enabled": True,
                    "configure_url": "/github",
                },
            ),
            patch.object(
                api_editor,
                "get_github_publish_owners",
                side_effect=api_editor.GithubCredentialError(
                    "The GitHub connection could not be read; reconnect it in Docassemble"
                ),
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/github/status?project=Housing"
            ):
                response = api_editor.editor_api_github_status()

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertFalse(data["connected"])
        self.assertFalse(data["organizations_enabled"])
        self.assertEqual(data["owners"], [])

    MANIFEST_PATH = "/playground/packages/Housing/docassemble.HousingForms"
    MANIFEST_INFO = {
        "interview_files": ["main.yml"],
        "template_files": [],
        "module_files": [],
        "static_files": [],
        "sources_files": [],
        "dependencies": [],
        "description": "Housing forms",
        "license": "MIT License",
        "readme": "# Housing forms",
        "url": "",
        "version": "0.0.1",
    }

    def test_publish_prepares_manifest_and_queues_a_background_commit(self):
        """The request must not hold open the per-file GitHub round trips."""
        prepared = {
            "package": "HousingForms",
            "repository": "docassemble-HousingForms",
            "manifest_path": "/playground/packages/Housing/docassemble.HousingForms",
        }
        sent = {}

        def fake_send_task(task_name, kwargs=None):
            sent["task_name"] = task_name
            sent["kwargs"] = kwargs
            return types.SimpleNamespace(id="celery-task-1")

        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "_editor_async_is_configured", return_value=True),
            patch.object(api_editor, "r", _FakeRedis()),
            patch.object(
                api_editor,
                "workerapp",
                types.SimpleNamespace(send_task=fake_send_task),
            ),
            patch.object(
                api_editor,
                "get_native_github_integration",
                return_value={
                    "enabled": True,
                    "connected": True,
                    "organizations_enabled": True,
                },
            ),
            patch.object(
                api_editor,
                "get_github_publish_owners",
                return_value=[
                    {"login": "ada", "type": "user"},
                    {"login": "LegalAid", "type": "organization"},
                ],
            ),
            patch.object(
                api_editor,
                "prepare_project_github_package",
                return_value=prepared,
            ) as prepare,
            patch.object(api_editor, "ensure_github_repository") as ensure_repository,
            patch.object(api_editor, "publish_github_package") as publish,
            patch.object(api_editor, "_editor_user_designator", return_value="Ada"),
        ):
            api_editor.current_user.email = "ada@example.com"
            with api_editor.app.test_request_context(
                "/al/editor/api/github/publish",
                method="POST",
                json={
                    "project": "Housing",
                    "owner": "LegalAid",
                    "package": "HousingForms",
                    "branch": "feature/github",
                    "commit_message": "Update interview",
                },
            ):
                response = api_editor.editor_api_github_publish()

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["status"], "queued")
        data = payload["data"]
        self.assertEqual(data["repository"], "docassemble-HousingForms")
        self.assertEqual(data["owner"], "LegalAid")
        self.assertEqual(data["branch"], "feature/github")
        self.assertEqual(
            data["job_url"],
            f"/al/editor/api/github/publish/jobs/{payload['job_id']}",
        )
        self.assertEqual(data["state"]["status"], "queued")

        # No GitHub traffic happens in the request itself.
        ensure_repository.assert_not_called()
        publish.assert_not_called()
        prepare.assert_called_once_with(
            user_id=7,
            project_name="Housing",
            package_name="HousingForms",
            author_name="Ada",
            author_email="ada@example.com",
            github_url="https://github.com/LegalAid/docassemble-HousingForms",
        )
        self.assertEqual(
            sent["task_name"],
            "docassemble.ALWeaver.api_weaver_worker.weaver_editor_github_publish_task",
        )
        self.assertEqual(
            sent["kwargs"],
            {
                "job_id": payload["job_id"],
                "uid": 7,
                "project": "Housing",
                "package": "HousingForms",
                "repository": "docassemble-HousingForms",
                "owner": "LegalAid",
                "owner_type": "organization",
                "author_name": "Ada",
                "author_email": "ada@example.com",
                "branch": "feature/github",
                "commit_message": "Update interview",
                "repository_url": "https://github.com/LegalAid/docassemble-HousingForms",
            },
        )

    def test_publish_refuses_when_celery_is_not_configured(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "_editor_async_is_configured", return_value=False),
            patch.object(
                api_editor,
                "get_worker_configuration_status",
                return_value={"configured": False, "message": "Not configured."},
            ),
            patch.object(api_editor, "prepare_project_github_package") as prepare,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/github/publish",
                method="POST",
                json={
                    "project": "Housing",
                    "owner": "LegalAid",
                    "package": "HousingForms",
                    "branch": "main",
                    "commit_message": "Update interview",
                },
            ):
                response = api_editor.editor_api_github_publish()

        self.assertEqual(response.status_code, 503)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "editor_async_not_configured")
        prepare.assert_not_called()

    def test_publish_job_runs_the_github_calls_and_records_the_commit(self):
        redis = _FakeRedis()
        with (
            patch.object(api_editor, "r", redis),
            patch.object(
                api_editor,
                "load_project_github_manifest",
                return_value=(dict(self.MANIFEST_INFO), self.MANIFEST_PATH),
            ) as load_manifest,
            patch.object(
                api_editor,
                "ensure_github_repository",
                return_value={
                    "html_url": "https://github.com/LegalAid/docassemble-HousingForms",
                    "default_branch": "main",
                    "created_by_weaver": True,
                },
            ) as ensure_repository,
            patch.object(
                api_editor,
                "publish_github_package",
                return_value={"sha": "commit-sha", "files": 12},
            ) as publish,
        ):
            result = api_editor._complete_github_publish_job(
                job_id="job-1",
                uid=7,
                project="Housing",
                package="HousingForms",
                repository="docassemble-HousingForms",
                owner="LegalAid",
                owner_type="organization",
                author_name="Ada",
                author_email="ada@example.com",
                branch="feature/github",
                commit_message="Update interview",
                repository_url="https://github.com/LegalAid/docassemble-HousingForms",
            )
            state = api_editor._load_job_state(api_editor.GITHUB_PUBLISH_JOB, "job-1")
            publish_kwargs = publish.call_args.kwargs
            # The progress hook writes through to the job record.
            publish_kwargs["on_progress"]("Uploading main.yml (1 of 2).", 50)
            progressed = api_editor._load_job_state(
                api_editor.GITHUB_PUBLISH_JOB, "job-1"
            )

        self.assertEqual(result["commit_sha"], "commit-sha")
        self.assertEqual(result["files_committed"], 12)
        self.assertTrue(result["repository_created"])
        self.assertEqual(
            result["commit_url"],
            "https://github.com/LegalAid/docassemble-HousingForms/commit/commit-sha",
        )
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["progress"], 100)
        self.assertEqual(state["result"], result)

        ensure_repository.assert_called_once_with(
            owner="LegalAid",
            repository="docassemble-HousingForms",
            description="A docassemble project for Housing.",
            owner_type="organization",
            user_id=7,
        )
        # The manifest is re-read in the worker rather than trusting a path
        # handed across the queue, so this works on a multi-server install.
        load_manifest.assert_called_once_with(
            user_id=7,
            project_name="Housing",
            package_name="HousingForms",
        )
        self.assertEqual(publish_kwargs["package_info"], self.MANIFEST_INFO)
        self.assertEqual(publish_kwargs["manifest_path"], self.MANIFEST_PATH)
        self.assertEqual(publish_kwargs["default_branch"], "main")
        self.assertEqual(publish_kwargs["branch"], "feature/github")
        self.assertEqual(publish_kwargs["author_email"], "ada@example.com")
        self.assertEqual(progressed["message"], "Uploading main.yml (1 of 2).")
        self.assertEqual(progressed["progress"], 55)

    def test_publish_job_records_a_lost_github_connection_as_a_failure(self):
        with (
            patch.object(api_editor, "r", _FakeRedis()),
            patch.object(
                api_editor,
                "ensure_github_repository",
                side_effect=api_editor.GithubCredentialError(
                    "The GitHub connection has expired; reconnect it in Docassemble"
                ),
            ),
        ):
            with self.assertRaises(api_editor.GithubCredentialError):
                api_editor._complete_github_publish_job(
                    job_id="job-2",
                    uid=7,
                    project="Housing",
                    package="HousingForms",
                    repository="docassemble-HousingForms",
                    owner="LegalAid",
                    owner_type="organization",
                    author_name="Ada",
                    author_email="ada@example.com",
                    branch="main",
                    commit_message="Update interview",
                    repository_url="https://github.com/LegalAid/docassemble-HousingForms",
                )
            state = api_editor._load_job_state(api_editor.GITHUB_PUBLISH_JOB, "job-2")

        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["stage"], "ensure_repository")
        self.assertEqual(state["error"]["type"], "github_not_connected")

    def test_publish_job_status_is_scoped_to_its_owner(self):
        redis = _FakeRedis()
        with patch.object(api_editor, "r", redis):
            api_editor._store_job_state(
                api_editor.GITHUB_PUBLISH_JOB,
                "job-3",
                {"status": "succeeded", "owner_user_id": 7, "result": {"files": 3}},
            )
            with (
                patch.object(api_editor, "_editor_auth_check", return_value=True),
                patch.object(api_editor, "_current_user_id", return_value=7),
            ):
                with api_editor.app.test_request_context(
                    "/al/editor/api/github/publish/jobs/job-3"
                ):
                    owner_response = api_editor.editor_api_github_publish_job("job-3")
            with (
                patch.object(api_editor, "_editor_auth_check", return_value=True),
                patch.object(api_editor, "_current_user_id", return_value=99),
            ):
                with api_editor.app.test_request_context(
                    "/al/editor/api/github/publish/jobs/job-3"
                ):
                    other_response = api_editor.editor_api_github_publish_job("job-3")

        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(owner_response.get_json()["status"], "succeeded")
        self.assertEqual(other_response.status_code, 404)

    def test_publish_rejects_invalid_branch_before_writing_manifest(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "prepare_project_github_package") as prepare,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/github/publish",
                method="POST",
                json={
                    "project": "Housing",
                    "owner": "ada",
                    "package": "HousingForms",
                    "branch": "bad branch",
                    "commit_message": "Update interview",
                },
            ):
                response = api_editor.editor_api_github_publish()

        self.assertEqual(response.status_code, 400)
        self.assertIn("valid Git branch", response.get_json()["error"]["message"])
        prepare.assert_not_called()


class TestEditorProjectSearchApi(unittest.TestCase):
    def test_search_returns_context_group_metadata_and_revisions(self):
        project_files = [
            {
                "section": "interview",
                "file_type": "interview",
                "file_type_label": "Interviews",
                "filename": "main.yml",
                "content": "question: Alpha\n",
                "revision": "revision-main",
            },
            {
                "section": "modules",
                "file_type": "modules",
                "file_type_label": "Modules",
                "filename": "helper.py",
                "content": "alpha = 1\n",
                "revision": "revision-helper",
            },
        ]
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor,
                "_project_text_files",
                return_value=(project_files, []),
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/project/search",
                method="POST",
                json={"project": "default", "query": "alpha", "mode": "text"},
            ):
                response = api_editor.editor_api_project_search()

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["match_count"], 2)
        self.assertEqual(data["file_count"], 2)
        self.assertEqual(data["files"][0]["file_type_label"], "Interviews")
        self.assertEqual(data["files"][0]["matches"][0]["line"], 1)
        self.assertEqual(data["files"][1]["revision"], "revision-helper")

    def test_replace_preflights_exact_spans_before_committing(self):
        source = "alpha and alpha\n"
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "_read_project_text_file", return_value=source),
            patch.object(api_editor, "_commit_project_replacements") as commit,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/project/replace",
                method="POST",
                json={
                    "project": "default",
                    "query": "alpha",
                    "replacement": "beta",
                    "mode": "text",
                    "files": [
                        {
                            "section": "interview",
                            "filename": "main.yml",
                            "revision": "test-revision",
                            "matches": [{"start": 0, "end": 5}],
                        }
                    ],
                },
            ):
                response = api_editor.editor_api_project_replace()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["replacement_count"], 1)
        changes = commit.call_args.args[2]
        self.assertEqual(changes[0]["updated"], "beta and alpha\n")

    def test_replace_rejects_stale_search_without_writing(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "_read_project_text_file", return_value="alpha\n"),
            patch.object(api_editor, "_commit_project_replacements") as commit,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/project/replace",
                method="POST",
                json={
                    "project": "default",
                    "query": "alpha",
                    "replacement": "beta",
                    "mode": "text",
                    "files": [
                        {
                            "section": "interview",
                            "filename": "main.yml",
                            "revision": "older-revision",
                            "matches": [{"start": 0, "end": 5}],
                        }
                    ],
                },
            ):
                response = api_editor.editor_api_project_replace()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "stale_search")
        commit.assert_not_called()

    def test_variable_refactor_reuses_safe_rename_planning_across_a_file(self):
        source = (
            "---\n"
            "id: ask_name\n"
            "question: Name\n"
            "fields:\n"
            "  - Name: old_name\n"
            "---\n"
            "id: use_name\n"
            "code: |\n"
            "  if old_name:\n"
            "    pass\n"
        )
        project_files = [
            {
                "section": "interview",
                "file_type": "interview",
                "file_type_label": "Interviews",
                "filename": "main.yml",
                "content": source,
                "revision": "source-revision",
            }
        ]
        validation = types.SimpleNamespace(blocking=False)
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor,
                "_project_text_files",
                return_value=(project_files, []),
            ),
            patch.object(
                api_editor, "_project_search_revision", return_value="manifest"
            ),
            patch.object(
                api_editor, "validate_candidate_source", return_value=validation
            ),
            patch.object(api_editor, "_commit_project_replacements") as commit,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/project/replace",
                method="POST",
                json={
                    "project": "default",
                    "query": "old_name",
                    "replacement": "client_name",
                    "mode": "variable",
                    "project_revision": "manifest",
                },
            ):
                response = api_editor.editor_api_project_replace()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["replacement_count"], 2)
        updated = commit.call_args.args[2][0]["updated"]
        self.assertNotIn("old_name", updated)
        self.assertEqual(updated.count("client_name"), 2)

    def test_final_batch_preflight_detects_a_race_before_any_write(self):
        changes = [
            {
                "section": "interview",
                "filename": "one.yml",
                "original": "one old",
                "updated": "one new",
            },
            {
                "section": "modules",
                "filename": "two.py",
                "original": "two old",
                "updated": "two new",
            },
        ]
        with (
            patch.object(
                api_editor,
                "_read_project_text_file",
                side_effect=["one old", "two changed elsewhere"],
            ),
            patch.object(api_editor, "_write_project_text_file") as write,
        ):
            with self.assertRaises(api_editor.StaleProjectSearchError) as raised:
                api_editor._commit_project_replacements(7, "default", changes)

        self.assertEqual(raised.exception.files[0]["filename"], "two.py")
        write.assert_not_called()


class TestEditorApiFileCreation(unittest.TestCase):
    def test_github_import_derives_project_name_from_repository(self):
        snapshot = {
            "url": "https://github.com/OtherOrg/docassemble-PublicForms",
            "branch": "HEAD",
            "sha": "remote-sha",
            "files": {},
        }
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "get_list_of_projects", return_value=[]),
            patch.object(
                api_editor,
                "next_available_project_name",
                side_effect=lambda base, existing: base,
            ),
            patch.object(api_editor, "create_project") as create,
            patch.object(
                api_editor, "get_github_repository_snapshot", return_value=snapshot
            ),
            patch.object(
                api_editor,
                "import_github_snapshot",
                return_value={"filename": "main.yml", "files_imported": 1},
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/new-project",
                method="POST",
                json={
                    "project_name": "",
                    "github_url": "https://github.com/OtherOrg/docassemble-PublicForms",
                },
            ):
                response = api_editor.editor_api_new_project()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["project"], "PublicForms")
        create.assert_called_once_with(7, "PublicForms")

    def test_new_project_can_import_any_github_repository_url(self):
        snapshot = {
            "url": "https://github.com/OtherOrg/docassemble-PublicForms",
            "branch": "main",
            "sha": "remote-sha",
            "files": {},
        }
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "get_list_of_projects", return_value=[]),
            patch.object(
                api_editor, "next_available_project_name", return_value="PublicForms"
            ),
            patch.object(api_editor, "create_project") as create,
            patch.object(
                api_editor, "get_github_repository_snapshot", return_value=snapshot
            ) as fetch,
            patch.object(
                api_editor,
                "import_github_snapshot",
                return_value={"filename": "main.yml", "files_imported": 4},
            ) as import_snapshot,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/new-project",
                method="POST",
                json={
                    "project_name": "PublicForms",
                    "github_url": "https://github.com/OtherOrg/docassemble-PublicForms",
                },
            ):
                response = api_editor.editor_api_new_project()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["filename"], "main.yml")
        create.assert_called_once_with(7, "PublicForms")
        self.assertEqual(
            fetch.call_args.kwargs["repository_url"],
            "https://github.com/OtherOrg/docassemble-PublicForms",
        )
        import_snapshot.assert_called_once_with(
            user_id=7, project_name="PublicForms", snapshot=snapshot
        )

    def test_save_file_accepts_intentionally_empty_source(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "playground_write_yaml") as mock_write,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/file",
                method="POST",
                json={
                    "project": "default",
                    "filename": "test.yml",
                    "content": "",
                },
            ):
                response = api_editor.editor_api_save_file()

        self.assertEqual(response.status_code, 200)
        mock_write.assert_called_once_with(7, "default", "test.yml", "")

    def test_save_file_rejects_missing_content(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "playground_write_yaml") as mock_write,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/file",
                method="POST",
                json={"project": "default", "filename": "test.yml"},
            ):
                response = api_editor.editor_api_save_file()

        self.assertEqual(response.status_code, 400)
        self.assertIn("content must be", response.get_json()["error"]["message"])
        mock_write.assert_not_called()

    def test_validate_source_uses_submitted_buffer(self):
        submitted = "---\nid: unsaved\nquestion: Unsaved title\n"
        saved = "---\nid: saved\nquestion: Saved title\n"
        findings = [
            {
                "severity": "warning",
                "level": "warning",
                "message": "Unsaved diagnostic",
                "filename": "test.yml",
                "file_name": "test.yml",
                "block_id": "unsaved",
                "source_range": None,
                "yaml_path": None,
            }
        ]
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "playground_read_yaml", return_value=saved),
            patch.object(
                api_editor, "_validate_source_text", return_value=findings
            ) as mock_validate,
            patch.object(
                api_editor, "playground_get_variables"
            ) as mock_saved_variable_check,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/validate-source",
                method="POST",
                json={
                    "project": "default",
                    "filename": "test.yml",
                    "raw_yaml": submitted,
                    "revision": "test-revision",
                },
            ):
                response = api_editor.editor_api_validate_source()

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["scope"], "unsaved_source")
        self.assertEqual(payload["filename"], "test.yml")
        self.assertEqual(payload["diagnostics"], findings)
        self.assertEqual(payload["errors"], findings)
        self.assertTrue(payload["base_revision_matches"])
        mock_validate.assert_called_once_with(submitted, "test.yml")
        mock_saved_variable_check.assert_not_called()

    def test_get_file_returns_exact_raw_yaml_for_populated_and_empty_files(self):
        model = {
            "blocks": [],
            "metadata_blocks": [],
            "include_blocks": [],
            "default_screen_parts_blocks": [],
            "order_blocks": [],
        }
        for source in ("metadata:\n  title: 'Exact'\n", ""):
            with self.subTest(source=source):
                with (
                    patch.object(api_editor, "_editor_auth_check", return_value=True),
                    patch.object(api_editor, "_current_user_id", return_value=7),
                    patch.object(
                        api_editor, "playground_read_yaml", return_value=source
                    ),
                    patch.object(
                        api_editor, "parse_interview_yaml", return_value=model
                    ),
                ):
                    with api_editor.app.test_request_context(
                        "/al/editor/api/file?project=default&filename=test.yml",
                        method="GET",
                    ):
                        response = api_editor.editor_api_get_file()

                payload = response.get_json()["data"]
                self.assertEqual(payload["filename"], "test.yml")
                self.assertEqual(payload["raw_yaml"], source)
                self.assertIn("revision", payload)

    def test_new_project_route_uploads_docx_queues_background_job(self):
        docx_path = Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"

        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "get_list_of_projects", return_value=[]),
            patch.object(api_editor, "_editor_async_is_configured", return_value=True),
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
        self.assertTrue(start_kwargs["generation_options"]["include_next_steps"])
        self.assertTrue(start_kwargs["generation_options"]["include_download_screen"])
        self.assertTrue(
            start_kwargs["generation_options"]["interview_overrides"][
                "next_steps_enabled"
            ]
        )
        self.assertEqual(len(start_kwargs["uploaded_files"]), 1)
        self.assertEqual(start_kwargs["uploaded_files"][0]["filename"], docx_path.name)
        self.assertIsInstance(start_kwargs["uploaded_files"][0]["content_bytes"], bytes)
        self.assertEqual(
            start_kwargs["uploaded_files"][0]["mimetype"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_new_project_upload_refuses_when_celery_is_not_configured(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "_editor_async_is_configured", return_value=False),
            patch.object(api_editor, "create_project") as mock_create_project,
        ):
            with api_editor.app.test_client() as client:
                response = client.post(
                    "/al/editor/api/new-project",
                    data={
                        "project_name": "DocxSmoke",
                        "files": (BytesIO(b"not read"), "source.docx"),
                    },
                    content_type="multipart/form-data",
                )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["error"]["code"], "editor_async_not_configured"
        )
        details = response.get_json()["error"]["details"]
        self.assertFalse(details["configured"])
        self.assertIn("#celery-worker-configuration", details["docs_url"])
        mock_create_project.assert_not_called()

    def test_start_new_project_job_enqueues_celery_without_daemon_thread(self):
        async_result = types.SimpleNamespace(id="celery-task-1")
        with (
            patch.object(api_editor, "_store_new_project_job_state") as mock_store,
            patch.object(api_editor, "_update_new_project_job_state") as mock_update,
            patch.object(
                api_editor.workerapp, "send_task", return_value=async_result
            ) as mock_send,
        ):
            result = api_editor._start_new_project_upload_job(
                uid=7,
                request_id="req-1",
                project_name="DocxSmoke",
                uploaded_files=[
                    {
                        "filename": "source.docx",
                        "content_bytes": b"content",
                        "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    }
                ],
                generation_options={"include_next_steps": False},
                debug_requested=False,
            )

        self.assertEqual(result["state"]["status"], "queued")
        self.assertEqual(result["state"]["owner_user_id"], 7)
        self.assertEqual(result["state"]["operation_type"], "new_project_upload")
        mock_store.assert_called_once()
        mock_send.assert_called_once()
        self.assertEqual(
            mock_send.call_args.kwargs["kwargs"]["job_id"], result["job_id"]
        )
        mock_update.assert_called_once_with(
            result["job_id"], celery_task_id="celery-task-1"
        )

        api_source = Path(api_editor.__file__).read_text()
        self.assertNotIn("import threading", api_source)
        self.assertNotIn("threading.Thread", api_source)

    def test_metadata_save_preserves_unrelated_source_exactly(self):
        from . import editor_utils as real_editor_utils

        source = (
            "# header\n"
            "metadata:\n"
            "  title: 'Original' # title comment\n"
            "---\n"
            "# unrelated comment\n"
            "id: intro\n"
            "question: |\n"
            "  Keep this exactly.\n"
        )
        edited = "# header\nmetadata:\n  title: 'Edited' # title comment"
        revision = real_editor_utils.source_revision(source)

        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "playground_read_yaml", return_value=source),
            patch.object(api_editor, "playground_write_yaml") as mock_write,
            patch.object(
                api_editor,
                "source_revision",
                side_effect=real_editor_utils.source_revision,
            ),
            patch.object(
                api_editor,
                "update_metadata_documents_in_yaml",
                side_effect=real_editor_utils.update_metadata_documents_in_yaml,
            ),
            patch.object(
                api_editor,
                "parse_interview_yaml",
                side_effect=real_editor_utils.parse_interview_yaml,
            ),
            patch.object(
                api_editor,
                "metadata_source_slice",
                side_effect=real_editor_utils.metadata_source_slice,
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/file/metadata",
                method="POST",
                json={
                    "project": "default",
                    "filename": "test.yml",
                    "raw_yaml": edited,
                    "expected_revision": revision,
                },
            ):
                response = api_editor.editor_api_save_metadata()

        expected = source.replace("'Original'", "'Edited'")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["raw_yaml"], expected)
        mock_write.assert_called_once_with(7, "default", "test.yml", expected)

    def test_assemblyline_settings_get_returns_schema_and_revision(self):
        source = "metadata:\n  title: Example\n"
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "playground_read_yaml", return_value=source),
            patch.object(
                api_editor,
                "read_settings",
                return_value={"schema": [], "values": {"title": "Example"}},
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/assemblyline-settings?project=default&filename=test.yml"
            ):
                response = api_editor.editor_api_get_assemblyline_settings()

        payload = response.get_json()["data"]
        self.assertEqual(payload["values"]["title"], "Example")
        self.assertEqual(payload["revision"], "test-revision")

    def test_assemblyline_settings_save_rejects_stale_revision(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "playground_read_yaml", return_value="source"),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/assemblyline-settings",
                method="POST",
                json={
                    "project": "default",
                    "filename": "test.yml",
                    "expected_revision": "old-revision",
                    "settings": {"title": "Changed"},
                },
            ):
                response = api_editor.editor_api_save_assemblyline_settings()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "revision_conflict")


class TestEditorNewProjectNaming(unittest.TestCase):
    """A generated project is named after its document, not "interview.yml"."""

    def _run_upload_job(self, yaml_filename, interview_filename=None):
        with (
            patch.object(api_editor, "_update_new_project_job_state"),
            patch.object(api_editor, "playground_write_yaml") as mock_write,
            patch.object(api_editor, "_copy_files_to_section"),
            patch.object(
                api_editor,
                "generate_interview_from_bytes",
                return_value={
                    "yaml_text": "metadata:\n  title: Eviction\n",
                    "yaml_filename": yaml_filename,
                    "input_filename": "eviction.pdf",
                    "generated_template_files": [],
                },
            ),
        ):
            result = api_editor._complete_new_project_upload_job(
                job_id="job-1",
                uid=7,
                project_name="Eviction",
                request_id="req-1",
                uploaded_files=[
                    {
                        "filename": "eviction.pdf",
                        "content_bytes": b"%PDF-1.4",
                        "mimetype": "application/pdf",
                    }
                ],
                generation_options={},
                debug_requested=False,
                interview_filename=interview_filename,
            )
        return result, mock_write

    def test_generated_project_keeps_the_descriptive_name_weaver_derived(self):
        result, mock_write = self._run_upload_job("eviction.yml")
        self.assertEqual(result["filename"], "eviction.yml")
        self.assertEqual(mock_write.call_args.args[2], "eviction.yml")

    def test_author_supplied_filename_wins(self):
        result, mock_write = self._run_upload_job(
            "eviction.yml", interview_filename="main.yml"
        )
        self.assertEqual(result["filename"], "main.yml")
        self.assertEqual(mock_write.call_args.args[2], "main.yml")

    def test_an_unusable_derived_name_falls_back_to_the_assemblyline_default(self):
        result, _mock_write = self._run_upload_job("")
        self.assertEqual(result["filename"], "main.yml")

    def test_blank_project_uses_main_yml(self):
        with (
            patch.object(api_editor, "playground_write_yaml") as mock_write,
            patch.object(api_editor, "get_list_of_projects", return_value=[]),
            patch.object(
                api_editor, "next_available_project_name", return_value="Blank"
            ),
            patch.object(api_editor, "create_project"),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/new-project", json={"project_name": "Blank"}
            ):
                response = api_editor._new_project_from_template(7, "req-1")
        self.assertEqual(response.get_json()["data"]["filename"], "main.yml")
        self.assertEqual(mock_write.call_args.args[2], "main.yml")

    def test_publishing_metadata_reaches_the_generator(self):
        pdf_path = Path(__file__).parent / "test/test_dropdown_fields.pdf"
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "get_list_of_projects", return_value=[]),
            patch.object(api_editor, "_editor_async_is_configured", return_value=True),
            patch.object(
                api_editor, "next_available_project_name", return_value="Meta"
            ),
            patch.object(api_editor, "create_project"),
            patch.object(api_editor, "_start_new_project_upload_job") as mock_start_job,
        ):
            mock_start_job.return_value = {
                "job_id": "job-1",
                "job_url": "/al/editor/api/new-project/jobs/job-1",
                "state": {"status": "queued"},
            }
            with api_editor.app.test_client() as client:
                with pdf_path.open("rb") as handle:
                    client.post(
                        "/al/editor/api/new-project",
                        data={
                            "project_name": "Meta",
                            "interview_title": "Petition to enforce the sanitary code",
                            "interview_short_title": "Sanitary code",
                            "interview_description": "Ask the court to inspect.",
                            "jurisdiction": "NAM-US-US+MA",
                            "landing_page_url": "https://example.org/sanitary",
                            "list_topics": "HO-00-00-00-00, HO-05-00-00-00",
                            "interview_filename": "sanitary_code.yml",
                            "default_state": "MA",
                            "files": (BytesIO(handle.read()), pdf_path.name),
                        },
                        content_type="multipart/form-data",
                    )

        kwargs = mock_start_job.call_args.kwargs
        overrides = kwargs["generation_options"]["interview_overrides"]
        self.assertEqual(kwargs["interview_filename"], "sanitary_code.yml")
        self.assertEqual(overrides["title"], "Petition to enforce the sanitary code")
        self.assertEqual(overrides["short_title"], "Sanitary code")
        self.assertEqual(overrides["description"], "Ask the court to inspect.")
        self.assertEqual(overrides["landing_page_url"], "https://example.org/sanitary")
        self.assertTrue(overrides["has_other_categories"])
        self.assertEqual(
            overrides["other_categories"], "HO-00-00-00-00, HO-05-00-00-00"
        )
        # An explicit jurisdiction is not overwritten by the default state.
        self.assertEqual(overrides["jurisdiction"], "NAM-US-US+MA")
        self.assertEqual(overrides["state"], "MA")


class TestEditorNewProjectMultipleUploads(unittest.TestCase):
    """Every uploaded document is woven into the one generated interview."""

    def _run(self, uploaded_files, generator_result=None, **job_kwargs):
        payload = {
            "yaml_text": "metadata:\n  title: Filing\n",
            "yaml_filename": "filing.yml",
            "input_filename": uploaded_files[0]["filename"],
            "generated_template_files": [],
        }
        payload.update(generator_result or {})
        written = {}
        with (
            patch.object(api_editor, "_update_new_project_job_state"),
            patch.object(api_editor, "playground_write_yaml"),
            patch.object(api_editor, "_copy_files_to_section") as mock_copy,
            patch.object(
                api_editor, "generate_interview_from_bytes", return_value=payload
            ) as mock_generate,
        ):
            mock_copy.side_effect = lambda **kwargs: written.update(
                {
                    os.path.basename(path): Path(path).read_bytes()
                    for path in kwargs["files"]
                }
            )
            result = api_editor._complete_new_project_upload_job(
                job_id="job-1",
                uid=7,
                project_name="Filing",
                request_id="req-1",
                uploaded_files=uploaded_files,
                generation_options={},
                debug_requested=False,
                **job_kwargs,
            )
        return result, mock_generate.call_args.kwargs, written

    def test_the_companion_documents_reach_the_generator(self):
        result, generate_kwargs, written = self._run(
            [
                {
                    "filename": "petition.pdf",
                    "content_bytes": b"%PDF-petition",
                    "mimetype": "application/pdf",
                },
                {
                    "filename": "affidavit.pdf",
                    "content_bytes": b"%PDF-affidavit",
                    "mimetype": "application/pdf",
                },
            ],
            generator_result={"template_filenames": ["petition.pdf", "affidavit.pdf"]},
        )

        self.assertEqual(generate_kwargs["filename"], "petition.pdf")
        self.assertEqual(
            [
                document["filename"]
                for document in generate_kwargs["additional_documents"]
            ],
            ["affidavit.pdf"],
        )
        self.assertEqual(
            generate_kwargs["additional_documents"][0]["content_bytes"],
            b"%PDF-affidavit",
        )
        self.assertEqual(result["woven_templates"], ["petition.pdf", "affidavit.pdf"])
        self.assertEqual(sorted(written), ["affidavit.pdf", "petition.pdf"])

    def test_the_project_stores_the_names_the_yaml_refers_to(self):
        """Two uploads sharing a name are told apart by the generator."""
        _result, _generate_kwargs, written = self._run(
            [
                {
                    "filename": "form.pdf",
                    "content_bytes": b"%PDF-first",
                    "mimetype": "application/pdf",
                },
                {
                    "filename": "form.pdf",
                    "content_bytes": b"%PDF-second",
                    "mimetype": "application/pdf",
                },
            ],
            generator_result={"template_filenames": ["form.pdf", "form_2.pdf"]},
        )
        self.assertEqual(written["form.pdf"], b"%PDF-first")
        self.assertEqual(written["form_2.pdf"], b"%PDF-second")

    def test_a_renamed_template_replaces_the_original_in_the_project(self):
        """The YAML names fields that only exist in the rewritten file."""
        result, _generate_kwargs, written = self._run(
            [
                {
                    "filename": "petition.pdf",
                    "content_bytes": b"%PDF-original",
                    "mimetype": "application/pdf",
                },
                {
                    "filename": "affidavit.pdf",
                    "content_bytes": b"%PDF-untouched",
                    "mimetype": "application/pdf",
                },
            ],
            generator_result={
                "template_filenames": ["petition.pdf", "affidavit.pdf"],
                "normalized_template_files": [
                    {"filename": "petition.pdf", "content_bytes": b"%PDF-renamed"}
                ],
            },
        )
        self.assertEqual(written["petition.pdf"], b"%PDF-renamed")
        self.assertEqual(written["affidavit.pdf"], b"%PDF-untouched")
        self.assertEqual(result["renamed_template_count"], 1)


INTERVIEW_WITH_TWO_DOCUMENTS = """---
objects:
  - petition: ALDocument.using(filename="petition", enabled=True)
  - affidavit: ALDocument.using(filename="affidavit", enabled=True)
---
objects:
  - al_user_bundle: ALDocumentBundle.using(elements=[petition, affidavit], filename="p", enabled=True)
"""


class TestEditorTemplateAnalysisApi(unittest.TestCase):
    """Analyzing a template that was added to a project after it was created."""

    def _post(self, payload, handler):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/template/analyze", method="POST", json=payload
            ):
                return handler()

    def test_a_template_that_is_not_in_the_project_is_a_404(self):
        with patch.object(
            api_editor,
            "_template_analysis_target",
            side_effect=FileNotFoundError("nope.pdf is not in this project"),
        ):
            response = self._post(
                {"project": "Eviction", "filename": "main.yml", "template": "nope.pdf"},
                api_editor.editor_api_analyze_template,
            )
        self.assertEqual(response.status_code, 404)

    def test_a_queued_analysis_reports_where_to_poll(self):
        with (
            patch.object(
                api_editor, "_template_analysis_target", return_value="/tmp/a.pdf"
            ),
            patch.object(api_editor, "playground_read_yaml", return_value="---\n"),
            patch.object(api_editor, "_editor_async_is_configured", return_value=True),
            patch.object(api_editor, "_store_job_state"),
            patch.object(api_editor, "_update_job_state"),
            patch.object(
                api_editor.workerapp,
                "send_task",
                return_value=types.SimpleNamespace(id="celery-1"),
            ) as mock_send,
        ):
            response = self._post(
                {
                    "project": "Eviction",
                    "filename": "main.yml",
                    "template": "affidavit.pdf",
                },
                api_editor.editor_api_analyze_template,
            )
        self.assertEqual(response.status_code, 202)
        body = response.get_json()
        self.assertIn("/al/editor/api/template/analyze/jobs/", body["job_url"])
        self.assertEqual(
            mock_send.call_args.kwargs["kwargs"]["template_filename"], "affidavit.pdf"
        )

    def test_applying_against_a_changed_interview_is_a_conflict(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor, "playground_read_yaml", return_value="---\nobjects: {}\n"
            ),
            patch.object(api_editor, "source_revision", return_value="now"),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/template/apply",
                method="POST",
                json={
                    "project": "Eviction",
                    "filename": "main.yml",
                    "expected_revision": "then",
                    "blocks": ["objects:\n  - affidavit: ALDocument.using()"],
                },
            ):
                response = api_editor.editor_api_apply_template_analysis()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "revision_conflict")


class TestEditorApplyBlockIds(unittest.TestCase):
    """One colliding screen id must not throw away the whole apply."""

    def test_a_colliding_id_is_numbered_rather_than_refused(self):
        taken = {"user name", "user name 2"}
        block, block_id = api_editor._block_id_without_collision(
            "id: user name\nquestion: |\n  What is your name?\n", taken
        )
        self.assertEqual(block_id, "user name 3")
        self.assertIn("id: user name 3\n", block)
        self.assertIn("question: |\n", block)

    def test_an_id_nothing_else_uses_is_left_exactly_as_it_is(self):
        block, block_id = api_editor._block_id_without_collision(
            "id: rent\nquestion: |\n  Rent\n", {"user name"}
        )
        self.assertEqual(block_id, "rent")
        self.assertEqual(block, "id: rent\nquestion: |\n  Rent\n")

    def test_a_block_with_no_id_is_left_alone(self):
        block, block_id = api_editor._block_id_without_collision(
            "objects:\n  - affidavit: ALDocument.using()\n", {"user name"}
        )
        self.assertIsNone(block_id)
        self.assertEqual(block, "objects:\n  - affidavit: ALDocument.using()\n")


class TestEditorDocumentsApi(unittest.TestCase):
    """Rearranging the documents an interview assembles."""

    def test_it_lists_the_documents_and_their_bundle_order(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor,
                "playground_read_yaml",
                return_value=INTERVIEW_WITH_TWO_DOCUMENTS,
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/documents?project=Eviction&filename=main.yml"
            ):
                response = api_editor.editor_api_documents()
        data = response.get_json()["data"]
        self.assertEqual(
            [document["name"] for document in data["documents"]],
            ["petition", "affidavit"],
        )
        self.assertEqual(data["bundles"][0]["elements"], ["petition", "affidavit"])

    def _save(self, payload):
        written = {}
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(
                api_editor,
                "playground_read_yaml",
                return_value=INTERVIEW_WITH_TWO_DOCUMENTS,
            ),
            patch.object(api_editor, "playground_write_yaml") as mock_write,
        ):
            mock_write.side_effect = (
                lambda uid, project, filename, content: written.update(
                    {"content": content}
                )
            )
            with api_editor.app.test_request_context(
                "/al/editor/api/documents", method="POST", json=payload
            ):
                response = api_editor.editor_api_save_documents()
        return response, written.get("content", "")

    def test_reordering_a_bundle_is_written_back(self):
        response, content = self._save(
            {
                "project": "Eviction",
                "filename": "main.yml",
                "expected_revision": "test-revision",
                "bundles": [
                    {
                        "bundle": "al_user_bundle",
                        "elements": ["affidavit", "petition"],
                    }
                ],
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("elements=[affidavit, petition]", content)

    def test_an_enabled_rule_is_written_into_the_declaration(self):
        response, content = self._save(
            {
                "project": "Eviction",
                "filename": "main.yml",
                "expected_revision": "test-revision",
                "enabled": [{"name": "affidavit", "expression": "user_is_low_income"}],
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("enabled=user_is_low_income", content)
        self.assertIn(
            '- petition: ALDocument.using(filename="petition", enabled=True)', content
        )

    def test_a_rule_that_is_not_an_expression_is_refused(self):
        response, content = self._save(
            {
                "project": "Eviction",
                "filename": "main.yml",
                "expected_revision": "test-revision",
                "enabled": [{"name": "affidavit", "expression": "if x: y"}],
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(content, "")

    def test_a_stale_revision_is_a_conflict(self):
        response, content = self._save(
            {
                "project": "Eviction",
                "filename": "main.yml",
                "expected_revision": "stale",
                "bundles": [{"bundle": "al_user_bundle", "elements": ["affidavit"]}],
            }
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(content, "")


class TestEditorStyleCheckSeverity(unittest.TestCase):
    def test_style_findings_never_report_as_errors(self):
        demoted = api_editor._demote_style_findings(
            [
                {
                    "rule_id": "missing-metadata-fields",
                    "level": "error",
                    "severity": "error",
                    "message": "x",
                },
                {
                    "rule_id": "vague-button",
                    "level": "warning",
                    "severity": "warning",
                    "message": "y",
                },
                {
                    "rule_id": "prefer-person-objects",
                    "level": "info",
                    "severity": "info",
                    "message": "z",
                },
            ]
        )
        self.assertEqual(
            [item["level"] for item in demoted], ["warning", "warning", "info"]
        )
        self.assertEqual(
            [item["severity"] for item in demoted], ["warning", "warning", "info"]
        )
        self.assertEqual(demoted[0]["style_original_level"], "error")
        self.assertNotIn("style_original_level", demoted[1])


class TestEditorListTopics(unittest.TestCase):
    """The picker offers the same codes the question-driven Weaver offers."""

    def test_taxonomy_is_grouped_with_the_heading_code_first(self):
        groups = api_editor._list_topic_groups()
        self.assertTrue(groups)

        by_label = {group["label"]: group for group in groups}
        self.assertIn("Housing", by_label)
        housing = by_label["Housing"]
        # A group leads with its own broadest code.
        self.assertEqual(housing["topics"][0]["code"], "HO-00-00-00-00")
        self.assertTrue(housing["topics"][0]["heading"])
        codes = [topic["code"] for topic in housing["topics"]]
        self.assertIn("HO-05-00-00-00", codes)
        self.assertEqual(len(codes), len(set(codes)))
        for topic in housing["topics"]:
            self.assertTrue(topic["label"])

        # Relevance order, the same custom order get_LIST_codes applies.
        self.assertEqual(groups[0]["label"], "Housing")

    def test_endpoint_returns_the_groups_to_an_authenticated_developer(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            api_editor.app.test_request_context("/al/editor/api/list-topics"),
        ):
            payload = api_editor.editor_api_list_topics().get_json()

        self.assertTrue(payload["success"])
        self.assertTrue(payload["data"]["groups"])
        self.assertEqual(payload["data"]["docs_url"], "https://taxonomy.legal")

    def test_endpoint_refuses_an_unauthenticated_request(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=False),
            api_editor.app.test_request_context("/al/editor/api/list-topics"),
        ):
            response = api_editor.editor_api_list_topics()

        status = response[1] if isinstance(response, tuple) else response.status_code
        self.assertEqual(status, 401)


class TestEditorBlockPayloadValidation(unittest.TestCase):
    """What the "Add a block" modal hands the API has to be accepted."""

    def accepts(self, block_yaml):
        api_editor._validate_block_yaml_payload(block_yaml)

    def test_a_standalone_comment_block_is_a_real_block(self):
        # Prose about the interview. docassemble reads it, the checker passes
        # it, and the modal offers it — so the API cannot refuse it.
        self.accepts("comment: |\n  Explain what the blocks below do.\n")

    def test_a_blank_new_block_of_only_yaml_comments_is_allowed(self):
        # What "Raw YAML block" inserts, before anything is typed over it.
        self.accepts("# replace with any docassemble YAML\n")
        self.accepts("# one\n\n# two\n")

    def test_an_id_with_nothing_to_name_is_refused(self):
        for payload in ("id: c1\n", "id: c1\ncomment: |\n  Just prose.\n"):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    self.accepts(payload)

    def test_a_document_that_is_not_a_block_is_still_refused(self):
        for payload in ("- one\n- two\n", "just a string\n", "{}\n"):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.accepts(payload)


if __name__ == "__main__":
    unittest.main()

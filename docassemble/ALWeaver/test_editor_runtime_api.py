# do not pre-load

import json
import unittest
from unittest.mock import patch

from .docassemble_compat import TargetActionResult, TargetSession
from .runtime_sessions import (
    create_runtime_record,
    delete_runtime_record,
    load_runtime_record,
    playground_yaml_filename,
    store_runtime_record,
)
from .test_editor_api import api_editor


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.expiry = ex

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


class TestEditorRuntimeApi(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()

    def _record(self, owner=7):
        target = TargetSession("docassemble.playground7:main.yml", "raw-target-id")
        record = create_runtime_record(
            weaver_session_id="weaver-session",
            owner_user_id=owner,
            project="default",
            filename="main.yml",
            yaml_filename=target.yaml_filename,
            target=target,
        )
        store_runtime_record(self.redis, record)
        return record

    def _base_patches(self, user_id=7):
        return (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_runtime_inspector_enabled", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=user_id),
            patch.object(api_editor, "r", self.redis),
        )

    def test_runtime_records_are_owner_scoped_and_publicly_redacted(self):
        self.assertEqual(
            playground_yaml_filename(12, "Housing", "main.yml"),
            "docassemble.playground12Housing:main.yml",
        )
        target = TargetSession("docassemble.playground12:main.yml", "raw-da-id")
        record = create_runtime_record(
            weaver_session_id="weaver-id",
            owner_user_id=12,
            project="default",
            filename="main.yml",
            yaml_filename=target.yaml_filename,
            target=target,
        )
        store_runtime_record(self.redis, record)

        self.assertIsNone(load_runtime_record(self.redis, "weaver-id", 99))
        owned = load_runtime_record(self.redis, "weaver-id", 12)
        public = owned.public_dict("/interview?opaque")
        self.assertNotIn("docassemble_session_id", public)
        self.assertNotIn("raw-da-id", json.dumps(public))
        self.assertTrue(delete_runtime_record(self.redis, "weaver-id", 12))

    def test_create_session_uses_owned_playground_file_and_returns_weaver_id(self):
        target = TargetSession("docassemble.playground7:main.yml", "raw-target-id")
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(
                api_editor, "playground_read_yaml", return_value="id: intro\n"
            ),
            patch.object(
                api_editor, "create_target_session", return_value=target
            ) as create,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions",
                method="POST",
                json={"project": "default", "filename": "main.yml"},
            ):
                response = api_editor.editor_api_runtime_create_session()

        self.assertEqual(response.status_code, 201)
        data = response.get_json()["data"]
        self.assertIn("weaver_session_id", data)
        self.assertNotIn("docassemble_session_id", data)
        create.assert_called_once_with(
            "docassemble.playground7:main.yml", secret=None, url_args=None
        )

    def test_variable_read_filters_internal_values_by_default(self):
        self._record()
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(
                api_editor,
                "get_target_variables",
                return_value={"answer": 42, "_internal": {"secret": "hidden"}},
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/variables"
            ):
                response = api_editor.editor_api_runtime_variables("weaver-session")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["variables"], {"answer": 42})
        self.assertEqual(data["fact_source"], "observed_runtime")

    def test_variable_write_never_processes_objects(self):
        self._record()
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(api_editor, "set_target_variables") as set_variables,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/variables",
                method="POST",
                json={"variables": {"status": "ready"}, "delete": ["old_value"]},
            ):
                response = api_editor.editor_api_runtime_variables("weaver-session")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(set_variables.call_args.kwargs["process_objects"])

    def test_arbitrary_actions_are_rejected(self):
        self._record()
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(api_editor, "run_target_action_raw") as run_action,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/actions/not_allowed",
                method="POST",
                json={},
            ):
                response = api_editor.editor_api_runtime_action(
                    "weaver-session", "not_allowed"
                )
        self.assertEqual(response.status_code, 403)
        run_action.assert_not_called()

    def test_allowlisted_actions_are_always_read_only(self):
        self._record()
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(
                api_editor,
                "run_target_action_raw",
                return_value=TargetActionResult(status="success", data={"value": 1}),
            ) as run_action,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/actions/al_weaver.inspect_variable",
                method="POST",
                json={"arguments": {"name": "answer"}},
            ):
                response = api_editor.editor_api_runtime_action(
                    "weaver-session", "al_weaver.inspect_variable"
                )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(run_action.call_args.kwargs["read_only"])


if __name__ == "__main__":
    unittest.main()

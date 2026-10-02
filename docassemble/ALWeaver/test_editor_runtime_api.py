# do not pre-load

import json
import unittest
from datetime import timedelta
from unittest.mock import patch

from .docassemble_compat import TargetActionResult, TargetSession
from .runtime_sessions import (
    RUNTIME_SESSION_KEY_PREFIX,
    RUNTIME_SESSION_EXPIRE_SECONDS,
    create_runtime_record,
    delete_runtime_record,
    load_runtime_record,
    playground_yaml_filename,
    store_runtime_record,
)
from .test_editor_api import api_editor
from .test_editor_api import _TestRedisLock
from . import runtime_sessions, worker_config


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.sorted_sets = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expiry = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)

    def lock(self, name, **kwargs):
        return _TestRedisLock(name)

    def scan_iter(self, match, count=100):
        import fnmatch

        return iter([key for key in self.values if fnmatch.fnmatch(key, match)])

    def zadd(self, key, values):
        self.sorted_sets.setdefault(key, {}).update(values)

    def zrem(self, key, member):
        self.sorted_sets.get(key, {}).pop(member, None)

    def zrangebyscore(self, key, minimum, maximum, start=0, num=20):
        return [
            member
            for member, score in sorted(
                self.sorted_sets.get(key, {}).items(), key=lambda item: item[1]
            )
            if score <= maximum
        ][start : start + num]


class TestEditorRuntimeApi(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.revision = self.enterContext(
            patch.object(
                runtime_sessions,
                "get_target_session_revision",
                return_value=(1, runtime_sessions.utc_now()),
            )
        )
        self.delete_target = self.enterContext(
            patch.object(runtime_sessions, "delete_target_session")
        )

    def _record(self, owner=7, session_id="weaver-session"):
        target = TargetSession(
            f"docassemble.playground{owner}:main.yml", session_id + "-target"
        )
        record = create_runtime_record(
            weaver_session_id=session_id,
            owner_user_id=owner,
            project="default",
            filename="main.yml",
            yaml_filename=target.yaml_filename,
            target=target,
        )
        record.progress_revision = 1
        store_runtime_record(self.redis, record)
        return record

    def _base_patches(self, user_id=7):
        return (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_runtime_inspector_enabled", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=user_id),
            patch.object(api_editor, "r", self.redis),
        )

    def test_snapshot_combines_reads_without_history_writes(self):
        self._record()
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(self.redis, "set", wraps=self.redis.set) as store,
            patch.object(
                api_editor,
                "get_target_question",
                return_value={"questionName": "intro"},
            ) as question,
            patch.object(
                api_editor,
                "get_target_variables",
                return_value={"answer": 1, "_internal": {}},
            ) as variables,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/snapshot"
            ):
                response = api_editor.editor_api_runtime_variables("weaver-session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["data"]["question"], {"questionName": "intro"}
        )
        self.assertEqual(response.get_json()["data"]["variables"], {"answer": 1})
        question.assert_called_once()
        variables.assert_called_once()
        store.assert_not_called()

    def test_polling_and_refresh_do_not_extend_idle_deadline(self):
        from datetime import timedelta
        from .runtime_sessions import utc_now

        record = self._record()
        record.last_accessed_at = utc_now() - timedelta(seconds=61)
        store_runtime_record(self.redis, record)
        with patch.object(self.redis, "set", wraps=self.redis.set) as store:
            load_runtime_record(self.redis, "weaver-session", 7)
            load_runtime_record(self.redis, "weaver-session", 7)
        store.assert_not_called()
        self.assertEqual(
            runtime_sessions.deadline(record),
            runtime_sessions.deadline(
                load_runtime_record(self.redis, "weaver-session", 7)
            ),
        )
        self.assertIsNone(self.redis.expiry)

    def test_refresh_reconnects_to_existing_session_without_creating_one(self):
        record = self._record()
        with (
            self._base_context(),
            patch.object(api_editor, "playground_read_yaml"),
            patch.object(api_editor, "create_target_session") as create,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions?project=default&filename=main.yml"
            ):
                response = api_editor.editor_api_runtime_create_session()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["data"]["session"]["weaver_session_id"],
            record.weaver_session_id,
        )
        create.assert_not_called()
        self.delete_target.assert_not_called()

    def _base_context(self, user_id=7):
        from contextlib import ExitStack

        stack = ExitStack()
        for patcher in self._base_patches(user_id):
            stack.enter_context(patcher)
        return stack

    def test_end_deletes_docassemble_data_and_cleanup_indexes(self):
        record = self._record()
        self.redis.set(
            runtime_sessions.RUNTIME_SESSION_OWNER_PREFIX + "7",
            record.weaver_session_id,
        )
        with (
            self._base_context(),
            api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session", method="DELETE"
            ),
        ):
            response = api_editor.editor_api_runtime_session(record.weaver_session_id)
        self.assertEqual(response.status_code, 200)
        self.delete_target.assert_called_once_with(
            TargetSession(record.yaml_filename, record.docassemble_session_id), 7
        )
        self.assertEqual(self.redis.values, {})
        self.assertEqual(
            self.redis.sorted_sets[runtime_sessions.RUNTIME_SESSION_DUE_KEY], {}
        )

    def test_idle_session_is_deleted_even_when_browser_keeps_polling(self):
        record = self._record()
        record.last_progress_at = runtime_sessions.utc_now() - timedelta(minutes=31)
        store_runtime_record(self.redis, record)
        with (
            self._base_context(),
            api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/snapshot"
            ),
        ):
            response = api_editor.editor_api_runtime_variables(record.weaver_session_id)
        self.assertEqual(response.status_code, 404)
        self.delete_target.assert_called_once()
        self.assertIsNone(load_runtime_record(self.redis, record.weaver_session_id, 7))

    def test_screen_progress_postpones_idle_cleanup_without_browser_secret(self):
        record = self._record()
        record.last_progress_at = runtime_sessions.utc_now() - timedelta(minutes=31)
        store_runtime_record(self.redis, record)
        changed = runtime_sessions.utc_now() - timedelta(minutes=2)
        self.revision.return_value = (2, changed.replace(tzinfo=None))
        self.assertEqual(runtime_sessions.cleanup_due_runtime_sessions(self.redis), 0)
        live = load_runtime_record(self.redis, record.weaver_session_id, 7)
        self.assertEqual(live.last_progress_at, changed)
        self.assertEqual(live.progress_revision, 2)
        self.delete_target.assert_not_called()

    def test_failed_database_deletion_keeps_record_for_retry(self):
        record = self._record()
        record.last_progress_at = runtime_sessions.utc_now() - timedelta(minutes=31)
        store_runtime_record(self.redis, record)
        self.delete_target.side_effect = RuntimeError("database unavailable")
        self.assertEqual(runtime_sessions.cleanup_due_runtime_sessions(self.redis), 0)
        self.assertIsNotNone(
            load_runtime_record(self.redis, record.weaver_session_id, 7)
        )
        self.assertIn(
            record.weaver_session_id,
            self.redis.sorted_sets[runtime_sessions.RUNTIME_SESSION_DUE_KEY],
        )
        self.delete_target.side_effect = None
        self.assertEqual(runtime_sessions.cleanup_due_runtime_sessions(self.redis), 1)
        self.assertEqual(self.redis.values, {})

    def test_failed_expiry_cleanup_returns_json_and_preserves_retry_record(self):
        record = self._record()
        record.last_progress_at = runtime_sessions.utc_now() - timedelta(minutes=31)
        store_runtime_record(self.redis, record)
        self.delete_target.side_effect = RuntimeError("database unavailable")
        with (
            self._base_context(),
            api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/snapshot"
            ),
        ):
            response = api_editor.editor_api_runtime_variables(record.weaver_session_id)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.get_json()["error"]["code"], "runtime_operation_failed"
        )
        self.assertIsNotNone(
            load_runtime_record(self.redis, record.weaver_session_id, 7)
        )

    def test_cleanup_discovers_legacy_records_and_keeps_only_latest_for_owner(self):
        old = self._record()
        old.created_at -= timedelta(minutes=10)
        store_runtime_record(self.redis, old)
        self._record(session_id="latest")
        self._record(owner=99, session_id="other-owner")
        # Simulate a pre-upgrade record without a deadline index.
        payload = json.loads(
            self.redis.get(RUNTIME_SESSION_KEY_PREFIX + old.weaver_session_id)
        )
        payload.pop("last_progress_at")
        payload.pop("progress_revision")
        self.redis.set(
            RUNTIME_SESSION_KEY_PREFIX + old.weaver_session_id, json.dumps(payload)
        )
        self.redis.zrem(runtime_sessions.RUNTIME_SESSION_DUE_KEY, old.weaver_session_id)
        result = runtime_sessions.cleanup_owned_runtime_sessions(self.redis, 7)
        self.assertEqual(result["session"].weaver_session_id, "latest")
        self.assertEqual(result["deleted"], 1)
        self.delete_target.assert_called_once_with(
            TargetSession(old.yaml_filename, old.docassemble_session_id), 7
        )
        self.assertIsNotNone(load_runtime_record(self.redis, "other-owner", 99))

    def test_cleanup_refuses_records_pointing_to_ordinary_interviews(self):
        record = self._record()
        record.yaml_filename = "docassemble.RealClientInterview:main.yml"
        store_runtime_record(self.redis, record)
        with self.assertRaises(ValueError):
            runtime_sessions.cleanup_owned_runtime_sessions(self.redis, 7)
        self.delete_target.assert_not_called()

    def test_refresh_queues_only_one_worker_cleanup_task(self):
        from unittest.mock import Mock

        worker = Mock()
        record = self._record()
        with (
            patch.object(
                worker_config,
                "worker_configuration_is_ready",
                return_value=True,
            ),
            patch.object(runtime_sessions, "get_worker_app", return_value=worker),
        ):
            for _ in range(5):
                runtime_sessions.schedule_runtime_cleanup(self.redis, record)
        worker.send_task.assert_called_once()
        kwargs = worker.send_task.call_args.kwargs
        self.assertEqual(
            kwargs["kwargs"],
            {"session_id": record.weaver_session_id, "owner_user_id": 7},
        )
        self.assertLessEqual(kwargs["countdown"], 300)

    def test_failed_task_enqueue_can_be_retried_without_losing_record(self):
        from unittest.mock import Mock

        worker = Mock()
        record = self._record()
        with (
            patch.object(
                worker_config,
                "worker_configuration_is_ready",
                return_value=True,
            ),
            patch.object(runtime_sessions, "get_worker_app", return_value=worker),
        ):
            worker.send_task.side_effect = RuntimeError("broker unavailable")
            runtime_sessions.schedule_runtime_cleanup(self.redis, record)
            worker.send_task.side_effect = None
            runtime_sessions.schedule_runtime_cleanup(self.redis, record)
        self.assertEqual(worker.send_task.call_count, 2)
        self.assertIsNotNone(
            load_runtime_record(self.redis, record.weaver_session_id, 7)
        )

    def test_starting_replacement_deletes_old_session_and_preserves_other_owners(self):
        old = self._record()
        self._record(owner=99, session_id="other-owner")
        with (
            self._base_context(),
            patch.object(api_editor, "playground_read_yaml"),
            patch.object(
                api_editor,
                "create_target_session",
                return_value=TargetSession(old.yaml_filename, "new-debug-target"),
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions",
                method="POST",
                json={"project": "default", "filename": "main.yml"},
            ):
                response = api_editor.editor_api_runtime_create_session()
        self.assertEqual(response.status_code, 201)
        self.delete_target.assert_called_once_with(
            TargetSession(old.yaml_filename, old.docassemble_session_id), 7
        )
        self.assertIsNone(load_runtime_record(self.redis, old.weaver_session_id, 7))
        self.assertIsNotNone(load_runtime_record(self.redis, "other-owner", 99))

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

    def test_missing_endpoint_returns_actionable_error_without_creating_record(self):
        class DAErrorNoEndpoint(Exception):
            pass

        direct = DAErrorNoEndpoint("private diagnostic trace")
        wrapped = RuntimeError("Docassemble API wrapper")
        wrapped.__cause__ = direct
        serialized = RuntimeError(
            "create_new_interview: failure to assemble interview: "
            "DAErrorNoEndpoint: private diagnostic trace"
        )
        for failure in (direct, wrapped, serialized):
            with self.subTest(failure=type(failure).__name__):
                patches = self._base_patches()
                with (
                    patches[0],
                    patches[1],
                    patches[2],
                    patches[3],
                    patch.object(api_editor, "playground_read_yaml", return_value=""),
                    patch.object(
                        api_editor, "create_target_session", side_effect=failure
                    ),
                ):
                    with api_editor.app.test_request_context(
                        "/al/editor/api/runtime/sessions",
                        method="POST",
                        json={"project": "default", "filename": "include.yml"},
                    ):
                        response = api_editor.editor_api_runtime_create_session()
                self.assertEqual(response.status_code, 422)
                error = response.get_json()["error"]
                self.assertEqual(error["code"], "runtime_no_endpoint")
                self.assertIn("include.yml", error["message"])
                self.assertIn("main interview", error["message"])
                self.assertNotIn("private diagnostic trace", json.dumps(error))
                self.assertEqual(self.redis.values, {})

    def test_other_startup_errors_keep_generic_response(self):
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(api_editor, "playground_read_yaml", return_value=""),
            patch.object(
                api_editor,
                "create_target_session",
                side_effect=RuntimeError("private unrelated startup failure"),
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions",
                method="POST",
                json={"project": "default", "filename": "main.yml"},
            ):
                response = api_editor.editor_api_runtime_create_session()
        self.assertEqual(response.status_code, 500)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "runtime_session_creation_failed")
        self.assertNotIn("private unrelated startup failure", json.dumps(error))

    def test_runtime_inspector_disabled_is_a_feature_disabled_404(self):
        patches = self._base_patches()
        with (
            patches[0],
            patch.object(api_editor, "_runtime_inspector_enabled", return_value=False),
            patches[2],
            patches[3],
            patch.object(api_editor, "playground_read_yaml") as read_yaml,
            patch.object(api_editor, "create_target_session") as create_target,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions",
                method="POST",
                json={"project": "default", "filename": "main.yml"},
            ):
                response = api_editor.editor_api_runtime_create_session()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json()["error"]["code"], "runtime_inspector_disabled"
        )
        read_yaml.assert_not_called()
        create_target.assert_not_called()

    def test_other_user_cannot_inspect_or_seed_runtime_session(self):
        self._record(owner=7)
        patches = self._base_patches(user_id=99)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(api_editor, "get_target_variables") as get_variables,
            patch.object(api_editor, "set_target_variables") as set_variables,
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/variables"
            ):
                response = api_editor.editor_api_runtime_variables("weaver-session")

            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session/variables",
                method="POST",
                json={"variables": {"canary": "must not be seeded"}},
            ):
                seed_response = api_editor.editor_api_runtime_variables(
                    "weaver-session"
                )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(seed_response.status_code, 404)
        self.assertEqual(
            response.get_json()["error"]["code"], "runtime_session_not_found"
        )
        self.assertEqual(
            seed_response.get_json()["error"]["code"], "runtime_session_not_found"
        )
        self.assertNotIn("must not be seeded", json.dumps(seed_response.get_json()))
        get_variables.assert_not_called()
        set_variables.assert_not_called()

    def test_expired_runtime_record_resolves_to_not_found(self):
        self._record()
        self.assertIsNone(self.redis.expiry)
        # A successfully cleaned-up record is no longer addressable.
        self.redis.delete(RUNTIME_SESSION_KEY_PREFIX + "weaver-session")
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions/weaver-session", method="GET"
            ):
                response = api_editor.editor_api_runtime_session("weaver-session")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json()["error"]["code"], "runtime_session_not_found"
        )

    def test_fresh_browser_receives_the_key_used_for_its_target_session(self):
        target = TargetSession(
            "docassemble.playground7:main.yml",
            "raw-target-id",
            secret="generated-browser-key",
        )
        patches = self._base_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patch.object(
                api_editor, "playground_read_yaml", return_value="id: intro\n"
            ),
            patch.object(api_editor, "bump_interview_source_index"),
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
        set_cookie_headers = response.headers.getlist("Set-Cookie")
        self.assertEqual(len(set_cookie_headers), 1)
        self.assertTrue(
            set_cookie_headers[0].startswith("secret=generated-browser-key;")
        )
        self.assertIn("HttpOnly", set_cookie_headers[0])
        self.assertIn("Path=/", set_cookie_headers[0])
        self.assertNotIn("generated-browser-key", json.dumps(response.get_json()))
        stored = json.loads(
            self.redis.get(
                RUNTIME_SESSION_KEY_PREFIX
                + response.get_json()["data"]["weaver_session_id"]
            )
        )
        self.assertEqual(stored["encrypted_secret"], "generated-browser-key")
        create.assert_called_once_with(
            "docassemble.playground7:main.yml", secret=None, url_args=None
        )

    def test_the_debuggers_iframe_can_decrypt_the_session_weaver_created(self):
        """Docassemble decrypts a session only with the visitor's own cookie.

        A target session encrypted with any other key makes ``/interview``
        discard it and start a different one, so the iframe would show a
        session the debugger panels are not describing.
        """
        target = TargetSession(
            "docassemble.playground7:main.yml", "raw-target-id", secret="browser-key"
        )
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
                headers={"Cookie": "secret=browser-key"},
            ):
                response = api_editor.editor_api_runtime_create_session()

        self.assertEqual(response.status_code, 201)
        create.assert_called_once_with(
            "docassemble.playground7:main.yml",
            secret="browser-key",
            url_args=None,
        )
        stored = json.loads(
            self.redis.get(
                RUNTIME_SESSION_KEY_PREFIX
                + response.get_json()["data"]["weaver_session_id"]
            )
        )
        self.assertTrue(stored["encrypted"])
        # The developer's key decrypts every session they own; the browser
        # sends it on each request, so Weaver never keeps a copy.
        self.assertIsNone(stored["encrypted_secret"])
        self.assertNotIn("browser-key", json.dumps(stored))

    def test_variable_read_filters_internal_values_by_default(self):
        record = self._record()
        record.seeded_variables = ["answer"]
        store_runtime_record(self.redis, record)
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
        self.assertEqual(data["seeded_variables"], ["answer"])
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
        stored = json.loads(
            self.redis.get(RUNTIME_SESSION_KEY_PREFIX + "weaver-session")
        )
        self.assertEqual(stored["seeded_variables"], ["status"])
        scenario_events = [
            item for item in stored["history"] if item["event"] == "scenario_applied"
        ]
        self.assertEqual(scenario_events[-1]["seeded_variables"], ["status"])
        self.assertEqual(scenario_events[-1]["deleted_variables"], ["old_value"])

    def test_invalid_scenario_yaml_is_a_validation_error_without_mutation(self):
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
                json={"scenario_yaml": "[malformed"},
            ):
                response = api_editor.editor_api_runtime_variables("weaver-session")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json()["error"]["code"], "invalid_runtime_variable_request"
        )
        set_variables.assert_not_called()

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

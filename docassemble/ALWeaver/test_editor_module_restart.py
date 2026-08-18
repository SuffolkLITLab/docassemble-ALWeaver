# do not pre-load

"""Saving Playground Python modules, and the deferred restart that loads them."""

import json
import os
import tempfile
import types
import unittest
from unittest.mock import patch

from .editor_modules import (
    ModuleSyntaxError,
    check_module_syntax,
    clear_modules_dirty,
    mark_modules_dirty,
    module_package_directory,
    normalize_restart_policy,
    publish_module_source,
    read_modules_dirty,
    unpublish_module,
    validate_module_filename,
)
from .test_editor_api import api_editor


class FakeRedis:
    """Enough Redis for the dirty flag and the restart-status record."""

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)

    def pipeline(self):
        store = self.values

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


class TestModuleFilenames(unittest.TestCase):
    def test_names_docassemble_would_never_import_are_refused(self):
        # copy_playground_modules only copies files matching ^[A-Za-z].*\.py$,
        # so these would be saved and then silently never loaded.
        for bad in ("_helpers.py", "2col.py", ".hidden.py", "util", "util.txt"):
            with self.subTest(filename=bad):
                with self.assertRaises(ValueError):
                    validate_module_filename(bad)

    def test_ordinary_module_names_are_accepted(self):
        for good in ("util.py", "custom_fields.py", "Housing2.py"):
            with self.subTest(filename=good):
                validate_module_filename(good)


class TestModuleSyntaxCheck(unittest.TestCase):
    def test_a_syntax_error_reports_where_it_is(self):
        with self.assertRaises(ModuleSyntaxError) as caught:
            check_module_syntax("util.py", "def broken(:\n    pass\n")
        self.assertEqual(caught.exception.filename, "util.py")
        self.assertEqual(caught.exception.line, 1)
        self.assertIn("util.py", str(caught.exception))

    def test_source_that_compiles_passes(self):
        check_module_syntax("util.py", "def fine():\n    return 1\n")

    def test_a_module_that_compiles_but_would_fail_on_import_is_not_run(self):
        # Importing to find this would mean executing the developer's code in
        # the request handler, which is exactly what the compile check avoids.
        check_module_syntax("util.py", "raise RuntimeError('boom')\n")


class TestPublishingModules(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def _publish(self, filename, content, project="default"):
        return publish_module_source(
            package_root=self.root,
            user_id=7,
            project=project,
            filename=filename,
            content=content,
        )

    def test_a_new_module_goes_live_without_a_restart(self):
        # Nothing can be holding it in sys.modules, so copying it across is
        # enough.
        self.assertEqual(self._publish("util.py", "X = 1\n"), "live")
        installed = os.path.join(
            module_package_directory(self.root, 7, "default"), "util.py"
        )
        with open(installed, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "X = 1\n")

    def test_overwriting_an_installed_module_needs_a_restart(self):
        self._publish("util.py", "X = 1\n")
        self.assertEqual(self._publish("util.py", "X = 2\n"), "restart_required")

    def test_named_projects_get_their_own_package_directory(self):
        self._publish("util.py", "X = 1\n", project="Housing")
        self.assertTrue(
            module_package_directory(self.root, 7, "Housing").endswith(
                os.path.join("docassemble", "playground7Housing")
            )
        )

    def test_a_server_without_a_writable_package_root_reports_unavailable(self):
        self.assertEqual(
            publish_module_source(
                package_root=None,
                user_id=7,
                project="default",
                filename="util.py",
                content="X = 1\n",
            ),
            "unavailable",
        )

    def test_no_partially_written_module_is_ever_visible(self):
        self._publish("util.py", "X = 1\n")
        target_dir = module_package_directory(self.root, 7, "default")
        # Only the finished file, never the staging name, is left behind.
        self.assertEqual(sorted(os.listdir(target_dir)), ["util.py"])

    def test_unpublishing_reports_whether_the_module_was_installed(self):
        self._publish("util.py", "X = 1\n")
        self.assertTrue(
            unpublish_module(
                package_root=self.root, user_id=7, project="default", filename="util.py"
            )
        )
        self.assertFalse(
            unpublish_module(
                package_root=self.root, user_id=7, project="default", filename="util.py"
            )
        )


class TestPendingRestartState(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()

    def test_marked_changes_are_read_back_once_per_file(self):
        mark_modules_dirty(self.redis, 7, "default", "util.py", server_start_time=100.0)
        mark_modules_dirty(self.redis, 7, "default", "util.py", server_start_time=100.0)
        mark_modules_dirty(
            self.redis, 7, "default", "other.py", server_start_time=100.0
        )
        state = read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        self.assertEqual(
            [entry["filename"] for entry in state["files"]], ["other.py", "util.py"]
        )

    def test_a_restart_from_anywhere_clears_the_flag(self):
        # The stock Playground, a package install, or our own restart all move
        # START_TIME forward, and any of them loads the module.
        mark_modules_dirty(self.redis, 7, "default", "util.py", server_start_time=100.0)
        self.assertIsNone(
            read_modules_dirty(self.redis, 7, "default", server_start_time=200.0)
        )

    def test_projects_do_not_share_a_flag(self):
        mark_modules_dirty(self.redis, 7, "Housing", "util.py", server_start_time=100.0)
        self.assertIsNone(
            read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        )

    def test_clearing_removes_the_flag(self):
        mark_modules_dirty(self.redis, 7, "default", "util.py", server_start_time=100.0)
        clear_modules_dirty(self.redis, 7, "default")
        self.assertIsNone(
            read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        )

    def test_unreadable_state_is_treated_as_nothing_pending(self):
        self.redis.values["da:weaver:modules_dirty:7:default"] = b"not json"
        self.assertIsNone(
            read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        )


class TestRestartPolicy(unittest.TestCase):
    def test_the_default_is_to_ask_first(self):
        for raw in (None, "", "nonsense"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_restart_policy(raw), "prompt")

    def test_the_configured_spellings_are_accepted(self):
        self.assertEqual(normalize_restart_policy("auto"), "auto")
        self.assertEqual(normalize_restart_policy("Never"), "never")
        self.assertEqual(normalize_restart_policy("always"), "auto")
        self.assertEqual(normalize_restart_policy("off"), "never")


class TestModuleSaveApi(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.storage = tempfile.mkdtemp()
        self.package_root = tempfile.mkdtemp()
        self.area = types.SimpleNamespace(finalize=lambda: None)

    def _save(self, payload):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "r", self.redis),
            patch.object(
                api_editor,
                "_editor_storage_directory",
                return_value=(self.area, self.storage),
            ),
            patch.object(
                api_editor, "full_package_directory", return_value=self.package_root
            ),
            patch.object(api_editor, "server_start_time", return_value=100.0),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/section-file", method="POST", json=payload
            ):
                return api_editor.editor_api_save_section_file()

    def test_a_new_module_is_saved_and_reported_live(self):
        response = self._save(
            {
                "project": "default",
                "section": "modules",
                "filename": "util.py",
                "content": "X = 1\n",
            }
        )
        data = response.get_json()["data"]
        self.assertEqual(data["module"]["status"], "live")
        self.assertFalse(data["module"]["restart_required"])
        self.assertFalse(data["restart_state"]["pending"])

    def test_changing_an_installed_module_marks_the_project_for_restart(self):
        payload = {
            "project": "default",
            "section": "modules",
            "filename": "util.py",
            "content": "X = 1\n",
        }
        self._save(payload)
        payload["content"] = "X = 2\n"
        data = self._save(payload).get_json()["data"]
        self.assertTrue(data["module"]["restart_required"])
        self.assertTrue(data["restart_state"]["pending"])
        self.assertEqual(
            [entry["filename"] for entry in data["restart_state"]["files"]], ["util.py"]
        )

    def test_a_module_that_does_not_compile_is_refused_and_not_written(self):
        response = self._save(
            {
                "project": "default",
                "section": "modules",
                "filename": "util.py",
                "content": "def broken(:\n",
            }
        )
        self.assertEqual(response.status_code, 400)
        error = response.get_json()["error"]
        self.assertEqual(error["type"], "module_syntax_error")
        self.assertEqual(error["line"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.storage, "util.py")))

    def test_forcing_keeps_unfinished_work_without_installing_it(self):
        response = self._save(
            {
                "project": "default",
                "section": "modules",
                "filename": "util.py",
                "content": "def broken(:\n",
                "force": True,
            }
        )
        data = response.get_json()["data"]
        self.assertEqual(data["module"]["status"], "not_published")
        self.assertTrue(os.path.exists(os.path.join(self.storage, "util.py")))
        self.assertFalse(
            os.path.exists(
                os.path.join(self.package_root, "docassemble", "playground7", "util.py")
            )
        )

    def test_a_module_name_docassemble_would_skip_is_refused(self):
        response = self._save(
            {
                "project": "default",
                "section": "modules",
                "filename": "_helpers.py",
                "content": "X = 1\n",
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("but never loaded", response.get_json()["error"]["message"])

    def test_other_sections_are_untouched_by_any_of_this(self):
        response = self._save(
            {
                "project": "default",
                "section": "templates",
                "filename": "_notes.txt",
                "content": "hello\n",
            }
        )
        data = response.get_json()["data"]
        self.assertNotIn("module", data)
        self.assertNotIn("restart_state", data)


class TestBulkModuleWrites(unittest.TestCase):
    """Paths that replace module files without going through a save."""

    def setUp(self):
        self.redis = FakeRedis()
        self.storage = tempfile.mkdtemp()
        self.package_root = tempfile.mkdtemp()
        self.area = types.SimpleNamespace(finalize=lambda: None)

    def _write(self, filename, content):
        with open(os.path.join(self.storage, filename), "w", encoding="utf-8") as fh:
            fh.write(content)

    def _installed(self, filename):
        return os.path.join(self.package_root, "docassemble", "playground7", filename)

    def _patched(self):
        return (
            patch.object(api_editor, "r", self.redis),
            patch.object(
                api_editor,
                "_editor_storage_directory",
                return_value=(self.area, self.storage),
            ),
            patch.object(
                api_editor, "full_package_directory", return_value=self.package_root
            ),
            patch.object(api_editor, "server_start_time", return_value=100.0),
        )

    def _reconcile(self):
        redis_patch, storage_patch, root_patch, time_patch = self._patched()
        with redis_patch, storage_patch, root_patch, time_patch:
            api_editor._reconcile_project_modules(7, "default")

    def test_a_pulled_module_is_installed_without_a_restart(self):
        self._write("util.py", "X = 1\n")
        self._reconcile()
        self.assertTrue(os.path.exists(self._installed("util.py")))
        self.assertIsNone(
            read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        )

    def test_a_pull_that_changes_an_installed_module_needs_a_restart(self):
        self._write("util.py", "X = 1\n")
        self._reconcile()
        self._write("util.py", "X = 2\n")
        self._reconcile()
        state = read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        self.assertEqual([entry["filename"] for entry in state["files"]], ["util.py"])

    def test_a_module_the_pull_removed_is_uninstalled_and_flagged(self):
        self._write("util.py", "X = 1\n")
        self._reconcile()
        os.remove(os.path.join(self.storage, "util.py"))
        self._reconcile()
        self.assertFalse(os.path.exists(self._installed("util.py")))
        state = read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        self.assertEqual(state["files"][0]["reason"], "deleted")

    def test_a_pulled_module_that_does_not_compile_is_not_installed(self):
        self._write("util.py", "def broken(:\n")
        self._reconcile()
        self.assertFalse(os.path.exists(self._installed("util.py")))
        self.assertIsNotNone(
            read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        )

    def test_a_name_docassemble_would_skip_is_left_alone_entirely(self):
        self._write("_helpers.py", "X = 1\n")
        self._reconcile()
        self.assertFalse(os.path.exists(self._installed("_helpers.py")))
        # Nothing to restart for: Docassemble would never have loaded it.
        self.assertIsNone(
            read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        )

    def test_reconciling_never_fails_the_operation_it_follows(self):
        with (
            patch.object(api_editor, "r", self.redis),
            patch.object(
                api_editor,
                "_editor_storage_directory",
                side_effect=SystemExit(1),
            ),
        ):
            api_editor._reconcile_project_modules(7, "default")

    def test_project_wide_replace_installs_the_module_it_rewrote(self):
        self._write("util.py", "GREETING = 'hi'\n")
        self._reconcile()
        redis_patch, storage_patch, root_patch, time_patch = self._patched()
        with redis_patch, storage_patch, root_patch, time_patch:
            api_editor._write_project_text_file(
                7, "default", "modules", "util.py", "GREETING = 'hello'\n"
            )
        with open(self._installed("util.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "GREETING = 'hello'\n")
        self.assertIsNotNone(
            read_modules_dirty(self.redis, 7, "default", server_start_time=100.0)
        )


class TestRestartApi(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()

    def _context(self, path, **kwargs):
        return api_editor.app.test_request_context(path, **kwargs)

    def test_restart_state_reports_the_policy_and_what_is_pending(self):
        mark_modules_dirty(self.redis, 7, "default", "util.py", server_start_time=100.0)
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "r", self.redis),
            patch.object(api_editor, "server_start_time", return_value=100.0),
            patch.object(api_editor, "_restarting_is_allowed", return_value=True),
            patch.object(api_editor, "_filesystem_is_read_only", return_value=False),
            patch.object(api_editor, "_module_restart_policy", return_value="prompt"),
        ):
            with self._context("/al/editor/api/server/restart-state?project=default"):
                data = api_editor.editor_api_restart_state().get_json()["data"]
        self.assertTrue(data["pending"])
        self.assertEqual(data["policy"], "prompt")
        self.assertTrue(data["restart_allowed"])
        self.assertEqual(data["disruption_seconds"], [10, 30])

    def test_a_read_only_server_explains_itself_instead_of_offering_a_restart(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "r", self.redis),
            patch.object(api_editor, "server_start_time", return_value=100.0),
            patch.object(api_editor, "_filesystem_is_read_only", return_value=True),
        ):
            with self._context("/al/editor/api/server/restart-state?project=default"):
                data = api_editor.editor_api_restart_state().get_json()["data"]
        self.assertFalse(data["restart_allowed"])
        self.assertIn("read-only", data["restart_blocked_reason"])

    def test_restarting_writes_the_polling_record_before_taking_the_server_down(self):
        order = []

        def fake_restart():
            order.append(
                "restart:" + str(sorted(k for k in self.redis.values if "restart" in k))
            )

        mark_modules_dirty(self.redis, 7, "default", "util.py", server_start_time=100.0)
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "r", self.redis),
            patch.object(api_editor, "server_start_time", return_value=100.0),
            patch.object(api_editor, "_restarting_is_allowed", return_value=True),
            patch.object(api_editor, "_filesystem_is_read_only", return_value=False),
            patch.object(api_editor, "restart_docassemble", side_effect=fake_restart),
        ):
            with self._context(
                "/al/editor/api/server/restart",
                method="POST",
                json={"project": "default"},
            ):
                payload = api_editor.editor_api_restart_server().get_json()
        task_id = payload["data"]["task_id"]
        # The record has to exist before restart_all takes down this worker,
        # or the browser has nothing left to poll.
        self.assertIn("da:restart_status:" + task_id, order[0])
        self.assertNotIn("da:weaver:modules_dirty:7:default", self.redis.values)

    def test_a_server_that_may_not_restart_refuses_with_the_reason(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "r", self.redis),
            patch.object(api_editor, "_filesystem_is_read_only", return_value=False),
            patch.object(api_editor, "_restarting_is_allowed", return_value=False),
        ):
            with self._context(
                "/al/editor/api/server/restart",
                method="POST",
                json={"project": "default"},
            ):
                response = api_editor.editor_api_restart_server()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "restart_not_allowed")

    def test_restart_status_completes_only_once_a_newer_process_answers(self):
        self.redis.values["da:restart_status:abc"] = json.dumps(
            {"server_start_time": 100.0}
        )

        def status(start_time, reset_running):
            with (
                patch.object(api_editor, "_editor_auth_check", return_value=True),
                patch.object(api_editor, "r", self.redis),
                patch.object(api_editor, "server_start_time", return_value=start_time),
                patch.object(
                    api_editor, "reset_process_is_running", return_value=reset_running
                ),
            ):
                with self._context("/al/editor/api/server/restart-status?task_id=abc"):
                    return api_editor.editor_api_restart_status().get_json()["data"][
                        "status"
                    ]

        self.assertEqual(status(100.0, False), "working")
        # A newer process is answering, but supervisor is still resetting the
        # background workers, so the restart is not finished.
        self.assertEqual(status(200.0, True), "working")
        self.assertEqual(status(200.0, False), "completed")

    def test_an_unknown_task_is_reported_rather_than_erroring(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "r", self.redis),
        ):
            with self._context("/al/editor/api/server/restart-status?task_id=gone"):
                data = api_editor.editor_api_restart_status().get_json()["data"]
        self.assertEqual(data["status"], "unknown")


class TestRuntimeSessionFreshness(unittest.TestCase):
    def test_starting_a_test_session_invalidates_the_cached_parse(self):
        # "Run the interview" reaches Docassemble with cache=0 and the server
        # bumps the index itself; the API path has to do it explicitly or the
        # inspector runs against YAML from before the last save.
        bumped = []
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_runtime_inspector_enabled", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "r", FakeRedis()),
            patch.object(api_editor, "playground_read_yaml", return_value="id: x\n"),
            patch.object(
                api_editor, "bump_interview_source_index", side_effect=bumped.append
            ),
            patch.object(
                api_editor,
                "create_target_session",
                return_value=types.SimpleNamespace(
                    yaml_filename="docassemble.playground7:main.yml",
                    session_id="target-id",
                    secret=None,
                ),
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/runtime/sessions",
                method="POST",
                json={"project": "default", "filename": "main.yml"},
            ):
                api_editor.editor_api_runtime_create_session()
        self.assertEqual(bumped, ["docassemble.playground7:main.yml"])


if __name__ == "__main__":
    unittest.main()

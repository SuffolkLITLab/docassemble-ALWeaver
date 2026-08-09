# do not pre load

"""HTTP-level guarantees for the editing-assistant endpoints.

The invariants under test are the ones a model must never be able to reach
around: the feature flags, owner scoping, the file the session is bound to,
staleness on apply, and the rule that no agent request ever writes to the
Playground.
"""

from contextlib import ExitStack
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from . import editor_agent_validation
from .editor_agent_models import (
    WeaverAgentSession,
    load_agent_session,
    store_agent_session,
)
from .editor_agent_repair import auto_heal_source
from .editor_utils import (
    metadata_source_slice,
    parse_interview_yaml,
    parse_order_code,
)
from .source_document import source_revision
from .test_editor_api import api_editor

INTERVIEW = """metadata:
  title: Demo
---
id: intro
question: Welcome
---
id: user_address
question: Where do you live?
"""

BROKEN_IDS = """metadata:
  title: Demo
---
question: |
  What is your name?
---
id: intro
question: Hello
---
id: intro
question: Hello again
"""


def _id_diagnostics(raw_yaml, filename):
    """Stand in for DAYamlChecker's id rules, keyed off its real wording.

    Whether the checker still uses this wording is pinned by
    test_editor_agent_repair; here it only has to be deterministic.
    """
    findings = []
    for index, line in enumerate(raw_yaml.splitlines(), start=1):
        if line.strip() == "question: |" and "id: what_is_your_name" not in raw_yaml:
            findings.append(
                {
                    "level": "error",
                    "severity": "error",
                    "message": "question block is missing an `id`: What is your name?",
                    "filename": filename,
                    "line_number": index,
                }
            )
    if raw_yaml.count("id: intro\n") > 1:
        findings.append(
            {
                "level": "error",
                "severity": "error",
                "message": 'Duplicate block id "intro" - first used at line 7',
                "filename": filename,
                "line_number": 10,
            }
        )
    return findings


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, ex=None):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat_completion(self, **kwargs):
        if not self.responses:
            return {"action": "final", "summary": "Done."}
        return self.responses.pop(0)


class AgentApiTestCase(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        checker = patch.object(
            editor_agent_validation, "dayamlchecker_findings", return_value=[]
        )
        self.addCleanup(checker.stop)
        checker.start()
        # The api_editor test loader stubs source_revision to a constant, which
        # would make every staleness check pass for the wrong reason. Restore
        # the real content hash so revision comparisons mean something.
        revision = patch.object(api_editor, "source_revision", source_revision)
        self.addCleanup(revision.stop)
        revision.start()
        # The loader also stubs the YAML model helpers. The agent endpoints
        # return a real interview model to the browser, so use the real ones.
        for name, implementation in (
            ("parse_interview_yaml", parse_interview_yaml),
            ("parse_order_code", parse_order_code),
            ("metadata_source_slice", metadata_source_slice),
        ):
            patcher = patch.object(api_editor, name, implementation)
            self.addCleanup(patcher.stop)
            patcher.start()
        self.saved_revision = source_revision(INTERVIEW)

    def _patches(
        self, user_id=7, agent=True, patch_model=True, runtime=False, saved=INTERVIEW
    ):
        return [
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=user_id),
            patch.object(api_editor, "_agent_editor_available", return_value=agent),
            patch.object(
                api_editor,
                "_assistant_status",
                return_value={
                    "available": agent,
                    "code": "ready" if agent else "disabled",
                    "message": "" if agent else "turned off",
                },
            ),
            patch.object(
                api_editor, "_runtime_inspector_enabled", return_value=runtime
            ),
            patch.object(api_editor, "r", self.redis),
            patch.object(api_editor, "playground_read_yaml", return_value=saved),
        ]

    def _stored_session(self, owner=7, candidate=None, base_revision=None):
        session = WeaverAgentSession(
            session_id="agent-1",
            owner_user_id=owner,
            project="default",
            filename="main.yml",
            base_saved_revision=base_revision or self.saved_revision,
            original_working_source=INTERVIEW,
            candidate_source=candidate or INTERVIEW,
            candidate_revision=source_revision(candidate or INTERVIEW),
        )
        store_agent_session(self.redis, session)
        return session

    def _request(self, view, path, method="POST", json_body=None, args=None, **kwargs):
        with ExitStack() as stack:
            for patcher in self._patches(**kwargs):
                stack.enter_context(patcher)
            with api_editor.app.test_request_context(
                path, method=method, json=json_body
            ):
                return view(*(args or ()))


class TestConfiguration(unittest.TestCase):
    """Settings use Docassemble's own key style, and the assistant is on by default."""

    def _with_config(self, config, environ=None):
        return (
            patch.object(api_editor, "_daconfig", return_value=config),
            patch.dict(api_editor.os.environ, environ or {}, clear=False),
        )

    def test_the_assistant_is_on_when_nothing_is_configured(self):
        with patch.object(api_editor, "_daconfig", return_value={}):
            self.assertTrue(api_editor._agent_editor_enabled())

    def test_a_grouped_lowercase_setting_turns_it_off(self):
        config = {"weaver": {"assistant": False}}
        with patch.object(api_editor, "_daconfig", return_value=config):
            self.assertFalse(api_editor._agent_editor_enabled())

    def test_a_flat_lowercase_setting_works_too(self):
        with patch.object(
            api_editor, "_daconfig", return_value={"weaver assistant": False}
        ):
            self.assertFalse(api_editor._agent_editor_enabled())

    def test_the_older_upper_snake_spelling_still_works(self):
        with patch.object(
            api_editor,
            "_daconfig",
            return_value={"WEAVER_ENABLE_AGENT_EDITOR": "false"},
        ):
            self.assertFalse(api_editor._agent_editor_enabled())

    def test_underscore_keys_are_found_after_docassemble_rewrites_them(self):
        """Docassemble rejects underscores in configuration keys and converts
        them to spaces on load, so `WEAVER_ENABLE_PATCH_MODEL: True` in a
        config file arrives as `WEAVER ENABLE PATCH MODEL`. Matching only the
        underscore form silently ignores a setting the author did write."""
        for key in (
            "WEAVER ENABLE PATCH MODEL",
            "weaver enable patch model",
            "WEAVER_ENABLE_PATCH_MODEL",
        ):
            with self.subTest(key=key):
                with patch.object(api_editor, "_daconfig", return_value={key: True}):
                    self.assertTrue(api_editor._patch_model_enabled())

    def test_the_grouped_setting_wins_over_the_legacy_one(self):
        config = {
            "weaver": {"runtime inspector": True},
            "WEAVER_ENABLE_RUNTIME_INSPECTOR": "false",
        }
        with patch.object(api_editor, "_daconfig", return_value=config):
            self.assertTrue(api_editor._runtime_inspector_enabled())

    def test_the_model_can_be_named_in_the_configuration(self):
        config = {"weaver": {"assistant model": "gpt-5-mini"}}
        with patch.object(api_editor, "_daconfig", return_value=config):
            self.assertEqual(api_editor._weaver_text("assistant model"), "gpt-5-mini")

    def test_the_assistant_does_not_depend_on_the_source_patch_api(self):
        # The agent compiles its own range operations in process; it never calls
        # POST /al/editor/api/file/patch.
        with patch.object(api_editor, "_daconfig", return_value={}):
            self.assertFalse(api_editor._patch_model_enabled())
            self.assertTrue(api_editor._agent_editor_enabled())


class TestAssistantAvailability(unittest.TestCase):
    def _status(self, llms, config=None, worker_ready=True):
        with (
            patch.object(api_editor, "_daconfig", return_value=config or {}),
            patch.object(api_editor, "_load_llms_module", return_value=llms),
            patch.object(
                api_editor, "worker_configuration_is_ready", return_value=worker_ready
            ),
        ):
            return api_editor._assistant_status()

    def test_a_missing_background_worker_is_explained(self):
        """A turn runs in the worker, so no worker means no assistant. Saying so
        beats accepting a request that can never be picked up."""
        status = self._status(
            types.SimpleNamespace(client=object()), worker_ready=False
        )
        self.assertFalse(status["available"])
        self.assertEqual(status["code"], api_editor.ASSISTANT_STATUS_NO_WORKER)
        self.assertIn("background worker", status["message"])

    def test_a_configured_model_is_reported_as_ready(self):
        status = self._status(types.SimpleNamespace(client=object()))
        self.assertTrue(status["available"])
        self.assertEqual(status["code"], api_editor.ASSISTANT_STATUS_READY)

    def test_a_missing_api_key_is_explained_rather_than_hidden(self):
        # ALToolbox leaves its client as None when it finds no credentials.
        status = self._status(types.SimpleNamespace(client=None))
        self.assertFalse(status["available"])
        self.assertEqual(status["code"], api_editor.ASSISTANT_STATUS_NO_MODEL)
        self.assertIn("openai api key", status["message"])

    def test_a_missing_toolbox_is_explained(self):
        status = self._status(None)
        self.assertEqual(status["code"], api_editor.ASSISTANT_STATUS_NO_TOOLBOX)
        self.assertIn("ALToolbox", status["message"])

    def test_being_turned_off_is_reported_separately_from_being_unconfigured(self):
        status = self._status(
            types.SimpleNamespace(client=object()),
            config={"weaver": {"assistant": False}},
        )
        self.assertEqual(status["code"], api_editor.ASSISTANT_STATUS_DISABLED)

    def test_the_bootstrap_carries_the_status_to_the_browser(self):
        with (
            patch.object(api_editor, "_daconfig", return_value={}),
            patch.object(
                api_editor,
                "_load_llms_module",
                return_value=types.SimpleNamespace(client=None),
            ),
            patch.object(
                api_editor, "worker_configuration_is_ready", return_value=True
            ),
        ):
            features = api_editor._editor_feature_bootstrap()
        # The panel is still offered, so the author can find out why it is idle.
        self.assertTrue(features["agent_editor"])
        self.assertFalse(features["assistant_status"]["available"])
        self.assertIn("openai api key", features["assistant_status"]["message"])

    def test_an_unconfigured_server_answers_503_not_404(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_daconfig", return_value={}),
            patch.object(
                api_editor,
                "_load_llms_module",
                return_value=types.SimpleNamespace(client=None),
            ),
            patch.object(
                api_editor, "worker_configuration_is_ready", return_value=True
            ),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/agent/sessions", method="POST", json={}
            ):
                response = api_editor.editor_api_agent_create_session()
        self.assertEqual(response.status_code, 503)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "assistant_unavailable")
        self.assertIn("openai api key", error["message"])


class TestFeatureFlags(AgentApiTestCase):
    def test_every_agent_endpoint_is_hidden_without_the_agent_flag(self):
        cases = [
            (api_editor.editor_api_agent_create_session, (), "/api/agent/sessions"),
            (
                api_editor.editor_api_agent_session,
                ("agent-1",),
                "/api/agent/sessions/agent-1",
            ),
            (
                api_editor.editor_api_agent_turn,
                ("agent-1",),
                "/api/agent/sessions/agent-1/turn",
            ),
            (
                api_editor.editor_api_agent_apply,
                ("agent-1",),
                "/api/agent/sessions/agent-1/apply",
            ),
            (
                api_editor.editor_api_agent_reset,
                ("agent-1",),
                "/api/agent/sessions/agent-1/reset",
            ),
            (
                api_editor.editor_api_agent_cancel,
                ("agent-1",),
                "/api/agent/sessions/agent-1/cancel",
            ),
        ]
        for view, args, path in cases:
            with self.subTest(path=path):
                response = self._request(
                    view, path, json_body={}, args=args, agent=False
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(
                    response.get_json()["error"]["code"], "agent_editor_disabled"
                )

    def test_the_assistant_stands_on_its_own(self):
        """The other two betas stay opt-in; the assistant does not wait on them.

        Nothing in the agent path calls POST /al/editor/api/file/patch — the
        tools compile their range operations in process — so coupling the two
        only ever hid a working feature.
        """
        with (
            patch.object(api_editor, "_daconfig", return_value={}),
            patch.object(
                api_editor,
                "_load_llms_module",
                return_value=types.SimpleNamespace(client=object()),
            ),
            patch.object(
                api_editor, "worker_configuration_is_ready", return_value=True
            ),
        ):
            features = api_editor._editor_feature_bootstrap()
        self.assertFalse(features["patch_model"])
        self.assertFalse(features["runtime_inspector"])
        self.assertTrue(features["agent_editor"])
        self.assertTrue(features["assistant_status"]["available"])

    def test_the_bootstrap_publishes_every_flag_in_both_spellings(self):
        config = {
            "weaver": {
                "assistant": True,
                "runtime inspector": True,
                "source patch api": True,
            }
        }
        with (
            patch.object(api_editor, "_daconfig", return_value=config),
            patch.object(
                api_editor,
                "_load_llms_module",
                return_value=types.SimpleNamespace(client=object()),
            ),
            patch.object(
                api_editor, "worker_configuration_is_ready", return_value=True
            ),
        ):
            features = api_editor._editor_feature_bootstrap()
        for key in ("patch_model", "runtime_inspector", "agent_editor"):
            self.assertTrue(features[key], key)
        self.assertTrue(features["runtimeInspector"])
        self.assertTrue(features["agentEditor"])


class TestSessionCreation(AgentApiTestCase):
    def test_a_session_binds_to_the_requested_project_and_file(self):
        response = self._request(
            api_editor.editor_api_agent_create_session,
            "/api/agent/sessions",
            json_body={
                "project": "default",
                "filename": "main.yml",
                "raw_yaml": INTERVIEW,
                "base_revision": self.saved_revision,
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()["data"]
        self.assertEqual(data["project"], "default")
        self.assertEqual(data["filename"], "main.yml")
        self.assertFalse(data["stale"])
        # Nothing internal escapes to the browser.
        self.assertNotIn("original_working_source", data)
        self.assertNotIn("candidate_source", data)

        stored = load_agent_session(self.redis, data["agent_session_id"], 7)
        self.assertEqual(stored.candidate_source, INTERVIEW)

    def test_a_stale_base_revision_is_refused(self):
        response = self._request(
            api_editor.editor_api_agent_create_session,
            "/api/agent/sessions",
            json_body={
                "project": "default",
                "filename": "main.yml",
                "raw_yaml": INTERVIEW,
                "base_revision": "a-revision-from-before",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"]["code"], "agent_base_revision_stale"
        )

    def test_working_source_with_blocking_errors_cannot_start_a_session(self):
        with patch.object(
            editor_agent_validation,
            "dayamlchecker_findings",
            return_value=[
                {
                    "level": "error",
                    "severity": "error",
                    "message": "This interview is broken",
                    "filename": "main.yml",
                }
            ],
        ):
            response = self._request(
                api_editor.editor_api_agent_create_session,
                "/api/agent/sessions",
                json_body={
                    "project": "default",
                    "filename": "main.yml",
                    "raw_yaml": INTERVIEW,
                    "base_revision": self.saved_revision,
                },
            )
        self.assertEqual(response.status_code, 422)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "invalid_working_source")
        self.assertTrue(error["details"]["diagnostics"])

    def test_mechanical_id_problems_are_offered_as_a_fix_rather_than_a_dead_end(self):
        with patch.object(
            editor_agent_validation,
            "dayamlchecker_findings",
            side_effect=_id_diagnostics,
        ):
            response = self._request(
                api_editor.editor_api_agent_create_session,
                "/api/agent/sessions",
                json_body={
                    "project": "default",
                    "filename": "main.yml",
                    "raw_yaml": BROKEN_IDS,
                    "base_revision": source_revision(BROKEN_IDS),
                },
                saved=BROKEN_IDS,
            )
        self.assertEqual(response.status_code, 422)
        details = response.get_json()["error"]["details"]
        self.assertTrue(details["can_auto_heal"])
        self.assertEqual(details["repairable_count"], 2)
        self.assertEqual(details["unrepairable_count"], 0)
        self.assertEqual(len(details["repairs"]), 2)

    def test_auto_heal_starts_the_session_and_keeps_the_fix_in_the_diff(self):
        with patch.object(
            editor_agent_validation,
            "dayamlchecker_findings",
            side_effect=_id_diagnostics,
        ):
            with patch.object(api_editor, "playground_write_yaml") as write:
                response = self._request(
                    api_editor.editor_api_agent_create_session,
                    "/api/agent/sessions",
                    json_body={
                        "project": "default",
                        "filename": "main.yml",
                        "raw_yaml": BROKEN_IDS,
                        "base_revision": source_revision(BROKEN_IDS),
                        "auto_heal": True,
                    },
                    saved=BROKEN_IDS,
                )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()["data"]
        self.assertEqual(len(data["repairs"]), 2)
        # The repair is a change the developer has not saved yet.
        self.assertTrue(data["has_candidate_changes"])
        write.assert_not_called()

        stored = load_agent_session(self.redis, data["agent_session_id"], 7)
        self.assertIn("id: intro_2", stored.candidate_source)
        self.assertIn("id: what_is_your_name", stored.candidate_source)
        # The diff base stays the developer's own source so the fix is visible.
        self.assertEqual(stored.original_working_source, BROKEN_IDS)
        self.assertIn("+id: intro_2", stored.candidate().diff("main.yml"))

    def test_auto_heal_is_opt_in(self):
        with patch.object(
            editor_agent_validation,
            "dayamlchecker_findings",
            side_effect=_id_diagnostics,
        ):
            response = self._request(
                api_editor.editor_api_agent_create_session,
                "/api/agent/sessions",
                json_body={
                    "project": "default",
                    "filename": "main.yml",
                    "raw_yaml": BROKEN_IDS,
                    "base_revision": source_revision(BROKEN_IDS),
                    "auto_heal": False,
                },
                saved=BROKEN_IDS,
            )
        self.assertEqual(response.status_code, 422)

    def test_a_healed_session_resets_to_the_repaired_source(self):
        with patch.object(
            editor_agent_validation,
            "dayamlchecker_findings",
            side_effect=_id_diagnostics,
        ):
            healed = auto_heal_source(filename="main.yml", raw_yaml=BROKEN_IDS)
        self.assertTrue(healed.repairs)
        session = WeaverAgentSession(
            session_id="agent-1",
            owner_user_id=7,
            project="default",
            filename="main.yml",
            base_saved_revision=self.saved_revision,
            original_working_source=BROKEN_IDS,
            candidate_source=healed.raw_yaml.replace("Hello again", "Edited"),
            candidate_revision="candidate",
            repaired_working_source=healed.raw_yaml,
        )
        store_agent_session(self.redis, session)
        response = self._request(
            api_editor.editor_api_agent_reset,
            "/api/agent/sessions/agent-1/reset",
            json_body={},
            args=("agent-1",),
        )
        self.assertEqual(response.status_code, 200)
        stored = load_agent_session(self.redis, "agent-1", 7)
        self.assertEqual(stored.candidate_source, healed.raw_yaml)
        self.assertNotEqual(stored.candidate_source, BROKEN_IDS)

    def test_the_working_source_snapshot_is_what_the_candidate_starts_from(self):
        unsaved = INTERVIEW.replace("Welcome", "Welcome, unsaved edit")
        response = self._request(
            api_editor.editor_api_agent_create_session,
            "/api/agent/sessions",
            json_body={
                "project": "default",
                "filename": "main.yml",
                "raw_yaml": unsaved,
                "base_revision": self.saved_revision,
            },
        )
        self.assertEqual(response.status_code, 201)
        stored = load_agent_session(
            self.redis, response.get_json()["data"]["agent_session_id"], 7
        )
        self.assertIn("Welcome, unsaved edit", stored.candidate_source)


class TestSessionOwnership(AgentApiTestCase):
    def test_another_developer_cannot_read_or_drive_a_session(self):
        self._stored_session(owner=7)
        for view, method, path in (
            (api_editor.editor_api_agent_session, "GET", "/api/agent/sessions/agent-1"),
            (
                api_editor.editor_api_agent_turn,
                "POST",
                "/api/agent/sessions/agent-1/turn",
            ),
            (
                api_editor.editor_api_agent_apply,
                "POST",
                "/api/agent/sessions/agent-1/apply",
            ),
            (
                api_editor.editor_api_agent_reset,
                "POST",
                "/api/agent/sessions/agent-1/reset",
            ),
        ):
            with self.subTest(path=path):
                response = self._request(
                    view,
                    path,
                    method=method,
                    json_body={"message": "hello"},
                    args=("agent-1",),
                    user_id=99,
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(
                    response.get_json()["error"]["code"], "agent_session_not_found"
                )


class TestTurn(AgentApiTestCase):
    def _run_turn(self, responses, message="Reword the intro", user_id=7):
        """Start a turn and run it to completion.

        The endpoint queues the work to Celery, so the test captures what would
        have been enqueued and runs the worker body itself.
        """
        llm = FakeLLM(responses)
        started = []

        def capture(_task_name, kwargs=None):
            started.append(kwargs or {})
            return types.SimpleNamespace(id="celery-agent-1")

        with (
            patch.object(api_editor, "_load_llms_module", return_value=llm),
            patch.object(api_editor.workerapp, "send_task", side_effect=capture),
        ):
            response = self._request(
                api_editor.editor_api_agent_turn,
                "/api/agent/sessions/agent-1/turn",
                json_body={"message": message},
                args=("agent-1",),
                user_id=user_id,
            )
            if response.status_code == 202:
                for kwargs in started:
                    with ExitStack() as stack:
                        for patcher in self._patches(user_id=user_id):
                            stack.enter_context(patcher)
                        api_editor._run_agent_turn_in_background(**kwargs)
        self.last_progress = api_editor.load_progress(self.redis, "agent-1", user_id)
        return response

    def test_a_turn_edits_the_candidate_and_never_writes_the_playground(self):
        self._stored_session()
        with patch.object(api_editor, "playground_write_yaml") as write:
            response = self._run_turn(
                [
                    {
                        "action": "tool",
                        "tool": "replace_question",
                        "arguments": {
                            "block_id": "intro",
                            "question": {"question": "Welcome to the interview"},
                        },
                    },
                    {"action": "final", "summary": "Reworded the intro."},
                ]
            )
        # The request only starts the work; the outcome arrives via progress.
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.get_json()["data"]["started"])
        result = self.last_progress["result"]
        self.assertFalse(self.last_progress["running"])
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["has_candidate_changes"])
        self.assertEqual(result["summary"], "Reworded the intro.")
        write.assert_not_called()

        stored = load_agent_session(self.redis, "agent-1", 7)
        self.assertIn("Welcome to the interview", stored.candidate_source)
        self.assertEqual(len(stored.command_history), 1)
        self.assertEqual(stored.command_history[0]["tool"], "replace_question")
        self.assertEqual(stored.command_history[0]["status"], "accepted")

    def test_a_model_cannot_retarget_the_session_to_another_file(self):
        self._stored_session()
        response = self._run_turn(
            [
                {
                    "action": "tool",
                    "tool": "replace_question",
                    "arguments": {
                        "block_id": "intro",
                        "project": "other_project",
                        "filename": "secrets.yml",
                        "question": {"question": "Owned"},
                    },
                },
                {"action": "final", "summary": "Could not."},
            ]
        )
        self.assertEqual(response.status_code, 202)
        stored = load_agent_session(self.redis, "agent-1", 7)
        self.assertEqual(stored.filename, "main.yml")
        self.assertEqual(stored.project, "default")
        self.assertEqual(stored.candidate_source, INTERVIEW)

    def test_an_over_long_message_is_refused(self):
        self._stored_session()
        response = self._run_turn(
            [{"action": "final", "summary": "ok"}],
            message="x" * (api_editor.MAX_CHAT_MESSAGE_CHARS + 1),
        )
        self.assertEqual(response.status_code, 400)

    def test_runtime_tools_stay_unavailable_without_the_runtime_flag(self):
        self._stored_session()
        with patch.object(api_editor, "create_target_session") as create:
            response = self._run_turn(
                [
                    {
                        "action": "tool",
                        "tool": "runtime_start_session",
                        "arguments": {},
                    },
                    {"action": "final", "summary": "No runtime here."},
                ],
                message="test the interview",
            )
        self.assertEqual(response.status_code, 202)
        create.assert_not_called()
        events = self.last_progress["result"]["turn"]["events"]
        rejected = [event for event in events if event.get("status") == "rejected"]
        self.assertTrue(rejected)

    def test_a_long_conversation_is_stopped_and_told_to_start_fresh(self):
        """This assistant is for small, discrete edits. A sprawling chat makes
        each turn slower and vaguer and the candidate harder to review as one
        diff, so the chat ends and asks for a new one."""
        session = self._stored_session()
        session.turn_count = api_editor.MAX_TURNS_PER_SESSION
        store_agent_session(self.redis, session)

        response = self._request(
            api_editor.editor_api_agent_turn,
            "/api/agent/sessions/agent-1/turn",
            json_body={"message": "one more thing"},
            args=("agent-1",),
        )
        self.assertEqual(response.status_code, 409)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "turn_limit_reached")
        self.assertIn("start a new chat", error["message"])

    def test_the_browser_is_told_how_many_requests_remain(self):
        session = self._stored_session()
        session.turn_count = 7
        store_agent_session(self.redis, session)
        payload = load_agent_session(self.redis, "agent-1", 7).public_dict()
        self.assertEqual(payload["turns_remaining"], 3)
        self.assertEqual(payload["max_turns"], api_editor.MAX_TURNS_PER_SESSION)

    def test_each_accepted_turn_counts_against_the_limit(self):
        self._stored_session()
        self._run_turn([{"action": "final", "summary": "ok"}])
        self.assertEqual(load_agent_session(self.redis, "agent-1", 7).turn_count, 1)

    def test_a_reset_gives_the_chat_its_budget_back(self):
        session = self._stored_session()
        session.turn_count = api_editor.MAX_TURNS_PER_SESSION
        store_agent_session(self.redis, session)
        self._request(
            api_editor.editor_api_agent_reset,
            "/api/agent/sessions/agent-1/reset",
            json_body={},
            args=("agent-1",),
        )
        self.assertEqual(load_agent_session(self.redis, "agent-1", 7).turn_count, 0)

    def test_a_turn_is_queued_to_celery_and_never_run_in_process(self):
        """Weaver's rule for long editor work is the Celery worker, never an
        in-process thread. A turn outlives any request — the browser times out
        first and nginx closes an idle upstream read at sixty seconds — so it
        has to be queued, not awaited."""
        self._stored_session()
        sent = []

        def capture(task_name, kwargs=None):
            sent.append((task_name, kwargs or {}))
            return types.SimpleNamespace(id="celery-agent-1")

        with patch.object(api_editor.workerapp, "send_task", side_effect=capture):
            response = self._request(
                api_editor.editor_api_agent_turn,
                "/api/agent/sessions/agent-1/turn",
                json_body={"message": "reword the intro"},
                args=("agent-1",),
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(sent), 1)
        task_name, kwargs = sent[0]
        self.assertEqual(task_name, api_editor.AGENT_TURN_CELERY_TASK)
        self.assertEqual(kwargs["session_id"], "agent-1")
        self.assertEqual(kwargs["owner_user_id"], 7)
        # The worker is told the target by session, never by project or filename.
        self.assertNotIn("project", kwargs)
        self.assertNotIn("filename", kwargs)

        source = Path(api_editor.__file__).read_text()
        self.assertNotIn("import threading", source)
        self.assertNotIn("threading.Thread", source)

    def test_a_worker_that_will_not_take_the_job_is_reported_not_swallowed(self):
        self._stored_session()
        with patch.object(
            api_editor.workerapp, "send_task", side_effect=RuntimeError("no broker")
        ):
            response = self._request(
                api_editor.editor_api_agent_turn,
                "/api/agent/sessions/agent-1/turn",
                json_body={"message": "reword the intro"},
                args=("agent-1",),
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "agent_turn_not_queued")
        # No orphaned record left claiming a turn is running.
        self.assertIsNone(api_editor.load_progress(self.redis, "agent-1", 7))

    def test_a_second_turn_cannot_start_while_one_is_running(self):
        self._stored_session()
        api_editor.store_progress(
            self.redis,
            "agent-1",
            7,
            running=True,
            events=[],
            started_at=api_editor.time.time(),
        )
        response = self._request(
            api_editor.editor_api_agent_turn,
            "/api/agent/sessions/agent-1/turn",
            json_body={"message": "another request"},
            args=("agent-1",),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "turn_in_progress")

    def test_an_abandoned_turn_does_not_block_the_session_forever(self):
        """A recycled worker leaves a record that says running. It has to go
        stale, or the assistant is wedged until the record expires."""
        self._stored_session()
        api_editor.store_progress(
            self.redis, "agent-1", 7, running=True, events=[], started_at=0.0
        )
        stale = api_editor.load_progress(self.redis, "agent-1", 7)
        stale["updated_at"] = api_editor.time.time() - 600
        self.assertFalse(api_editor.progress_is_live(stale))


class TestApply(AgentApiTestCase):
    def test_apply_returns_the_candidate_and_writes_nothing(self):
        candidate = INTERVIEW.replace("Welcome", "Welcome, friend")
        self._stored_session(candidate=candidate)
        with patch.object(api_editor, "playground_write_yaml") as write:
            response = self._request(
                api_editor.editor_api_agent_apply,
                "/api/agent/sessions/agent-1/apply",
                json_body={},
                args=("agent-1",),
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["raw_yaml"], candidate)
        # The editor must stay dirty against the revision still on disk.
        self.assertEqual(data["saved_revision"], self.saved_revision)
        self.assertNotEqual(data["candidate_revision"], data["saved_revision"])
        self.assertIn("blocks", data)
        write.assert_not_called()

    def test_apply_is_refused_when_the_saved_file_moved_on(self):
        self._stored_session(base_revision="the-revision-when-chat-started")
        with patch.object(api_editor, "playground_write_yaml") as write:
            response = self._request(
                api_editor.editor_api_agent_apply,
                "/api/agent/sessions/agent-1/apply",
                json_body={},
                args=("agent-1",),
            )
        self.assertEqual(response.status_code, 409)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "agent_session_stale")
        self.assertIn("Restart the assistant", error["message"])
        write.assert_not_called()

    def test_a_candidate_with_blocking_errors_cannot_be_applied(self):
        self._stored_session()
        with patch.object(
            editor_agent_validation,
            "dayamlchecker_findings",
            return_value=[
                {
                    "level": "error",
                    "severity": "error",
                    "message": "Still broken",
                    "filename": "main.yml",
                }
            ],
        ):
            with patch.object(api_editor, "playground_write_yaml") as write:
                response = self._request(
                    api_editor.editor_api_agent_apply,
                    "/api/agent/sessions/agent-1/apply",
                    json_body={},
                    args=("agent-1",),
                )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_candidate")
        write.assert_not_called()


class TestLiveProgress(AgentApiTestCase):
    """A turn is one blocking request, so progress has to be published as it goes."""

    def test_progress_is_published_while_the_turn_runs(self):
        self._stored_session()
        seen = []

        original = api_editor.store_progress

        def recording(redis_client, session_id, owner, **kwargs):
            seen.append({"running": kwargs["running"], "count": len(kwargs["events"])})
            return original(redis_client, session_id, owner, **kwargs)

        llm = FakeLLM(
            [
                {
                    "action": "tool",
                    "tool": "get_interview_outline",
                    "arguments": {},
                },
                {"action": "final", "summary": "Looked around."},
            ]
        )
        with (
            patch.object(api_editor, "_load_llms_module", return_value=llm),
            patch.object(api_editor, "store_progress", side_effect=recording),
        ):
            with ExitStack() as stack:
                for patcher in self._patches():
                    stack.enter_context(patcher)
                api_editor._run_agent_turn_in_background(
                    session_id="agent-1",
                    owner_user_id=7,
                    message="look around",
                    selected_block_id=None,
                    runtime_enabled=False,
                    request_id="req-1",
                    started_at=0.0,
                )
        # Published repeatedly during the run, and the event list grows.
        self.assertGreater(len(seen), 2)
        self.assertTrue(all(item["running"] for item in seen[:-1]))
        self.assertGreater(seen[-2]["count"], seen[0]["count"])
        # The final write marks the turn finished and carries the outcome.
        self.assertFalse(seen[-1]["running"])
        finished = api_editor.load_progress(self.redis, "agent-1", 7)
        self.assertIsNotNone(finished["result"])
        self.assertIsNone(finished["error"])

    def test_a_crashing_turn_reports_failure_instead_of_hanging(self):
        """Nothing can await the thread, so a crash has to land in the record;
        otherwise the panel spins until the record expires."""
        self._stored_session()

        def explode(**kwargs):
            raise RuntimeError("provider is down")

        with (
            patch.object(api_editor, "_load_llms_module", return_value=FakeLLM([])),
            patch.object(api_editor, "run_agent_turn", side_effect=explode),
        ):
            with ExitStack() as stack:
                for patcher in self._patches():
                    stack.enter_context(patcher)
                api_editor._run_agent_turn_in_background(
                    session_id="agent-1",
                    owner_user_id=7,
                    message="do a thing",
                    selected_block_id=None,
                    runtime_enabled=False,
                    request_id="req-1",
                    started_at=0.0,
                )
        finished = api_editor.load_progress(self.redis, "agent-1", 7)
        self.assertFalse(finished["running"])
        self.assertEqual(finished["error"]["code"], "agent_turn_failed")
        # The candidate is untouched by a turn that blew up.
        self.assertEqual(
            load_agent_session(self.redis, "agent-1", 7).candidate_source, INTERVIEW
        )

    def test_the_progress_endpoint_is_owner_scoped(self):
        self._stored_session(owner=7)
        api_editor.store_progress(
            self.redis, "agent-1", 7, running=True, events=[], started_at=0.0
        )
        response = self._request(
            api_editor.editor_api_agent_progress,
            "/api/agent/sessions/agent-1/progress",
            method="GET",
            args=("agent-1",),
            user_id=99,
        )
        self.assertEqual(response.status_code, 404)

    def test_progress_reports_the_steps_taken_so_far(self):
        self._stored_session()
        api_editor.store_progress(
            self.redis,
            "agent-1",
            7,
            running=True,
            events=[
                {"type": "status", "label": "Editing candidate", "status": "editing"},
                {
                    "type": "tool_result",
                    "tool": "insert_question",
                    "label": "Inserted new screen",
                    "status": "success",
                },
            ],
            started_at=123.0,
        )
        response = self._request(
            api_editor.editor_api_agent_progress,
            "/api/agent/sessions/agent-1/progress",
            method="GET",
            args=("agent-1",),
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertTrue(data["running"])
        self.assertEqual(len(data["events"]), 2)
        self.assertEqual(data["events"][-1]["label"], "Inserted new screen")
        # The owner id is never handed back to the browser.
        self.assertNotIn("owner_user_id", data)

    def test_a_reset_clears_stale_progress(self):
        self._stored_session()
        api_editor.store_progress(
            self.redis, "agent-1", 7, running=True, events=[{"x": 1}], started_at=0.0
        )
        self._request(
            api_editor.editor_api_agent_reset,
            "/api/agent/sessions/agent-1/reset",
            json_body={},
            args=("agent-1",),
        )
        self.assertIsNone(api_editor.load_progress(self.redis, "agent-1", 7))


class TestResetAndCancel(AgentApiTestCase):
    def test_reset_restores_the_original_working_candidate(self):
        self._stored_session(candidate=INTERVIEW.replace("Welcome", "Changed"))
        response = self._request(
            api_editor.editor_api_agent_reset,
            "/api/agent/sessions/agent-1/reset",
            json_body={},
            args=("agent-1",),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["data"]["has_candidate_changes"])
        stored = load_agent_session(self.redis, "agent-1", 7)
        self.assertEqual(stored.candidate_source, INTERVIEW)
        self.assertEqual(stored.messages, [])

    def test_cancel_marks_the_session_so_a_running_turn_stops(self):
        self._stored_session()
        response = self._request(
            api_editor.editor_api_agent_cancel,
            "/api/agent/sessions/agent-1/cancel",
            json_body={},
            args=("agent-1",),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(load_agent_session(self.redis, "agent-1", 7).cancelled)


if __name__ == "__main__":
    unittest.main()

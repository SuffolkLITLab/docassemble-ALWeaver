# do not pre-load

"""AI requests must release web workers and stay bounded across accounts."""

from contextlib import ExitStack
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from .editor_utils import parse_interview_yaml
from .test_editor_api import api_editor

INTERVIEW = """id: q
question: Your name
fields:
  - Name: user_name
"""


class Redis:
    def __init__(self):
        self.values = {}
        self.locks = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def pipeline(self):
        return self

    def expire(self, *args):
        pass

    def execute(self):
        pass

    def eval(self, script, count, key, value):
        if self.get(key) == value:
            del self.values[key]
            return 1
        return 0

    def lock(self, name, **kwargs):
        return self.locks.setdefault(name, threading.Lock())


@pytest.fixture
def jobs():
    redis = Redis()
    with ExitStack() as stack:
        stack.enter_context(patch.object(api_editor, "r", redis))
        stack.enter_context(
            patch.object(api_editor, "_editor_auth_check", return_value=True)
        )
        stack.enter_context(
            patch.object(api_editor, "_current_user_id", return_value=7)
        )
        stack.enter_context(
            patch.object(api_editor, "worker_configuration_is_ready", return_value=True)
        )
        stack.enter_context(
            patch.object(api_editor, "playground_read_yaml", return_value=INTERVIEW)
        )
        stack.enter_context(
            patch.object(api_editor, "parse_interview_yaml", parse_interview_yaml)
        )
        stack.enter_context(
            patch.object(
                api_editor, "_load_llms_module", return_value=SimpleNamespace()
            )
        )
        send = stack.enter_context(patch.object(api_editor.workerapp, "send_task"))
        yield redis, send


def submit(operation="generate-screen", **overrides):
    body = {"project": "default", "filename": "main.yml", "block_id": "q"}
    body.update(overrides)
    with api_editor.app.test_request_context(
        "/al/editor/api/ai/" + operation,
        method="POST",
        json=body,
    ):
        handler = (
            api_editor.editor_api_ai_generate_screen
            if operation == "generate-screen"
            else api_editor.editor_api_ai_generate_fields
        )
        return handler()


@pytest.mark.parametrize("operation", ["generate-screen", "generate-fields"])
def test_submit_is_async_and_one_outstanding_job_per_owner(jobs, operation):
    redis, send = jobs
    model = SimpleNamespace(chat_completion=lambda **kwargs: pytest.fail("model"))
    with patch.object(api_editor, "_load_llms_module", return_value=model):
        response = submit(operation)
        assert response.status_code == 202
        assert submit(operation).status_code == 429
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs["time_limit"] == 180
    assert kwargs["soft_time_limit"] == 150
    assert kwargs["expires"] == 900
    assert kwargs["kwargs"]["uid"] == 7
    with patch.object(api_editor, "_current_user_id", return_value=8):
        assert submit(operation).status_code == 202


@pytest.mark.parametrize(
    "overrides, status, message",
    [
        ({"block_id": ""}, 400, "block_id is required"),
        ({"block_id": "missing"}, 400, "must refer to a question block"),
    ],
)
def test_invalid_field_requests_fail_before_queueing(jobs, overrides, status, message):
    redis, send = jobs
    response = submit("generate-fields", **overrides)
    assert response.status_code == status
    assert message in response.get_json()["error"]["message"]
    send.assert_not_called()
    assert redis.get(api_editor.AI_JOB_OWNER_PREFIX + "7") is None


def test_missing_file_fails_before_queueing(jobs):
    redis, send = jobs
    with patch.object(
        api_editor, "playground_read_yaml", side_effect=FileNotFoundError("missing.yml")
    ):
        assert submit().status_code == 404
        with api_editor.app.test_request_context(
            "/?project=default&filename=main.yml&include_llm=1"
        ):
            assert api_editor.editor_api_style_check().status_code == 404
    send.assert_not_called()
    assert redis.get(api_editor.AI_JOB_OWNER_PREFIX + "7") is None


def test_worker_validation_errors_keep_their_message(jobs):
    _, send = jobs
    response = submit("generate-fields")
    assert response.status_code == 202, response.get_json()
    job_id = response.get_json()["data"]["job_id"]
    with patch.object(
        api_editor,
        "_generate_ai_fields",
        side_effect=ValueError("AI did not return any usable fields"),
    ):
        api_editor._run_ai_job_with_capacity(**send.call_args.kwargs["kwargs"])
    state = api_editor._load_job_state(api_editor.AI_JOB, job_id)
    assert state["status"] == "failed"
    assert state["error"]["message"] == "AI did not return any usable fields"


def test_result_is_owner_scoped_and_completion_releases_reservation(jobs):
    redis, send = jobs
    response = submit()
    job_id = response.get_json()["data"]["job_id"]
    with patch.object(
        api_editor,
        "_generate_ai_screen",
        return_value={"screen": {"question": "Hello"}},
    ):
        assert api_editor._run_ai_job_with_capacity(**send.call_args.kwargs["kwargs"])
    with api_editor.app.test_request_context("/"):
        with patch.object(api_editor, "_current_user_id", return_value=8):
            assert api_editor.editor_api_ai_job(job_id).status_code == 404
        result = api_editor.editor_api_ai_job(job_id).get_json()["data"]
    assert result["status"] == "succeeded"
    assert result["result"]["screen"]["question"] == "Hello"
    assert submit().status_code == 202
    # Polling the old job must not remove the newer reservation.
    with api_editor.app.test_request_context("/"):
        api_editor.editor_api_ai_job(job_id)
    assert submit().status_code == 429


def test_full_capacity_defers_without_model_work_or_blocking(jobs):
    redis, send = jobs
    submit()
    for slot in range(2):
        redis.lock(f"da:alweaver:editor:ai-slot:{slot}").acquire()
    with patch.object(api_editor, "_complete_ai_job") as complete:
        assert not api_editor._run_ai_job_with_capacity(
            **send.call_args.kwargs["kwargs"]
        )
        complete.assert_not_called()
        redis.lock("da:alweaver:editor:ai-slot:1").release()
        assert api_editor._run_ai_job_with_capacity(**send.call_args.kwargs["kwargs"])
        complete.assert_called_once()
    assert not redis.lock("da:alweaver:editor:ai-slot:1").locked()


def test_expired_queue_and_worker_failure_release_owner(jobs):
    redis, send = jobs
    response = submit()
    job_id = response.get_json()["data"]["job_id"]
    api_editor._update_job_state(api_editor.AI_JOB, job_id, queued_at=time.time() - 901)
    with patch.object(api_editor, "_complete_ai_job") as complete:
        assert api_editor._run_ai_job_with_capacity(**send.call_args.kwargs["kwargs"])
        complete.assert_not_called()
    assert api_editor._load_job_state(api_editor.AI_JOB, job_id)["status"] == "expired"
    response = submit()
    job_id = response.get_json()["data"]["job_id"]
    from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]

    with patch.object(
        api_editor, "_generate_ai_screen", side_effect=SoftTimeLimitExceeded
    ):
        api_editor._run_ai_job_with_capacity(**send.call_args.kwargs["kwargs"])
    assert api_editor._load_job_state(api_editor.AI_JOB, job_id)["status"] == "failed"
    assert submit().status_code == 202


def test_failed_dispatch_and_missing_worker_do_not_run_synchronously(jobs):
    redis, send = jobs
    send.side_effect = RuntimeError("Broker unavailable")
    assert submit().status_code == 500
    assert redis.get(api_editor.AI_JOB_OWNER_PREFIX + "7") is None
    with patch.object(api_editor, "worker_configuration_is_ready", return_value=False):
        assert submit().status_code == 503


def test_style_defaults_to_deterministic_and_ai_is_queued(jobs):
    with (
        patch.object(
            api_editor, "_style_check_result", return_value={"errors": []}
        ) as check,
        patch.object(api_editor, "_interview_linter"),
    ):
        with api_editor.app.test_request_context("/?project=default&filename=main.yml"):
            assert api_editor.editor_api_style_check().status_code == 200
        check.assert_called_once_with(7, "default", "main.yml", False)
        check.reset_mock()
        with api_editor.app.test_request_context(
            "/?project=default&filename=main.yml&include_llm=1"
        ):
            assert api_editor.editor_api_style_check().status_code == 202
        check.assert_not_called()


def test_poll_recovers_worker_hard_failure(jobs):
    _, send = jobs
    job_id = submit().get_json()["data"]["job_id"]
    with patch.object(
        api_editor.workerapp,
        "AsyncResult",
        return_value=SimpleNamespace(state="FAILURE", result="Time limit exceeded"),
    ):
        with api_editor.app.test_request_context("/"):
            response = api_editor.editor_api_ai_job(job_id)
    assert response.get_json()["data"]["status"] == "failed"
    assert submit().status_code == 202


def test_template_context_cache_invalidates_changed_and_added_files(tmp_path):
    template = tmp_path / "form.pdf"
    template.write_bytes(b"PDF stub")
    with (
        patch.object(
            api_editor,
            "create_saved_file",
            return_value=SimpleNamespace(directory=str(tmp_path)),
        ),
        patch(
            "pdfminer.high_level.extract_text", return_value="Sample form"
        ) as extract,
    ):
        assert "Sample form" in api_editor._project_template_context_text(7, "default")
        api_editor._project_template_context_text(7, "default")
        extract.assert_called_once()
        template.write_bytes(b"Changed PDF stub")
        api_editor._project_template_context_text(7, "default")
        assert extract.call_count == 2
        (tmp_path / "new.pdf").write_bytes(b"Another form")
        api_editor._project_template_context_text(7, "default")
        assert extract.call_count == 4

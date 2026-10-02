# do not pre-load

"""Publishing must survive the partially initialized 1.9 worker from #1086."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import threading
import types
from unittest.mock import Mock, patch

from flask import Blueprint, Flask, current_app, has_app_context, has_request_context
import pytest

from . import docassemble_compat as compat


class TaskApp:
    def __init__(self):
        self.options = {}

    def task(self, function=None, **kwargs):
        def register(fn):
            self.options[fn.__name__] = kwargs
            return fn

        return register(function) if function is not None else register


@pytest.fixture(params=["1.9", "1.10"])
def publish_worker(request):
    app = Flask(__name__)
    # A failed server import leaves this registration on the existing app.
    blueprint = Blueprint("flask_user", __name__)
    app.register_blueprint(blueprint)

    @contextmanager
    def broken_native_context():
        app.register_blueprint(Blueprint("flask_user", __name__))
        yield

    functions = types.SimpleNamespace(reset_local_variables=Mock())
    thread_context = None
    if request.param == "1.10":
        thread_context = types.ModuleType("docassemble.base.thread_context")
        thread_context.empty_globals = dict

        @contextmanager
        def global_context(values):
            functions.reset_local_variables()
            yield

        thread_context.global_context = global_context
    config = types.ModuleType("docassemble.base.config")
    config.daconfig = {"url root": "https://example.test", "root": "/da/"}
    api_utils = types.ModuleType("docassemble.ALWeaver.api_utils")
    api_utils.generate_interview_from_bytes = Mock()
    editor = types.ModuleType("docassemble.ALWeaver.api_editor")
    editor._complete_github_publish_job = Mock(return_value={"sha": "commit"})
    editor._complete_new_project_upload_job = Mock()
    editor._load_new_project_job_state = Mock()
    native = Mock(side_effect=broken_native_context)
    with (
        patch.dict(
            sys.modules,
            {
                "docassemble.ALWeaver.docassemble_compat": compat,
                "docassemble.base.config": config,
                "docassemble.base.thread_context": thread_context,
                "docassemble.ALWeaver.api_utils": api_utils,
                "docassemble.ALWeaver.api_editor": editor,
            },
        ),
        patch.object(compat, "get_flask_app", return_value=app),
        patch.object(compat, "get_worker_app", return_value=TaskApp()),
        patch.object(compat, "_base_functions", return_value=functions),
        patch.object(compat, "background_context", native),
    ):
        spec = importlib.util.spec_from_file_location(
            "docassemble.ALWeaver._github_worker_context_test",
            Path(__file__).with_name("api_weaver_worker.py"),
        )
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        yield worker, app, editor, native, functions
    assert app.blueprints == {"flask_user": blueprint}


def publish(worker, uid=1):
    return worker.weaver_editor_github_publish_task(
        job_id=f"job-{uid}",
        uid=uid,
        project=f"Project{uid}",
        package="Test",
        repository="docassemble-Test",
        owner="test",
        owner_type="user",
        author_name="Test",
        author_email="test@example.test",
        branch="main",
        commit_message="Test",
        repository_url="https://github.com/test/docassemble-Test",
    )


def test_publish_avoids_poisoned_native_startup(publish_worker):
    worker, app, editor, native, functions = publish_worker
    with pytest.raises(ValueError, match="already registered"):
        with native():
            pass
    native.reset_mock()
    assert publish(worker) == {"sha": "commit"}
    native.assert_not_called()
    functions.reset_local_variables.assert_called_once()
    assert not has_app_context()
    assert not has_request_context()


@pytest.mark.parametrize("live", [True, False])
def test_cleanup_checks_requeue_only_live_sessions_without_server_startup(
    publish_worker, live
):
    worker, app, editor, native, functions = publish_worker
    runtime = importlib.import_module("docassemble.ALWeaver.runtime_sessions")
    redis_client = Mock()
    record = Mock() if live else None
    with patch.object(
        compat, "get_redis_client", return_value=redis_client
    ), patch.object(
        runtime, "get_live_runtime_record", return_value=record
    ) as load, patch.object(
        runtime, "schedule_runtime_cleanup"
    ) as schedule:
        worker.weaver_cleanup_runtime_session_task(
            session_id="debug-session", owner_user_id=7
        )
    load.assert_called_once_with(redis_client, "debug-session", 7)
    redis_client.delete.assert_called_once_with(
        runtime.RUNTIME_SESSION_KEY_PREFIX + "debug-session:cleanup-queued"
    )
    if live:
        schedule.assert_called_once_with(redis_client, record)
    else:
        schedule.assert_not_called()
    native.assert_not_called()
    assert not has_app_context()
    assert not has_request_context()


def test_cleanup_retries_transient_failures_a_few_times_only(publish_worker):
    worker = publish_worker[0]
    options = worker.workerapp.options["weaver_cleanup_runtime_session_task"]
    assert options["retry_kwargs"] == {"max_retries": 3}
    # A record that fails validation fails identically on every retry.
    assert issubclass(ValueError, options["dont_autoretry_for"])
    assert compat.DocassembleCompatibilityError in options["dont_autoretry_for"]
    # A busy session lock is a RuntimeError, and is worth retrying.
    assert not issubclass(RuntimeError, options["dont_autoretry_for"])


def test_twelve_publishes_have_independent_contexts(publish_worker):
    worker, app, editor, native, functions = publish_worker
    barrier = threading.Barrier(12)

    def complete(**kwargs):
        from flask import g, request

        g.uid = kwargs["uid"]
        barrier.wait(timeout=10)
        assert current_app._get_current_object() is app
        assert request.url == "https://example.test/da/interview"
        assert g.uid == kwargs["uid"]
        return g.uid

    editor._complete_github_publish_job.side_effect = complete
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert list(pool.map(lambda uid: publish(worker, uid), range(12))) == list(
            range(12)
        )
    assert functions.reset_local_variables.call_count == 12
    native.assert_not_called()


def test_publish_context_unwinds_after_failure(publish_worker):
    worker, app, editor, native, functions = publish_worker
    editor._complete_github_publish_job.side_effect = RuntimeError("GitHub unavailable")
    with pytest.raises(RuntimeError, match="GitHub unavailable"):
        publish(worker)
    native.assert_not_called()
    assert functions.reset_local_variables.call_count == 1
    assert not has_app_context()
    assert not has_request_context()


def new_project(worker):
    return worker.weaver_editor_new_project_task(
        job_id="synthetic-job",
        uid=7,
        project_name="Synthetic",
        request_id="synthetic-request",
        uploaded_files=[{"filename": "private-name.pdf"}],
        generation_options={},
        debug_requested=False,
        create_test=False,
    )


def test_new_project_failure_uses_durable_owner_record_without_returning_exception(
    publish_worker,
):
    worker, _app, editor, _native, _functions = publish_worker
    marker = "/private/storage/private-name.pdf"
    editor._complete_new_project_upload_job.side_effect = OSError(marker)
    editor._load_new_project_job_state.return_value = {
        "owner_user_id": 7,
        "status": "failed",
    }

    result = new_project(worker)

    assert result is None
    editor._load_new_project_job_state.assert_called_once_with("synthetic-job")


def test_new_project_failure_without_terminal_owner_record_is_generic(publish_worker):
    worker, _app, editor, _native, _functions = publish_worker
    marker = "/private/storage/private-name.pdf"
    editor._complete_new_project_upload_job.side_effect = OSError(marker)
    editor._load_new_project_job_state.return_value = {
        "owner_user_id": 7,
        "status": "running",
    }

    with pytest.raises(RuntimeError, match="ALWeaver generation failed") as exc_info:
        new_project(worker)

    assert marker not in str(exc_info.value)

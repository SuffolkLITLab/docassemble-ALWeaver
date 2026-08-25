# do not pre-load

from contextlib import contextmanager, nullcontext
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import types
import unittest
from unittest.mock import patch

from flask import Flask
from jinja2 import DebugUndefined

from . import docassemble_compat


class TestDocassembleCompatibilityInterface(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls

        class FakeFunctions:
            server = types.SimpleNamespace()
            # Stands in for a server whose startup already imported every
            # package, so the custom datatype fallback stays out of the way.
            custom_types = {"fake_datatype": {}}

            @staticmethod
            def create_session(yaml_filename, secret=None, url_args=None):
                calls.append(("create", yaml_filename, secret, url_args))
                return "session-123"

            @staticmethod
            def get_session_variables(*args, **kwargs):
                calls.append(("variables", args, kwargs))
                return {"answer": 42}

            @staticmethod
            def set_session_variables(*args, **kwargs):
                calls.append(("set", args, kwargs))

            @staticmethod
            def get_question_data(*args, **kwargs):
                calls.append(("question", args, kwargs))
                return {"questionName": "intro"}

            @staticmethod
            def go_back_in_session(*args, **kwargs):
                calls.append(("back", args, kwargs))
                return "back"

            @staticmethod
            def run_action_in_session(*args, **kwargs):
                calls.append(("action", args, kwargs))
                return True

        self.functions = FakeFunctions()
        self.functions.server.run_action_in_session = lambda **kwargs: {
            "status": "success",
            "data": {"observed": kwargs["action"]},
            "warnings": ["test warning"],
        }
        self.base_patch = patch.object(
            docassemble_compat, "_base_functions", return_value=self.functions
        )
        self.hook_patch = patch.object(
            docassemble_compat, "_pluggy_action_hook", return_value=None
        )
        self.base_patch.start()
        self.hook_patch.start()

    def tearDown(self):
        self.hook_patch.stop()
        self.base_patch.stop()

    def test_target_session_wrappers_use_stable_high_level_functions(self):
        target = docassemble_compat.create_target_session(
            "pkg:interview.yml", secret="secret", url_args={"test": "1"}
        )
        self.assertEqual(target.session_id, "session-123")
        self.assertEqual(
            docassemble_compat.get_target_variables(target), {"answer": 42}
        )
        docassemble_compat.set_target_variables(
            target,
            {"seeded": True},
            delete=["old"],
            overwrite=True,
            process_objects=True,
        )
        self.assertEqual(
            docassemble_compat.get_target_question(target)["questionName"], "intro"
        )
        self.assertEqual(docassemble_compat.go_back_target_session(target), "back")
        docassemble_compat.run_target_action(target, "inspect", read_only=True)

        set_call = next(call for call in self.calls if call[0] == "set")
        self.assertEqual(set_call[2]["delete"], ["old"])
        self.assertTrue(set_call[2]["overwrite"])
        action_call = next(call for call in self.calls if call[0] == "action")
        self.assertTrue(action_call[2]["read_only"])

    def test_raw_action_normalizes_19_server_and_prefers_110_hook(self):
        target = docassemble_compat.TargetSession("pkg:interview.yml", "session-123")
        result = docassemble_compat.run_target_action_raw(
            target, "al_weaver.inspect_object"
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data, {"observed": "al_weaver.inspect_object"})
        self.assertEqual(result.warnings, ["test warning"])

        captured = {}

        def hook(**kwargs):
            captured.update(kwargs)
            return {"status": "success", "data": {"hook": True}}

        target = docassemble_compat.TargetSession("pkg:interview.yml", "session-123")
        with patch.object(docassemble_compat, "_pluggy_action_hook", return_value=hook):
            result = docassemble_compat.run_target_action_raw(target, "inspect")

        self.assertEqual(result.data, {"hook": True})
        self.assertTrue(captured["read_only"])

    def test_every_target_session_call_gets_the_runtime_thread_context(self):
        """Actions need the same thread context the other wrappers install.

        Without it Docassemble runs an allowlisted ``al_weaver.inspect_*``
        action with no ``current_info`` and no guarantee that custom datatypes
        are registered, unlike the identical question and variable reads.
        """
        entered = []
        target = docassemble_compat.TargetSession("pkg:interview.yml", "session-123")

        @contextmanager
        def counting_context():
            entered.append(True)
            yield

        with patch.object(docassemble_compat, "_runtime_context", counting_context):
            docassemble_compat.run_target_action(target, "inspect")
            docassemble_compat.run_target_action_raw(target, "inspect")

        self.assertEqual(len(entered), 2)

    def test_custom_datatype_discovery_is_skipped_when_docassemble_loaded_them(self):
        """Docassemble's own startup import is what normally registers these.

        Repeating its filesystem walk on a server that already has custom
        datatypes would read every installed package on the first debugger
        click for nothing.
        """
        self.functions.custom_types = {"al_phone": object()}
        with (
            patch.object(docassemble_compat, "_CUSTOM_DATATYPES_LOADED", False),
            patch.object(docassemble_compat, "_import_custom_datatype_modules") as scan,
        ):
            docassemble_compat._load_custom_datatypes()
            self.assertFalse(scan.called)

        self.functions.custom_types = {}
        with (
            patch.object(docassemble_compat, "_CUSTOM_DATATYPES_LOADED", False),
            patch.object(docassemble_compat, "_import_custom_datatype_modules") as scan,
        ):
            docassemble_compat._load_custom_datatypes()
            docassemble_compat._load_custom_datatypes()
            self.assertEqual(scan.call_count, 1)

    def test_docx_jinja_environment_uses_installed_docassemble_layout(self):
        environment = docassemble_compat.create_docx_jinja_environment(
            undefined=DebugUndefined
        )

        self.assertIs(environment.undefined, DebugUndefined)
        self.assertIn("ampersand_filter", environment.filters)


class TestWebappAccessors(unittest.TestCase):
    """The webapp internals the Weaver needs moved between 1.9.x and 1.10.x."""

    LAYOUT_19 = {
        "docassemble.webapp.app_object": {"app": "flask-app", "csrf": "csrf"},
        "docassemble.webapp.daredis": {"r": "redis"},
        "docassemble.webapp.server": {"r": "redis", "api_verify": "api-verify"},
        "docassemble.webapp.worker_common": {
            "workerapp": "worker",
            "bg_context": nullcontext,
        },
    }
    LAYOUT_110 = {
        "docassemble.webapp.app_object": {"flaskapp": "flask-app"},
        "docassemble.webapp.extensions": {"csrf": "csrf"},
        "docassemble.webapp.daredis": {"r": "redis"},
        "docassemble.webapp.api.helpers": {"api_verify": "api-verify"},
        "docassemble.webapp.worker_common": {"workerapp": "worker"},
        "docassemble.webapp.tasks.context": {"bg_context": nullcontext},
    }

    @contextmanager
    def _layout(self, modules):
        """Present exactly one Docassemble layout, with nothing else installed."""
        stubs = {}
        for module_name, attributes in modules.items():
            module = types.ModuleType(module_name)
            for name, value in attributes.items():
                setattr(module, name, value)
            stubs[module_name] = module
        removed = {
            name: module
            for name, module in sys.modules.items()
            if name.startswith("docassemble.webapp") and name not in stubs
        }
        for name in removed:
            del sys.modules[name]
        try:
            with patch.dict(sys.modules, stubs, clear=False):
                with patch.object(
                    docassemble_compat.importlib,
                    "import_module",
                    side_effect=ImportError("not installed"),
                ):
                    yield
        finally:
            sys.modules.update(removed)

    def _resolve_all(self):
        return {
            "app": docassemble_compat.get_flask_app(),
            "csrf": docassemble_compat.get_csrf(),
            "redis": docassemble_compat.get_redis_client(),
            "api_verify": docassemble_compat.get_api_verify(),
            "worker": docassemble_compat.get_worker_app(),
        }

    def test_accessors_resolve_against_both_docassemble_layouts(self):
        expected = {
            "app": "flask-app",
            "csrf": "csrf",
            "redis": "redis",
            "api_verify": "api-verify",
            "worker": "worker",
        }
        for label, layout in (("1.9.x", self.LAYOUT_19), ("1.10.x", self.LAYOUT_110)):
            with self.subTest(layout=label):
                with self._layout(layout):
                    self.assertEqual(self._resolve_all(), expected)

    def test_background_context_is_found_in_both_layouts(self):
        for label, layout in (("1.9.x", self.LAYOUT_19), ("1.10.x", self.LAYOUT_110)):
            with self.subTest(layout=label):
                with self._layout(layout):
                    with docassemble_compat.background_context():
                        pass

    def test_missing_capability_raises_compatibility_error(self):
        with self._layout({}):
            with self.assertRaises(docassemble_compat.DocassembleCompatibilityError):
                docassemble_compat.get_flask_app()

    def test_already_imported_modules_are_preferred_over_new_imports(self):
        """Probing must never import a webapp module the process is not using."""
        stub = types.ModuleType("docassemble.webapp.server")
        stub.r = "redis-from-loaded-module"
        with patch.dict(sys.modules, {"docassemble.webapp.server": stub}, clear=False):
            imported = []

            def record(module_name):
                imported.append(module_name)
                raise ImportError(module_name)

            with patch.object(
                docassemble_compat.importlib, "import_module", side_effect=record
            ):
                self.assertEqual(
                    docassemble_compat._first_webapp_attr(
                        (
                            ("docassemble.webapp.daredis", "r"),
                            ("docassemble.webapp.server", "r"),
                        ),
                        "its Redis client",
                    ),
                    "redis-from-loaded-module",
                )
            self.assertEqual(imported, [])

    def test_initialize_interview_context_falls_back_to_19x_locations(self):
        """1.9.x has neither ``docassemble.base.thread_context`` nor
        ``docassemble.webapp.utils.helpers`` — confirmed against the real
        upstream source at v1.9.13 in
        ``test_19_and_110_session_contracts_when_checkout_available``. On
        1.9.x, ``this_thread`` lives on ``docassemble.base.functions`` and
        ``current_info`` lives on ``docassemble.webapp.server``. Without this
        fallback ``this_thread.current_info`` is silently never populated on
        a 1.9.x server, and Docassemble's own session creation (which reads
        ``this_thread.current_info['user']['device_id']`` unconditionally)
        breaks in ways that surface as unrelated-looking interview errors.
        """
        functions_stub = types.ModuleType("docassemble.base.functions")
        this_thread = types.SimpleNamespace()
        functions_stub.this_thread = this_thread

        captured = {}

        def fake_current_info(**kwargs):
            captured.update(kwargs)
            return {"user": {"device_id": kwargs["device_id"]}}

        layout = dict(self.LAYOUT_19)
        layout["docassemble.webapp.server"] = dict(layout["docassemble.webapp.server"])
        layout["docassemble.webapp.server"]["current_info"] = fake_current_info

        removed_base = {}
        if "docassemble.base.thread_context" in sys.modules:
            removed_base["docassemble.base.thread_context"] = sys.modules.pop(
                "docassemble.base.thread_context"
            )

        app = Flask(__name__)
        try:
            with self._layout(layout):
                with patch.dict(
                    sys.modules,
                    {"docassemble.base.functions": functions_stub},
                    clear=False,
                ):
                    with app.test_request_context("/"):
                        with patch("flask_login.current_user") as mock_user:
                            mock_user.id = 7
                            docassemble_compat.initialize_interview_context()
        finally:
            sys.modules.update(removed_base)

        self.assertEqual(
            this_thread.current_info, {"user": {"device_id": "alweaver-runtime"}}
        )
        self.assertEqual(captured["session_uid"], "7")

    def test_runtime_context_degrades_when_thread_context_is_missing(self):
        """``_runtime_context`` must not require the 1.10.x-only module."""
        removed_base = {}
        if "docassemble.base.thread_context" in sys.modules:
            removed_base["docassemble.base.thread_context"] = sys.modules.pop(
                "docassemble.base.thread_context"
            )
        try:
            with self._layout({}):
                with (
                    patch.object(
                        docassemble_compat, "initialize_interview_context"
                    ),
                    patch.object(docassemble_compat, "_load_custom_datatypes"),
                ):
                    with docassemble_compat._runtime_context():
                        pass
        finally:
            sys.modules.update(removed_base)


class TestNativeGithubCompatibility(unittest.TestCase):
    def test_repository_snapshot_uses_one_archive_download(self):
        archive_buffer = io.BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            for path, content in (
                (
                    "repo-root/docassemble/PublicForms/data/questions/main.yml",
                    b"question: Hello\n",
                ),
                ("repo-root/README.md", b"ignored"),
            ):
                info = tarfile.TarInfo(path)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))

        class FakeHttp:
            def __init__(self):
                self.calls = []

            def request(self, url, method, headers=None, body=None):
                self.calls.append((url, method))
                if url.endswith("/tarball/commit-sha"):
                    return {"status": "200"}, archive_buffer.getvalue()
                if "/commits/main" in url:
                    return {"status": "200"}, b'{"sha": "commit-sha"}'
                return {
                    "status": "200"
                }, b'{"default_branch": "main", "private": false}'

        http = FakeHttp()
        with patch.object(
            docassemble_compat, "_github_authorized_http", return_value=http
        ):
            result = docassemble_compat.get_github_repository_snapshot(
                repository_url="https://github.com/OtherOrg/docassemble-PublicForms",
                user_id=7,
            )

        self.assertEqual(result["sha"], "commit-sha")
        self.assertEqual(
            result["files"],
            {"docassemble/PublicForms/data/questions/main.yml": b"question: Hello\n"},
        )
        self.assertEqual(len(http.calls), 3)
        self.assertFalse(any("/git/blobs/" in url for url, _method in http.calls))

    def test_public_snapshot_needs_no_github_api_or_oauth_connection(self):
        archive_buffer = io.BytesIO()
        content = b"question: Public interview\n"
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo(
                "repo-root/docassemble/PublicForms/data/questions/main.yml"
            )
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

        class FakeHttp:
            def __init__(self):
                self.calls = []

            def request(self, url, method, headers=None, body=None):
                self.calls.append(url)
                return {"status": "200"}, archive_buffer.getvalue()

        http = FakeHttp()
        with (
            patch.object(
                docassemble_compat,
                "_github_authorized_http",
                side_effect=docassemble_compat.GithubCredentialError("not connected"),
            ),
            patch.object(
                docassemble_compat.importlib,
                "import_module",
                return_value=types.SimpleNamespace(Http=lambda: http),
            ),
            patch.object(
                docassemble_compat.subprocess,
                "run",
                return_value=types.SimpleNamespace(
                    returncode=0,
                    stdout="a" * 40 + "\tHEAD\n",
                    stderr="",
                ),
            ) as ls_remote,
        ):
            result = docassemble_compat.get_github_repository_snapshot(
                repository_url="https://github.com/OtherOrg/docassemble-PublicForms",
                user_id=7,
            )

        self.assertEqual(result["branch"], "HEAD")
        self.assertEqual(result["sha"], "a" * 40)
        self.assertEqual(len(http.calls), 1)
        self.assertTrue(http.calls[0].startswith("https://codeload.github.com/"))
        self.assertNotIn("api.github.com", http.calls[0])
        ls_remote.assert_called_once()

    def test_public_snapshot_reports_git_resolution_failures(self):
        failures = (
            (
                subprocess.TimeoutExpired(["git", "ls-remote"], 30),
                "took too long",
            ),
            (OSError("git could not start"), "could not run Git"),
        )
        for failure, message in failures:
            with self.subTest(failure=type(failure).__name__):
                with (
                    patch.object(
                        docassemble_compat,
                        "_github_authorized_http",
                        side_effect=docassemble_compat.GithubCredentialError(
                            "not connected"
                        ),
                    ),
                    patch.object(
                        docassemble_compat.importlib,
                        "import_module",
                        return_value=types.SimpleNamespace(Http=lambda: object()),
                    ),
                    patch.object(
                        docassemble_compat.subprocess,
                        "run",
                        side_effect=failure,
                    ),
                ):
                    with self.assertRaisesRegex(
                        docassemble_compat.DocassembleCompatibilityError, message
                    ):
                        docassemble_compat.get_github_repository_snapshot(
                            repository_url=(
                                "https://github.com/OtherOrg/docassemble-PublicForms"
                            ),
                            user_id=7,
                        )

    def test_repository_snapshot_rejects_nested_data_files(self):
        archive_buffer = io.BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            for path, content in (
                (
                    "repo-root/docassemble/PublicForms/data/questions/main.yml",
                    b"question: Hello\n",
                ),
                (
                    "repo-root/docassemble/PublicForms/data/static/images/logo.svg",
                    b"<svg></svg>",
                ),
            ):
                info = tarfile.TarInfo(path)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))

        class FakeHttp:
            def request(self, url, method, headers=None, body=None):
                if url.endswith("/tarball/commit-sha"):
                    return {"status": "200"}, archive_buffer.getvalue()
                if "/commits/main" in url:
                    return {"status": "200"}, b'{"sha": "commit-sha"}'
                return {
                    "status": "200"
                }, b'{"default_branch": "main", "private": false}'

        with patch.object(
            docassemble_compat,
            "_github_authorized_http",
            return_value=FakeHttp(),
        ):
            with self.assertRaisesRegex(
                docassemble_compat.DocassembleCompatibilityError, "nested files"
            ):
                docassemble_compat.get_github_repository_snapshot(
                    repository_url=(
                        "https://github.com/OtherOrg/docassemble-PublicForms"
                    ),
                    user_id=7,
                )

    def test_repository_url_is_not_limited_to_connected_owner(self):
        parsed = docassemble_compat.normalize_github_repository_url(
            "https://github.com/CompletelyDifferentOrg/docassemble-Public.git"
        )
        self.assertEqual(parsed["owner"], "CompletelyDifferentOrg")
        self.assertEqual(
            parsed["url"],
            "https://github.com/CompletelyDifferentOrg/docassemble-Public",
        )
        with self.assertRaises(ValueError):
            docassemble_compat.normalize_github_repository_url(
                "https://example.com/not-github/repository"
            )

    def _app_for_layout(self, layout):
        app = Flask(f"github-{layout}")
        app.config["USE_GITHUB"] = True
        if layout == "1.10.x":
            app.add_url_rule(
                "/playground/github",
                endpoint="develop.github_menu",
                view_func=lambda: "github",
            )
        else:
            app.add_url_rule(
                "/github",
                endpoint="github_menu",
                view_func=lambda: "github",
            )
        return app

    def test_native_github_configuration_resolves_on_19_and_110(self):
        redis = types.SimpleNamespace(get=lambda key: b'{"shared": true, "orgs": true}')
        for layout in ("1.9.x", "1.10.x"):
            with self.subTest(layout=layout):
                app = self._app_for_layout(layout)
                with app.test_request_context("/"):
                    with (
                        patch.object(
                            docassemble_compat, "get_flask_app", return_value=app
                        ),
                        patch.object(
                            docassemble_compat,
                            "get_redis_client",
                            return_value=redis,
                        ),
                    ):
                        status = docassemble_compat.get_native_github_integration(7)

                self.assertTrue(status["enabled"])
                self.assertTrue(status["connected"])
                self.assertTrue(status["organizations_enabled"])
                self.assertTrue(status["configure_url"])

    def test_native_github_status_reports_disabled_configuration(self):
        app = self._app_for_layout("1.10.x")
        app.config["USE_GITHUB"] = False
        with app.test_request_context("/"):
            with patch.object(docassemble_compat, "get_flask_app", return_value=app):
                status = docassemble_compat.get_native_github_integration(7)
        self.assertFalse(status["enabled"])
        self.assertFalse(status["connected"])

    def test_publish_owners_include_personal_account_and_paginated_orgs(self):
        class FakeHttp:
            def __init__(self):
                self.responses = [
                    ({"status": "200"}, {"login": "ada"}),
                    (
                        {
                            "status": "200",
                            "link": '<https://api.github.com/user/orgs?page=2>; rel="next"',
                        },
                        [{"login": "LegalAid"}],
                    ),
                    ({"status": "200"}, [{"login": "CourtForms"}]),
                ]

            def request(self, url, method, headers=None, body=None):
                response, payload = self.responses.pop(0)
                return response, json.dumps(payload).encode()

        with patch.object(
            docassemble_compat, "_github_authorized_http", return_value=FakeHttp()
        ):
            owners = docassemble_compat.get_github_publish_owners()

        self.assertEqual(
            owners,
            [
                {"login": "ada", "type": "user"},
                {"login": "LegalAid", "type": "organization"},
                {"login": "CourtForms", "type": "organization"},
            ],
        )

    def test_malformed_github_credential_is_reported_as_expired_connection(self):
        class BrokenStorage:
            def __init__(self, **kwargs):
                pass

            def get(self):
                raise json.JSONDecodeError("Expecting value", "", 0)

        with patch.object(
            docassemble_compat,
            "_first_webapp_attr",
            return_value=BrokenStorage,
        ):
            with self.assertRaises(docassemble_compat.GithubCredentialError) as raised:
                docassemble_compat._github_authorized_http()

        self.assertIn("reconnect it in Docassemble", str(raised.exception))

    def test_background_github_credentials_are_loaded_for_explicit_user(self):
        requested_keys = []

        class FakeRedis:
            def get(self, key):
                requested_keys.append(key)
                return b'{"access_token": "worker-token"}'

        authorized_http = object()

        class FakeCredentials:
            invalid = False

            def authorize(self, http):
                self.http = http
                return authorized_http

        parsed_values = []

        class FakeCredentialFactory:
            @staticmethod
            def new_from_json(value):
                parsed_values.append(value)
                return FakeCredentials()

        def fake_import(module_name):
            if module_name == "oauth2client.client":
                return types.SimpleNamespace(Credentials=FakeCredentialFactory)
            if module_name == "httplib2":
                return types.SimpleNamespace(Http=lambda: object())
            raise AssertionError(f"Unexpected import: {module_name}")

        with (
            patch.object(
                docassemble_compat, "get_redis_client", return_value=FakeRedis()
            ),
            patch.object(
                docassemble_compat.importlib, "import_module", side_effect=fake_import
            ),
            patch.object(
                docassemble_compat,
                "_first_webapp_attr",
                side_effect=AssertionError(
                    "Background credential lookup must not use current_user storage"
                ),
            ),
        ):
            result = docassemble_compat._github_authorized_http(user_id=7)

        self.assertIs(result, authorized_http)
        self.assertEqual(requested_keys, ["da:github:userid:7"])
        self.assertEqual(parsed_values, ['{"access_token": "worker-token"}'])

    def test_missing_organization_repository_is_created_under_that_org(self):
        class FakeHttp:
            def __init__(self):
                self.calls = []

            def request(self, url, method, headers=None, body=None):
                self.calls.append((url, method, json.loads(body) if body else None))
                if method == "GET":
                    return {"status": "404"}, b'{"message": "Not Found"}'
                return (
                    {"status": "201"},
                    b'{"html_url": "https://github.com/LegalAid/docassemble-HousingForms"}',
                )

        http = FakeHttp()
        with (
            patch.object(
                docassemble_compat,
                "get_github_publish_owners",
                return_value=[
                    {"login": "ada", "type": "user"},
                    {"login": "LegalAid", "type": "organization"},
                ],
            ),
            patch.object(
                docassemble_compat, "_github_authorized_http", return_value=http
            ),
        ):
            repository = docassemble_compat.ensure_github_repository(
                owner="LegalAid",
                repository="docassemble-HousingForms",
                description="Housing forms",
            )

        self.assertEqual(
            http.calls[1],
            (
                "https://api.github.com/orgs/LegalAid/repos",
                "POST",
                {
                    "name": "docassemble-HousingForms",
                    "description": "Housing forms",
                    "auto_init": True,
                },
            ),
        )
        self.assertTrue(repository["created_by_weaver"])

    PACKAGE_INFO = {
        "dependencies": [],
        "description": "Housing forms",
        "license": "MIT License",
        "interview_files": ["main.yml"],
        "template_files": [],
        "module_files": [],
        "static_files": [],
        "sources_files": [],
    }

    def _fake_package_builder(self, filenames=("README.md",)):
        """Stand in for Docassemble's ``make_package_dir``.

        The real builder writes into the ``directory`` the caller supplies, so
        the fake must too — that is what lets Weaver clean up after a failure.
        """
        staging_directories = []

        def fake_make_package_dir(
            pkgname, info, author_info, directory=None, current_project="default"
        ):
            self.assertIsNotNone(directory, "Weaver must own the staging directory")
            staging_directories.append(directory)
            package_directory = Path(directory) / f"docassemble-{pkgname}"
            package_directory.mkdir()
            for filename in filenames:
                target = package_directory / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"# {filename}\n", encoding="utf-8")
            return directory

        return fake_make_package_dir, staging_directories

    def _publish(self, http, builder, **overrides):
        arguments = {
            "owner": "LegalAid",
            "repository": "docassemble-HousingForms",
            "package": "HousingForms",
            "project": "Housing",
            "user_id": 7,
            "package_info": dict(self.PACKAGE_INFO),
            "author_name": "Ada",
            "author_email": "ada@example.com",
            "branch": "main",
            "commit_message": "Publish housing forms",
        }
        arguments.update(overrides)
        with (
            patch.object(
                docassemble_compat, "_first_webapp_attr", return_value=builder
            ),
            patch.object(
                docassemble_compat, "_github_authorized_http", return_value=http
            ) as authorized,
        ):
            result = docassemble_compat.publish_github_package(**arguments)
        authorized.assert_called_once_with(user_id=arguments["user_id"])
        return result

    @staticmethod
    def _body_for(http, suffix, method="POST"):
        return next(
            body
            for url, called_method, body in http.calls
            if called_method == method and url.endswith(suffix)
        )

    def test_publish_github_package_creates_a_commit_on_a_new_branch(self):
        builder, staging_directories = self._fake_package_builder()

        class FakeHttp:
            def __init__(self):
                self.calls = []

            def request(self, url, method, headers=None, body=None):
                parsed_body = json.loads(body) if body else None
                self.calls.append((url, method, parsed_body))
                if method == "GET":
                    return {"status": "404"}, b'{"message": "Not Found"}'
                if url.endswith("/git/blobs"):
                    return {"status": "201"}, b'{"sha": "blob-sha"}'
                if url.endswith("/git/trees"):
                    return {"status": "201"}, b'{"sha": "tree-sha"}'
                if url.endswith("/git/commits"):
                    return {"status": "201"}, b'{"sha": "commit-sha"}'
                return {"status": "201"}, b'{"ref": "refs/heads/main"}'

        http = FakeHttp()
        result = self._publish(http, builder)

        self.assertEqual(result, {"sha": "commit-sha", "branch": "main", "files": 1})
        self.assertEqual(http.calls[0][1], "GET")
        self.assertEqual(http.calls[-1][1], "POST")
        self.assertEqual(http.calls[-1][2]["ref"], "refs/heads/main")
        self.assertTrue(staging_directories)
        self.assertFalse(Path(staging_directories[0]).exists())

    def test_publish_github_package_initializes_an_empty_repository(self):
        """A repository Weaver just created has no commits.

        GitHub answers git-data reads on such a repository with 409 "Git
        Repository is empty", including blob writes.  The Contents API can
        create the required initial commit before the Git Database upload.
        """
        builder, _staging = self._fake_package_builder()

        class FakeHttp:
            def __init__(self):
                self.calls = []

            def request(self, url, method, headers=None, body=None):
                parsed_body = json.loads(body) if body else None
                self.calls.append((url, method, parsed_body))
                if method == "GET":
                    return (
                        {"status": "409"},
                        b'{"message": "Git Repository is empty."}',
                    )
                if method == "PUT" and url.endswith("/contents/.gitkeep"):
                    return (
                        {"status": "201"},
                        b'{"commit": {"sha": "initial-commit-sha"}}',
                    )
                if url.endswith("/git/blobs"):
                    return {"status": "201"}, b'{"sha": "blob-sha"}'
                if url.endswith("/git/trees"):
                    return {"status": "201"}, b'{"sha": "tree-sha"}'
                if url.endswith("/git/commits"):
                    return {"status": "201"}, b'{"sha": "first-commit-sha"}'
                if method == "PATCH" and url.endswith("/git/refs/heads/main"):
                    return {"status": "200"}, b'{"ref": "refs/heads/main"}'
                return {"status": "400"}, b'{"message": "Unexpected call"}'

        http = FakeHttp()
        result = self._publish(http, builder, default_branch="main")

        self.assertEqual(
            result, {"sha": "first-commit-sha", "branch": "main", "files": 1}
        )
        self.assertEqual(
            self._body_for(http, "/contents/.gitkeep", method="PUT"),
            {
                "message": "Initialize repository for ALWeaver publishing",
                "content": "Cg==",
            },
        )
        commit_body = self._body_for(http, "/git/commits")
        self.assertEqual(commit_body["parents"], ["initial-commit-sha"])
        self.assertEqual(
            self._body_for(http, "/git/refs/heads/main", method="PATCH"),
            {"sha": "first-commit-sha", "force": False},
        )

    def test_publish_github_package_creates_new_branch_from_default_branch(self):
        builder, _staging = self._fake_package_builder()

        class FakeHttp:
            def __init__(self):
                self.calls = []

            def request(self, url, method, headers=None, body=None):
                parsed_body = json.loads(body) if body else None
                self.calls.append((url, method, parsed_body))
                if method == "GET":
                    if url.endswith("/git/ref/heads/feature/github"):
                        return {"status": "404"}, b'{"message": "Not Found"}'
                    if url.endswith("/git/ref/heads/main"):
                        return (
                            {"status": "200"},
                            b'{"object": {"sha": "main-commit-sha"}}',
                        )
                if url.endswith("/git/blobs"):
                    return {"status": "201"}, b'{"sha": "blob-sha"}'
                if url.endswith("/git/trees"):
                    return {"status": "201"}, b'{"sha": "tree-sha"}'
                if url.endswith("/git/commits"):
                    return {"status": "201"}, b'{"sha": "new-commit-sha"}'
                if url.endswith("/git/refs"):
                    return {"status": "201"}, b'{"ref": "refs/heads/feature/github"}'
                return {"status": "400"}, b'{"message": "Unexpected call"}'

        http = FakeHttp()
        result = self._publish(
            http,
            builder,
            branch="feature/github",
            default_branch="main",
            commit_message="Publish housing forms on new branch",
        )

        self.assertEqual(
            result, {"sha": "new-commit-sha", "branch": "feature/github", "files": 1}
        )
        self.assertEqual(
            self._body_for(http, "/git/commits")["parents"], ["main-commit-sha"]
        )
        self.assertEqual(http.calls[-1][1], "POST")
        self.assertEqual(
            http.calls[-1][0],
            "https://api.github.com/repos/LegalAid/docassemble-HousingForms/git/refs",
        )
        self.assertEqual(
            http.calls[-1][2],
            {"ref": "refs/heads/feature/github", "sha": "new-commit-sha"},
        )

    def test_publish_github_package_replaces_the_tree_so_deletions_propagate(self):
        """Publishing must not inherit the parent tree.

        The native publisher ran ``git add .`` inside a clone, so a file the
        author deleted or renamed in the Playground disappeared from the
        repository.  Passing ``base_tree`` here would silently keep it forever.
        """
        builder, _staging = self._fake_package_builder(
            filenames=("README.md", "setup.py")
        )

        class FakeHttp:
            def __init__(self):
                self.calls = []

            def request(self, url, method, headers=None, body=None):
                parsed_body = json.loads(body) if body else None
                self.calls.append((url, method, parsed_body))
                if method == "GET":
                    return (
                        {"status": "200"},
                        b'{"object": {"sha": "existing-commit-sha"}}',
                    )
                if url.endswith("/git/blobs"):
                    return {"status": "201"}, b'{"sha": "blob-sha"}'
                if url.endswith("/git/trees"):
                    return {"status": "201"}, b'{"sha": "tree-sha"}'
                if url.endswith("/git/commits"):
                    return {"status": "201"}, b'{"sha": "next-commit-sha"}'
                if method == "PATCH":
                    return {"status": "200"}, b'{"ref": "refs/heads/main"}'
                return {"status": "400"}, b'{"message": "Unexpected call"}'

        http = FakeHttp()
        result = self._publish(http, builder)

        self.assertEqual(result["files"], 2)
        tree_body = self._body_for(http, "/git/trees")
        self.assertNotIn("base_tree", tree_body)
        self.assertEqual(
            sorted(entry["path"] for entry in tree_body["tree"]),
            ["README.md", "setup.py"],
        )
        # The parent commit's tree is never read, so no extra round trip.
        self.assertFalse(
            [url for url, _method, _body in http.calls if "/git/commits/" in url]
        )
        self.assertEqual(
            self._body_for(http, "/git/commits")["parents"], ["existing-commit-sha"]
        )
        self.assertEqual(
            self._body_for(http, "/git/refs/heads/main", method="PATCH"),
            {"sha": "next-commit-sha", "force": False},
        )
        self.assertEqual(
            next(url for url, method, _body in http.calls if method == "PATCH"),
            "https://api.github.com/repos/LegalAid/docassemble-HousingForms/git/refs/heads/main",
        )

    def test_publish_github_package_attributes_the_commit_to_the_weaver_user(self):
        builder, _staging = self._fake_package_builder()

        class FakeHttp:
            def __init__(self):
                self.calls = []

            def request(self, url, method, headers=None, body=None):
                parsed_body = json.loads(body) if body else None
                self.calls.append((url, method, parsed_body))
                if method == "GET":
                    return {"status": "404"}, b'{"message": "Not Found"}'
                if url.endswith("/git/blobs"):
                    return {"status": "201"}, b'{"sha": "blob-sha"}'
                if url.endswith("/git/trees"):
                    return {"status": "201"}, b'{"sha": "tree-sha"}'
                if url.endswith("/git/commits"):
                    return {"status": "201"}, b'{"sha": "commit-sha"}'
                return {"status": "201"}, b'{"ref": "refs/heads/main"}'

        http = FakeHttp()
        self._publish(http, builder)

        commit_body = self._body_for(http, "/git/commits")
        expected = {"name": "Ada", "email": "ada@example.com"}
        self.assertEqual(commit_body["author"], expected)
        self.assertEqual(commit_body["committer"], expected)

    def test_publish_github_package_reports_progress_for_every_file(self):
        """The Celery job surfaces this while the browser polls."""
        builder, _staging = self._fake_package_builder(
            filenames=("README.md", "setup.py")
        )

        class FakeHttp:
            def request(self, url, method, headers=None, body=None):
                if method == "GET":
                    return {"status": "404"}, b'{"message": "Not Found"}'
                if url.endswith("/git/blobs"):
                    return {"status": "201"}, b'{"sha": "blob-sha"}'
                if url.endswith("/git/trees"):
                    return {"status": "201"}, b'{"sha": "tree-sha"}'
                if url.endswith("/git/commits"):
                    return {"status": "201"}, b'{"sha": "commit-sha"}'
                return {"status": "201"}, b'{"ref": "refs/heads/main"}'

        reported = []
        self._publish(
            FakeHttp(),
            builder,
            on_progress=lambda message, percent: reported.append((message, percent)),
        )

        messages = [message for message, _percent in reported]
        self.assertIn("Uploading README.md (1 of 2).", messages)
        self.assertIn("Uploading setup.py (2 of 2).", messages)
        self.assertIn("Creating the commit.", messages)
        percents = [percent for _message, percent in reported]
        self.assertEqual(percents, sorted(percents))
        self.assertTrue(all(0 <= percent <= 100 for percent in percents))

    def test_publish_github_package_survives_a_failing_progress_hook(self):
        builder, _staging = self._fake_package_builder()

        class FakeHttp:
            def request(self, url, method, headers=None, body=None):
                if method == "GET":
                    return {"status": "404"}, b'{"message": "Not Found"}'
                if url.endswith("/git/blobs"):
                    return {"status": "201"}, b'{"sha": "blob-sha"}'
                if url.endswith("/git/trees"):
                    return {"status": "201"}, b'{"sha": "tree-sha"}'
                if url.endswith("/git/commits"):
                    return {"status": "201"}, b'{"sha": "commit-sha"}'
                return {"status": "201"}, b'{"ref": "refs/heads/main"}'

        def exploding_progress(message, percent):
            raise RuntimeError("Redis is down")

        result = self._publish(FakeHttp(), builder, on_progress=exploding_progress)

        self.assertEqual(result["sha"], "commit-sha")

    def test_publish_github_package_cleans_up_when_the_package_build_fails(self):
        staging_directories = []

        def exploding_make_package_dir(
            pkgname, info, author_info, directory=None, current_project="default"
        ):
            staging_directories.append(directory)
            (Path(directory) / "partial-copy.txt").write_text("x", encoding="utf-8")
            raise RuntimeError("disk full")

        with self.assertRaises(RuntimeError):
            self._publish(object(), exploding_make_package_dir)

        self.assertTrue(staging_directories)
        self.assertFalse(Path(staging_directories[0]).exists())


class TestDocassembleSourceCompatibility(unittest.TestCase):
    def test_private_webapp_imports_are_isolated_to_compatibility_module(self):
        package_dir = Path(__file__).resolve().parent
        violations = []
        for path in package_dir.glob("*.py"):
            if path.name == "docassemble_compat.py" or path.name.startswith("test_"):
                continue
            for line_number, line in enumerate(path.read_text().splitlines(), start=1):
                if (
                    "from docassemble.webapp" in line
                    or "import docassemble.webapp" in line
                ):
                    violations.append(f"{path.name}:{line_number}: {line.strip()}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_19_and_110_session_contracts_when_checkout_available(self):
        repo_dir = Path(__file__).resolve().parents[2]
        checkout = Path(
            os.environ.get(
                "DOCASSEMBLE_SOURCE_CHECKOUT", str(repo_dir.parent / "docassemble")
            )
        )
        if not (checkout / ".git").is_dir():
            self.skipTest("Set DOCASSEMBLE_SOURCE_CHECKOUT to verify upstream APIs")

        functions_path = "docassemble_base/docassemble/base/functions.py"
        expected_signatures = (
            "def create_session(yaml_filename, secret=None, url_args=None):",
            "def get_session_variables(yaml_filename, session_id, secret=None, simplify=True):",
            "def set_session_variables(yaml_filename, session_id, variables, secret=None, question_name=None, overwrite=False, process_objects=False, delete=None):",
            "def run_action_in_session(yaml_filename, session_id, action, arguments=None, secret=None, persistent=False, overwrite=False, read_only=False):",
            "def get_question_data(yaml_filename, session_id, secret=None):",
            "def go_back_in_session(yaml_filename, session_id, secret=None):",
        )
        for ref in ("v1.9.0", "v1.9.13", "v1.10.0", "v1.10.7"):
            result = subprocess.run(
                ["git", "-C", str(checkout), "show", f"{ref}:{functions_path}"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{ref}: {result.stderr}")
            for signature in expected_signatures:
                self.assertIn(signature, result.stdout, f"{ref}: {signature}")

        hooks_result = subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "show",
                "v1.10.7:docassemble_base/docassemble/base/hooks.py",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(hooks_result.returncode, 0, hooks_result.stderr)
        self.assertIn("def server_run_action_in_session(**kwargs)", hooks_result.stdout)

        context_locations = {
            "v1.9.13": "docassemble_webapp/docassemble/webapp/worker_common.py",
            "v1.10.7": "docassemble_webapp/docassemble/webapp/tasks/context.py",
        }
        for ref, context_path in context_locations.items():
            result = subprocess.run(
                ["git", "-C", str(checkout), "show", f"{ref}:{context_path}"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{ref}: {result.stderr}")
            self.assertIn("def bg_context()", result.stdout)

        webapp_symbols = {
            "v1.9.13": (
                ("app_object.py", "app, csrf = create_app()"),
                ("server.py", "from docassemble.webapp.daredis import r"),
                ("server.py", "def api_verify("),
            ),
            "v1.10.7": (
                ("app_object.py", "flaskapp = Flask(__name__)"),
                ("extensions.py", "csrf = CSRFProtect()"),
                ("daredis.py", "r = redis."),
                ("api/helpers.py", "def api_verify("),
                ("worker_common.py", "celery_app as workerapp"),
            ),
        }
        for ref, expectations in webapp_symbols.items():
            for module_path, snippet in expectations:
                result = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(checkout),
                        "show",
                        f"{ref}:docassemble_webapp/docassemble/webapp/{module_path}",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, f"{ref}: {result.stderr}")
                self.assertIn(snippet, result.stdout, f"{ref}:{module_path}")

        github_publishers = {
            "v1.9.13": (
                "server.py",
                "@app.route('/createplaygroundpackage'",
            ),
            "v1.10.7": (
                "develop/views.py",
                "@develop_bp.route('/createplaygroundpackage'",
            ),
        }
        for ref, (module_path, route_snippet) in github_publishers.items():
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "show",
                    f"{ref}:docassemble_webapp/docassemble/webapp/{module_path}",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{ref}: {result.stderr}")
            self.assertIn(route_snippet, result.stdout, f"{ref}:{module_path}")
            self.assertIn("def create_playground_package():", result.stdout)
            self.assertIn("da:using_github:userid:", result.stdout)


if __name__ == "__main__":
    unittest.main()

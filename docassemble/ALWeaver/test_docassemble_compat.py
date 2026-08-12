# do not pre-load

from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from flask import Flask
from jinja2 import DebugUndefined

from . import docassemble_compat


class TestDocassembleCompatibilityInterface(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls

        class FakeFunctions:
            server = types.SimpleNamespace()

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


class TestNativeGithubCompatibility(unittest.TestCase):
    def _app_for_layout(self, layout):
        app = Flask(f"github-{layout}")
        app.config["USE_GITHUB"] = True
        if layout == "1.10.x":
            app.add_url_rule(
                "/playground/github",
                endpoint="develop.github_menu",
                view_func=lambda: "github",
            )
            app.add_url_rule(
                "/playground/package/create",
                endpoint="develop.create_playground_package",
                view_func=lambda: "publish",
            )
        else:
            app.add_url_rule(
                "/github",
                endpoint="github_menu",
                view_func=lambda: "github",
            )
            app.add_url_rule(
                "/createplaygroundpackage",
                endpoint="create_playground_package",
                view_func=lambda: "publish",
            )
        return app

    def test_native_github_endpoints_resolve_on_19_and_110(self):
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
                        publish_url = docassemble_compat.native_github_publish_url(
                            project="Housing",
                            package="HousingForms",
                            branch="feature/github",
                            commit_message="Update interview",
                        )

                self.assertTrue(status["available"])
                self.assertTrue(status["connected"])
                self.assertTrue(status["organizations_enabled"])
                self.assertTrue(status["configure_url"])
                query = parse_qs(urlsplit(publish_url).query)
                self.assertEqual(query["project"], ["Housing"])
                self.assertEqual(query["package"], ["HousingForms"])
                self.assertEqual(query["branch"], ["feature/github"])
                self.assertEqual(query["github"], ["1"])

    def test_native_github_status_reports_disabled_configuration(self):
        app = self._app_for_layout("1.10.x")
        app.config["USE_GITHUB"] = False
        with app.test_request_context("/"):
            with patch.object(docassemble_compat, "get_flask_app", return_value=app):
                status = docassemble_compat.get_native_github_integration(7)
        self.assertFalse(status["enabled"])
        self.assertFalse(status["connected"])
        self.assertFalse(status["available"])

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
                },
            ),
        )
        self.assertTrue(repository["created_by_weaver"])


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

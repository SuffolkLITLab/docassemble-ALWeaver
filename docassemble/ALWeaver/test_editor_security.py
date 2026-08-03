# do not pre load

from pathlib import Path
import types
import unittest
from unittest.mock import patch

from .test_editor_api import api_editor
from .worker_config import (
    CELERY_CONFIGURATION_DOCS_URL,
    CELERY_MODULE,
    get_worker_configuration_status,
    worker_configuration_is_ready,
)


class TestEditorSecurity(unittest.TestCase):
    def test_celery_preflight_is_actionable_and_never_raises(self):
        configured = {"celery modules": ["another.module", CELERY_MODULE]}
        self.assertTrue(worker_configuration_is_ready(configured))

        missing = get_worker_configuration_status({"celery modules": []})
        self.assertFalse(missing["configured"])
        self.assertEqual(missing["required_module"], CELERY_MODULE)
        self.assertEqual(missing["docs_url"], CELERY_CONFIGURATION_DOCS_URL)

        class BrokenConfig:
            def get(self, key, default=None):
                raise RuntimeError("configuration unavailable")

        failed = get_worker_configuration_status(BrokenConfig())
        self.assertEqual(failed["code"], "celery_configuration_check_failed")

    def test_browser_routes_have_no_csrf_exemptions_or_wildcard_cors(self):
        source = Path(api_editor.__file__).read_text()
        self.assertNotIn("@csrf.exempt", source)
        self.assertNotIn("@cross_origin", source)
        self.assertNotIn("from flask_cors", source)
        self.assertNotIn('origins="*"', source)

    def test_only_admins_and_developers_are_authorized(self):
        cases = (
            (False, (), False),
            (True, ("user",), False),
            (True, ("developer",), True),
            (True, ("admin",), True),
        )
        for authenticated, roles, expected in cases:
            with self.subTest(authenticated=authenticated, roles=roles):
                user = types.SimpleNamespace(
                    is_authenticated=authenticated,
                    has_role=lambda *allowed: bool(set(roles) & set(allowed)),
                )
                with patch.object(api_editor, "current_user", user):
                    self.assertEqual(api_editor._editor_auth_check(), expected)

    def test_page_bootstrap_includes_security_and_worker_preflight_data(self):
        template = "<script>window.data = __EDITOR_BOOTSTRAP_JSON__;</script>"
        status = {
            "configured": False,
            "code": "celery_module_missing",
            "message": "Uploaded generation unavailable.",
            "docs_url": "https://example.test/setup",
        }
        user = types.SimpleNamespace(
            is_authenticated=True,
            id=7,
            email="developer@example.com",
            has_role=lambda *roles: "developer" in roles,
        )
        with (
            patch.object(api_editor, "current_user", user),
            patch.object(api_editor, "_get_template_content", return_value=template),
            patch.object(
                api_editor, "playground_list_projects", return_value=["default"]
            ),
            patch.object(api_editor, "generate_csrf", return_value="server-csrf-token"),
            patch.object(
                api_editor,
                "get_worker_configuration_status",
                return_value=status,
            ),
        ):
            with api_editor.app.test_request_context("/al/editor"):
                rendered = api_editor._render_editor_page()

        self.assertIn('"csrfToken": "server-csrf-token"', rendered)
        self.assertIn('"systemChecks"', rendered)
        self.assertIn('"celery_module_missing"', rendered)
        self.assertIn('"https://example.test/setup"', rendered)

    def test_editor_page_redirects_non_developers_before_rendering(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=False),
            patch.object(api_editor, "_get_template_content") as get_template,
        ):
            with api_editor.app.test_request_context("/al/editor"):
                response = api_editor.editor_page()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/user/sign-in", response.headers["Location"])
        get_template.assert_not_called()


if __name__ == "__main__":
    unittest.main()

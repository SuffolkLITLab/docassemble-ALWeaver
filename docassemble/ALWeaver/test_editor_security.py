from pathlib import Path
import types
import unittest
from unittest.mock import patch

from .test_editor_api import api_editor


class TestEditorSecurity(unittest.TestCase):
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

    def test_page_bootstrap_includes_server_generated_csrf_token(self):
        template = "<script>window.data = __EDITOR_BOOTSTRAP_JSON__;</script>"
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
        ):
            with api_editor.app.test_request_context("/al/editor"):
                rendered = api_editor._render_editor_page()
        self.assertIn('"csrfToken": "server-csrf-token"', rendered)

    def test_page_bootstrap_warns_before_unconfigured_celery_use(self):
        template = "<script>window.data = __EDITOR_BOOTSTRAP_JSON__;</script>"
        status = {
            "configured": False,
            "code": "celery_module_missing",
            "message": "Uploaded generation unavailable.",
            "docs_url": "https://example.test/setup",
        }
        with (
            patch.object(api_editor, "_get_template_content", return_value=template),
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_current_user_id", return_value=7),
            patch.object(api_editor, "playground_list_projects", return_value=[]),
            patch.object(api_editor, "generate_csrf", return_value="test-csrf"),
            patch.object(
                api_editor,
                "get_worker_configuration_status",
                return_value=status,
            ),
        ):
            with api_editor.app.test_request_context("/al/editor"):
                rendered = api_editor._render_editor_page()

        self.assertIn('"systemChecks"', rendered)
        self.assertIn('"celery_module_missing"', rendered)
        self.assertIn('"https://example.test/setup"', rendered)

    def test_editor_renders_accessible_celery_preflight_notice(self):
        package_dir = Path(api_editor.__file__).parent
        template = (package_dir / "data/templates/editor.html").read_text()
        controller = (package_dir / "data/static/editor.js").read_text()

        self.assertIn('id="editor-celery-warning"', template)
        self.assertIn('aria-live="polite"', template)
        self.assertIn("BOOT.systemChecks && BOOT.systemChecks.celery", controller)
        self.assertIn("renderSystemChecks();", controller)

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

    def test_controller_passes_bootstrap_csrf_to_api_client(self):
        editor_source = (
            Path(api_editor.__file__).parent / "data/static/editor.js"
        ).read_text()
        self.assertIn("csrfToken: BOOT.csrfToken || null", editor_source)


if __name__ == "__main__":
    unittest.main()

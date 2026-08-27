# do not pre-load

from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

from .test_editor_api import api_editor
from .worker_config import (
    CELERY_CONFIGURATION_DOCS_URL,
    CELERY_MODULE,
    add_celery_module_to_config_yaml,
    get_worker_configuration_status,
    worker_configuration_is_ready,
)


class TestEditorSecurity(unittest.TestCase):
    def test_celery_config_patcher_preserves_existing_layout_and_modules(self):
        source = (
            "# keep this hand-written config\n"
            "celery modules:\n"
            "  - docassemble.ALDashboard.api_dashboard_worker\n"
            "mail:\n"
            "  default sender: forms@example.test\n"
        )
        updated, changed = add_celery_module_to_config_yaml(source)
        self.assertTrue(changed)
        self.assertEqual(
            updated,
            "# keep this hand-written config\n"
            "celery modules:\n"
            "  - docassemble.ALDashboard.api_dashboard_worker\n"
            "  - docassemble.ALWeaver.api_weaver_worker\n"
            "mail:\n"
            "  default sender: forms@example.test\n",
        )
        unchanged, changed_again = add_celery_module_to_config_yaml(updated)
        self.assertFalse(changed_again)
        self.assertEqual(unchanged, updated)

    def test_celery_config_patcher_matches_existing_list_indentation(self):
        source = (
            "celery modules:\n"
            "    - docassemble.ALDashboard.api_dashboard_worker\n"
            "mail:\n"
            "    default sender: forms@example.test\n"
        )
        updated, changed = add_celery_module_to_config_yaml(source)
        self.assertTrue(changed)
        self.assertEqual(
            updated,
            "celery modules:\n"
            "    - docassemble.ALDashboard.api_dashboard_worker\n"
            "    - docassemble.ALWeaver.api_weaver_worker\n"
            "mail:\n"
            "    default sender: forms@example.test\n",
        )
        import yaml

        yaml.safe_load(updated)

    def test_celery_config_patcher_preserves_quoted_hash_in_value(self):
        source = 'celery modules: "docassemble.ALDashboard.api_dashboard_worker#tag"\n'
        updated, changed = add_celery_module_to_config_yaml(source)
        self.assertTrue(changed)
        self.assertEqual(
            updated,
            "celery modules:\n"
            '  - "docassemble.ALDashboard.api_dashboard_worker#tag"\n'
            "  - docassemble.ALWeaver.api_weaver_worker\n",
        )

    def test_celery_config_patcher_handles_inline_and_missing_settings(self):
        inline, changed = add_celery_module_to_config_yaml(
            "celery modules: [docassemble.ALDashboard.api_dashboard_worker] # jobs\n"
        )
        self.assertTrue(changed)
        self.assertEqual(
            inline,
            "celery modules: [docassemble.ALDashboard.api_dashboard_worker, "
            "docassemble.ALWeaver.api_weaver_worker] # jobs\n",
        )
        missing, changed = add_celery_module_to_config_yaml("redis: redis://redis\n")
        self.assertTrue(changed)
        self.assertEqual(
            missing,
            "redis: redis://redis\n"
            "celery modules:\n"
            "  - docassemble.ALWeaver.api_weaver_worker\n",
        )

    def test_celery_config_endpoint_is_admin_only_and_uses_precise_patch(self):
        with (
            patch.object(api_editor, "_editor_auth_check", return_value=True),
            patch.object(api_editor, "_editor_admin_check", return_value=False),
        ):
            with api_editor.app.test_request_context(
                "/al/editor/api/server/celery-config", method="POST", json={}
            ):
                self.assertEqual(
                    api_editor.editor_api_add_celery_config().status_code, 403
                )

        with TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / "config.yml"
            config_path.write_text(
                "celery modules:\n  - docassemble.ALDashboard.api_dashboard_worker\n"
                "mail:\n  default sender: forms@example.test\n"
            )
            with (
                patch.object(api_editor, "_editor_auth_check", return_value=True),
                patch.object(api_editor, "_editor_admin_check", return_value=True),
                patch.object(
                    api_editor,
                    "_celery_setup_capability",
                    return_value={"can_save": True},
                ),
                patch.object(
                    api_editor,
                    "_restart_capability",
                    return_value={"allowed": True, "reason": None},
                ),
                patch.object(api_editor, "_config_file_path", return_value=str(config_path)),
                patch.object(api_editor, "_write_config_source") as write_config,
                patch.object(api_editor, "restart_docassemble") as restart,
            ):
                with api_editor.app.test_request_context(
                    "/al/editor/api/server/celery-config", method="POST", json={}
                ):
                    response = api_editor.editor_api_add_celery_config()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["data"]["changed"])
            written_source = write_config.call_args.args[0]
            self.assertIn("docassemble.ALDashboard.api_dashboard_worker", written_source)
            self.assertIn(CELERY_MODULE, written_source)
            self.assertIn("mail:\n  default sender: forms@example.test\n", written_source)
            restart.assert_called_once_with()

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

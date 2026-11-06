# do not pre-load
"""Issue publication respects the connected project and acting user's credentials."""

from unittest.mock import patch
from types import SimpleNamespace

from .test_editor_api import api_editor
from . import docassemble_compat


def submit(**overrides):
    data = {
        "project": "default",
        "repository_url": "https://github.com/org/repo",
        "title": "Readiness",
        "body": "- [ ] Fix instructions",
    }
    data.update(overrides)
    with api_editor.app.test_request_context(
        "/al/editor/api/weaver/readiness/issue", method="POST", json=data
    ):
        return api_editor.editor_api_readiness_issue()


def test_issue_uses_stored_repository_and_actor_credentials():
    with patch.object(
        api_editor, "_editor_auth_check", return_value=True
    ), patch.object(api_editor, "_current_user_id", return_value=7), patch.object(
        api_editor, "_actor_user_id", return_value=9
    ), patch.object(
        api_editor,
        "find_project_github_sync",
        return_value={"repository_url": "https://github.com/org/repo"},
    ) as sync, patch.object(
        api_editor,
        "create_github_issue",
        return_value={"url": "https://github.com/org/repo/issues/3", "number": 3},
    ) as create:
        response = submit()
        assert response.json["success"]
        sync.assert_called_once_with(user_id=7, project_name="default")
        create.assert_called_once_with(
            repository_url="https://github.com/org/repo",
            title="Readiness",
            body="- [ ] Fix instructions",
            user_id=9,
        )


def test_issue_rejects_repository_switch_missing_connection_and_oversize_body():
    with patch.object(
        api_editor, "_editor_auth_check", return_value=True
    ), patch.object(api_editor, "_current_user_id", return_value=7), patch.object(
        api_editor,
        "find_project_github_sync",
        return_value={"repository_url": "https://github.com/org/repo"},
    ) as sync, patch.object(
        api_editor, "create_github_issue"
    ) as create:
        for data in [
            {"repository_url": "https://github.com/other/repo"},
            {"body": "x" * 60001},
            {"title": ""},
        ]:
            response = submit(**data)
            assert response.status_code == 400
        sync.return_value = None
        assert submit().status_code == 400
        create.assert_not_called()


def test_issue_requires_authentication():
    with patch.object(
        api_editor, "_editor_auth_check", return_value=False
    ), patch.object(api_editor, "create_github_issue") as create:
        assert submit().status_code in (401, 403)
        create.assert_not_called()


def test_github_issue_posts_full_markdown_once():
    with patch.object(
        docassemble_compat, "_github_authorized_http", return_value=object()
    ) as auth, patch.object(
        docassemble_compat,
        "_github_json_request",
        return_value=(SimpleNamespace(status=201), {"number": 4}),
    ) as request:
        result = docassemble_compat.create_github_issue(
            repository_url="https://github.com/org/repo",
            title="Readiness",
            body="- [ ] Fix\n\n## Sources",
            user_id=9,
        )
        auth.assert_called_once_with(user_id=9)
        assert request.call_count == 1
        assert request.call_args.args[1:] == (
            "https://api.github.com/repos/org/repo/issues",
            "POST",
            {"title": "Readiness", "body": "- [ ] Fix\n\n## Sources"},
        )
        assert result["url"] == "https://github.com/org/repo/issues/4"

"""Exercise the authorization boundary on every editor API route."""

import re
from unittest.mock import patch


class _User:
    def __init__(self, role):
        self.role = role
        self.is_authenticated = role != "anonymous"
        self.id = None if role == "anonymous" else 7

    def has_role(self, *roles):
        return self.role in roles


class _AuthorizedBoundaryReached(Exception):
    pass


def _request_path(rule):
    """Build an inert URL and placeholder arguments for a Flask route."""
    path = rule.rule
    kwargs = {}
    for name in rule.arguments:
        kwargs[name] = "matrix-auth-probe"
        path = re.sub(r"<(?:(?:path|string):)?" + name + r">", kwargs[name], path)
    return path, kwargs


def test_every_editor_api_method_enforces_role_boundary():
    from .test_editor_api import api_editor

    routes = [
        (rule, method)
        for rule in api_editor.app.url_map.iter_rules()
        if rule.rule.startswith("/al/editor/api/")
        for method in rule.methods or ()
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    ]
    assert len(routes) >= 80  # A new route must be included automatically.

    real_guard = api_editor._editor_auth_check
    for rule, method in routes:
        path, kwargs = _request_path(rule)
        view = api_editor.app.view_functions[rule.endpoint]
        for role in ("anonymous", "user", "developer", "admin"):
            user = _User(role)
            with (
                patch.object(api_editor, "current_user", user),
                api_editor.app.test_request_context(path, method=method),
            ):
                if role in {"anonymous", "user"}:
                    response = view(**kwargs)
                    assert response.status_code == 401, (path, method, role)
                    assert response.get_json()["error"]["type"] == "auth_error"
                else:

                    def stop_after_guard():
                        assert real_guard(), (path, method, role)
                        raise _AuthorizedBoundaryReached

                    with patch.object(
                        api_editor, "_editor_auth_check", side_effect=stop_after_guard
                    ):
                        try:
                            view(**kwargs)
                        except _AuthorizedBoundaryReached:
                            pass
                        else:
                            raise AssertionError(
                                f"Authorization guard missing: {method} {path} {role}"
                            )


def test_server_config_route_requires_admin_after_editor_access():
    from .test_editor_api import api_editor

    route = "/al/editor/api/server/celery-config"
    with (
        patch.object(api_editor, "current_user", _User("developer")),
        api_editor.app.test_request_context(route, method="POST"),
    ):
        response = api_editor.editor_api_add_celery_config()
        assert response.status_code == 403
        assert response.get_json()["error"]["type"] == "authorization_error"

    class _AdminReached(Exception):
        pass

    with (
        patch.object(api_editor, "current_user", _User("admin")),
        patch.object(api_editor, "_celery_setup_capability", side_effect=_AdminReached),
        api_editor.app.test_request_context(route, method="POST"),
    ):
        try:
            api_editor.editor_api_add_celery_config()
        except _AdminReached:
            pass
        else:
            raise AssertionError("Administrator did not pass the config route gate")

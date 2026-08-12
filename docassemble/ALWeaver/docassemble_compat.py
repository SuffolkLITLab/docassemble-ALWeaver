"""Weaver-owned compatibility boundary for Docassemble 1.9.x and 1.10.x."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import importlib
import importlib.metadata
import json
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from flask import Response, jsonify, url_for


class DocassembleCompatibilityError(RuntimeError):
    """Raised when the installed Docassemble lacks a required capability."""


@dataclass(frozen=True)
class DocassembleCapabilities:
    version: str
    has_pluggy_hooks: bool
    supports_read_only_actions: bool
    supports_raw_action_result: bool
    supports_session_question_data: bool


@dataclass(frozen=True)
class TargetSession:
    yaml_filename: str
    session_id: str
    secret: Optional[str] = field(default=None, repr=False)


@dataclass(frozen=True)
class TargetActionResult:
    status: str
    data: Any = None
    warnings: List[str] = field(default_factory=list)
    raw: Any = field(default=None, repr=False, compare=False)


def _base_functions() -> Any:
    return importlib.import_module("docassemble.base.functions")


def _docx_jinja_module() -> Any:
    """Return the module that owns Docassemble's DOCX Jinja integration."""
    try:
        module = importlib.import_module("docassemble.base.jinja")
    except ImportError:
        module = importlib.import_module("docassemble.base.parse")
    if not all(
        hasattr(module, name)
        for name in ("DAEnvironment", "DAExtension", "registered_jinja_filters")
    ):
        raise DocassembleCompatibilityError(
            "This Docassemble installation does not expose its DOCX Jinja environment"
        )
    return module


def create_docx_jinja_environment(*, undefined: Any) -> Any:
    """Create Docassemble's DOCX Jinja environment across 1.9.x and 1.10.x."""
    module = _docx_jinja_module()
    environment = module.DAEnvironment(
        undefined=undefined,
        extensions=[module.DAExtension],
    )
    environment.filters.update(module.registered_jinja_filters)
    builtin_filters = getattr(module, "builtin_jinja_filters", None)
    if builtin_filters is None:
        get_builtin_filters = getattr(module, "get_builtin_jinja_filters", None)
        if not callable(get_builtin_filters):
            raise DocassembleCompatibilityError(
                "This Docassemble installation does not expose its DOCX Jinja filters"
            )
        builtin_filters = get_builtin_filters()
    environment.filters.update(builtin_filters)
    return environment


def _first_webapp_attr(candidates: Sequence[Tuple[str, str]], capability: str) -> Any:
    """Return the first attribute that exists among (module, attribute) candidates.

    Private webapp modules are imported only inside this compatibility boundary.

    Docassemble 1.10.x moved several webapp internals out of
    ``docassemble.webapp.server`` and ``docassemble.webapp.app_object``, so each
    capability has to be looked up in more than one place. Modules that are
    already imported are preferred, so that probing for a capability never
    triggers the import of a heavyweight webapp module that this process does
    not otherwise use.
    """
    for module_name, attribute in candidates:
        module = sys.modules.get(module_name)
        value = getattr(module, attribute, None) if module is not None else None
        if value is not None:
            return value
    for module_name, attribute in candidates:
        if module_name in sys.modules:
            continue
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        value = getattr(module, attribute, None)
        if value is not None:
            return value
    raise DocassembleCompatibilityError(
        f"This Docassemble installation does not expose {capability}"
    )


def _docassemble_version() -> str:
    try:
        return importlib.metadata.version("docassemble.base")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _pluggy_action_hook() -> Any:
    try:
        hooks = importlib.import_module("docassemble.base.hooks")
    except ImportError:
        return None
    hook = getattr(hooks, "server_run_action_in_session", None)
    return hook if callable(hook) else None


def _legacy_raw_action() -> Any:
    functions = _base_functions()
    server = getattr(functions, "server", None)
    action = getattr(server, "run_action_in_session", None)
    return action if callable(action) else None


def get_capabilities() -> DocassembleCapabilities:
    functions = _base_functions()
    pluggy_hook = _pluggy_action_hook()
    legacy_action = _legacy_raw_action()
    return DocassembleCapabilities(
        version=_docassemble_version(),
        has_pluggy_hooks=pluggy_hook is not None,
        supports_read_only_actions=callable(
            getattr(functions, "run_action_in_session", None)
        ),
        supports_raw_action_result=pluggy_hook is not None or legacy_action is not None,
        supports_session_question_data=callable(
            getattr(functions, "get_question_data", None)
        ),
    )


def create_target_session(
    yaml_filename: str,
    *,
    secret: Optional[str] = None,
    url_args: Optional[Dict[str, Any]] = None,
) -> TargetSession:
    session_id = _base_functions().create_session(
        yaml_filename, secret=secret, url_args=url_args
    )
    return TargetSession(
        yaml_filename=yaml_filename,
        session_id=str(session_id),
        secret=secret,
    )


def get_target_variables(
    target: TargetSession, *, simplify: bool = True
) -> Dict[str, Any]:
    result = _base_functions().get_session_variables(
        target.yaml_filename,
        target.session_id,
        secret=target.secret,
        simplify=simplify,
    )
    if not isinstance(result, dict):
        raise DocassembleCompatibilityError(
            "Docassemble returned a non-dictionary session variable result"
        )
    return result


def set_target_variables(
    target: TargetSession,
    variables: Dict[str, Any],
    *,
    delete: Optional[List[str]] = None,
    overwrite: bool = False,
    process_objects: bool = False,
) -> None:
    _base_functions().set_session_variables(
        target.yaml_filename,
        target.session_id,
        variables,
        secret=target.secret,
        delete=delete,
        overwrite=overwrite,
        process_objects=process_objects,
    )


def get_target_question(target: TargetSession) -> Dict[str, Any]:
    result = _base_functions().get_question_data(
        target.yaml_filename, target.session_id, secret=target.secret
    )
    if not isinstance(result, dict):
        raise DocassembleCompatibilityError(
            "Docassemble returned a non-dictionary question result"
        )
    return result


def go_back_target_session(target: TargetSession) -> Any:
    return _base_functions().go_back_in_session(
        target.yaml_filename, target.session_id, secret=target.secret
    )


def run_target_action(
    target: TargetSession,
    action: str,
    *,
    arguments: Optional[Dict[str, Any]] = None,
    read_only: bool = True,
) -> None:
    _base_functions().run_action_in_session(
        target.yaml_filename,
        target.session_id,
        action,
        arguments=arguments or {},
        secret=target.secret,
        read_only=read_only,
    )


def _normalize_raw_action_result(result: Any) -> TargetActionResult:
    if isinstance(result, TargetActionResult):
        return result
    if isinstance(result, dict):
        status = str(result.get("status") or "success")
        if status != "success":
            raise DocassembleCompatibilityError(
                str(result.get("message") or "Docassemble action failed")
            )
        warnings_value = result.get("warnings") or []
        if isinstance(warnings_value, str):
            warnings = [warnings_value]
        else:
            warnings = [str(item) for item in warnings_value]
        data = result.get("data")
        if data is None:
            remaining = {
                key: value
                for key, value in result.items()
                if key not in {"status", "warnings", "message"}
            }
            data = remaining or None
        return TargetActionResult(
            status="success", data=data, warnings=warnings, raw=result
        )
    return TargetActionResult(status="success", data=result, raw=result)


def run_target_action_raw(
    target: TargetSession,
    action: str,
    *,
    arguments: Optional[Dict[str, Any]] = None,
    read_only: bool = True,
) -> TargetActionResult:
    kwargs = {
        "i": target.yaml_filename,
        "session": target.session_id,
        "secret": target.secret,
        "action": action,
        "persistent": False,
        "overwrite": False,
        "read_only": read_only,
        "arguments": arguments or {},
    }
    raw_action = _pluggy_action_hook() or _legacy_raw_action()
    if raw_action is None:
        raise DocassembleCompatibilityError(
            "This Docassemble installation does not expose raw session actions"
        )
    return _normalize_raw_action_result(raw_action(**kwargs))


def get_flask_app() -> Any:
    return _first_webapp_attr(
        (
            ("docassemble.webapp.app_object", "app"),
            ("docassemble.webapp.app_object", "flaskapp"),
            ("docassemble.webapp.flask_app", "flaskapp"),
            ("docassemble.webapp.server", "app"),
        ),
        "its Flask application",
    )


def get_csrf() -> Any:
    return _first_webapp_attr(
        (
            ("docassemble.webapp.app_object", "csrf"),
            ("docassemble.webapp.extensions", "csrf"),
        ),
        "its CSRF protection",
    )


def get_redis_client() -> Any:
    return _first_webapp_attr(
        (
            ("docassemble.webapp.daredis", "r"),
            ("docassemble.webapp.server", "r"),
        ),
        "its Redis client",
    )


def get_api_verify() -> Any:
    return _first_webapp_attr(
        (
            ("docassemble.webapp.api.helpers", "api_verify"),
            ("docassemble.webapp.server", "api_verify"),
        ),
        "its API authentication",
    )


def get_worker_app() -> Any:
    return _first_webapp_attr(
        (
            ("docassemble.webapp.worker_common", "workerapp"),
            ("docassemble.webapp.tasks.common", "celery_app"),
        ),
        "its Celery worker application",
    )


def background_context() -> AbstractContextManager[Any]:
    context_factory = _first_webapp_attr(
        (
            ("docassemble.webapp.worker_common", "bg_context"),
            ("docassemble.webapp.tasks.context", "bg_context"),
        ),
        "its background task context",
    )
    return context_factory()


def create_saved_file(*args: Any, **kwargs: Any) -> Any:
    saved_file = _first_webapp_attr(
        (
            ("docassemble.webapp.files", "SavedFile"),
            ("docassemble.webapp.files.savedfile", "SavedFile"),
        ),
        "its saved file storage",
    )
    return saved_file(*args, **kwargs)


def create_playground(*args: Any, **kwargs: Any) -> Any:
    playground = _first_webapp_attr(
        (("docassemble.webapp.playground", "Playground"),),
        "its playground storage",
    )
    return playground(*args, **kwargs)


def _first_endpoint_url(candidates: Sequence[str], **values: Any) -> Optional[str]:
    """Resolve a native Docassemble endpoint across the 1.9/1.10 split."""
    for endpoint in candidates:
        try:
            return str(url_for(endpoint, **values))
        except Exception:
            continue
    return None


def get_native_github_integration(user_id: int) -> Dict[str, Any]:
    """Describe Docassemble's built-in GitHub integration for one user.

    Docassemble 1.10 moved the developer views onto the ``develop`` blueprint;
    1.9 registered the same views as bare Flask endpoints.  Redis remains the
    authoritative source for whether this user enabled the native integration.
    """
    flask_app = get_flask_app()
    enabled = bool(flask_app.config.get("USE_GITHUB"))
    configure_url = _first_endpoint_url(
        (
            "develop.github_menu",
            "github_menu",
        )
    )
    publish_available = (
        _first_endpoint_url(
            (
                "develop.create_playground_package",
                "create_playground_package",
            )
        )
        is not None
    )
    connected = False
    organizations_enabled = False
    if enabled:
        try:
            raw_settings = get_redis_client().get(
                f"da:using_github:userid:{int(user_id)}"
            )
            connected = raw_settings is not None
            if raw_settings is not None:
                decoded_settings = (
                    raw_settings.decode()
                    if isinstance(raw_settings, bytes)
                    else str(raw_settings)
                )
                if decoded_settings == "1":
                    organizations_enabled = True
                else:
                    settings = json.loads(decoded_settings)
                    organizations_enabled = bool(settings.get("orgs"))
        except Exception:
            connected = False
            organizations_enabled = False
    return {
        "enabled": enabled,
        "connected": connected,
        "organizations_enabled": organizations_enabled,
        "available": enabled and publish_available,
        "configure_url": configure_url,
    }


def _github_authorized_http() -> Any:
    """Return Docassemble's authorized GitHub HTTP client."""
    storage_class = _first_webapp_attr(
        (
            (
                "docassemble.webapp.utils.redis_cred_storage",
                "RedisCredStorage",
            ),
            ("docassemble.webapp.server", "RedisCredStorage"),
        ),
        "its GitHub OAuth credential storage",
    )
    credentials = storage_class(oauth_app="github").get()
    if not credentials or getattr(credentials, "invalid", False):
        raise DocassembleCompatibilityError(
            "The GitHub connection has expired; reconnect it in Docassemble"
        )
    httplib2 = importlib.import_module("httplib2")
    return credentials.authorize(httplib2.Http())


def _github_json_request(
    http: Any, url: str, method: str = "GET", body: Optional[Dict[str, Any]] = None
) -> Tuple[Any, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    encoded_body = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        encoded_body = json.dumps(body)
    response, content = http.request(url, method, headers=headers, body=encoded_body)
    try:
        payload = json.loads(content.decode("utf-8")) if content else None
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    return response, payload


def _github_error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict) and payload.get("message"):
        return str(payload["message"])
    return fallback


def get_github_publish_owners() -> List[Dict[str, str]]:
    """List the personal account and organizations visible to GitHub OAuth."""
    http = _github_authorized_http()
    response, user = _github_json_request(http, "https://api.github.com/user")
    if int(response.get("status", 0)) != 200 or not isinstance(user, dict):
        raise DocassembleCompatibilityError(
            _github_error_message(user, "GitHub did not return the connected account")
        )
    user_login = str(user.get("login") or "").strip()
    if not user_login:
        raise DocassembleCompatibilityError(
            "GitHub did not return a username for the connected account"
        )

    owners = [{"login": user_login, "type": "user"}]
    url: Optional[str] = "https://api.github.com/user/orgs?per_page=100"
    while url:
        response, organizations = _github_json_request(http, url)
        if int(response.get("status", 0)) != 200 or not isinstance(organizations, list):
            raise DocassembleCompatibilityError(
                _github_error_message(
                    organizations, "GitHub did not return your organizations"
                )
            )
        owners.extend(
            {"login": str(org["login"]), "type": "organization"}
            for org in organizations
            if isinstance(org, dict) and org.get("login")
        )
        link_header = str(response.get("link") or "")
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        url = next_match.group(1) if next_match else None
    return owners


def ensure_github_repository(
    *, owner: str, repository: str, description: str = ""
) -> Dict[str, Any]:
    """Find or create a repository under a selected authenticated owner.

    Docassemble creates missing repositories only under ``/user/repos``.  For
    organizations, Weaver creates the empty repository first and then lets the
    native publisher perform all Git operations against it.
    """
    owners = get_github_publish_owners()
    selected = next(
        (
            item
            for item in owners
            if item["login"].casefold() == str(owner).strip().casefold()
        ),
        None,
    )
    if selected is None:
        raise ValueError("Choose a GitHub account or organization from the list")

    http = _github_authorized_http()
    encoded_owner = quote(selected["login"], safe="")
    encoded_repository = quote(repository, safe="")
    response, repo = _github_json_request(
        http, f"https://api.github.com/repos/{encoded_owner}/{encoded_repository}"
    )
    status = int(response.get("status", 0))
    if status == 200 and isinstance(repo, dict):
        if not (repo.get("permissions") or {}).get("push", True):
            raise DocassembleCompatibilityError(
                f"You do not have permission to push to {selected['login']}/{repository}"
            )
        repo["created_by_weaver"] = False
        return repo
    if status != 404:
        raise DocassembleCompatibilityError(
            _github_error_message(repo, "GitHub could not check the repository")
        )

    if selected["type"] == "organization":
        create_url = f"https://api.github.com/orgs/{encoded_owner}/repos"
    else:
        create_url = "https://api.github.com/user/repos"
    response, repo = _github_json_request(
        http,
        create_url,
        "POST",
        {"name": repository, "description": description},
    )
    if int(response.get("status", 0)) != 201 or not isinstance(repo, dict):
        raise DocassembleCompatibilityError(
            _github_error_message(
                repo,
                f"GitHub could not create {selected['login']}/{repository}",
            )
        )
    repo["created_by_weaver"] = True
    return repo


def native_github_publish_url(
    *, project: str, package: str, branch: str, commit_message: str
) -> str:
    """Build the native Playground GitHub publish URL on 1.9.x or 1.10.x."""
    result = _first_endpoint_url(
        (
            "develop.create_playground_package",
            "create_playground_package",
        ),
        project=project,
        package=package,
        github="1",
        branch=branch,
        commit_message=commit_message,
    )
    if result is None:
        raise DocassembleCompatibilityError(
            "This Docassemble installation does not expose its Playground GitHub publisher"
        )
    return result


def json_response(payload: Any, status: int = 200) -> Response:
    response = jsonify(payload)
    response.status_code = status
    return response


def json_error(
    message: str,
    status: int,
    *,
    code: str,
    details: Optional[Dict[str, Any]] = None,
) -> Response:
    return json_response(
        {
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
        },
        status,
    )

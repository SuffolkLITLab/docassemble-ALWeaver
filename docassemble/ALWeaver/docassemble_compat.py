"""Weaver-owned compatibility boundary for Docassemble 1.9.x and 1.10.x."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import base64
import importlib
import importlib.metadata
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlparse

from flask import Response, jsonify, url_for


class DocassembleCompatibilityError(RuntimeError):
    """Raised when the installed Docassemble lacks a required capability."""


class GithubCredentialError(DocassembleCompatibilityError):
    """Raised when Docassemble's stored GitHub OAuth credential is unusable."""


# GitHub answers 404 for a missing ref, but 409 ("Git Repository is empty") for
# every git-data read against a repository that has no commits yet — which is
# exactly the repository Weaver just created for a first publish.  Both mean
# "there is nothing to build on", not "something went wrong".
_GITHUB_NO_SUCH_REF_STATUSES = frozenset({404, 409})


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


def _optional_webapp_attr(candidates: Sequence[Tuple[str, str]]) -> Any:
    """Like :func:`_first_webapp_attr` but returns ``None`` instead of raising.

    Used for the restart machinery, which an installation is allowed not to
    have: a server with restarting disabled should degrade to an explanation,
    not a 500.
    """
    try:
        return _first_webapp_attr(candidates, "this capability")
    except BaseException:  # pylint: disable=broad-except
        # Importing a webapp module can do more than fail: reading the server
        # configuration calls sys.exit when there is no config file. An
        # optional capability must not take the caller down with it.
        return None


def full_package_directory() -> Optional[str]:
    """The site-packages root Docassemble installs packages into.

    1.9.x computes it in ``webapp.server``; 1.10.x moved it to
    ``webapp.config``.
    """
    value = _optional_webapp_attr(
        (
            ("docassemble.webapp.config", "FULL_PACKAGE_DIRECTORY"),
            ("docassemble.webapp.server", "FULL_PACKAGE_DIRECTORY"),
        )
    )
    return str(value) if value else None


def server_start_time() -> float:
    """When the process serving this request booted.

    Read out of the already-imported module where possible. Importing
    ``docassemble.base.config`` has the side effect of loading the server
    configuration, which calls ``sys.exit`` when there is no config file — fine
    inside a real server, fatal anywhere else.
    """
    module = sys.modules.get("docassemble.base.config")
    if module is None:
        try:
            module = importlib.import_module("docassemble.base.config")
        except BaseException:  # pylint: disable=broad-except
            return 0.0
    try:
        return float(getattr(module, "START_TIME", 0.0))
    except (TypeError, ValueError):
        return 0.0


def reset_process_is_running() -> bool:
    """Whether supervisor's ``reset`` program is still working."""
    func = _optional_webapp_attr(
        (
            ("docassemble.webapp.utils.helpers", "reset_process_running"),
            ("docassemble.webapp.server", "reset_process_running"),
        )
    )
    if not callable(func):
        return False
    try:
        return bool(func())
    except Exception:
        return False


def restart_docassemble() -> None:
    """Restart every Docassemble process, the way ``/restart_ajax`` does.

    1.9.x defines ``restart_all`` in ``webapp.server``; 1.10.x moved it to
    ``webapp.main.helpers``. It clears the cached interview sources, restarts
    the other hosts, and then restarts this one, which is why the caller must
    have already written its polling record before calling this.
    """
    func = _optional_webapp_attr(
        (
            ("docassemble.webapp.main.helpers", "restart_all"),
            ("docassemble.webapp.server", "restart_all"),
        )
    )
    if not callable(func):
        raise DocassembleCompatibilityError(
            "This Docassemble installation does not expose a way to restart"
        )
    func()


def bump_interview_source_index(yaml_filename: str) -> None:
    """Invalidate every worker's cached parse of one interview.

    ``interview_cache`` validates its per-process cache against the Redis
    counter ``da:interviewsource:<path>``, so without this bump a worker that
    has already parsed the file keeps serving the old questions. Docassemble
    does it for ``/interview`` requests carrying ``cache=0``; anything else
    that starts a session against freshly edited YAML has to do it itself.
    """
    try:
        import docassemble.base.parse  # type: ignore

        docassemble.base.parse.interview_source_from_string(
            yaml_filename
        ).update_index()
    except Exception:
        # A stale parse is a much smaller problem than a failed session start.
        pass


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
        "configure_url": configure_url,
    }


def _github_authorized_http(*, user_id: Optional[int] = None) -> Any:
    """Return Docassemble's authorized GitHub HTTP client.

    Request handlers can use Docassemble's request-scoped credential storage.
    Celery workers cannot: that storage derives its Redis key from
    ``flask_login.current_user``, which is anonymous outside a request.  When
    the caller supplies ``user_id``, read the same per-user Redis record
    explicitly so background publishing authorizes as the user who queued it.
    """
    try:
        if user_id is None:
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
        else:
            raw_credentials = get_redis_client().get(f"da:github:userid:{int(user_id)}")
            if raw_credentials is None:
                credentials = None
            else:
                serialized_credentials = (
                    raw_credentials.decode("utf-8")
                    if isinstance(raw_credentials, bytes)
                    else str(raw_credentials)
                )
                oauth_client = importlib.import_module("oauth2client.client")
                credentials = oauth_client.Credentials.new_from_json(
                    serialized_credentials
                )
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        # Some Docassemble versions let JSONDecodeError escape when the
        # Redis credential record is empty or stale.  That is an expired
        # connection, not a malformed editor request.
        raise GithubCredentialError(
            "The GitHub connection could not be read; reconnect it in Docassemble"
        ) from exc
    if not credentials or getattr(credentials, "invalid", False):
        raise GithubCredentialError(
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


def normalize_github_repository_url(raw_url: str) -> Dict[str, str]:
    """Validate a GitHub repository URL and return its canonical components."""
    value = str(raw_url or "").strip()
    if value.endswith(".git"):
        value = value[:-4]
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "github.com",
        "www.github.com",
    }:
        raise ValueError("Enter an HTTPS GitHub repository URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or not all(
        re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts
    ):
        raise ValueError(
            "Enter a GitHub repository URL like https://github.com/owner/repository"
        )
    owner, repository = parts
    return {
        "owner": owner,
        "repository": repository,
        "url": f"https://github.com/{owner}/{repository}",
    }


def get_github_repository_snapshot(
    *,
    repository_url: str,
    user_id: Optional[int] = None,
    ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Read one GitHub repository tree, using OAuth when available.

    An anonymous client is deliberately supported so importing a public URL is
    never limited to repositories owned by the connected GitHub account.
    """
    repository = normalize_github_repository_url(repository_url)
    anonymous = False
    try:
        http = _github_authorized_http(user_id=user_id)
    except GithubCredentialError:
        httplib2 = importlib.import_module("httplib2")
        http = httplib2.Http()
        anonymous = True

    base_url = (
        "https://api.github.com/repos/"
        f"{quote(repository['owner'], safe='')}/{quote(repository['repository'], safe='')}"
    )
    if anonymous:
        selected_ref = str(ref or "HEAD").strip()
        if not re.fullmatch(
            r"[A-Za-z0-9._/-]+", selected_ref
        ) or selected_ref.startswith("-"):
            raise ValueError("Enter a valid Git branch or commit")
        if re.fullmatch(r"[0-9a-fA-F]{40}", selected_ref):
            commit_sha = selected_ref
        else:
            try:
                result = subprocess.run(
                    ["git", "ls-remote", repository["url"], selected_ref],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                raise DocassembleCompatibilityError(
                    "GitHub took too long to resolve that branch; try again or enter a commit SHA"
                ) from exc
            except OSError as exc:
                raise DocassembleCompatibilityError(
                    "Docassemble could not run Git to resolve that branch; try again or enter a commit SHA"
                ) from exc
            lines = result.stdout.splitlines()
            commit_sha = lines[0].split()[0] if lines else ""
            if result.returncode != 0 or not re.fullmatch(
                r"[0-9a-fA-F]{40}", commit_sha
            ):
                raise DocassembleCompatibilityError(
                    "GitHub repository was not found, is private, or does not contain that branch"
                )
        archive_url = (
            f"https://codeload.github.com/{quote(repository['owner'], safe='')}/"
            f"{quote(repository['repository'], safe='')}/tar.gz/{commit_sha}"
        )
        repo_info: Dict[str, Any] = {"private": False}
    else:
        response, repo_info = _github_json_request(http, base_url)
        status = int(response.get("status", 0))
        if status != 200 or not isinstance(repo_info, dict):
            if status == 404:
                message = "GitHub repository was not found or is private"
            else:
                message = "GitHub could not read the repository"
            raise DocassembleCompatibilityError(
                _github_error_message(repo_info, message)
            )

        selected_ref = str(ref or repo_info.get("default_branch") or "main").strip()
        response, commit = _github_json_request(
            http, f"{base_url}/commits/{quote(selected_ref, safe='')}"
        )
        if int(response.get("status", 0)) != 200 or not isinstance(commit, dict):
            raise DocassembleCompatibilityError(
                _github_error_message(commit, f"GitHub could not read {selected_ref}")
            )
        commit_sha = str(commit.get("sha") or "").strip()
        archive_url = f"{base_url}/tarball/{quote(commit_sha, safe='')}"
    if not commit_sha:
        raise DocassembleCompatibilityError("GitHub did not return a repository commit")

    # One archive request avoids GitHub's low anonymous API limit. A valid
    # public package can contain hundreds of templates; reading each through
    # /git/blobs would otherwise fail halfway through for users who have not
    # connected a GitHub account.
    archive_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response, archive_content = http.request(
        archive_url, "GET", headers=archive_headers
    )
    archive_status = int(response.get("status", 0))
    if archive_status in {301, 302, 303, 307, 308} and response.get("location"):
        response, archive_content = http.request(
            str(response["location"]), "GET", headers=archive_headers
        )
        archive_status = int(response.get("status", 0))
    if archive_status != 200:
        raise DocassembleCompatibilityError(
            "GitHub could not download the repository archive"
        )

    files: Dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_content), mode="r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or "/" not in member.name:
                    continue
                path = member.name.split("/", 1)[1]
                if re.fullmatch(
                    r"docassemble/[^/]+/data/(questions|templates|static|sources)/.+/.+",
                    path,
                ):
                    raise DocassembleCompatibilityError(
                        "The repository contains nested files under a docassemble data directory; "
                        "move them directly into questions, templates, static, or sources before importing"
                    )
                if not (
                    re.fullmatch(
                        r"docassemble/[^/]+/data/(questions|templates|static|sources)/[^/]+",
                        path,
                    )
                    or re.fullmatch(r"docassemble/[^/]+/[^/]+\.py", path)
                ):
                    continue
                if member.size > 25 * 1024 * 1024:
                    raise DocassembleCompatibilityError(
                        f"The repository file {path} is too large to import"
                    )
                stream = archive.extractfile(member)
                if stream is not None:
                    files[path] = stream.read()
    except (tarfile.TarError, OSError) as exc:
        raise DocassembleCompatibilityError(
            "GitHub returned an invalid repository archive"
        ) from exc

    return {
        **repository,
        "branch": selected_ref,
        "sha": commit_sha,
        "files": files,
        "private": bool(repo_info.get("private")),
    }


def get_github_publish_owners(*, user_id: Optional[int] = None) -> List[Dict[str, str]]:
    """List the personal account and organizations visible to GitHub OAuth."""
    http = _github_authorized_http(user_id=user_id)
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
    *,
    owner: str,
    repository: str,
    description: str = "",
    owner_type: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Find or create a repository under a selected authenticated owner.

    Docassemble creates missing repositories only under ``/user/repos``.  For
    organizations, Weaver creates the empty repository first and then commits
    into it through :func:`publish_github_package`.

    Pass ``owner_type`` when the caller already resolved the owner against
    :func:`get_github_publish_owners`; that skips a second ``/user/orgs``
    pagination walk on every publish.  Background callers must also pass
    ``user_id`` so credential lookup does not depend on a Flask request user.
    """
    if owner_type:
        selected = {"login": str(owner).strip(), "type": str(owner_type)}
    else:
        owners = get_github_publish_owners(user_id=user_id)
        found = next(
            (
                item
                for item in owners
                if item["login"].casefold() == str(owner).strip().casefold()
            ),
            None,
        )
        if found is None:
            raise ValueError("Choose a GitHub account or organization from the list")
        selected = found

    http = _github_authorized_http(user_id=user_id)
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
        {
            "name": repository,
            "description": description,
            # GitHub's Git Database API rejects every blob/tree/ref operation
            # with 409 while a repository has no commits.  An initial commit
            # makes the repository immediately usable by the package upload
            # below; its standalone tree replaces this generated README.
            "auto_init": True,
        },
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


def publish_github_package(
    *,
    owner: str,
    repository: str,
    package: str,
    project: str,
    user_id: int,
    package_info: Dict[str, Any],
    author_name: str,
    author_email: str,
    branch: str,
    commit_message: str,
    manifest_path: str = "",
    default_branch: str = "",
    on_progress: Optional[Callable[[str, int], None]] = None,
) -> Dict[str, Any]:
    """Commit a generated Playground package through GitHub's Git API.

    The native Playground publisher shells out to Git over SSH and then
    redirects the browser away from Weaver.  The editor already has the
    authorized GitHub connection, so the Git database API is a better fit: it
    works for personal and organization repositories and needs no SSH key.

    One blob upload per file means a template-heavy project takes far longer
    than a web request should, so this runs in Docassemble's Celery worker.
    ``on_progress`` receives ``(message, percent)`` on this function's own
    0-100 scale for the caller to surface while it runs.

    ``manifest_path`` supplies the modification time Docassemble's package
    builder expects, and ``default_branch`` is the repository's default branch,
    used as the starting point when ``branch`` does not exist yet.
    """

    def report(message: str, percent: int) -> None:
        if on_progress is None:
            return
        try:
            on_progress(message, max(0, min(100, int(percent))))
        except Exception:
            # Progress reporting must never abort a publish that is working.
            pass

    make_package_dir = _first_webapp_attr(
        (
            ("docassemble.webapp.files", "make_package_dir"),
            ("docassemble.webapp.files.savedfile", "make_package_dir"),
        ),
        "its Playground package builder",
    )
    package_info = dict(package_info)
    manifest_path = str(manifest_path or "")
    default_branch = str(default_branch or "").strip()
    if manifest_path and os.path.isfile(manifest_path):
        package_info["modtime"] = os.path.getmtime(manifest_path)
    else:
        package_info.setdefault("modtime", 0)

    display_name = str(author_name or "Account").strip() or "Account"
    if author_email:
        author_label = f"{display_name} <{author_email}>"
    else:
        author_label = display_name
    author_info = {
        "id": user_id,
        "author name": display_name,
        "author email": author_email,
        "author name and email": author_label,
    }

    # Create the staging directory here rather than letting Docassemble pick a
    # temporary one: if the package build fails partway through the copy, the
    # ``finally`` below still knows what to remove.
    package_directory = tempfile.mkdtemp(prefix="weaver-github-")
    try:
        report("Building the package from the Playground project.", 5)
        make_package_dir(
            package,
            package_info,
            author_info,
            directory=package_directory,
            current_project=project,
        )
        packagedir = os.path.join(package_directory, f"docassemble-{package}")
        if not os.path.isdir(packagedir):
            raise DocassembleCompatibilityError(
                "Docassemble did not create the GitHub package directory"
            )

        files: List[Tuple[str, str]] = []
        for root, _directories, filenames in os.walk(packagedir):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                relative_path = os.path.relpath(full_path, packagedir).replace(
                    os.sep, "/"
                )
                files.append((relative_path, full_path))
        files.sort()
        if not files:
            raise ValueError("The generated GitHub package is empty")

        http = _github_authorized_http(user_id=user_id)
        repository_path = (
            f"https://api.github.com/repos/{quote(str(owner), safe='')}/"
            f"{quote(str(repository), safe='')}"
        )
        branch_ref = quote(str(branch), safe="/")
        ref_url = f"{repository_path}/git/ref/heads/{branch_ref}"
        ref_update_url = f"{repository_path}/git/refs/heads/{branch_ref}"

        target_branch_exists = False
        parent_sha: Optional[str] = None
        response, ref = _github_json_request(http, ref_url)
        ref_status = int(response.get("status", 0))
        if ref_status == 200 and isinstance(ref, dict):
            parent_sha = str((ref.get("object") or {}).get("sha") or "") or None
            target_branch_exists = True
        elif ref_status == 409:
            # GitHub does not permit even blob creation through the Git
            # Database API until an empty repository has its first commit.
            # This also repairs repositories created by an older Weaver
            # version without ``auto_init``.
            response, initialized = _github_json_request(
                http,
                f"{repository_path}/contents/.gitkeep",
                "PUT",
                {
                    "message": "Initialize repository for ALWeaver publishing",
                    "content": "Cg==",
                },
            )
            if int(response.get("status", 0)) != 201 or not isinstance(
                initialized, dict
            ):
                raise DocassembleCompatibilityError(
                    _github_error_message(
                        initialized, "GitHub could not initialize the empty repository"
                    )
                )
            parent_sha = str((initialized.get("commit") or {}).get("sha") or "") or None
            if not parent_sha:
                raise DocassembleCompatibilityError(
                    "GitHub did not return the initial repository commit"
                )
            initialized_branch = default_branch or "main"
            default_branch = initialized_branch
            target_branch_exists = branch == initialized_branch
        elif ref_status not in _GITHUB_NO_SUCH_REF_STATUSES:
            raise DocassembleCompatibilityError(
                _github_error_message(ref, "GitHub could not read the target branch")
            )

        # If the requested branch does not exist, base it on the repository's
        # default branch when one is available.  A repository Weaver just
        # created has no commits at all, so it simply starts without a parent.
        if not target_branch_exists and default_branch and default_branch != branch:
            default_ref_url = (
                f"{repository_path}/git/ref/heads/{quote(default_branch, safe='/')}"
            )
            response, default_ref = _github_json_request(http, default_ref_url)
            default_status = int(response.get("status", 0))
            if default_status == 200 and isinstance(default_ref, dict):
                parent_sha = (
                    str((default_ref.get("object") or {}).get("sha") or "") or None
                )
            elif default_status not in _GITHUB_NO_SUCH_REF_STATUSES:
                raise DocassembleCompatibilityError(
                    _github_error_message(
                        default_ref, "GitHub could not read the default branch"
                    )
                )

        tree_entries: List[Dict[str, str]] = []
        total_files = len(files)
        for index, (relative_path, full_path) in enumerate(files, start=1):
            report(
                f"Uploading {relative_path} ({index} of {total_files}).",
                15 + int(70 * (index - 1) / total_files),
            )
            with open(full_path, "rb") as stream:
                encoded_content = base64.b64encode(stream.read()).decode("ascii")
            response, blob = _github_json_request(
                http,
                f"{repository_path}/git/blobs",
                "POST",
                {"content": encoded_content, "encoding": "base64"},
            )
            if int(response.get("status", 0)) != 201 or not isinstance(blob, dict):
                raise DocassembleCompatibilityError(
                    _github_error_message(
                        blob, f"GitHub could not upload {relative_path}"
                    )
                )
            blob_sha = str(blob.get("sha") or "").strip()
            if not blob_sha:
                raise DocassembleCompatibilityError(
                    f"GitHub did not return a blob for {relative_path}"
                )
            tree_entries.append(
                {
                    "path": relative_path,
                    "mode": "100755" if os.access(full_path, os.X_OK) else "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }
            )

        # Deliberately no ``base_tree``: the walk above already covers every
        # file in the package, so posting a standalone tree replaces the branch
        # contents.  Extending the parent tree instead would leave files the
        # author deleted or renamed in the Playground behind forever, which is
        # not what the native ``git add .`` publisher did.
        report("Creating the package tree.", 88)
        response, tree = _github_json_request(
            http, f"{repository_path}/git/trees", "POST", {"tree": tree_entries}
        )
        if int(response.get("status", 0)) != 201 or not isinstance(tree, dict):
            raise DocassembleCompatibilityError(
                _github_error_message(tree, "GitHub could not create the package tree")
            )
        tree_sha = str(tree.get("sha") or "").strip()
        if not tree_sha:
            raise DocassembleCompatibilityError("GitHub did not return a package tree")

        commit_body: Dict[str, Any] = {
            "message": commit_message,
            "tree": tree_sha,
        }
        # Attribute the commit to the Weaver user the way the native publisher's
        # ``git config user.name``/``user.email`` did.  Without this every
        # commit made through a shared connection looks like the token owner.
        if author_email:
            commit_body["author"] = {
                "name": display_name,
                "email": author_email,
            }
            commit_body["committer"] = dict(commit_body["author"])
        if parent_sha:
            commit_body["parents"] = [parent_sha]
        report("Creating the commit.", 93)
        response, commit = _github_json_request(
            http, f"{repository_path}/git/commits", "POST", commit_body
        )
        if int(response.get("status", 0)) != 201 or not isinstance(commit, dict):
            raise DocassembleCompatibilityError(
                _github_error_message(commit, "GitHub could not create the commit")
            )
        commit_sha = str(commit.get("sha") or "").strip()
        if not commit_sha:
            raise DocassembleCompatibilityError("GitHub did not return a commit")

        report(f"Pointing {branch} at the new commit.", 97)
        if target_branch_exists:
            response, updated_ref = _github_json_request(
                http,
                ref_update_url,
                "PATCH",
                {"sha": commit_sha, "force": False},
            )
            expected_status = 200
        else:
            response, updated_ref = _github_json_request(
                http,
                f"{repository_path}/git/refs",
                "POST",
                {"ref": f"refs/heads/{branch}", "sha": commit_sha},
            )
            expected_status = 201
        if int(response.get("status", 0)) != expected_status:
            raise DocassembleCompatibilityError(
                _github_error_message(updated_ref, "GitHub could not update the branch")
            )
        return {"sha": commit_sha, "branch": branch, "files": len(files)}
    finally:
        shutil.rmtree(package_directory, ignore_errors=True)


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

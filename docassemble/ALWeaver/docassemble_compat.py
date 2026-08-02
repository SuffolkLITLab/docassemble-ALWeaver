"""Weaver-owned compatibility boundary for Docassemble 1.9.x and 1.10.x."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import importlib
import importlib.metadata
from typing import Any, Dict, List, Optional

from flask import Response, jsonify


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


def _private_webapp_module(module_name: str) -> Any:
    """Import a private webapp module only inside this compatibility boundary."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise DocassembleCompatibilityError(
            f"Docassemble webapp capability {module_name!r} is unavailable"
        ) from exc


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
    return getattr(_private_webapp_module("docassemble.webapp.app_object"), "app")


def get_csrf() -> Any:
    return getattr(_private_webapp_module("docassemble.webapp.app_object"), "csrf")


def get_redis_client() -> Any:
    return getattr(_private_webapp_module("docassemble.webapp.server"), "r")


def get_api_verify() -> Any:
    return getattr(_private_webapp_module("docassemble.webapp.server"), "api_verify")


def get_worker_app() -> Any:
    return getattr(
        _private_webapp_module("docassemble.webapp.worker_common"), "workerapp"
    )


def background_context() -> AbstractContextManager[Any]:
    worker_common = _private_webapp_module("docassemble.webapp.worker_common")
    context_factory = getattr(worker_common, "bg_context", None)
    if not callable(context_factory):
        context_factory = getattr(
            _private_webapp_module("docassemble.webapp.tasks.context"), "bg_context"
        )
    return context_factory()


def create_saved_file(*args: Any, **kwargs: Any) -> Any:
    saved_file = getattr(
        _private_webapp_module("docassemble.webapp.files"), "SavedFile"
    )
    return saved_file(*args, **kwargs)


def create_playground(*args: Any, **kwargs: Any) -> Any:
    playground = getattr(
        _private_webapp_module("docassemble.webapp.playground"), "Playground"
    )
    return playground(*args, **kwargs)


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

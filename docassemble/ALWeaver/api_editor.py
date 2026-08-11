# pre-load

"""Flask endpoints for the WYSIWYM interview editor.

Provides:
    GET  /al/editor              — serve the editor single-page application
    GET  /al/editor/api/projects — list playground projects
    GET  /al/editor/api/files    — list YAML files in a project
    POST /al/editor/api/file/new — create a new YAML interview file
    GET  /al/editor/api/file     — read & parse a YAML file
    POST /al/editor/api/file     — save full YAML back to a file
    POST /al/editor/api/file/metadata — update metadata-related documents only
    POST /al/editor/api/block    — update a single block in-place
    POST /al/editor/api/insert-block — insert a new block at a target position
    GET  /al/editor/api/variables — extract variable names from a file
    POST /al/editor/api/order    — save order-builder steps as code
    POST /al/editor/api/ai/generate-screen — draft one question screen with AI
    POST /al/editor/api/ai/generate-fields — draft fields for a question with AI
    POST /al/editor/api/new-project — create a project (optionally via Weaver)
    GET  /al/editor/api/parse-order — parse order code into structured steps
    POST /al/editor/api/draft-order — generate a draft order from blocks
    POST /al/editor/api/draft-review-screen — generate draft review YAML
    GET  /al/editor/api/preview-url — get the interview preview URL
    GET  /al/editor/api/weaver/validate — validate a saved YAML file
    POST /al/editor/api/validate-source — validate a submitted source buffer
    POST /al/editor/api/project/search — search every text file in a project
    POST /al/editor/api/project/replace — replace selected matches or refactor a variable
    POST /al/editor/api/agent/sessions — start an editing-assistant session
    GET  /al/editor/api/agent/sessions/<id> — read assistant session state
    DELETE /al/editor/api/agent/sessions/<id> — end an assistant session
    POST /al/editor/api/agent/sessions/<id>/turn — run one assistant turn
    POST /al/editor/api/agent/sessions/<id>/cancel — stop a running turn
    POST /al/editor/api/agent/sessions/<id>/reset — restore the original candidate
    POST /al/editor/api/agent/sessions/<id>/apply — return the candidate source
"""

from __future__ import annotations

import importlib.resources
import hashlib
import json
import mimetypes
import os
import re
import shutil
import traceback
import textwrap
import tempfile
import time
import uuid
from copy import deepcopy
from html import escape
from urllib.parse import quote
from typing import Any, Dict, List, Optional, cast

import yaml
from flask import Response, jsonify, redirect, request, url_for
from flask_wtf.csrf import generate_csrf
from flask_login import current_user

from docassemble.base.util import log

from .docassemble_compat import (
    create_target_session,
    create_saved_file,
    get_target_question,
    get_target_variables,
    go_back_target_session,
    get_csrf,
    get_flask_app,
    get_redis_client,
    get_worker_app,
    json_response as jsonify_with_status,
    run_target_action_raw,
    set_target_variables,
)
from .worker_config import (
    CELERY_CONFIGURATION_DOCS_URL,
    CELERY_MODULE,
    get_worker_configuration_status,
    worker_configuration_is_ready,
)

app = get_flask_app()
csrf = get_csrf()
r = get_redis_client()
workerapp = get_worker_app()

from .api_utils import (
    generate_interview_from_bytes,
    parse_bool,
    validate_upload_metadata,
)

try:
    from .editor_utils import (
        canonical_block_yaml,
        canonicalize_block_yaml,
        comment_out_block_in_yaml,
        delete_block_from_yaml,
        delete_saved_file,
        generate_draft_order,
        parse_interview_yaml,
        metadata_source_slice,
        parse_order_code,
        playground_get_variables,
        playground_interview_url,
        playground_list_projects,
        playground_list_yaml_files,
        playground_read_yaml,
        playground_write_yaml,
        rename_saved_file,
        serialize_blocks_to_yaml,
        serialize_order_steps,
        source_revision,
        enable_commented_block_in_yaml,
        reorder_blocks_in_yaml,
        update_block_in_yaml,
        update_metadata_documents_in_yaml,
    )
except Exception as _editor_utils_import_err:
    import traceback as _traceback

    log(
        "ALWeaver api_editor: FAILED TO IMPORT editor_utils: "
        + _traceback.format_exc(),
        "error",
    )
    raise

from .source_document import (
    apply_range_operations,
    parse_source_document,
    unified_source_diff,
)
from .editor_project_search import (
    MAX_PROJECT_MATCHES,
    context_for_span,
    find_literal_matches,
    replace_selected_matches,
)
from .editor_agent import (
    AgentConfigurationError,
    pick_agent_model_name,
    record_turn,
    run_agent_turn,
)
from .editor_agent_repair import auto_heal_source, describe_repair_offer
from .editor_agent_models import (
    MAX_CANDIDATE_SOURCE_BYTES,
    MAX_CHAT_MESSAGE_CHARS,
    MAX_TURNS_PER_SESSION,
    WeaverAgentSession,
    clear_progress,
    delete_agent_session,
    load_agent_session,
    load_progress,
    progress_is_live,
    store_agent_session,
    store_progress,
)
from .editor_agent_validation import (
    annotate_lint_findings,
    block_line_span,
    block_lookup_map,
    lint_level_from_severity,
    lint_summary_for_findings,
    resolve_lint_block_id,
    source_range_for_line,
    validate_candidate_source,
    validate_source_text,
)
from .runtime_sessions import (
    append_runtime_event,
    create_runtime_record,
    delete_runtime_record,
    load_runtime_record,
    playground_yaml_filename,
    store_runtime_record,
)

try:
    from .editor_ai_utils import (
        DEFAULT_FIELD_TYPES,
        normalize_generated_fields,
        normalize_generated_screen,
        pick_small_model_name,
        validate_yaml_with_dayamlchecker,
    )
except Exception as _ai_utils_import_err:
    import traceback as _traceback

    log(
        "ALWeaver api_editor: FAILED TO IMPORT editor_ai_utils: "
        + _traceback.format_exc(),
        "error",
    )
    raise
from .playground_publish import (
    SECTION_TO_STORAGE,
    _copy_files_to_section,
    delete_project,
    create_project,
    get_list_of_projects,
    next_available_project_name,
    normalize_project_name,
    rename_project,
)

__all__: list = []

EDITOR_BASE_PATH = "/al/editor"

EDITOR_SECTION_ALIASES: Dict[str, str] = {
    "template": "templates",
    "templates": "templates",
    "module": "modules",
    "modules": "modules",
    "static": "static",
    "area-static": "static",
    "static-files": "static",
    "data": "data",
    "source": "data",
    "sources": "data",
    "datasource": "data",
    "datasources": "data",
}

EDITOR_SECTION_TO_STORAGE: Dict[str, str] = {
    "templates": SECTION_TO_STORAGE["templates"],
    "modules": SECTION_TO_STORAGE["modules"],
    "static": SECTION_TO_STORAGE["static"],
    "data": SECTION_TO_STORAGE["sources"],
}

EDITOR_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".css",
    ".scss",
    ".less",
    ".html",
    ".xml",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xlf",
    ".xliff",
    ".ini",
    ".cfg",
    ".toml",
    ".mako",
    ".feature",
}

EDITOR_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".svg",
    ".avif",
    ".tif",
    ".tiff",
}

EDITOR_SEARCH_FILE_TYPES = {
    "interview": "Interviews",
    "templates": "Templates",
    "modules": "Modules",
    "static": "Static files",
    "data": "Sources",
}
EDITOR_SEARCH_MAX_FILE_BYTES = 2 * 1024 * 1024


class StaleProjectSearchError(ValueError):
    """Raised when a project-search target changes during final preflight."""

    def __init__(self, files: List[Dict[str, str]]):
        super().__init__("Project files changed after this search")
        self.files = files


DEFAULT_DASHBOARD_EDITOR_URLS = {
    "pdf": "/al/pdf-labeler?project={project}&filename={filename}",
    "docx": "/al/docx-labeler?project={project}&filename={filename}",
}


# ---------------------------------------------------------------------------
# Auth helpers (mirror ALDashboard session-cookie pattern)
# ---------------------------------------------------------------------------


def _editor_auth_check() -> bool:
    """Return True for authenticated Docassemble admins and developers."""
    try:
        has_role = getattr(current_user, "has_role", None)
        return bool(
            current_user.is_authenticated
            and callable(has_role)
            and has_role("admin", "developer")
        )
    except Exception:
        return False


def _auth_fail(request_id: str):
    login_url, _logout_url = _editor_auth_urls()
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "auth_error",
                "message": "Login required for the interview editor.",
            },
            "data": {
                "login_url": login_url,
            },
        },
        401,
    )


def _current_user_id() -> int:
    uid = getattr(current_user, "id", None)
    if uid is None:
        raise RuntimeError("No authenticated user")
    return int(uid)


def _editor_auth_return_target() -> str:
    """Return a safe in-app location for post-login redirects."""
    next_arg = request.args.get("next")
    if isinstance(next_arg, str):
        next_target = next_arg.strip()
        if next_target.startswith("/") and not next_target.startswith("//"):
            return next_target
        if next_target:
            return EDITOR_BASE_PATH
    current = request.full_path or EDITOR_BASE_PATH
    if current.endswith("?"):
        current = current[:-1]
    return current or EDITOR_BASE_PATH


def _editor_auth_urls() -> tuple[str, str]:
    next_target = _editor_auth_return_target()
    return (
        f"/user/sign-in?next={quote(next_target, safe='')}",
        f"/user/sign-out?next={quote(next_target, safe='')}",
    )


def _editor_current_language() -> Optional[str]:
    """Return the active interview language, if docassemble can tell us."""
    try:
        import docassemble.base.functions

        return docassemble.base.functions.get_language()
    except Exception:
        return None


def _resolve_endpoint(*candidates: str) -> str:
    """Return the URL for the first endpoint name that this server registers.

    Docassemble moved its views onto blueprints (``develop.playground_page``)
    but older releases registered them bare (``playground_page``), so each menu
    entry is looked up under every name it has ever had. An unknown name means
    the feature is absent from this server, not an error.
    """
    for candidate in candidates:
        try:
            return str(url_for(candidate))
        except Exception:
            continue
    return ""


def _editor_account_menu_items(logout_url: str) -> List[Dict[str, str]]:
    """Build docassemble's own account menu for the signed-in user.

    Mirrors the dropdown in docassemble's ``base_templates/base.html`` so the
    editor's navbar offers the same destinations, gated by the same roles and
    configuration flags, as every native docassemble page.
    """
    try:
        if not current_user.is_authenticated:
            return []
    except Exception:
        return []

    items: List[Dict[str, str]] = []

    def add_item(label: str, *endpoints: str, href: Optional[str] = None) -> None:
        target = href or _resolve_endpoint(*endpoints)
        if target:
            items.append({"label": str(label), "url": str(target)})

    def has_roles(*roles: str) -> bool:
        try:
            return bool(current_user.has_roles(list(roles)))
        except Exception:
            try:
                return bool(current_user.has_role(*roles))
            except Exception:
                return False

    def can_do(permission: str) -> bool:
        try:
            return bool(current_user.can_do(permission))
        except Exception:
            return False

    if has_roles("admin", "advocate") and app.config.get("ENABLE_MONITOR"):
        add_item("Monitor", "monitor.monitor", "monitor")
    if has_roles("admin", "developer", "trainer") and app.config.get("ENABLE_TRAINING"):
        add_item("Train", "ml.train", "train")
    if has_roles("admin", "developer"):
        if app.config.get("ALLOW_UPDATES") and (
            app.config.get("DEVELOPER_CAN_INSTALL") or has_roles("admin")
        ):
            add_item("Package Management", "packages.update_package", "update_package")
        if app.config.get("ALLOW_LOG_VIEWING"):
            add_item("Logs", "logs.logs", "logs")
        if app.config.get("ENABLE_PLAYGROUND"):
            add_item("Playground", "develop.playground_page", "playground_page")
            add_item("Utilities", "develop.utilities", "utilities")
    if has_roles("admin", "advocate") or can_do("access_user_info"):
        add_item("User List", "users.user_list", "user_list")
    if has_roles("admin") and app.config.get("ALLOW_CONFIGURATION_EDITING"):
        add_item("Configuration", "admin.config_page", "config_page")
    if app.config.get("SHOW_DISPATCH"):
        add_item("Available Interviews", "admin.interview_start", "interview_start")

    for item in app.config.get("ADMIN_INTERVIEWS", []) or []:
        try:
            if item.can_use():
                add_item(
                    item.get_title(_editor_current_language()),
                    href=item.get_url(),
                )
        except Exception:  # nosec B112
            continue

    if app.config.get("SHOW_MY_INTERVIEWS") or has_roles("admin"):
        add_item("My Interviews", "admin.interview_list", "interview_list")
    if app.config.get("SHOW_PROFILE") or has_roles("admin", "developer"):
        add_item("Profile", "users.user_profile_page", "user_profile_page")
    else:
        social_id = str(getattr(current_user, "social_id", "") or "")
        if social_id.startswith("local") and app.config.get("ALLOW_CHANGING_PASSWORD"):
            add_item("Change Password", "user.change_password")

    add_item("Sign Out", href=logout_url)
    return items


def _editor_user_designator() -> str:
    """Return the label docassemble would print for the current user."""
    for attribute in ("first_name", "last_name"):
        # docassemble shows "First Last" when a name is on file, email otherwise.
        if str(getattr(current_user, attribute, "") or "").strip():
            first = str(getattr(current_user, "first_name", "") or "").strip()
            last = str(getattr(current_user, "last_name", "") or "").strip()
            return " ".join(part for part in (first, last) if part)
    return str(getattr(current_user, "email", "") or "").strip() or "Account"


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _normalize_project(raw: Optional[str]) -> str:
    value = str(raw or "default").strip() or "default"
    if "/" in value or "\\" in value or value.startswith("."):
        raise ValueError("Invalid project name")
    return value


def _normalize_filename(raw: Optional[str]) -> str:
    value = os.path.basename(str(raw or "").strip())
    if not value or value in {".", ".."}:
        raise ValueError("YAML filename is required")
    if not value.lower().endswith((".yml", ".yaml")):
        raise ValueError("File must be a YAML interview")
    return value


def _normalize_new_filename(raw: Optional[str]) -> str:
    value = os.path.basename(str(raw or "").strip())
    if not value or value in {".", ".."}:
        raise ValueError("YAML filename is required")
    if "." not in value:
        value = f"{value}.yml"
    if not value.lower().endswith((".yml", ".yaml")):
        raise ValueError("File must be a YAML interview")
    return value


def _normalize_renamed_storage_filename(
    raw: Optional[str], existing_filename: str
) -> str:
    value = os.path.basename(str(raw or "").strip())
    if not value or value in {".", ".."}:
        raise ValueError("YAML filename is required")
    if "." not in value:
        existing_ext = os.path.splitext(existing_filename)[1]
        if existing_ext:
            value = value + existing_ext
    return value


def _normalize_renamed_filename(raw: Optional[str], existing_filename: str) -> str:
    value = _normalize_renamed_storage_filename(raw, existing_filename)
    if not value.lower().endswith((".yml", ".yaml")):
        raise ValueError("File must be a YAML interview")
    return value


def _default_new_interview_yaml() -> str:
    return (
        "metadata:\n"
        "  title: New interview\n"
        "---\n"
        f"id: question_{uuid.uuid4().hex[:8]}\n"
        "question: New question\n"
    )


def _normalize_section(raw: Optional[str]) -> str:
    value = str(raw or "").strip().lower()
    if value not in EDITOR_SECTION_ALIASES:
        raise ValueError("Invalid section")
    return EDITOR_SECTION_ALIASES[value]


def _normalize_storage_filename(raw: Optional[str]) -> str:
    value = os.path.basename(str(raw or "").strip())
    if not value or value in {".", ".."}:
        raise ValueError("filename is required")
    return value


def _editor_storage_directory(
    user_id: int, project: str, storage_section: str
) -> tuple[Any, str]:
    area = create_saved_file(user_id, fix=True, section=storage_section)
    directory = (
        area.directory
        if project == "default"
        else os.path.join(area.directory, project)
    )
    os.makedirs(directory, exist_ok=True)
    return area, directory


def _editor_playground_directory(user_id: int, project: str) -> tuple[Any, str]:
    area = create_saved_file(user_id, fix=True, section="playground")
    directory = (
        area.directory
        if project == "default"
        else os.path.join(area.directory, project)
    )
    os.makedirs(directory, exist_ok=True)
    return area, directory


def _build_file_response_data(
    updated_content: str,
    project: str,
    filename: str,
    *,
    inserted_block_id: Optional[str] = None,
) -> Dict[str, Any]:
    model = parse_interview_yaml(updated_content)
    order_step_map: Dict[str, List[Dict[str, Any]]] = {}
    order_steps: list = []
    for idx in model.get("order_blocks", []):
        block = model["blocks"][idx]
        code = block.get("data", {}).get("code", "")
        if code:
            parsed_steps = parse_order_code(code)
            order_step_map[block["id"]] = parsed_steps
            if not order_steps:
                order_steps = parsed_steps
    return {
        "project": project,
        "filename": filename,
        "blocks": model["blocks"],
        "metadata_blocks": model["metadata_blocks"],
        "include_blocks": model["include_blocks"],
        "default_screen_parts_blocks": model["default_screen_parts_blocks"],
        "order_blocks": model["order_blocks"],
        "order_steps": order_steps,
        "order_step_map": order_step_map,
        "raw_yaml": updated_content,
        **({"inserted_block_id": inserted_block_id} if inserted_block_id else {}),
    }


# Diagnostic normalisation and whole-source validation live in
# editor_agent_validation so that the agent, the patch API and the editor's own
# unsaved-source check cannot drift apart. These aliases keep the existing
# module-level names that call sites and tests already patch.
_lint_level_from_severity = lint_level_from_severity
_block_lookup_map = block_lookup_map
_block_line_span = block_line_span
_resolve_lint_block_id = resolve_lint_block_id
_annotate_lint_findings = annotate_lint_findings
_lint_summary_for_findings = lint_summary_for_findings
_source_range_for_line = source_range_for_line
_validate_source_text = validate_source_text


def _run_interview_linter(raw_yaml: str, include_llm: bool = True) -> Dict[str, Any]:
    from docassemble.ALDashboard.interview_linter import lint_interview_content

    return lint_interview_content(raw_yaml, include_llm=include_llm)


def _is_text_editable(filename: str, mimetype: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    if ext in EDITOR_TEXT_EXTENSIONS:
        return True
    return bool(mimetype and mimetype.startswith("text/"))


def _is_placeholder_file(filename: str) -> bool:
    return filename.lower().endswith(".placeholder")


def _preview_kind_for_file(filename: str, editable: bool) -> str:
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext in EDITOR_IMAGE_EXTENSIONS:
        return "image"
    if editable:
        return "text"
    return "binary"


def _dashboard_editor_url(kind: str, project: str, filename: str) -> str:
    pattern = DEFAULT_DASHBOARD_EDITOR_URLS[kind]
    return pattern.format(
        project=quote(project, safe="/"), filename=quote(filename, safe="")
    )


def _list_editor_section_files(
    user_id: int, project: str, section: str
) -> List[Dict[str, Any]]:
    storage_section = EDITOR_SECTION_TO_STORAGE[section]
    _area, directory = _editor_storage_directory(user_id, project, storage_section)
    if not os.path.isdir(directory):
        return []
    items: List[Dict[str, Any]] = []
    for name in sorted(
        os.listdir(directory), key=lambda v: (_is_placeholder_file(v), v.lower())
    ):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        guessed_mimetype, _enc = mimetypes.guess_type(name)
        mimetype_value = guessed_mimetype or "application/octet-stream"
        editable = _is_text_editable(name, mimetype_value) and not _is_placeholder_file(
            name
        )
        items.append(
            {
                "filename": name,
                "size": os.path.getsize(path),
                "modified": int(os.path.getmtime(path)),
                "mimetype": mimetype_value,
                "editable": editable,
                "preview_kind": _preview_kind_for_file(name, editable),
            }
        )
    return items


def _read_project_text_file(
    user_id: int, project: str, section: str, filename: str
) -> str:
    """Read one search-scoped file after applying the editor's normal guards."""
    if section == "interview":
        return playground_read_yaml(user_id, project, _normalize_filename(filename))
    normalized_section = _normalize_section(section)
    normalized_filename = _normalize_storage_filename(filename)
    metadata = {
        item["filename"]: item
        for item in _list_editor_section_files(user_id, project, normalized_section)
    }.get(normalized_filename)
    if not metadata:
        raise FileNotFoundError(f"{normalized_filename} not found")
    if not metadata.get("editable"):
        raise ValueError(f"{normalized_filename} is not a text-editable file")
    if int(metadata.get("size") or 0) > EDITOR_SEARCH_MAX_FILE_BYTES:
        raise ValueError(f"{normalized_filename} is too large for project search")
    storage_section = EDITOR_SECTION_TO_STORAGE[normalized_section]
    _area, directory = _editor_storage_directory(user_id, project, storage_section)
    with open(
        os.path.join(directory, normalized_filename), encoding="utf-8", errors="replace"
    ) as fh:
        return fh.read()


def _write_project_text_file(
    user_id: int, project: str, section: str, filename: str, content: str
) -> None:
    """Write one already-validated project-search target."""
    if section == "interview":
        playground_write_yaml(user_id, project, _normalize_filename(filename), content)
        return
    normalized_section = _normalize_section(section)
    normalized_filename = _normalize_storage_filename(filename)
    storage_section = EDITOR_SECTION_TO_STORAGE[normalized_section]
    area, directory = _editor_storage_directory(user_id, project, storage_section)
    with open(
        os.path.join(directory, normalized_filename), "w", encoding="utf-8"
    ) as fh:
        fh.write(content)
    area.finalize()


def _project_text_files(
    user_id: int, project: str, *, interviews_only: bool = False
) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Return bounded text buffers in stable file-type/filename order."""
    files: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for item in playground_list_yaml_files(user_id, project):
        if not isinstance(item, dict) or not item.get("filename"):
            continue
        filename = _normalize_filename(item.get("filename"))
        content = playground_read_yaml(user_id, project, filename)
        if len(content.encode("utf-8")) > EDITOR_SEARCH_MAX_FILE_BYTES:
            skipped.append(
                {"section": "interview", "filename": filename, "reason": "too_large"}
            )
            continue
        files.append(
            {
                "section": "interview",
                "file_type": "interview",
                "file_type_label": EDITOR_SEARCH_FILE_TYPES["interview"],
                "filename": filename,
                "content": content,
                "revision": source_revision(content),
            }
        )
    if interviews_only:
        return files, skipped

    for section in ("templates", "modules", "static", "data"):
        for item in _list_editor_section_files(user_id, project, section):
            filename = str(item.get("filename") or "")
            if not item.get("editable"):
                continue
            if int(item.get("size") or 0) > EDITOR_SEARCH_MAX_FILE_BYTES:
                skipped.append(
                    {"section": section, "filename": filename, "reason": "too_large"}
                )
                continue
            content = _read_project_text_file(user_id, project, section, filename)
            files.append(
                {
                    "section": section,
                    "file_type": section,
                    "file_type_label": EDITOR_SEARCH_FILE_TYPES[section],
                    "filename": filename,
                    "content": content,
                    "revision": source_revision(content),
                }
            )
    return files, skipped


def _project_search_revision(files: List[Dict[str, Any]]) -> str:
    manifest = "\n".join(
        f"{item['section']}\0{item['filename']}\0{item['revision']}" for item in files
    )
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def _commit_project_replacements(
    user_id: int, project: str, changes: List[Dict[str, Any]]
) -> None:
    """Write a preflighted batch and make a best-effort rollback on failure."""
    stale_files: List[Dict[str, str]] = []
    for change in changes:
        current = _read_project_text_file(
            user_id, project, change["section"], change["filename"]
        )
        if current != change["original"]:
            stale_files.append(
                {"section": change["section"], "filename": change["filename"]}
            )
    if stale_files:
        raise StaleProjectSearchError(stale_files)

    written: List[Dict[str, Any]] = []
    try:
        for change in changes:
            _write_project_text_file(
                user_id,
                project,
                change["section"],
                change["filename"],
                change["updated"],
            )
            written.append(change)
    except Exception:
        for change in reversed(written):
            try:
                _write_project_text_file(
                    user_id,
                    project,
                    change["section"],
                    change["filename"],
                    change["original"],
                )
            except Exception as rollback_exc:
                log(
                    "ALWeaver editor: project replace rollback failed for "
                    f"{change['section']}/{change['filename']}: {rollback_exc!r}",
                    "error",
                )
        raise


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def _get_template_content(filename: str) -> str:
    """Read a file from data/templates/ inside the installed package."""
    try:
        ref = (
            importlib.resources.files("docassemble.ALWeaver")
            / "data"
            / "templates"
            / filename
        )
        with importlib.resources.as_file(ref) as path:
            if path.exists():
                return path.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return ""
    return ""


def _get_static_content(filename: str) -> str:
    """Read a file from data/static/ inside the installed package."""
    try:
        ref = (
            importlib.resources.files("docassemble.ALWeaver")
            / "data"
            / "static"
            / filename
        )
        with importlib.resources.as_file(ref) as path:
            if path.exists():
                return path.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return ""
    return ""


def _editor_feature_bootstrap() -> Dict[str, Any]:
    """Publish the editor's feature state to the browser.

    ``agent_editor`` says whether the assistant may be offered at all;
    ``assistant_status`` says whether it can actually run. The panel is shown
    for the first and explains itself for the second, so a missing API key
    produces an explanation rather than a chat box that fails on submit.

    Both spellings are emitted: editor.js already reads the camelCase keys, and
    the agent contract is specified in snake_case.
    """
    patch_model = _patch_model_enabled()
    runtime_inspector = _runtime_inspector_enabled()
    agent_editor = _agent_editor_enabled()
    status = _assistant_status()
    return {
        "patch_model": patch_model,
        "runtime_inspector": runtime_inspector,
        "agent_editor": agent_editor,
        "assistant_status": status,
        "patchModel": patch_model,
        "runtimeInspector": runtime_inspector,
        "agentEditor": agent_editor,
        "assistantStatus": status,
    }


def _render_editor_page() -> str:
    """Build the editor HTML, injecting bootstrap JSON for the logged-in user."""
    html = _get_template_content("editor.html")
    if not html:
        return ""
    login_url, logout_url = _editor_auth_urls()
    bootstrap: Dict[str, Any] = {
        "apiBasePath": EDITOR_BASE_PATH,
        "csrfToken": generate_csrf(),
        "features": _editor_feature_bootstrap(),
        "systemChecks": {
            "celery": get_worker_configuration_status(),
        },
        "auth": {
            "authenticated": False,
            "loginUrl": login_url,
            "logoutUrl": logout_url,
            "designator": "",
            "menuItems": [],
        },
    }
    try:
        if _editor_auth_check():
            uid = _current_user_id()
            bootstrap["projects"] = playground_list_projects(uid)
            bootstrap["authenticated"] = True
            bootstrap["auth"]["authenticated"] = True
            bootstrap["auth"]["email"] = getattr(current_user, "email", None)
            bootstrap["auth"]["designator"] = _editor_user_designator()
            bootstrap["auth"]["menuItems"] = _editor_account_menu_items(logout_url)
        else:
            bootstrap["authenticated"] = False
            bootstrap["auth"]["authenticated"] = False
    except Exception:
        bootstrap["authenticated"] = False
        bootstrap["auth"]["authenticated"] = False
    return html.replace(
        "__EDITOR_BOOTSTRAP_JSON__",
        json.dumps(bootstrap, sort_keys=True),
    )


def _load_llms_module():
    try:
        from docassemble.ALToolbox import llms

        return llms
    except Exception as exc:
        log(f"ALWeaver editor: unable to load ALToolbox llms: {exc!r}", "error")
        return None


def _field_types_from_request(payload: Dict[str, Any]) -> List[str]:
    raw = payload.get("field_types")
    if not isinstance(raw, list):
        return list(DEFAULT_FIELD_TYPES)
    cleaned = [str(item).strip() for item in raw if str(item).strip()]
    return cleaned or list(DEFAULT_FIELD_TYPES)


def _question_block_by_id(
    blocks: List[Dict[str, Any]], block_id: str
) -> Optional[Dict[str, Any]]:
    for block in blocks:
        if block.get("id") == block_id and block.get("type") == "question":
            return block
    return None


def _interview_outline_text(blocks: List[Dict[str, Any]], max_items: int = 80) -> str:
    lines: List[str] = []
    for idx, block in enumerate(blocks[:max_items], start=1):
        kind = str(block.get("type") or "other")
        title = str(block.get("title") or "").strip() or "Untitled"
        variable = str(block.get("variable") or "").strip()
        suffix = f" [{variable}]" if variable else ""
        lines.append(f"{idx}. {kind}: {title}{suffix}")
    return "\n".join(lines)


def _project_template_context_text(
    user_id: int, project: str, max_chars: int = 8000
) -> str:
    """Extract lightweight context from uploaded templates in playgroundtemplate."""
    try:
        area = create_saved_file(
            user_id, fix=False, section=SECTION_TO_STORAGE["templates"]
        )
    except Exception:
        return ""
    project_dir = (
        area.directory
        if project == "default"
        else os.path.join(area.directory, project)
    )
    if not os.path.isdir(project_dir):
        return ""

    chunks: List[str] = []
    for filename in sorted(os.listdir(project_dir))[:3]:
        path = os.path.join(project_dir, filename)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(filename.lower())[1]
        extracted = ""
        try:
            if ext == ".pdf":
                from pdfminer.high_level import extract_text

                extracted = extract_text(path, maxpages=2)
            elif ext == ".docx":
                from docx2python import docx2python

                extracted = docx2python(path).text
        except Exception:
            extracted = ""
        compact = re.sub(r"\s+", " ", str(extracted or "")).strip()
        if compact:
            chunks.append(f"Template: {filename}\n{compact[:2200]}")
        else:
            chunks.append(f"Template: {filename}\n[text unavailable]")

    return "\n\n".join(chunks)[:max_chars]


def _ensure_dayamlchecker_valid(yaml_text: str) -> None:
    ok, details = validate_yaml_with_dayamlchecker(yaml_text)
    if ok:
        return
    detail_text = details.strip() or "DAYamlChecker rejected generated YAML"
    raise ValueError(f"Generated YAML failed DAYamlChecker validation: {detail_text}")


def _validate_block_yaml_payload(block_yaml: str) -> None:
    """Validate a single block payload before saving/inserting.

    Reject placeholder-only blocks that contain no functional keys.
    """
    try:
        parsed = yaml.safe_load(block_yaml)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("block_yaml must contain exactly one YAML mapping block")

    normalized_keys = {
        str(key).strip().lower() for key in parsed.keys() if str(key).strip()
    }
    if not normalized_keys:
        raise ValueError("Block must contain at least one key")
    if normalized_keys.issubset({"id", "comment"}):
        raise ValueError(
            "Block is incomplete: add at least one functional key besides id/comment"
        )


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------


@app.route(EDITOR_BASE_PATH, methods=["GET"])
def editor_page() -> Response:
    """Serve the WYSIWYM interview editor page."""
    if not _editor_auth_check():
        login_url, _logout_url = _editor_auth_urls()
        return cast(Response, redirect(login_url))
    log("ALWeaver: Serving editor page", "info")
    html = _render_editor_page()
    if not html:
        log("ALWeaver: editor template not found", "error")
        return Response("Editor template not found.", status=500, mimetype="text/plain")
    return Response(html, mimetype="text/html")


@app.route(f"{EDITOR_BASE_PATH}/static/<path:filename>", methods=["GET"])
def editor_static(filename: str) -> Response:
    """Serve static assets (CSS/JS) for the editor."""
    # Only allow safe filenames
    safe = os.path.basename(filename)
    if safe != filename or ".." in filename:
        return Response("Not found", status=404, mimetype="text/plain")
    content = _get_static_content(safe)
    if not content:
        return Response("Not found", status=404, mimetype="text/plain")
    if safe.endswith(".css"):
        mimetype = "text/css"
    elif safe.endswith(".js"):
        mimetype = "application/javascript"
    else:
        mimetype = "text/plain"
    return Response(content, mimetype=mimetype)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.route(f"{EDITOR_BASE_PATH}/api/projects", methods=["GET"])
def editor_api_projects() -> Response:
    """List playground projects for the current user."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"projects": playground_list_projects(uid)},
            }
        )
    except Exception as exc:
        log(f"ALWeaver editor: projects error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/project/rename", methods=["POST"])
def editor_api_rename_project() -> Response:
    """Rename a playground project across all sections."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        old_project = _normalize_project(post_data.get("project"))
        new_project = _normalize_project(post_data.get("new_project"))
        if old_project == new_project:
            raise ValueError("New project name must be different")
        rename_project(uid, old_project, new_project)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": new_project,
                    "old_project": old_project,
                    "projects": playground_list_projects(uid),
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: rename project error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/project/delete", methods=["POST"])
def editor_api_delete_project() -> Response:
    """Delete a playground project across all sections."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        delete_project(uid, project)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "projects": playground_list_projects(uid),
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: delete project error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/files", methods=["GET"])
def editor_api_files() -> Response:
    """List YAML files in a playground project."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "files": playground_list_yaml_files(uid, project),
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: files error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/project/search", methods=["POST"])
def editor_api_project_search() -> Response:
    """Search all text-editable files in one Playground project."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        project = _normalize_project(post_data.get("project"))
        query = post_data.get("query")
        if not isinstance(query, str):
            raise ValueError("Search text is required")
        mode = str(post_data.get("mode") or "text").strip().lower()
        if mode not in {"text", "variable"}:
            raise ValueError("Search mode must be text or variable")
        replacement = post_data.get("replacement")
        case_sensitive = parse_bool(post_data.get("case_sensitive"), default=False)
        whole_word = parse_bool(post_data.get("whole_word"), default=False)
        files, skipped = _project_text_files(
            uid, project, interviews_only=mode == "variable"
        )
        project_revision = _project_search_revision(files)
        results: List[Dict[str, Any]] = []
        total_matches = 0
        truncated = False

        if mode == "variable":
            from .editor_agent_rename import (
                analyze_rename,
                validate_variable_reference,
            )

            invalid = validate_variable_reference(query)
            if invalid:
                raise ValueError(invalid)
            if not isinstance(replacement, str) or not replacement.strip():
                raise ValueError(
                    "Enter the new variable name before previewing a refactor"
                )
            invalid_replacement = validate_variable_reference(replacement)
            if invalid_replacement:
                raise ValueError(invalid_replacement)
            if query == replacement:
                raise ValueError(f"{query} is already named that")
            for item in files:
                analysis = analyze_rename(
                    filename=item["filename"],
                    raw_yaml=item["content"],
                    old_name=query,
                    new_name=replacement,
                )
                contexts: List[Dict[str, Any]] = []
                for occurrence in analysis.occurrences:
                    if total_matches >= MAX_PROJECT_MATCHES:
                        truncated = True
                        break
                    context = context_for_span(
                        item["content"], occurrence.start, occurrence.end
                    )
                    context.update(
                        {
                            "replaceable": occurrence.safe,
                            "reason": occurrence.reason,
                            "context_type": occurrence.context,
                            "block_id": occurrence.block_id,
                        }
                    )
                    contexts.append(context)
                    total_matches += 1
                if contexts:
                    results.append(
                        {
                            key: item[key]
                            for key in (
                                "section",
                                "file_type",
                                "file_type_label",
                                "filename",
                                "revision",
                            )
                        }
                        | {"matches": contexts}
                    )
                if truncated:
                    break
        else:
            for item in files:
                remaining = MAX_PROJECT_MATCHES - total_matches
                if remaining <= 0:
                    truncated = True
                    break
                matches, file_truncated = find_literal_matches(
                    item["content"],
                    query,
                    case_sensitive=case_sensitive,
                    whole_word=whole_word,
                    limit=min(remaining, 500),
                )
                if matches:
                    results.append(
                        {
                            key: item[key]
                            for key in (
                                "section",
                                "file_type",
                                "file_type_label",
                                "filename",
                                "revision",
                            )
                        }
                        | {"matches": matches}
                    )
                    total_matches += len(matches)
                if file_truncated or total_matches >= MAX_PROJECT_MATCHES:
                    truncated = True
                    if total_matches >= MAX_PROJECT_MATCHES:
                        break

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "mode": mode,
                    "query": query,
                    "replacement": replacement if mode == "variable" else None,
                    "case_sensitive": case_sensitive,
                    "whole_word": whole_word,
                    "project_revision": project_revision,
                    "files": results,
                    "file_count": len(results),
                    "match_count": total_matches,
                    "truncated": truncated,
                    "skipped": skipped,
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: project search error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "message": "The project search could not be completed.",
                },
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/project/replace", methods=["POST"])
def editor_api_project_replace() -> Response:
    """Apply a stale-safe text replacement or semantic variable refactor."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        project = _normalize_project(post_data.get("project"))
        query = post_data.get("query")
        replacement = post_data.get("replacement")
        if not isinstance(query, str) or not query:
            raise ValueError("Search text is required")
        if not isinstance(replacement, str):
            raise ValueError("Replacement must be text")
        mode = str(post_data.get("mode") or "text").strip().lower()
        if mode not in {"text", "variable"}:
            raise ValueError("Replace mode must be text or variable")
        case_sensitive = parse_bool(post_data.get("case_sensitive"), default=False)
        whole_word = parse_bool(post_data.get("whole_word"), default=False)
        changes: List[Dict[str, Any]] = []
        replacement_count = 0

        if mode == "variable":
            from .editor_agent_rename import (
                analyze_rename,
                check_rename_batch,
                plan_rename_operations,
                validate_variable_reference,
            )
            from .editor_agent_tools import _variable_catalog

            invalid_old = validate_variable_reference(query)
            if invalid_old:
                raise ValueError(invalid_old)
            invalid = validate_variable_reference(replacement)
            if invalid:
                raise ValueError(invalid)
            if query == replacement:
                raise ValueError(f"{query} is already named that")
            files, skipped = _project_text_files(uid, project, interviews_only=True)
            current_project_revision = _project_search_revision(files)
            if post_data.get("project_revision") != current_project_revision:
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "conflict",
                            "code": "stale_search",
                            "message": "Project files changed after this search. Search again before replacing.",
                            "details": {"project_revision": current_project_revision},
                        },
                    },
                    409,
                )

            problems: List[str] = [
                f"{item['filename']} is too large to inspect safely" for item in skipped
            ]
            diagnostics: List[Dict[str, Any]] = []
            replacement_definitions = [
                item["filename"]
                for item in files
                if replacement
                in {
                    str(entry.get("variable") or "")
                    for entry in _variable_catalog(item["content"])
                }
            ]
            if replacement_definitions:
                problems.append(
                    f"{replacement} is already used in "
                    + ", ".join(replacement_definitions[:5])
                    + "; renaming onto it could merge two variables"
                )
            for item in files:
                preliminary = analyze_rename(
                    filename=item["filename"],
                    raw_yaml=item["content"],
                    old_name=query,
                    new_name=replacement,
                )
                if preliminary.blocking_occurrences:
                    lines = ", ".join(
                        f"line {occurrence.line} ({occurrence.reason})"
                        for occurrence in preliminary.blocking_occurrences[:5]
                    )
                    problems.append(
                        f"{item['filename']}: {query} has ambiguous references at {lines}"
                    )
                    diagnostics.extend(
                        occurrence.public_dict() | {"filename": item["filename"]}
                        for occurrence in preliminary.blocking_occurrences[:20]
                    )
                    continue
                if not preliminary.safe_occurrences:
                    # Display prose is intentionally not part of a semantic
                    # rename and does not prevent references in other files.
                    continue
                analyses, file_problems = check_rename_batch(
                    filename=item["filename"],
                    raw_yaml=item["content"],
                    renames=[{"old_name": query, "new_name": replacement}],
                )
                if file_problems:
                    problems.extend(
                        f"{item['filename']}: {problem}" for problem in file_problems
                    )
                    continue
                operations = plan_rename_operations(analyses)
                updated, _applied_operations = apply_range_operations(
                    item["content"], operations
                )
                validation = validate_candidate_source(
                    filename=item["filename"], raw_yaml=updated
                )
                if validation.blocking:
                    problems.append(
                        f"{item['filename']}: the refactor would produce validation errors"
                    )
                    diagnostics.extend(validation.blocking_diagnostics())
                    continue
                count = sum(len(analysis.safe_occurrences) for analysis in analyses)
                changes.append(
                    {
                        "section": "interview",
                        "filename": item["filename"],
                        "original": item["content"],
                        "updated": updated,
                        "count": count,
                    }
                )
                replacement_count += count
            if problems:
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "unsafe_refactor",
                            "code": "unsafe_refactor",
                            "message": " ".join(problems[:6]),
                            "details": {
                                "problems": problems,
                                "diagnostics": diagnostics,
                            },
                        },
                    },
                    422,
                )
            if not changes:
                raise ValueError("No safe variable references were found to rename")
        else:
            requested_files = post_data.get("files")
            if not isinstance(requested_files, list):
                raise ValueError("Selected search results are required")
            if len(requested_files) > 500:
                raise ValueError("Too many files were selected")
            stale_files: List[Dict[str, str]] = []
            seen_files: set[tuple[str, str]] = set()
            selected_count = 0
            for requested in requested_files:
                if not isinstance(requested, dict):
                    raise ValueError("Each selected file must be an object")
                raw_section = str(requested.get("section") or "")
                section = (
                    "interview"
                    if raw_section == "interview"
                    else _normalize_section(raw_section)
                )
                filename = (
                    _normalize_filename(requested.get("filename"))
                    if section == "interview"
                    else _normalize_storage_filename(requested.get("filename"))
                )
                key = (section, filename)
                if key in seen_files:
                    raise ValueError(f"{filename} was selected more than once")
                seen_files.add(key)
                original = _read_project_text_file(uid, project, section, filename)
                current_revision = source_revision(original)
                if requested.get("revision") != current_revision:
                    stale_files.append({"section": section, "filename": filename})
                    continue
                raw_matches = requested.get("matches")
                if not isinstance(raw_matches, list):
                    raise ValueError(f"Selected matches are required for {filename}")
                selected_count += len(raw_matches)
                if selected_count > MAX_PROJECT_MATCHES:
                    raise ValueError("Too many matches were selected")
                updated, count = replace_selected_matches(
                    original,
                    query,
                    replacement,
                    raw_matches,
                    case_sensitive=case_sensitive,
                    whole_word=whole_word,
                )
                if count:
                    changes.append(
                        {
                            "section": section,
                            "filename": filename,
                            "original": original,
                            "updated": updated,
                            "count": count,
                        }
                    )
                    replacement_count += count
            if stale_files:
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "conflict",
                            "code": "stale_search",
                            "message": "Some files changed after this search. Search again before replacing.",
                            "details": {"files": stale_files},
                        },
                    },
                    409,
                )
            if not changes:
                raise ValueError("Select at least one match to replace")

        _commit_project_replacements(uid, project, changes)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "mode": mode,
                    "replacement_count": replacement_count,
                    "file_count": len(changes),
                    "files": [
                        {
                            "section": change["section"],
                            "filename": change["filename"],
                            "replacement_count": change["count"],
                            "revision": source_revision(change["updated"]),
                        }
                        for change in changes
                    ],
                },
            }
        )
    except StaleProjectSearchError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "conflict",
                    "code": "stale_search",
                    "message": "Some files changed while the replacement was being checked. Search again before replacing.",
                    "details": {"files": exc.files},
                },
            },
            409,
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: project replace error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "message": "The project replacement could not be completed.",
                },
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/file/new", methods=["POST"])
def editor_api_new_file() -> Response:
    """Create a new YAML interview file in the current playground project."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_new_filename(post_data.get("filename"))
        existing_filenames = {
            item.get("filename")
            for item in playground_list_yaml_files(uid, project)
            if isinstance(item, dict)
        }
        if filename in existing_filenames:
            raise ValueError(f"{filename} already exists")
        content = post_data.get("content")
        if not isinstance(content, str) or not content.strip():
            content = _default_new_interview_yaml()
        playground_write_yaml(uid, project, filename, content)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "size": len(content),
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: new file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-files", methods=["GET"])
def editor_api_section_files() -> Response:
    """List files for templates/modules/data sources in the selected project."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        section = _normalize_section(request.args.get("section"))
        files = _list_editor_section_files(uid, project, section)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "files": files,
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: section-files error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-file", methods=["GET"])
def editor_api_get_section_file() -> Response:
    """Read a text-editable section file from templates/modules/data sources."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        section = _normalize_section(request.args.get("section"))
        filename = _normalize_storage_filename(request.args.get("filename"))
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        _area, directory = _editor_storage_directory(uid, project, storage_section)
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{filename} not found")
        guessed_mimetype, _enc = mimetypes.guess_type(filename)
        mimetype_value = guessed_mimetype or "application/octet-stream"
        if not _is_text_editable(filename, mimetype_value):
            raise ValueError("File is not text-editable")
        with open(path, "rb") as fh:
            raw = fh.read()
        content = raw.decode("utf-8", errors="replace")
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "filename": filename,
                    "mimetype": mimetype_value,
                    "editable": True,
                    "content": content,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: get section-file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-file", methods=["POST"])
def editor_api_save_section_file() -> Response:
    """Save a text-editable section file in templates/modules/data sources."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        section = _normalize_section(post_data.get("section"))
        filename = _normalize_storage_filename(post_data.get("filename"))
        content = post_data.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a text string")
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        area, directory = _editor_storage_directory(uid, project, storage_section)
        guessed_mimetype, _enc = mimetypes.guess_type(filename)
        mimetype_value = guessed_mimetype or "application/octet-stream"
        if not _is_text_editable(filename, mimetype_value):
            raise ValueError("File is not text-editable")
        path = os.path.join(directory, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        area.finalize()
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "filename": filename,
                    "size": len(content),
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: save section-file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-file/new", methods=["POST"])
def editor_api_new_section_file() -> Response:
    """Create a new file in templates/modules/data sources."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        section = _normalize_section(post_data.get("section"))
        filename = _normalize_storage_filename(post_data.get("filename"))
        content = post_data.get("content", "")
        if not isinstance(content, str):
            raise ValueError("content must be a text string")
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        area, directory = _editor_storage_directory(uid, project, storage_section)
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            raise ValueError(f"{filename} already exists")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        area.finalize()
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "filename": filename,
                    "size": len(content),
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: new section-file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-file/upload", methods=["POST"])
def editor_api_upload_section_file() -> Response:
    """Upload one or more files into templates/modules/data sources."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.form.get("project"))
        section = _normalize_section(request.form.get("section"))
        uploads = request.files.getlist("files")
        if not uploads:
            raise ValueError("No files uploaded")
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        area, directory = _editor_storage_directory(uid, project, storage_section)
        saved_files: List[str] = []
        for upload in uploads:
            candidate_name = _normalize_storage_filename(upload.filename)
            path = os.path.join(directory, candidate_name)
            if os.path.exists(path):
                stem, ext = os.path.splitext(candidate_name)
                counter = 1
                while os.path.exists(path):
                    candidate_name = f"{stem}_{counter}{ext}"
                    path = os.path.join(directory, candidate_name)
                    counter += 1
            upload.save(path)
            saved_files.append(candidate_name)
        area.finalize()
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "saved_files": saved_files,
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: upload section-file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-file/raw", methods=["GET"])
def editor_api_section_file_raw() -> Response:
    """Serve the raw bytes for a section file (preview/download iframe)."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        section = _normalize_section(request.args.get("section"))
        filename = _normalize_storage_filename(request.args.get("filename"))
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        _area, directory = _editor_storage_directory(uid, project, storage_section)
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{filename} not found")
        guessed_mimetype, _enc = mimetypes.guess_type(filename)
        mimetype_value = guessed_mimetype or "application/octet-stream"
        with open(path, "rb") as fh:
            payload = fh.read()
        response = Response(payload, mimetype=mimetype_value)
        response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
        return response
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: section-file raw error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-file/docx-preview", methods=["GET"])
def editor_api_section_file_docx_preview() -> Response:
    """Return a low-fidelity HTML preview for DOCX template files."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        from docx2python import docx2python

        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        section = _normalize_section(request.args.get("section"))
        filename = _normalize_storage_filename(request.args.get("filename"))
        if not filename.lower().endswith(".docx"):
            raise ValueError("DOCX preview requires a .docx file")
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        _area, directory = _editor_storage_directory(uid, project, storage_section)
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{filename} not found")

        preview_text = docx2python(path).text or ""
        lines = [line.strip() for line in preview_text.splitlines() if line.strip()]
        if not lines:
            lines = ["(No text content found in this DOCX.)"]
        body_html = "".join(f"<p>{escape(line)}</p>" for line in lines[:400])
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "filename": filename,
                    "html": body_html,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: docx preview error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/dashboard-editor-url", methods=["GET"])
def editor_api_dashboard_editor_url() -> Response:
    """Return a URL for opening a template in a dedicated dashboard editor tab."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        project = _normalize_project(request.args.get("project"))
        section = _normalize_section(request.args.get("section"))
        filename = _normalize_storage_filename(request.args.get("filename"))
        extension = os.path.splitext(filename.lower())[1]
        if extension == ".pdf":
            url = _dashboard_editor_url("pdf", project, filename)
        elif extension == ".docx":
            url = _dashboard_editor_url("docx", project, filename)
        else:
            raise ValueError(
                "Dashboard editor is only available for PDF and DOCX templates"
            )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "filename": filename,
                    "url": url,
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: dashboard editor url error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/file", methods=["GET"])
def editor_api_get_file() -> Response:
    """Read and parse a YAML file into the normalised block model."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        raw_yaml = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(raw_yaml)

        order_step_map: Dict[str, List[Dict[str, Any]]] = {}
        order_steps: list = []
        for idx in model.get("order_blocks", []):
            block = model["blocks"][idx]
            code = block.get("data", {}).get("code", "")
            if code:
                parsed_steps = parse_order_code(code)
                order_step_map[block["id"]] = parsed_steps
                if not order_steps:
                    order_steps = parsed_steps

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "blocks": model["blocks"],
                    "metadata_blocks": model["metadata_blocks"],
                    "include_blocks": model["include_blocks"],
                    "default_screen_parts_blocks": model["default_screen_parts_blocks"],
                    "order_blocks": model["order_blocks"],
                    "order_steps": order_steps,
                    "order_step_map": order_step_map,
                    "raw_yaml": raw_yaml,
                    "revision": source_revision(raw_yaml),
                    "metadata_raw_yaml": metadata_source_slice(raw_yaml),
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: get file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/validate-source", methods=["POST"])
def editor_api_validate_source() -> Response:
    """Validate source supplied by the editor without reading it back from disk."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        raw_yaml = post_data.get("raw_yaml")
        if not isinstance(raw_yaml, str):
            raise ValueError("raw_yaml must be a YAML string")
        revision = post_data.get("revision")
        if revision is not None and not isinstance(revision, str):
            raise ValueError("revision must be a string or null")

        # Reading the target confirms that this developer owns the Playground
        # file and lets the client distinguish current and stale base revisions.
        saved_yaml = playground_read_yaml(uid, project, filename)
        current_revision = source_revision(saved_yaml)
        diagnostics = _validate_source_text(raw_yaml, filename)
        summary = _lint_summary_for_findings(diagnostics)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "scope": "unsaved_source",
                    "diagnostics": diagnostics,
                    "errors": diagnostics,
                    "summary": {
                        "count": len(diagnostics),
                        "errors": summary["error"],
                        "warnings": summary["warning"],
                        "infos": summary["info"],
                    },
                    "revision": revision,
                    "current_revision": current_revision,
                    "base_revision_matches": (
                        revision == current_revision if revision is not None else None
                    ),
                    "validated_source_revision": source_revision(raw_yaml),
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "validation_error",
                    "code": "invalid_validation_request",
                    "message": str(exc),
                },
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: validate-source error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "code": "source_validation_failed",
                    "message": str(exc),
                },
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/weaver/validate", methods=["GET"])
def editor_api_validate() -> Response:
    """Run DAYamlChecker on a playground YAML file and return errors."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        raw_yaml = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(raw_yaml)

        errors: List[Dict[str, Any]] = []
        from dayamlchecker.yaml_structure import find_errors_from_string  # type: ignore

        checker_errors = find_errors_from_string(raw_yaml, input_file=filename)
        for checker_error in checker_errors:
            msg = str(getattr(checker_error, "err_str", "") or "").strip() or str(
                checker_error
            )
            lowered = msg.lower()
            level = "error"
            if lowered.startswith("warning:"):
                level = "warning"
                msg = msg[len("warning:") :].strip()
            elif lowered.startswith("info:"):
                level = "info"
                msg = msg[len("info:") :].strip()
            variable = ""
            qmatch = re.search(r'"([^"]+)"', msg) or re.search(r"'([^']+)'", msg)
            if qmatch:
                variable = qmatch.group(1)
            errors.append(
                {
                    "level": level,
                    "message": msg,
                    "variable": variable,
                    "line_number": getattr(checker_error, "line_number", None),
                    "filename": filename,
                    "source": "dayamlchecker",
                }
            )
        # Also include playground-style undefined variable and parse diagnostics.
        try:
            variable_info = playground_get_variables(uid, project, filename)
            undefined_names = (
                variable_info.get("undefined_names")
                if isinstance(variable_info, dict)
                else None
            )
            if isinstance(undefined_names, (list, set, tuple)):
                for var_name in sorted(
                    str(name).strip() for name in undefined_names if str(name).strip()
                ):
                    errors.append(
                        {
                            "level": "warning",
                            "message": f"Undefined variable referenced: {var_name}",
                            "variable": var_name,
                            "line_number": None,
                            "filename": filename,
                            "source": "playground",
                        }
                    )
        except Exception as exc:
            errors.append(
                {
                    "level": "error",
                    "message": str(exc) or "Playground parser reported an error",
                    "variable": "",
                    "line_number": None,
                    "filename": filename,
                    "source": "playground",
                }
            )

        # Deduplicate identical diagnostics from multiple sources.
        deduped: List[Dict[str, Any]] = []
        seen: set = set()
        for diagnostic in errors:
            key = (
                str(diagnostic.get("level") or ""),
                str(diagnostic.get("message") or ""),
                str(diagnostic.get("variable") or ""),
                str(diagnostic.get("line_number") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(diagnostic)
        errors = _annotate_lint_findings(
            deduped, model["blocks"], source_name="validation"
        )

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "errors": errors,
                    "summary": {
                        "count": len(errors),
                        "errors": sum(
                            1 for err in errors if err.get("level") == "error"
                        ),
                        "warnings": sum(
                            1 for err in errors if err.get("level") == "warning"
                        ),
                        "infos": sum(1 for err in errors if err.get("level") == "info"),
                    },
                    "checker": "dayamlchecker",
                    "structured": True,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: validate error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/weaver/style-check", methods=["GET"])
def editor_api_style_check() -> Response:
    """Run the system-wide interview linter and return block-aware style findings."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        include_llm = str(request.args.get("include_llm", "1")).strip().lower() not in {
            "0",
            "false",
            "no",
        }
        raw_yaml = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(raw_yaml)
        lint_result = _run_interview_linter(raw_yaml, include_llm=include_llm)
        findings = (
            lint_result.get("findings", []) if isinstance(lint_result, dict) else []
        )
        if not isinstance(findings, list):
            findings = []
        annotated_findings = _annotate_lint_findings(
            findings, model["blocks"], source_name="style-check"
        )
        summary = _lint_summary_for_findings(annotated_findings)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "errors": annotated_findings,
                    "summary": {
                        "count": len(annotated_findings),
                        "errors": summary["error"],
                        "warnings": summary["warning"],
                        "infos": summary["info"],
                    },
                    "checker": "ALDashboard.interview_linter",
                    "structured": True,
                    "include_llm": include_llm,
                    "screen_catalog": (
                        lint_result.get("screen_catalog", [])
                        if isinstance(lint_result, dict)
                        else []
                    ),
                    "lint_mode": (
                        lint_result.get("lint_mode")
                        if isinstance(lint_result, dict)
                        else None
                    ),
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: style-check error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/file", methods=["POST"])
def editor_api_save_file() -> Response:
    """Save full YAML content to a playground file."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        content = post_data.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a YAML string")
        playground_write_yaml(uid, project, filename, content)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "size": len(content),
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: save file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


# Weaver's editor settings, in the form Docassemble configuration normally
# takes: lowercase words separated by spaces, grouped under one heading.
#
#     weaver:
#       assistant: False
#       assistant model: gpt-5-mini
#       runtime inspector: True
#
# Each setting maps to the older UPPER_SNAKE spelling as well, so installs that
# already set one of those keys — or the matching environment variable — keep
# working without edits.
WEAVER_CONFIG_SECTION = "weaver"

WEAVER_SETTING_LEGACY_NAMES: Dict[str, str] = {
    "assistant": "WEAVER_ENABLE_AGENT_EDITOR",
    "assistant model": "WEAVER_AGENT_MODEL",
    "runtime inspector": "WEAVER_ENABLE_RUNTIME_INSPECTOR",
    "source patch api": "WEAVER_ENABLE_PATCH_MODEL",
}

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _daconfig() -> Dict[str, Any]:
    try:
        from docassemble.base.config import daconfig

        return daconfig if isinstance(daconfig, dict) else {}
    except (ImportError, AttributeError):
        return {}


def _legacy_config_spellings(legacy: str) -> List[str]:
    """Every form a legacy UPPER_SNAKE key can take in the configuration.

    Docassemble rejects underscores in configuration keys and rewrites them to
    spaces on load, so a config file saying ``WEAVER_ENABLE_AGENT_EDITOR``
    actually yields the key ``WEAVER ENABLE AGENT EDITOR``. Looking only for
    the underscore form silently misses a setting the author did write.
    """
    spaced = legacy.replace("_", " ")
    return [legacy, spaced, spaced.lower(), legacy.lower()]


def _weaver_setting(name: str) -> Any:
    """Read one Weaver editor setting, newest spelling first."""
    legacy = WEAVER_SETTING_LEGACY_NAMES.get(name)
    if legacy:
        from_env = os.environ.get(legacy)
        if from_env is not None:
            return from_env

    config = _daconfig()
    section = config.get(WEAVER_CONFIG_SECTION)
    if isinstance(section, dict) and name in section:
        return section[name]
    flat = f"{WEAVER_CONFIG_SECTION} {name}"
    if flat in config:
        return config[flat]
    if legacy:
        for spelling in _legacy_config_spellings(legacy):
            if spelling in config:
                return config[spelling]
    return None


def _weaver_flag(name: str, default: bool) -> bool:
    """Read a boolean Weaver setting, falling back to ``default``."""
    value = _weaver_setting(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    return default


def _weaver_text(name: str) -> Optional[str]:
    value = _weaver_setting(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _editor_config_value(name: str) -> Optional[str]:
    """Read a raw environment or Docassemble configuration value by name."""
    configured = os.environ.get(name)
    if configured is None:
        configured = _daconfig().get(name)
    if configured is None:
        return None
    text = str(configured).strip()
    return text or None


def _editor_feature_enabled(name: str) -> bool:
    """Read an opt-in editor feature flag from environment or DA config."""
    return str(_editor_config_value(name) or "").lower() in _TRUTHY


def _patch_model_enabled() -> bool:
    """The revisioned source-patch API at POST /al/editor/api/file/patch."""
    return _weaver_flag("source patch api", False)


def _agent_editor_enabled() -> bool:
    """The editing assistant is on unless an administrator turns it off.

    It does not depend on the source-patch API: the agent compiles its own
    range operations in process and never calls that endpoint.
    """
    return _weaver_flag("assistant", True)


ASSISTANT_STATUS_READY = "ready"
ASSISTANT_STATUS_DISABLED = "disabled"
ASSISTANT_STATUS_NO_TOOLBOX = "toolbox_unavailable"
ASSISTANT_STATUS_NO_MODEL = "model_not_configured"
ASSISTANT_STATUS_NO_WORKER = "worker_not_configured"

_ASSISTANT_STATUS_MESSAGES = {
    ASSISTANT_STATUS_DISABLED: (
        "The editing assistant is turned off in this server's configuration."
    ),
    ASSISTANT_STATUS_NO_TOOLBOX: (
        "The editing assistant needs the ALToolbox package, which this server "
        "does not have installed. Ask your server administrator to install "
        "docassemble.ALToolbox."
    ),
    ASSISTANT_STATUS_NO_MODEL: (
        "The editing assistant needs a language model, and this server has no "
        "API key configured. Ask your server administrator to add an "
        "`openai api key` (or an `open ai:` block) to the Configuration."
    ),
    ASSISTANT_STATUS_NO_WORKER: (
        "The editing assistant runs in this server's background worker, which "
        "is not configured. Ask your server administrator to set up the "
        "Celery worker."
    ),
}


def _assistant_status() -> Dict[str, Any]:
    """Report whether the assistant can actually run, and why not if it cannot.

    An unconfigured model is the common case on a fresh server, and a chat box
    that accepts a request and then fails is worse than one that explains what
    is missing. ALToolbox sets its client to None when it finds no credentials,
    so that is the honest signal rather than a guess at config key names.
    """
    if not _agent_editor_enabled():
        code = ASSISTANT_STATUS_DISABLED
        return {
            "available": False,
            "code": code,
            "message": _ASSISTANT_STATUS_MESSAGES[code],
        }
    llms = _load_llms_module()
    if llms is None:
        code = ASSISTANT_STATUS_NO_TOOLBOX
        return {
            "available": False,
            "code": code,
            "message": _ASSISTANT_STATUS_MESSAGES[code],
        }
    if getattr(llms, "client", None) is None:
        code = ASSISTANT_STATUS_NO_MODEL
        return {
            "available": False,
            "code": code,
            "message": _ASSISTANT_STATUS_MESSAGES[code],
        }
    # A turn runs in the worker, so no worker means no assistant. Better to say
    # so up front than to accept a request that can never be picked up.
    if not worker_configuration_is_ready():
        code = ASSISTANT_STATUS_NO_WORKER
        return {
            "available": False,
            "code": code,
            "message": _ASSISTANT_STATUS_MESSAGES[code],
            "details": {"docs_url": CELERY_CONFIGURATION_DOCS_URL},
        }
    return {"available": True, "code": ASSISTANT_STATUS_READY, "message": ""}


def _agent_editor_available() -> bool:
    return bool(_assistant_status()["available"])


@app.route(f"{EDITOR_BASE_PATH}/api/file/patch", methods=["POST"])
def editor_api_patch_file() -> Response:
    """Atomically apply source-range edits against an expected file revision."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _patch_model_enabled():
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "feature_disabled",
                    "code": "patch_model_disabled",
                    "message": "The revisioned source-patch model is not enabled.",
                },
            },
            404,
        )
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        expected_revision = post_data.get("expected_revision")
        if not isinstance(expected_revision, str) or not expected_revision:
            raise ValueError("expected_revision is required")
        operations = post_data.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ValueError("operations must be a non-empty list")
        base_raw_yaml = post_data.get("base_raw_yaml")
        if base_raw_yaml is not None and not isinstance(base_raw_yaml, str):
            raise ValueError("base_raw_yaml must be a string or null")

        current_content = playground_read_yaml(uid, project, filename)
        current_revision = source_revision(current_content)
        if expected_revision != current_revision:
            conflict: Dict[str, Any] = {
                "type": "revision_conflict",
                "code": "revision_conflict",
                "message": "The file changed since it was loaded.",
                "expected_revision": expected_revision,
                "current_revision": current_revision,
                "current_raw_yaml": current_content,
                "base_raw_yaml": base_raw_yaml,
            }
            conflict["details"] = {
                key: value
                for key, value in conflict.items()
                if key not in {"type", "code", "message", "details"}
            }
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": conflict,
                },
                409,
            )

        updated_content, applied_operations = apply_range_operations(
            current_content, operations
        )
        # The whole patched candidate goes through the same validator the agent
        # uses, so a source patch can never hold a weaker standard than an
        # agent edit. Nothing is written until it comes back non-blocking.
        validation = validate_candidate_source(
            filename=filename, raw_yaml=updated_content
        )
        diagnostics = validation.diagnostics
        if validation.blocking:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "invalid_patched_source",
                        "code": "invalid_patched_source",
                        "message": "The patch would produce an invalid interview.",
                        "details": {"diagnostics": diagnostics},
                    },
                },
                422,
            )

        model = validation.model or parse_interview_yaml(updated_content)
        source_diff = unified_source_diff(current_content, updated_content, filename)
        playground_write_yaml(uid, project, filename, updated_content)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "raw_yaml": updated_content,
                    "revision": validation.revision,
                    "applied_operations": applied_operations,
                    "diagnostics": diagnostics,
                    "summary": validation.public_summary(),
                    "diff": source_diff,
                    "blocks": model["blocks"],
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "validation_error",
                    "code": "invalid_patch_request",
                    "message": str(exc),
                },
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: source patch error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "code": "patch_failed",
                    "message": "The source patch could not be applied.",
                },
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/file/metadata", methods=["POST"])
def editor_api_save_metadata() -> Response:
    """Update only existing metadata-related YAML documents."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        edited_yaml = post_data.get("raw_yaml")
        expected_revision = post_data.get("expected_revision")
        if not isinstance(edited_yaml, str):
            raise ValueError("raw_yaml must be a YAML string")
        if not isinstance(expected_revision, str) or not expected_revision:
            raise ValueError("expected_revision is required")

        current_content = playground_read_yaml(uid, project, filename)
        current_revision = source_revision(current_content)
        if expected_revision != current_revision:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "revision_conflict",
                        "code": "revision_conflict",
                        "message": "The file changed since it was loaded.",
                        "expected_revision": expected_revision,
                        "current_revision": current_revision,
                    },
                },
                409,
            )

        updated_content = update_metadata_documents_in_yaml(
            current_content, edited_yaml
        )
        playground_write_yaml(uid, project, filename, updated_content)
        model = parse_interview_yaml(updated_content)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "blocks": model["blocks"],
                    "metadata_blocks": model["metadata_blocks"],
                    "include_blocks": model["include_blocks"],
                    "default_screen_parts_blocks": model["default_screen_parts_blocks"],
                    "order_blocks": model["order_blocks"],
                    "raw_yaml": updated_content,
                    "revision": source_revision(updated_content),
                    "metadata_raw_yaml": metadata_source_slice(updated_content),
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: save metadata error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


RUNTIME_INSPECTION_ACTIONS = {
    "al_weaver.inspect_object",
    "al_weaver.inspect_variable",
    "al_weaver.inspect_event_stack",
    "al_weaver.inspect_gathering_state",
}
RUNTIME_ACTION_RESULT_LIMIT = 256 * 1024
RUNTIME_VARIABLE_RESULT_LIMIT = 1024 * 1024


def _runtime_inspector_enabled() -> bool:
    return _weaver_flag("runtime inspector", False)


def _runtime_disabled(request_id: str) -> Response:
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "feature_disabled",
                "code": "runtime_inspector_disabled",
                "message": "The runtime session inspector is not enabled.",
            },
        },
        404,
    )


def _runtime_not_found(request_id: str) -> Response:
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "not_found",
                "code": "runtime_session_not_found",
                "message": "The target session was not found.",
            },
        },
        404,
    )


def _runtime_operation_failed(
    request_id: str, operation: str, exc: Exception
) -> Response:
    log(
        "ALWeaver editor: runtime operation failed "
        f"operation={operation} error_type={type(exc).__name__}",
        "error",
    )
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "runtime_error",
                "code": "runtime_operation_failed",
                "message": "Docassemble could not complete the runtime inspection request.",
                "details": {"operation": operation},
            },
        },
        502,
    )


def _runtime_target_url(record: Any) -> str:
    return (
        "/interview?i="
        + quote(record.yaml_filename, safe="")
        + "&session="
        + quote(record.docassemble_session_id, safe="")
    )


def _load_owned_runtime_session(weaver_session_id: str) -> Any:
    return load_runtime_record(r, weaver_session_id, _current_user_id())


@app.route(f"{EDITOR_BASE_PATH}/api/runtime/sessions", methods=["POST"])
def editor_api_runtime_create_session() -> Response:
    """Create a separate Docassemble target session for runtime inspection."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _runtime_inspector_enabled():
        return _runtime_disabled(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        purpose = str(post_data.get("purpose") or "test").strip()
        if purpose not in {"test", "scenario", "inspection"}:
            raise ValueError("purpose must be test, scenario, or inspection")
        url_args = post_data.get("url_args")
        if url_args is not None and not isinstance(url_args, dict):
            raise ValueError("url_args must be an object or null")

        # Confirms this developer owns the requested Playground file.
        playground_read_yaml(uid, project, filename)
        yaml_filename = playground_yaml_filename(uid, project, filename)
        target = create_target_session(
            yaml_filename,
            secret=None,
            url_args=url_args or None,
        )
        if target.secret is not None:
            raise ValueError("Encrypted target sessions are not currently supported")
        record = create_runtime_record(
            weaver_session_id=str(uuid.uuid4()),
            owner_user_id=uid,
            project=project,
            filename=filename,
            yaml_filename=yaml_filename,
            target=target,
            purpose=purpose,
        )
        store_runtime_record(r, record)
        return jsonify_with_status(
            {
                "success": True,
                "request_id": request_id,
                "data": record.public_dict(_runtime_target_url(record)),
            },
            201,
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "validation_error",
                    "code": "invalid_runtime_session_request",
                    "message": str(exc),
                },
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: runtime session creation failed: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "code": "runtime_session_creation_failed",
                    "message": "The target Docassemble session could not be created.",
                },
            },
            500,
        )


@app.route(
    f"{EDITOR_BASE_PATH}/api/runtime/sessions/<weaver_session_id>",
    methods=["GET", "DELETE"],
)
def editor_api_runtime_session(weaver_session_id: str) -> Response:
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _runtime_inspector_enabled():
        return _runtime_disabled(request_id)
    record = _load_owned_runtime_session(weaver_session_id)
    if record is None:
        return _runtime_not_found(request_id)
    if request.method == "DELETE":
        delete_runtime_record(r, weaver_session_id, _current_user_id())
        return jsonify(
            {"success": True, "request_id": request_id, "data": {"deleted": True}}
        )
    return jsonify(
        {
            "success": True,
            "request_id": request_id,
            "data": record.public_dict(_runtime_target_url(record)),
        }
    )


@app.route(
    f"{EDITOR_BASE_PATH}/api/runtime/sessions/<weaver_session_id>/variables",
    methods=["GET", "POST"],
)
def editor_api_runtime_variables(weaver_session_id: str) -> Response:
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _runtime_inspector_enabled():
        return _runtime_disabled(request_id)
    record = _load_owned_runtime_session(weaver_session_id)
    if record is None:
        return _runtime_not_found(request_id)
    try:
        target = record.target()
        if request.method == "POST":
            post_data = request.get_json(silent=True)
            if not isinstance(post_data, dict):
                raise ValueError("Request body must be a JSON object")
            scenario_yaml = post_data.get("scenario_yaml")
            if scenario_yaml is not None:
                if not isinstance(scenario_yaml, str):
                    raise ValueError("scenario_yaml must be a string")
                scenario = yaml.safe_load(scenario_yaml)
                if not isinstance(scenario, dict):
                    raise ValueError("Scenario YAML must contain a mapping")
                post_data = scenario
            variables = post_data.get("variables", {})
            delete = post_data.get("delete", [])
            if not isinstance(variables, dict):
                raise ValueError("variables must be an object")
            if not isinstance(delete, list) or not all(
                isinstance(name, str) and name.strip() for name in delete
            ):
                raise ValueError("delete must be a list of variable names")
            serialized_input = json.dumps(
                {"variables": variables, "delete": delete}, default=str
            )
            if len(serialized_input.encode("utf-8")) > RUNTIME_ACTION_RESULT_LIMIT:
                raise ValueError("Variable payload is too large")
            set_target_variables(
                target,
                variables,
                delete=delete,
                overwrite=bool(post_data.get("overwrite", False)),
                process_objects=False,
            )
            append_runtime_event(
                r,
                record,
                "scenario_applied",
                set_count=len(variables),
                delete_count=len(delete),
            )
            return jsonify(
                {
                    "success": True,
                    "request_id": request_id,
                    "data": {"updated": True},
                }
            )

        variables = get_target_variables(target, simplify=True)
        include_internal = parse_bool(
            request.args.get("include_internal"), default=False
        )
        if not include_internal:
            variables = {
                key: value
                for key, value in variables.items()
                if not str(key).startswith("_internal")
            }
        serialized = json.dumps(variables, default=str)
        if len(serialized.encode("utf-8")) > RUNTIME_VARIABLE_RESULT_LIMIT:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "response_too_large",
                        "code": "runtime_variables_too_large",
                        "message": "The simplified variable result is too large to display.",
                    },
                },
                413,
            )
        append_runtime_event(r, record, "variables_refreshed")
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "variables": variables,
                    "includes_internal": include_internal,
                    "fact_source": "observed_runtime",
                },
            }
        )
    except ValueError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "validation_error",
                    "code": "invalid_runtime_variable_request",
                    "message": str(exc),
                },
            },
            400,
        )
    except Exception as exc:
        return _runtime_operation_failed(request_id, "variables", exc)


@app.route(
    f"{EDITOR_BASE_PATH}/api/runtime/sessions/<weaver_session_id>/question",
    methods=["GET"],
)
def editor_api_runtime_question(weaver_session_id: str) -> Response:
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _runtime_inspector_enabled():
        return _runtime_disabled(request_id)
    record = _load_owned_runtime_session(weaver_session_id)
    if record is None:
        return _runtime_not_found(request_id)
    try:
        question = get_target_question(record.target())
        append_runtime_event(
            r,
            record,
            "question_returned",
            question_name=question.get("questionName"),
        )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"question": question, "fact_source": "observed_runtime"},
            }
        )
    except Exception as exc:
        return _runtime_operation_failed(request_id, "question", exc)


@app.route(
    f"{EDITOR_BASE_PATH}/api/runtime/sessions/<weaver_session_id>/back",
    methods=["POST"],
)
def editor_api_runtime_back(weaver_session_id: str) -> Response:
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _runtime_inspector_enabled():
        return _runtime_disabled(request_id)
    record = _load_owned_runtime_session(weaver_session_id)
    if record is None:
        return _runtime_not_found(request_id)
    try:
        go_back_target_session(record.target())
        append_runtime_event(r, record, "back_invoked")
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"went_back": True},
            }
        )
    except Exception as exc:
        return _runtime_operation_failed(request_id, "back", exc)


@app.route(
    f"{EDITOR_BASE_PATH}/api/runtime/sessions/<weaver_session_id>/actions/<action_name>",
    methods=["POST"],
)
def editor_api_runtime_action(weaver_session_id: str, action_name: str) -> Response:
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _runtime_inspector_enabled():
        return _runtime_disabled(request_id)
    record = _load_owned_runtime_session(weaver_session_id)
    if record is None:
        return _runtime_not_found(request_id)
    if action_name not in RUNTIME_INSPECTION_ACTIONS:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "forbidden_action",
                    "code": "runtime_action_not_allowed",
                    "message": "That runtime inspection action is not allowlisted.",
                },
            },
            403,
        )
    post_data = request.get_json(silent=True) or {}
    arguments = post_data.get("arguments", {})
    if not isinstance(arguments, dict):
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "validation_error",
                    "code": "invalid_runtime_action_arguments",
                    "message": "arguments must be an object",
                },
            },
            400,
        )
    try:
        result = run_target_action_raw(
            record.target(), action_name, arguments=arguments, read_only=True
        )
    except Exception as exc:
        return _runtime_operation_failed(request_id, "action", exc)
    data = result.data
    if isinstance(data, (bytes, bytearray)) or (
        isinstance(data, str)
        and data.lstrip().lower().startswith(("<!doctype html", "<html"))
    ):
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "invalid_action_response",
                    "code": "runtime_action_response_rejected",
                    "message": "The inspection action returned an unsupported response.",
                },
            },
            502,
        )
    try:
        serialized = json.dumps(
            {"status": result.status, "data": data, "warnings": result.warnings}
        )
    except (TypeError, ValueError):
        serialized = ""
    if not serialized or len(serialized.encode("utf-8")) > RUNTIME_ACTION_RESULT_LIMIT:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "invalid_action_response",
                    "code": "runtime_action_response_rejected",
                    "message": "The inspection action response cannot be displayed safely.",
                },
            },
            502,
        )
    append_runtime_event(r, record, "action_invoked", action=action_name)
    return jsonify(
        {
            "success": True,
            "request_id": request_id,
            "data": {
                "status": result.status,
                "data": data,
                "warnings": result.warnings,
                "fact_source": "observed_runtime",
            },
        }
    )


# ---------------------------------------------------------------------------
# Agent editing sessions
#
# The browser hands over a working source snapshot; the server binds the
# session to one project and filename and never lets a model change either.
# Nothing in this section writes to the Playground: Apply hands the candidate
# back to the editor as unsaved state, and the existing Save path persists it.
# ---------------------------------------------------------------------------


def _agent_disabled(request_id: str) -> Response:
    """Explain why the assistant cannot serve this request.

    A feature an administrator switched off is a 404; a feature that is on but
    has nothing to talk to is a 503, because the fix is configuration rather
    than a different request.
    """
    status = _assistant_status()
    turned_off = status["code"] == ASSISTANT_STATUS_DISABLED
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "feature_disabled" if turned_off else "assistant_unavailable",
                "code": (
                    "agent_editor_disabled" if turned_off else "assistant_unavailable"
                ),
                "message": status["message"],
                "details": {"status": status},
            },
        },
        404 if turned_off else 503,
    )


def _agent_not_found(request_id: str) -> Response:
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "not_found",
                "code": "agent_session_not_found",
                "message": "The assistant session was not found or has expired.",
            },
        },
        404,
    )


def _agent_validation_error(request_id: str, exc: Exception) -> Response:
    status = 404 if isinstance(exc, FileNotFoundError) else 400
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "validation_error",
                "code": "invalid_agent_request",
                "message": str(exc),
            },
        },
        status,
    )


def _agent_stale(request_id: str, session: Any, current_revision: str) -> Response:
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "stale_source",
                "code": "agent_session_stale",
                "message": (
                    "Source changed since this agent session began. Restart the "
                    "assistant against the current interview."
                ),
                "details": {
                    "base_revision": session.base_saved_revision,
                    "current_revision": current_revision,
                },
            },
        },
        409,
    )


def _log_agent_event(**fields: Any) -> None:
    """Record an agent operation without ever logging interview content.

    Prompts, interview text, uploaded document text and runtime variable values
    stay out of the server log; the detailed conversation lives in the
    owner-scoped Redis record for the session lifetime instead.
    """
    log(
        "ALWeaver editor agent: "
        + " ".join(
            f"{key}={value}" for key, value in fields.items() if value is not None
        ),
        "info",
    )


class _AgentRuntimeBridge:
    """Read-only access to the existing runtime inspector, for agent tools.

    This does not reimplement Docassemble runtime execution: it drives the same
    server-owned target session records the inspector UI already uses, and only
    ever runs allowlisted ``al_weaver.inspect_*`` actions.
    """

    def __init__(self, user_id: int, project: str, filename: str):
        self._user_id = user_id
        self._project = project
        self._filename = filename
        self._record: Any = None

    def _target(self) -> Any:
        if self._record is None:
            raise ValueError("No runtime session has been started")
        return self._record.target()

    def start_session(self) -> Dict[str, Any]:
        playground_read_yaml(self._user_id, self._project, self._filename)
        yaml_filename = playground_yaml_filename(
            self._user_id, self._project, self._filename
        )
        target = create_target_session(yaml_filename, secret=None, url_args=None)
        if target.secret is not None:
            raise ValueError("Encrypted target sessions are not currently supported")
        record = create_runtime_record(
            weaver_session_id=str(uuid.uuid4()),
            owner_user_id=self._user_id,
            project=self._project,
            filename=self._filename,
            yaml_filename=yaml_filename,
            target=target,
            purpose="inspection",
        )
        store_runtime_record(r, record)
        self._record = record
        return {
            "weaver_session_id": record.weaver_session_id,
            "target_url": _runtime_target_url(record),
        }

    def current_question(self) -> Dict[str, Any]:
        question = get_target_question(self._target())
        append_runtime_event(r, self._record, "question_returned")
        return {"question": question}

    def variables(self) -> Dict[str, Any]:
        values = get_target_variables(self._target(), simplify=True)
        values = {
            key: value
            for key, value in values.items()
            if not str(key).startswith("_internal")
        }
        serialized = json.dumps(values, default=str)
        if len(serialized.encode("utf-8")) > RUNTIME_VARIABLE_RESULT_LIMIT:
            raise ValueError("The runtime variable result is too large to inspect")
        append_runtime_event(r, self._record, "variables_refreshed")
        return {"variables": values}

    def apply_scenario(
        self, variables: Dict[str, Any], delete: List[str]
    ) -> Dict[str, Any]:
        if not isinstance(variables, dict):
            raise ValueError("variables must be an object")
        delete_names = [str(name) for name in (delete or []) if str(name).strip()]
        serialized = json.dumps(
            {"variables": variables, "delete": delete_names}, default=str
        )
        if len(serialized.encode("utf-8")) > RUNTIME_ACTION_RESULT_LIMIT:
            raise ValueError("Variable payload is too large")
        set_target_variables(
            self._target(),
            variables,
            delete=delete_names,
            overwrite=False,
            process_objects=False,
        )
        append_runtime_event(
            r,
            self._record,
            "scenario_applied",
            set_count=len(variables),
            delete_count=len(delete_names),
        )
        return {"updated": True}

    def back(self) -> Dict[str, Any]:
        go_back_target_session(self._target())
        append_runtime_event(r, self._record, "back_invoked")
        return {"went_back": True}

    def inspect(self, action_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if action_name not in RUNTIME_INSPECTION_ACTIONS:
            raise ValueError("That runtime inspection action is not allowlisted")
        result = run_target_action_raw(
            self._target(), action_name, arguments=arguments or {}, read_only=True
        )
        data = result.data
        if isinstance(data, (bytes, bytearray)) or (
            isinstance(data, str)
            and data.lstrip().lower().startswith(("<!doctype html", "<html"))
        ):
            raise ValueError("The inspection action returned an unsupported response")
        serialized = json.dumps({"status": result.status, "data": data}, default=str)
        if len(serialized.encode("utf-8")) > RUNTIME_ACTION_RESULT_LIMIT:
            raise ValueError("The inspection action response is too large")
        append_runtime_event(r, self._record, "action_invoked", action=action_name)
        return {"status": result.status, "data": data}


def _load_owned_agent_session(session_id: str) -> Any:
    return load_agent_session(r, session_id, _current_user_id())


def _agent_session_payload(
    session: Any, *, current_revision: Optional[str] = None
) -> Dict[str, Any]:
    payload = session.public_dict()
    payload["saved_revision"] = current_revision
    payload["stale"] = (
        current_revision is not None and current_revision != session.base_saved_revision
    )
    return payload


@app.route(f"{EDITOR_BASE_PATH}/api/agent/sessions", methods=["POST"])
def editor_api_agent_create_session() -> Response:
    """Start an agent conversation bound to one Playground file."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _agent_editor_available():
        return _agent_disabled(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        raw_yaml = post_data.get("raw_yaml")
        if not isinstance(raw_yaml, str):
            raise ValueError("raw_yaml must be a YAML string")
        if len(raw_yaml.encode("utf-8")) > MAX_CANDIDATE_SOURCE_BYTES:
            raise ValueError("This interview is too large for the editing assistant")
        base_revision = post_data.get("base_revision")
        if not isinstance(base_revision, str) or not base_revision:
            raise ValueError("base_revision is required")

        # Reading the target proves this developer owns the Playground file.
        saved_yaml = playground_read_yaml(uid, project, filename)
        current_revision = source_revision(saved_yaml)
        if base_revision != current_revision:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "stale_source",
                        "code": "agent_base_revision_stale",
                        "message": (
                            "The saved file changed after this editor buffer was "
                            "loaded. Reload the interview before starting the "
                            "assistant."
                        ),
                        "details": {
                            "base_revision": base_revision,
                            "current_revision": current_revision,
                        },
                    },
                },
                409,
            )

        auto_heal = bool(post_data.get("auto_heal", False))
        candidate_source = raw_yaml
        repaired_source: Optional[str] = None
        repairs: List[Dict[str, Any]] = []
        validation = validate_candidate_source(filename=filename, raw_yaml=raw_yaml)

        if validation.blocking and auto_heal:
            # Mechanical id problems are repaired deterministically, never by a
            # model. The repairs are part of the candidate, so they show up in
            # the diff the developer reviews before saving.
            repair_result = auto_heal_source(filename=filename, raw_yaml=raw_yaml)
            if repair_result.healed:
                candidate_source = repair_result.raw_yaml
                repaired_source = repair_result.raw_yaml
                repairs = [item.public_dict() for item in repair_result.repairs]
                validation = repair_result.validation or validate_candidate_source(
                    filename=filename, raw_yaml=candidate_source
                )
                _log_agent_event(
                    request_id=request_id,
                    user=uid,
                    project=project,
                    filename=filename,
                    event="working_source_repaired",
                    repairs=len(repairs),
                )

        if validation.blocking:
            offer = describe_repair_offer(filename=filename, raw_yaml=raw_yaml)
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "invalid_working_source",
                        "code": "invalid_working_source",
                        "message": (
                            "The assistant needs a valid interview to start from. "
                            "Fix the errors below, then try again."
                        ),
                        "details": {
                            "diagnostics": validation.blocking_diagnostics(),
                            **offer,
                        },
                    },
                },
                422,
            )

        session = WeaverAgentSession(
            session_id=str(uuid.uuid4()),
            owner_user_id=uid,
            project=project,
            filename=filename,
            base_saved_revision=current_revision,
            # The diff base stays the developer's own source so any repair is
            # visible; Reset returns to the repaired baseline instead.
            original_working_source=raw_yaml,
            candidate_source=candidate_source,
            candidate_revision=validation.revision,
            repaired_working_source=repaired_source,
            repairs=repairs,
        )
        store_agent_session(r, session)
        _log_agent_event(
            request_id=request_id,
            agent_session=session.session_id,
            user=uid,
            project=project,
            filename=filename,
            event="session_created",
            repairs=len(repairs) or None,
        )
        return jsonify_with_status(
            {
                "success": True,
                "request_id": request_id,
                "data": _agent_session_payload(
                    session, current_revision=current_revision
                ),
            },
            201,
        )
    except (ValueError, FileNotFoundError) as exc:
        return _agent_validation_error(request_id, exc)
    except Exception as exc:
        log(f"ALWeaver editor: agent session creation failed: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "code": "agent_session_creation_failed",
                    "message": "The assistant session could not be created.",
                },
            },
            500,
        )


@app.route(
    f"{EDITOR_BASE_PATH}/api/agent/sessions/<session_id>", methods=["GET", "DELETE"]
)
def editor_api_agent_session(session_id: str) -> Response:
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _agent_editor_available():
        return _agent_disabled(request_id)
    session = _load_owned_agent_session(session_id)
    if session is None:
        return _agent_not_found(request_id)
    if request.method == "DELETE":
        delete_agent_session(r, session_id, _current_user_id())
        clear_progress(r, session_id)
        return jsonify(
            {"success": True, "request_id": request_id, "data": {"deleted": True}}
        )
    try:
        current_revision = source_revision(
            playground_read_yaml(
                session.owner_user_id, session.project, session.filename
            )
        )
    except (ValueError, FileNotFoundError):
        current_revision = None
    return jsonify(
        {
            "success": True,
            "request_id": request_id,
            "data": _agent_session_payload(session, current_revision=current_revision),
        }
    )


def _run_agent_turn_in_background(
    *,
    session_id: str,
    owner_user_id: int,
    message: str,
    selected_block_id: Optional[str],
    runtime_enabled: bool,
    request_id: str,
    started_at: float,
) -> None:
    """Run one turn to completion outside the request that asked for it.

    Everything needed is looked up fresh here, so the thread holds no Flask
    request state. Whatever happens — success, refusal or crash — the outcome
    lands in the progress record, because that is the only place the browser
    can still read it once the original request is gone.
    """
    live_events: List[Dict[str, Any]] = [
        {"type": "status", "label": "Starting", "status": "thinking"}
    ]

    def publish_progress(
        running: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> None:
        store_progress(
            r,
            session_id,
            owner_user_id,
            running=running,
            events=live_events,
            started_at=started_at,
            result=result,
            error=error,
        )

    model_name = ""
    try:
        session = load_agent_session(r, session_id, owner_user_id)
        if session is None:
            publish_progress(
                False,
                error={
                    "code": "agent_session_not_found",
                    "message": "The assistant session expired before the request ran.",
                },
            )
            return

        llms = _load_llms_module()
        if llms is None:
            raise AgentConfigurationError("docassemble.ALToolbox.llms is not available")
        model_name = pick_agent_model_name(llms, _weaver_text("assistant model"))
        runtime = (
            _AgentRuntimeBridge(
                session.owner_user_id, session.project, session.filename
            )
            if runtime_enabled
            else None
        )

        def should_cancel() -> bool:
            latest = load_agent_session(r, session_id, owner_user_id)
            return bool(latest and latest.cancelled)

        def on_event(event: Dict[str, Any]) -> None:
            live_events.append(event)
            publish_progress(True)

        candidate = session.candidate()
        result = run_agent_turn(
            session=session,
            candidate=candidate,
            user_message=message,
            llms_module=llms,
            model_name=model_name,
            runtime_enabled=runtime_enabled,
            runtime=runtime,
            selected_block_id=selected_block_id,
            should_cancel=should_cancel,
            on_event=on_event,
        )
        record_turn(session, result)
        store_agent_session(r, session)

        for command in candidate.applied_commands:
            _log_agent_event(
                request_id=request_id,
                agent_session=session_id,
                user=owner_user_id,
                project=session.project,
                filename=session.filename,
                model=model_name,
                tool=command.get("tool"),
                status=command.get("status"),
                before_revision=command.get("before_revision"),
                after_revision=command.get("after_revision"),
            )
        _log_agent_event(
            request_id=request_id,
            agent_session=session_id,
            user=owner_user_id,
            model=model_name,
            event="turn_finished",
            status=result.status,
            stop_reason=result.stop_reason,
            errors=len(
                [
                    item
                    for item in result.diagnostics
                    if str(item.get("level")) == "error"
                ]
            ),
            latency_ms=int((time.time() - started_at) * 1000),
        )
        payload = dict(result.public_dict())
        payload["session"] = _agent_session_payload(session)
        publish_progress(False, result=payload)
    except AgentConfigurationError as exc:
        publish_progress(
            False, error={"code": "agent_model_unavailable", "message": str(exc)}
        )
    except Exception as exc:  # noqa: BLE001 - a lost thread must not hang the UI
        log(f"ALWeaver editor: agent turn failed: {exc!r}", "error")
        _log_agent_event(
            request_id=request_id,
            agent_session=session_id,
            user=owner_user_id,
            model=model_name or None,
            event="turn_failed",
            error_type=type(exc).__name__,
        )
        publish_progress(
            False,
            error={
                "code": "agent_turn_failed",
                "message": "The assistant could not complete that request.",
            },
        )


@app.route(f"{EDITOR_BASE_PATH}/api/agent/sessions/<session_id>/turn", methods=["POST"])
def editor_api_agent_turn(session_id: str) -> Response:
    """Start one bounded agent turn and return immediately.

    A turn routinely outlives any HTTP request: the browser client gives up
    after its own timeout and nginx closes an idle upstream read at sixty
    seconds by default, while a multi-step edit takes longer than that. So the
    work runs in the background and the browser follows it through the progress
    endpoint instead of holding a request open.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _agent_editor_available():
        return _agent_disabled(request_id)
    session = _load_owned_agent_session(session_id)
    if session is None:
        return _agent_not_found(request_id)
    started_at = time.time()
    try:
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        message = post_data.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if len(message) > MAX_CHAT_MESSAGE_CHARS:
            raise ValueError(
                f"A chat message may be at most {MAX_CHAT_MESSAGE_CHARS} characters"
            )
        selected_block_id = post_data.get("selected_block_id")
        if selected_block_id is not None and not isinstance(selected_block_id, str):
            raise ValueError("selected_block_id must be a string or null")

        if session.is_exhausted:
            # This assistant is for small, discrete edits. Rather than letting a
            # conversation sprawl until each turn is slow and vague, it stops and
            # asks for the work so far to be applied and a fresh chat started.
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "conflict",
                        "code": "turn_limit_reached",
                        "message": (
                            f"This chat has reached its {MAX_TURNS_PER_SESSION}-request "
                            "limit. Apply what you have, then start a new chat for the "
                            "next change — the assistant works best on one task at a time."
                        ),
                        "details": {"max_turns": MAX_TURNS_PER_SESSION},
                    },
                },
                409,
            )

        if progress_is_live(load_progress(r, session_id, session.owner_user_id)):
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "conflict",
                        "code": "turn_in_progress",
                        "message": "This assistant is still working on the previous request.",
                    },
                },
                409,
            )

        session.cancelled = False
        session.turn_count = int(session.turn_count) + 1
        store_agent_session(r, session)
        store_progress(
            r,
            session_id,
            session.owner_user_id,
            running=True,
            events=[{"type": "status", "label": "Starting", "status": "thinking"}],
            started_at=started_at,
        )

        try:
            workerapp.send_task(
                AGENT_TURN_CELERY_TASK,
                kwargs={
                    "session_id": session_id,
                    "owner_user_id": session.owner_user_id,
                    "message": message,
                    "selected_block_id": selected_block_id,
                    "runtime_enabled": _runtime_inspector_enabled(),
                    "request_id": request_id,
                    "started_at": started_at,
                },
            )
        except Exception as exc:
            log(f"ALWeaver editor: could not queue agent turn: {exc!r}", "error")
            clear_progress(r, session_id)
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "server_error",
                        "code": "agent_turn_not_queued",
                        "message": (
                            "The assistant could not be started. Check that this "
                            "server's background worker is running."
                        ),
                    },
                },
                503,
            )
        return jsonify_with_status(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "started": True,
                    "started_at": started_at,
                    "session": _agent_session_payload(session),
                },
            },
            202,
        )
    except (ValueError, FileNotFoundError) as exc:
        clear_progress(r, session_id)
        return _agent_validation_error(request_id, exc)
    except AgentConfigurationError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "code": "agent_model_unavailable",
                    "message": str(exc),
                },
            },
            503,
        )
    except Exception as exc:
        log(f"ALWeaver editor: agent turn failed: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "code": "agent_turn_failed",
                    "message": "The assistant could not complete that request.",
                },
            },
            500,
        )


@app.route(
    f"{EDITOR_BASE_PATH}/api/agent/sessions/<session_id>/progress", methods=["GET"]
)
def editor_api_agent_progress(session_id: str) -> Response:
    """Report what the running turn has done so far.

    Polled by the browser while a turn is in flight. Reads a dedicated record
    rather than the session, so it never races the turn's own writes.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _agent_editor_available():
        return _agent_disabled(request_id)
    uid = _current_user_id()
    if load_agent_session(r, session_id, uid) is None:
        return _agent_not_found(request_id)
    progress = load_progress(r, session_id, uid) or {
        "running": False,
        "events": [],
        "started_at": None,
    }
    return jsonify({"success": True, "request_id": request_id, "data": progress})


@app.route(
    f"{EDITOR_BASE_PATH}/api/agent/sessions/<session_id>/cancel", methods=["POST"]
)
def editor_api_agent_cancel(session_id: str) -> Response:
    """Ask a running turn to stop before its next model or tool step."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _agent_editor_available():
        return _agent_disabled(request_id)
    session = _load_owned_agent_session(session_id)
    if session is None:
        return _agent_not_found(request_id)
    session.cancelled = True
    store_agent_session(r, session)
    return jsonify(
        {"success": True, "request_id": request_id, "data": {"cancelled": True}}
    )


@app.route(
    f"{EDITOR_BASE_PATH}/api/agent/sessions/<session_id>/reset", methods=["POST"]
)
def editor_api_agent_reset(session_id: str) -> Response:
    """Return the candidate to the working source the session started with."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _agent_editor_available():
        return _agent_disabled(request_id)
    session = _load_owned_agent_session(session_id)
    if session is None:
        return _agent_not_found(request_id)
    session.reset_candidate()
    store_agent_session(r, session)
    clear_progress(r, session_id)
    _log_agent_event(
        request_id=request_id,
        agent_session=session.session_id,
        user=session.owner_user_id,
        event="session_reset",
    )
    return jsonify(
        {
            "success": True,
            "request_id": request_id,
            "data": _agent_session_payload(session),
        }
    )


@app.route(
    f"{EDITOR_BASE_PATH}/api/agent/sessions/<session_id>/apply", methods=["POST"]
)
def editor_api_agent_apply(session_id: str) -> Response:
    """Hand the candidate back to the browser as unsaved editor state.

    This endpoint never writes to the Playground. The developer applies, looks
    at the result, and then saves through the editor's existing Save path.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _agent_editor_available():
        return _agent_disabled(request_id)
    session = _load_owned_agent_session(session_id)
    if session is None:
        return _agent_not_found(request_id)
    try:
        saved_yaml = playground_read_yaml(
            session.owner_user_id, session.project, session.filename
        )
        current_revision = source_revision(saved_yaml)
        if current_revision != session.base_saved_revision:
            return _agent_stale(request_id, session, current_revision)

        validation = validate_candidate_source(
            filename=session.filename, raw_yaml=session.candidate_source
        )
        if validation.blocking:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "invalid_candidate",
                        "code": "invalid_candidate",
                        "message": "This candidate has validation errors and cannot be applied.",
                        "details": {"diagnostics": validation.blocking_diagnostics()},
                    },
                },
                422,
            )

        candidate = session.candidate()
        _log_agent_event(
            request_id=request_id,
            agent_session=session.session_id,
            user=session.owner_user_id,
            project=session.project,
            filename=session.filename,
            event="candidate_applied",
            candidate_revision=session.candidate_revision,
            commands=len(session.command_history),
        )
        payload = _build_file_response_data(
            session.candidate_source, session.project, session.filename
        )
        payload.update(
            {
                "candidate_revision": session.candidate_revision,
                # The revision the editor stays dirty against: applying hands
                # the candidate to the browser and writes nothing to disk.
                "saved_revision": current_revision,
                "metadata_raw_yaml": metadata_source_slice(session.candidate_source),
                "diff": candidate.diff(session.filename),
                "diagnostics": validation.diagnostics,
                "summary": validation.public_summary(),
            }
        )
        return jsonify({"success": True, "request_id": request_id, "data": payload})
    except (ValueError, FileNotFoundError) as exc:
        return _agent_validation_error(request_id, exc)
    except Exception as exc:
        log(f"ALWeaver editor: agent apply failed: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "code": "agent_apply_failed",
                    "message": "The candidate could not be applied.",
                },
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/file/rename", methods=["POST"])
def editor_api_rename_file() -> Response:
    """Rename a YAML interview file within the current playground project."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        old_filename = _normalize_filename(post_data.get("filename"))
        new_filename = _normalize_renamed_filename(
            post_data.get("new_filename"), old_filename
        )
        if old_filename == new_filename:
            raise ValueError("New filename must be different")
        area, directory = _editor_playground_directory(uid, project)
        rename_saved_file(area, directory, old_filename, new_filename)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": new_filename,
                    "old_filename": old_filename,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: rename file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/file/delete", methods=["POST"])
def editor_api_delete_file() -> Response:
    """Delete a YAML interview file from the current playground project."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        area, directory = _editor_playground_directory(uid, project)
        delete_saved_file(area, directory, filename)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: delete file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-file/rename", methods=["POST"])
def editor_api_rename_section_file() -> Response:
    """Rename a file inside templates/modules/static/data sources."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        section = _normalize_section(post_data.get("section"))
        old_filename = _normalize_storage_filename(post_data.get("filename"))
        new_filename = _normalize_renamed_storage_filename(
            post_data.get("new_filename"), old_filename
        )
        if old_filename == new_filename:
            raise ValueError("New filename must be different")
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        area, directory = _editor_storage_directory(uid, project, storage_section)
        rename_saved_file(area, directory, old_filename, new_filename)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "filename": new_filename,
                    "old_filename": old_filename,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: rename section-file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/section-file/delete", methods=["POST"])
def editor_api_delete_section_file() -> Response:
    """Delete a file inside templates/modules/static/data sources."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        section = _normalize_section(post_data.get("section"))
        filename = _normalize_storage_filename(post_data.get("filename"))
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        area, directory = _editor_storage_directory(uid, project, storage_section)
        delete_saved_file(area, directory, filename)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": section,
                    "filename": filename,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: delete section-file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/block", methods=["POST"])
def editor_api_save_block() -> Response:
    """Update a single block in a YAML file by block id."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        block_id = str(post_data.get("block_id", "")).strip()
        new_yaml = post_data.get("block_yaml")
        if not block_id:
            raise ValueError("block_id is required")
        if not isinstance(new_yaml, str) or not new_yaml.strip():
            raise ValueError("block_yaml must be a non-empty YAML string")
        _validate_block_yaml_payload(new_yaml)

        current_content = playground_read_yaml(uid, project, filename)
        updated_content = update_block_in_yaml(current_content, block_id, new_yaml)
        playground_write_yaml(uid, project, filename, updated_content)

        model = parse_interview_yaml(updated_content)
        order_step_map: Dict[str, List[Dict[str, Any]]] = {}
        order_steps: list = []
        for idx in model.get("order_blocks", []):
            block = model["blocks"][idx]
            code = block.get("data", {}).get("code", "")
            if code:
                parsed_steps = parse_order_code(code)
                order_step_map[block["id"]] = parsed_steps
                if not order_steps:
                    order_steps = parsed_steps
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "blocks": model["blocks"],
                    "metadata_blocks": model["metadata_blocks"],
                    "include_blocks": model["include_blocks"],
                    "default_screen_parts_blocks": model["default_screen_parts_blocks"],
                    "order_blocks": model["order_blocks"],
                    "order_steps": order_steps,
                    "order_step_map": order_step_map,
                    "raw_yaml": updated_content,
                    "saved_block_id": block_id,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: save block error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/block/delete", methods=["POST"])
def editor_api_delete_block() -> Response:
    """Delete a single block from a YAML file by block id."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        block_id = str(post_data.get("block_id", "")).strip()
        if not block_id:
            raise ValueError("block_id is required")

        current_content = playground_read_yaml(uid, project, filename)
        updated_content = delete_block_from_yaml(current_content, block_id)
        playground_write_yaml(uid, project, filename, updated_content)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": _build_file_response_data(updated_content, project, filename),
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: delete block error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/block/comment", methods=["POST"])
def editor_api_comment_block() -> Response:
    """Disable a single block by commenting it out in YAML."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        block_id = str(post_data.get("block_id", "")).strip()
        if not block_id:
            raise ValueError("block_id is required")

        current_content = playground_read_yaml(uid, project, filename)
        updated_content = comment_out_block_in_yaml(current_content, block_id)
        playground_write_yaml(uid, project, filename, updated_content)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": _build_file_response_data(updated_content, project, filename),
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: comment block error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/block/enable", methods=["POST"])
def editor_api_enable_block() -> Response:
    """Re-enable a previously commented-out block in a YAML file."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        block_id = str(post_data.get("block_id", "")).strip()
        if not block_id:
            raise ValueError("block_id is required")

        current_content = playground_read_yaml(uid, project, filename)
        updated_content = enable_commented_block_in_yaml(current_content, block_id)
        playground_write_yaml(uid, project, filename, updated_content)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": _build_file_response_data(updated_content, project, filename),
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: enable block error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/block/reorder", methods=["POST"])
def editor_api_reorder_blocks() -> Response:
    """Reorder all blocks in a YAML file by block id."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        block_ids = post_data.get("block_ids")
        if not isinstance(block_ids, list):
            raise ValueError("block_ids must be a list")
        normalized_block_ids = [
            str(block_id).strip() for block_id in block_ids if str(block_id).strip()
        ]

        current_content = playground_read_yaml(uid, project, filename)
        updated_content = reorder_blocks_in_yaml(current_content, normalized_block_ids)
        playground_write_yaml(uid, project, filename, updated_content)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": _build_file_response_data(updated_content, project, filename),
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: reorder blocks error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/insert-block", methods=["POST"])
def editor_api_insert_block() -> Response:
    """Insert a new block into a YAML file after the given block id.

    If ``insert_after_id`` is empty, the block is inserted at the top.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        _insert_raw = post_data.get("insert_after_id")
        insert_after_id = str(_insert_raw).strip() if _insert_raw else None
        block_yaml = post_data.get("block_yaml")
        if not isinstance(block_yaml, str) or not block_yaml.strip():
            raise ValueError("block_yaml must be a non-empty YAML string")
        _validate_block_yaml_payload(block_yaml)

        current_content = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(current_content)
        blocks = model["blocks"]

        block_text = canonicalize_block_yaml(block_yaml)
        existing_parts = [
            b["yaml"].strip()
            for b in blocks
            if b.get("yaml", "").strip() and b.get("yaml", "").strip() != "{}"
        ]

        insert_at: int
        if not insert_after_id:
            insert_at = 0
        else:
            found_insert_at: Optional[int] = None
            for idx, block in enumerate(blocks):
                if block.get("id") == insert_after_id:
                    found_insert_at = idx + 1
                    break
            if found_insert_at is None:
                raise ValueError(f"Block with id {insert_after_id!r} not found")
            insert_at = found_insert_at

        existing_parts.insert(insert_at, block_text)
        updated_content = "\n---\n".join(existing_parts) + "\n"
        playground_write_yaml(uid, project, filename, updated_content)

        updated_model = parse_interview_yaml(updated_content)
        inserted_block_id: Optional[str] = None
        id_match = re.search(r"(?m)^id:\s*['\"]?([^'\"\n]+)['\"]?\s*$", block_text)
        if id_match:
            inserted_block_id = id_match.group(1).strip()
        elif 0 <= insert_at < len(updated_model["blocks"]):
            inserted_block_id = (
                str(updated_model["blocks"][insert_at].get("id") or "").strip() or None
            )

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "blocks": updated_model["blocks"],
                    "metadata_blocks": updated_model["metadata_blocks"],
                    "include_blocks": updated_model["include_blocks"],
                    "default_screen_parts_blocks": updated_model[
                        "default_screen_parts_blocks"
                    ],
                    "order_blocks": updated_model["order_blocks"],
                    "raw_yaml": updated_content,
                    "inserted_block_id": inserted_block_id,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: insert block error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/variables", methods=["GET"])
def editor_api_variables() -> Response:
    """Get extracted variable names from a playground YAML file."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        data = None
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                data = playground_get_variables(uid, project, filename)
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise
        if data is None:
            raise last_exc or RuntimeError("Unable to extract variables.")
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": data,
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: variables error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/order", methods=["POST"])
def editor_api_save_order() -> Response:
    """Save order-builder steps while preserving the block's metadata."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        target_block_id = str(post_data.get("order_block_id") or "").strip()
        steps = post_data.get("steps")
        if not isinstance(steps, list):
            raise ValueError("steps must be a list of order step objects")

        code_body = serialize_order_steps(steps)

        # Load the current file, find the order block, and replace it
        current_content = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(current_content)

        target_block: Optional[Dict[str, Any]] = None
        if target_block_id:
            for block in model["blocks"]:
                if block.get("id") == target_block_id:
                    target_block = block
                    break
        elif model["order_blocks"]:
            target_block = model["blocks"][model["order_blocks"][0]]

        if target_block:
            block_data = deepcopy(target_block.get("data") or {})
            if not isinstance(block_data, dict):
                block_data = {}
            block_data["id"] = str(
                block_data.get("id") or target_block.get("id") or "interview_order"
            )
            # Existing order blocks are not necessarily mandatory.  In many
            # AssemblyLine interviews the standalone/main block is mandatory
            # and invokes the order block; forcing this block to mandatory
            # creates duplicate mandatory code blocks and invalidates YAML.
            block_data["code"] = code_body
            order_yaml = canonical_block_yaml(block_data)
            updated = update_block_in_yaml(
                current_content, target_block["id"], order_yaml
            )
        else:
            # Append a new mandatory code block
            indented_body = "\n".join(f"  {line}" for line in code_body.splitlines())
            order_yaml = (
                f"id: interview_order\nmandatory: True\ncode: |\n{indented_body}\n"
            )
            updated = current_content.rstrip() + "\n---\n" + order_yaml + "\n"

        playground_write_yaml(uid, project, filename, updated)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "order_block_id": (
                        target_block.get("id") if target_block else "interview_order"
                    ),
                    "order_yaml": order_yaml,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: save order error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/ai/generate-screen", methods=["POST"])
def editor_api_ai_generate_screen() -> Response:
    """Generate a single question screen draft from interview + template context."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        llms = _load_llms_module()
        if llms is None:
            raise ValueError("docassemble.ALToolbox.llms is not available")

        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        block_id = str(post_data.get("block_id") or "").strip()
        user_instruction = str(post_data.get("instruction") or "").strip()
        field_types = _field_types_from_request(post_data)

        raw_yaml = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(raw_yaml)
        blocks = model.get("blocks") or []
        block = _question_block_by_id(blocks, block_id) if block_id else None
        current_block_data = deepcopy(block.get("data") or {}) if block else {}

        outline = _interview_outline_text(blocks)
        template_context = _project_template_context_text(uid, project)
        current_screen_payload = post_data.get("current_screen")

        system_message = textwrap.dedent("""
            You are drafting ONE docassemble question screen.
            Return ONLY JSON with keys:
              question: string
              subquestion: string
              continue_button_field: string
              fields: array of {label, field, datatype, choices?}

            Rules:
            - Usually draft 2-3 fields on a normal screen.
            - Never return more than 7 fields.
            - Choose datatypes from the provided allowed list.
            - Keep labels plain and user-friendly.
            - Keep variable names python-safe snake_case.
            """).strip()

        user_message = (
            f"Allowed datatypes: {json.dumps(field_types)}\n\n"
            f"Optional user instruction for this screen:\n{user_instruction or '[none]'}\n\n"
            f"Current screen snapshot:\n{json.dumps(current_screen_payload or current_block_data, ensure_ascii=False)}\n\n"
            f"Interview outline:\n{outline[:6000]}\n\n"
            f"Template context (source document excerpts):\n{template_context[:7000] or '[none]'}\n\n"
            f"Current raw interview YAML:\n{raw_yaml[:12000]}"
        )

        model_name = pick_small_model_name(llms)
        drafted = llms.chat_completion(
            system_message=system_message,
            user_message=user_message,
            json_mode=True,
            model=model_name,
        )
        if not isinstance(drafted, dict):
            raise ValueError("AI did not return a JSON object")

        screen = normalize_generated_screen(drafted, allowed_datatypes=field_types)

        candidate_block = deepcopy(
            current_block_data if isinstance(current_block_data, dict) else {}
        )
        candidate_block["id"] = str(
            candidate_block.get("id") or block_id or "ai_generated_screen"
        )
        candidate_block["question"] = screen.get("question")
        if screen.get("subquestion"):
            candidate_block["subquestion"] = screen.get("subquestion")
        candidate_block["fields"] = screen.get("fields") or []
        if screen.get("continue_button_field"):
            candidate_block["continue button field"] = screen.get(
                "continue_button_field"
            )

        candidate_yaml = canonical_block_yaml(candidate_block)
        _ensure_dayamlchecker_valid(candidate_yaml)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "screen": screen,
                    "model": model_name,
                    "validated_yaml": candidate_yaml,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: ai generate-screen error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/ai/generate-fields", methods=["POST"])
def editor_api_ai_generate_fields() -> Response:
    """Generate fields for one existing question block using full interview context."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        llms = _load_llms_module()
        if llms is None:
            raise ValueError("docassemble.ALToolbox.llms is not available")

        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        block_id = str(post_data.get("block_id") or "").strip()
        if not block_id:
            raise ValueError("block_id is required")
        field_types = _field_types_from_request(post_data)

        raw_yaml = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(raw_yaml)
        blocks = model.get("blocks") or []
        block = _question_block_by_id(blocks, block_id)
        if not block:
            raise ValueError("block_id must refer to a question block")

        outline = _interview_outline_text(blocks)
        template_context = _project_template_context_text(uid, project)
        current_screen_payload = post_data.get("current_screen")
        if not isinstance(current_screen_payload, dict):
            current_screen_payload = deepcopy(block.get("data") or {})

        system_message = textwrap.dedent("""
            You are generating fields for ONE docassemble question screen.
            Return ONLY JSON with key:
              fields: array of {label, field, datatype, choices?}

            Rules:
            - Usually return 2-3 fields for a normal screen.
            - Never return more than 7 fields.
            - Choose datatypes from the provided allowed list.
            - Keep labels plain and user-friendly.
            - Keep variable names python-safe snake_case.
            """).strip()

        user_message = (
            f"Allowed datatypes: {json.dumps(field_types)}\n\n"
            f"Current question screen data:\n{json.dumps(current_screen_payload, ensure_ascii=False)}\n\n"
            f"Interview outline:\n{outline[:6000]}\n\n"
            f"Template context (source document excerpts):\n{template_context[:7000] or '[none]'}\n\n"
            f"Current raw interview YAML:\n{raw_yaml[:12000]}"
        )

        model_name = pick_small_model_name(llms)
        drafted = llms.chat_completion(
            system_message=system_message,
            user_message=user_message,
            json_mode=True,
            model=model_name,
        )
        if not isinstance(drafted, dict):
            raise ValueError("AI did not return a JSON object")

        generated_fields = normalize_generated_fields(
            drafted.get("fields", []),
            allowed_datatypes=field_types,
        )
        if not generated_fields:
            raise ValueError("AI did not return any usable fields")

        candidate_block = deepcopy(block.get("data") or {})
        candidate_block["id"] = str(candidate_block.get("id") or block_id)
        candidate_block["fields"] = generated_fields
        candidate_yaml = canonical_block_yaml(candidate_block)
        _ensure_dayamlchecker_valid(candidate_yaml)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "fields": generated_fields,
                    "model": model_name,
                    "validated_yaml": candidate_yaml,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: ai generate-fields error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/parse-order", methods=["GET"])
def editor_api_parse_order() -> Response:
    """Parse order code text into structured steps (no file required)."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        code = request.args.get("code", "")
        steps = parse_order_code(code)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"steps": steps},
            }
        )
    except Exception as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/draft-order", methods=["POST"])
def editor_api_draft_order() -> Response:
    """Generate a draft order from the current file's blocks."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))

        raw_yaml = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(raw_yaml)
        steps = generate_draft_order(model["blocks"])

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"steps": steps},
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: draft-order error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/draft-review-screen", methods=["POST"])
def editor_api_draft_review_screen() -> Response:
    """Generate draft review-screen YAML using ALDashboard when available."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))

        raw_yaml = playground_read_yaml(uid, project, filename)
        from docassemble.ALDashboard.review_screen_generator import (
            generate_review_screen_yaml,
        )

        review_yaml = generate_review_screen_yaml([raw_yaml])
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"review_yaml": review_yaml},
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: draft-review-screen error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/preview-url", methods=["GET"])
def editor_api_preview_url() -> Response:
    """Get the docassemble interview preview URL for a playground file."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        url = playground_interview_url(uid, project, filename)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"url": url},
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: preview-url error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


NEW_PROJECT_JOB_KEY_PREFIX = "da:alweaver:editor:new-project:"
NEW_PROJECT_JOB_EXPIRE_SECONDS = 24 * 60 * 60
NEW_PROJECT_CELERY_MODULE = CELERY_MODULE
AGENT_TURN_CELERY_TASK = (
    "docassemble.ALWeaver.api_weaver_worker.weaver_editor_agent_turn_task"
)
NEW_PROJECT_CELERY_TASK = (
    "docassemble.ALWeaver.api_weaver_worker.weaver_editor_new_project_task"
)
NEW_PROJECT_TERMINAL_STATES = {
    "succeeded",
    "failed",
    "cancelled",
    "expired",
}


def _editor_async_is_configured() -> bool:
    return worker_configuration_is_ready()


def _log_editor_worker_preflight() -> None:
    status = get_worker_configuration_status()
    if status["configured"]:
        return
    log(
        "ALWeaver editor Celery preflight: "
        f"{status['message']} Configuration instructions: "
        f"{CELERY_CONFIGURATION_DOCS_URL}",
        "warning",
    )


_log_editor_worker_preflight()


def _new_project_job_key(job_id: str) -> str:
    return NEW_PROJECT_JOB_KEY_PREFIX + job_id


def _load_new_project_job_state(job_id: str) -> Optional[Dict[str, Any]]:
    raw = r.get(_new_project_job_key(job_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _store_new_project_job_state(job_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(state)
    payload["job_id"] = job_id
    payload.setdefault("created_at", payload.get("updated_at", time.time()))
    payload["updated_at"] = time.time()
    pipe = r.pipeline()
    pipe.set(_new_project_job_key(job_id), json.dumps(payload))
    pipe.expire(_new_project_job_key(job_id), NEW_PROJECT_JOB_EXPIRE_SECONDS)
    pipe.execute()
    return payload


def _update_new_project_job_state(job_id: str, **updates: Any) -> Dict[str, Any]:
    state = _load_new_project_job_state(job_id) or {}
    state.update(updates)
    return _store_new_project_job_state(job_id, state)


def _complete_new_project_upload_job(
    *,
    job_id: str,
    uid: int,
    project_name: str,
    request_id: str,
    uploaded_files: List[Dict[str, Any]],
    generation_options: Dict[str, Any],
    debug_requested: bool,
) -> Dict[str, Any]:
    stage = "start"
    temp_dir = tempfile.mkdtemp(prefix="editor-upload-")
    try:
        _update_new_project_job_state(
            job_id,
            status="running",
            stage=stage,
            message="Starting background Weaver generation.",
            project=project_name,
            request_id=request_id,
            started_at=time.time(),
            progress=5,
        )
        temp_paths: List[str] = []
        first_result: Optional[Dict[str, Any]] = None

        for payload in uploaded_files:
            filename = str(payload.get("filename") or "").strip()
            content_bytes = payload.get("content_bytes") or b""
            mimetype = payload.get("mimetype")
            if not filename:
                raise ValueError("Uploaded file is missing a filename.")
            if not isinstance(content_bytes, (bytes, bytearray)):
                raise ValueError("Uploaded file bytes are invalid.")

            dest = os.path.join(temp_dir, filename)
            with open(dest, "wb") as fh:
                fh.write(bytes(content_bytes))
            temp_paths.append(dest)

            if first_result is None:
                stage = "generate_interview"
                _update_new_project_job_state(
                    job_id,
                    status="running",
                    stage=stage,
                    message="Generating interview from the uploaded document.",
                    progress=20,
                )
                first_result = generate_interview_from_bytes(
                    filename=filename,
                    content_bytes=bytes(content_bytes),
                    mimetype=str(mimetype) if mimetype else None,
                    generation_options=generation_options,
                    include_yaml_text=True,
                )

        if first_result is None:
            raise ValueError("No valid files were uploaded.")

        yaml_text = str(first_result.get("yaml_text", "") or "")
        if not yaml_text:
            raise ValueError(
                "Weaver did not produce any YAML output for the uploaded file."
            )

        stage = "write_yaml"
        _update_new_project_job_state(
            job_id,
            status="running",
            stage=stage,
            message="Writing generated interview YAML.",
            progress=70,
        )
        playground_write_yaml(uid, project_name, "interview.yml", yaml_text)

        stage = "copy_templates"
        _update_new_project_job_state(
            job_id,
            status="running",
            stage=stage,
            message="Copying uploaded files into the project.",
            progress=85,
        )
        _copy_files_to_section(
            user_id=uid,
            project_name=project_name,
            storage_section=SECTION_TO_STORAGE["templates"],
            files=temp_paths,
        )

        result = {
            "project": project_name,
            "filename": "interview.yml",
            "generated_from": first_result.get("input_filename"),
            "uploaded_count": len(temp_paths),
        }
        _update_new_project_job_state(
            job_id,
            status="succeeded",
            stage="done",
            message="Project created successfully.",
            project=result["project"],
            filename=result["filename"],
            generated_from=result["generated_from"],
            uploaded_count=result["uploaded_count"],
            result=result,
            progress=100,
            finished_at=time.time(),
        )
        return result
    except Exception as exc:
        tb = traceback.format_exc()
        error_payload: Dict[str, Any] = {
            "type": "server_error",
            "message": "ALWeaver generation failed.",
        }
        if debug_requested:
            error_payload["stage"] = stage
            error_payload["traceback"] = tb
        _update_new_project_job_state(
            job_id,
            status="failed",
            stage=stage,
            message=error_payload["message"],
            error=error_payload,
            finished_at=time.time(),
        )
        log(
            "ALWeaver editor: background new-project upload failed "
            f"job_id={job_id} project={project_name} stage={stage}: {exc!r}\n{tb}",
            "error",
        )
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _start_new_project_upload_job(
    *,
    uid: int,
    request_id: str,
    project_name: str,
    uploaded_files: List[Dict[str, Any]],
    generation_options: Dict[str, Any],
    debug_requested: bool,
) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    queued_at = time.time()
    initial_state: Dict[str, Any] = {
        "status": "queued",
        "stage": "queued",
        "message": "Queued for background Weaver generation.",
        "owner_user_id": uid,
        "operation_type": "new_project_upload",
        "input_revision": None,
        "project": project_name,
        "request_id": request_id,
        "generated_from": uploaded_files[0].get("filename") if uploaded_files else None,
        "uploaded_count": len(uploaded_files),
        "queued_at": queued_at,
        "started_at": None,
        "finished_at": None,
        "progress": 0,
        "result": None,
        "error": None,
    }
    _store_new_project_job_state(job_id, initial_state)
    try:
        task = workerapp.send_task(
            NEW_PROJECT_CELERY_TASK,
            kwargs={
                "job_id": job_id,
                "uid": uid,
                "project_name": project_name,
                "request_id": request_id,
                "uploaded_files": uploaded_files,
                "generation_options": generation_options,
                "debug_requested": debug_requested,
            },
        )
    except Exception as exc:
        _update_new_project_job_state(
            job_id,
            status="failed",
            stage="enqueue",
            message="Unable to queue background Weaver generation.",
            finished_at=time.time(),
            error={
                "type": "queue_error",
                "message": str(exc) or "Unable to queue Celery task.",
            },
        )
        raise
    _update_new_project_job_state(job_id, celery_task_id=task.id)
    return {
        "job_id": job_id,
        "job_url": f"{EDITOR_BASE_PATH}/api/new-project/jobs/{job_id}",
        "state": initial_state,
    }


def _reconcile_new_project_job_state(
    job_id: str, state: Dict[str, Any]
) -> Dict[str, Any]:
    status = str(state.get("status") or "queued")
    if status in NEW_PROJECT_TERMINAL_STATES:
        return state
    celery_task_id = state.get("celery_task_id")
    if not celery_task_id:
        return _update_new_project_job_state(
            job_id,
            status="expired",
            stage="expired",
            message="The job has no associated Celery task.",
            finished_at=time.time(),
            error={
                "type": "job_expired",
                "message": "The queued task record is unavailable.",
            },
        )

    task_result = workerapp.AsyncResult(id=celery_task_id)
    celery_state = str(getattr(task_result, "state", "") or "").upper()
    if celery_state == "SUCCESS":
        task_value = getattr(task_result, "result", None)
        return _update_new_project_job_state(
            job_id,
            status="succeeded",
            stage="done",
            message="Project created successfully.",
            progress=100,
            finished_at=time.time(),
            result=task_value if isinstance(task_value, dict) else state.get("result"),
        )
    if celery_state == "FAILURE":
        task_error = getattr(task_result, "result", None)
        return _update_new_project_job_state(
            job_id,
            status="failed",
            stage=state.get("stage") or "failed",
            message="ALWeaver generation failed.",
            finished_at=time.time(),
            error={
                "type": "celery_failure",
                "message": str(task_error or "Task failed"),
            },
        )
    if celery_state == "REVOKED":
        return _update_new_project_job_state(
            job_id,
            status="cancelled",
            stage="cancelled",
            message="The job was cancelled.",
            finished_at=time.time(),
        )
    if celery_state in {"STARTED", "RETRY"}:
        updates: Dict[str, Any] = {"status": "running"}
        if not state.get("started_at"):
            updates["started_at"] = time.time()
        return _update_new_project_job_state(job_id, **updates)
    if celery_state in {"PENDING", "RECEIVED"}:
        return _update_new_project_job_state(job_id, status="queued")
    return _update_new_project_job_state(
        job_id,
        status="expired",
        stage="expired",
        message="The Celery task state is no longer available.",
        finished_at=time.time(),
        error={"type": "job_expired", "message": f"Unknown task state: {celery_state}"},
    )


@app.route(f"{EDITOR_BASE_PATH}/api/new-project", methods=["POST"])
def editor_api_new_project() -> Response:
    """Create a new playground project, optionally seeded with a template.

    Accepts two content-types:
    1. application/json — template-based creation (existing behaviour)
    2. multipart/form-data — "I'm feeling lucky" mode: upload one or more
       PDF/DOCX files and let Weaver generate a scaffolded draft.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()

        uploaded_files = request.files.getlist("files")
        if uploaded_files and uploaded_files[0].filename:
            return _new_project_from_uploads(uid, request_id, uploaded_files)

        return _new_project_from_template(uid, request_id)
    except (ValueError, FileNotFoundError) as exc:
        status = 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        log(f"ALWeaver editor: new-project error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


def _new_project_from_template(uid: int, request_id: str) -> Response:
    """Create a project from a bundled template or a minimal starter."""
    post_data = request.get_json(silent=True) or {}
    raw_name = post_data.get("project_name", "NewProject")
    template_id = post_data.get("template_id")

    base_name = normalize_project_name(raw_name)
    existing = get_list_of_projects(uid)
    project_name = next_available_project_name(base_name, [*existing, "default"])
    create_project(uid, project_name)

    # If a template is specified, load its content and write it
    starter_yaml = ""
    if template_id:
        template_file = f"interview_templates/{template_id}.yml"
        try:
            ref = (
                importlib.resources.files("docassemble.ALWeaver")
                / "data"
                / "sources"
                / template_file
            )
            with importlib.resources.as_file(ref) as p:
                if p.exists():
                    starter_yaml = p.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, OSError):
            starter_yaml = ""

    if not starter_yaml:
        # Create a minimal starter interview
        starter_yaml = (
            "metadata:\n"
            f"  title: {project_name}\n"
            "---\n"
            "id: intro_screen\n"
            "mandatory: True\n"
            "question: Welcome\n"
            "subquestion: |\n"
            "  This interview was created with the Docassemble editor.\n"
            "continue button field: intro_screen\n"
        )

    # Write starter YAML
    playground_write_yaml(uid, project_name, "interview.yml", starter_yaml)

    return jsonify(
        {
            "success": True,
            "request_id": request_id,
            "data": {
                "project": project_name,
                "filename": "interview.yml",
                "template_id": template_id,
            },
        }
    )


def _new_project_from_uploads(
    uid: int, request_id: str, uploaded_files: list
) -> Response:
    """'I'm feeling lucky' mode — generate a scaffolded interview from uploads.

    Accepts one or more PDF/DOCX files. Runs ``generate_interview_from_bytes``
    on the first file to produce a draft YAML, writes it to a new playground
    project, and copies all uploaded originals into the templates section.
    """
    if not _editor_async_is_configured():
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "async_not_configured",
                    "code": "editor_async_not_configured",
                    "message": (
                        "Background project generation is not configured. Add "
                        f"{NEW_PROJECT_CELERY_MODULE!r} to the Docassemble "
                        "'celery modules' configuration list, then restart the "
                        "Docassemble web and Celery services."
                    ),
                    "details": get_worker_configuration_status(),
                },
            },
            503,
        )
    raw_name = request.form.get("project_name", "NewProject")
    generation_notes = request.form.get("generation_notes", "").strip()
    help_page_url = request.form.get("help_page_url", "").strip()
    help_page_title = request.form.get("help_page_title", "").strip()
    help_source_text = request.form.get("help_source_text", "").strip()
    if not help_source_text:
        help_source_text = generation_notes
    use_llm_assist = parse_bool(request.form.get("use_llm_assist"), default=False)

    base_name = normalize_project_name(raw_name)
    existing = get_list_of_projects(uid)
    project_name = next_available_project_name(base_name, [*existing, "default"])
    create_project(uid, project_name)

    debug_requested = str(request.args.get("debug", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    try:
        uploaded_payloads: List[Dict[str, Any]] = []
        log(
            "ALWeaver editor: new-project upload start "
            f"request_id={request_id} user_id={uid} project={project_name} "
            f"files={len(uploaded_files)} notes_provided={bool(generation_notes)} "
            f"help_page_url={help_page_url!r} help_source_chars={len(help_source_text or '')} "
            f"use_llm_assist={use_llm_assist}",
            "info",
        )
        for file_storage in uploaded_files:
            filename = file_storage.filename or ""
            content_bytes = file_storage.read()
            mimetype = file_storage.mimetype

            # validate_upload_metadata raises on bad files
            safe_name, _ext = validate_upload_metadata(
                filename=filename,
                content_bytes=content_bytes,
                mimetype=mimetype,
            )
            uploaded_payloads.append(
                {
                    "filename": safe_name,
                    "content_bytes": content_bytes,
                    "mimetype": mimetype,
                }
            )

        if not uploaded_payloads:
            raise ValueError("No valid files were uploaded.")

        generation_options: Dict[str, Any] = {
            "create_package_zip": False,
            "include_next_steps": False,
            "exact_name": uploaded_payloads[0]["filename"],
            "use_llm_assist": use_llm_assist,
        }
        if help_page_url:
            generation_options["help_page_url"] = help_page_url
        if help_page_title:
            generation_options["help_page_title"] = help_page_title
        if help_source_text:
            generation_options["help_source_text"] = help_source_text
        log(
            "ALWeaver editor: queueing background project generation "
            f"request_id={request_id} project={project_name} "
            f"generation_options={sorted(generation_options.keys())} "
            f"exact_name={uploaded_payloads[0]['filename']!r}",
            "info",
        )
        job_info = _start_new_project_upload_job(
            uid=uid,
            request_id=request_id,
            project_name=project_name,
            uploaded_files=uploaded_payloads,
            generation_options=generation_options,
            debug_requested=debug_requested,
        )

        return jsonify_with_status(
            {
                "success": True,
                "request_id": request_id,
                "status": "queued",
                "job_id": job_info["job_id"],
                "job_url": job_info["job_url"],
                "data": job_info["state"],
            },
            202,
        )
    except (ValueError, FileNotFoundError) as exc:
        log(
            "ALWeaver editor: new-project from upload validation error "
            f"request_id={request_id} project={project_name}: {exc!r}",
            "warning",
        )
        status = 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )
    except Exception as exc:
        tb = traceback.format_exc()
        log(
            "ALWeaver editor: new-project from upload error "
            f"request_id={request_id} project={project_name}: {exc!r}\n"
            f"{tb}",
            "error",
        )
        status = 500
        error_payload: Dict[str, Any] = {
            "type": "server_error",
            "message": "ALWeaver generation failed.",
        }
        if debug_requested:
            error_payload["traceback"] = tb
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": error_payload,
            },
            status,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/new-project/jobs/<job_id>", methods=["GET"])
def editor_api_new_project_job(job_id: str) -> Response:
    """Get the status of a queued upload-based project creation job."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        state = _load_new_project_job_state(job_id)
        if not state or state.get("owner_user_id") not in {None, uid}:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {"type": "not_found", "message": "Job not found."},
                },
                404,
            )
        state = _reconcile_new_project_job_state(job_id, state)
        status = str(state.get("status") or "queued")
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "job_id": job_id,
                "status": status,
                "data": state,
            }
        )
    except Exception as exc:
        log(f"ALWeaver editor: new-project job status error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )

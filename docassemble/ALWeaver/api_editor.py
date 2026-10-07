# pre-load

"""Flask endpoints for the WYSIWYM interview editor.

Provides:
    GET  /al/editor              — serve the editor single-page application
    GET  /al/editor/api/projects — list playground projects
    GET  /al/editor/api/github/status — inspect native GitHub integration
    POST /al/editor/api/github/publish — queue a package commit to GitHub
    GET  /al/editor/api/github/publish/jobs/<id> — poll a queued publish
    GET  /al/editor/api/files    — list YAML files in a project
    POST /al/editor/api/file/new — create a new YAML interview file
    GET  /al/editor/api/file     — read & parse a YAML file
    POST /al/editor/api/file     — save full YAML back to a file
    POST /al/editor/api/file/metadata — update metadata-related documents only
    POST /al/editor/api/block    — update a single block in-place
    POST /al/editor/api/insert-block — insert a new block at a target position
    GET  /al/editor/api/question-library — AssemblyLine questions for this file's objects
    POST /al/editor/api/question-library/insert — copy chosen library questions in
    POST /al/editor/api/question-library/object — declare a new list of people
    GET  /al/editor/api/package-file — parse a YAML file from an installed package
    GET  /al/editor/api/variables — extract variable names from a file
    POST /al/editor/api/order    — save order-builder steps as code
    POST /al/editor/api/ai/generate-screen — draft one question screen with AI
    POST /al/editor/api/ai/generate-fields — draft fields for a question with AI
    POST /al/editor/api/new-project — create a project (optionally via Weaver)
    POST /al/editor/api/template/import — read a template already in a project
    POST /al/editor/api/template/revise — replace a template after revision confirmation
    GET  /al/editor/api/template/import/jobs/<id> — poll a template import
    POST /al/editor/api/template/apply — add the accepted parts of one to the YAML
    GET  /al/editor/api/template/variable-report/suggestion — its title and filename
    POST /al/editor/api/template/variable-report — draft a DOCX template from the questions
    GET  /al/editor/api/documents — the documents an interview assembles
    POST /al/editor/api/documents — reorder documents or change what enables them
    GET  /al/editor/api/parse-order — parse order code into structured steps
    POST /al/editor/api/draft-order — generate a draft order from blocks
    POST /al/editor/api/draft-review-screen — draft or re-sync the review screen
    GET  /al/editor/api/preview-url — get the interview preview URL
    GET  /al/editor/api/list-topics — LIST taxonomy codes for the topic picker
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
    GET  /al/editor/api/server/restart-state — pending module changes, if any
    POST /al/editor/api/server/restart — restart Docassemble so modules load
    GET  /al/editor/api/server/restart-status — poll a restart in progress
"""

from __future__ import annotations

import ast
import base64
import difflib
import importlib
import importlib.metadata
import importlib.resources
import hashlib
import hmac
import json
import keyword
import mimetypes
import os
import re
import shutil
import sys
import traceback
import textwrap
import tempfile
import time
import uuid
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from html import escape
from urllib.parse import quote
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
)

import yaml
from flask import Response, current_app, jsonify, redirect, request, url_for
from flask_wtf.csrf import generate_csrf
from flask_login import current_user

from docassemble.base.util import log

from .analysis_cache import Dependencies, FileResultCache

try:
    from docassemble.base.functions import package_question_filename
    from docassemble.base.error import DAInvalidFilename
except Exception:  # pragma: no cover - depends on the server's Docassemble
    package_question_filename = None  # type: ignore[assignment]

    class DAInvalidFilename(Exception):  # type: ignore[no-redef]
        pass


from .docassemble_compat import (
    default_github_owner,
    get_default_github_owner,
    bump_interview_source_index,
    create_target_session,
    create_saved_file,
    full_package_directory,
    reset_process_is_running,
    restart_docassemble,
    server_start_time,
    GithubCredentialError,
    get_target_question,
    get_target_variables,
    go_back_target_session,
    get_csrf,
    get_flask_app,
    get_github_publish_owners,
    get_github_branch_head,
    get_github_merge_base,
    get_github_repository_branches,
    get_github_workflow_access,
    get_github_repository_snapshot,
    is_github_package_path,
    build_github_package_snapshot,
    github_package_snapshot_revision,
    github_authorization_url,
    normalize_github_repository_url,
    get_native_github_integration,
    get_redis_client,
    get_worker_app,
    json_response as jsonify_with_status,
    ensure_github_repository,
    publish_github_package,
    run_target_action_raw,
    set_target_variables,
)
from .document_bundles import (
    interview_documents,
    remove_document,
    set_bundle_elements,
    set_enabled_expression,
    template_status,
)
from .worker_config import (
    CELERY_CONFIGURATION_DOCS_URL,
    CELERY_MODULE,
    add_celery_module_to_config_yaml,
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
    validate_document_content,
    validate_upload_metadata,
)
from .editor_modules import (
    MODULE_FILENAME_PATTERN,
    RESTART_DISRUPTION_SECONDS,
    ModuleSyntaxError,
    check_module_syntax,
    clear_modules_dirty,
    mark_modules_dirty,
    module_package_directory,
    normalize_restart_policy,
    publish_module_source,
    read_modules_dirty,
    restart_status_key,
    unpublish_module,
    validate_module_filename,
)
from .project_filenames import safe_project_filename, unique_project_filenames
from .assemblyline_settings import read_settings, update_settings
from .question_library import (
    attribute_references,
    library_catalog,
    PERSON_CLASSES,
    PERSON_LIST_CLASSES,
)
from .generator_constants import generator_constants

try:
    from .editor_utils import (
        BLOCK_TYPE_OBJECTS,
        canonical_block_yaml,
        canonicalize_block_yaml,
        comment_out_block_in_yaml,
        delete_block_from_yaml,
        delete_saved_file,
        generate_draft_order,
        add_object_declaration,
        insert_block_in_yaml,
        inserted_block_id_by_position,
        is_comment_only_yaml,
        parse_interview_yaml,
        _safe_load_interview_document,
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
        validate_order_steps,
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

from .variable_report import (
    court_form_options,
    suggested_report_names,
    write_variable_report_docx,
)
from .review_screen_sync import (
    ALDashboardUnavailable,
    carry_over_unmatched_entries,
    collect_interview_yaml_texts,
    ensure_revisit_tables,
    generate_review_screen_yaml,
    inferred_objects_document,
    review_screen_identity,
    review_scope_warnings,
    sync_review_screen,
)
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
    diff_stats,
    load_agent_session,
    load_progress,
    progress_is_live,
    store_agent_session,
    store_progress,
    truncate_diff,
)
from .editor_agent_validation import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
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
    cleanup_due_runtime_sessions,
    cleanup_owned_runtime_sessions,
    close_runtime_session,
    create_runtime_record,
    get_live_runtime_record,
    playground_yaml_filename,
    refresh_runtime_progress,
    runtime_session_lock,
    schedule_runtime_cleanup,
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
    find_project_github_sync,
    github_project_name,
    import_github_snapshot,
    merge_github_snapshot,
    next_available_project_name,
    normalize_github_package_name,
    normalize_project_name,
    load_project_github_manifest,
    prepare_project_github_package,
    record_project_github_sync,
    rename_project,
)
from .github_repository import (
    PYPROJECT_PATH,
    adopt_repository_snapshot,
    repository_config_view,
    repository_dependency_names,
    repository_publish_files,
    update_repository_config,
)
from .kiln_tests import (
    MANAGED_IT_RUNS_FILENAME,
    create_kiln_feature,
    create_kiln_feature_from_json,
    default_feature_filename,
    kiln_feature_checks_accessibility,
    sync_kiln_feature,
)

__all__: list = []

EDITOR_BASE_PATH = "/al/editor"
MAX_TEMPLATE_REPLACEMENT_BYTES = 50 * 1024 * 1024

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


class ProjectReplacementWriteError(RuntimeError):
    """A replacement batch failed, with verified rollback/recovery information."""

    def __init__(self, restored: List[Dict[str, str]], recovery: List[Dict[str, str]]):
        self.restored = restored
        self.recovery = recovery
        super().__init__(
            "Replacement failed. Some files could not be restored; use the recovery content and inspect the listed files."
            if recovery
            else "Replacement failed. All attempted files were restored to their original content."
        )


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


def _editor_admin_check() -> bool:
    """Return True only for an authenticated Docassemble administrator."""
    try:
        has_role = getattr(current_user, "has_role", None)
        return bool(
            current_user.is_authenticated and callable(has_role) and has_role("admin")
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


def _normalize_git_branch(raw: Optional[str]) -> str:
    """Validate a Git ref name without narrowing Docassemble's slash support."""
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Branch name is required")
    if len(value) > 255:
        raise ValueError("Branch name is too long")
    invalid = (
        value == "@"
        or value.startswith(("/", "."))
        or value.endswith(("/", "."))
        or ".." in value
        or "@{" in value
        or "//" in value
        or any(character.isspace() or ord(character) < 32 for character in value)
        or any(character in "~^:?*[\\" for character in value)
        or any(
            part.startswith(".") or part.endswith(".lock") for part in value.split("/")
        )
    )
    if invalid:
        raise ValueError("Branch name is not a valid Git branch name")
    return value


def _normalize_commit_message(raw: Optional[str]) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Commit message is required")
    if len(value) > 500:
        raise ValueError("Commit message must be 500 characters or fewer")
    return value


def _plain_filename(raw: Optional[str], required_message: str) -> str:
    value = str(raw or "").strip()
    if not value or value in {".", ".."}:
        raise ValueError(required_message)
    if "/" in value or "\\" in value:
        raise ValueError("Filename must not contain a path separator")
    return value


def _normalize_filename(raw: Optional[str]) -> str:
    value = _plain_filename(raw, "YAML filename is required")
    if not value.lower().endswith((".yml", ".yaml")):
        raise ValueError("File must be a YAML interview")
    return value


def _normalize_new_filename(raw: Optional[str]) -> str:
    value = _plain_filename(raw, "YAML filename is required")
    if "." not in value:
        value = f"{value}.yml"
    if not value.lower().endswith((".yml", ".yaml")):
        raise ValueError("File must be a YAML interview")
    return value


# AssemblyLine's YAML coding style: a runnable file is `main.yml`, and a package
# with a single interview may instead carry a descriptive name derived from the
# document (`eviction.yml`).  https://assemblyline.suffolklitlab.org/docs/coding_style/yaml
DEFAULT_NEW_INTERVIEW_FILENAME = "main.yml"


def _normalize_new_interview_filename(raw: Optional[str]) -> Optional[str]:
    """An author-supplied interview filename, or None to use the derived name."""
    value = str(raw or "").strip()
    if not value:
        return None
    return _normalize_new_filename(value)


def _normalize_generated_filename(raw: Optional[str]) -> str:
    """The filename Weaver derived for a generated interview, or the AL default."""
    try:
        return _normalize_new_filename(raw)
    except ValueError:
        return DEFAULT_NEW_INTERVIEW_FILENAME


def _normalize_renamed_storage_filename(
    raw: Optional[str], existing_filename: str
) -> str:
    value = _plain_filename(raw, "YAML filename is required")
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
        'question: ""\n'
    )


def _normalize_section(raw: Optional[str]) -> str:
    value = str(raw or "").strip().lower()
    if value not in EDITOR_SECTION_ALIASES:
        raise ValueError("Invalid section")
    return EDITOR_SECTION_ALIASES[value]


def _normalize_storage_filename(raw: Optional[str]) -> str:
    return _plain_filename(raw, "filename is required")


def _renamed_file_message(requested: str, stored: str, reason: str) -> str:
    """Explain, to the author, why the file is not called what they called it.

    Args:
        requested (str): the name the file arrived with.
        stored (str): the name the project actually stores it under.
        reason (str): ``unsupported_characters`` or ``name_taken``.

    Returns:
        str: a sentence naming both names and the rule behind the change.
    """
    if reason == "name_taken":
        return (
            f"{requested} was saved as {stored}, because this project already "
            "has a file with that name."
        )
    return (
        f"{requested} was saved as {stored}. The Playground can only find a "
        "file whose name is made of letters, digits, dots, hyphens and "
        "underscores, so anything else in the name is replaced. Refer to it "
        f"as {stored} in your interview."
    )


def _optional_flag(raw: Any) -> Optional[bool]:
    """A yes/no that is allowed to be neither, for a setting with a default.

    A checkbox cannot say "leave it to the profile", so the editor sends the
    key only when the author actually chose. An absent or empty value is that
    third state and stays ``None`` rather than collapsing to ``False``.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in _TRUTHY:
            return True
        if value in _FALSY:
            return False
        raise ValueError(f"Expected yes or no, not {raw!r}.")
    return bool(raw)


def _optional_list_columns(raw: Any) -> Optional[int]:
    """How many columns a list table may use, or ``None`` for the default."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, float) and not raw.is_integer():
        raise ValueError("Columns per list must be a whole number.")
    try:
        value = int(raw)
    except (TypeError, ValueError) as err:
        raise ValueError("Columns per list must be a whole number.") from err
    if value < 1 or value > 12:
        raise ValueError("Columns per list must be between 1 and 12.")
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
    order_step_map, order_steps = _order_steps_from_model(model)
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
        "revision": source_revision(updated_content),
        **({"inserted_block_id": inserted_block_id} if inserted_block_id else {}),
    }


def _check_expected_source_revision(
    post_data: Dict[str, Any], current_content: str, request_id: str
) -> Optional[Response]:
    """Reject stale writes when a client supplies the revision it edited.

    The revision remains optional for older integrations. The editor always
    supplies it for source mutations, which prevents two open workspaces from
    silently overwriting one another.
    """
    expected_revision = post_data.get("expected_revision")
    if expected_revision is None:
        return None
    if not isinstance(expected_revision, str) or not expected_revision:
        raise ValueError("expected_revision must be a non-empty string")
    current_revision = source_revision(current_content)
    if expected_revision == current_revision:
        return None
    error: Dict[str, Any] = {
        "type": "revision_conflict",
        "code": "revision_conflict",
        "message": "The file changed since you opened it. Reload or resolve the conflict before saving.",
        "expected_revision": expected_revision,
        "current_revision": current_revision,
        "current_raw_yaml": current_content,
    }
    base_raw_yaml = post_data.get("base_raw_yaml")
    if isinstance(base_raw_yaml, str):
        error["base_raw_yaml"] = base_raw_yaml
    error["details"] = {
        key: value
        for key, value in error.items()
        if key not in {"type", "code", "message", "details"}
    }
    return jsonify_with_status(
        {"success": False, "request_id": request_id, "error": error}, 409
    )


class SourceWriteLockUnavailable(RuntimeError):
    """The shared source lock could not be acquired safely."""


@contextmanager
def _source_file_lock(
    user_id: int, project: str, filename: str, section: str = "interview"
) -> Iterator[None]:
    """Serialize project-file commits across Docassemble workers with Redis."""
    key_material = f"{user_id}\0{project}\0{section}\0{filename}".encode("utf-8")
    lock_key = "alweaver:editor:source:" + hashlib.sha256(key_material).hexdigest()
    lock_factory = getattr(r, "lock", None)
    if callable(lock_factory):
        try:
            lock = lock_factory(lock_key, timeout=60, blocking_timeout=30)
            acquired = lock.acquire(blocking=True, blocking_timeout=30)
        except Exception as exc:
            raise SourceWriteLockUnavailable(
                "The shared source lock service is unavailable."
            ) from exc
        if not acquired:
            raise SourceWriteLockUnavailable(
                "Timed out waiting for another source save to finish."
            )
        try:
            yield
        finally:
            try:
                lock.release()
            except Exception as exc:
                raise SourceWriteLockUnavailable(
                    "The shared source lock could not be released."
                ) from exc
        return

    raise SourceWriteLockUnavailable("The shared source lock service is unavailable.")


def _write_source_content(
    user_id: int,
    project: str,
    filename: str,
    updated_content: str,
    post_data: Dict[str, Any],
    request_id: str,
    *,
    parsed_model: Optional[Dict[str, Any]] = None,
) -> Optional[Response]:
    """Recheck the base revision and write under a per-file distributed lock."""
    try:
        with _source_file_lock(user_id, project, filename):
            current_content = playground_read_yaml(user_id, project, filename)
            conflict = _check_expected_source_revision(
                post_data, current_content, request_id
            )
            if conflict is not None:
                # A client may lose the response after this exact candidate
                # committed. Treat a byte-for-byte current source as an
                # idempotent success, while still rejecting every genuinely
                # stale candidate so another author's work is preserved.
                if current_content == updated_content:
                    return None
                return conflict
            # Keep compatibility with valid legacy questions that do not have
            # an explicit `id`. The checker reports these as errors, but the
            # editor has stable fallback block handles for them and must not
            # force an otherwise-valid source into draft mode.
            diagnostics = _validate_source_text(
                updated_content, filename, parsed_model=parsed_model
            )
            blocking_diagnostics = [
                item
                for item in diagnostics
                if _lint_level_from_severity(item.get("level") or item.get("severity"))
                == "error"
                and not (
                    item.get("source") == "dayamlchecker"
                    and str(item.get("message") or "").startswith(
                        "question block is missing an `id`:"
                    )
                )
                and not (
                    item.get("source") == "dayamlchecker"
                    and str(item.get("message") or "")
                    == "metadata block is missing common CourtFormsOnline publishing fields: can_I_use_this_form"
                )
            ]
            depth_limited = any(
                item.get("source") == "yaml-parser"
                and item.get("message")
                == "YAML nesting exceeds the supported validation depth."
                for item in blocking_diagnostics
            )
            if depth_limited:
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "validation_error",
                            "code": "yaml_nesting_too_deep",
                            "message": (
                                "This YAML is nested beyond the supported depth and "
                                "cannot be saved as an interview."
                            ),
                            "details": {
                                "diagnostics": diagnostics,
                                "blocking_count": len(blocking_diagnostics),
                                "summary": _lint_summary_for_findings(diagnostics),
                            },
                        },
                    },
                    422,
                )
            if blocking_diagnostics and post_data.get("save_as_draft") is not True:
                summary = _lint_summary_for_findings(diagnostics)
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "validation_error",
                            "code": "draft_confirmation_required",
                            "message": (
                                "This source has validation errors. Confirm saving it "
                                "as a draft to keep editing."
                            ),
                            "details": {
                                "diagnostics": diagnostics,
                                "blocking_count": len(blocking_diagnostics),
                                "summary": summary,
                            },
                        },
                    },
                    422,
                )
            playground_write_yaml(user_id, project, filename, updated_content)
    except SourceWriteLockUnavailable as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "source_lock_unavailable",
                    "code": "source_lock_unavailable",
                    "message": str(exc),
                },
            },
            503,
        )
    except FileNotFoundError:
        # A project directory that does not exist beneath the authenticated
        # user's Playground is indistinguishable from an object they do not
        # own.  Do not expose the server's storage path in the exception text.
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "not_found",
                    "code": "interview_file_not_found",
                    "message": "Interview file not found.",
                },
            },
            404,
        )
    return None


def _section_file_revision_conflict(
    post_data: Dict[str, Any], current_content: Union[str, bytes], request_id: str
) -> Optional[Response]:
    expected_revision = post_data.get("expected_revision")
    if expected_revision is None:
        return None
    if not isinstance(expected_revision, str) or not expected_revision:
        raise ValueError("expected_revision must be a non-empty string")
    if isinstance(current_content, bytes):
        # Binary template revisions are exposed as hashes of the exact file
        # bytes by the section-file listing endpoint. Keep mutation checks on
        # the same representation; decoding with replacement changes bytes.
        current_revision = hashlib.sha256(current_content).hexdigest()
        response_content = current_content.decode("utf-8", errors="replace")
    else:
        current_revision = source_revision(current_content)
        response_content = current_content
    if expected_revision == current_revision:
        return None
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "revision_conflict",
                "code": "revision_conflict",
                "message": (
                    "The file changed since you opened it. Reload or resolve "
                    "the conflict before saving."
                ),
                "expected_revision": expected_revision,
                "current_revision": current_revision,
                "current_content": response_content,
            },
        },
        409,
    )


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


def _interview_linter() -> Callable[..., Dict[str, Any]]:
    try:
        from docassemble.ALDashboard.interview_linter import (  # type: ignore
            lint_interview_content,
        )
    except Exception as exc:
        raise ALDashboardUnavailable(
            "Running style checks needs the ALDashboard package. Install "
            "docassemble.ALDashboard on this server and try again."
        ) from exc
    return lint_interview_content


def _run_interview_linter(raw_yaml: str, include_llm: bool = True) -> Dict[str, Any]:
    return _interview_linter()(raw_yaml, include_llm=include_llm)


def _demote_style_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cap style findings at ``warning``.

    The style checker is house style, not validity: it never runs inside
    `validate_candidate_source()` and it never stops a save. ALDashboard grades
    its own rules red/yellow/green, and red arrives here as `error` -- the same
    level a YAML file that will not load produces. An interview that runs fine
    but has a thin `metadata` block should not be reported the same way.
    """
    demoted: List[Dict[str, Any]] = []
    for finding in findings:
        item = dict(finding)
        if _lint_level_from_severity(item.get("level") or item.get("severity")) == (
            SEVERITY_ERROR
        ):
            item["level"] = SEVERITY_WARNING
            item["severity"] = SEVERITY_WARNING
            item["style_original_level"] = SEVERITY_ERROR
        demoted.append(item)
    return demoted


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
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        guessed_mimetype, _enc = mimetypes.guess_type(name)
        mimetype_value = guessed_mimetype or "application/octet-stream"
        editable = _is_text_editable(name, mimetype_value) and not _is_placeholder_file(
            name
        )
        item: Dict[str, Any] = {
            "filename": name,
            "size": os.path.getsize(path),
            "modified": int(os.path.getmtime(path)),
            "mimetype": mimetype_value,
            "editable": editable,
            "preview_kind": _preview_kind_for_file(name, editable),
        }
        if section == "templates" and not editable:
            try:
                digest = hashlib.sha256()
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        digest.update(chunk)
                item["revision"] = digest.hexdigest()
            except OSError:
                # A concurrent replacement can make this listing momentarily
                # stale. The explicit revision endpoint refuses writes without
                # a hash from the current file.
                pass
        if editable:
            try:
                with open(path, "rb") as fh:
                    item["revision"] = source_revision(
                        fh.read().decode("utf-8", errors="replace")
                    )
            except OSError:
                # The file may have changed during listing. Its later GET
                # supplies a revision before an edit can be saved.
                pass
        items.append(item)
    return items


def _order_steps_from_model(model: Dict[str, Any]) -> Tuple[Dict[str, Any], list]:
    """Parse every interview-order block a parsed file contains.

    ``order_blocks`` holds *document* indices, which are what ``block["index"]``
    records; they are not positions in ``blocks``, because empty documents never
    become blocks. Reading them as positions returns the wrong block in any file
    with a blank document, and raises IndexError when the order block is the
    last one -- which is every file that opens with `---` and ends with its
    mandatory code.
    """
    wanted = set(model.get("order_blocks") or [])
    order_step_map: Dict[str, Any] = {}
    order_steps: list = []
    for block in model.get("blocks", []):
        if block.get("index") not in wanted:
            continue
        code = (block.get("data") or {}).get("code", "")
        if not code:
            continue
        parsed_steps = parse_order_code(code)
        order_step_map[block["id"]] = parsed_steps
        if not order_steps:
            order_steps = parsed_steps
    return order_step_map, order_steps


def _named_order_steps_from_model(model: Dict[str, Any]) -> Dict[str, list]:
    """Order blocks triggered by a final ``some_var = True`` assignment.

    These can live in an included file without an ``id`` or ``mandatory`` key.
    Keep this separate from the order builder's editable block map.
    """
    named: Dict[str, list] = {}

    def asks_for_a_screen(steps: list) -> bool:
        return any(
            step.get("kind") in {"screen", "gather"}
            or asks_for_a_screen(step.get("children") or [])
            or asks_for_a_screen(step.get("else_children") or [])
            for step in steps
        )

    for block in model.get("blocks", []):
        if block.get("type") != "code":
            continue
        code = (block.get("data") or {}).get("code")
        if not isinstance(code, str):
            continue
        try:
            body = ast.parse(code).body
        except SyntaxError:
            continue
        if not body or not isinstance(body[-1], ast.Assign):
            continue
        assignment = body[-1]
        if not (
            len(assignment.targets) == 1
            and isinstance(assignment.targets[0], ast.Name)
            and isinstance(assignment.value, ast.Constant)
            and assignment.value.value is True
        ):
            continue
        steps = parse_order_code(code)
        if asks_for_a_screen(steps):
            named.setdefault(assignment.targets[0].id, steps)
    return named


def _project_yaml_filenames(user_id: int, project: str) -> List[str]:
    """Interview filenames in a project, for walking its include graph.

    A review screen usually sits in a file of its own that the interviews
    include, so working out what an interview is made of means looking at more
    than the file that is open.
    """
    try:
        return [
            _normalize_filename(item["filename"])
            for item in playground_list_yaml_files(user_id, project)
            if isinstance(item, dict) and item.get("filename")
        ]
    except Exception as exc:
        log(f"ALWeaver editor: could not list project YAML files: {exc!r}", "warning")
        return []


def _literal_file_dependencies(
    user_id: int, project: str, section: str, filename: str
) -> List[Dict[str, str]]:
    """Find project-local literal references that a rename/delete would break.

    This deliberately handles only references the editor can prove from source:
    local YAML includes, YAML ``modules`` declarations, Python imports of a
    project module, and literal template-file values. Computed Mako/Python
    references are not guessed at.
    """
    normalized_section = section
    target = os.path.basename(filename)
    target_stem = os.path.splitext(target)[0]
    dependencies: List[Dict[str, str]] = []

    def add(source_name: str, reference: str, kind: str) -> None:
        item = {
            "filename": source_name,
            "reference": reference,
            "kind": kind,
        }
        if item not in dependencies:
            dependencies.append(item)

    def scalar_values(value: Any, parent_key: str = "") -> Iterator[Tuple[str, str]]:
        if isinstance(value, dict):
            for key, child in value.items():
                yield from scalar_values(child, str(key))
        elif isinstance(value, list):
            for child in value:
                yield from scalar_values(child, parent_key)
        elif isinstance(value, str):
            yield parent_key, value

    for source_name in _project_yaml_filenames(user_id, project):
        if normalized_section == "interview" and source_name == filename:
            continue
        try:
            source = playground_read_yaml(user_id, project, source_name)
            documents = list(yaml.safe_load_all(source))
        except (OSError, ValueError, yaml.YAMLError):
            continue
        for document in documents:
            if not isinstance(document, dict):
                continue
            if normalized_section == "interview":
                include = document.get("include")
                include_items = [include] if isinstance(include, str) else include
                if isinstance(include_items, list):
                    for item in include_items:
                        literal = str(item or "").strip()
                        if (
                            literal == target
                            and ":" not in literal
                            and "/" not in literal
                            and "\\" not in literal
                        ):
                            add(source_name, literal, "include")
            elif normalized_section == "modules":
                modules = document.get("modules")
                module_items = [modules] if isinstance(modules, str) else modules
                if isinstance(module_items, list):
                    for item in module_items:
                        literal = str(item or "").strip()
                        if (
                            "${" not in literal
                            and "<%" not in literal
                            and literal.rsplit(".", 1)[-1] == target_stem
                        ):
                            add(source_name, literal, "module")
            elif normalized_section == "templates":
                for key, literal_value in scalar_values(document):
                    literal = literal_value.strip()
                    if (
                        "template" in key.lower()
                        and "${" not in literal
                        and "<%" not in literal
                        and os.path.basename(literal.replace("\\", "/")) == target
                    ):
                        add(source_name, literal, "template")

    if normalized_section == "modules":
        for item in _list_editor_section_files(user_id, project, "modules"):
            source_name = str(item.get("filename") or "")
            if (
                not source_name
                or source_name == filename
                or not source_name.lower().endswith(".py")
                or int(item.get("size") or 0) > EDITOR_SEARCH_MAX_FILE_BYTES
            ):
                continue
            try:
                source = _read_project_text_file(
                    user_id, project, "modules", source_name
                )
                tree = ast.parse(source)
            except (OSError, SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                imported: List[str] = []
                if isinstance(node, ast.Import):
                    imported = [alias.name.rsplit(".", 1)[-1] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module.rsplit(".", 1)[-1] if node.module else ""]
                    imported.extend(alias.name for alias in node.names)
                if target_stem in imported:
                    add(source_name, target_stem, "module import")

    return dependencies


def _file_dependency_conflict(
    user_id: int,
    project: str,
    section: str,
    filename: str,
    operation: str,
    request_id: str,
) -> Optional[Response]:
    dependencies = _literal_file_dependencies(user_id, project, section, filename)
    if not dependencies:
        return None
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {
                "type": "dependency_conflict",
                "code": "file_has_references",
                "message": (
                    f"Cannot {operation} {filename} while project files still "
                    "refer to it. Update those references first, then retry."
                ),
                "filename": filename,
                "dependencies": dependencies,
            },
        },
        409,
    )


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
    if normalized_section == "modules":
        _sync_module_after_write(user_id, project, normalized_filename, content)


def _normalize_kiln_test_filename(filename: Any) -> str:
    normalized = _normalize_storage_filename(filename)
    if not normalized.lower().endswith(".feature"):
        raise ValueError("An ALKiln test filename must end in .feature")
    return normalized


def _project_kiln_test_filenames(user_id: int, project: str) -> List[str]:
    return sorted(
        str(item["filename"])
        for item in _list_editor_section_files(user_id, project, "data")
        if str(item.get("filename") or "").lower().endswith(".feature")
    )


def _project_interview_yaml(
    user_id: int,
    project: str,
    filenames: Optional[List[str]] = None,
) -> str:
    """Combine the author-selected project YAML files for fixture analysis."""
    available = _project_yaml_filenames(user_id, project)
    if filenames is None:
        selected = available
    else:
        selected = []
        for filename in filenames:
            normalized = _normalize_filename(filename)
            if normalized not in available:
                raise ValueError(f"{normalized} is not a YAML file in this project")
            if normalized not in selected:
                selected.append(normalized)
    sources = [
        playground_read_yaml(user_id, project, filename) for filename in selected
    ]
    if not sources:
        raise ValueError("Select at least one interview YAML file to analyze")
    return "\n---\n".join(sources)


def _kiln_entrypoint_files(user_id: int, project: str, filename: str) -> List[str]:
    """Default test scope is the selected entrypoint's include closure."""
    filenames, _texts = collect_interview_yaml_texts(
        lambda name: playground_read_yaml(user_id, project, name), filename
    )
    # Destination detection must see the selected runnable interview last.
    return [name for name in filenames if name != filename] + [filename]


def _write_default_kiln_test(
    user_id: int,
    project: str,
    interview_filename: str,
    yaml_text: Optional[str] = None,
) -> Dict[str, Any]:
    generated = create_kiln_feature(
        (
            yaml_text
            if yaml_text is not None
            else _project_interview_yaml(
                user_id,
                project,
                _kiln_entrypoint_files(user_id, project, interview_filename),
            )
        ),
        interview_filename=interview_filename,
    )
    test_filename = default_feature_filename(interview_filename)
    _write_project_text_file(
        user_id,
        project,
        "data",
        test_filename,
        str(generated["feature_text"]),
    )
    return {"filename": test_filename, **generated}


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
                skipped.append(
                    {
                        "section": section,
                        "filename": filename,
                        "reason": "binary_or_unsupported",
                    }
                )
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


def _local_template_field_names(path: str) -> List[str]:
    """Read fields without constructing a DAStaticFile outside an interview."""
    if path.lower().endswith(".pdf"):
        from docassemble.base.pdftk import read_fields

        names = [str(field[0]) for field in (read_fields(path) or [])]
    else:
        from .interview_generator import docx_template_text, get_docx_variables

        names = [str(name) for name in get_docx_variables(docx_template_text(path))]
    return list(dict.fromkeys(names))


def _binary_template_rename_problems(
    user_id: int, project: str, old_name: str
) -> List[str]:
    """Refuse a YAML-only refactor that would strand references in a template."""
    problems = []
    for item in _list_editor_section_files(user_id, project, "templates"):
        filename = str(item.get("filename") or "")
        if not filename.lower().endswith((".docx", ".pdf")):
            continue
        try:
            if int(item.get("size") or 0) > EDITOR_SEARCH_MAX_FILE_BYTES:
                raise ValueError("template exceeds the inspection size limit")
            _, directory = _editor_storage_directory(
                user_id, project, EDITOR_SECTION_TO_STORAGE["templates"]
            )
            path = os.path.join(directory, filename)
            names = _local_template_field_names(path)
            if any(
                name == old_name
                or name.startswith(old_name + ".")
                or name.startswith(old_name + "[")
                for name in names
            ):
                problems.append(
                    f"{filename} contains {old_name}. A YAML-only rename cannot update this binary template. "
                    "Update its fields and references together in source before renaming."
                )
        except Exception:
            problems.append(
                f"{filename} could not be inspected for references to {old_name}. "
                "Check the template before renaming; no files have been changed."
            )
    return problems


def _project_search_revision(files: List[Dict[str, Any]]) -> str:
    manifest = "\n".join(
        f"{item['section']}\0{item['filename']}\0{item['revision']}" for item in files
    )
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def _commit_project_replacements(
    user_id: int, project: str, changes: List[Dict[str, Any]]
) -> None:
    """Lock every interview file in a replacement batch before checking it."""
    sorted_changes = sorted(
        changes, key=lambda change: (change["section"], change["filename"])
    )
    with ExitStack() as locks:
        for change in sorted_changes:
            locks.enter_context(
                _source_file_lock(
                    user_id, project, change["filename"], change["section"]
                )
            )
        _commit_project_replacements_locked(user_id, project, changes)


def _commit_project_replacements_locked(
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

    attempted: List[Dict[str, Any]] = []
    try:
        for change in changes:
            # A failing write may already have truncated its destination.
            attempted.append(change)
            _write_project_text_file(
                user_id,
                project,
                change["section"],
                change["filename"],
                change["updated"],
            )
    except Exception as write_exc:
        restored: List[Dict[str, str]] = []
        recovery: List[Dict[str, str]] = []
        for change in reversed(attempted):
            identity = {"section": change["section"], "filename": change["filename"]}
            try:
                _write_project_text_file(
                    user_id,
                    project,
                    change["section"],
                    change["filename"],
                    change["original"],
                )
                if (
                    _read_project_text_file(
                        user_id, project, change["section"], change["filename"]
                    )
                    != change["original"]
                ):
                    raise OSError("Restored content did not match the original")
                restored.append(identity)
            except Exception as rollback_exc:
                recovery.append(identity | {"original_content": change["original"]})
                log(
                    "ALWeaver editor: project replace rollback failed for "
                    f"{change['section']}/{change['filename']}: {rollback_exc!r}",
                    "error",
                )
        raise ProjectReplacementWriteError(restored, recovery) from write_exc


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
    capability = _restart_capability()
    module_restart = {
        "policy": _module_restart_policy(),
        "allowed": capability["allowed"],
        "blocked_reason": capability["reason"],
        "disruption_seconds": list(RESTART_DISRUPTION_SECONDS),
    }
    assistant_privacy = {
        "provider_name": _weaver_text("assistant provider name") or "",
        "model_name": _weaver_text("assistant model") or "",
        "provider_retention": _weaver_text("assistant provider retention") or "",
    }
    return {
        "patch_model": patch_model,
        "runtime_inspector": runtime_inspector,
        "agent_editor": agent_editor,
        "assistant_status": status,
        "assistant_privacy": assistant_privacy,
        "module_restart": module_restart,
        "patchModel": patch_model,
        "runtimeInspector": runtime_inspector,
        "agentEditor": agent_editor,
        "assistantStatus": status,
        "assistantPrivacy": assistant_privacy,
        "moduleRestart": module_restart,
    }


def _render_editor_page() -> str:
    """Build the editor HTML, injecting bootstrap JSON for the logged-in user."""
    html = _get_template_content("editor.html")
    if not html:
        return ""
    login_url, logout_url = _editor_auth_urls()
    celery_check = get_worker_configuration_status()
    celery_check["setup"] = _celery_setup_capability()
    bootstrap: Dict[str, Any] = {
        "apiBasePath": EDITOR_BASE_PATH,
        "previewWidgetStyle": _preview_widget_style(),
        "csrfToken": generate_csrf(),
        "features": _editor_feature_bootstrap(),
        "systemChecks": {
            "celery": celery_check,
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
            projects = playground_list_projects(uid)
            bootstrap["projects"] = projects
            bootstrap["projectSyncs"] = _project_github_sync_summaries(uid, projects)
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


def _preview_widget_style() -> str:
    """Select the markup used by the installed standardformatter."""
    try:
        version = importlib.metadata.version("docassemble.base")
    except importlib.metadata.PackageNotFoundError:
        return "labelauty"
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if match and tuple(map(int, match.groups())) >= (1, 10, 8):
        return "native"
    return "labelauty"


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


_template_context_cache = FileResultCache(max_bytes=256 * 1024)


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

    return _template_context_cache.get(
        (user_id, project, project_dir, max_chars),
        lambda dependencies: _extract_template_context(
            project_dir, max_chars, dependencies
        ),
    )


def _extract_template_context(
    project_dir: str, max_chars: int, dependencies: Dependencies
) -> str:
    dependencies.add(project_dir, content=False)
    chunks: List[str] = []
    for filename in sorted(os.listdir(project_dir))[:3]:
        path = os.path.join(project_dir, filename)
        if not os.path.isfile(path):
            continue
        dependencies.add(path, content=False)
        ext = os.path.splitext(filename.lower())[1]
        extracted = ""
        try:
            if ext == ".pdf":
                from pdfminer.high_level import extract_text

                extracted = extract_text(path, maxpages=2)
            elif ext == ".docx":
                from docx2python import docx2python

                with docx2python(path) as document:
                    extracted = document.text
        except Exception:
            dependencies.cacheable = False
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


class EmptyQuestionError(ValueError):
    """A question block's label is blank and the author has not opted in."""


def _validate_block_yaml_payload(
    block_yaml: str, *, allow_empty_question: bool = False
) -> None:
    """Validate a single block payload before saving/inserting.

    Two shapes look like placeholders but are legitimate documents, and both
    are what the "Add a block" modal hands over:

    * a document of nothing but YAML comments — a blank new block, before its
      author has typed anything over it;
    * a standalone ``comment:`` block — prose about the interview.

    What is rejected is an ``id`` with nothing beside it that gives the block a
    type. The id names a block, there is no block there for it to name, and
    docassemble reports "couldn't identify a block type" on the whole file.
    Insertion may also create an empty question draft; saving that draft must
    supply question text.
    """
    try:
        parsed = _safe_load_interview_document(block_yaml)
    except RecursionError as exc:
        raise ValueError(
            "YAML nesting exceeds the supported validation depth."
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if parsed is None and is_comment_only_yaml(block_yaml):
        return
    if not isinstance(parsed, dict):
        raise ValueError("block_yaml must contain exactly one YAML mapping block")

    if (
        not allow_empty_question
        and "question" in parsed
        and (not isinstance(parsed["question"], str) or not parsed["question"].strip())
    ):
        raise EmptyQuestionError(
            "Question text is required before saving a question block"
        )

    normalized_keys = {
        str(key).strip().lower() for key in parsed.keys() if str(key).strip()
    }
    if not normalized_keys:
        raise ValueError("Block must contain at least one key")
    if "id" in normalized_keys and normalized_keys.issubset({"id", "comment"}):
        raise ValueError(
            "Block is incomplete: an id needs a block beside it to name, "
            "so add a key like question, code, or objects — or drop the id"
        )
    if "template" in parsed and (
        "content" in parsed or "subject" in parsed or "content file" in parsed
    ):
        name = str(parsed.get("template") or "").strip()
        if not name.isidentifier() or keyword.iskeyword(name):
            # Docassemble also supports generic/indexed and attribute template
            # names. They stay in the raw-YAML fallback; this validator must
            # not make an existing supported source form impossible to save.
            if re.fullmatch(
                r"[A-Za-z_]\w*(?:(?:\.[A-Za-z_]\w*)|(?:\[[^\]\r\n]+\]))+",
                name,
            ):
                return
            raise ValueError(
                "Template name must be a valid top-level Python identifier "
                "and not a Python keyword"
            )
        content = parsed.get("content")
        if "content file" not in parsed and (
            not isinstance(content, str) or not content.strip()
        ):
            raise ValueError("Template content cannot be empty")
        subject = parsed.get("subject")
        if subject is not None and not isinstance(subject, str):
            raise ValueError("Template subject must be text")


def _template_references(
    content: str, name: str, exclude_block_id: str = ""
) -> List[str]:
    """Describe direct uses that would lose their last template definition."""
    if not name:
        return []
    blocks = parse_interview_yaml(content)["blocks"]
    if exclude_block_id and any(
        block.get("type") == "template"
        and str(block.get("id") or "") != exclude_block_id
        and str((block.get("data") or {}).get("template") or "").strip() == name
        for block in blocks
    ):
        return []
    pattern = re.compile(
        r"\bcollapse_template\s*\(\s*" + re.escape(name) + r"\s*(?=[,)])"
    )
    references: List[str] = []
    for block in blocks:
        if str(block.get("id") or "") == exclude_block_id:
            continue
        block_yaml = str(block.get("yaml") or "")
        if not pattern.search(block_yaml):
            continue
        references.append(
            f"{block.get('title') or block.get('id') or 'block'} "
            f"(line {block.get('line_start') or '?'})"
        )
    return references


def _known_top_level_names(content: str, exclude_block_id: str = "") -> Set[str]:
    """Collect non-template bindings without evaluating interview code."""
    names: Set[str] = set()
    for block in parse_interview_yaml(content)["blocks"]:
        if str(block.get("id") or "") == exclude_block_id:
            continue
        data = block.get("data") or {}
        if not isinstance(data, dict):
            continue
        if block.get("type") == "template":
            continue
        objects = data.get("objects")
        if isinstance(objects, dict):
            names.update(str(value).strip() for value in objects if str(value).strip())
        elif isinstance(objects, list):
            for item in objects:
                if isinstance(item, dict):
                    names.update(
                        str(value).strip() for value in item if str(value).strip()
                    )
        fields = data.get("fields")
        if isinstance(fields, list):
            for field in fields:
                if not isinstance(field, dict):
                    continue
                explicit = field.get("field")
                if isinstance(explicit, str) and explicit.strip():
                    names.add(explicit.strip().split(".", 1)[0].split("[", 1)[0])
                    continue
                for label, value in field.items():
                    if label in {
                        "datatype",
                        "default",
                        "hint",
                        "help",
                        "label",
                        "required",
                        "show if",
                        "hide if",
                        "enable if",
                        "disable if",
                        "input type",
                        "validate",
                        "choices",
                        "code",
                        "note",
                        "html",
                        "raw html",
                    }:
                        continue
                    if isinstance(value, str) and value.strip():
                        names.add(value.strip().split(".", 1)[0].split("[", 1)[0])
                        break
        for key in (
            "continue button field",
            "sets",
            "signature",
            "yesno",
            "noyes",
            "yesnomaybe",
            "noyesmaybe",
            "field",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                names.add(value.strip().split(".", 1)[0].split("[", 1)[0])
        variable = str(block.get("variable") or "").strip()
        if variable:
            names.add(variable.split(".", 1)[0].split("[", 1)[0])
        code = data.get("code")
        if isinstance(code, str):
            try:
                tree = ast.parse(code)
            except SyntaxError:
                tree = None
            if tree is not None:
                pending: List[ast.AST] = list(tree.body)
                while pending:
                    node = pending.pop()
                    if isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    ):
                        names.add(node.name)
                        continue  # Their bodies bind names in a separate scope.
                    if isinstance(
                        node,
                        (
                            ast.Lambda,
                            ast.ListComp,
                            ast.SetComp,
                            ast.DictComp,
                            ast.GeneratorExp,
                        ),
                    ):
                        continue
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                        names.add(node.id)
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        for imported in node.names:
                            if imported.name != "*":
                                names.add(
                                    imported.asname or imported.name.split(".", 1)[0]
                                )
                    pending.extend(ast.iter_child_nodes(node))
    return names


def _validate_template_against_file(
    current_content: str, block_yaml: str, *, current_block_id: str = ""
) -> None:
    parsed = _safe_load_interview_document(block_yaml)
    if (
        not isinstance(parsed, dict)
        or "template" not in parsed
        or not ("content" in parsed or "subject" in parsed or "content file" in parsed)
    ):
        return
    name = str(parsed.get("template") or "").strip()
    if current_block_id:
        current = next(
            (
                block
                for block in parse_interview_yaml(current_content)["blocks"]
                if str(block.get("id") or "") == current_block_id
            ),
            None,
        )
        old_name = str(((current or {}).get("data") or {}).get("template") or "")
        if old_name == name:
            return  # Existing language/conditional variants can share a name.
        if old_name:
            references = _template_references(
                current_content, old_name, exclude_block_id=current_block_id
            )
            if references:
                raise ValueError(
                    f"Cannot rename template {old_name!r}; it is used by: "
                    + ", ".join(references)
                )
    if name.isidentifier() and name in _known_top_level_names(
        current_content, current_block_id
    ):
        raise ValueError(
            f"The name {name!r} is already defined by a non-template block "
            "in this interview file. Choose a different template variable name."
        )


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------


@app.route(EDITOR_BASE_PATH, methods=["GET"])
@app.route(f"{EDITOR_BASE_PATH}/", methods=["GET"])
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


def _editor_spa_route(**_route_values: str) -> Response:
    """Serve the shell through the canonical page handler."""
    return editor_page()


# Browser routes mirror the editor's project/interview hierarchy.  Keep these
# explicit: an unrestricted catch-all here could mask API or asset endpoints.
for _index, _route in enumerate(
    (
        f"{EDITOR_BASE_PATH}/projects/<project>",
        f"{EDITOR_BASE_PATH}/projects",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>/blocks",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>/blocks/<block_id>",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>/source",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>/order",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>/settings",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>/tests",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>/debug",
        f"{EDITOR_BASE_PATH}/projects/<project>/interviews/<filename>/documents",
        f"{EDITOR_BASE_PATH}/projects/<project>/templates",
        f"{EDITOR_BASE_PATH}/projects/<project>/templates/<filename>",
        f"{EDITOR_BASE_PATH}/projects/<project>/modules",
        f"{EDITOR_BASE_PATH}/projects/<project>/modules/<filename>",
        f"{EDITOR_BASE_PATH}/projects/<project>/static",
        f"{EDITOR_BASE_PATH}/projects/<project>/static/<filename>",
        f"{EDITOR_BASE_PATH}/projects/<project>/sources",
        f"{EDITOR_BASE_PATH}/projects/<project>/sources/<filename>",
        f"{EDITOR_BASE_PATH}/projects/<project>/documents",
        f"{EDITOR_BASE_PATH}/create",
    )
):
    app.add_url_rule(
        _route,
        endpoint=f"editor_spa_{_index}",
        view_func=_editor_spa_route,
        methods=["GET"],
        strict_slashes=False,
    )


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


def _github_sync_summary(sync: Dict[str, Any]) -> Dict[str, Any]:
    """Return the client-safe fields of a project's GitHub sync record."""
    return {
        "package": sync["package"],
        "repository_url": sync["repository_url"],
        "branch": sync["branch"],
        "has_merge_base": bool(sync.get("commit")),
    }


def _project_github_sync_summaries(
    user_id: int, projects: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Return safe GitHub sync metadata keyed by Playground project."""
    summaries: Dict[str, Dict[str, Any]] = {}
    for project in projects:
        sync = find_project_github_sync(user_id=user_id, project_name=project)
        if not sync:
            continue
        summaries[project] = _github_sync_summary(sync)
    return summaries


@app.route(f"{EDITOR_BASE_PATH}/api/projects", methods=["GET"])
def editor_api_projects() -> Response:
    """List playground projects for the current user."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        projects = playground_list_projects(uid)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "projects": projects,
                    "github_syncs": _project_github_sync_summaries(uid, projects),
                },
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


@app.route(f"{EDITOR_BASE_PATH}/github/authorize", methods=["GET"])
def editor_github_authorize() -> Response:
    """Connect GitHub, including permission to publish ALKiln workflows."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    return cast(Response, redirect(github_authorization_url()))


def _attach_workflow_access(uid: int, owners: List[Dict[str, Any]]) -> None:
    """Say per owner whether publishing can include ALKiln workflows.

    GitHub only reveals a missing workflow permission by rejecting the
    commit, so the dialog checks up front and names the fix. A failed check
    leaves the owners unmarked; the publish itself still handles rejection.
    """
    try:
        access = get_github_workflow_access(
            [str(owner["login"]) for owner in owners], user_id=uid
        )
    except Exception as exc:
        log(f"ALWeaver editor: GitHub workflow access check failed: {exc!r}", "warning")
        return
    for owner in owners:
        owner["workflow_access"] = access["owners"].get(str(owner["login"]))


def _server_github_owner() -> str:
    """The server's ``github issues: default repository owner``, or ''.

    AssemblyLine files feedback there (or with ``suffolklitlab``) when an
    interview names no ``github_user``.
    """
    github_issues = _daconfig().get("github issues")
    if not isinstance(github_issues, dict):
        return ""
    return str(github_issues.get("default repository owner") or "").strip()


@app.route(f"{EDITOR_BASE_PATH}/api/github/owners", methods=["GET"])
def editor_api_github_owners() -> Response:
    """List the GitHub accounts a new project can be associated with.

    The new-project screen offers these for "Associate with this GitHub
    username", selecting ``default_owner``, alongside ``server_owner``, the
    server's ``github issues: default repository owner`` setting (empty when
    it is not set). Without a GitHub connection,
    ``owners`` is empty.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        owners = get_github_publish_owners(user_id=_current_user_id())
    except GithubCredentialError:
        owners = []
    except Exception as exc:
        log(f"ALWeaver editor: GitHub owners lookup failed: {exc!r}", "warning")
        owners = []
    server_owner = _server_github_owner()
    return jsonify(
        {
            "success": True,
            "request_id": request_id,
            "data": {
                "owners": owners,
                "default_owner": default_github_owner(owners, server_owner),
                "server_owner": server_owner,
            },
        }
    )


@app.route(f"{EDITOR_BASE_PATH}/api/github/status", methods=["GET"])
def editor_api_github_status() -> Response:
    """Report whether Docassemble's native GitHub publisher is ready."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        default_package = normalize_github_package_name(
            normalize_project_name(project, fallback="WeaverProject")
        )
        sync = find_project_github_sync(user_id=uid, project_name=project)
        sync_data = None
        if sync:
            try:
                repository = normalize_github_repository_url(sync["repository_url"])
            except ValueError:
                pass
            else:
                commit = str(sync.get("commit") or "").strip()
                published = bool(re.fullmatch(r"[0-9a-fA-F]{40}", commit))
                sync_data = {
                    **_github_sync_summary(sync),
                    "owner": repository["owner"],
                    "repository_url": repository["url"],
                    "published": published,
                    "commit_url": (
                        f"{repository['url']}/commit/{commit}" if published else None
                    ),
                }
        if parse_bool(request.args.get("sync_only"), default=False):
            return jsonify(
                {
                    "success": True,
                    "request_id": request_id,
                    "data": {"project": project, "sync": sync_data},
                }
            )
        status = get_native_github_integration(uid)
        if status.get("enabled"):
            status["configure_url"] = url_for("editor_github_authorize")
        owners: List[Dict[str, Any]] = []
        if status.get("enabled") and status.get("connected"):
            try:
                owners = [
                    {
                        **owner,
                        "available": bool(
                            owner.get("type") == "user"
                            or status.get("organizations_enabled")
                        ),
                    }
                    for owner in get_github_publish_owners(user_id=uid)
                ]
            except GithubCredentialError as exc:
                # The Redis integration flag can outlive the OAuth record.
                # Treat that state as disconnected so the editor can show the
                # normal reconnect path instead of returning a 400 caused by
                # credential JSON parsing.
                log(
                    f"ALWeaver editor: GitHub credential unavailable: {exc!r}",
                    "warning",
                )
                status.update({"connected": False, "organizations_enabled": False})
        if owners:
            _attach_workflow_access(uid, owners)
        status["owners"] = owners
        status.update(
            {
                "project": project,
                "default_package": default_package,
                "default_repository": f"docassemble-{default_package}",
                # Publishing runs in the Celery worker, so the modal can refuse
                # up front rather than after the user fills the form in.
                "async_configured": _editor_async_is_configured(),
                "celery": get_worker_configuration_status(),
                "sync": sync_data,
            }
        )
        return jsonify({"success": True, "request_id": request_id, "data": status})
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
        log(f"ALWeaver editor: GitHub status error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/github/branches", methods=["GET"])
def editor_api_github_branches() -> Response:
    """List a GitHub repository's branches.

    Either ``repository_url`` (any repository, read anonymously when GitHub is
    not connected) or the ``owner`` and ``package`` of a publish target.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        if request.args.get("repository_url"):
            repository = normalize_github_repository_url(request.args["repository_url"])
            branches = get_github_repository_branches(
                owner=repository["owner"],
                repository=repository["repository"],
                user_id=uid,
                allow_anonymous=True,
            )
            return jsonify(
                {
                    "success": True,
                    "request_id": request_id,
                    "data": {"repository_url": repository["url"], **branches},
                }
            )
        project = _normalize_project(request.args.get("project"))
        package = normalize_github_package_name(request.args.get("package"))
        owner = str(request.args.get("owner") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner):
            raise ValueError("Choose a GitHub account or organization")
        integration = get_native_github_integration(uid)
        if not integration.get("enabled") or not integration.get("connected"):
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "github_not_connected",
                        "message": "Connect your GitHub account before listing branches.",
                    },
                },
                409,
            )
        branches = get_github_repository_branches(
            owner=owner, repository=f"docassemble-{package}", user_id=uid
        )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "owner": owner,
                    "package": package,
                    **branches,
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
    except GithubCredentialError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "github_not_connected", "message": str(exc)},
            },
            409,
        )
    except Exception as exc:
        log(f"ALWeaver editor: GitHub branch list error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


def _repository_config_package(project: str, raw_package: Any) -> str:
    if str(raw_package or "").strip():
        return normalize_github_package_name(raw_package)
    sync = find_project_github_sync(user_id=_current_user_id(), project_name=project)
    if sync:
        return str(sync["package"])
    return normalize_github_package_name(
        normalize_project_name(project, fallback="WeaverProject")
    )


def _repository_config_author() -> Dict[str, str]:
    # Publishing stamps the current user into the manifest, so the preview
    # shows the pyproject.toml that publish will actually write.
    return {
        "author_name": _editor_user_designator(),
        "author_email": str(getattr(current_user, "email", "") or "").strip(),
    }


GITHUB_PUBLISH_PREVIEW_MAX_AGE_SECONDS = 15 * 60


def _sign_github_publish_preview(data: Dict[str, Any]) -> str:
    secret = getattr(app, "secret_key", None)
    if not secret:
        raise RuntimeError("This server cannot sign a GitHub publish preview")
    key = secret if isinstance(secret, bytes) else str(secret).encode("utf-8")
    body = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(key, body, hashlib.sha256).digest()
    return ".".join(
        (
            base64.urlsafe_b64encode(body).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
        )
    )


def _verify_github_publish_preview(token: Any) -> Dict[str, Any]:
    secret = getattr(app, "secret_key", None)
    try:
        if not secret or not isinstance(token, str):
            raise ValueError
        encoded_body, encoded_signature = token.split(".", 1)
        body = base64.urlsafe_b64decode(encoded_body + "=" * (-len(encoded_body) % 4))
        signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        key = secret if isinstance(secret, bytes) else str(secret).encode("utf-8")
        expected = hmac.new(key, body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        issued_at = int(data.get("issued_at") or 0)
        if time.time() - issued_at > GITHUB_PUBLISH_PREVIEW_MAX_AGE_SECONDS:
            raise ValueError
        if issued_at > time.time() + 60:
            raise ValueError
        return data
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(
            "This GitHub publish preview is invalid or expired. Preview the changes again."
        ) from exc


def _github_publish_diff(
    local_files: Dict[str, Dict[str, Any]],
    remote_files: Dict[str, bytes],
    *,
    managed_paths: Set[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Summarize the complete target tree and return bounded text diffs."""
    target: Dict[str, bytes] = {
        path: item["content"] for path, item in local_files.items()
    }
    for path, content in remote_files.items():
        if (
            path.startswith(".github/")
            and path not in target
            and path not in managed_paths
        ):
            target[path] = content

    changes: List[Dict[str, Any]] = []
    names: List[str] = sorted(target)
    total_diff_chars = 0
    for path in sorted(set(target) | set(remote_files)):
        if path not in remote_files:
            change = "added"
        elif path not in target:
            change = "deleted"
        elif target[path] != remote_files[path]:
            change = "modified"
        else:
            continue
        item: Dict[str, Any] = {"path": path, "change": change}
        old = remote_files.get(path, b"")
        new = target.get(path, b"")
        try:
            if b"\0" in old or b"\0" in new:
                raise UnicodeDecodeError("utf-8", b"\0", 0, 1, "binary")
            old_text = old.decode("utf-8").splitlines(keepends=True)
            new_text = new.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            item["binary"] = True
        else:
            patch_text = "".join(
                difflib.unified_diff(
                    old_text,
                    new_text,
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    n=3,
                )
            )
            remaining = max(0, 100_000 - total_diff_chars)
            item["diff"] = patch_text[: min(5_000, remaining)]
            total_diff_chars += len(item["diff"])
            if len(patch_text) > len(item["diff"]):
                item["diff_truncated"] = True
        changes.append(item)
    return changes, names


@app.route(f"{EDITOR_BASE_PATH}/api/github/repository-config", methods=["GET", "POST"])
def editor_api_github_repository_config() -> Response:
    """Read or change the workflows and pyproject.toml a publish writes.

    A POST carries one ``operation`` so each toggle or editor save is applied
    against the stored settings rather than a stale copy from the browser.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        if request.method == "POST":
            post_data = request.get_json(silent=True) or {}
            project = _normalize_project(post_data.get("project"))
            package = _repository_config_package(project, post_data.get("package"))
            view = update_repository_config(
                uid,
                project,
                package,
                post_data.get("operation"),
                manifest_overrides=_repository_config_author(),
            )
        else:
            project = _normalize_project(request.args.get("project"))
            package = _repository_config_package(project, request.args.get("package"))
            view = repository_config_view(
                uid, project, package, manifest_overrides=_repository_config_author()
            )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "package": package,
                    "pyproject_path": PYPROJECT_PATH,
                    **view,
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
        log(f"ALWeaver editor: GitHub repository settings error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/github/publish", methods=["POST"])
def editor_api_github_publish() -> Response:
    """Prepare a Playground package and queue the commit to GitHub.

    Everything that can fail on the user's input is checked here so the browser
    gets an immediate 400/409.  The GitHub round trips — one blob upload per
    file — are handed to the Celery worker and polled through the job URL in
    the 202 response.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    integration: Dict[str, Any] = {}
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        package = normalize_github_package_name(post_data.get("package"))
        owner = str(post_data.get("owner") or "").strip()
        if not owner:
            raise ValueError("GitHub owner is required")
        branch = _normalize_git_branch(post_data.get("branch"))
        commit_message = _normalize_commit_message(post_data.get("commit_message"))
        # Checked after the input is validated so a malformed request still gets
        # its 400, but before anything is written or queued.
        if not _editor_async_is_configured():
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "async_not_configured",
                        "code": "editor_async_not_configured",
                        "message": (
                            "Background GitHub publishing is not configured. Add "
                            f"{CELERY_MODULE!r} to the Docassemble 'celery "
                            "modules' configuration list, then restart the "
                            "Docassemble web and Celery services."
                        ),
                        "details": get_worker_configuration_status(),
                    },
                },
                503,
            )
        integration = get_native_github_integration(uid)
        if not integration.get("enabled"):
            raise RuntimeError(
                "Docassemble's GitHub integration is not enabled on this server"
            )
        if not integration.get("connected"):
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "github_not_connected",
                        "message": "Connect your GitHub account in Docassemble before publishing.",
                    },
                    "data": {"configure_url": integration.get("configure_url")},
                },
                409,
            )

        author_name = _editor_user_designator()
        author_email = str(getattr(current_user, "email", "") or "").strip()
        owners = get_github_publish_owners(user_id=uid)
        selected_owner = next(
            (
                candidate
                for candidate in owners
                if candidate["login"].casefold() == owner.casefold()
            ),
            None,
        )
        if selected_owner is None:
            raise ValueError("Choose a GitHub account or organization from the list")
        if selected_owner.get("type") == "organization" and not integration.get(
            "organizations_enabled"
        ):
            raise ValueError(
                "Enable organization repository access in Docassemble's GitHub settings first"
            )
        repository = f"docassemble-{package}"
        repository_url = f"https://github.com/{selected_owner['login']}/{repository}"
        # A preview is optional. When the browser sends one, hold the publish
        # to what the user reviewed. Either way the worker refuses a branch
        # with commits this project has not pulled.
        preview_token = post_data.get("preview_token")
        preview = (
            _verify_github_publish_preview(preview_token) if preview_token else None
        )
        if preview is not None and (
            preview.get("user_id") != uid
            or preview.get("project") != project
            or preview.get("package") != package
            or str(preview.get("owner") or "").casefold()
            != str(selected_owner["login"]).casefold()
            or str(preview.get("repository_url") or "").rstrip("/").casefold()
            != repository_url.rstrip("/").casefold()
            or preview.get("branch") != branch
        ):
            raise ValueError(
                "The publish target changed after preview. Review the current target before publishing."
            )
        # Docassemble's github_url, github_branch, and commit marker describe
        # the last successful publish. Keep them until the worker commits and
        # record_project_github_sync updates all three together.
        prepared = prepare_project_github_package(
            user_id=uid,
            project_name=project,
            package_name=package,
            author_name=author_name,
            author_email=author_email,
            dependencies=repository_dependency_names(uid, project, package),
        )
        if preview is not None:
            package_info, manifest_path = load_project_github_manifest(
                user_id=uid,
                project_name=project,
                package_name=package,
            )
            repository_files = repository_publish_files(
                uid, project, package, manifest=package_info
            )
            current_snapshot = build_github_package_snapshot(
                package=package,
                project=project,
                user_id=uid,
                package_info=package_info,
                author_name=author_name,
                author_email=author_email,
                manifest_path=manifest_path,
                extra_repository_files=repository_files["files"],
            )
            if github_package_snapshot_revision(current_snapshot) != preview.get(
                "source_revision"
            ):
                raise ValueError(
                    "The Playground package changed after its publish preview. Preview the current files again."
                )
        reviewed = preview or {}
        queued = _start_github_publish_job(
            uid=uid,
            request_id=request_id,
            project=project,
            package=prepared["package"],
            repository=prepared["repository"],
            owner=selected_owner["login"],
            owner_type=str(selected_owner.get("type") or ""),
            author_name=author_name,
            author_email=author_email,
            branch=branch,
            commit_message=commit_message,
            repository_url=repository_url,
            expected_remote_sha=reviewed.get("remote_sha") or None,
            expected_source_revision=reviewed.get("source_revision"),
        )
        return jsonify_with_status(
            {
                "success": True,
                "request_id": request_id,
                "job_id": queued["job_id"],
                "status": "queued",
                "data": {
                    "project": project,
                    "package": prepared["package"],
                    "repository": prepared["repository"],
                    "owner": selected_owner["login"],
                    "repository_url": repository_url,
                    "branch": branch,
                    "job_id": queued["job_id"],
                    "job_url": queued["job_url"],
                    "state": queued["state"],
                },
            },
            202,
        )
    except GithubCredentialError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "github_not_connected",
                    "message": str(exc),
                },
                "data": {"configure_url": integration.get("configure_url")},
            },
            409,
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
        log(f"ALWeaver editor: GitHub publish error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(
    f"{EDITOR_BASE_PATH}/api/github/publish/jobs/<job_id>",
    methods=["GET"],
)
def editor_api_github_publish_job(job_id: str) -> Response:
    """Get the status of a queued GitHub publish."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        state = _load_job_state(GITHUB_PUBLISH_JOB, job_id)
        if not state or state.get("owner_user_id") not in {None, uid}:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {"type": "not_found", "message": "Job not found."},
                },
                404,
            )
        state = _reconcile_github_publish_job_state(job_id, state)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "job_id": job_id,
                "status": str(state.get("status") or "queued"),
                "data": state,
            }
        )
    except Exception as exc:
        log(f"ALWeaver editor: GitHub publish job status error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/github/pull", methods=["POST"])
def editor_api_github_pull() -> Response:
    """Merge a branch of the project's GitHub repository into the project.

    ``branch`` defaults to the synced branch. Pulling another branch merges
    from the commit it shares with the last sync, and a clean merge moves the
    project's sync to that branch so it can be published to.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        sync = find_project_github_sync(user_id=uid, project_name=project)
        if not sync:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "not_synced",
                        "message": "This project is not linked to a GitHub repository.",
                    },
                },
                409,
            )
        branch = (
            _normalize_git_branch(post_data["branch"])
            if post_data.get("branch")
            else sync["branch"]
        )
        remote = get_github_repository_snapshot(
            repository_url=sync["repository_url"], user_id=uid, ref=branch
        )
        # Older manifests did not record the published commit. Establishing the
        # current head as the base is safe and makes all later pulls mergeable.
        base_ref: Optional[str] = sync.get("commit") or remote["sha"]
        if sync.get("commit") and branch != sync["branch"]:
            base_ref = get_github_merge_base(
                repository_url=sync["repository_url"],
                base=sync["commit"],
                head=remote["sha"],
                user_id=uid,
            )
            if not base_ref:
                raise ValueError(
                    f"GitHub branch {branch!r} shares no history with this "
                    "project. Create a project from that branch instead."
                )
        base = (
            remote
            if base_ref == remote["sha"]
            else get_github_repository_snapshot(
                repository_url=sync["repository_url"], user_id=uid, ref=base_ref
            )
        )
        result = merge_github_snapshot(
            user_id=uid,
            project_name=project,
            base_snapshot=base,
            remote_snapshot=remote,
            sync=sync,
        )
        if not result.get("merged"):
            conflicts = result.get("conflicts") or []
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "merge_conflict",
                        "message": "GitHub changes conflict with local edits. No files were changed.",
                        "details": {"conflicts": conflicts, "branch": branch},
                    },
                },
                409,
            )
        adopt_repository_snapshot(
            uid,
            project,
            sync["package"],
            remote["files"],
            # With a recorded sync point, only files changed on GitHub since
            # then are taken; when nothing moved, nothing is. A manifest from
            # before sync points were recorded has nothing to compare
            # against, so the repository is taken as on an import.
            base["files"] if sync.get("commit") else None,
        )
        _reconcile_project_modules(uid, project)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    **result,
                    "restart_state": _restart_state_payload(uid, project),
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
        log(f"ALWeaver editor: GitHub pull error: {exc!r}", "error")
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
    except FileNotFoundError:
        # Playground raises this both for absent projects and projects the
        # current user cannot access. Keep the response deliberately generic:
        # exception text may include a private server-side filesystem path.
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "not_found",
                    "message": "Project not found or unavailable.",
                },
            },
            404,
        )
    except Exception as exc:
        log(
            f"ALWeaver editor: files error ({type(exc).__name__}) request_id={request_id}",
            "error",
        )
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "message": "Unable to list project files.",
                },
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
        warnings: List[str] = []

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
            warnings = _binary_template_rename_problems(uid, project, query)
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
                    "warnings": warnings,
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
            problems.extend(_binary_template_rename_problems(uid, project, query))
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
    except ProjectReplacementWriteError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "replacement_write_failed",
                    "message": str(exc),
                    "details": {
                        "restored_files": exc.restored,
                        "recovery_files": exc.recovery,
                    },
                },
            },
            500,
        )
    except SourceWriteLockUnavailable as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "source_lock_unavailable",
                    "code": "source_lock_unavailable",
                    "message": str(exc),
                },
            },
            503,
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
                    "revision": source_revision(content),
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
        # A module that does not compile is refused rather than saved, because
        # the failure would otherwise surface much later, in whichever
        # interview imports it. "force" lets the developer keep unfinished work
        # anyway; it is saved but deliberately not published.
        force = parse_bool(post_data.get("force"), default=False)
        module_info: Optional[Dict[str, Any]] = None
        if section == "modules":
            validate_module_filename(filename)
            if not force:
                check_module_syntax(filename, content)
        path = os.path.join(directory, filename)
        try:
            with _source_file_lock(uid, project, filename, section):
                current_content = ""
                if os.path.isfile(path) and not os.path.islink(path):
                    with open(path, "rb") as fh:
                        current_content = fh.read().decode("utf-8", errors="replace")
                conflict = _section_file_revision_conflict(
                    post_data, current_content, request_id
                )
                if conflict is not None:
                    return conflict
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
                area.finalize()
        except SourceWriteLockUnavailable as exc:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "source_lock_unavailable",
                        "code": "source_lock_unavailable",
                        "message": str(exc),
                    },
                },
                503,
            )
        if section == "modules":
            try:
                check_module_syntax(filename, content)
            except ModuleSyntaxError as syntax_exc:
                module_info = {
                    "status": "not_published",
                    "restart_required": False,
                    "message": (
                        f"{filename} was saved but not installed, because it "
                        f"does not compile: {syntax_exc}"
                    ),
                }
            else:
                module_info = _save_module_file(uid, project, filename, content)
        data: Dict[str, Any] = {
            "project": project,
            "section": section,
            "filename": filename,
            "size": len(content),
            "revision": source_revision(content),
        }
        if module_info is not None:
            data["module"] = module_info
            data["restart_state"] = _restart_state_payload(uid, project)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": data,
            }
        )
    except ModuleSyntaxError as exc:
        return _module_error_response(request_id, exc)
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
        # Rejected here rather than at first save: a module whose name
        # Docassemble will not import is worth catching before the developer
        # writes any code in it.
        if section == "modules":
            validate_module_filename(filename)
            check_module_syntax(filename, content)
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            raise ValueError(f"{filename} already exists")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        area.finalize()
        data: Dict[str, Any] = {
            "project": project,
            "section": section,
            "filename": filename,
            "size": len(content),
        }
        if section == "modules":
            data["module"] = _save_module_file(uid, project, filename, content)
            data["restart_state"] = _restart_state_payload(uid, project)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": data,
            }
        )
    except ModuleSyntaxError as exc:
        return _module_error_response(request_id, exc)
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


@app.route(
    f"{EDITOR_BASE_PATH}/api/template/variable-report/suggestion", methods=["GET"]
)
def editor_api_template_variable_report_suggestion() -> Response:
    """The title, filename and source files a variable report would use."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))

        raw_yaml = playground_read_yaml(uid, project, filename)

        def read_project_file(name: str) -> str:
            if name == filename:
                return raw_yaml
            return playground_read_yaml(uid, project, _normalize_filename(name))

        sources, yaml_texts = collect_interview_yaml_texts(
            read_project_file, filename, _project_yaml_filenames(uid, project)
        )
        suggested = suggested_report_names(yaml_texts, primary_filename=filename)
        # Which shapes this server can draft depends on the ALDashboard it has
        # installed, so the editor asks rather than assuming.
        options = court_form_options()
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "title": suggested["title"],
                    "filename": suggested["filename"],
                    "sources": sources,
                    "court_forms_supported": bool(options.get("supported")),
                    "shapes": options.get("shapes", []),
                    "court_profiles": options.get("profiles", []),
                },
            }
        )
    except ALDashboardUnavailable as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "unavailable", "message": str(exc)},
            },
            503,
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
        log(f"ALWeaver editor: variable-report suggestion error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/template/variable-report", methods=["POST"])
def editor_api_template_variable_report() -> Response:
    """Draft a starter DOCX template from the interview's own questions.

    The document is written into the project's templates folder, so it shows up
    beside uploaded templates and can be imported from Document setup like any
    other file.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        show_variable_names = bool(post_data.get("show_variable_names"))
        show_variable_types = bool(post_data.get("show_variable_types"))
        max_list_cols = _optional_list_columns(post_data.get("max_list_cols"))
        shape = str(post_data.get("shape") or "intake").strip().lower() or "intake"
        court_profile = str(post_data.get("court_profile") or "").strip() or None
        include_certificate_of_service = (
            bool(post_data.get("include_certificate_of_service"))
            if post_data.get("include_certificate_of_service") is not None
            else None
        )
        # Tri-state on purpose: unset means "whatever this court's profile
        # says", which is not the same answer as "do not number the body".
        numbered_paragraphs = _optional_flag(post_data.get("numbered_paragraphs"))
        include_markdown = bool(post_data.get("include_markdown"))

        raw_yaml = playground_read_yaml(uid, project, filename)

        def read_project_file(name: str) -> str:
            if name == filename:
                return raw_yaml
            return playground_read_yaml(uid, project, _normalize_filename(name))

        sources, yaml_texts = collect_interview_yaml_texts(
            read_project_file, filename, _project_yaml_filenames(uid, project)
        )
        suggested = suggested_report_names(yaml_texts, primary_filename=filename)
        report_title = str(post_data.get("title") or suggested["title"]).strip()
        output_filename = safe_project_filename(
            _normalize_storage_filename(
                post_data.get("output_filename") or suggested["filename"]
            ),
            default_stem="variables",
        )
        if not output_filename.lower().endswith(".docx"):
            output_filename += ".docx"

        storage_section = EDITOR_SECTION_TO_STORAGE["templates"]
        area, directory = _editor_storage_directory(uid, project, storage_section)
        path = os.path.join(directory, output_filename)
        # The Markdown draft is the same document in text, so it shares the
        # DOCX's name -- and has to clear the same overwrite check before
        # either file is written.
        markdown_filename = (
            f"{os.path.splitext(output_filename)[0]}.md" if include_markdown else None
        )
        for name in (output_filename, markdown_filename):
            if not name:
                continue
            if os.path.exists(os.path.join(directory, name)) and not post_data.get(
                "overwrite"
            ):
                raise ValueError(
                    f"{name} already exists. Rename it, or choose to replace it."
                )

        summary = write_variable_report_docx(
            yaml_texts,
            path,
            report_title=report_title or None,
            show_variable_names=show_variable_names,
            show_variable_types=show_variable_types,
            max_list_cols=max_list_cols,
            shape=shape,
            court_profile=court_profile,
            include_certificate_of_service=include_certificate_of_service,
            numbered_paragraphs=numbered_paragraphs,
            markdown_path=(
                os.path.join(directory, markdown_filename)
                if markdown_filename
                else None
            ),
        )

        # A Dashboard that hands back no markdown leaves nothing to sit beside
        # the new DOCX. Anything still at that path is the previous draft --
        # the overwrite check already cleared it, or we would not be here --
        # and it no longer describes the document next to it. Left alone it is
        # a trap: an attachment's `content file:` would go on assembling the
        # old text against the new form. So it goes, and the caller is told.
        markdown_written = bool(markdown_filename and summary.get("markdown_size"))
        if markdown_filename and not markdown_written:
            stale_markdown = os.path.join(directory, markdown_filename)
            if os.path.exists(stale_markdown):
                os.remove(stale_markdown)
        area.finalize()

        markdown_data: Dict[str, Any] = {}
        if markdown_written:
            markdown_data["markdown_filename"] = markdown_filename
        elif include_markdown:
            markdown_data["markdown_written"] = False

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "section": "templates",
                    "filename": output_filename,
                    "title": report_title,
                    "sources": sources,
                    **markdown_data,
                    **summary,
                },
            }
        )
    except ALDashboardUnavailable as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "unavailable", "message": str(exc)},
            },
            503,
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
        log(f"ALWeaver editor: template variable-report error: {exc!r}", "error")
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
        renamed_files: List[Dict[str, str]] = []
        modules: List[Dict[str, Any]] = []
        for upload in uploads:
            requested_name = _normalize_storage_filename(upload.filename)
            # A name Docassemble cannot resolve -- `contract (1).docx` -- would
            # be stored happily and then reported missing by every interview
            # that referred to it, so uploads are renamed at the door.
            candidate_name = safe_project_filename(requested_name, default_stem=section)
            reason = (
                "unsupported_characters" if candidate_name != requested_name else ""
            )
            if section == "modules":
                validate_module_filename(candidate_name)
            path = os.path.join(directory, candidate_name)
            if os.path.exists(path):
                stem, ext = os.path.splitext(candidate_name)
                counter = 1
                while os.path.exists(path):
                    candidate_name = f"{stem}_{counter}{ext}"
                    path = os.path.join(directory, candidate_name)
                    counter += 1
                reason = "name_taken"
                # De-duplicating the name can produce one Docassemble would
                # skip, e.g. util_1.py is fine but a leading digit would not be.
                if section == "modules":
                    validate_module_filename(candidate_name)
            upload.save(path)
            saved_files.append(candidate_name)
            # Say so rather than leaving the author to notice: the name they
            # uploaded is not the name anything in the project may refer to.
            if reason:
                renamed_files.append(
                    {
                        "from": requested_name,
                        "to": candidate_name,
                        "reason": reason,
                        "message": _renamed_file_message(
                            requested_name, candidate_name, reason
                        ),
                    }
                )
        area.finalize()
        for candidate_name in saved_files if section == "modules" else []:
            with open(os.path.join(directory, candidate_name), encoding="utf-8") as fh:
                uploaded_source = fh.read()
            try:
                check_module_syntax(candidate_name, uploaded_source)
            except ModuleSyntaxError as syntax_exc:
                modules.append(
                    {
                        "filename": candidate_name,
                        "status": "not_published",
                        "restart_required": False,
                        "message": (
                            f"{candidate_name} was uploaded but not installed, "
                            f"because it does not compile: {syntax_exc}"
                        ),
                    }
                )
                continue
            result = _save_module_file(uid, project, candidate_name, uploaded_source)
            result["filename"] = candidate_name
            modules.append(result)
        data: Dict[str, Any] = {
            "project": project,
            "section": section,
            "saved_files": saved_files,
            "renamed_files": renamed_files,
        }
        if section == "modules":
            data["modules"] = modules
            data["restart_state"] = _restart_state_payload(uid, project)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": data,
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


# A package name and a YAML file inside it, with no way to write ".." into
# either half. Docassemble's resolver refuses a traversal too; this refuses to
# hand it one in the first place.
_PACKAGE_YAML_REFERENCE_RE = re.compile(
    r"^(docassemble\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
    r":((?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.ya?ml)$"
)


def _read_package_yaml(reference: str) -> str:
    """Read one YAML file out of an installed package.

    An interview is made of more than the files in its playground: the screens
    an author never wrote -- a person's name, an address, the court -- come
    from ``docassemble.AssemblyLine`` and are installed alongside it. Reading
    them is what Docassemble itself does with the same reference, through the
    same resolver, so the report shows what a package really asks rather than
    a copy of it that goes stale.
    """
    if not _PACKAGE_YAML_REFERENCE_RE.match(reference or ""):
        raise ValueError("Not a package YAML reference")
    if package_question_filename is None:
        raise ValueError("This Docassemble cannot resolve package file references")
    # Docassemble's own resolver, which rejects a traversal or an invalid
    # package name rather than reaching outside the installed package.
    try:
        path = package_question_filename(reference)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"{reference} is not installed on this server")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _report_reader(uid: int, project: str) -> Any:
    def read(name: str) -> str:
        if ":" in name:
            return _read_package_yaml(name)
        return playground_read_yaml(uid, project, _normalize_filename(name))

    return read


@app.route(f"{EDITOR_BASE_PATH}/api/reports/entrypoints", methods=["POST"])
def editor_api_report_entrypoints() -> Response:
    """Suggest entrypoints while letting authors select any project interview."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        body = request.get_json(silent=True) or {}
        project = _normalize_project(body.get("project"))
        uid = _current_user_id()
        files = _project_yaml_filenames(uid, project)
        included: set[str] = set()
        runnable: set[str] = set()
        for name in files:
            model = parse_interview_yaml(playground_read_yaml(uid, project, name))
            for block in model["blocks"]:
                data = block.get("data") or {}
                targets = data.get("include", [])
                if isinstance(targets, str):
                    targets = [targets]
                if isinstance(targets, list):
                    included.update(t for t in targets if isinstance(t, str))
                if data.get("mandatory"):
                    runnable.add(name)
        result = [
            {"filename": name, "suggested": name in runnable or name not in included}
            for name in files
        ]
        return jsonify(
            {"success": True, "request_id": request_id, "data": {"files": result}}
        )
    except (ValueError, OSError) as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/reports/archive", methods=["POST"])
def editor_api_report_archive() -> Response:
    """Package browser-rendered reports into a portable ZIP with an index."""
    import base64
    import html
    import zipfile
    from io import BytesIO

    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        body = request.get_json(silent=True) or {}
        reports = body.get("reports")
        if not isinstance(reports, list) or not 1 <= len(reports) <= 100:
            raise ValueError("Select between 1 and 100 interviews.")
        output = BytesIO()
        links = []
        seen: set[str] = set()
        total = 0
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for report in reports:
                if not isinstance(report, dict):
                    raise ValueError("Invalid or duplicate report.")
                filename = _normalize_filename(report.get("filename")) + ".html"
                content = report.get("html")
                if not isinstance(content, str) or filename in seen:
                    raise ValueError("Invalid or duplicate report.")
                seen.add(filename)
                total += len(content.encode("utf-8"))
                if total > 50 * 1024 * 1024:
                    raise ValueError("Reports exceed the 50 MB archive limit.")
                archive.writestr(filename, content)
                links.append(
                    f'<li><a href="{html.escape(filename, quote=True)}">{html.escape(filename)}</a></li>'
                )
            archive.writestr(
                "index.html",
                '<!doctype html><html lang="en"><meta charset="utf-8">'
                "<title>Interview flow reports</title><h1>Interview flow reports</h1>"
                "<p>Open a report to read, print, or save it as PDF. Styling and diagrams require network access.</p><ul>"
                + "".join(links)
                + "</ul></html>",
            )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"content": base64.b64encode(output.getvalue()).decode()},
            }
        )
    except (ValueError, OSError) as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/reports/scan", methods=["POST"])
def editor_api_report_scan() -> Response:
    """Scan an entrypoint and includes without executing interview code."""
    from .interview_scan import scan_interview

    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        body = request.get_json(silent=True) or {}
        project = _normalize_project(body.get("project"))
        filename = _normalize_filename(body.get("filename"))
        read = _report_reader(_current_user_id(), project)
        read(
            filename
        )  # Fail an unavailable entrypoint instead of returning an empty report.
        result = scan_interview(read, filename)
        return jsonify({"success": True, "data": result, "request_id": request_id})
    except (ValueError, OSError) as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/package-file", methods=["GET"])
def editor_api_get_package_file() -> Response:
    """Parse a YAML file from an installed package into the block model.

    Read-only, and only ever a `data/questions` file of an installed
    ``docassemble.*`` package: the editor cannot write here, and nothing in a
    package is editable from this editor.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    reference = str(request.args.get("reference") or "").strip()
    try:
        raw_yaml = _read_package_yaml(reference)
        model = parse_interview_yaml(raw_yaml)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "reference": reference,
                    # The blocks carry their own `include:` entries, which is
                    # how the caller walks on to the next package file.
                    "blocks": model["blocks"],
                    "named_order_steps": _named_order_steps_from_model(model),
                },
            }
        )
    except (ValueError, DAInvalidFilename) as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except FileNotFoundError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "not_found", "message": str(exc)},
            },
            404,
        )
    except Exception as exc:
        log(f"ALWeaver editor: package file read error: {exc!r}", "error")
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
        order_step_map, order_steps = _order_steps_from_model(model)

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
                    "named_order_steps": _named_order_steps_from_model(model),
                    "raw_yaml": raw_yaml,
                    "revision": source_revision(raw_yaml),
                    "metadata_raw_yaml": metadata_source_slice(raw_yaml),
                },
            }
        )
    except FileNotFoundError:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "not_found",
                    "code": "interview_file_not_found",
                    "message": "Interview file not found.",
                },
            },
            404,
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


def _style_check_result(
    uid: int, project: str, filename: str, include_llm: bool
) -> Dict[str, Any]:
    raw_yaml = playground_read_yaml(uid, project, filename)
    model = parse_interview_yaml(raw_yaml)
    lint_result = _run_interview_linter(raw_yaml, include_llm=include_llm)
    findings = lint_result.get("findings", []) if isinstance(lint_result, dict) else []
    if not isinstance(findings, list):
        findings = []
    annotated_findings = _demote_style_findings(
        _annotate_lint_findings(findings, model["blocks"], source_name="style-check")
    )
    summary = _lint_summary_for_findings(annotated_findings)
    return {
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
            lint_result.get("lint_mode") if isinstance(lint_result, dict) else None
        ),
    }


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
        include_llm = str(request.args.get("include_llm", "0")).strip().lower() not in {
            "0",
            "false",
            "no",
        }
        if include_llm:
            # Fail fast on a missing file or missing linter; neither needs a model.
            playground_read_yaml(uid, project, filename)
            _interview_linter()
            return _queue_ai_job(
                "style-check",
                uid,
                {"project": project, "filename": filename},
                request_id,
            )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": _style_check_result(uid, project, filename, False),
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
    except ALDashboardUnavailable as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "unavailable", "message": str(exc)},
            },
            503,
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
        conflict = _write_source_content(
            uid, project, filename, content, post_data, request_id
        )
        if conflict is not None:
            return conflict
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "size": len(content),
                    "revision": source_revision(content),
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
#       restart on module save: prompt
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
    """Docassemble's loaded configuration, or an empty one outside a server.

    Read out of the already-imported module where possible: importing
    ``docassemble.base.config`` loads the server configuration as a side
    effect, and calls ``sys.exit`` when there is no config file to load.
    """
    module = sys.modules.get("docassemble.base.config")
    if module is None:
        try:
            module = importlib.import_module("docassemble.base.config")
        except BaseException:  # pylint: disable=broad-except
            return {}
    config = getattr(module, "daconfig", None)
    return config if isinstance(config, dict) else {}


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


# ---------------------------------------------------------------------------
# Playground module safety
#
# Saving a module is the one editor action that cannot take effect on its own.
# See editor_modules.py for why; the helpers below decide what to tell the
# developer about it and when to offer the restart.
# ---------------------------------------------------------------------------


def _module_restart_policy() -> str:
    """How the editor should handle a module change that needs a restart.

    ``prompt`` (the default) asks before restarting, ``auto`` restarts without
    asking when the developer runs the interview, and ``never`` only ever shows
    the banner and leaves the restart to the developer.
    """
    return normalize_restart_policy(_weaver_setting("restart on module save"))


def _filesystem_is_read_only() -> bool:
    """``reset.sh`` refuses to restart on a read-only file system."""
    return bool(_daconfig().get("read only file system", False))


def _celery_setup_capability() -> Dict[str, Any]:
    """Describe who may make the narrowly-scoped Celery config change."""
    is_admin = _editor_admin_check()
    config_editing_enabled = bool(app.config.get("ALLOW_CONFIGURATION_EDITING"))
    read_only = _filesystem_is_read_only()
    config_url = ""
    if is_admin:
        config_url = _resolve_endpoint("admin.config_page", "config_page")
    if not is_admin:
        reason = "Ask an administrator to add the Weaver worker module."
    elif not config_editing_enabled:
        reason = "Configuration editing is disabled on this server."
    elif read_only:
        reason = "This server's configuration file system is read-only."
    else:
        reason = None
    return {
        "is_admin": is_admin,
        "can_save": bool(is_admin and config_editing_enabled and not read_only),
        "config_url": config_url,
        "blocked_reason": reason,
    }


def _config_file_path() -> str:
    path = _daconfig().get("config file")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Docassemble did not provide the path to config.yml.")
    return path


def _write_config_source(source: str) -> None:
    """Write config source verbatim locally and to configured shared storage."""
    config_path = _config_file_path()
    from .docassemble_compat import cloud_object

    cloud = cloud_object()
    if cloud is not None:
        cloud.get_key("config.yml").set_contents_from_string(source)
    stat_result = os.stat(config_path)
    temporary_path = f"{config_path}.weaver-{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as config_file:
            config_file.write(source)
        os.chmod(temporary_path, stat_result.st_mode)
        os.replace(temporary_path, config_path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _restarting_is_allowed() -> bool:
    """Whether this server permits restarts at all.

    Docassemble sets ``ALLOW_RESTARTING`` from whether the Playground, package
    updates, or configuration editing are enabled.
    """
    try:
        return bool(app.config.get("ALLOW_RESTARTING", False))
    except Exception:
        return False


def _restart_capability() -> Dict[str, Any]:
    """Whether this server can restart itself, and why not when it cannot."""
    if _filesystem_is_read_only():
        return {
            "allowed": False,
            "reason": (
                "This server runs on a read-only file system, so it cannot "
                "restart itself. Module changes will load the next time it is "
                "redeployed."
            ),
        }
    if not _restarting_is_allowed():
        return {
            "allowed": False,
            "reason": (
                "Restarting is disabled on this server. Ask an administrator "
                "to restart it so your module changes load."
            ),
        }
    return {"allowed": True, "reason": None}


def _pending_module_changes(uid: int, project: str) -> Optional[Dict[str, Any]]:
    try:
        return read_modules_dirty(
            r,
            uid,
            project,
            server_start_time=server_start_time(),
            copy_ready=lambda state: _restart_module_copy_ready(
                {
                    "user_id": uid,
                    "project": project,
                    "module_manifest": _restart_module_manifest(
                        uid, project, pending=state
                    ),
                }
            ),
        )
    except Exception as exc:  # a broken flag must not break the editor
        log(f"ALWeaver editor: could not read pending module state: {exc!r}", "error")
        return None


def _flag_module_change(uid: int, project: str, filename: str, reason: str) -> None:
    try:
        mark_modules_dirty(
            r,
            uid,
            project,
            filename,
            server_start_time=server_start_time(),
            reason=reason,
        )
    except Exception as exc:
        log(f"ALWeaver editor: could not record pending module state: {exc!r}", "error")


def _restart_state_payload(uid: int, project: str) -> Dict[str, Any]:
    """Everything the editor needs to decide what to say about restarting."""
    pending = _pending_module_changes(uid, project)
    capability = _restart_capability()
    return {
        "project": project,
        "pending": bool(pending),
        "files": (pending or {}).get("files", []),
        "since": (pending or {}).get("since"),
        "policy": _module_restart_policy(),
        "restart_allowed": capability["allowed"],
        "restart_blocked_reason": capability["reason"],
        "disruption_seconds": list(RESTART_DISRUPTION_SECONDS),
    }


def _restart_module_manifest(
    uid: int, project: str, *, pending: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Capture the module files the next server process must publish.

    Docassemble rebuilds Playground packages during startup. The HTTP process
    can be answering requests before that copy is visible, so its start time
    and Supervisor's reset state alone do not prove a module is ready to run.
    This small manifest lets the restart poll wait for the actual package
    files without storing their source in Redis.
    """
    _area, directory = _editor_storage_directory(
        uid, project, EDITOR_SECTION_TO_STORAGE["modules"]
    )
    expected: Dict[str, str] = {}
    for filename in os.listdir(directory):
        if not MODULE_FILENAME_PATTERN.match(filename):
            continue
        with open(os.path.join(directory, filename), "rb") as module_file:
            expected[filename] = hashlib.sha256(module_file.read()).hexdigest()

    if pending is None:
        pending = _pending_module_changes(uid, project) or {}
    removed = sorted(
        {
            entry["filename"]
            for entry in pending.get("files", [])
            if entry.get("reason") in {"deleted", "renamed"}
            and entry.get("filename") not in expected
        }
    )
    return {"expected": expected, "removed": removed}


def _restart_module_copy_ready(record: Dict[str, Any]) -> bool:
    """Whether startup copied this restart's saved module state to packages."""
    manifest = record.get("module_manifest")
    if not isinstance(manifest, dict):
        # Older records and restarts unrelated to module edits retain the
        # original server-start/reset completion semantics.
        return True
    try:
        user_id = int(record["user_id"])
        project = str(record["project"])
        package_dir = module_package_directory(
            full_package_directory(), user_id, project
        )
        if not package_dir:
            return False
        expected = manifest.get("expected", {})
        removed = manifest.get("removed", [])
        if not isinstance(expected, dict) or not isinstance(removed, list):
            return False
        for filename, expected_hash in expected.items():
            if not isinstance(filename, str) or not MODULE_FILENAME_PATTERN.match(
                filename
            ):
                return False
            path = os.path.join(package_dir, filename)
            try:
                with open(path, "rb") as module_file:
                    actual_hash = hashlib.sha256(module_file.read()).hexdigest()
            except OSError:
                return False
            if actual_hash != expected_hash:
                return False
        for filename in removed:
            if not isinstance(filename, str) or not MODULE_FILENAME_PATTERN.match(
                filename
            ):
                return False
            if os.path.exists(os.path.join(package_dir, filename)):
                return False
        return True
    except (KeyError, OSError, TypeError, ValueError):
        return False


def _save_module_file(
    uid: int, project: str, filename: str, content: str
) -> Dict[str, Any]:
    """Validate, publish, and report on one module save.

    Returns the ``module`` half of the save response: whether the module is
    live already or the project now needs a restart.
    """
    validate_module_filename(filename)
    check_module_syntax(filename, content)
    outcome = publish_module_source(
        package_root=full_package_directory(),
        user_id=uid,
        project=project,
        filename=filename,
        content=content,
    )
    if outcome == "live":
        return {
            "status": "live",
            "restart_required": False,
            "message": f"{filename} is available to your interviews now.",
        }
    if outcome == "unavailable":
        _flag_module_change(uid, project, filename, "changed")
        return {
            "status": "restart_required",
            "restart_required": True,
            "message": (
                f"{filename} was saved. This server would not let the editor "
                "install it directly, so it will load when the server restarts."
            ),
        }
    _flag_module_change(uid, project, filename, "changed")
    return {
        "status": "restart_required",
        "restart_required": True,
        "message": (
            f"{filename} was saved. Because an earlier version may already be "
            "loaded, the server has to restart before your changes take effect."
        ),
    }


def _sync_module_after_write(
    uid: int, project: str, filename: str, content: str
) -> None:
    """Keep the installed copy in step with a module written elsewhere.

    Project-wide find/replace writes module files directly, and must not be
    turned into a save that can fail: a module that will not compile, or whose
    name Docassemble would skip, simply is not installed.
    """
    try:
        validate_module_filename(filename)
    except ValueError:
        return
    try:
        check_module_syntax(filename, content)
    except ModuleSyntaxError:
        _flag_module_change(uid, project, filename, "changed")
        return
    try:
        _save_module_file(uid, project, filename, content)
    except Exception as exc:
        log(f"ALWeaver editor: could not install {filename}: {exc!r}", "error")
        _flag_module_change(uid, project, filename, "changed")


def _reconcile_project_modules(uid: int, project: str) -> None:
    """Bring the installed modules back in line with the saved ones.

    Used after a bulk change that replaces files behind the editor's back — a
    GitHub pull or import — where individual saves never happened.
    """
    # Reconciling is bookkeeping on top of an import or pull that already
    # succeeded; it must never turn that into a failure.
    try:
        package_root = full_package_directory()
        _area, directory = _editor_storage_directory(
            uid, project, EDITOR_SECTION_TO_STORAGE["modules"]
        )
        saved = {
            name
            for name in os.listdir(directory)
            if MODULE_FILENAME_PATTERN.match(name)
        }
    except (Exception, SystemExit) as exc:
        log(f"ALWeaver editor: could not list saved modules: {exc!r}", "error")
        return
    for filename in sorted(saved):
        try:
            with open(os.path.join(directory, filename), encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            continue
        _sync_module_after_write(uid, project, filename, content)
    installed_dir = module_package_directory(package_root, uid, project)
    if not installed_dir or not os.path.isdir(installed_dir):
        return
    for filename in sorted(os.listdir(installed_dir)):
        if not MODULE_FILENAME_PATTERN.match(filename) or filename in saved:
            continue
        if unpublish_module(
            package_root=package_root,
            user_id=uid,
            project=project,
            filename=filename,
        ):
            _flag_module_change(uid, project, filename, "deleted")


def _rename_module_file(
    uid: int, project: str, old_filename: str, new_filename: str, directory: str
) -> Dict[str, Any]:
    """Move a module's installed copy to follow a rename.

    Dropping the old copy stops new imports of it, but a worker that already
    imported the old name still holds it, so a rename always needs a restart
    unless the module had never been installed in the first place.
    """
    package_root = full_package_directory()
    was_installed = unpublish_module(
        package_root=package_root,
        user_id=uid,
        project=project,
        filename=old_filename,
    )
    try:
        with open(os.path.join(directory, new_filename), encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        content = ""
    try:
        check_module_syntax(new_filename, content)
        published = publish_module_source(
            package_root=package_root,
            user_id=uid,
            project=project,
            filename=new_filename,
            content=content,
        )
    except ModuleSyntaxError:
        published = "unavailable"
    if not was_installed and published == "live":
        return {
            "status": "live",
            "restart_required": False,
            "message": f"{new_filename} is available to your interviews now.",
        }
    _flag_module_change(uid, project, old_filename, "renamed")
    return {
        "status": "restart_required",
        "restart_required": True,
        "message": (
            f"{old_filename} was renamed to {new_filename}. The server has to "
            "restart before interviews stop seeing the old name."
        ),
    }


def _delete_module_file(uid: int, project: str, filename: str) -> Dict[str, Any]:
    """Remove a module's installed copy after the source file is deleted."""
    was_installed = unpublish_module(
        package_root=full_package_directory(),
        user_id=uid,
        project=project,
        filename=filename,
    )
    if not was_installed:
        return {
            "status": "live",
            "restart_required": False,
            "message": f"{filename} was deleted.",
        }
    _flag_module_change(uid, project, filename, "deleted")
    return {
        "status": "restart_required",
        "restart_required": True,
        "message": (
            f"{filename} was deleted. The server has to restart before "
            "interviews that already loaded it stop using it."
        ),
    }


def _module_error_response(request_id: str, exc: ModuleSyntaxError) -> Response:
    payload = exc.to_dict()
    payload["request_id"] = request_id
    return jsonify_with_status(
        {"success": False, "request_id": request_id, "error": payload},
        400,
    )


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
            # If the server committed the exact patch but its response was
            # lost, replaying the same operations against the supplied base is
            # safe only when that candidate is byte-for-byte current source.
            if (
                isinstance(base_raw_yaml, str)
                and source_revision(base_raw_yaml) == expected_revision
            ):
                retried_content, _retried_operations = apply_range_operations(
                    base_raw_yaml, operations
                )
                if retried_content == current_content:
                    current_content = base_raw_yaml
                else:
                    conflict_response = _check_expected_source_revision(
                        post_data, current_content, request_id
                    )
                    assert conflict_response is not None
                    return conflict_response
            else:
                conflict_response = _check_expected_source_revision(
                    post_data, current_content, request_id
                )
                assert conflict_response is not None
                return conflict_response

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
        conflict = _write_source_content(
            uid, project, filename, updated_content, post_data, request_id
        )
        if conflict is not None:
            return conflict
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
        updated_content = update_metadata_documents_in_yaml(
            current_content, edited_yaml
        )
        conflict = _write_source_content(
            uid, project, filename, updated_content, post_data, request_id
        )
        if conflict is not None:
            return conflict
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


def _resolve_server_defaults() -> Dict[str, Dict[str, Any]]:
    """What each server-wide AssemblyLine setting resolves to right now.

    Several of these settings exist server-wide as well as per interview, so
    typing a value into the panel silently overrides the whole server for this
    one interview. The panel says so, which means it needs the value being
    overridden.
    """
    from .assemblyline_settings import ASSEMBLY_LINE_FALLBACKS, SERVER_DEFAULTS

    resolved: Dict[str, Dict[str, Any]] = {}
    for key, config_key in SERVER_DEFAULTS.items():
        entry: Dict[str, Any] = {
            "config_key": config_key,
            "value": "",
            "source": "assemblyline",
        }
        if config_key:
            config_value = _daconfig().get(config_key)
            if config_value not in (None, ""):
                entry["value"] = str(config_value)
                entry["source"] = "config"
        if not entry["value"]:
            entry["value"] = ASSEMBLY_LINE_FALLBACKS.get(key, "")
        resolved[key] = entry
    return resolved


LIST_TAXONOMY_FILE = "data/sources/list-taxonomy.csv"
LIST_TAXONOMY_URL = "https://taxonomy.legal"


def _list_topic_groups() -> List[Dict[str, Any]]:
    """The LIST taxonomy, grouped for a picker.

    `get_LIST_codes()` is the same reader the question-driven Weaver's topics
    screen uses, so the editor and the classic flow offer the same codes in the
    same relevance order.
    """
    from .list_taxonomy import get_LIST_codes

    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), LIST_TAXONOMY_FILE
    )
    groups: List[Dict[str, Any]] = []
    index: Dict[str, Dict[str, Any]] = {}
    for entry in get_LIST_codes(csv_path) or []:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("value") or "").strip()
        label = str(entry.get("label") or "").strip()
        group_label = str(entry.get("group") or "Other").strip() or "Other"
        if not code or not label:
            continue
        group = index.get(group_label)
        if group is None:
            group = {"label": group_label, "topics": []}
            index[group_label] = group
            groups.append(group)
        # A group's own heading code (XX-00-00-00-00) is a valid answer too, and
        # reads first because it is the broadest one in the group.
        is_heading = code.endswith("-00-00-00-00")
        topic = {"code": code, "label": label, "heading": is_heading}
        if is_heading:
            group["topics"].insert(0, topic)
            group["code"] = code
        else:
            group["topics"].append(topic)
    return groups


@app.route(f"{EDITOR_BASE_PATH}/api/list-topics", methods=["GET"])
def editor_api_list_topics() -> Response:
    """Return the LIST taxonomy so the editor can offer a topic picker."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "groups": _list_topic_groups(),
                    "docs_url": LIST_TAXONOMY_URL,
                },
            }
        )
    except Exception as exc:
        log(f"ALWeaver editor: LIST topics error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/assemblyline-settings", methods=["GET"])
def editor_api_get_assemblyline_settings() -> Response:
    """Return structured metadata and exact-name AssemblyLine variables."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        content = playground_read_yaml(uid, project, filename)
        data = read_settings(content)
        data.update(
            {
                "project": project,
                "filename": filename,
                "revision": source_revision(content),
                "server_defaults": _resolve_server_defaults(),
            }
        )
        return jsonify({"success": True, "request_id": request_id, "data": data})
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
        log(f"ALWeaver editor: AssemblyLine settings read error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/assemblyline-settings", methods=["POST"])
def editor_api_save_assemblyline_settings() -> Response:
    """Atomically update the editor-owned AssemblyLine settings block."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        expected_revision = post_data.get("expected_revision")
        submitted = post_data.get("settings")
        if not isinstance(expected_revision, str) or not expected_revision:
            raise ValueError("expected_revision is required")
        if not isinstance(submitted, dict):
            raise ValueError("settings must be an object")

        current = playground_read_yaml(uid, project, filename)
        updated = update_settings(current, submitted)
        validation = validate_candidate_source(filename=filename, raw_yaml=updated)
        if validation.blocking:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "invalid_settings_source",
                        "message": "The settings would produce an invalid interview.",
                        "details": {"diagnostics": validation.diagnostics},
                    },
                },
                422,
            )
        conflict = _write_source_content(
            uid, project, filename, updated, post_data, request_id
        )
        if conflict is not None:
            return conflict
        model = validation.model or parse_interview_yaml(updated)
        data = read_settings(updated)
        data.update(
            {
                "project": project,
                "filename": filename,
                "revision": source_revision(updated),
                "raw_yaml": updated,
                "blocks": model["blocks"],
                "metadata_blocks": model["metadata_blocks"],
                "include_blocks": model["include_blocks"],
                "default_screen_parts_blocks": model["default_screen_parts_blocks"],
                "order_blocks": model["order_blocks"],
                "metadata_raw_yaml": metadata_source_slice(updated),
            }
        )
        return jsonify({"success": True, "request_id": request_id, "data": data})
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
        log(f"ALWeaver editor: AssemblyLine settings save error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/next-steps-template/reset", methods=["POST"])
def editor_api_reset_next_steps_template() -> Response:
    """Replace a next-steps DOCX shell after making a recoverable backup."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        from .interview_generator import runtime_next_steps_template_for_form_type

        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        if post_data.get("confirm_replace") is not True:
            raise ValueError("confirm_replace must be true")
        source = playground_read_yaml(uid, project, filename)
        settings = read_settings(source)["values"]
        form_type = str(settings.get("al_form_type") or "other")
        template_match = re.search(
            r"(?m)^\s*docx template file:\s*([^\s#]+_next_steps\.docx)\s*$",
            source,
        )
        if not template_match:
            raise ValueError(
                "This interview does not reference a next-steps DOCX shell"
            )
        template_filename = os.path.basename(template_match.group(1).strip("\"'"))
        area, directory = _editor_storage_directory(
            uid, project, SECTION_TO_STORAGE["templates"]
        )
        destination = os.path.join(directory, template_filename)
        backup_filename: Optional[str] = None
        if os.path.isfile(destination):
            stem, extension = os.path.splitext(template_filename)
            candidate = f"{stem}.pre-weaver-reset{extension}"
            counter = 2
            while os.path.exists(os.path.join(directory, candidate)):
                candidate = f"{stem}.pre-weaver-reset-{counter}{extension}"
                counter += 1
            shutil.copyfile(destination, os.path.join(directory, candidate))
            backup_filename = candidate

        replacement = runtime_next_steps_template_for_form_type(form_type)
        shutil.copyfile(replacement, destination)
        area.finalize()
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "filename": template_filename,
                    "backup_filename": backup_filename,
                    "form_type": form_type,
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
        log(f"ALWeaver editor: next-steps template reset error: {exc!r}", "error")
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
    """The developer-only interview debugger is on unless explicitly disabled."""
    return _weaver_flag("runtime inspector", True)


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
                "message": "This debug session ended or expired after 30 minutes without advancing a screen. Start a new test session.",
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


def _browser_session_secret() -> Optional[str]:
    """The developer's own Docassemble decryption key, from their cookie.

    Docassemble's ``/interview`` route decrypts a session with nothing but the
    visitor's ``secret`` cookie — there is no query-string equivalent — so the
    debugger iframe can open the target session only if Weaver encrypted it
    with that same key. Creating the session with any other key makes
    Docassemble discard it and silently start a different one in the iframe,
    leaving the panels describing a session the developer is not using.

    Read per request rather than stored: this key decrypts every session the
    developer owns, and it is already in the browser making the request.
    """
    try:
        secret = request.cookies.get("secret")
    except RuntimeError:
        # Outside a request context there is no browser to keep in sync.
        return None
    return str(secret) if secret else None


def _runtime_has_no_endpoint(exc: BaseException) -> bool:
    """Recognize Docassemble's no-endpoint error, including its API wrapper."""
    seen: set[int] = set()
    while id(exc) not in seen:
        seen.add(id(exc))
        if type(exc).__name__ == "DAErrorNoEndpoint" or str(exc).startswith(
            "create_new_interview: failure to assemble interview: DAErrorNoEndpoint:"
        ):
            return True
        nested = exc.__cause__ or exc.__context__
        if nested is None:
            return False
        exc = nested
    return False


def _runtime_target_url(record: Any) -> str:
    return (
        "/interview?i="
        + quote(record.yaml_filename, safe="")
        + "&session="
        + quote(record.docassemble_session_id, safe="")
    )


def _load_owned_runtime_session(weaver_session_id: str) -> Any:
    return get_live_runtime_record(r, weaver_session_id, _current_user_id())


def _schedule_runtime_cleanup(record: Any) -> None:
    schedule_runtime_cleanup(r, record)


@app.before_request
def _cleanup_idle_debug_sessions() -> None:
    if not request.path.startswith(EDITOR_BASE_PATH) or not _editor_auth_check():
        return
    try:
        # One bounded sweep per minute across all web processes, including on
        # servers without Weaver's Celery module. Never keep an idle record alive.
        if r.set("da:alweaver:editor:runtime-housekeeping", "1", nx=True, ex=60):
            cleanup_due_runtime_sessions(r)
    except Exception as exc:
        log(f"Debug session cleanup deferred: {type(exc).__name__}", "error")


@app.route(f"{EDITOR_BASE_PATH}/api/runtime/sessions/cleanup", methods=["POST"])
def editor_api_runtime_cleanup_sessions() -> Response:
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _runtime_inspector_enabled():
        return _runtime_disabled(request_id)
    try:
        uid = _current_user_id()
        with runtime_session_lock(r, f"owner:{uid}"):
            result = cleanup_owned_runtime_sessions(r, uid)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"deleted": result["deleted"]},
            }
        )
    except Exception as exc:
        return _runtime_operation_failed(request_id, "cleanup", exc)


@app.route(f"{EDITOR_BASE_PATH}/api/runtime/sessions", methods=["GET", "POST"])
def editor_api_runtime_create_session() -> Response:
    """Create a separate Docassemble target session for runtime inspection."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _runtime_inspector_enabled():
        return _runtime_disabled(request_id)
    try:
        uid = _current_user_id()
        post_data = (
            dict(request.args)
            if request.method == "GET"
            else request.get_json(silent=True)
        )
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
        with runtime_session_lock(r, f"owner:{uid}"):
            current = cleanup_owned_runtime_sessions(r, uid)["session"]
            if request.method == "GET":
                if current:
                    _schedule_runtime_cleanup(current)
                matching = (
                    current
                    and current.project == project
                    and current.filename == filename
                )
                return jsonify(
                    {
                        "success": True,
                        "request_id": request_id,
                        "data": {
                            "session": (
                                current.public_dict(_runtime_target_url(current))
                                if matching
                                else None
                            )
                        },
                    }
                )
            # Starting a replacement ends every previous debug interview for
            # this developer. Normal saved interviews are never selected here.
            cleanup_owned_runtime_sessions(r, uid, keep_latest=False)
            return _create_runtime_session_response(
                uid, project, filename, purpose, url_args, request_id
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
        return _runtime_operation_failed(request_id, "session", exc)


def _create_runtime_session_response(
    uid: int, project: str, filename: str, purpose: str, url_args: Any, request_id: str
) -> Response:
    try:
        yaml_filename = playground_yaml_filename(uid, project, filename)
        # "Run the interview" reaches Docassemble with cache=0, which makes the
        # server bump this index itself. Starting a session through the API
        # does not, so without this the inspector can run against a parse from
        # before the developer's last save.
        bump_interview_source_index(yaml_filename)
        browser_secret = _browser_session_secret()
        target = create_target_session(
            yaml_filename,
            secret=browser_secret,
            url_args=url_args or None,
        )
        record = create_runtime_record(
            weaver_session_id=str(uuid.uuid4()),
            owner_user_id=uid,
            project=project,
            filename=filename,
            yaml_filename=yaml_filename,
            target=target,
            purpose=purpose,
            persist_secret=browser_secret is None,
        )
        store_runtime_record(r, record)
        refresh_runtime_progress(r, record)
        r.set(
            "da:alweaver:editor:runtime-session:owner:" + str(uid),
            record.weaver_session_id,
        )
        _schedule_runtime_cleanup(record)
        response = jsonify_with_status(
            {
                "success": True,
                "request_id": request_id,
                "data": record.public_dict(_runtime_target_url(record)),
            },
            201,
        )
        if browser_secret is None and target.secret:
            # A fresh editor-only browser may not yet have Docassemble's
            # session-decryption cookie. The target session was encrypted
            # with this generated key, so install the same HttpOnly cookie
            # Docassemble itself sets on its next normal interview response.
            response.set_cookie(
                "secret",
                target.secret,
                httponly=True,
                secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
                samesite=current_app.config.get("SESSION_COOKIE_SAMESITE"),
            )
        return response
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
        log(
            "ALWeaver editor: runtime session creation failed: "
            f"{exc!r}\n{traceback.format_exc()}",
            "error",
        )
        if _runtime_has_no_endpoint(exc):
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "validation_error",
                        "code": "runtime_no_endpoint",
                        "message": (
                            f"Docassemble reached the end of {filename} without "
                            "a screen to display. If this is an include file, "
                            "start debugging the main interview that includes it. "
                            "Standalone interviews need a mandatory flow and "
                            "an ending screen."
                        ),
                    },
                },
                422,
            )
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
    try:
        record = _load_owned_runtime_session(weaver_session_id)
    except Exception as exc:
        return _runtime_operation_failed(request_id, "session", exc)
    if record is None:
        return _runtime_not_found(request_id)
    if request.method == "DELETE":
        try:
            with runtime_session_lock(r, weaver_session_id):
                close_runtime_session(r, record)
        except Exception as exc:
            return _runtime_operation_failed(request_id, "delete", exc)
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
    f"{EDITOR_BASE_PATH}/api/runtime/sessions/<weaver_session_id>/snapshot",
    methods=["GET"],
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
    try:
        record = _load_owned_runtime_session(weaver_session_id)
    except Exception as exc:
        return _runtime_operation_failed(request_id, "session", exc)
    if record is None:
        return _runtime_not_found(request_id)
    try:
        target = record.target(_browser_session_secret())
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
            seeded_names = {str(name) for name in variables}
            deleted_names = {str(name) for name in delete}
            record.seeded_variables = sorted(
                (set(record.seeded_variables) | seeded_names) - deleted_names
            )
            append_runtime_event(
                r,
                record,
                "scenario_applied",
                set_count=len(variables),
                delete_count=len(delete),
                seeded_variables=sorted(seeded_names),
                deleted_variables=sorted(deleted_names),
            )
            return jsonify(
                {
                    "success": True,
                    "request_id": request_id,
                    "data": {"updated": True},
                }
            )

        # Get the question first: Docassemble may assemble it and update the
        # session. This is one observation, not an atomic database snapshot.
        snapshot = request.path.endswith("/snapshot")
        question_data = {"question": get_target_question(target)} if snapshot else {}
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
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    **question_data,
                    "variables": variables,
                    "seeded_variables": list(record.seeded_variables),
                    "includes_internal": include_internal,
                    "fact_source": "observed_runtime",
                },
            }
        )
    except (ValueError, yaml.YAMLError) as exc:
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
    try:
        record = _load_owned_runtime_session(weaver_session_id)
    except Exception as exc:
        return _runtime_operation_failed(request_id, "session", exc)
    if record is None:
        return _runtime_not_found(request_id)
    try:
        question = get_target_question(record.target(_browser_session_secret()))
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
    try:
        record = _load_owned_runtime_session(weaver_session_id)
    except Exception as exc:
        return _runtime_operation_failed(request_id, "session", exc)
    if record is None:
        return _runtime_not_found(request_id)
    try:
        go_back_target_session(record.target(_browser_session_secret()))
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
    try:
        record = _load_owned_runtime_session(weaver_session_id)
    except Exception as exc:
        return _runtime_operation_failed(request_id, "session", exc)
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
            record.target(_browser_session_secret()),
            action_name,
            arguments=arguments,
            read_only=True,
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
        return self._record.target(_browser_session_secret())

    def start_session(self) -> Dict[str, Any]:
        playground_read_yaml(self._user_id, self._project, self._filename)
        yaml_filename = playground_yaml_filename(
            self._user_id, self._project, self._filename
        )
        browser_secret = _browser_session_secret()
        target = create_target_session(
            yaml_filename, secret=browser_secret, url_args=None
        )
        record = create_runtime_record(
            weaver_session_id=str(uuid.uuid4()),
            owner_user_id=self._user_id,
            project=self._project,
            filename=self._filename,
            yaml_filename=yaml_filename,
            target=target,
            purpose="inspection",
            persist_secret=browser_secret is None,
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
    read_only: bool = False,
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
            read_only=read_only,
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
        read_only = post_data.get("read_only", False)
        if not isinstance(read_only, bool):
            raise ValueError("read_only must be a boolean")

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
                    "read_only": read_only,
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
        dependency_conflict = _file_dependency_conflict(
            uid, project, "interview", old_filename, "rename", request_id
        )
        if dependency_conflict is not None:
            return dependency_conflict
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
        dependency_conflict = _file_dependency_conflict(
            uid, project, "interview", filename, "delete", request_id
        )
        if dependency_conflict is not None:
            return dependency_conflict
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


@app.route(f"{EDITOR_BASE_PATH}/api/template/revise", methods=["POST"])
def editor_api_revise_template() -> Response:
    """Replace a template only when the confirmed original revision matches."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.form.get("project"))
        filename = _normalize_storage_filename(request.form.get("filename"))
        expected_revision = request.form.get("expected_revision")
        if not isinstance(expected_revision, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_revision
        ):
            raise ValueError("expected_revision must be a SHA-256 revision")
        if not parse_bool(request.form.get("confirm_replace"), default=False):
            raise ValueError("Explicit confirmation is required to replace a template")
        if os.path.splitext(filename.lower())[1] not in {".pdf", ".docx"}:
            raise ValueError("Only PDF and DOCX templates can be revised here")
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise ValueError("A replacement template file is required")
        if _normalize_storage_filename(upload.filename) != filename:
            raise ValueError(
                "The replacement filename must match the existing template"
            )

        storage_section = EDITOR_SECTION_TO_STORAGE["templates"]
        area, directory = _editor_storage_directory(uid, project, storage_section)
        path = os.path.join(directory, filename)
        temporary_path: Optional[str] = None
        backup_path: Optional[str] = None
        with _source_file_lock(uid, project, filename, "templates"):
            if not os.path.isfile(path) or os.path.islink(path):
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "not_found",
                            "code": "template_not_found",
                            "message": "The template to revise was not found.",
                        },
                    },
                    404,
                )
            if os.path.getsize(path) > MAX_TEMPLATE_REPLACEMENT_BYTES:
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "file_too_large",
                            "code": "file_too_large",
                            "message": "The existing template is too large to replace safely.",
                        },
                    },
                    413,
                )
            with open(path, "rb") as fh:
                original_bytes = fh.read()
            current_revision = hashlib.sha256(original_bytes).hexdigest()
            if not hmac.compare_digest(expected_revision, current_revision):
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "revision_conflict",
                            "code": "revision_conflict",
                            "message": (
                                "The template changed since you confirmed the "
                                "replacement. Reload the file list before retrying."
                            ),
                            "expected_revision": expected_revision,
                            "current_revision": current_revision,
                        },
                    },
                    409,
                )
            replacement_bytes = upload.stream.read(MAX_TEMPLATE_REPLACEMENT_BYTES + 1)
            if len(replacement_bytes) > MAX_TEMPLATE_REPLACEMENT_BYTES:
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "file_too_large",
                            "code": "file_too_large",
                            "message": "The replacement template exceeds the 50 MiB limit.",
                        },
                    },
                    413,
                )
            if not replacement_bytes:
                raise ValueError("The replacement template file is empty")
            # Validate the bounded upload before creating a backup or changing
            # the referenced file. A malformed replacement must not displace
            # the last known-good template.
            try:
                validate_document_content(filename, replacement_bytes)
            except ValueError as exc:
                raise ValueError(str(exc)) from None
            extension = os.path.splitext(filename)[1]
            backup_filename = (
                f"{os.path.splitext(filename)[0]}.alweaver-backup-"
                f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-"
                f"{current_revision[:8]}{extension}"
            )
            backup_path = os.path.join(directory, backup_filename)
            if os.path.exists(backup_path):
                backup_filename = (
                    f"{os.path.splitext(filename)[0]}.alweaver-backup-"
                    f"{uuid.uuid4().hex[:12]}-{current_revision[:8]}{extension}"
                )
                backup_path = os.path.join(directory, backup_filename)
            backup_temporary_path: Optional[str] = None
            replaced = False
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=directory,
                    prefix=".alweaver-template-backup-",
                    delete=False,
                ) as backup:
                    backup_temporary_path = backup.name
                    backup.write(original_bytes)
                    backup.flush()
                    os.fsync(backup.fileno())
                os.replace(backup_temporary_path, backup_path)
                backup_temporary_path = None
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=directory, prefix=".alweaver-template-", delete=False
                ) as temporary:
                    temporary_path = temporary.name
                    temporary.write(replacement_bytes)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_path, path)
                temporary_path = None
                replaced = True
                try:
                    area.finalize()
                except Exception:
                    # Keep the last known-good template if storage finalization
                    # fails after the atomic rename.
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        dir=directory,
                        prefix=".alweaver-template-rollback-",
                        delete=False,
                    ) as backup:
                        temporary_path = backup.name
                        backup.write(original_bytes)
                        backup.flush()
                        os.fsync(backup.fileno())
                    os.replace(temporary_path, path)
                    temporary_path = None
                    replaced = False
                    if backup_path and os.path.exists(backup_path):
                        os.remove(backup_path)
                    backup_path = None
                    try:
                        area.finalize()
                    except Exception:
                        log(
                            "ALWeaver editor: template replacement rollback finalization failed",
                            "error",
                        )
                    raise
            finally:
                if temporary_path and os.path.exists(temporary_path):
                    os.remove(temporary_path)
                if backup_temporary_path and os.path.exists(backup_temporary_path):
                    os.remove(backup_temporary_path)
                if not replaced and backup_path and os.path.exists(backup_path):
                    os.remove(backup_path)

        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "original_revision": current_revision,
                    "revision": hashlib.sha256(replacement_bytes).hexdigest(),
                    "backup_filename": backup_filename,
                    "backup_revision": current_revision,
                    "size": len(replacement_bytes),
                },
            }
        )
    except SourceWriteLockUnavailable as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "source_lock_unavailable",
                    "code": "source_lock_unavailable",
                    "message": str(exc),
                },
            },
            503,
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
        log(f"ALWeaver editor: template replacement failed: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "message": "The template could not be replaced.",
                },
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
        requested_filename = _normalize_renamed_storage_filename(
            post_data.get("new_filename"), old_filename
        )
        new_filename = safe_project_filename(requested_filename, default_stem=section)
        if old_filename == new_filename:
            raise ValueError("New filename must be different")
        if section == "modules":
            validate_module_filename(new_filename)
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        area, directory = _editor_storage_directory(uid, project, storage_section)
        try:
            with ExitStack() as locks:
                for lock_filename in sorted({old_filename, new_filename}):
                    locks.enter_context(
                        _source_file_lock(uid, project, lock_filename, section)
                    )
                old_path = os.path.join(directory, old_filename)
                if not os.path.isfile(old_path) or os.path.islink(old_path):
                    raise FileNotFoundError(f"{old_filename} not found")
                with open(old_path, "rb") as fh:
                    current_content = fh.read()
                conflict = _section_file_revision_conflict(
                    post_data, current_content, request_id
                )
                if conflict is not None:
                    return conflict
                dependency_conflict = _file_dependency_conflict(
                    uid, project, section, old_filename, "rename", request_id
                )
                if dependency_conflict is not None:
                    return dependency_conflict
                rename_saved_file(area, directory, old_filename, new_filename)
        except SourceWriteLockUnavailable as exc:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "source_lock_unavailable",
                        "code": "source_lock_unavailable",
                        "message": str(exc),
                    },
                },
                503,
            )
        data: Dict[str, Any] = {
            "project": project,
            "section": section,
            "filename": new_filename,
            "old_filename": old_filename,
            # The author typed a name the Playground could not have found, so
            # they need to hear which name the file actually has now.
            "renamed_files": (
                []
                if new_filename == requested_filename
                else [
                    {
                        "from": requested_filename,
                        "to": new_filename,
                        "reason": "unsupported_characters",
                        "message": _renamed_file_message(
                            requested_filename, new_filename, "unsupported_characters"
                        ),
                    }
                ]
            ),
        }
        if section == "modules":
            data["module"] = _rename_module_file(
                uid, project, old_filename, new_filename, directory
            )
            data["restart_state"] = _restart_state_payload(uid, project)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": data,
            }
        )
    except ModuleSyntaxError as exc:
        return _module_error_response(request_id, exc)
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
        try:
            with _source_file_lock(uid, project, filename, section):
                path = os.path.join(directory, filename)
                if not os.path.isfile(path) or os.path.islink(path):
                    raise FileNotFoundError(f"{filename} not found")
                with open(path, "rb") as fh:
                    current_content = fh.read()
                conflict = _section_file_revision_conflict(
                    post_data, current_content, request_id
                )
                if conflict is not None:
                    return conflict
                dependency_conflict = _file_dependency_conflict(
                    uid, project, section, filename, "delete", request_id
                )
                if dependency_conflict is not None:
                    return dependency_conflict
                delete_saved_file(area, directory, filename)
        except SourceWriteLockUnavailable as exc:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "source_lock_unavailable",
                        "code": "source_lock_unavailable",
                        "message": str(exc),
                    },
                },
                503,
            )
        data: Dict[str, Any] = {
            "project": project,
            "section": section,
            "filename": filename,
        }
        if section == "modules":
            data["module"] = _delete_module_file(uid, project, filename)
            data["restart_state"] = _restart_state_payload(uid, project)
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
        log(f"ALWeaver editor: delete section-file error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/server/celery-config", methods=["POST"])
def editor_api_add_celery_config() -> Response:
    """Add Weaver's Celery module without reformatting the server config."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    if not _editor_admin_check():
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "authorization_error",
                    "message": "Only an administrator may update config.yml.",
                },
            },
            403,
        )
    setup = _celery_setup_capability()
    if not setup["can_save"]:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "configuration_not_editable",
                    "message": setup["blocked_reason"],
                },
            },
            409,
        )
    restart_capability = _restart_capability()
    if not restart_capability["allowed"]:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "restart_not_allowed",
                    "message": restart_capability["reason"],
                },
            },
            409,
        )
    try:
        config_path = _config_file_path()
        with open(config_path, "r", encoding="utf-8") as config_file:
            original = config_file.read()
        updated, changed = add_celery_module_to_config_yaml(original)
        if changed:
            _write_config_source(updated)
        # Celery discovers task modules on process start.  Restart only after
        # the precise config change is durable, just as Docassemble's own
        # configuration workflow does.
        restart_docassemble()
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "changed": changed,
                    "required_module": CELERY_MODULE,
                    "restarting": True,
                },
            }
        )
    except (OSError, ValueError) as exc:
        log(f"ALWeaver editor: Celery configuration update error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "configuration_error", "message": str(exc)},
            },
            500,
        )
    except Exception as exc:
        log(f"ALWeaver editor: unexpected Celery configuration error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "configuration_error",
                    "message": "Unable to update the Celery configuration.",
                },
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/server/restart-state", methods=["GET"])
def editor_api_restart_state() -> Response:
    """Report whether this project has module changes awaiting a restart."""
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
                "data": _restart_state_payload(uid, project),
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
        log(f"ALWeaver editor: restart-state error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/server/restart", methods=["POST"])
def editor_api_restart_server() -> Response:
    """Restart every Docassemble process so module changes load.

    The polling record is written before the restart is triggered, exactly as
    Docassemble's own ``/restart_ajax`` does it: ``restart_all()`` takes down
    the worker handling this request, so anything that has to survive the call
    has to be in Redis before it.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    capability = _restart_capability()
    if not capability["allowed"]:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "validation_error",
                    "code": "restart_not_allowed",
                    "message": capability["reason"],
                },
            },
            409,
        )
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        module_manifest = _restart_module_manifest(uid, project)
        task_id = uuid.uuid4().hex
        pipe = r.pipeline()
        pipe.set(
            restart_status_key(task_id),
            json.dumps(
                {
                    "server_start_time": server_start_time(),
                    "user_id": uid,
                    "project": project,
                    "module_manifest": module_manifest,
                }
            ),
        )
        pipe.expire(restart_status_key(task_id), 3600)
        pipe.execute()
        restart_docassemble()
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "task_id": task_id,
                    "project": project,
                    "disruption_seconds": list(RESTART_DISRUPTION_SECONDS),
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
        log(f"ALWeaver editor: restart failed: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "code": "restart_failed",
                    "message": "The server could not be restarted.",
                },
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/server/restart-status", methods=["GET"])
def editor_api_restart_status() -> Response:
    """Poll a restart started by POST /api/server/restart.

    Reads the same Redis record shape as Docassemble's ``check_restart_status``
    so the two agree about what "finished" means: this process booted after the
    restart was requested, and supervisor's reset program is no longer running.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    task_id = str(request.args.get("task_id") or "").strip()
    if not task_id:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": "task_id is required"},
            },
            400,
        )
    try:
        raw = r.get(restart_status_key(task_id))
        if raw is None:
            return jsonify(
                {
                    "success": True,
                    "request_id": request_id,
                    "data": {"task_id": task_id, "status": "unknown"},
                }
            )
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        record = json.loads(raw)
        requested_at = float(record.get("server_start_time") or 0)
        working = (
            server_start_time() <= requested_at
            or reset_process_is_running()
            or not _restart_module_copy_ready(record)
        )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "task_id": task_id,
                    "status": "working" if working else "completed",
                },
            }
        )
    except Exception as exc:
        log(f"ALWeaver editor: restart-status error: {exc!r}", "error")
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
        allow_empty_question = post_data.get("allow_empty_question") is True
        _validate_block_yaml_payload(
            new_yaml, allow_empty_question=allow_empty_question
        )

        current_content = playground_read_yaml(uid, project, filename)
        _validate_template_against_file(
            current_content, new_yaml, current_block_id=block_id
        )
        current_model = parse_interview_yaml(current_content)
        original_block = next(
            (block for block in current_model["blocks"] if block["id"] == block_id),
            None,
        )
        # Dropping `question:` from a question block leaves fields with no
        # screen to sit on. Turning the block into code, objects, a template
        # and so on is a legitimate edit, so only an untyped result is refused.
        if original_block and original_block["type"] == "question":
            new_blocks = parse_interview_yaml(new_yaml)["blocks"]
            if new_blocks and new_blocks[0]["type"] == "other":
                raise ValueError(
                    "Question text is required before saving a question block"
                )
        saved_index = original_block["index"] if original_block else None
        updated_content = update_block_in_yaml(
            current_content,
            block_id,
            new_yaml,
            preserve_unchanged_annotations=(
                str(post_data.get("edit_mode") or "").strip().lower() == "graphical"
            ),
            parsed_model=current_model,
        )
        model = parse_interview_yaml(updated_content)
        conflict = _write_source_content(
            uid,
            project,
            filename,
            updated_content,
            post_data,
            request_id,
            parsed_model=model,
        )
        if conflict is not None:
            return conflict

        # A block without an `id:` is addressed by a content hash, which the
        # edit just changed; find it again by position so it stays selected.
        saved_block_id = next(
            (
                block["id"]
                for block in model["blocks"]
                if saved_index is not None and block["index"] == saved_index
            ),
            block_id,
        )
        order_step_map, order_steps = _order_steps_from_model(model)
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
                    "revision": source_revision(updated_content),
                    "saved_block_id": saved_block_id,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        error_type = (
            "empty_question"
            if isinstance(exc, EmptyQuestionError)
            else "validation_error"
        )
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": error_type, "message": str(exc)},
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
        current_block = next(
            (
                item
                for item in parse_interview_yaml(current_content)["blocks"]
                if str(item.get("id") or "") == block_id
            ),
            None,
        )
        if current_block and current_block.get("type") == "template":
            template_name = str(
                ((current_block.get("data") or {}).get("template") or "")
            ).strip()
            references = _template_references(
                current_content, template_name, exclude_block_id=block_id
            )
            if references:
                raise ValueError(
                    f"Cannot delete template {template_name!r}; it is used by: "
                    + ", ".join(references)
                )
        updated_content = delete_block_from_yaml(current_content, block_id)
        conflict = _write_source_content(
            uid, project, filename, updated_content, post_data, request_id
        )
        if conflict is not None:
            return conflict

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
        conflict = _write_source_content(
            uid, project, filename, updated_content, post_data, request_id
        )
        if conflict is not None:
            return conflict

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
        conflict = _write_source_content(
            uid, project, filename, updated_content, post_data, request_id
        )
        if conflict is not None:
            return conflict

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
        conflict = _write_source_content(
            uid, project, filename, updated_content, post_data, request_id
        )
        if conflict is not None:
            return conflict

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
        _validate_block_yaml_payload(block_yaml, allow_empty_question=True)

        current_content = playground_read_yaml(uid, project, filename)
        _validate_template_against_file(current_content, block_yaml)
        block_text = block_yaml.strip("\r\n")
        updated_content = insert_block_in_yaml(
            current_content, block_text, insert_after_id
        )
        conflict = _write_source_content(
            uid, project, filename, updated_content, post_data, request_id
        )
        if conflict is not None:
            return conflict

        updated_model = parse_interview_yaml(updated_content)
        inserted_block_id: Optional[str] = None
        id_match = re.search(r"(?m)^id:\s*['\"]?([^'\"\n]+)['\"]?\s*$", block_text)
        if id_match:
            inserted_block_id = id_match.group(1).strip()
        else:
            # A block with no id of its own — a comment, or a blank new block —
            # is identified by where it landed, not by being last in the file.
            inserted_block_id = inserted_block_id_by_position(
                updated_model["blocks"], insert_after_id
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
                    "revision": source_revision(updated_content),
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


QUESTION_LIBRARY_DOCS_URL = (
    "https://assemblyline.suffolklitlab.org/docs/authoring/customizing_interview"
)


def _question_library_catalog(content: str) -> List[Dict[str, Any]]:
    """The AssemblyLine questions on offer for the objects one file declares.

    The Weaver copies these questions in when it first writes an interview, but
    an object declared later -- in the editor, a week on -- needs them just as
    much. The catalog is built from the file itself so the questions name the
    author's own objects rather than AssemblyLine's generic ``x``.
    """
    model = parse_interview_yaml(content)
    objects: List[Dict[str, Any]] = []
    existing_ids: List[str] = []
    for block in model["blocks"]:
        block_id = str(block.get("id") or "").strip()
        if block_id:
            existing_ids.append(block_id)
        # Only live `objects:` blocks carry `editor_objects`, so a commented-out
        # declaration offers nothing — while its id still counts as taken.
        objects.extend(block.get("editor_objects") or [])
    return library_catalog(
        objects,
        references=attribute_references(content),
        existing_ids=existing_ids,
    )


@app.route(f"{EDITOR_BASE_PATH}/api/question-library", methods=["GET"])
def editor_api_question_library() -> Response:
    """List the AssemblyLine baseline questions this file's objects can use."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        content = playground_read_yaml(uid, project, filename)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "filename": filename,
                    "objects": _question_library_catalog(content),
                    "docs_url": QUESTION_LIBRARY_DOCS_URL,
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
        log(f"ALWeaver editor: question library error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/question-library/insert", methods=["POST"])
def editor_api_question_library_insert() -> Response:
    """Copy the chosen baseline questions into a YAML file.

    The blocks are rendered here rather than taken from the browser: the client
    picks an object and a question kind, and the same template the Weaver uses
    writes the YAML.
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
        requested = post_data.get("questions")
        if not isinstance(requested, list) or not requested:
            raise ValueError("questions must be a non-empty list")

        content = playground_read_yaml(uid, project, filename)
        catalog = _question_library_catalog(content)
        offered = {
            (entry["var"], question["kind"]): question
            for entry in catalog
            for question in entry["questions"]
        }
        # Insert in the catalog's own order — the gather flow before the
        # questions about each person — rather than in whatever order the
        # checkboxes were ticked. Keying by position also drops a question
        # asked for twice, which would otherwise be two blocks with one id.
        order = {key: position for position, key in enumerate(offered)}
        chosen: Dict[int, Dict[str, Any]] = {}
        for item in requested:
            if not isinstance(item, dict):
                raise ValueError("each question must be an object")
            key = (
                str(item.get("var") or "").strip(),
                str(item.get("kind") or "").strip(),
            )
            question = offered.get(key)
            if question is None:
                raise ValueError(
                    f"There is no {key[1]!r} question available for {key[0]!r}"
                )
            chosen[order[key]] = question

        inserted_ids: List[str] = []
        skipped_ids: List[str] = []
        updated_content = content
        anchor = insert_after_id
        for _position, question in sorted(chosen.items()):
            if question["present"]:
                # Already copied in once. Inserting it again would give the file
                # two blocks with one id, and docassemble would use only one.
                skipped_ids.append(question["question_id"])
                continue
            block_text = str(question["yaml"]).strip("\r\n")
            _validate_block_yaml_payload(block_text)
            updated_content = insert_block_in_yaml(updated_content, block_text, anchor)
            anchor = question["question_id"]
            inserted_ids.append(question["question_id"])

        if inserted_ids:
            conflict = _write_source_content(
                uid, project, filename, updated_content, post_data, request_id
            )
            if conflict is not None:
                return conflict

        data = _build_file_response_data(
            updated_content,
            project,
            filename,
            inserted_block_id=inserted_ids[0] if inserted_ids else None,
        )
        # The revision the file now has, so the next metadata save is not
        # rejected as a conflict with a write the editor made itself.
        data["revision"] = source_revision(updated_content)
        data["inserted_block_ids"] = inserted_ids
        data["skipped_block_ids"] = skipped_ids
        return jsonify({"success": True, "request_id": request_id, "data": data})
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
        log(f"ALWeaver editor: question library insert error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


# The `.using()` parameters the "how many people?" control owns, and what each
# one has to be. Anything else in a declaration is the author's own writing,
# and this endpoint does not compose it.
_PEOPLE_LIST_PARAMS: Dict[str, type] = {
    "there_are_any": bool,
    "ask_number": bool,
    "target_number": int,
}


def _person_declaration(class_name: str, using_args: str) -> str:
    """Compose the ``objects:`` expression for a new person or list of people.

    The expression is rebuilt from the parameters rather than passed through:
    what arrives is a quantity choice from a radio group, and an ``objects:``
    entry is a Python expression the interview evaluates.
    """
    if class_name not in PERSON_LIST_CLASSES + PERSON_CLASSES:
        raise ValueError(
            "The question library declares people: "
            f"{', '.join(PERSON_LIST_CLASSES + PERSON_CLASSES)}"
        )
    text = str(using_args or "").strip()
    if not text:
        return class_name
    if class_name not in PERSON_LIST_CLASSES:
        raise ValueError(f"{class_name} does not take how-many parameters")
    try:
        call = ast.parse(f"_f({text})", mode="eval").body
    except SyntaxError as exc:
        raise ValueError(f"Could not read the how-many parameters: {exc}") from exc
    if not isinstance(call, ast.Call) or call.args:
        raise ValueError("The how-many parameters must be named, e.g. ask_number=True")
    parameters: List[str] = []
    for keyword in call.keywords:
        expected = _PEOPLE_LIST_PARAMS.get(str(keyword.arg or ""))
        if expected is None:
            raise ValueError(f"{keyword.arg!r} is not a how-many parameter")
        try:
            value = ast.literal_eval(keyword.value)
        except ValueError as exc:
            raise ValueError(f"{keyword.arg} must be a plain value") from exc
        if expected is bool:
            if not isinstance(value, bool):
                raise ValueError(f"{keyword.arg} must be True or False")
        elif not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{keyword.arg} must be a whole number")
        parameters.append(f"{keyword.arg}={value!r}")
    if not parameters:
        return class_name
    return f"{class_name}.using({', '.join(parameters)})"


def _question_library_object_target(
    model: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    """Where a new person declaration should go: an existing block, or after one.

    A generated interview has several ``objects:`` blocks -- the people, the
    ALDocuments, the bundles -- so the people go in the block that already
    declares people. Failing that a block of their own is written, after the
    last block of the file's preamble, rather than dropping an `ALPeopleList`
    among the documents.

    Returns:
        ``(block to extend, block to insert after)``, at most one of which is set.
    """
    head_indices = set(
        list(model.get("metadata_blocks") or [])
        + list(model.get("include_blocks") or [])
        + list(model.get("default_screen_parts_blocks") or [])
    )
    anchor: Optional[str] = None
    for block in model.get("blocks", []):
        data = block.get("data")
        if not isinstance(data, dict) or data.get("_commented"):
            continue
        is_objects = block.get("type") == BLOCK_TYPE_OBJECTS
        if is_objects or block.get("index") in head_indices:
            anchor = str(block.get("id") or "").strip() or anchor
        if not is_objects:
            continue
        for row in block.get("editor_objects") or []:
            if str(row.get("class_name") or "") in PERSON_LIST_CLASSES + PERSON_CLASSES:
                return str(block.get("id") or "").strip(), None
    return None, anchor


@app.route(f"{EDITOR_BASE_PATH}/api/question-library/object", methods=["POST"])
def editor_api_question_library_object() -> Response:
    """Declare a new list of people, or one person, in this file.

    The questions are only worth offering for objects the interview has, so the
    picker can add one: declaring `witnesses` is the step that was missing
    between wanting AssemblyLine's questions about witnesses and getting them.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        name = str(post_data.get("name") or "").strip()
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ValueError(
                "A variable name has to be a word Python can use: letters, "
                "digits and underscores, not starting with a digit"
            )
        if name in generator_constants.AL_MANAGED_OBJECTS:
            raise ValueError(
                f"AssemblyLine declares and manages {name} itself, so declaring "
                "it here would break it"
            )
        expression = _person_declaration(
            str(post_data.get("class_name") or "").strip(),
            str(post_data.get("using_args") or ""),
        )

        content = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(content)
        for block in model["blocks"]:
            for row in block.get("editor_objects") or []:
                if str(row.get("name") or "").strip() == name:
                    raise ValueError(f"{name} is already declared in this file")

        extend_block_id, insert_after_id = _question_library_object_target(model)
        updated_content: Optional[str] = None
        if extend_block_id:
            try:
                updated_content = add_object_declaration(
                    content, extend_block_id, name, expression
                )
            except ValueError:
                # The people are declared in a shape a single line cannot join
                # -- `objects: {users: ALPeopleList}`, say. Rewriting that block
                # into another style is an edit nobody asked for, so the new
                # person gets a block of their own next to it.
                updated_content = None
        if updated_content is None:
            block_text = f"objects:\n  - {name}: {expression}"
            _validate_block_yaml_payload(block_text)
            updated_content = insert_block_in_yaml(
                content, block_text, insert_after_id or extend_block_id
            )
        conflict = _write_source_content(
            uid, project, filename, updated_content, post_data, request_id
        )
        if conflict is not None:
            return conflict

        data = _build_file_response_data(updated_content, project, filename)
        data["revision"] = source_revision(updated_content)
        data["declared"] = {"var": name, "expression": expression}
        data["objects"] = _question_library_catalog(updated_content)
        return jsonify({"success": True, "request_id": request_id, "data": data})
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
        log(f"ALWeaver editor: question library object error: {exc!r}", "error")
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

        validate_order_steps(steps)
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
            if target_block is None:
                raise ValueError(
                    "The selected order block no longer exists. Reload the file."
                )
        elif model["order_blocks"]:
            target_block = next(
                block
                for block in model["blocks"]
                if block["index"] == model["order_blocks"][0]
            )

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
                current_content,
                target_block["id"],
                order_yaml,
                preserve_unchanged_annotations=True,
            )
        else:
            # Append a new mandatory code block
            indented_body = "\n".join(f"  {line}" for line in code_body.splitlines())
            order_yaml = (
                f"id: interview_order\nmandatory: True\ncode: |\n{indented_body}\n"
            )
            updated = current_content.rstrip() + "\n---\n" + order_yaml + "\n"

        conflict = _write_source_content(
            uid, project, filename, updated, post_data, request_id
        )
        if conflict is not None:
            return conflict
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
                    "revision": source_revision(updated),
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


def _ai_request_context(
    uid: int, post_data: Dict[str, Any], require_block: bool
) -> Tuple[Any, str, str, str, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Cheap checks shared by the request path and the worker.

    The route runs these before queueing so bad input still gets a
    descriptive 400/404 instead of occupying the user's one AI job slot.
    """
    llms = _load_llms_module()
    if llms is None:
        raise ValueError("docassemble.ALToolbox.llms is not available")

    project = _normalize_project(post_data.get("project"))
    filename = _normalize_filename(post_data.get("filename"))
    block_id = str(post_data.get("block_id") or "").strip()
    if require_block and not block_id:
        raise ValueError("block_id is required")

    raw_yaml = playground_read_yaml(uid, project, filename)
    model = parse_interview_yaml(raw_yaml)
    blocks = model.get("blocks") or []
    block = _question_block_by_id(blocks, block_id) if block_id else None
    if require_block and not block:
        raise ValueError("block_id must refer to a question block")
    return llms, project, block_id, raw_yaml, blocks, block


def _generate_ai_screen(uid: int, post_data: Dict[str, Any]) -> Dict[str, Any]:
    llms, project, block_id, raw_yaml, blocks, block = _ai_request_context(
        uid, post_data, require_block=False
    )
    user_instruction = str(post_data.get("instruction") or "").strip()
    field_types = _field_types_from_request(post_data)
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
        - When fields is non-empty, continue_button_field must be an empty string.
        - Use continue_button_field only for a screen with no input fields.
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
        candidate_block["continue button field"] = screen.get("continue_button_field")

    candidate_yaml = canonical_block_yaml(candidate_block)
    _ensure_dayamlchecker_valid(candidate_yaml)
    return {
        "screen": screen,
        "model": model_name,
        "validated_yaml": candidate_yaml,
    }


@app.route(f"{EDITOR_BASE_PATH}/api/ai/generate-screen", methods=["POST"])
def editor_api_ai_generate_screen() -> Response:
    """Generate a single question screen draft from interview + template context."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        uid = _current_user_id()
        _ai_request_context(uid, post_data, require_block=False)
        _field_types_from_request(post_data)
        return _queue_ai_job("generate-screen", uid, post_data, request_id)
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


def _generate_ai_fields(uid: int, post_data: Dict[str, Any]) -> Dict[str, Any]:
    llms, project, block_id, raw_yaml, blocks, block = _ai_request_context(
        uid, post_data, require_block=True
    )
    assert block is not None
    field_types = _field_types_from_request(post_data)

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
    return {
        "fields": generated_fields,
        "model": model_name,
        "validated_yaml": candidate_yaml,
    }


@app.route(f"{EDITOR_BASE_PATH}/api/ai/generate-fields", methods=["POST"])
def editor_api_ai_generate_fields() -> Response:
    """Generate fields for one existing question block using full interview context."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        post_data = request.get_json(silent=True)
        if not isinstance(post_data, dict):
            raise ValueError("Request body must be a JSON object")
        uid = _current_user_id()
        _ai_request_context(uid, post_data, require_block=True)
        _field_types_from_request(post_data)
        return _queue_ai_job("generate-fields", uid, post_data, request_id)
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


@app.route(f"{EDITOR_BASE_PATH}/api/expression", methods=["POST"])
def editor_api_expression() -> Response:
    """Describe Python syntax for guided editing; never evaluate it."""
    from .editor_expressions import parse_expression

    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "bad_request", "message": "Expected an object"},
            },
            400,
        )
    try:
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": parse_expression(
                    body.get("source", ""), body.get("context", "value")
                ),
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
    """Draft a review screen for an interview, or re-sync the one it has.

    Reads the interview and every project file it includes, so a review screen
    stays current with variables that moved into another file. ``mode: "sync"``
    also returns the whole file with the old review screen, revisit screens and
    tables replaced in place, for the author to look over before saving.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))

        mode = str(post_data.get("mode") or "append").strip().lower()
        if mode not in ("append", "sync"):
            raise ValueError("mode must be 'append' or 'sync'.")

        raw_yaml = playground_read_yaml(uid, project, filename)

        def read_project_file(name: str) -> str:
            if name == filename:
                return raw_yaml
            return playground_read_yaml(uid, project, _normalize_filename(name))

        sources, yaml_texts = collect_interview_yaml_texts(
            read_project_file, filename, _project_yaml_filenames(uid, project)
        )
        identity = review_screen_identity(raw_yaml)
        # AssemblyLine declares `plaintiffs`, `defendants` and `courts` in its
        # own package, which the include walk does not follow. Telling the
        # generator about the lists this file already reviews keeps their
        # entries instead of silently dropping them.
        inferred_objects = inferred_objects_document(yaml_texts)
        generator_inputs = list(yaml_texts)
        if inferred_objects:
            generator_inputs.append(inferred_objects)
        review_yaml = ensure_revisit_tables(
            generate_review_screen_yaml(
                generator_inputs,
                screen_id=identity.get("id"),
                event_name=identity.get("event"),
                question_text=identity.get("question"),
            ),
            yaml_texts,
        )
        review_yaml, kept_entries = carry_over_unmatched_entries(review_yaml, raw_yaml)

        data: Dict[str, Any] = {
            "review_yaml": review_yaml,
            "sources": sources,
            "had_review_screen": bool(identity.get("found")),
            "replaced": False,
            "kept_entries": kept_entries,
            "warnings": review_scope_warnings(sources, yaml_texts),
            "revision": source_revision(raw_yaml),
        }
        if mode == "sync":
            data["full_yaml"], data["replaced"] = sync_review_screen(
                raw_yaml, review_yaml
            )
            # The drafted block on its own does not show what a sync will do to
            # the file: what is being dropped matters as much as what arrives.
            diff_text = unified_source_diff(raw_yaml, data["full_yaml"], filename)
            data["diff"] = truncate_diff(diff_text)
            data["diff"].update(diff_stats(diff_text))
            data["unchanged"] = not diff_text
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": data,
            }
        )
    except ALDashboardUnavailable as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "unavailable", "message": str(exc)},
            },
            503,
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


@app.route(f"{EDITOR_BASE_PATH}/api/kiln-tests", methods=["GET"])
def editor_api_kiln_tests() -> Response:
    """List selectable ALKiln tests in a Playground project."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        tests = _project_kiln_test_filenames(uid, project)
        managed_accessibility_enabled = None
        if MANAGED_IT_RUNS_FILENAME in tests:
            managed_accessibility_enabled = kiln_feature_checks_accessibility(
                _read_project_text_file(uid, project, "data", MANAGED_IT_RUNS_FILENAME)
            )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "tests": tests,
                    "managed_test_filename": MANAGED_IT_RUNS_FILENAME,
                    "managed_accessibility_enabled": managed_accessibility_enabled,
                },
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/kiln-test/draft", methods=["POST"])
def editor_api_draft_kiln_test() -> Response:
    """Draft a new test or a semantic sync of a selected existing test."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        data = request.get_json(silent=True) or {}
        project = _normalize_project(data.get("project"))
        interview_filename = _normalize_filename(data.get("interview_filename"))
        mode = str(data.get("mode") or "it_runs").strip()
        accessibility_enabled = parse_bool(data.get("accessibility"), default=True)
        yaml_filenames_raw = data.get("yaml_filenames")
        yaml_filenames: Optional[List[str]] = None
        if yaml_filenames_raw is not None:
            if not isinstance(yaml_filenames_raw, list) or not all(
                isinstance(filename, str) for filename in yaml_filenames_raw
            ):
                raise ValueError("yaml_filenames must be a list of YAML filenames")
            yaml_filenames = [
                filename
                for filename in yaml_filenames_raw
                if filename != interview_filename
            ]
            # Destination detection uses the last relevant YAML document. Keep
            # the runnable endpoint last so another checked endpoint cannot
            # silently choose the test's ending screen.
            yaml_filenames.append(interview_filename)
        requested_test = str(data.get("test_filename") or "").strip()
        if mode not in {"it_runs", "json"}:
            raise ValueError("Unknown ALKiln test creation mode")
        if mode == "it_runs" and yaml_filenames is None:
            yaml_filenames = _kiln_entrypoint_files(uid, project, interview_filename)
        test_filename = (
            MANAGED_IT_RUNS_FILENAME
            if mode == "it_runs"
            else _normalize_kiln_test_filename(requested_test)
        )
        existing = ""
        if mode == "it_runs" and test_filename in _project_kiln_test_filenames(
            uid, project
        ):
            existing = _read_project_text_file(uid, project, "data", test_filename)
        if mode == "json":
            if test_filename == MANAGED_IT_RUNS_FILENAME:
                raise ValueError(
                    f"{MANAGED_IT_RUNS_FILENAME} is reserved for Weaver's managed smoke test"
                )
            if test_filename in _project_kiln_test_filenames(uid, project):
                raise ValueError(
                    f"{test_filename} already exists. Choose a new filename; Weaver will not overwrite recorded tests."
                )
            json_text = data.get("json_text")
            if not isinstance(json_text, str) or not json_text.strip():
                raise ValueError("Paste a Docassemble variables JSON export")
            question_id = str(data.get("question_id") or "review_screen").strip()
            result = create_kiln_feature_from_json(
                json_text,
                interview_filename=interview_filename,
                question_id=question_id,
                accessibility_enabled=accessibility_enabled,
            )
            result.update(
                {
                    "existing_feature_text": "",
                    "proposed_feature_text": result["feature_text"],
                    "diff": unified_source_diff(
                        "", str(result["feature_text"]), test_filename
                    ),
                    "unchanged": False,
                    "added_screens": [],
                    "removed_screens": [],
                    "added_functionality": [
                        str(row).split("|")[1].strip()
                        for row in result.get("rows", [])
                        if str(row).count("|") >= 2
                    ],
                    "removed_functionality": [],
                }
            )
        elif existing:
            yaml_text = _project_interview_yaml(uid, project, yaml_filenames)
            result = sync_kiln_feature(
                existing,
                yaml_text,
                interview_filename=interview_filename,
                accessibility_enabled=accessibility_enabled,
            )
        else:
            yaml_text = _project_interview_yaml(uid, project, yaml_filenames)
            result = create_kiln_feature(
                yaml_text,
                interview_filename=interview_filename,
                accessibility_enabled=accessibility_enabled,
            )
            result.update(
                {
                    "existing_feature_text": "",
                    "proposed_feature_text": result["feature_text"],
                    "diff": unified_source_diff(
                        "", str(result["feature_text"]), test_filename
                    ),
                    "unchanged": False,
                    "added_screens": [
                        str(item["id"]) for item in result.get("screen_definitions", [])
                    ],
                    "removed_screens": [],
                    "added_functionality": [
                        str(row).split("|")[1].strip()
                        for row in result.get("rows", [])
                        if str(row).count("|") >= 2
                    ],
                    "removed_functionality": [],
                }
            )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "test_filename": test_filename,
                    "mode": mode,
                    "expected_revision": source_revision(existing),
                    **result,
                },
            }
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        status = 404 if isinstance(exc, FileNotFoundError) else 400
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            status,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/kiln-test/apply", methods=["POST"])
def editor_api_apply_kiln_test() -> Response:
    """Save a reviewed ALKiln feature into the Playground Sources area."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        data = request.get_json(silent=True) or {}
        project = _normalize_project(data.get("project"))
        test_filename = _normalize_kiln_test_filename(data.get("test_filename"))
        mode = str(data.get("mode") or "it_runs").strip()
        if mode == "it_runs":
            if test_filename != MANAGED_IT_RUNS_FILENAME:
                raise ValueError(
                    f"Only {MANAGED_IT_RUNS_FILENAME} can be synchronized by Weaver"
                )
        elif mode == "json":
            if test_filename == MANAGED_IT_RUNS_FILENAME:
                raise ValueError(
                    f"{MANAGED_IT_RUNS_FILENAME} is reserved for Weaver's managed smoke test"
                )
        else:
            raise ValueError("Unknown ALKiln test creation mode")
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("The generated ALKiln test is empty")
        with _source_file_lock(uid, project, test_filename, "data"):
            exists = test_filename in _project_kiln_test_filenames(uid, project)
            current = (
                _read_project_text_file(uid, project, "data", test_filename)
                if exists
                else ""
            )
            if mode == "json" and exists:
                raise ValueError(
                    f"{test_filename} already exists. Weaver will not overwrite recorded tests."
                )
            if mode == "it_runs":
                if not data.get("expected_revision"):
                    raise ValueError(
                        "Draft the test again before saving; its revision is missing."
                    )
                conflict = _section_file_revision_conflict(data, current, request_id)
                if conflict is not None and current != content:
                    return conflict
            if current != content:
                _write_project_text_file(uid, project, "data", test_filename, content)
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {"test_filename": test_filename},
            }
        )
    except SourceWriteLockUnavailable as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "source_lock_unavailable", "message": str(exc)},
            },
            503,
        )
    except (ValueError, FileNotFoundError) as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
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
GITHUB_PUBLISH_JOB_KEY_PREFIX = "da:alweaver:editor:github-publish:"
GITHUB_PUBLISH_JOB_EXPIRE_SECONDS = 24 * 60 * 60
GITHUB_PUBLISH_CELERY_TASK = (
    "docassemble.ALWeaver.api_weaver_worker.weaver_editor_github_publish_task"
)
TEMPLATE_IMPORT_JOB_KEY_PREFIX = "da:alweaver:editor:template-import:"
TEMPLATE_IMPORT_JOB_EXPIRE_SECONDS = 24 * 60 * 60
TEMPLATE_IMPORT_CELERY_TASK = (
    "docassemble.ALWeaver.api_weaver_worker.weaver_editor_template_import_task"
)
JOB_TERMINAL_STATES = {
    "succeeded",
    "failed",
    "cancelled",
    "expired",
}
NEW_PROJECT_TERMINAL_STATES = JOB_TERMINAL_STATES
# Celery can start a task before the API process persists its returned task id
# beside the initial job record. Give that write a short grace period so a
# fast task is not misreported as expired by its first status poll.
JOB_CELERY_TASK_ID_GRACE_SECONDS = 30


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


@dataclass(frozen=True)
class _EditorJobKind:
    """One family of background jobs tracked in Redis.

    Every long-running editor operation stores the same shaped state record
    under its own key prefix, so the load/store/reconcile helpers below are
    shared rather than duplicated per operation.
    """

    key_prefix: str
    celery_task: str
    expire_seconds: int = 24 * 60 * 60


NEW_PROJECT_JOB = _EditorJobKind(
    key_prefix=NEW_PROJECT_JOB_KEY_PREFIX,
    celery_task=NEW_PROJECT_CELERY_TASK,
    expire_seconds=NEW_PROJECT_JOB_EXPIRE_SECONDS,
)
GITHUB_PUBLISH_JOB = _EditorJobKind(
    key_prefix=GITHUB_PUBLISH_JOB_KEY_PREFIX,
    celery_task=GITHUB_PUBLISH_CELERY_TASK,
    expire_seconds=GITHUB_PUBLISH_JOB_EXPIRE_SECONDS,
)
TEMPLATE_IMPORT_JOB = _EditorJobKind(
    key_prefix=TEMPLATE_IMPORT_JOB_KEY_PREFIX,
    celery_task=TEMPLATE_IMPORT_CELERY_TASK,
    expire_seconds=TEMPLATE_IMPORT_JOB_EXPIRE_SECONDS,
)


AI_JOB = _EditorJobKind(
    key_prefix="da:alweaver:editor:ai-job:",
    celery_task="docassemble.ALWeaver.api_weaver_worker.weaver_editor_ai_task",
    expire_seconds=60 * 60,
)
AI_JOB_QUEUE_SECONDS = 15 * 60
AI_JOB_SOFT_LIMIT = 150
AI_JOB_HARD_LIMIT = 180
AI_JOB_OWNER_PREFIX = "da:alweaver:editor:ai-owner:"


def _job_state_key(kind: _EditorJobKind, job_id: str) -> str:
    return kind.key_prefix + job_id


def _load_job_state(kind: _EditorJobKind, job_id: str) -> Optional[Dict[str, Any]]:
    raw = r.get(_job_state_key(kind, job_id))
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


def _store_job_state(
    kind: _EditorJobKind, job_id: str, state: Dict[str, Any]
) -> Dict[str, Any]:
    payload = dict(state)
    payload["job_id"] = job_id
    payload.setdefault("created_at", payload.get("updated_at", time.time()))
    payload["updated_at"] = time.time()
    key = _job_state_key(kind, job_id)
    pipe = r.pipeline()
    pipe.set(key, json.dumps(payload))
    pipe.expire(key, kind.expire_seconds)
    pipe.execute()
    return payload


def _update_job_state(
    kind: _EditorJobKind, job_id: str, **updates: Any
) -> Dict[str, Any]:
    state = _load_job_state(kind, job_id) or {}
    state.update(updates)
    return _store_job_state(kind, job_id, state)


def _release_ai_owner(uid: int, job_id: str) -> None:
    # A timed-out job must never release a newer job's reservation.
    r.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end",
        1,
        AI_JOB_OWNER_PREFIX + str(uid),
        job_id,
    )


def _queue_ai_job(
    operation: str, uid: int, payload: Dict[str, Any], request_id: str
) -> Response:
    if not worker_configuration_is_ready():
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "unavailable",
                    "code": "editor_async_not_configured",
                    "message": "AI drafting and AI style checks require Weaver's Celery worker module.",
                    "details": get_worker_configuration_status(),
                },
            },
            503,
        )
    if len(json.dumps(payload).encode("utf-8")) > 128 * 1024:
        raise ValueError("AI request is too large (maximum 128 KiB)")
    job_id = str(uuid.uuid4())
    if not r.set(
        AI_JOB_OWNER_PREFIX + str(uid),
        job_id,
        nx=True,
        ex=AI_JOB_QUEUE_SECONDS + AI_JOB_HARD_LIMIT + 60,
    ):
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "busy",
                    "code": "ai_job_in_progress",
                    "message": "An AI draft or style check is already queued or running for your account. Wait for it to finish.",
                },
            },
            429,
        )
    try:
        state = _store_job_state(
            AI_JOB,
            job_id,
            {
                "owner_user_id": uid,
                "operation": operation,
                "status": "queued",
                "queued_at": time.time(),
                "celery_task_id": job_id,
                "result": None,
                "error": None,
            },
        )
        workerapp.send_task(
            AI_JOB.celery_task,
            task_id=job_id,
            kwargs={
                "job_id": job_id,
                "uid": uid,
                "operation": operation,
                "payload": payload,
            },
            soft_time_limit=AI_JOB_SOFT_LIMIT,
            time_limit=AI_JOB_HARD_LIMIT,
            expires=AI_JOB_QUEUE_SECONDS,
        )
    except Exception:
        _release_ai_owner(uid, job_id)
        _update_job_state(
            AI_JOB,
            job_id,
            status="failed",
            error={"message": "Could not queue the AI request."},
        )
        raise
    return jsonify_with_status(
        {
            "success": True,
            "request_id": request_id,
            "status": "queued",
            "data": {
                "job_id": job_id,
                "job_url": f"{EDITOR_BASE_PATH}/api/ai/jobs/{job_id}",
                "status": state["status"],
            },
        },
        202,
    )


def _run_ai_job_with_capacity(
    job_id: str, uid: int, operation: str, payload: Dict[str, Any]
) -> bool:
    """Try once for a server-wide slot; False means retry later, without waiting."""
    state = _load_job_state(AI_JOB, job_id)
    if (
        not state
        or state.get("owner_user_id") != uid
        or state.get("status") in JOB_TERMINAL_STATES
    ):
        return True
    if time.time() - state["queued_at"] > AI_JOB_QUEUE_SECONDS:
        _update_job_state(
            AI_JOB,
            job_id,
            status="expired",
            error={"message": "The AI request expired in the queue. Please try again."},
        )
        _release_ai_owner(uid, job_id)
        return True
    # Each slot expires after the worker's hard limit, including a cleanup
    # margin for a killed worker. No web or Celery worker waits on the lock.
    for slot in range(2):
        lock = r.lock(
            f"da:alweaver:editor:ai-slot:{slot}", timeout=AI_JOB_HARD_LIMIT + 60
        )
        if not lock.acquire(blocking=False):
            continue
        try:
            _complete_ai_job(job_id, uid, operation, payload)
        finally:
            lock.release()
        return True
    return False


def _complete_ai_job(
    job_id: str, uid: int, operation: str, payload: Dict[str, Any]
) -> None:
    state = _load_job_state(AI_JOB, job_id)
    if (
        not state
        or state.get("owner_user_id") != uid
        or state.get("status") in JOB_TERMINAL_STATES
    ):
        return
    try:
        _update_job_state(AI_JOB, job_id, status="running", started_at=time.time())
        if operation == "generate-screen":
            result = _generate_ai_screen(uid, payload)
        elif operation == "generate-fields":
            result = _generate_ai_fields(uid, payload)
        elif operation == "style-check":
            result = _style_check_result(
                uid,
                _normalize_project(payload.get("project")),
                _normalize_filename(payload.get("filename")),
                True,
            )
        else:
            raise ValueError("Unknown AI operation")
        _update_job_state(
            AI_JOB, job_id, status="succeeded", result=result, finished_at=time.time()
        )
    except (ValueError, FileNotFoundError, ALDashboardUnavailable) as exc:
        # The synchronous routes returned these messages as 4xx/503 errors;
        # keep them readable now that the work finishes in a worker.
        _update_job_state(
            AI_JOB,
            job_id,
            status="failed",
            finished_at=time.time(),
            error={"type": "validation_error", "message": str(exc)},
        )
    except Exception as exc:
        log(f"ALWeaver editor: AI job {job_id} failed: {type(exc).__name__}", "error")
        _update_job_state(
            AI_JOB,
            job_id,
            status="failed",
            finished_at=time.time(),
            error={
                "type": "ai_job_failed",
                "message": "The AI request failed or exceeded its time limit. Please try again.",
            },
        )
    finally:
        _release_ai_owner(uid, job_id)


@app.route(f"{EDITOR_BASE_PATH}/api/ai/jobs/<job_id>", methods=["GET"])
def editor_api_ai_job(job_id: str) -> Response:
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    uid = _current_user_id()
    state = _load_job_state(AI_JOB, job_id)
    if not state or state.get("owner_user_id") != uid:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "not_found", "message": "Job not found."},
            },
            404,
        )
    if state.get("status") not in JOB_TERMINAL_STATES:
        if time.time() - state["queued_at"] > AI_JOB_QUEUE_SECONDS + AI_JOB_HARD_LIMIT:
            state = _update_job_state(
                AI_JOB,
                job_id,
                status="expired",
                error={"message": "The AI request expired. Please try again."},
            )
        else:
            state = _reconcile_job_state(
                AI_JOB,
                job_id,
                state,
                success_message="AI request completed.",
                failure_message="The AI request failed or exceeded its time limit.",
            )
    if state.get("status") in JOB_TERMINAL_STATES:
        _release_ai_owner(uid, job_id)
    return jsonify({"success": True, "request_id": request_id, "data": state})


def _load_new_project_job_state(job_id: str) -> Optional[Dict[str, Any]]:
    return _load_job_state(NEW_PROJECT_JOB, job_id)


def _store_new_project_job_state(job_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    return _store_job_state(NEW_PROJECT_JOB, job_id, state)


def _update_new_project_job_state(job_id: str, **updates: Any) -> Dict[str, Any]:
    return _update_job_state(NEW_PROJECT_JOB, job_id, **updates)


def _complete_new_project_upload_job(
    *,
    job_id: str,
    uid: int,
    project_name: str,
    request_id: str,
    uploaded_files: List[Dict[str, Any]],
    generation_options: Dict[str, Any],
    debug_requested: bool,
    interview_filename: Optional[str] = None,
    create_test: bool = False,
) -> Dict[str, Any]:
    stage = "start"
    temp_dir = tempfile.mkdtemp(prefix="editor-upload-")
    completed_artifacts: List[str] = []
    incomplete_artifacts: List[str] = []

    def checkpoint_artifacts(checkpoint_stage: str) -> None:
        """Persist logical output progress so polling can report worker loss."""
        partial_result = {
            "project": project_name,
            "partial_artifacts": list(completed_artifacts),
            "incomplete_artifacts": list(incomplete_artifacts),
            "incomplete_stage": checkpoint_stage,
        }
        _update_new_project_job_state(
            job_id,
            status="running",
            stage=checkpoint_stage,
            partial_artifacts=partial_result["partial_artifacts"],
            incomplete_artifacts=partial_result["incomplete_artifacts"],
            result=partial_result,
        )

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
        documents: List[Dict[str, Any]] = []
        for payload in uploaded_files:
            filename = str(payload.get("filename") or "").strip()
            content_bytes = payload.get("content_bytes") or b""
            mimetype = payload.get("mimetype")
            if not filename:
                raise ValueError("Uploaded file is missing a filename.")
            if not isinstance(content_bytes, (bytes, bytearray)):
                raise ValueError("Uploaded file bytes are invalid.")
            documents.append(
                {
                    "filename": filename,
                    "content_bytes": bytes(content_bytes),
                    "mimetype": str(mimetype) if mimetype else None,
                }
            )

        if not documents:
            raise ValueError("No valid files were uploaded.")

        stage = "generate_interview"
        _update_new_project_job_state(
            job_id,
            status="running",
            stage=stage,
            message=(
                "Generating interview from the uploaded document."
                if len(documents) == 1
                else f"Generating interview from {len(documents)} uploaded documents."
            ),
            progress=20,
        )
        # Every upload is woven into the one interview: each contributes its
        # fields, its own attachment block, and an entry in the bundle.
        first_result = generate_interview_from_bytes(
            filename=documents[0]["filename"],
            content_bytes=documents[0]["content_bytes"],
            mimetype=documents[0]["mimetype"],
            generation_options=generation_options,
            include_yaml_text=True,
            include_generated_template_bytes=True,
            additional_documents=documents[1:],
        )

        # Renaming rewrites the template, and the YAML now refers to the new
        # field names, so the project has to carry the rewritten file.
        normalized_bytes: Dict[str, bytes] = {}
        for normalized_file in first_result.get("normalized_template_files", []) or []:
            if not isinstance(normalized_file, dict):
                continue
            normalized_name = os.path.basename(
                str(normalized_file.get("filename") or "")
            )
            normalized_content = normalized_file.get("content_bytes")
            if not normalized_name or not isinstance(
                normalized_content, (bytes, bytearray)
            ):
                continue
            normalized_bytes[normalized_name] = bytes(normalized_content)

        # Weaver has the final say on template filenames -- two uploads that
        # arrived sharing one are told apart there -- so the project stores
        # them under the names the generated YAML refers to.
        woven_names = [
            os.path.basename(str(name))
            for name in (first_result.get("template_filenames") or [])
        ]
        if len(woven_names) != len(documents) or not all(woven_names):
            woven_names = [
                os.path.basename(document["filename"]) for document in documents
            ]
        temp_paths: List[str] = []
        for document, woven_name in zip(documents, woven_names):
            dest = os.path.join(temp_dir, woven_name)
            with open(dest, "wb") as fh:
                fh.write(normalized_bytes.get(woven_name) or document["content_bytes"])
            temp_paths.append(dest)

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
        # Weaver already derived a descriptive name from the document; the
        # author may have overridden it on the creation screen.
        yaml_filename = interview_filename or _normalize_generated_filename(
            first_result.get("yaml_filename")
        )
        incomplete_artifacts = [yaml_filename]
        checkpoint_artifacts(stage)
        playground_write_yaml(uid, project_name, yaml_filename, yaml_text)
        completed_artifacts.append(yaml_filename)
        incomplete_artifacts = []
        checkpoint_artifacts(stage)
        generated_test = None
        if create_test:
            # The managed feature writer may create the file before failing
            # while flushing or returning metadata. Report its known logical
            # name as potentially incomplete until the write fully succeeds.
            incomplete_artifacts = [MANAGED_IT_RUNS_FILENAME]
            checkpoint_artifacts(stage)
            generated_test = _write_default_kiln_test(
                uid, project_name, yaml_filename, yaml_text
            )["filename"]
            if generated_test:
                completed_artifacts.append(generated_test)
            incomplete_artifacts = []
            checkpoint_artifacts(stage)

        stage = "copy_templates"
        _update_new_project_job_state(
            job_id,
            status="running",
            stage=stage,
            message="Copying uploaded files into the project.",
            progress=85,
        )
        incomplete_artifacts = list(woven_names)
        checkpoint_artifacts(stage)
        _copy_files_to_section(
            user_id=uid,
            project_name=project_name,
            storage_section=SECTION_TO_STORAGE["templates"],
            files=temp_paths,
        )
        completed_artifacts.extend(woven_names)
        incomplete_artifacts = []
        checkpoint_artifacts(stage)
        generated_template_files = first_result.get("generated_template_files", [])
        generated_paths: List[str] = []
        for generated_file in generated_template_files:
            if not isinstance(generated_file, dict):
                continue
            generated_name = os.path.basename(str(generated_file.get("filename") or ""))
            generated_bytes = generated_file.get("content_bytes")
            if not generated_name or not isinstance(
                generated_bytes, (bytes, bytearray)
            ):
                continue
            generated_path = os.path.join(temp_dir, generated_name)
            with open(generated_path, "wb") as generated_handle:
                generated_handle.write(bytes(generated_bytes))
            generated_paths.append(generated_path)
        if generated_paths:
            incomplete_artifacts = [
                os.path.basename(str(item.get("filename") or ""))
                for item in generated_template_files
                if isinstance(item, dict) and item.get("filename")
            ]
            checkpoint_artifacts(stage)
            _copy_files_to_section(
                user_id=uid,
                project_name=project_name,
                storage_section=SECTION_TO_STORAGE["templates"],
                files=generated_paths,
            )
            completed_artifacts.extend(incomplete_artifacts)
            incomplete_artifacts = []
            checkpoint_artifacts(stage)

        result = {
            "project": project_name,
            "filename": yaml_filename,
            "generated_from": first_result.get("input_filename"),
            "woven_templates": woven_names,
            "uploaded_count": len(temp_paths),
            "generated_template_count": len(generated_paths),
            "renamed_template_count": len(normalized_bytes),
            "test_filename": generated_test,
            "warnings": list(first_result.get("warnings") or []),
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
            error=None,
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
        partial_result = {
            "project": project_name,
            "partial_artifacts": list(completed_artifacts),
            "incomplete_artifacts": list(incomplete_artifacts),
            "incomplete_stage": stage,
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
            result=partial_result,
            partial_artifacts=partial_result["partial_artifacts"],
            incomplete_artifacts=partial_result["incomplete_artifacts"],
            finished_at=time.time(),
        )
        log(
            "ALWeaver editor: background new-project upload failed "
            f"job_id={job_id} request_id={request_id} stage={stage} "
            f"exception_type={type(exc).__name__}",
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
    interview_filename: Optional[str] = None,
    create_test: bool = True,
    renamed_files: Optional[List[Dict[str, str]]] = None,
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
        "celery_task_id": job_id,
        "generated_from": uploaded_files[0].get("filename") if uploaded_files else None,
        "uploaded_count": len(uploaded_files),
        # The generated YAML refers to the template by the name the project
        # stores it under, which is not always the name that was uploaded.
        "renamed_files": list(renamed_files or []),
        "queued_at": queued_at,
        "started_at": None,
        "finished_at": None,
        "progress": 0,
        "result": None,
        "error": None,
    }
    _store_new_project_job_state(job_id, initial_state)
    try:
        workerapp.send_task(
            NEW_PROJECT_CELERY_TASK,
            task_id=job_id,
            kwargs={
                "job_id": job_id,
                "uid": uid,
                "project_name": project_name,
                "request_id": request_id,
                "uploaded_files": uploaded_files,
                "generation_options": generation_options,
                "debug_requested": debug_requested,
                "interview_filename": interview_filename,
                "create_test": create_test,
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
    return {
        "job_id": job_id,
        "job_url": f"{EDITOR_BASE_PATH}/api/new-project/jobs/{job_id}",
        "state": initial_state,
    }


def _reconcile_job_state(
    kind: _EditorJobKind,
    job_id: str,
    state: Dict[str, Any],
    *,
    success_message: str,
    failure_message: str,
) -> Dict[str, Any]:
    """Fold the Celery task's own state back into the stored job record.

    A worker that dies mid-task never gets to write its failure, so the poll
    endpoint asks Celery directly whenever the record is not already terminal.
    """
    status = str(state.get("status") or "queued")
    if status in JOB_TERMINAL_STATES:
        return state
    celery_task_id = state.get("celery_task_id")
    if not celery_task_id:
        queued_at = state.get("queued_at")
        if queued_at is not None:
            try:
                queue_age = max(0.0, time.time() - float(queued_at))
            except (TypeError, ValueError):
                queue_age = JOB_CELERY_TASK_ID_GRACE_SECONDS
            if queue_age < JOB_CELERY_TASK_ID_GRACE_SECONDS:
                return state
        return _update_job_state(
            kind,
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
        return _update_job_state(
            kind,
            job_id,
            status="succeeded",
            stage="done",
            message=success_message,
            progress=100,
            finished_at=time.time(),
            result=task_value if isinstance(task_value, dict) else state.get("result"),
            error=None,
        )
    if celery_state == "FAILURE":
        task_error = getattr(task_result, "result", None)
        return _update_job_state(
            kind,
            job_id,
            status="failed",
            stage=state.get("stage") or "failed",
            message=failure_message,
            finished_at=time.time(),
            error={
                "type": "celery_failure",
                "message": str(task_error or "Task failed"),
            },
        )
    if celery_state == "REVOKED":
        return _update_job_state(
            kind,
            job_id,
            status="cancelled",
            stage="cancelled",
            message="The job was cancelled.",
            finished_at=time.time(),
        )
    if celery_state in {"STARTED", "RETRY"}:
        if status == "running":
            return state
        updates: Dict[str, Any] = {"status": "running"}
        if not state.get("started_at"):
            updates["started_at"] = time.time()
        return _update_job_state(kind, job_id, **updates)
    if celery_state in {"PENDING", "RECEIVED"}:
        return state
    return _update_job_state(
        kind,
        job_id,
        status="expired",
        stage="expired",
        message="The Celery task state is no longer available.",
        finished_at=time.time(),
        error={"type": "job_expired", "message": f"Unknown task state: {celery_state}"},
    )


def _reconcile_new_project_job_state(
    job_id: str, state: Dict[str, Any]
) -> Dict[str, Any]:
    return _reconcile_job_state(
        NEW_PROJECT_JOB,
        job_id,
        state,
        success_message="Project created successfully.",
        failure_message="ALWeaver generation failed.",
    )


def _reconcile_github_publish_job_state(
    job_id: str, state: Dict[str, Any]
) -> Dict[str, Any]:
    return _reconcile_job_state(
        GITHUB_PUBLISH_JOB,
        job_id,
        state,
        success_message="Published to GitHub successfully.",
        failure_message="Publishing to GitHub failed.",
    )


@app.route(f"{EDITOR_BASE_PATH}/api/github/publish/preview", methods=["POST"])
def editor_api_github_publish_preview() -> Response:
    """Build a read-only file diff for one selected GitHub target."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        package = normalize_github_package_name(post_data.get("package"))
        owner = str(post_data.get("owner") or "").strip()
        if not owner:
            raise ValueError("GitHub owner is required")
        branch = _normalize_git_branch(post_data.get("branch"))
        integration = get_native_github_integration(uid)
        if not integration.get("enabled") or not integration.get("connected"):
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "github_not_connected",
                        "message": "Connect your GitHub account in Docassemble before previewing a publish.",
                    },
                },
                409,
            )
        selected_owner = next(
            (
                candidate
                for candidate in get_github_publish_owners(user_id=uid)
                if str(candidate.get("login") or "").casefold() == owner.casefold()
            ),
            None,
        )
        if selected_owner is None:
            raise ValueError("Choose a GitHub account or organization from the list")
        if selected_owner.get("type") == "organization" and not integration.get(
            "organizations_enabled"
        ):
            raise ValueError(
                "Enable organization repository access in Docassemble's GitHub settings first"
            )
        author = _repository_config_author()
        owner = str(selected_owner["login"])
        repository_url = f"https://github.com/{owner}/docassemble-{package}"
        prepared = prepare_project_github_package(
            user_id=uid,
            project_name=project,
            package_name=package,
            author_name=author["author_name"],
            author_email=author["author_email"],
            github_url=repository_url,
            dependencies=repository_dependency_names(uid, project, package),
            persist_manifest=False,
        )
        package_info = prepared["manifest"]
        repository_files = repository_publish_files(
            uid, project, package, manifest=package_info
        )
        local_files = build_github_package_snapshot(
            package=package,
            project=project,
            user_id=uid,
            package_info=package_info,
            author_name=author["author_name"],
            author_email=author["author_email"],
            manifest_path=prepared["manifest_path"],
            extra_repository_files=repository_files["files"],
        )
        remote = get_github_repository_snapshot(
            repository_url=repository_url,
            user_id=uid,
            ref=branch,
            allow_missing=True,
            include_all_files=True,
        )
        target_sha = str(remote.get("sha") or "")
        remote_files = remote.get("files") or {}
        if remote.get("missing") and remote.get("repository_exists"):
            default_branch = str(remote.get("default_branch") or "main")
            base = get_github_repository_snapshot(
                repository_url=repository_url,
                user_id=uid,
                ref=default_branch,
                allow_missing=True,
                include_all_files=True,
            )
            target_sha = str(base.get("sha") or "")
            remote_files = base.get("files") or {}
        changes, target_files = _github_publish_diff(
            local_files,
            {
                str(path): content
                for path, content in remote_files.items()
                if isinstance(path, str) and isinstance(content, bytes)
            },
            managed_paths=set(repository_files["managed_paths"]),
        )
        unpulled = _github_branch_unpulled_message(
            find_project_github_sync(user_id=uid, project_name=project),
            repository_url=repository_url,
            branch=branch,
            remote=remote,
        )
        source_revision = github_package_snapshot_revision(local_files)
        preview = {
            "user_id": uid,
            "project": project,
            "package": package,
            "owner": owner,
            "repository_url": repository_url,
            "branch": branch,
            "source_revision": source_revision,
            "remote_sha": target_sha,
            "issued_at": int(time.time()),
        }
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project,
                    "package": package,
                    "owner": owner,
                    "repository_url": repository_url,
                    "branch": branch,
                    "remote_sha": target_sha,
                    "source_revision": source_revision,
                    "unpulled": unpulled,
                    "repository_missing": bool(remote.get("missing")),
                    "files": target_files,
                    "changes": changes,
                    "preview_token": _sign_github_publish_preview(preview),
                },
            }
        )
    except GithubCredentialError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "github_not_connected", "message": str(exc)},
            },
            409,
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
        log(f"ALWeaver editor: GitHub publish preview error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


def _github_branch_unpulled_message(
    sync: Optional[Dict[str, Any]],
    *,
    repository_url: str,
    branch: str,
    remote: Dict[str, Any],
) -> Optional[str]:
    """Explain why publishing to ``branch`` would undo commits, if it would.

    Like ``git push``, a publish to an existing branch must build on what the
    project last pulled: the branch head has to be the commit Weaver last
    synchronized from that repository. Each publish replaces the branch's
    files, so building on any other head would silently revert its changes.
    A new branch, or one holding no package files yet (such as a repository
    GitHub initialized with only a README), has nothing to undo.
    """
    if remote.get("missing") or not any(
        is_github_package_path(path) for path in remote.get("files") or {}
    ):
        return None
    synced = (
        sync
        if sync
        and str(sync.get("repository_url") or "").rstrip("/").casefold()
        == repository_url.rstrip("/").casefold()
        else None
    )
    if synced and synced.get("commit") and remote.get("sha") == synced["commit"]:
        return None
    if synced and synced.get("branch") == branch:
        return (
            f"GitHub branch {branch!r} has advanced since this project was last "
            "synchronized. Pull the remote changes and resolve them in the "
            "project before publishing again."
        )
    advice = (
        "Use Pull from GitHub to merge that branch into this project"
        if synced
        else "Create a project from that branch to bring its changes over"
    )
    return (
        f"GitHub branch {branch!r} has commits this project has not pulled. "
        f"{advice}, or publish to a new branch."
    )


def _assert_github_publish_branch_is_current(
    *,
    uid: int,
    project: str,
    repository_url: str,
    branch: str,
    expected_remote_sha: Optional[str] = None,
) -> None:
    """Refuse a publish that would revert commits the project does not have,
    or, after a preview, one whose branch moved since it was reviewed."""
    remote = get_github_branch_head(
        repository_url=repository_url, ref=branch, user_id=uid
    )
    message = _github_branch_unpulled_message(
        find_project_github_sync(user_id=uid, project_name=project),
        repository_url=repository_url,
        branch=branch,
        remote=remote,
    )
    if message:
        raise ValueError(f"{message} No files were published.")
    if expected_remote_sha is None:
        return
    # A new branch is created from the default branch, as the preview showed.
    parent = remote
    if remote.get("missing") and remote.get("repository_exists"):
        parent = get_github_branch_head(
            repository_url=repository_url,
            ref=str(remote.get("default_branch") or "main"),
            user_id=uid,
        )
    if str(parent.get("sha") or "") != expected_remote_sha:
        raise ValueError(
            f"GitHub branch {branch!r} changed after the publish preview. "
            "Review its latest changes before publishing; no files were committed."
        )


def _complete_github_publish_job(
    *,
    job_id: str,
    uid: int,
    project: str,
    package: str,
    repository: str,
    owner: str,
    owner_type: str,
    author_name: str,
    author_email: str,
    branch: str,
    commit_message: str,
    repository_url: str,
    expected_remote_sha: Optional[str] = None,
    expected_source_revision: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the repository if needed and commit the prepared package.

    Runs in the Celery worker: one blob upload per file means a project with a
    handful of templates makes far more GitHub round trips than a web request
    can wait for.
    """
    stage = "start"
    try:
        _update_job_state(
            GITHUB_PUBLISH_JOB,
            job_id,
            status="running",
            stage=stage,
            message="Starting the GitHub publish.",
            started_at=time.time(),
            progress=5,
        )

        stage = "ensure_repository"
        _update_job_state(
            GITHUB_PUBLISH_JOB,
            job_id,
            stage=stage,
            message=f"Checking {owner}/{repository} on GitHub.",
            progress=10,
        )
        _assert_github_publish_branch_is_current(
            uid=uid,
            project=project,
            repository_url=repository_url,
            branch=branch,
            expected_remote_sha=expected_remote_sha,
        )
        github_repository = ensure_github_repository(
            owner=owner,
            repository=repository,
            description=f"A docassemble project for {project}.",
            owner_type=owner_type or None,
            user_id=uid,
        )
        canonical_url = str(github_repository.get("html_url") or repository_url).rstrip(
            "/"
        )

        stage = "publish"
        package_info, manifest_path = load_project_github_manifest(
            user_id=uid,
            project_name=project,
            package_name=package,
        )

        repository_files = repository_publish_files(
            uid, project, package, manifest=package_info
        )

        def report(message: str, percent: int) -> None:
            # publish_github_package reports on its own 0-100 scale; the
            # repository check already accounted for the first tenth.
            _update_job_state(
                GITHUB_PUBLISH_JOB,
                job_id,
                stage="publish",
                message=message,
                progress=15 + int(80 * percent / 100),
            )

        committed = publish_github_package(
            owner=owner,
            repository=repository,
            package=package,
            project=project,
            user_id=uid,
            package_info=package_info,
            author_name=author_name,
            author_email=author_email,
            branch=branch,
            commit_message=commit_message,
            manifest_path=manifest_path,
            default_branch=str(github_repository.get("default_branch") or ""),
            on_progress=report,
            extra_repository_files=repository_files["files"],
            preserved_path_prefixes=(".github/",),
            managed_paths=repository_files["managed_paths"],
            expected_remote_sha=expected_remote_sha,
            expected_source_revision=expected_source_revision,
        )
        record_project_github_sync(
            user_id=uid,
            project_name=project,
            package_name=package,
            repository_url=canonical_url,
            branch=branch,
            commit_sha=committed["sha"],
        )

        result = {
            "project": project,
            "package": package,
            "repository": repository,
            "owner": owner,
            "repository_url": canonical_url,
            "repository_created": bool(github_repository.get("created_by_weaver")),
            "branch": branch,
            "commit_sha": committed["sha"],
            "files_committed": committed["files"],
            "commit_url": f"{canonical_url}/commit/{committed['sha']}",
            "warnings": committed.get("warnings", []),
            "skipped_workflows": committed.get("skipped_workflows", []),
            "workflow_access": committed.get("workflow_access"),
        }
        _update_job_state(
            GITHUB_PUBLISH_JOB,
            job_id,
            status="succeeded",
            stage="done",
            message=(
                f"Published {result['files_committed']} files to "
                f"{owner}/{repository} on {branch}."
            ),
            result=result,
            error=None,
            progress=100,
            finished_at=time.time(),
        )
        return result
    except Exception as exc:
        if isinstance(exc, GithubCredentialError):
            error_type = "github_not_connected"
        elif isinstance(exc, ValueError):
            error_type = "validation_error"
        else:
            error_type = "server_error"
        _update_job_state(
            GITHUB_PUBLISH_JOB,
            job_id,
            status="failed",
            stage=stage,
            message="Publishing to GitHub failed.",
            error={"type": error_type, "message": str(exc)},
            finished_at=time.time(),
        )
        log(
            "ALWeaver editor: background GitHub publish failed "
            f"job_id={job_id} project={project} stage={stage}: {exc!r}\n"
            f"{traceback.format_exc()}",
            "error",
        )
        raise


def _start_github_publish_job(
    *,
    uid: int,
    request_id: str,
    project: str,
    package: str,
    repository: str,
    owner: str,
    owner_type: str,
    author_name: str,
    author_email: str,
    branch: str,
    commit_message: str,
    repository_url: str,
    expected_remote_sha: Optional[str] = None,
    expected_source_revision: Optional[str] = None,
) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    initial_state: Dict[str, Any] = {
        "status": "queued",
        "stage": "queued",
        "message": f"Queued for publishing to {owner}/{repository}.",
        "owner_user_id": uid,
        "operation_type": "github_publish",
        "project": project,
        "package": package,
        "repository": repository,
        "owner": owner,
        "branch": branch,
        "repository_url": repository_url,
        "expected_remote_sha": expected_remote_sha,
        "expected_source_revision": expected_source_revision,
        "request_id": request_id,
        "celery_task_id": job_id,
        "queued_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "progress": 0,
        "result": None,
        "error": None,
    }
    _store_job_state(GITHUB_PUBLISH_JOB, job_id, initial_state)
    try:
        workerapp.send_task(
            GITHUB_PUBLISH_CELERY_TASK,
            task_id=job_id,
            kwargs={
                "job_id": job_id,
                "uid": uid,
                "project": project,
                "package": package,
                "repository": repository,
                "owner": owner,
                "owner_type": owner_type,
                "author_name": author_name,
                "author_email": author_email,
                "branch": branch,
                "commit_message": commit_message,
                "repository_url": repository_url,
                "expected_remote_sha": expected_remote_sha,
                "expected_source_revision": expected_source_revision,
            },
        )
    except Exception as exc:
        _update_job_state(
            GITHUB_PUBLISH_JOB,
            job_id,
            status="failed",
            stage="enqueue",
            message="Unable to queue the GitHub publish.",
            finished_at=time.time(),
            error={
                "type": "queue_error",
                "message": str(exc) or "Unable to queue Celery task.",
            },
        )
        raise
    return {
        "job_id": job_id,
        "job_url": f"{EDITOR_BASE_PATH}/api/github/publish/jobs/{job_id}",
        "state": initial_state,
    }


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
    github_url = str(post_data.get("github_url") or "").strip()
    create_test = parse_bool(post_data.get("create_test"), default=True)
    snapshot: Dict[str, Any] = {}
    if github_url:
        # Read the repository first, so a bad URL or branch never leaves an
        # empty project behind.
        snapshot = get_github_repository_snapshot(
            repository_url=github_url,
            user_id=uid,
            ref=str(post_data.get("github_branch") or "").strip() or None,
        )
        if not str(raw_name or "").strip():
            raw_name = github_project_name(
                snapshot["repository"], str(snapshot.get("branch") or "")
            )

    base_name = normalize_project_name(raw_name)
    existing = get_list_of_projects(uid)
    project_name = next_available_project_name(base_name, [*existing, "default"])
    create_project(uid, project_name)

    if github_url:
        try:
            imported = import_github_snapshot(
                user_id=uid, project_name=project_name, snapshot=snapshot
            )
            adopt_repository_snapshot(
                uid, project_name, imported["package"], snapshot["files"]
            )
        except Exception:
            # A failed import should not leave an empty, misleading project in
            # the user's project chooser.
            delete_project(uid, project_name)
            raise
        # An imported repository can bring Python modules with it, and no save
        # went through the editor to install them.
        _reconcile_project_modules(uid, project_name)
        test_filename = None
        if create_test:
            existing_tests = _project_kiln_test_filenames(uid, project_name)
            if not existing_tests:
                test_filename = _write_default_kiln_test(
                    uid, project_name, imported["filename"]
                )["filename"]
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "project": project_name,
                    "filename": imported["filename"],
                    "github_url": snapshot["url"],
                    "github_branch": snapshot["branch"],
                    "files_imported": imported["files_imported"],
                    "restart_state": _restart_state_payload(uid, project_name),
                    "test_filename": test_filename,
                },
            }
        )

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
            "---\n"
            "mandatory: True\n"
            "code: |\n"
            "  intro_screen\n"
            "  blank_project_complete\n"
            "---\n"
            "event: blank_project_complete\n"
            "question: Interview ready\n"
            "subquestion: |\n"
            "  This blank interview is ready for you to edit.\n"
        )

    # Write starter YAML. There is no document to name it after, so a blank
    # project gets AssemblyLine's functional name for a runnable file.
    playground_write_yaml(
        uid, project_name, DEFAULT_NEW_INTERVIEW_FILENAME, starter_yaml
    )
    test_filename = None
    if create_test:
        test_filename = _write_default_kiln_test(
            uid,
            project_name,
            DEFAULT_NEW_INTERVIEW_FILENAME,
            starter_yaml,
        )["filename"]

    return jsonify(
        {
            "success": True,
            "request_id": request_id,
            "data": {
                "project": project_name,
                "filename": DEFAULT_NEW_INTERVIEW_FILENAME,
                "template_id": template_id,
                "test_filename": test_filename,
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
    github_user = request.form.get("github_user")
    output_type = request.form.get("output_type", "form").strip().lower()
    if output_type not in {"form", "survey"}:
        raise ValueError("output_type must be form or survey")
    form_type = request.form.get("form_type", "auto").strip()
    valid_form_types = {
        "auto",
        "starts_case",
        "existing_case",
        "appeal",
        "other_form",
        "letter",
        "other",
    }
    if form_type not in valid_form_types:
        raise ValueError("Unsupported AssemblyLine form type")
    typical_role = request.form.get("typical_role", "auto").strip()
    if typical_role not in {"auto", "plaintiff", "defendant", "unknown"}:
        raise ValueError("Unsupported typical user role")
    default_state = request.form.get("default_state", "").strip().upper()
    include_next_steps = parse_bool(
        request.form.get("include_next_steps"), default=True
    )
    enable_navigation = parse_bool(request.form.get("enable_navigation"), default=True)
    copy_baseline_questions = parse_bool(
        request.form.get("copy_baseline_questions"), default=True
    )
    create_test = parse_bool(request.form.get("create_test"), default=True)
    # Off by default: renaming rewrites the template that ships in the project,
    # so the author asks for it rather than discovering it happened.
    normalize_field_names = parse_bool(
        request.form.get("normalize_field_names"), default=False
    )
    # Publishing metadata. The generator can invent a title from the filename and
    # `_ensure_required_metadata_values()` backfills the rest, but the values an
    # author actually knows -- jurisdiction, topics, landing page -- can only come
    # from the author, and a project created without them starts life failing the
    # shared metadata style rule.
    interview_title = request.form.get("interview_title", "").strip()
    interview_short_title = request.form.get("interview_short_title", "").strip()
    interview_description = request.form.get("interview_description", "").strip()
    jurisdiction = request.form.get("jurisdiction", "").strip()
    landing_page_url = request.form.get("landing_page_url", "").strip()
    list_topics = [
        topic.strip()
        for topic in request.form.get("list_topics", "").split(",")
        if topic.strip()
    ]
    interview_filename = _normalize_new_interview_filename(
        request.form.get("interview_filename", "")
    )

    base_name = normalize_project_name(raw_name)
    existing = get_list_of_projects(uid)
    project_name = next_available_project_name(base_name, [*existing, "default"])

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
            f"use_llm_assist={use_llm_assist} "
            f"normalize_field_names={normalize_field_names}",
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
            validate_document_content(safe_name, content_bytes)
            requested_name = os.path.basename(str(filename).strip())
            uploaded_payloads.append(
                {
                    "filename": safe_name,
                    "requested_filename": requested_name,
                    "content_bytes": content_bytes,
                    "mimetype": mimetype,
                }
            )

        if not uploaded_payloads:
            raise ValueError("No valid files were uploaded.")

        renamed_uploads: List[Dict[str, str]] = []
        unique_names = unique_project_filenames(
            [str(payload["filename"]) for payload in uploaded_payloads]
        )
        for payload, unique_name in zip(uploaded_payloads, unique_names):
            normalized_name = str(payload["filename"])
            requested_name = str(payload.pop("requested_filename"))
            payload["filename"] = unique_name
            if unique_name == requested_name:
                continue
            if unique_name != normalized_name:
                reason = "name_collision"
                message = (
                    f"{requested_name} was saved as {unique_name} because its "
                    "normalized filename conflicts with another uploaded file. "
                    f"Refer to it as {unique_name} in your interview."
                )
            else:
                reason = "unsupported_characters"
                message = _renamed_file_message(requested_name, unique_name, reason)
            renamed_uploads.append(
                {
                    "from": requested_name,
                    "to": unique_name,
                    "reason": reason,
                    "message": message,
                }
            )

        interview_overrides: Dict[str, Any] = {
            "enable_navigation": enable_navigation,
            "next_steps_enabled": include_next_steps,
            # Feedback issues go to this owner's repository. The editor sends
            # the author's choice, which may be blank to use the server's
            # default; other callers get the suggestion the editor would show.
            "github_user": (
                github_user.strip()
                if github_user is not None
                else get_default_github_owner(
                    user_id=uid, server_owner=_server_github_owner()
                )
            ),
        }
        if interview_title:
            interview_overrides["title"] = interview_title
        if interview_short_title:
            interview_overrides["short_title"] = interview_short_title
        if interview_description:
            interview_overrides["description"] = interview_description
        if landing_page_url:
            interview_overrides["landing_page_url"] = landing_page_url
        if list_topics:
            # output.mako builds `LIST_topics` from the category selections, so
            # freeform topics travel as `other_categories`.
            interview_overrides["has_other_categories"] = True
            interview_overrides["other_categories"] = ", ".join(list_topics)
        if jurisdiction:
            interview_overrides["jurisdiction"] = jurisdiction
        if form_type != "auto":
            interview_overrides["form_type"] = form_type
            interview_overrides["court_related"] = form_type != "letter"
        if typical_role != "auto":
            interview_overrides["typical_role"] = typical_role
        if default_state:
            interview_overrides["state"] = default_state
            if not jurisdiction:
                interview_overrides["jurisdiction"] = f"NAM-US-US+{default_state}"

        generation_options: Dict[str, Any] = {
            "create_package_zip": False,
            # Keep a durable disabled shell in form projects so the setting can
            # be turned on later without reconstructing bundle/attachment YAML.
            "include_next_steps": output_type == "form",
            "include_download_screen": output_type == "form",
            "copy_baseline_questions": copy_baseline_questions,
            "separate_main_order": parse_bool(
                request.form.get("separate_main_order"), default=False
            ),
            "exact_name": uploaded_payloads[0]["filename"],
            "use_llm_assist": use_llm_assist,
            "interview_overrides": interview_overrides,
            "normalize_field_names": normalize_field_names,
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
            f"generation_options={sorted(generation_options.keys())}",
            "info",
        )
        # Validate and parse every upload before creating a Playground project.
        # A bad encrypted or truncated file should produce a clean request
        # error, not leave an empty project that looks like a partial success.
        create_project(uid, project_name)
        job_info = _start_new_project_upload_job(
            uid=uid,
            request_id=request_id,
            project_name=project_name,
            uploaded_files=uploaded_payloads,
            generation_options=generation_options,
            debug_requested=debug_requested,
            interview_filename=interview_filename,
            create_test=create_test,
            renamed_files=renamed_uploads,
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


def _template_import_target(
    uid: int, project: str, template_filename: str
) -> Tuple[str, str]:
    """Locate a template file inside the project's templates section.

    A template that predates upload renaming may still carry a name
    Docassemble cannot resolve from a `docx template file:` line. Importing it
    would write an attachment block pointing at a file the interview then
    reports as missing, so the file is renamed on the way in and the caller
    works with the name that will resolve.

    Args:
        uid (int): the Playground owner.
        project (str): the project name.
        template_filename (str): the template's filename.

    Returns:
        Tuple[str, str]: the path to the template on disk, and the name the
        project now stores it under.

    Raises:
        FileNotFoundError: when the project has no such template.
        ValueError: when the file is not a PDF or DOCX Weaver can read.
    """
    area, directory = _editor_storage_directory(
        uid, project, EDITOR_SECTION_TO_STORAGE["templates"]
    )
    path = os.path.join(directory, template_filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{template_filename} is not in this project")
    if not template_filename.lower().endswith((".pdf", ".docx")):
        raise ValueError("Only PDF and DOCX templates can be analyzed.")
    safe_filename = safe_project_filename(template_filename, default_stem="template")
    if safe_filename == template_filename:
        return path, template_filename
    safe_path = os.path.join(directory, safe_filename)
    if os.path.exists(safe_path):
        raise ValueError(
            f"{template_filename} cannot be used under a name Docassemble can "
            f"resolve, because {safe_filename} is already in this project. "
            "Rename one of them."
        )
    rename_saved_file(area, directory, template_filename, safe_filename)
    log(
        "ALWeaver editor: renamed template to a resolvable name "
        f"project={project} from={template_filename!r} to={safe_filename!r}",
        "info",
    )
    return safe_path, safe_filename


def _complete_template_import_job(
    *,
    job_id: str,
    uid: int,
    project: str,
    template_filename: str,
    interview_filename: str,
    use_llm_assist: bool,
    request_id: str,
) -> Dict[str, Any]:
    """Work out what importing one template into an interview would take.

    Args:
        job_id (str): the job record to report progress into.
        uid (int): the Playground owner.
        project (str): the project holding both files.
        template_filename (str): the template to analyze.
        interview_filename (str): the interview it would join.
        use_llm_assist (bool): whether to let AI refine labels and grouping.
        request_id (str): the originating request, for the log.

    Returns:
        Dict[str, Any]: the analysis, in the shape the editor renders.

    Raises:
        Exception: re-raised after the failure is recorded on the job.
    """
    # Imported here, not at module import: analysis pulls in the whole
    # generator, and only the worker ever runs it.
    from .template_analysis import analyze_template

    stage = "start"
    try:
        _update_job_state(
            TEMPLATE_IMPORT_JOB,
            job_id,
            status="running",
            stage=stage,
            message=f"Reading {template_filename}.",
            progress=10,
        )
        requested_filename = template_filename
        template_path, template_filename = _template_import_target(
            uid, project, template_filename
        )
        interview_yaml = playground_read_yaml(uid, project, interview_filename)

        stage = "analyze"
        _update_job_state(
            TEMPLATE_IMPORT_JOB,
            job_id,
            status="running",
            stage=stage,
            message=f"Reading the fields in {template_filename}.",
            progress=35,
        )
        analysis = analyze_template(
            template_path=template_path,
            template_filename=template_filename,
            interview_yaml=interview_yaml,
            use_llm_assist=use_llm_assist,
        )
        result = analysis.to_dict()
        result["project"] = project
        result["template_filename"] = template_filename
        # The attachment block will name the renamed file, so the author has
        # to be told the template is not called what they picked any more.
        result["renamed_files"] = (
            []
            if template_filename == requested_filename
            else [
                {
                    "from": requested_filename,
                    "to": template_filename,
                    "reason": "unsupported_characters",
                    "message": _renamed_file_message(
                        requested_filename, template_filename, "unsupported_characters"
                    ),
                }
            ]
        )
        result["interview_filename"] = interview_filename
        result["interview_revision"] = source_revision(interview_yaml)
        _update_job_state(
            TEMPLATE_IMPORT_JOB,
            job_id,
            status="succeeded",
            stage="done",
            message=f"Read {template_filename}.",
            progress=100,
            result=result,
            error=None,
            finished_at=time.time(),
        )
        return result
    except Exception as exc:
        tb = traceback.format_exc()
        _update_job_state(
            TEMPLATE_IMPORT_JOB,
            job_id,
            status="failed",
            stage=stage,
            message="Reading the template failed.",
            error={"type": "server_error", "message": str(exc)},
            finished_at=time.time(),
        )
        log(
            "ALWeaver editor: template import failed "
            f"request_id={request_id} job_id={job_id} project={project} "
            f"template={template_filename} stage={stage}: {exc!r}\n{tb}",
            "error",
        )
        raise


@app.route(f"{EDITOR_BASE_PATH}/api/template/import", methods=["POST"])
def editor_api_import_template() -> Response:
    """Queue the read of a template already sitting in the project.

    The author calls this importing: the template becomes one of the documents
    the interview assembles. Reading its fields is how that happens, and on a
    template already imported it is how a revised form gets its new ones.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        template_filename = _normalize_storage_filename(post_data.get("template"))
        interview_filename = _normalize_filename(post_data.get("filename"))
        use_llm_assist = parse_bool(post_data.get("use_llm_assist"), default=False)
        # Fail here rather than in the worker: an author who picked the wrong
        # file should hear about it now.
        requested_filename = template_filename
        _template_path, template_filename = _template_import_target(
            uid, project, template_filename
        )
        playground_read_yaml(uid, project, interview_filename)

        if not _editor_async_is_configured():
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {
                        "type": "async_not_configured",
                        "code": "editor_async_not_configured",
                        "message": (
                            "Reading a template runs in the background. Add "
                            f"{NEW_PROJECT_CELERY_MODULE!r} to the Docassemble "
                            "'celery modules' configuration list, then restart "
                            "the Docassemble web and Celery services."
                        ),
                        "details": get_worker_configuration_status(),
                    },
                },
                503,
            )

        job_id = str(uuid.uuid4())
        initial_state: Dict[str, Any] = {
            "status": "queued",
            "stage": "queued",
            "message": f"Queued a read of {template_filename}.",
            "owner_user_id": uid,
            "operation_type": "template_import",
            "project": project,
            "template": template_filename,
            # Renaming happened before the job was queued, so say so here as
            # well as on the finished analysis.
            "renamed_files": (
                []
                if template_filename == requested_filename
                else [
                    {
                        "from": requested_filename,
                        "to": template_filename,
                        "reason": "unsupported_characters",
                        "message": _renamed_file_message(
                            requested_filename,
                            template_filename,
                            "unsupported_characters",
                        ),
                    }
                ]
            ),
            "filename": interview_filename,
            "request_id": request_id,
            "celery_task_id": job_id,
            "queued_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "progress": 0,
            "result": None,
            "error": None,
        }
        _store_job_state(TEMPLATE_IMPORT_JOB, job_id, initial_state)
        workerapp.send_task(
            TEMPLATE_IMPORT_CELERY_TASK,
            task_id=job_id,
            kwargs={
                "job_id": job_id,
                "uid": uid,
                "project": project,
                "template_filename": template_filename,
                "interview_filename": interview_filename,
                "use_llm_assist": use_llm_assist,
                "request_id": request_id,
            },
        )
        return jsonify_with_status(
            {
                "success": True,
                "request_id": request_id,
                "status": "queued",
                "job_id": job_id,
                "job_url": f"{EDITOR_BASE_PATH}/api/template/import/jobs/{job_id}",
                "data": initial_state,
            },
            202,
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
        log(f"ALWeaver editor: import template error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/template/import/jobs/<job_id>", methods=["GET"])
def editor_api_import_template_job(job_id: str) -> Response:
    """Get the status of a queued template import."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        state = _load_job_state(TEMPLATE_IMPORT_JOB, job_id)
        if not state or state.get("owner_user_id") not in {None, uid}:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {"type": "not_found", "message": "Job not found."},
                },
                404,
            )
        state = _reconcile_job_state(
            TEMPLATE_IMPORT_JOB,
            job_id,
            state,
            success_message="Template read.",
            failure_message="Reading the template failed.",
        )
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "job_id": job_id,
                "status": str(state.get("status") or "queued"),
                "data": state,
            }
        )
    except Exception as exc:
        log(f"ALWeaver editor: template import job status error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


_BLOCK_ID_LINE_RE = re.compile(r"""(?m)^id:[ \t]*(?P<id>.*?)[ \t]*$""")


def _block_id_without_collision(
    block_yaml: str, taken: Set[str]
) -> Tuple[str, Optional[str]]:
    """Give a block an id no other block in the file is already using.

    An analyzed template's screens keep the ids the generator derived from
    their question text, and two interviews drafted from related forms will
    produce some of the same ones. `insert_block_in_yaml` refuses a duplicate,
    which would throw away every other accepted block along with it, so the
    newcomer is numbered instead -- the same way the generator resolves
    duplicates within one file.

    Args:
        block_yaml (str): the block about to be inserted.
        taken (Set[str]): the ids already in the file.

    Returns:
        Tuple[str, Optional[str]]: the block, and the id it ended up with.
    """
    match = _BLOCK_ID_LINE_RE.search(block_yaml)
    if not match:
        return block_yaml, None
    current = match.group("id").strip().strip("\"'")
    if not current:
        return block_yaml, None
    if current not in taken:
        return block_yaml, current
    counter = 2
    while f"{current} {counter}" in taken:
        counter += 1
    new_id = f"{current} {counter}"
    return (
        block_yaml[: match.start()] + f"id: {new_id}" + block_yaml[match.end() :],
        new_id,
    )


@app.route(f"{EDITOR_BASE_PATH}/api/template/apply", methods=["POST"])
def editor_api_apply_template_analysis() -> Response:
    """Add the accepted pieces of a template import to the interview.

    The blocks and the bundle changes land in one write, so an interview never
    ends up with an attachment whose `ALDocument` was not declared.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        expected_revision = post_data.get("expected_revision")
        if not isinstance(expected_revision, str) or not expected_revision:
            raise ValueError("expected_revision is required")
        blocks = post_data.get("blocks")
        if not isinstance(blocks, list):
            raise ValueError("blocks must be a list")
        bundle_updates = post_data.get("bundles") or []
        if not isinstance(bundle_updates, list):
            raise ValueError("bundles must be a list")
        if not blocks and not bundle_updates:
            raise ValueError("Nothing was selected to add.")

        content = playground_read_yaml(uid, project, filename)
        added_block_ids: List[str] = []
        replaced_block_ids: List[str] = []
        taken_ids = {
            str(block.get("id") or "").strip()
            for block in parse_interview_yaml(content)["blocks"]
        }
        for entry in blocks:
            # A plain string adds a block. An object with `replace_block_id`
            # rewrites one in place, which is what re-reading a revised form
            # does to its attachment block.
            replace_block_id = None
            if isinstance(entry, dict):
                block_yaml = entry.get("yaml")
                raw_replace = entry.get("replace_block_id")
                replace_block_id = str(raw_replace).strip() if raw_replace else None
            else:
                block_yaml = entry
            if not isinstance(block_yaml, str) or not block_yaml.strip():
                raise ValueError("Each block must be a non-empty YAML string")
            _validate_block_yaml_payload(block_yaml)

            if replace_block_id:
                content = update_block_in_yaml(
                    content, replace_block_id, block_yaml.strip("\r\n")
                )
                replaced_block_ids.append(replace_block_id)
                continue

            block_text, block_id = _block_id_without_collision(
                block_yaml.strip("\r\n"), taken_ids
            )
            # Appended rather than placed: an author moves blocks around in the
            # outline, and guessing at a position here would only be a guess.
            existing_blocks = parse_interview_yaml(content)["blocks"]
            insert_after_id = (
                str(existing_blocks[-1].get("id")) if existing_blocks else None
            )
            content = insert_block_in_yaml(content, block_text, insert_after_id)
            if block_id:
                taken_ids.add(block_id)
                added_block_ids.append(block_id)

        for update in bundle_updates:
            if not isinstance(update, dict):
                raise ValueError("Each bundle change must be an object")
            bundle_name = str(update.get("bundle") or "").strip()
            elements = update.get("elements")
            if not bundle_name or not isinstance(elements, list):
                raise ValueError("A bundle change needs a bundle name and elements")
            content = set_bundle_elements(content, bundle_name, elements)

        conflict = _write_source_content(
            uid, project, filename, content, post_data, request_id
        )
        if conflict is not None:
            return conflict
        updated_model = parse_interview_yaml(content)
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
                    "raw_yaml": content,
                    "revision": source_revision(content),
                    "added_block_ids": added_block_ids,
                    "replaced_block_ids": replaced_block_ids,
                    "documents": interview_documents(content).to_dict(),
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
        log(f"ALWeaver editor: apply template import error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/attachment-mappings", methods=["POST"])
def editor_api_attachment_mappings() -> Response:
    """Read actual template fields or save surgical, revision-checked field edits."""
    from .attachment_editor import attachment_mappings, update_attachment_mappings

    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        payload = request.get_json(silent=True) or {}
        uid = _current_user_id()
        project = _normalize_project(payload.get("project"))
        filename = _normalize_filename(payload.get("filename"))
        content = playground_read_yaml(uid, project, filename)
        blocks = parse_interview_yaml(content)["blocks"]
        matches = [block for block in blocks if block["id"] == payload.get("block_id")]
        if len(matches) != 1:
            raise ValueError("Select a unique attachment block.")
        block = matches[0]
        if "updates" in payload:
            expected_revision = payload.get("expected_revision")
            if not isinstance(expected_revision, str) or not expected_revision:
                raise ValueError("expected_revision is required")
            if not isinstance(payload["updates"], list):
                raise ValueError("updates must be a list")
            updated = update_attachment_mappings(block["yaml"], payload["updates"])
            content = update_block_in_yaml(content, block["id"], updated)
            conflict = _write_source_content(
                uid, project, filename, content, payload, request_id
            )
            if conflict is not None:
                return conflict
            return jsonify(
                {
                    "success": True,
                    "request_id": request_id,
                    "data": {
                        "revision": source_revision(content),
                        "raw_yaml": content,
                    },
                }
            )

        attachments = attachment_mappings(block["yaml"])
        for attachment in attachments:
            attachment["template_fields"] = []
            try:
                template = _normalize_storage_filename(attachment["template"])
                if (
                    template != attachment["template"]
                    or ":" in template
                    or "${" in template
                ):
                    raise ValueError(
                        "Template reference is external or computed; edit its mappings below or use YAML mode."
                    )
                # Reading fields must not rename or modify the template.
                _, directory = _editor_storage_directory(
                    uid, project, EDITOR_SECTION_TO_STORAGE["templates"]
                )
                path = os.path.join(directory, template)
                if not os.path.isfile(path) or os.path.islink(path):
                    raise ValueError("Template is not a local project file.")
                if not template.lower().endswith((".pdf", ".docx")):
                    raise ValueError("Choose a PDF or DOCX template in YAML mode.")
                attachment["template_fields"] = _local_template_field_names(path)
            except Exception as exc:
                attachment["warning"] = f"Could not check template fields: {exc}"
        return jsonify(
            {
                "success": True,
                "request_id": request_id,
                "data": {
                    "revision": source_revision(content),
                    "attachments": attachments,
                },
            }
        )
    except (ValueError, yaml.YAMLError, FileNotFoundError) as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": str(exc)},
            },
            400,
        )
    except Exception as exc:
        log(f"ALWeaver editor: attachment mappings error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


@app.route(f"{EDITOR_BASE_PATH}/api/documents", methods=["GET"])
def editor_api_documents() -> Response:
    """List the documents an interview assembles, and the bundles they sit in."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        content = playground_read_yaml(uid, project, filename)
        data = interview_documents(content).to_dict()
        template_files = [
            str(item.get("filename") or "")
            for item in _list_editor_section_files(uid, project, "templates")
        ]
        data.update(
            {
                "project": project,
                "filename": filename,
                "revision": source_revision(content),
                "templates": template_status(content, template_files),
            }
        )
        return jsonify({"success": True, "request_id": request_id, "data": data})
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
        log(f"ALWeaver editor: documents error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )


def _document_removal_references(
    user_id: int, project: str, filename: str, candidate: str, names: List[str]
) -> List[Dict[str, Any]]:
    """Find remaining executable or ambiguous references after a deletion."""
    from .editor_agent_rename import analyze_rename

    references = []
    for source_name in dict.fromkeys(
        [filename] + _project_yaml_filenames(user_id, project)
    ):
        content = (
            candidate
            if source_name == filename
            else playground_read_yaml(user_id, project, source_name)
        )
        for name in names:
            analysis = analyze_rename(
                filename=source_name,
                raw_yaml=content,
                old_name=name,
                new_name="weaver_removed_document_reference",
            )
            for occurrence in analysis.safe_occurrences + analysis.blocking_occurrences:
                references.append(
                    {
                        "filename": source_name,
                        "document": name,
                        **occurrence.public_dict(),
                    }
                )
    return references


@app.route(f"{EDITOR_BASE_PATH}/api/documents", methods=["POST"])
def editor_api_save_documents() -> Response:
    """Reorder an interview's documents, or change what turns them on.

    Both are edits to `.using()` arguments inside `objects:` declarations:
    `elements=[...]` is the order the bundle assembles, and `enabled=` is the
    rule that decides whether a document is in the download at all.
    """
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        post_data = request.get_json(silent=True) or {}
        project = _normalize_project(post_data.get("project"))
        filename = _normalize_filename(post_data.get("filename"))
        expected_revision = post_data.get("expected_revision")
        if not isinstance(expected_revision, str) or not expected_revision:
            raise ValueError("expected_revision is required")
        bundle_updates = post_data.get("bundles") or []
        enabled_updates = post_data.get("enabled") or []
        removals = post_data.get("remove") or []
        if not isinstance(removals, list) or any(
            not isinstance(name, str) for name in removals
        ):
            raise ValueError("remove must be a list of document names")
        if not isinstance(bundle_updates, list) or not isinstance(
            enabled_updates, list
        ):
            raise ValueError("bundles and enabled must be lists")
        if not bundle_updates and not enabled_updates and not removals:
            raise ValueError("Nothing was changed.")

        content = playground_read_yaml(uid, project, filename)
        original_content = content
        for update in bundle_updates:
            if not isinstance(update, dict):
                raise ValueError("Each bundle change must be an object")
            bundle_name = str(update.get("bundle") or "").strip()
            elements = update.get("elements")
            if not bundle_name or not isinstance(elements, list):
                raise ValueError("A bundle change needs a bundle name and elements")
            content = set_bundle_elements(content, bundle_name, elements)

        for update in enabled_updates:
            if not isinstance(update, dict):
                raise ValueError("Each enabled change must be an object")
            name = str(update.get("name") or "").strip()
            if not name:
                raise ValueError("An enabled change needs the variable's name")
            raw_expression = update.get("expression")
            expression = None if raw_expression is None else str(raw_expression)
            content = set_enabled_expression(content, name, expression)

        for name in removals:
            content = remove_document(content, name)

        if removals:
            references = _document_removal_references(
                uid, project, filename, content, removals
            )
            plan = {
                "diff": unified_source_diff(original_content, content, filename),
                "references": references,
                "removed": removals,
                "blocked": bool(references),
                "revision": source_revision(original_content),
            }
            if parse_bool(post_data.get("preview"), default=False):
                return jsonify(
                    {"success": True, "request_id": request_id, "data": plan}
                )
            if references:
                locations = ", ".join(
                    f"{item['filename']}:{item['line']} ({item['document']})"
                    for item in references[:10]
                )
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "document_has_references",
                            "message": "Document removal was not saved. Resolve remaining references first: "
                            + locations,
                            "details": plan,
                        },
                    },
                    409,
                )

        # Deleting a declaration must not leave an unresolved YAML alias.
        try:
            list(yaml.compose_all(content))
        except yaml.YAMLError as exc:
            raise ValueError(
                f"The document changes would invalidate the YAML: {exc}"
            ) from exc

        conflict = _write_source_content(
            uid, project, filename, content, post_data, request_id
        )
        if conflict is not None:
            return conflict
        updated_model = parse_interview_yaml(content)
        data = interview_documents(content).to_dict()
        data.update(
            {
                "project": project,
                "filename": filename,
                "revision": source_revision(content),
                "blocks": updated_model["blocks"],
                "raw_yaml": content,
            }
        )
        return jsonify({"success": True, "request_id": request_id, "data": data})
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
        log(f"ALWeaver editor: save documents error: {exc!r}", "error")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "server_error", "message": str(exc)},
            },
            500,
        )

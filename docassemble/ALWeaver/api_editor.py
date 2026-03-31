# pre-load

"""Flask endpoints for the WYSIWYM interview editor.

Provides:
    GET  /al/editor              — serve the editor single-page application
    GET  /al/editor/api/projects — list playground projects
    GET  /al/editor/api/files    — list YAML files in a project
    GET  /al/editor/api/file     — read & parse a YAML file
    POST /al/editor/api/file     — save full YAML back to a file
    POST /al/editor/api/block    — update a single block in-place
    POST /al/editor/api/insert-block — insert a new block at a target position
    GET  /al/editor/api/variables — extract variable names from a file
    POST /al/editor/api/order    — save order-builder steps as code
    POST /al/editor/api/ai/generate-screen — draft one question screen with AI
    POST /al/editor/api/ai/generate-fields — draft fields for a question with AI
    POST /al/editor/api/new-project — create a project (optionally via Weaver)
    GET  /al/editor/api/parse-order — parse order code into structured steps
    POST /al/editor/api/draft-order — generate a draft order from blocks
    GET  /al/editor/api/preview-url — get the interview preview URL
"""

from __future__ import annotations

import importlib.resources
import json
import mimetypes
import os
import re
import shutil
import textwrap
import tempfile
import uuid
from copy import deepcopy
from html import escape
from urllib.parse import quote
from typing import Any, Dict, List, Optional

from flask import Response, jsonify, request
from flask_cors import cross_origin
from flask_login import current_user

from docassemble.base.util import log
from docassemble.webapp.app_object import app, csrf
from docassemble.webapp.server import jsonify_with_status

from .api_utils import generate_interview_from_bytes, validate_upload_metadata
from .editor_utils import (
    canonical_block_yaml,
    canonicalize_block_yaml,
    generate_draft_order,
    parse_interview_yaml,
    parse_order_code,
    playground_get_variables,
    playground_interview_url,
    playground_list_projects,
    playground_list_yaml_files,
    playground_read_yaml,
    playground_write_yaml,
    serialize_blocks_to_yaml,
    serialize_order_steps,
    update_block_in_yaml,
)
from .editor_ai_utils import (
    DEFAULT_FIELD_TYPES,
    normalize_generated_fields,
    normalize_generated_screen,
    pick_small_model_name,
    validate_yaml_with_dayamlchecker,
)
from .playground_publish import (
    SECTION_TO_STORAGE,
    _copy_files_to_section,
    create_project,
    get_list_of_projects,
    next_available_project_name,
    normalize_project_name,
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

DEFAULT_DASHBOARD_EDITOR_URLS = {
    "pdf": "/al/pdf-labeler?project={project}&filename={filename}",
    "docx": "/al/docx-labeler?project={project}&filename={filename}",
}


# ---------------------------------------------------------------------------
# Auth helpers (mirror ALDashboard session-cookie pattern)
# ---------------------------------------------------------------------------

def _editor_auth_check() -> bool:
    """Return True when the browser session belongs to an authenticated user."""
    try:
        return bool(current_user.is_authenticated)
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
        if next_target.startswith("/"):
            return next_target
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


def _editor_storage_directory(user_id: int, project: str, storage_section: str) -> tuple[Any, str]:
    from docassemble.webapp.files import SavedFile

    area = SavedFile(user_id, fix=True, section=storage_section)
    directory = area.directory if project == "default" else os.path.join(area.directory, project)
    os.makedirs(directory, exist_ok=True)
    return area, directory


def _editor_playground_directory(user_id: int, project: str) -> tuple[Any, str]:
    from docassemble.webapp.files import SavedFile

    area = SavedFile(user_id, fix=True, section="playground")
    directory = area.directory if project == "default" else os.path.join(area.directory, project)
    os.makedirs(directory, exist_ok=True)
    return area, directory


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
    return pattern.format(project=quote(project, safe="/"), filename=quote(filename, safe=""))


def _list_editor_section_files(user_id: int, project: str, section: str) -> List[Dict[str, Any]]:
    storage_section = EDITOR_SECTION_TO_STORAGE[section]
    _area, directory = _editor_storage_directory(user_id, project, storage_section)
    if not os.path.isdir(directory):
        return []
    items: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(directory), key=lambda v: (_is_placeholder_file(v), v.lower())):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        guessed_mimetype, _enc = mimetypes.guess_type(name)
        mimetype_value = guessed_mimetype or "application/octet-stream"
        editable = _is_text_editable(name, mimetype_value) and not _is_placeholder_file(name)
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
    except Exception:
        pass
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
    except Exception:
        pass
    return ""


def _render_editor_page() -> str:
    """Build the editor HTML, injecting bootstrap JSON for the logged-in user."""
    html = _get_template_content("editor.html")
    if not html:
        return ""
    login_url, logout_url = _editor_auth_urls()
    bootstrap: Dict[str, Any] = {
        "apiBasePath": EDITOR_BASE_PATH,
        "auth": {
            "authenticated": False,
            "loginUrl": login_url,
            "logoutUrl": logout_url,
        },
    }
    try:
        if _editor_auth_check():
            uid = _current_user_id()
            bootstrap["projects"] = playground_list_projects(uid)
            bootstrap["authenticated"] = True
            bootstrap["auth"]["authenticated"] = True
            bootstrap["auth"]["email"] = getattr(current_user, "email", None)
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


def _question_block_by_id(blocks: List[Dict[str, Any]], block_id: str) -> Optional[Dict[str, Any]]:
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


def _project_template_context_text(user_id: int, project: str, max_chars: int = 8000) -> str:
    """Extract lightweight context from uploaded templates in playgroundtemplate."""
    try:
        from docassemble.webapp.files import SavedFile
    except Exception:
        return ""

    area = SavedFile(user_id, fix=False, section=SECTION_TO_STORAGE["templates"])
    project_dir = area.directory if project == "default" else os.path.join(area.directory, project)
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


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@app.route(EDITOR_BASE_PATH, methods=["GET"])
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
def editor_page() -> Response:
    """Serve the WYSIWYM interview editor page."""
    log("ALWeaver: Serving editor page", "info")
    html = _render_editor_page()
    if not html:
        log("ALWeaver: editor template not found", "error")
        return Response(
            "Editor template not found.", status=500, mimetype="text/plain"
        )
    return Response(html, mimetype="text/html")


@app.route(f"{EDITOR_BASE_PATH}/static/<path:filename>", methods=["GET"])
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
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
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
def editor_api_projects() -> Response:
    """List playground projects for the current user."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {"projects": playground_list_projects(uid)},
        })
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


@app.route(f"{EDITOR_BASE_PATH}/api/files", methods=["GET"])
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
def editor_api_files() -> Response:
    """List YAML files in a playground project."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {
                "project": project,
                "files": playground_list_yaml_files(uid, project),
            },
        })
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


@app.route(f"{EDITOR_BASE_PATH}/api/section-files", methods=["GET"])
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
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
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
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
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
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
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
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
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
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
            raise ValueError("Dashboard editor is only available for PDF and DOCX templates")
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
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
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

        return jsonify({
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
            },
        })
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


@app.route(f"{EDITOR_BASE_PATH}/api/file", methods=["POST"])
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {
                "project": project,
                "filename": filename,
                "size": len(content),
            },
        })
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


@app.route(f"{EDITOR_BASE_PATH}/api/file/rename", methods=["POST"])
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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
        new_filename = _normalize_filename(post_data.get("new_filename"))
        if old_filename == new_filename:
            raise ValueError("New filename must be different")
        _area, directory = _editor_playground_directory(uid, project)
        old_path = os.path.join(directory, old_filename)
        if not os.path.isfile(old_path):
            raise FileNotFoundError(f"{old_filename} not found")
        new_path = os.path.join(directory, new_filename)
        if os.path.exists(new_path):
            raise ValueError(f"{new_filename} already exists")
        os.rename(old_path, new_path)
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


@app.route(f"{EDITOR_BASE_PATH}/api/section-file/rename", methods=["POST"])
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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
        new_filename = _normalize_storage_filename(post_data.get("new_filename"))
        if old_filename == new_filename:
            raise ValueError("New filename must be different")
        storage_section = EDITOR_SECTION_TO_STORAGE[section]
        _area, directory = _editor_storage_directory(uid, project, storage_section)
        old_path = os.path.join(directory, old_filename)
        if not os.path.isfile(old_path):
            raise FileNotFoundError(f"{old_filename} not found")
        new_path = os.path.join(directory, new_filename)
        if os.path.exists(new_path):
            raise ValueError(f"{new_filename} already exists")
        os.rename(old_path, new_path)
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


@app.route(f"{EDITOR_BASE_PATH}/api/block", methods=["POST"])
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {
                "project": project,
                "filename": filename,
                "blocks": model["blocks"],
                "metadata_blocks": model["metadata_blocks"],
                "include_blocks": model["include_blocks"],
                "default_screen_parts_blocks": model[
                    "default_screen_parts_blocks"
                ],
                "order_blocks": model["order_blocks"],
                "order_steps": order_steps,
                "order_step_map": order_step_map,
                "raw_yaml": updated_content,
                "saved_block_id": block_id,
            },
        })
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


@app.route(f"{EDITOR_BASE_PATH}/api/insert-block", methods=["POST"])
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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

        current_content = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(current_content)
        blocks = model["blocks"]

        block_text = canonicalize_block_yaml(block_yaml)
        existing_parts = [
            b["yaml"].strip()
            for b in blocks
            if b.get("yaml", "").strip() and b.get("yaml", "").strip() != "{}"
        ]

        if not insert_after_id:
            insert_at = 0
        else:
            insert_at = None
            for idx, block in enumerate(blocks):
                if block.get("id") == insert_after_id:
                    insert_at = idx + 1
                    break
            if insert_at is None:
                raise ValueError(f"Block with id {insert_after_id!r} not found")

        existing_parts.insert(insert_at, block_text)
        updated_content = "\n---\n".join(existing_parts) + "\n"
        playground_write_yaml(uid, project, filename, updated_content)

        updated_model = parse_interview_yaml(updated_content)
        inserted_block_id = None
        id_match = re.search(
            r"(?m)^id:\s*['\"]?([^'\"\n]+)['\"]?\s*$", block_text
        )
        if id_match:
            inserted_block_id = id_match.group(1).strip()
        elif 0 <= insert_at < len(updated_model["blocks"]):
            inserted_block_id = updated_model["blocks"][insert_at].get("id")

        return jsonify({
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
        })
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
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
def editor_api_variables() -> Response:
    """Get extracted variable names from a playground YAML file."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        uid = _current_user_id()
        project = _normalize_project(request.args.get("project"))
        filename = _normalize_filename(request.args.get("filename"))
        data = playground_get_variables(uid, project, filename)
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": data,
        })
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
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
def editor_api_save_order() -> Response:
    """Save order-builder steps as a mandatory code block."""
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
            block_data["id"] = str(block_data.get("id") or target_block.get("id") or "interview_order")
            block_data["mandatory"] = True
            block_data["code"] = code_body
            order_yaml = canonical_block_yaml(block_data)
            updated = update_block_in_yaml(current_content, target_block["id"], order_yaml)
        else:
            # Append a new mandatory code block
            order_yaml = f"id: interview_order\nmandatory: True\ncode: |\n{code_body}"
            updated = current_content.rstrip() + "\n---\n" + order_yaml + "\n"

        playground_write_yaml(uid, project, filename, updated)
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {
                "project": project,
                "filename": filename,
                "order_block_id": target_block.get("id") if target_block else "interview_order",
                "order_yaml": order_yaml,
            },
        })
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
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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

        system_message = textwrap.dedent(
            """
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
            """
        ).strip()

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

        candidate_block = deepcopy(current_block_data if isinstance(current_block_data, dict) else {})
        candidate_block["id"] = str(candidate_block.get("id") or block_id or "ai_generated_screen")
        candidate_block["question"] = screen.get("question")
        if screen.get("subquestion"):
            candidate_block["subquestion"] = screen.get("subquestion")
        candidate_block["fields"] = screen.get("fields") or []
        if screen.get("continue_button_field"):
            candidate_block["continue button field"] = screen.get("continue_button_field")

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
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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

        system_message = textwrap.dedent(
            """
            You are generating fields for ONE docassemble question screen.
            Return ONLY JSON with key:
              fields: array of {label, field, datatype, choices?}

            Rules:
            - Usually return 2-3 fields for a normal screen.
            - Never return more than 7 fields.
            - Choose datatypes from the provided allowed list.
            - Keep labels plain and user-friendly.
            - Keep variable names python-safe snake_case.
            """
        ).strip()

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
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
def editor_api_parse_order() -> Response:
    """Parse order code text into structured steps (no file required)."""
    request_id = str(uuid.uuid4())
    if not _editor_auth_check():
        return _auth_fail(request_id)
    try:
        code = request.args.get("code", "")
        steps = parse_order_code(code)
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {"steps": steps},
        })
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
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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

        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {"steps": steps},
        })
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


@app.route(f"{EDITOR_BASE_PATH}/api/preview-url", methods=["GET"])
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
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
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {"url": url},
        })
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


@app.route(f"{EDITOR_BASE_PATH}/api/new-project", methods=["POST"])
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
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

        # Detect whether this is a file-upload request
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
        except Exception:
            pass

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

    return jsonify({
        "success": True,
        "request_id": request_id,
        "data": {
            "project": project_name,
            "filename": "interview.yml",
            "template_id": template_id,
        },
    })


def _new_project_from_uploads(
    uid: int, request_id: str, uploaded_files: list
) -> Response:
    """'I'm feeling lucky' mode — generate a scaffolded interview from uploads.

    Accepts one or more PDF/DOCX files. Runs ``generate_interview_from_bytes``
    on the first file to produce a draft YAML, writes it to a new playground
    project, and copies all uploaded originals into the templates section.
    """
    raw_name = request.form.get("project_name", "NewProject")
    generation_notes = request.form.get("generation_notes", "").strip()

    base_name = normalize_project_name(raw_name)
    existing = get_list_of_projects(uid)
    project_name = next_available_project_name(base_name, [*existing, "default"])
    create_project(uid, project_name)

    # Validate & read every uploaded file; save to temp dir so we can
    # pass the paths to _copy_files_to_section afterwards.
    temp_dir = tempfile.mkdtemp(prefix="editor-upload-")
    temp_paths: List[str] = []
    first_result: Optional[Dict[str, Any]] = None

    try:
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

            # Persist to temp so _copy_files_to_section can copy it
            dest = os.path.join(temp_dir, safe_name)
            with open(dest, "wb") as fh:
                fh.write(content_bytes)
            temp_paths.append(dest)

            # Generate from the first file only
            if first_result is None:
                generation_options: Dict[str, Any] = {}
                if generation_notes:
                    generation_options["title"] = generation_notes
                first_result = generate_interview_from_bytes(
                    filename=safe_name,
                    content_bytes=content_bytes,
                    mimetype=mimetype,
                    generation_options=generation_options,
                    include_yaml_text=True,
                )

        if first_result is None:
            raise ValueError("No valid files were uploaded.")

        yaml_text = first_result.get("yaml_text", "")
        if not yaml_text:
            raise ValueError("Weaver did not produce any YAML output for the uploaded file.")

        # Write generated YAML
        playground_write_yaml(uid, project_name, "interview.yml", yaml_text)

        # Copy uploaded template originals into the playground templates section
        _copy_files_to_section(
            user_id=uid,
            project_name=project_name,
            storage_section=SECTION_TO_STORAGE["templates"],
            files=temp_paths,
        )

        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {
                "project": project_name,
                "filename": "interview.yml",
                "generated_from": first_result.get("input_filename"),
                "uploaded_count": len(temp_paths),
            },
        })
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

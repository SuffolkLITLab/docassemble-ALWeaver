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
    POST /al/editor/api/new-project — create a project (optionally via Weaver)
    GET  /al/editor/api/parse-order — parse order code into structured steps
    POST /al/editor/api/draft-order — generate a draft order from blocks
    GET  /al/editor/api/preview-url — get the interview preview URL
"""

from __future__ import annotations

import importlib.resources
import json
import os
import re
import shutil
import tempfile
import uuid
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

        # Also parse order blocks into structured steps
        order_steps: list = []
        for idx in model.get("order_blocks", []):
            block = model["blocks"][idx]
            code = block.get("data", {}).get("code", "")
            if code:
                order_steps = parse_order_code(code)
                break  # use first mandatory code block

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
        order_steps: list = []
        for idx in model.get("order_blocks", []):
            block = model["blocks"][idx]
            code = block.get("data", {}).get("code", "")
            if code:
                order_steps = parse_order_code(code)
                break
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
        steps = post_data.get("steps")
        if not isinstance(steps, list):
            raise ValueError("steps must be a list of order step objects")

        code_body = serialize_order_steps(steps)
        order_yaml = f"id: interview_order\nmandatory: True\ncode: |\n{code_body}"

        # Load the current file, find the order block, and replace it
        current_content = playground_read_yaml(uid, project, filename)
        model = parse_interview_yaml(current_content)

        if model["order_blocks"]:
            order_block_id = model["blocks"][model["order_blocks"][0]]["id"]
            updated = update_block_in_yaml(current_content, order_block_id, order_yaml)
        else:
            # Append a new mandatory code block
            updated = current_content.rstrip() + "\n---\n" + order_yaml + "\n"

        playground_write_yaml(uid, project, filename, updated)
        return jsonify({
            "success": True,
            "request_id": request_id,
            "data": {
                "project": project,
                "filename": filename,
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

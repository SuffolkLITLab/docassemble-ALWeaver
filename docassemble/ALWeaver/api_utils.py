import base64
import binascii
import json
import os
import shutil
import tempfile
from typing import Any, Dict, Mapping, Optional, Tuple

from .interview_generator import generate_interview_from_path

WEAVER_API_BASE_PATH = "/al/api/v1/weaver"

DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

ALLOWED_EXTENSION_TO_MIMETYPE = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_MIMETYPE_TO_EXTENSION = {
    mimetype: extension for extension, mimetype in ALLOWED_EXTENSION_TO_MIMETYPE.items()
}


class WeaverAPIValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "off"}:
            return False
    raise WeaverAPIValidationError(f"Could not parse boolean value {value!r}.")


def decode_base64_content(content: Any) -> bytes:
    if not isinstance(content, str) or not content.strip():
        raise WeaverAPIValidationError(
            "file_content_base64 must be a non-empty base64-encoded string."
        )
    try:
        return base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error):
        raise WeaverAPIValidationError("file_content_base64 is not valid base64 data.")


def _load_json_field(
    raw_value: Any, *, field_name: str, expected_type: type
) -> Optional[Any]:
    if raw_value is None:
        return None
    value = raw_value
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if stripped == "":
            return None
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            raise WeaverAPIValidationError(
                f"{field_name} must be valid JSON when provided as a string."
            )
    if not isinstance(value, expected_type):
        raise WeaverAPIValidationError(
            f"{field_name} must be a {expected_type.__name__}."
        )
    return value


def coerce_generation_options(raw_options: Mapping[str, Any]) -> Dict[str, Any]:
    options: Dict[str, Any] = {}

    for key in (
        "title",
        "jurisdiction",
        "categories",
        "default_country_code",
        "output_mako_choice",
    ):
        value = raw_options.get(key)
        if value is not None and value != "":
            options[key] = str(value)

    for key in ("create_package_zip", "include_next_steps", "include_download_screen"):
        if key in raw_options and raw_options.get(key) is not None:
            options[key] = parse_bool(raw_options.get(key), default=False)

    interview_overrides = _load_json_field(
        raw_options.get("interview_overrides"),
        field_name="interview_overrides",
        expected_type=dict,
    )
    if interview_overrides is not None:
        options["interview_overrides"] = interview_overrides

    field_definitions = _load_json_field(
        raw_options.get("field_definitions"),
        field_name="field_definitions",
        expected_type=list,
    )
    if field_definitions is not None:
        options["field_definitions"] = field_definitions

    screen_definitions = _load_json_field(
        raw_options.get("screen_definitions"),
        field_name="screen_definitions",
        expected_type=list,
    )
    if screen_definitions is not None:
        options["screen_definitions"] = screen_definitions

    return options


def coerce_response_flags(raw_options: Mapping[str, Any]) -> Dict[str, bool]:
    return {
        "include_package_zip_base64": parse_bool(
            raw_options.get("include_package_zip_base64"), default=False
        ),
        "include_yaml_text": parse_bool(
            raw_options.get("include_yaml_text"), default=True
        ),
    }


def merge_raw_options(raw_options: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(raw_options)
    options_blob = raw_options.get("options")
    parsed_options = _load_json_field(
        options_blob, field_name="options", expected_type=dict
    )
    if parsed_options:
        for key, value in parsed_options.items():
            merged.setdefault(key, value)
    return merged


def coerce_async_flag(raw_options: Mapping[str, Any]) -> bool:
    mode = raw_options.get("mode")
    if mode is not None and str(mode).strip() != "":
        normalized_mode = str(mode).strip().lower()
        if normalized_mode in {"async", "asynchronous"}:
            return True
        if normalized_mode in {"sync", "synchronous"}:
            return False
        raise WeaverAPIValidationError("mode must be either 'sync' or 'async'.")
    if "async" in raw_options and raw_options.get("async") is not None:
        return parse_bool(raw_options.get("async"), default=False)
    return False


def validate_upload_metadata(
    *,
    filename: str,
    content_bytes: bytes,
    mimetype: Optional[str] = None,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> Tuple[str, str]:
    if not filename:
        raise WeaverAPIValidationError("filename is required.")
    if len(content_bytes) == 0:
        raise WeaverAPIValidationError("Uploaded file is empty.")
    if len(content_bytes) > max_upload_bytes:
        raise WeaverAPIValidationError(
            f"Uploaded file is larger than {max_upload_bytes} bytes.",
            status_code=413,
        )

    safe_filename = os.path.basename(filename)
    extension = os.path.splitext(safe_filename)[1].lower()
    normalized_mimetype = (mimetype or "").split(";")[0].strip().lower()

    if extension not in ALLOWED_EXTENSION_TO_MIMETYPE:
        inferred_extension = ALLOWED_MIMETYPE_TO_EXTENSION.get(normalized_mimetype)
        if inferred_extension is None:
            raise WeaverAPIValidationError(
                "Only PDF and DOCX uploads are supported.",
                status_code=415,
            )
        extension = inferred_extension
        safe_filename = (
            safe_filename + extension if "." not in safe_filename else safe_filename
        )

    return safe_filename, extension


def generate_interview_from_bytes(
    *,
    filename: str,
    content_bytes: bytes,
    mimetype: Optional[str],
    generation_options: Mapping[str, Any],
    include_package_zip_base64: bool = False,
    include_yaml_text: bool = True,
) -> Dict[str, Any]:
    safe_filename, extension = validate_upload_metadata(
        filename=filename, content_bytes=content_bytes, mimetype=mimetype
    )

    output_dir = tempfile.mkdtemp(prefix="alweaver-api-")
    input_path: Optional[str] = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=extension, dir=output_dir, delete=False
        ) as handle:
            input_path = handle.name
            handle.write(content_bytes)

        result = generate_interview_from_path(
            input_path=input_path,
            output_dir=output_dir,
            **generation_options,
        )

        payload: Dict[str, Any] = {"input_filename": safe_filename}
        if include_yaml_text:
            payload["yaml_text"] = result.yaml_text
        if result.yaml_path:
            payload["yaml_filename"] = os.path.basename(result.yaml_path)

        if result.package_zip_path and os.path.exists(result.package_zip_path):
            payload["package_zip_filename"] = os.path.basename(result.package_zip_path)
            if include_package_zip_base64:
                with open(result.package_zip_path, "rb") as zip_handle:
                    payload["package_zip_base64"] = base64.b64encode(
                        zip_handle.read()
                    ).decode("ascii")

        return payload
    finally:
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
        shutil.rmtree(output_dir, ignore_errors=True)


def build_openapi_spec() -> Dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ALWeaver API",
            "version": "1.0.0",
            "description": (
                "Generate a draft docassemble interview from an uploaded PDF or DOCX template."
            ),
        },
        "paths": {
            WEAVER_API_BASE_PATH: {
                "post": {
                    "summary": "Generate interview artifacts from an uploaded template",
                    "description": (
                        "Supports multipart/form-data uploads and JSON payloads with "
                        "base64-encoded file content."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file"],
                                    "properties": {
                                        "file": {"type": "string", "format": "binary"},
                                        "title": {"type": "string"},
                                        "jurisdiction": {"type": "string"},
                                        "categories": {"type": "string"},
                                        "default_country_code": {"type": "string"},
                                        "output_mako_choice": {"type": "string"},
                                        "create_package_zip": {"type": "boolean"},
                                        "include_next_steps": {"type": "boolean"},
                                        "include_download_screen": {"type": "boolean"},
                                        "field_definitions": {"type": "string"},
                                        "screen_definitions": {"type": "string"},
                                        "interview_overrides": {"type": "string"},
                                        "include_package_zip_base64": {
                                            "type": "boolean"
                                        },
                                        "include_yaml_text": {"type": "boolean"},
                                        "async": {"type": "boolean"},
                                        "mode": {
                                            "type": "string",
                                            "enum": ["sync", "async"],
                                        },
                                        "options": {
                                            "type": "string",
                                            "description": "JSON object of generation options.",
                                        },
                                    },
                                }
                            },
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["filename", "file_content_base64"],
                                    "properties": {
                                        "filename": {"type": "string"},
                                        "mimetype": {"type": "string"},
                                        "file_content_base64": {"type": "string"},
                                        "title": {"type": "string"},
                                        "jurisdiction": {"type": "string"},
                                        "categories": {"type": "string"},
                                        "default_country_code": {"type": "string"},
                                        "output_mako_choice": {"type": "string"},
                                        "create_package_zip": {"type": "boolean"},
                                        "include_next_steps": {"type": "boolean"},
                                        "include_download_screen": {"type": "boolean"},
                                        "field_definitions": {
                                            "type": "array",
                                            "items": {"type": "object"},
                                        },
                                        "screen_definitions": {
                                            "type": "array",
                                            "items": {"type": "object"},
                                        },
                                        "interview_overrides": {"type": "object"},
                                        "include_package_zip_base64": {
                                            "type": "boolean"
                                        },
                                        "include_yaml_text": {"type": "boolean"},
                                        "async": {"type": "boolean"},
                                        "mode": {
                                            "type": "string",
                                            "enum": ["sync", "async"],
                                        },
                                    },
                                }
                            },
                        },
                    },
                    "responses": {
                        "200": {"description": "Interview generated."},
                        "202": {"description": "Job accepted for async processing."},
                        "400": {"description": "Invalid request."},
                        "403": {"description": "Access denied."},
                        "413": {"description": "Upload too large."},
                        "415": {"description": "Unsupported media type."},
                        "503": {"description": "Async mode is not configured."},
                        "500": {"description": "Internal server error."},
                    },
                }
            },
            f"{WEAVER_API_BASE_PATH}/jobs/{{job_id}}": {
                "get": {
                    "summary": "Get async job status and result",
                    "parameters": [
                        {
                            "name": "job_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                },
                "delete": {
                    "summary": "Delete async job metadata",
                    "parameters": [
                        {
                            "name": "job_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                },
            },
            f"{WEAVER_API_BASE_PATH}/openapi.json": {
                "get": {"summary": "Get OpenAPI document"}
            },
            f"{WEAVER_API_BASE_PATH}/docs": {"get": {"summary": "Human-readable docs"}},
        },
    }


def build_docs_html() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ALWeaver API Docs</title>
  <style>
    body {{
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      margin: 2rem auto;
      max-width: 860px;
      line-height: 1.45;
      padding: 0 1rem;
      color: #1f2937;
      background: linear-gradient(180deg, #f8fafc, #ffffff);
    }}
    code {{ background: #f1f5f9; padding: 0.1rem 0.3rem; border-radius: 4px; }}
    pre {{
      background: #0f172a;
      color: #e2e8f0;
      padding: 1rem;
      border-radius: 8px;
      overflow: auto;
    }}
    a {{ color: #0f766e; }}
  </style>
</head>
<body>
  <h1>ALWeaver API v1</h1>
  <p><strong>Primary endpoint:</strong> <code>POST {WEAVER_API_BASE_PATH}</code></p>
  <p><strong>OpenAPI:</strong> <a href="{WEAVER_API_BASE_PATH}/openapi.json">{WEAVER_API_BASE_PATH}/openapi.json</a></p>
  <h2>Auth</h2>
  <p>Uses docassemble API key authentication (<code>api_verify()</code>).</p>
  <h2>Multipart example</h2>
  <pre>curl -X POST \\
  -H "X-API-Key: &lt;DOCASSEMBLE_API_KEY&gt;" \\
  -F "file=@template.pdf" \\
  -F "title=My interview" \\
  -F "include_next_steps=false" \\
  -F "create_package_zip=true" \\
  {WEAVER_API_BASE_PATH}</pre>
  <h2>Optional async mode</h2>
  <pre>curl -X POST \\
  -H "X-API-Key: &lt;DOCASSEMBLE_API_KEY&gt;" \\
  -F "file=@template.pdf" \\
  -F "mode=async" \\
  {WEAVER_API_BASE_PATH}</pre>
  <p>Then poll <code>GET {WEAVER_API_BASE_PATH}/jobs/&lt;job_id&gt;</code> until <code>status</code> is <code>succeeded</code> or <code>failed</code>.</p>
  <p>Async mode requires docassemble config:<br><code>celery modules: [docassemble.ALWeaver.api_weaver_worker]</code></p>
  <h2>JSON example</h2>
  <pre>{{
  "filename": "template.docx",
  "file_content_base64": "&lt;base64-content&gt;",
  "title": "My interview",
  "include_next_steps": false,
  "create_package_zip": true,
  "mode": "sync"
}}</pre>
</body>
</html>
"""

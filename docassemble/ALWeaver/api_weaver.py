# pre-load

import json
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from flask import Response, jsonify, request
from flask_cors import cross_origin

from docassemble.base.config import daconfig, in_celery
from docassemble.base.util import log
from docassemble.webapp.app_object import app, csrf
from docassemble.webapp.server import api_verify, jsonify_with_status, r
from docassemble.webapp.worker_common import workerapp

from .api_utils import (
    WEAVER_API_BASE_PATH,
    WeaverAPIValidationError,
    build_docs_html,
    build_openapi_spec,
    coerce_async_flag,
    coerce_generation_options,
    coerce_response_flags,
    decode_base64_content,
    generate_interview_from_bytes,
    merge_raw_options,
)

__all__ = []
JOB_KEY_PREFIX = "da:alweaver:job:"
JOB_KEY_EXPIRE_SECONDS = 24 * 60 * 60
ASYNC_CELERY_MODULE = "docassemble.ALWeaver.api_weaver_worker"

if not in_celery:
    from .api_weaver_worker import weaver_generate_task


def _async_is_configured() -> bool:
    celery_modules = daconfig.get("celery modules", []) or []
    return ASYNC_CELERY_MODULE in celery_modules


def _job_key(job_id: str) -> str:
    return JOB_KEY_PREFIX + job_id


def _store_job_mapping(job_id: str, task_id: str) -> None:
    payload = {"id": task_id, "created_at": time.time()}
    pipe = r.pipeline()
    pipe.set(_job_key(job_id), json.dumps(payload))
    pipe.expire(_job_key(job_id), JOB_KEY_EXPIRE_SECONDS)
    pipe.execute()


def _fetch_job_mapping(job_id: str) -> Optional[Dict[str, Any]]:
    raw = r.get(_job_key(job_id))
    if raw is None:
        return None
    try:
        return json.loads(raw.decode())
    except Exception:
        return None


def _parse_request_payload() -> (
    Tuple[str, Optional[str], bytes, Dict[str, Any], Dict[str, bool], bool]
):
    if "file" in request.files:
        upload = request.files["file"]
        filename = upload.filename or "upload"
        mimetype = upload.mimetype
        content_bytes = upload.read()

        raw_options: Dict[str, Any] = dict(request.form)
        merged_options = merge_raw_options(raw_options)
        generation_options = coerce_generation_options(merged_options)
        response_flags = coerce_response_flags(merged_options)
        use_async = coerce_async_flag(merged_options)
        return (
            filename,
            mimetype,
            content_bytes,
            generation_options,
            response_flags,
            use_async,
        )

    post_data = request.get_json(silent=True)
    if isinstance(post_data, dict):
        if "file_content_base64" not in post_data:
            raise WeaverAPIValidationError(
                "JSON requests must include file_content_base64."
            )

        filename = str(post_data.get("filename") or "upload")
        mimetype = post_data.get("mimetype")
        content_bytes = decode_base64_content(post_data.get("file_content_base64"))
        merged_options = merge_raw_options(post_data)
        generation_options = coerce_generation_options(merged_options)
        response_flags = coerce_response_flags(merged_options)
        use_async = coerce_async_flag(merged_options)
        return (
            filename,
            mimetype,
            content_bytes,
            generation_options,
            response_flags,
            use_async,
        )

    raise WeaverAPIValidationError(
        "Expected multipart/form-data with a file, or JSON with file_content_base64."
    )


@app.route(WEAVER_API_BASE_PATH, methods=["POST"])
@csrf.exempt
@cross_origin(origins="*", methods=["POST", "HEAD"], automatic_options=True)
def weaver_generate():
    request_id = str(uuid.uuid4())

    if not api_verify():
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "auth_error", "message": "Access denied."},
            },
            403,
        )

    try:
        (
            filename,
            mimetype,
            content_bytes,
            generation_options,
            response_flags,
            use_async,
        ) = _parse_request_payload()
        if use_async:
            if not _async_is_configured():
                return jsonify_with_status(
                    {
                        "success": False,
                        "request_id": request_id,
                        "error": {
                            "type": "async_not_configured",
                            "message": (
                                "Async mode is not configured. Add "
                                f"{ASYNC_CELERY_MODULE!r} to the docassemble "
                                "'celery modules' configuration list."
                            ),
                        },
                    },
                    503,
                )
            task = weaver_generate_task.delay(
                filename=filename,
                mimetype=mimetype,
                content_bytes=content_bytes,
                generation_options=generation_options,
                include_package_zip_base64=response_flags["include_package_zip_base64"],
                include_yaml_text=response_flags["include_yaml_text"],
            )
            job_id = str(uuid.uuid4())
            _store_job_mapping(job_id, task.id)
            return jsonify_with_status(
                {
                    "success": True,
                    "api_version": "v1",
                    "request_id": request_id,
                    "status": "queued",
                    "job_id": job_id,
                    "job_url": f"{WEAVER_API_BASE_PATH}/jobs/{job_id}",
                },
                202,
            )
        payload = generate_interview_from_bytes(
            filename=filename,
            content_bytes=content_bytes,
            mimetype=mimetype,
            generation_options=generation_options,
            include_package_zip_base64=response_flags["include_package_zip_base64"],
            include_yaml_text=response_flags["include_yaml_text"],
        )
        response_body: Dict[str, Any] = {
            "success": True,
            "api_version": "v1",
            "request_id": request_id,
            "status": "succeeded",
            "data": payload,
        }
        return jsonify(response_body)
    except WeaverAPIValidationError as exc:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "validation_error", "message": exc.message},
            },
            exc.status_code,
        )
    except Exception as exc:
        log(f"ALWeaver API error: {exc!r}")
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {
                    "type": "server_error",
                    "message": "ALWeaver generation failed.",
                },
            },
            500,
        )


@app.route(f"{WEAVER_API_BASE_PATH}/jobs/<job_id>", methods=["GET", "DELETE"])
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "DELETE", "HEAD"], automatic_options=True)
def weaver_job(job_id: str):
    request_id = str(uuid.uuid4())
    if not api_verify():
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "auth_error", "message": "Access denied."},
            },
            403,
        )

    if request.method == "DELETE":
        task_info = _fetch_job_mapping(job_id)
        if not task_info:
            return jsonify_with_status(
                {
                    "success": False,
                    "request_id": request_id,
                    "error": {"type": "not_found", "message": "Job not found."},
                },
                404,
            )
        try:
            workerapp.AsyncResult(id=task_info["id"]).forget()
        except Exception:
            pass
        r.delete(_job_key(job_id))
        return jsonify(
            {
                "success": True,
                "api_version": "v1",
                "request_id": request_id,
                "job_id": job_id,
                "deleted": True,
            }
        )

    task_info = _fetch_job_mapping(job_id)
    if not task_info:
        return jsonify_with_status(
            {
                "success": False,
                "request_id": request_id,
                "error": {"type": "not_found", "message": "Job not found."},
            },
            404,
        )
    result = workerapp.AsyncResult(id=task_info["id"])
    state = (result.state or "").upper()
    if state == "SUCCESS":
        status = "succeeded"
    elif state in {"RECEIVED", "STARTED", "RETRY"}:
        status = "running"
    elif state == "FAILURE":
        status = "failed"
    else:
        status = "queued"

    response_body: Dict[str, Any] = {
        "success": True,
        "api_version": "v1",
        "request_id": request_id,
        "job_id": job_id,
        "task_id": task_info.get("id"),
        "status": status,
        "celery_state": state,
        "created_at": task_info.get("created_at"),
    }
    if state == "SUCCESS":
        response_body["data"] = result.get()
    elif state == "FAILURE":
        error_obj = result.result
        response_body["error"] = {
            "type": getattr(error_obj, "__class__", type(error_obj)).__name__,
            "message": str(error_obj),
        }
    return jsonify(response_body)


@app.route(f"{WEAVER_API_BASE_PATH}/openapi.json", methods=["GET"])
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
def weaver_openapi():
    return jsonify(build_openapi_spec())


@app.route(f"{WEAVER_API_BASE_PATH}/docs", methods=["GET"])
@csrf.exempt
@cross_origin(origins="*", methods=["GET", "HEAD"], automatic_options=True)
def weaver_docs():
    return Response(build_docs_html(), mimetype="text/html")

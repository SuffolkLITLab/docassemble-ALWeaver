# do not pre-load

from typing import Any, Dict, Mapping, Optional

from docassemble.webapp.worker_common import bg_context, workerapp

from .api_utils import generate_interview_from_bytes


@workerapp.task
def weaver_generate_task(
    filename: str,
    mimetype: Optional[str],
    content_bytes: bytes,
    generation_options: Mapping[str, Any],
    include_package_zip_base64: bool,
    include_yaml_text: bool,
) -> Dict[str, Any]:
    with bg_context():
        return generate_interview_from_bytes(
            filename=filename,
            content_bytes=content_bytes,
            mimetype=mimetype,
            generation_options=generation_options,
            include_package_zip_base64=include_package_zip_base64,
            include_yaml_text=include_yaml_text,
        )


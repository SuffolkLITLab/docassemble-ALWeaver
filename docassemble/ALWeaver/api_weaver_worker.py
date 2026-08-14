# do not pre-load

from typing import Any, Dict, Mapping, Optional

from .api_utils import generate_interview_from_bytes
from .docassemble_compat import background_context as bg_context, get_worker_app

workerapp = get_worker_app()


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


@workerapp.task(
    name="docassemble.ALWeaver.api_weaver_worker.weaver_editor_agent_turn_task"
)
def weaver_editor_agent_turn_task(
    *,
    session_id: str,
    owner_user_id: int,
    message: str,
    selected_block_id: Optional[str],
    runtime_enabled: bool,
    request_id: str,
    started_at: float,
) -> None:
    """Run one editing-assistant turn in Docassemble's Celery worker.

    A turn outlives any HTTP request — the browser gives up first, and nginx
    closes an idle upstream read well before a multi-step edit finishes — so it
    belongs in the worker, alongside project generation.
    """
    with bg_context():
        from .api_editor import _run_agent_turn_in_background

        _run_agent_turn_in_background(
            session_id=session_id,
            owner_user_id=owner_user_id,
            message=message,
            selected_block_id=selected_block_id,
            runtime_enabled=runtime_enabled,
            request_id=request_id,
            started_at=started_at,
        )


@workerapp.task(
    name="docassemble.ALWeaver.api_weaver_worker.weaver_editor_github_publish_task"
)
def weaver_editor_github_publish_task(
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
) -> Dict[str, Any]:
    """Commit a prepared Playground package to GitHub in the Celery worker.

    Publishing uploads one blob per file before it can write the tree, commit
    and ref, so a template-heavy project makes far more GitHub round trips than
    a web request should hold open.
    """
    with bg_context():
        from .api_editor import _complete_github_publish_job

        return _complete_github_publish_job(
            job_id=job_id,
            uid=uid,
            project=project,
            package=package,
            repository=repository,
            owner=owner,
            owner_type=owner_type,
            author_name=author_name,
            author_email=author_email,
            branch=branch,
            commit_message=commit_message,
            repository_url=repository_url,
        )


@workerapp.task(
    name="docassemble.ALWeaver.api_weaver_worker.weaver_editor_new_project_task"
)
def weaver_editor_new_project_task(
    *,
    job_id: str,
    uid: int,
    project_name: str,
    request_id: str,
    uploaded_files: list[Dict[str, Any]],
    generation_options: Dict[str, Any],
    debug_requested: bool,
) -> Dict[str, Any]:
    """Create an editor project inside Docassemble's configured Celery worker."""
    with bg_context():
        from .api_editor import _complete_new_project_upload_job

        return _complete_new_project_upload_job(
            job_id=job_id,
            uid=uid,
            project_name=project_name,
            request_id=request_id,
            uploaded_files=uploaded_files,
            generation_options=generation_options,
            debug_requested=debug_requested,
        )

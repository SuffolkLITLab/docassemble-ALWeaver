from __future__ import annotations

import os
import re
import shutil
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "create_project",
    "get_list_of_projects",
    "next_available_project_name",
    "normalize_project_name",
    "publish_weaver_artifacts_to_playground",
]


PLAYGROUND_SECTIONS = (
    "playground",
    "playgroundtemplate",
    "playgroundstatic",
    "playgroundsources",
    "playgroundmodules",
    "playgroundpackages",
)

SECTION_TO_STORAGE = {
    "questions": "playground",
    "templates": "playgroundtemplate",
    "static": "playgroundstatic",
    "sources": "playgroundsources",
    "modules": "playgroundmodules",
}


def normalize_project_name(
    raw_name: Optional[str], *, fallback: str = "ALWeaverProject"
) -> str:
    """Return a playground-safe project name.

    Playground project names must be alphanumeric and cannot start with a digit.
    """

    candidate = re.sub(r"[^A-Za-z0-9]+", "", str(raw_name or ""))
    if not candidate:
        candidate = re.sub(r"[^A-Za-z0-9]+", "", fallback)
    if not candidate:
        candidate = "ALWeaverProject"
    if candidate.lower() == "default":
        candidate = candidate + "Project"
    if candidate[0].isdigit():
        candidate = "P" + candidate
    return candidate


def next_available_project_name(base_name: str, existing_names: Iterable[str]) -> str:
    """Append or increment a numeric suffix until the project name is unique."""

    existing = {
        name for name in existing_names if isinstance(name, str) and name.strip() != ""
    }
    if base_name != "default" and base_name not in existing:
        return base_name

    match = re.match(r"^(.*?)(\d+)$", base_name)
    if match:
        stem = match.group(1) or "P"
        counter = int(match.group(2)) + 1
    else:
        stem = base_name
        counter = 1

    while True:
        candidate = f"{stem}{counter}"
        if candidate != "default" and candidate not in existing:
            return candidate
        counter += 1


def _directory_for(area: Any, project_name: str) -> str:
    if project_name == "default":
        return area.directory
    return os.path.join(area.directory, project_name)


def get_list_of_projects(user_id: int) -> List[str]:
    from docassemble.webapp.files import SavedFile

    playground = SavedFile(user_id, fix=False, section="playground")
    projects = playground.list_of_dirs() or []
    return sorted(
        {
            project
            for project in projects
            if isinstance(project, str) and project.strip() != ""
        }
    )


def create_project(user_id: int, project_name: str) -> None:
    from docassemble.webapp.files import SavedFile

    for section in PLAYGROUND_SECTIONS:
        area = SavedFile(user_id, fix=True, section=section)
        project_dir = os.path.join(area.directory, project_name)
        if not os.path.isdir(project_dir):
            os.makedirs(project_dir, exist_ok=True)
        placeholder = os.path.join(project_dir, ".placeholder")
        with open(placeholder, "a", encoding="utf-8"):
            os.utime(placeholder, None)
        area.finalize()


def _source_path_and_filename(file_like: Any) -> Tuple[str, str]:
    if isinstance(file_like, str):
        source_path = file_like
        filename = os.path.basename(source_path)
    else:
        path_attr = getattr(file_like, "path", None)
        if callable(path_attr):
            source_path = path_attr()
        else:
            raise ValueError(f"Object {file_like!r} does not expose a path() method")
        filename = getattr(file_like, "filename", None) or os.path.basename(source_path)

    source_extension = os.path.splitext(str(source_path or ""))[1]
    filename_extension = os.path.splitext(str(filename or ""))[1]
    if not filename_extension and source_extension:
        filename = f"{filename}{source_extension}"

    filename = os.path.basename(str(filename or ""))
    if not filename:
        raise ValueError("Cannot copy a file without a filename")
    if not source_path or not os.path.isfile(source_path):
        raise FileNotFoundError(f"Source file does not exist: {source_path!r}")
    return source_path, filename


def _dedupe_filename(filename: str, used: set[str]) -> str:
    if filename not in used:
        used.add(filename)
        return filename
    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = f"{stem}_{counter}{ext}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def _copy_files_to_section(
    *,
    user_id: int,
    project_name: str,
    storage_section: str,
    files: Sequence[Any],
) -> List[str]:
    from docassemble.webapp.files import SavedFile

    if not files:
        return []

    area = SavedFile(user_id, fix=True, section=storage_section)
    destination_dir = _directory_for(area, project_name)
    os.makedirs(destination_dir, exist_ok=True)

    existing_filenames = {
        name
        for name in os.listdir(destination_dir)
        if os.path.isfile(os.path.join(destination_dir, name))
    }
    copied_filenames: List[str] = []
    for file_like in files:
        if file_like is None:
            continue
        source_path, filename = _source_path_and_filename(file_like)
        destination_name = _dedupe_filename(filename, existing_filenames)
        shutil.copy2(source_path, os.path.join(destination_dir, destination_name))
        copied_filenames.append(destination_name)
    area.finalize()
    return copied_filenames


def publish_weaver_artifacts_to_playground(
    *,
    user_id: int,
    base_project_name: str,
    yaml_file: Any,
    template_files: Optional[Sequence[Any]] = None,
    static_files: Optional[Sequence[Any]] = None,
    source_files: Optional[Sequence[Any]] = None,
    module_files: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Create a unique playground project and copy generated interview artifacts."""

    normalized_base_name = normalize_project_name(base_project_name)
    existing_projects = get_list_of_projects(user_id)
    project_name = next_available_project_name(
        normalized_base_name, [*existing_projects, "default"]
    )
    create_project(user_id, project_name)

    copied_files = {
        "questions": _copy_files_to_section(
            user_id=user_id,
            project_name=project_name,
            storage_section=SECTION_TO_STORAGE["questions"],
            files=[yaml_file],
        ),
        "templates": _copy_files_to_section(
            user_id=user_id,
            project_name=project_name,
            storage_section=SECTION_TO_STORAGE["templates"],
            files=template_files or [],
        ),
        "static": _copy_files_to_section(
            user_id=user_id,
            project_name=project_name,
            storage_section=SECTION_TO_STORAGE["static"],
            files=static_files or [],
        ),
        "sources": _copy_files_to_section(
            user_id=user_id,
            project_name=project_name,
            storage_section=SECTION_TO_STORAGE["sources"],
            files=source_files or [],
        ),
        "modules": _copy_files_to_section(
            user_id=user_id,
            project_name=project_name,
            storage_section=SECTION_TO_STORAGE["modules"],
            files=module_files or [],
        ),
    }

    if not copied_files["questions"]:
        raise RuntimeError("No YAML file was copied to the playground project")

    yaml_filename = copied_files["questions"][0]
    project_suffix = "" if project_name == "default" else project_name
    interview_source = (
        f"docassemble.playground{int(user_id)}{project_suffix}:{yaml_filename}"
    )
    return {
        "project_name": project_name,
        "yaml_filename": yaml_filename,
        "interview_source": interview_source,
        "copied_files": copied_files,
    }

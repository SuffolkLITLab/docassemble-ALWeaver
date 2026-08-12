from __future__ import annotations

import os
import re
import shutil
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from .docassemble_compat import create_saved_file

__all__ = [
    "create_project",
    "delete_project",
    "get_list_of_projects",
    "next_available_project_name",
    "normalize_project_name",
    "publish_weaver_artifacts_to_playground",
    "prepare_project_github_package",
    "normalize_github_package_name",
    "rename_project",
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


def normalize_github_package_name(raw_name: Optional[str]) -> str:
    """Return the package suffix used for ``docassemble-<name>`` repositories."""
    value = str(raw_name or "").strip()
    value = re.sub(r"^docassemble[-.]", "", value, flags=re.IGNORECASE)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise ValueError(
            "Repository name must start with a letter and contain only letters, numbers, and underscores"
        )
    if value.lower() in {"base", "webapp", "demo"}:
        raise ValueError("That repository name is reserved by docassemble")
    return value


def _visible_section_files(area: Any, project_name: str) -> List[str]:
    directory = _directory_for(area, project_name)
    if not os.path.isdir(directory):
        return []
    return sorted(
        filename
        for filename in os.listdir(directory)
        if not filename.startswith(".")
        and os.path.isfile(os.path.join(directory, filename))
    )


def prepare_project_github_package(
    *,
    user_id: int,
    project_name: str,
    package_name: str,
    author_name: str = "",
    author_email: str = "",
    github_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Create/update the package manifest consumed by Docassemble's publisher.

    The native GitHub flow publishes Playground *packages*, not arbitrary
    projects.  Weaver keeps the manifest in sync with every visible file in
    the graphical project and lets Docassemble perform repository creation,
    authentication, Git operations, and the final pull-back into Playground.
    """
    package = normalize_github_package_name(package_name)
    file_fields = {
        "interview_files": "playground",
        "template_files": "playgroundtemplate",
        "module_files": "playgroundmodules",
        "static_files": "playgroundstatic",
        "sources_files": "playgroundsources",
    }
    files: Dict[str, List[str]] = {}
    for field_name, section in file_fields.items():
        area = create_saved_file(user_id, fix=True, section=section)
        files[field_name] = _visible_section_files(area, project_name)

    if not files["interview_files"]:
        raise ValueError("The project must contain at least one interview file")

    packages_area = create_saved_file(user_id, fix=True, section="playgroundpackages")
    package_directory = _directory_for(packages_area, project_name)
    os.makedirs(package_directory, exist_ok=True)
    manifest_path = os.path.join(package_directory, f"docassemble.{package}")
    existing: Dict[str, Any] = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream)
        if isinstance(loaded, dict):
            existing = loaded

    manifest: Dict[str, Any] = dict(existing)
    manifest.update(files)
    manifest.setdefault("dependencies", [])
    manifest.setdefault("description", f"A docassemble project for {project_name}.")
    manifest.setdefault("license", "MIT License")
    manifest.setdefault(
        "readme", f"# docassemble.{package}\n\nA docassemble extension.\n"
    )
    manifest.setdefault("url", "")
    manifest.setdefault("version", "0.0.1")
    if author_name:
        manifest["author_name"] = author_name
    else:
        manifest.setdefault("author_name", "")
    if author_email:
        manifest["author_email"] = author_email
    else:
        manifest.setdefault("author_email", "")
    if github_url:
        manifest["github_url"] = github_url

    with open(manifest_path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(manifest, stream, sort_keys=False, allow_unicode=True)
    packages_area.finalize()
    return {
        "package": package,
        "repository": f"docassemble-{package}",
        "manifest_path": manifest_path,
        "files": files,
    }


def get_list_of_projects(user_id: int) -> List[str]:
    playground = create_saved_file(user_id, fix=False, section="playground")
    projects = playground.list_of_dirs() or []
    return sorted(
        {
            project
            for project in projects
            if isinstance(project, str) and project.strip() != ""
        }
    )


def create_project(user_id: int, project_name: str) -> None:
    for section in PLAYGROUND_SECTIONS:
        area = create_saved_file(user_id, fix=True, section=section)
        project_dir = os.path.join(area.directory, project_name)
        if not os.path.isdir(project_dir):
            os.makedirs(project_dir, exist_ok=True)
        placeholder = os.path.join(project_dir, ".placeholder")
        with open(placeholder, "a", encoding="utf-8"):
            os.utime(placeholder, None)
        area.finalize()


def rename_project(user_id: int, old_project_name: str, new_project_name: str) -> None:
    if old_project_name == "default" or new_project_name == "default":
        raise ValueError("default project cannot be renamed")

    project_locations = []
    found_any = False
    for section in PLAYGROUND_SECTIONS:
        area = create_saved_file(user_id, fix=True, section=section)
        old_dir = _directory_for(area, old_project_name)
        new_dir = _directory_for(area, new_project_name)
        project_locations.append((area, old_dir, new_dir))
        if os.path.isdir(old_dir):
            found_any = True
        if os.path.exists(new_dir):
            raise ValueError(f"{new_project_name} already exists")

    if not found_any:
        raise FileNotFoundError(f"{old_project_name} not found")

    for area, old_dir, new_dir in project_locations:
        if not os.path.isdir(old_dir):
            continue
        os.rename(old_dir, new_dir)
        area.finalize()


def delete_project(user_id: int, project_name: str) -> None:
    if project_name == "default":
        raise ValueError("default project cannot be deleted")

    deleted_any = False
    for section in PLAYGROUND_SECTIONS:
        area = create_saved_file(user_id, fix=True, section=section)
        project_dir = _directory_for(area, project_name)
        if not os.path.isdir(project_dir):
            continue
        shutil.rmtree(project_dir)
        area.finalize()
        deleted_any = True

    if not deleted_any:
        raise FileNotFoundError(f"{project_name} not found")


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
    if not files:
        return []

    area = create_saved_file(user_id, fix=True, section=storage_section)
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

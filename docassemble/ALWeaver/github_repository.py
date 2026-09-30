"""Repository files Weaver manages beside a published Docassemble package.

Docassemble's package builder writes the package itself.  Weaver adds the
GitHub Actions workflows that check it and owns ``pyproject.toml`` so the
dependencies a sandboxed ALKiln server installs are the ones the author sees.

Settings live per Playground project in a dotfile next to the package
manifest.  Anything not written there falls back to a default, so a project
that never opened the settings still publishes the standard set.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import yaml

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w

from .docassemble_compat import create_saved_file

__all__ = [
    "STANDARD_WORKFLOWS",
    "PYPROJECT_PATH",
    "adopt_repository_snapshot",
    "load_repository_config",
    "repository_config_view",
    "repository_publish_files",
    "update_repository_config",
]

CONFIG_FILENAME = ".weaver-github.yml"
PYPROJECT_PATH = "pyproject.toml"
WORKFLOW_DIRECTORY = ".github/workflows"
MAX_FILE_CHARACTERS = 200_000

ALKILN_DOCS_URL = "https://assemblyline.suffolklitlab.org/docs/components/ALKiln/setup#sandbox-details"
ACTIONS_DOCS_URL = "https://assemblyline.suffolklitlab.org/docs/automated_quality_checks/github_actions"

ALKILN_SANDBOX_WORKFLOW = """name: ALKiln tests

on:
  push:
  pull_request:
  workflow_dispatch:
    inputs:
      tags:
        required: false
        description: 'Optional. A tag expression that chooses which tests to run (https://cucumber.io/docs/cucumber/api/#tag-expressions)'
      show_docker_output:
        required: false
        default: false
        type: boolean
        description: 'Show the docker logs while building the test server. This might show sensitive config information.'

jobs:
  interview-testing:
    # Run once for pushes in this repository and once for pull requests from
    # forks, instead of twice for a pull request from a branch here.
    if: (
          github.event_name != 'pull_request'
          && ! github.event.pull_request.head.repo.fork
        ) || (
          github.event_name == 'pull_request'
          && github.event.pull_request.head.repo.fork
        )
    runs-on: ubuntu-latest
    name: Run interview tests
    steps:
      - uses: actions/checkout@v4
      # Starts a temporary Docassemble server inside GitHub and installs this
      # branch, and its pyproject.toml dependencies, on it. No server of your
      # own is needed and the tests never touch one.
      - name: Start the isolated temporary Docassemble server on GitHub
        id: github_server
        uses: SuffolkLITLab/ALKiln/action_for_github_server@v5
        with:
          SHOW_DOCKER_OUTPUT: "${{ github.event.inputs.show_docker_output }}"
          CONFIG_CONTENTS: "${{ secrets.CONFIG_CONTENTS }}"
      - name: Run ALKiln tests
        uses: SuffolkLITLab/ALKiln@v5
        with:
          SERVER_URL: "${{ steps.github_server.outputs.SERVER_URL }}"
          DOCASSEMBLE_DEVELOPER_API_KEY: "${{ steps.github_server.outputs.DOCASSEMBLE_DEVELOPER_API_KEY }}"
          INSTALL_METHOD: "server"
          ALKILN_TAG_EXPRESSION: "${{ github.event.inputs.tags }}"
"""

# What earlier Weaver versions published. It needs a server of the author's
# own, so a repository still carrying it is upgraded rather than preserved.
LEGACY_ALKILN_SERVER_WORKFLOW = """name: ALKiln v5 tests

on:
  push:
  workflow_dispatch:
    inputs:
      tags:
        description: Optional ALKiln tag expression
        default: ''

jobs:
  interview-testing:
    runs-on: ubuntu-latest
    name: Run interview tests
    steps:
      - uses: actions/checkout@v4
      - name: Use ALKiln to run tests
        uses: SuffolkLITLab/ALKiln@v5
        with:
          SERVER_URL: ${{ secrets.SERVER_URL }}
          DOCASSEMBLE_DEVELOPER_API_KEY: ${{ secrets.DOCASSEMBLE_DEVELOPER_API_KEY }}
"""

BUILD_AND_CHECK_WORKFLOW = """name: Build and check package
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
jobs:
  build-and-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: SuffolkLITLab/ALActions/da_build@main
        with:
          python-version: "3.12"
"""

VALIDATE_DOCX_WORKFLOW = """name: Validate DOCX templates
on:
  pull_request:
    paths: ['**/*.docx']
  push:
    paths: ['**/*.docx']
  workflow_dispatch:
jobs:
  validate-templates:
    runs-on: ubuntu-latest
    steps:
      - uses: SuffolkLITLab/ALActions/valid_jinja2@main
"""

WORD_DIFF_WORKFLOW = """name: Diff Word documents
on:
  pull_request:
    paths: ['**/*.docx']
  workflow_dispatch:
jobs:
  docx-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: SuffolkLITLab/ALActions/word_diff@main
"""

PYTHON_QUALITY_WORKFLOW = """name: Python quality checks
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
jobs:
  python-quality:
    runs-on: ubuntu-latest
    steps:
      - uses: SuffolkLITLab/ALActions/black-formatting@main
      - uses: SuffolkLITLab/ALActions/docsig@main
      - uses: SuffolkLITLab/ALActions/pythontests@main
"""

DEPLOY_PLAYGROUND_WORKFLOW = """name: Deploy to playground
on:
  push:
    branches: ['feature/**']
jobs:
  deploy-playground:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: SuffolkLITLab/ALActions/da_playground_install@main
        with:
          SERVER_URL: ${{ secrets.SERVER_URL }}
          DOCASSEMBLE_DEVELOPER_API_KEY: ${{ secrets.DOCASSEMBLE_DEVELOPER_API_KEY }}
          PROJECT_NAME: "review-${{ github.ref_name }}"
"""

DEPLOY_PACKAGE_WORKFLOW = """name: Deploy package server-wide
on:
  push:
    branches: [main]
jobs:
  deploy-package:
    runs-on: ubuntu-latest
    steps:
      - uses: SuffolkLITLab/ALActions/da_package@main
        with:
          SERVER_URL: ${{ secrets.PROD_SERVER_URL }}
          DOCASSEMBLE_DEVELOPER_API_KEY: ${{ secrets.DOCASSEMBLE_DEVELOPER_API_KEY }}
          GITHUB_URL: "https://github.com/${{ github.repository }}"
          GITHUB_BRANCH: "main"
"""

HALL_MONITOR_WORKFLOW = """name: Hall monitor
on:
  schedule:
    - cron: "0 7,19 * * *"
  workflow_dispatch:
jobs:
  monitor-server:
    runs-on: ubuntu-latest
    steps:
      - uses: SuffolkLITLab/ALActions/hall_monitor@main
        with:
          # Replace these with your own server and addresses.
          SERVER_URL: "https://apps.example.org"
          SENDGRID_API_KEY: ${{ secrets.SENDGRID_API_KEY }}
          ERROR_EMAIL_FROM: "Monitor <alerts@example.org>"
          ERROR_EMAILS: "dev-team@example.org,admin@example.org"
"""


@dataclass(frozen=True)
class StandardWorkflow:
    id: str
    filename: str
    label: str
    description: str
    content: str
    # "on", "off", or the project contents that turn it on: "features" for
    # ALKiln tests, "modules" for custom Python modules.
    default: str
    secrets: Tuple[str, ...] = ()
    needs_editing: bool = False
    docs_url: str = ACTIONS_DOCS_URL
    legacy_contents: Tuple[str, ...] = ()

    @property
    def path(self) -> str:
        return f"{WORKFLOW_DIRECTORY}/{self.filename}"


STANDARD_WORKFLOWS: Tuple[StandardWorkflow, ...] = (
    StandardWorkflow(
        id="alkiln",
        filename="run_interview_tests.yml",
        label="ALKiln interview tests",
        description=(
            "Runs this project's .feature tests on a temporary Docassemble server "
            "that GitHub creates and deletes for each run. It installs the "
            "dependencies listed in pyproject.toml."
        ),
        content=ALKILN_SANDBOX_WORKFLOW,
        default="features",
        docs_url=ALKILN_DOCS_URL,
        legacy_contents=(LEGACY_ALKILN_SERVER_WORKFLOW,),
    ),
    StandardWorkflow(
        id="build_and_check",
        filename="build_and_check.yml",
        label="Build and check package",
        description=(
            "Builds the package and checks its YAML, Word templates, links, "
            "and PDF accessibility."
        ),
        content=BUILD_AND_CHECK_WORKFLOW,
        default="on",
    ),
    StandardWorkflow(
        id="validate_docx",
        filename="validate_docx.yml",
        label="Validate Word templates",
        description="Catches Jinja2 syntax errors in changed .docx templates.",
        content=VALIDATE_DOCX_WORKFLOW,
        default="on",
    ),
    StandardWorkflow(
        id="word_diff",
        filename="word_diff.yml",
        label="Word document diffs",
        description=(
            "Adds a readable text diff of changed .docx templates to pull requests."
        ),
        content=WORD_DIFF_WORKFLOW,
        default="on",
    ),
    StandardWorkflow(
        id="python_quality",
        filename="python_quality.yml",
        label="Python quality checks",
        description=(
            "Checks Black formatting and docstrings, and runs unit tests for "
            "custom Python modules."
        ),
        content=PYTHON_QUALITY_WORKFLOW,
        default="modules",
    ),
    StandardWorkflow(
        id="deploy_playground",
        filename="deploy_playground.yml",
        label="Deploy feature branches to a Playground",
        description=(
            "Installs each feature/ branch into a Playground project on your "
            "server so reviewers can try it."
        ),
        content=DEPLOY_PLAYGROUND_WORKFLOW,
        default="off",
        secrets=("SERVER_URL", "DOCASSEMBLE_DEVELOPER_API_KEY"),
    ),
    StandardWorkflow(
        id="deploy_package",
        filename="deploy_package.yml",
        label="Install on your server",
        description="Installs the package server-wide whenever main changes.",
        content=DEPLOY_PACKAGE_WORKFLOW,
        default="off",
        secrets=("PROD_SERVER_URL", "DOCASSEMBLE_DEVELOPER_API_KEY"),
    ),
    StandardWorkflow(
        id="hall_monitor",
        filename="hall_monitor.yml",
        label="Hall monitor",
        description=(
            "Checks twice a day that the interviews on your server still load, "
            "and emails you when one does not."
        ),
        content=HALL_MONITOR_WORKFLOW,
        default="off",
        secrets=("SENDGRID_API_KEY",),
        needs_editing=True,
    ),
)

_WORKFLOWS_BY_ID = {workflow.id: workflow for workflow in STANDARD_WORKFLOWS}

# Docassemble ships these; a package never lists them as dependencies.
_BUILT_IN_PACKAGES = {"base", "webapp", "demo"}

_YAML_PACKAGE_REFERENCE = re.compile(
    r"""^\s*-\s*["']?docassemble\.([A-Za-z_][A-Za-z0-9_]*)[:.]""", re.MULTILINE
)
_PYTHON_PACKAGE_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+docassemble\.([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE
)
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def dependency_name(spec: str) -> str:
    """Return the normalized distribution name a requirement refers to."""
    match = _REQUIREMENT_NAME.match(str(spec or ""))
    if not match:
        return ""
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def _distribution_name(spec: str) -> str:
    match = _REQUIREMENT_NAME.match(str(spec or ""))
    return match.group(1) if match else ""


_GITHUB_REPOSITORY_URL = re.compile(
    r"^(?:git\+)?https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)"
    r"(?:\.git)?(?:/tree/([^\s?#]+))?/?$"
)


def github_requirement(url: str) -> Optional[str]:
    """Turn a pasted GitHub repository URL into a pip requirement.

    ``https://github.com/org/docassemble-Foo/tree/main`` becomes
    ``docassemble.Foo @ git+https://github.com/org/docassemble-Foo.git@main``,
    the form Docassemble itself writes for packages installed from GitHub.
    """
    match = _GITHUB_REPOSITORY_URL.match(str(url or "").strip())
    if not match:
        return None
    owner, repository, branch = match.groups()
    name = re.sub(r"^docassemble-", "docassemble.", repository, flags=re.IGNORECASE)
    requirement = f"{name} @ git+https://github.com/{owner}/{repository}.git"
    return f"{requirement}@{branch}" if branch else requirement


def is_github_requirement(spec: str) -> bool:
    return "git+" in spec and "github.com" in spec


def installed_requirement(name: str) -> str:
    """Return ``name``, or a Git requirement when this server got it from GitHub.

    A package installed from GitHub is usually not on PyPI, so listing it by
    name alone would fail on ALKiln's test server.
    """
    import importlib.metadata
    import json

    try:
        raw = importlib.metadata.distribution(name).read_text("direct_url.json")
        direct_url = json.loads(raw) if raw else {}
    except (importlib.metadata.PackageNotFoundError, ValueError, OSError):
        return name
    vcs_info = direct_url.get("vcs_info") if isinstance(direct_url, dict) else None
    url = str(direct_url.get("url") or "") if isinstance(direct_url, dict) else ""
    if not isinstance(vcs_info, dict) or vcs_info.get("vcs") != "git" or not url:
        return name
    requirement = f"{name} @ git+{url}"
    revision = str(vcs_info.get("requested_revision") or "")
    return f"{requirement}@{revision}" if revision else requirement


def validate_dependency(spec: Any) -> str:
    """Return a cleaned requirement string or raise ``ValueError``."""
    text = str(spec or "").strip()
    if not text:
        raise ValueError("A dependency cannot be blank")
    text = github_requirement(text) or text
    try:
        from packaging.requirements import InvalidRequirement, Requirement
    except ImportError:
        if not dependency_name(text):
            raise ValueError(f"{text!r} is not a valid Python requirement")
        return text
    try:
        Requirement(text)
    except InvalidRequirement as exc:
        raise ValueError(f"{text!r} is not a valid Python requirement: {exc}") from exc
    return text


def detect_dependencies(
    yaml_texts: Iterable[str], module_texts: Iterable[str], package: str
) -> List[str]:
    """Return packages the project's interviews and modules pull in.

    Only references that name another installed package count: ``include``,
    ``modules`` and ``imports`` entries, and Python imports.
    """
    found = set()
    for text in yaml_texts:
        found.update(_YAML_PACKAGE_REFERENCE.findall(text or ""))
    for text in module_texts:
        found.update(_PYTHON_PACKAGE_IMPORT.findall(text or ""))
    own = str(package or "").lower()
    return sorted(
        f"docassemble.{name}"
        for name in found
        if name not in _BUILT_IN_PACKAGES
        and not name.startswith("playground")
        and name.lower() != own
    )


def _merge_dependencies(user: Sequence[str], detected: Sequence[str]) -> List[str]:
    """Combine user requirements with detected ones, the user's spec winning."""
    merged = {dependency_name(spec): spec for spec in detected}
    merged.update({dependency_name(spec): spec for spec in user})
    return [merged[name] for name in sorted(merged)]


def _setup_py_dependencies(text: str) -> List[str]:
    match = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not match:
        return []
    return [
        spec
        for spec in re.findall(r"""["']([^"']+)["']""", match.group(1))
        if dependency_name(spec)
    ]


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------


def _license_expression(raw_license: Any) -> str:
    text = str(raw_license or "").strip()
    if not text:
        return ""
    if "MIT" in text:
        return "MIT"
    # Docassemble checks against its SPDX list; a single token is the closest
    # Weaver can get without importing the web app.
    return text if re.fullmatch(r"[A-Za-z0-9.+-]+", text) else ""


def render_pyproject(
    package: str, manifest: Mapping[str, Any], dependencies: Sequence[str]
) -> str:
    """Render the pyproject.toml Docassemble's package builder would write.

    Weaver writes the dependency strings itself: Docassemble's builder drops
    any package that is not installed on this server, which a sandboxed test
    server would then fail to install.
    """
    project: Dict[str, Any] = {
        "name": f"docassemble.{package}",
        "version": str(manifest.get("version") or "0.0.1"),
        "description": str(manifest.get("description") or "A docassemble extension."),
        "readme": "README.md",
        "authors": [
            {
                "name": str(manifest.get("author_name") or ""),
                "email": str(manifest.get("author_email") or ""),
            }
        ],
        "dependencies": list(dependencies),
    }
    license_expression = _license_expression(manifest.get("license"))
    if license_expression:
        project["license"] = license_expression
        project["license-files"] = ["LICENSE"]
    project["urls"] = {
        "Homepage": str(manifest.get("url") or "https://docassemble.org")
    }
    data = {
        # Docassemble still imports pkg_resources, which setuptools 82 removed.
        "build-system": {
            "requires": ["setuptools>=80.9.0,<82"],
            "build-backend": "setuptools.build_meta",
        },
        "project": project,
        "tool": {"setuptools": {"packages": {"find": {"where": ["."]}}}},
    }
    return tomli_w.dumps(data)


def parse_pyproject(text: str) -> Dict[str, Any]:
    """Parse pyproject.toml text, raising ``ValueError`` on anything unusable."""
    if len(text) > MAX_FILE_CHARACTERS:
        raise ValueError("pyproject.toml is too large")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"pyproject.toml is not valid TOML: {exc}") from exc
    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml needs a [project] table")
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise ValueError("[project] dependencies must be a list of strings")
    return data


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def normalize_config(raw: Any) -> Dict[str, Any]:
    """Return a settings mapping with only known, well-typed entries."""
    raw = raw if isinstance(raw, dict) else {}
    workflows: Dict[str, Dict[str, Any]] = {}
    raw_workflows = raw.get("workflows")
    if isinstance(raw_workflows, dict):
        for workflow_id, entry in raw_workflows.items():
            if workflow_id not in _WORKFLOWS_BY_ID or not isinstance(entry, dict):
                continue
            normalized: Dict[str, Any] = {}
            if isinstance(entry.get("enabled"), bool):
                normalized["enabled"] = entry["enabled"]
            if isinstance(entry.get("content"), str):
                normalized["content"] = entry["content"]
            if normalized:
                workflows[workflow_id] = normalized
    dependencies = [
        str(spec).strip()
        for spec in raw.get("dependencies") or []
        if isinstance(spec, str) and dependency_name(spec)
    ]
    pyproject = raw.get("pyproject_toml")
    return {
        "workflows": workflows,
        "dependencies": dependencies,
        "pyproject_toml": pyproject if isinstance(pyproject, str) else None,
    }


def _workflow_enabled(
    workflow: StandardWorkflow,
    config: Mapping[str, Any],
    *,
    has_features: bool,
    has_modules: bool,
) -> bool:
    entry = config["workflows"].get(workflow.id, {})
    if "enabled" in entry:
        return bool(entry["enabled"])
    return _default_enabled(
        workflow, has_features=has_features, has_modules=has_modules
    )


def _default_enabled(
    workflow: StandardWorkflow, *, has_features: bool, has_modules: bool
) -> bool:
    if workflow.default == "features":
        return has_features
    if workflow.default == "modules":
        return has_modules
    return workflow.default == "on"


def _workflow_content(workflow: StandardWorkflow, config: Mapping[str, Any]) -> str:
    return config["workflows"].get(workflow.id, {}).get("content") or workflow.content


def _effective_dependencies(
    config: Mapping[str, Any], detected: Sequence[str]
) -> List[str]:
    if config["pyproject_toml"] is not None:
        return list(
            parse_pyproject(config["pyproject_toml"])["project"].get("dependencies", [])
        )
    return _merge_dependencies(config["dependencies"], detected)


def _pyproject_text(
    config: Mapping[str, Any],
    *,
    package: str,
    manifest: Mapping[str, Any],
    detected: Sequence[str],
) -> str:
    if config["pyproject_toml"] is not None:
        return config["pyproject_toml"]
    return render_pyproject(
        package, manifest, _effective_dependencies(config, detected)
    )


def resolve_config(
    config: Mapping[str, Any],
    *,
    package: str,
    manifest: Mapping[str, Any],
    detected: Sequence[str],
    has_features: bool,
    has_modules: bool,
) -> Dict[str, Any]:
    """Describe the settings for the editor and list the files to publish."""
    workflows = []
    files: Dict[str, str] = {}
    for workflow in STANDARD_WORKFLOWS:
        enabled = _workflow_enabled(
            workflow, config, has_features=has_features, has_modules=has_modules
        )
        content = _workflow_content(workflow, config)
        if enabled:
            files[workflow.path] = content
        workflows.append(
            {
                "id": workflow.id,
                "path": workflow.path,
                "label": workflow.label,
                "description": workflow.description,
                "docs_url": workflow.docs_url,
                "secrets": list(workflow.secrets),
                "needs_editing": workflow.needs_editing,
                "enabled": enabled,
                "recommended": _default_enabled(
                    workflow, has_features=has_features, has_modules=has_modules
                ),
                "content": content,
                "default_content": workflow.content,
                "customized": content != workflow.content,
            }
        )

    custom = config["pyproject_toml"] is not None
    dependencies = _effective_dependencies(config, detected)
    detected_names = {dependency_name(spec) for spec in detected}
    user_names = {dependency_name(spec) for spec in config["dependencies"]}
    present_names = {dependency_name(spec) for spec in dependencies}
    pyproject_text = _pyproject_text(
        config, package=package, manifest=manifest, detected=detected
    )
    files[PYPROJECT_PATH] = pyproject_text
    return {
        "workflows": workflows,
        "dependencies": [
            {
                "spec": spec,
                "name": _distribution_name(spec),
                "detected": dependency_name(spec) in detected_names,
                "user_set": dependency_name(spec) in user_names,
                "github": is_github_requirement(spec),
                # A detected package is re-added on every publish of a
                # generated file, so only an override of it can be removed.
                "removable": custom
                or dependency_name(spec) not in detected_names
                or dependency_name(spec) in user_names,
            }
            for spec in dependencies
        ],
        "missing_dependencies": [
            spec for spec in detected if dependency_name(spec) not in present_names
        ],
        "pyproject": {"text": pyproject_text, "custom": custom},
        "files": files,
        "managed_paths": sorted(
            [workflow.path for workflow in STANDARD_WORKFLOWS] + [PYPROJECT_PATH]
        ),
        "dependency_names": [_distribution_name(spec) for spec in dependencies],
    }


def apply_operation(
    config: Mapping[str, Any],
    operation: Any,
    *,
    package: str,
    manifest: Mapping[str, Any],
    detected: Sequence[str],
) -> Dict[str, Any]:
    """Return new settings with one editor change applied."""
    if not isinstance(operation, dict):
        raise ValueError("Settings change must be an object")
    updated = normalize_config(config)
    kind = operation.get("type")
    if kind == "workflow":
        workflow = _WORKFLOWS_BY_ID.get(str(operation.get("id") or ""))
        if workflow is None:
            raise ValueError("Unknown workflow")
        entry = dict(updated["workflows"].get(workflow.id, {}))
        if "enabled" in operation:
            if not isinstance(operation["enabled"], bool):
                raise ValueError("Workflow enabled must be true or false")
            entry["enabled"] = operation["enabled"]
        if "content" in operation:
            content = operation["content"]
            if content is None or content == workflow.content:
                entry.pop("content", None)
            else:
                entry["content"] = _validate_workflow(str(content), workflow.path)
        updated["workflows"][workflow.id] = entry
        return updated
    if kind == "dependencies":
        specs = operation.get("dependencies")
        if not isinstance(specs, list):
            raise ValueError("Dependencies must be a list")
        by_name: Dict[str, str] = {}
        for spec in specs:
            cleaned = validate_dependency(spec)
            if dependency_name(cleaned) == dependency_name(f"docassemble.{package}"):
                raise ValueError("A package cannot depend on itself")
            by_name[dependency_name(cleaned)] = cleaned
        cleaned_specs = [by_name[name] for name in sorted(by_name)]
        if updated["pyproject_toml"] is not None:
            data = parse_pyproject(updated["pyproject_toml"])
            data["project"]["dependencies"] = cleaned_specs
            updated["pyproject_toml"] = tomli_w.dumps(data)
        else:
            updated["dependencies"] = _user_dependencies(cleaned_specs, detected)
        return updated
    if kind == "pyproject":
        text = operation.get("text")
        if text is None:
            if updated["pyproject_toml"] is not None:
                # Keep what the author listed when going back to the
                # generated file.
                updated["dependencies"] = _user_dependencies(
                    _effective_dependencies(updated, detected), detected
                )
            updated["pyproject_toml"] = None
            return updated
        text = str(text)
        parse_pyproject(text)
        generated = normalize_config({**updated, "pyproject_toml": None})
        if text == _pyproject_text(
            generated, package=package, manifest=manifest, detected=detected
        ):
            updated["pyproject_toml"] = None
        else:
            updated["pyproject_toml"] = text
        return updated
    raise ValueError("Unknown settings change")


def _user_dependencies(specs: Sequence[str], detected: Sequence[str]) -> List[str]:
    """Drop the specs a generated file would add anyway."""
    detected_specs = {dependency_name(spec): spec for spec in detected}
    return [
        spec
        for spec in specs
        if detected_specs.get(dependency_name(spec), "").strip() != spec.strip()
    ]


def _validate_workflow(content: str, path: str) -> str:
    if len(content) > MAX_FILE_CHARACTERS:
        raise ValueError(f"{path} is too large")
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(parsed, dict) or "jobs" not in parsed:
        raise ValueError(f"{path} must be a GitHub workflow with a jobs section")
    return content


def adopt_repository_files(
    config: Mapping[str, Any],
    remote: Mapping[str, bytes],
    base: Optional[Mapping[str, bytes]],
    *,
    package: str,
    manifest: Mapping[str, Any],
    detected: Sequence[str],
) -> Dict[str, Any]:
    """Take on the repository's workflows and pyproject.toml.

    With no ``base`` (an import) every workflow and pyproject.toml the
    repository has is taken; a standard workflow it lacks keeps its default so
    the first publish adds it.  On a pull only files that changed on GitHub
    since the last sync are taken, so local settings survive, and a standard
    workflow deleted there is turned off.
    """
    updated = normalize_config(config)
    for workflow in STANDARD_WORKFLOWS:
        remote_content = _decoded(remote.get(workflow.path))
        if base is not None and remote_content == _decoded(base.get(workflow.path)):
            continue
        if remote_content is None:
            if base is not None:
                updated["workflows"][workflow.id] = {"enabled": False}
            continue
        entry: Dict[str, Any] = {"enabled": True}
        if (
            remote_content != workflow.content
            and remote_content not in workflow.legacy_contents
        ):
            entry["content"] = remote_content
        updated["workflows"][workflow.id] = entry

    remote_pyproject = _decoded(remote.get(PYPROJECT_PATH))
    if base is None or remote_pyproject != _decoded(base.get(PYPROJECT_PATH)):
        standard = _standard_pyproject(remote_pyproject)
        if standard is not None:
            # A file Docassemble or Weaver generated says nothing the manifest
            # cannot, so keep generating it; only its dependencies carry over.
            updated["pyproject_toml"] = None
            updated["dependencies"] = _user_dependencies(
                standard["project"].get("dependencies", []), detected
            )
        elif remote_pyproject is not None:
            try:
                updated = apply_operation(
                    updated,
                    {"type": "pyproject", "text": remote_pyproject},
                    package=package,
                    manifest=manifest,
                    detected=detected,
                )
            except ValueError:
                # An unusable file on GitHub should not block the import; the
                # generated one replaces it on the next publish.
                pass
        elif base is None:
            setup_py = _decoded(remote.get("setup.py"))
            if setup_py:
                updated["dependencies"] = _user_dependencies(
                    _setup_py_dependencies(setup_py), detected
                )
    return updated


_STANDARD_PROJECT_KEYS = {
    "name",
    "version",
    "description",
    "readme",
    "authors",
    "dependencies",
    "urls",
    "license",
    "license-files",
}


def _standard_pyproject(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the parsed file if it holds only what a package builder writes.

    Such a file differs from Weaver's rendering in details (the author, the
    version, the setuptools pin), so comparing text would mistake every
    imported repository for a hand-edited one and freeze its metadata.
    """
    if text is None:
        return None
    try:
        data = parse_pyproject(text)
    except ValueError:
        return None
    build_system = data.get("build-system", {})
    tool = data.get("tool", {})
    project = data["project"]
    requires = (
        build_system.get("requires", []) if isinstance(build_system, dict) else None
    )
    if (
        set(data) - {"build-system", "project", "tool"}
        or not isinstance(requires, list)
        or not all(
            isinstance(item, str) and dependency_name(item) == "setuptools"
            for item in requires
        )
        or set(build_system) - {"requires", "build-backend"}
        or tool not in ({}, {"setuptools": {"packages": {"find": {"where": ["."]}}}})
        or set(project) - _STANDARD_PROJECT_KEYS
        or set(project.get("urls", {}) or {}) - {"Homepage"}
    ):
        return None
    return data


def pyproject_manifest_fields(text: Optional[str]) -> Dict[str, str]:
    """Return the manifest fields a standard repository pyproject.toml sets.

    After an import the manifest holds defaults, so without this the first
    publish would reset the package to version 0.0.1.
    """
    standard = _standard_pyproject(text)
    if standard is None:
        return {}
    project = standard["project"]
    fields = {
        key: str(project[key])
        for key in ("version", "description")
        if isinstance(project.get(key), str) and project[key].strip()
    }
    homepage = (project.get("urls") or {}).get("Homepage")
    # Docassemble writes its own site when the manifest has no URL.
    if isinstance(homepage, str) and homepage.strip() not in {
        "",
        "https://docassemble.org",
    }:
        fields["url"] = homepage.strip()
    return fields


def _decoded(content: Optional[bytes]) -> Optional[str]:
    if content is None:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _project_directory(area: Any, project: str) -> str:
    if project == "default":
        return area.directory
    return os.path.join(area.directory, project)


def _read_texts(
    user_id: int, project: str, section: str, suffixes: Tuple[str, ...]
) -> List[str]:
    directory = _project_directory(
        create_saved_file(user_id, fix=True, section=section), project
    )
    if not os.path.isdir(directory):
        return []
    texts = []
    for filename in sorted(os.listdir(directory)):
        path = os.path.join(directory, filename)
        if filename.startswith(".") or not filename.lower().endswith(suffixes):
            continue
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as stream:
            texts.append(stream.read())
    return texts


def _project_facts(user_id: int, project: str, package: str) -> Dict[str, Any]:
    yaml_texts = _read_texts(user_id, project, "playground", (".yml", ".yaml"))
    module_texts = _read_texts(user_id, project, "playgroundmodules", (".py",))
    features = _read_texts(user_id, project, "playgroundsources", (".feature",))
    return {
        "detected": [
            installed_requirement(name)
            for name in detect_dependencies(yaml_texts, module_texts, package)
        ],
        "has_features": bool(features),
        "has_modules": bool(module_texts),
    }


def _packages_directory(user_id: int, project: str) -> Tuple[Any, str]:
    area = create_saved_file(user_id, fix=True, section="playgroundpackages")
    return area, _project_directory(area, project)


def load_repository_config(
    user_id: int,
    project: str,
    *,
    manifest: Optional[Mapping[str, Any]] = None,
    detected: Sequence[str] = (),
) -> Dict[str, Any]:
    """Load the saved settings, or start from the package manifest.

    A project published before Weaver managed pyproject.toml may list
    dependencies on Docassemble's Packages page that no interview names, so
    until settings are saved those count as the author's own.
    """
    _area, directory = _packages_directory(user_id, project)
    path = os.path.join(directory, CONFIG_FILENAME)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as stream:
                return normalize_config(yaml.safe_load(stream))
        except (OSError, yaml.YAMLError):
            pass
    return seed_config_from_manifest(manifest or {}, detected)


def seed_config_from_manifest(
    manifest: Mapping[str, Any], detected: Sequence[str]
) -> Dict[str, Any]:
    raw = manifest.get("dependencies")
    names = (
        [str(name) for name in raw if isinstance(name, str)]
        if isinstance(raw, list)
        else []
    )
    detected_names = {dependency_name(spec) for spec in detected}
    return normalize_config(
        {
            "dependencies": [
                name for name in names if dependency_name(name) not in detected_names
            ]
        }
    )


def save_repository_config(
    user_id: int, project: str, config: Mapping[str, Any]
) -> None:
    area, directory = _packages_directory(user_id, project)
    os.makedirs(directory, exist_ok=True)
    with open(
        os.path.join(directory, CONFIG_FILENAME), "w", encoding="utf-8"
    ) as stream:
        yaml.safe_dump(
            normalize_config(config), stream, sort_keys=False, allow_unicode=True
        )
    area.finalize()


def _load_manifest(user_id: int, project: str, package: str) -> Dict[str, Any]:
    _area, directory = _packages_directory(user_id, project)
    path = os.path.join(directory, f"docassemble.{package}")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def repository_config_view(
    user_id: int,
    project: str,
    package: str,
    *,
    manifest_overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return what the editor shows for a project's repository settings."""
    manifest = {
        **_load_manifest(user_id, project, package),
        **(manifest_overrides or {}),
    }
    facts = _project_facts(user_id, project, package)
    resolved = resolve_config(
        load_repository_config(
            user_id, project, manifest=manifest, detected=facts["detected"]
        ),
        package=package,
        manifest=manifest,
        **facts,
    )
    resolved.pop("files")
    resolved.pop("managed_paths")
    resolved["detected_dependencies"] = facts["detected"]
    resolved["has_features"] = facts["has_features"]
    resolved["has_modules"] = facts["has_modules"]
    return resolved


def update_repository_config(
    user_id: int,
    project: str,
    package: str,
    operation: Any,
    *,
    manifest_overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = {
        **_load_manifest(user_id, project, package),
        **(manifest_overrides or {}),
    }
    facts = _project_facts(user_id, project, package)
    updated = apply_operation(
        load_repository_config(
            user_id, project, manifest=manifest, detected=facts["detected"]
        ),
        operation,
        package=package,
        manifest=manifest,
        detected=facts["detected"],
    )
    save_repository_config(user_id, project, updated)
    return repository_config_view(
        user_id, project, package, manifest_overrides=manifest_overrides
    )


def repository_publish_files(
    user_id: int, project: str, package: str, manifest: Mapping[str, Any]
) -> Dict[str, Any]:
    """Return the extra files to commit and the paths Weaver owns."""
    facts = _project_facts(user_id, project, package)
    resolved = resolve_config(
        load_repository_config(
            user_id, project, manifest=manifest, detected=facts["detected"]
        ),
        package=package,
        manifest=manifest,
        **facts,
    )
    return {
        "files": resolved["files"],
        "managed_paths": resolved["managed_paths"],
        "dependency_names": resolved["dependency_names"],
    }


def repository_dependency_names(user_id: int, project: str, package: str) -> List[str]:
    """Return the distribution names to record in the Playground manifest."""
    facts = _project_facts(user_id, project, package)
    config = load_repository_config(
        user_id,
        project,
        manifest=_load_manifest(user_id, project, package),
        detected=facts["detected"],
    )
    return [
        _distribution_name(spec)
        for spec in _effective_dependencies(config, facts["detected"])
    ]


def adopt_repository_snapshot(
    user_id: int,
    project: str,
    package: str,
    remote_files: Mapping[str, bytes],
    base_files: Optional[Mapping[str, bytes]] = None,
) -> None:
    """Store the repository's workflows and pyproject.toml after import/pull."""
    manifest = _load_manifest(user_id, project, package)
    facts = _project_facts(user_id, project, package)
    updated = adopt_repository_files(
        load_repository_config(
            user_id, project, manifest=manifest, detected=facts["detected"]
        ),
        remote_files,
        base_files,
        package=package,
        manifest=manifest,
        detected=facts["detected"],
    )
    save_repository_config(user_id, project, updated)
    remote_pyproject = _decoded(remote_files.get(PYPROJECT_PATH))
    if base_files is None or remote_pyproject != _decoded(
        base_files.get(PYPROJECT_PATH)
    ):
        fields = pyproject_manifest_fields(remote_pyproject)
        if fields and any(manifest.get(key) != value for key, value in fields.items()):
            _save_manifest(user_id, project, package, {**manifest, **fields})


def _save_manifest(
    user_id: int, project: str, package: str, manifest: Mapping[str, Any]
) -> None:
    area, directory = _packages_directory(user_id, project)
    path = os.path.join(directory, f"docassemble.{package}")
    if not os.path.isfile(path):
        return
    with open(path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(dict(manifest), stream, sort_keys=False, allow_unicode=True)
    area.finalize()

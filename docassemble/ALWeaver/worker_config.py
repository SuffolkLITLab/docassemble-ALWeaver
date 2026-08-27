"""Shared configuration checks for ALWeaver Celery tasks."""

from __future__ import annotations

import re
from typing import Any, Mapping

CELERY_CONFIG_KEY = "celery modules"
CELERY_MODULE = "docassemble.ALWeaver.api_weaver_worker"
CELERY_CONFIGURATION_DOCS_URL = (
    "https://github.com/SuffolkLITLab/docassemble-ALWeaver"
    "#celery-worker-configuration"
)


def add_celery_module_to_config_yaml(source: str) -> tuple[str, bool]:
    """Add Weaver's worker module while retaining the rest of ``config.yml``.

    This intentionally edits text instead of loading and dumping YAML.  The
    configuration file is often hand-maintained and may contain comments,
    anchors, and a preferred layout that an installer should not rewrite.
    """
    if not isinstance(source, str):
        raise ValueError("The Docassemble configuration must be text.")
    line_pattern = re.compile(
        r"^(?P<indent>[ \t]*)(?:['\"]celery modules['\"]|celery modules)"
        r"[ \t]*:[ \t]*"
        r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^#\r\n]*)"
        r"(?P<comment>[ \t]*#.*)?$",
        re.MULTILINE,
    )
    match = line_pattern.search(source)
    if not match:
        suffix = "" if not source or source.endswith(("\n", "\r")) else "\n"
        return (
            source
            + suffix
            + f"{CELERY_CONFIG_KEY}:\n  - {CELERY_MODULE}\n",
            True,
        )

    line_value = match.group("value").strip()
    comment = match.group("comment") or ""
    if comment.startswith("#"):
        comment = " " + comment
    if line_value.startswith("[") and line_value.endswith("]"):
        members = [item.strip().strip("'\"") for item in line_value[1:-1].split(",")]
        if CELERY_MODULE in members:
            return source, False
        new_value = line_value[:-1].rstrip()
        separator = "" if new_value.endswith("[") else ", "
        replacement = (
            f"{match.group('indent')}{CELERY_CONFIG_KEY}: "
            f"{new_value}{separator}{CELERY_MODULE}]{comment}"
        )
        return source[: match.start()] + replacement + source[match.end() :], True

    if line_value:
        # A scalar is legal in Docassemble.  Preserve it as the first list
        # entry rather than replacing it or changing any unrelated YAML.
        existing = line_value.strip("'\"")
        if existing == CELERY_MODULE:
            return source, False
        replacement = (
            f"{match.group('indent')}{CELERY_CONFIG_KEY}:{comment}\n"
            f"{match.group('indent')}  - {line_value}\n"
            f"{match.group('indent')}  - {CELERY_MODULE}"
        )
        return source[: match.start()] + replacement + source[match.end() :], True

    # The value is a conventional block list.  Locate only its extent, then
    # insert one sibling list item before the next mapping key or document end.
    line_end = match.end()
    following = source[line_end:]
    insert_at = len(source)
    for boundary in re.finditer(r"\n(?P<indent>[ \t]*)(?=\S)", following):
        next_indent = boundary.group("indent")
        if len(next_indent.expandtabs(8)) <= len(match.group("indent").expandtabs(8)):
            insert_at = line_end + boundary.start()
            break
    block = source[line_end:insert_at]
    item_pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)-\s*(?P<quote>['\"]?)(?P<module>[^#\r\n'\"]+)"
        r"(?P=quote)\s*(?:#.*)?$"
    )
    existing_items = list(item_pattern.finditer(block))
    if any(item.group("module").strip() == CELERY_MODULE for item in existing_items):
        return source, False
    # Match the indentation of the existing list items rather than assuming
    # two spaces, so hand-formatted config files aren't corrupted.
    if existing_items:
        child_indent = existing_items[0].group("indent")
    else:
        child_indent = match.group("indent") + "  "
    insertion = f"\n{child_indent}- {CELERY_MODULE}"
    return source[:insert_at] + insertion + source[insert_at:], True


def get_worker_configuration_status(
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a serializable preflight result without raising on bad config."""
    try:
        if config is None:
            from docassemble.base.config import daconfig

            config = daconfig
        configured_modules = config.get(CELERY_CONFIG_KEY, []) or []
        if isinstance(configured_modules, str):
            configured_modules = [configured_modules]
        configured = CELERY_MODULE in configured_modules
    except Exception as exc:
        return {
            "configured": False,
            "code": "celery_configuration_check_failed",
            "message": (
                "Weaver could not inspect Docassemble's Celery configuration. "
                "Uploaded-document project generation and GitHub publishing "
                "are unavailable."
            ),
            "config_key": CELERY_CONFIG_KEY,
            "required_module": CELERY_MODULE,
            "docs_url": CELERY_CONFIGURATION_DOCS_URL,
            "details": {"exception_type": type(exc).__name__},
        }

    if configured:
        return {
            "configured": True,
            "code": "celery_configured",
            "message": "Weaver's Celery worker module is configured.",
            "config_key": CELERY_CONFIG_KEY,
            "required_module": CELERY_MODULE,
            "docs_url": CELERY_CONFIGURATION_DOCS_URL,
            "details": {},
        }
    return {
        "configured": False,
        "code": "celery_module_missing",
        "message": (
            "Uploaded-document project generation and GitHub publishing are "
            "unavailable until the Weaver worker module is added to "
            "Docassemble's Celery configuration and the web and Celery services "
            "are restarted. Other editor features remain available."
        ),
        "config_key": CELERY_CONFIG_KEY,
        "required_module": CELERY_MODULE,
        "docs_url": CELERY_CONFIGURATION_DOCS_URL,
        "details": {},
    }


def worker_configuration_is_ready(config: Mapping[str, Any] | None = None) -> bool:
    """Return whether Docassemble is configured to import Weaver's tasks."""
    return bool(get_worker_configuration_status(config).get("configured"))

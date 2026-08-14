"""Shared configuration checks for ALWeaver Celery tasks."""

from __future__ import annotations

from typing import Any, Mapping

CELERY_CONFIG_KEY = "celery modules"
CELERY_MODULE = "docassemble.ALWeaver.api_weaver_worker"
CELERY_CONFIGURATION_DOCS_URL = (
    "https://github.com/SuffolkLITLab/docassemble-ALWeaver"
    "#celery-worker-configuration"
)


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

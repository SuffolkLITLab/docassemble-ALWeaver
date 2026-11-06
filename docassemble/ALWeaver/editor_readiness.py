"""Run publication checks against an ephemeral copy of the working package."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Mapping


def repair_context_current(raw_yaml: str, finding: Mapping[str, Any]) -> bool:
    """Accept evidence only when its exact parsed block still exists in source."""
    if finding.get("rendered_jinja"):
        return False
    context = finding.get("context") or {}
    if not isinstance(context, Mapping):
        return False
    repair = context.get("repair_context") or {}
    if not isinstance(repair, Mapping):
        return False
    if repair.get("schema_version") != 1:
        return False
    from dayamlchecker.yaml_structure import parse_interview_documents

    normalized = raw_yaml.replace("\r\n", "\n").replace("\r", "\n")
    documents, _ = parse_interview_documents(normalized, "interview.yml")
    for doc in documents:
        if doc.index == repair.get("block_index"):
            return doc.source_code == repair.get("source_yaml") and hashlib.sha256(
                doc.source_code.encode("utf-8")
            ).hexdigest() == repair.get("source_sha256")
    return False


def check_package_snapshot(
    files: Mapping[str, Mapping[str, Any]],
    *,
    package: str,
    filename: str,
    raw_yaml: str,
    evidence: dict[str, Any] | None = None,
    review_level: str = "precision",
    include_llm: bool = False,
    model: str | None = None,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
) -> dict[str, Any]:
    """Overlay unsaved YAML without changing the Playground or package manifest."""
    from dayamlchecker.readiness import publication_readiness
    from dayamlchecker.yaml_structure import RuntimeOptions

    if review_level not in {"precision", "thorough"}:
        raise ValueError("Choose precision or thorough review")
    with tempfile.TemporaryDirectory(prefix="weaver-readiness-") as directory:
        root = Path(directory).resolve()
        for name, entry in files.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Unsafe package snapshot path")
            destination = root.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            content = entry["content"]
            destination.write_bytes(
                content.encode("utf-8") if isinstance(content, str) else content
            )
        question_path = root / "docassemble" / package / "data" / "questions" / filename
        if not question_path.is_file():
            raise ValueError("Current interview is missing from the package snapshot")
        question_path.write_text(raw_yaml, encoding="utf-8")
        report = publication_readiness(
            root,
            evidence=evidence,
            style_options=RuntimeOptions(
                style_enabled=True,
                style_review_level=review_level,
                style_include_llm=False,
                style_openai_model=model,
                spellcheck=None,
            ),
        )

        remote_failure = None
        if include_llm:
            from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]

            # Keep a complete local report if the optional provider stage exhausts
            # the Celery soft limit. Never restart paid calls after the timeout.
            try:
                report = publication_readiness(
                    root,
                    evidence=evidence,
                    style_options=RuntimeOptions(
                        style_enabled=True,
                        style_review_level=review_level,
                        style_include_llm=True,
                        style_openai_model=model,
                        style_openai_api_key=openai_api_key,
                        style_openai_base_url=openai_base_url,
                        spellcheck=None,
                    ),
                )
            except SoftTimeLimitExceeded:
                remote_failure = "AI style review timed out. Local checks are available; remote review is incomplete."
            if any(
                finding.get("message_id")
                in {"style_llm_request_failed", "style_llm_configuration_error"}
                for finding in report.get("findings", [])
            ):
                remote_failure = "AI style review failed. Check the provider configuration and run the review again."
        if remote_failure:
            report["checks"].append(
                {
                    "id": "ai_style_review",
                    "status": "needs_review",
                    "severity": "warning",
                    "release_gate": True,
                    "detail": remote_failure,
                }
            )
            if report["status"] == "pass":
                report["status"] = "needs_review"

        # Temporary paths are not usable navigation targets or durable evidence.
        def relative_paths(value: Any) -> Any:
            if isinstance(value, str):
                return value.replace(str(root) + "/", "") if value != str(root) else "."
            if isinstance(value, dict):
                return {key: relative_paths(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [relative_paths(item) for item in value]
            return value

        report = relative_paths(report)
        report["working_source_sha256"] = hashlib.sha256(
            raw_yaml.encode("utf-8")
        ).hexdigest()
        report["review_level"] = review_level
        report["include_llm"] = include_llm
        return report

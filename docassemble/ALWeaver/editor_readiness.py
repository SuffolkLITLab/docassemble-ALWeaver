"""Run publication checks against an ephemeral copy of the working package."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from pathlib import Path, PurePosixPath
import tempfile
from zipfile import ZipFile
from typing import Any, Mapping

READINESS_AI_TIMEOUT = 8 * 60
READINESS_JOB_SOFT_LIMIT = 20 * 60
READINESS_JOB_HARD_LIMIT = 21 * 60


def recheck_template_syntax(report: dict[str, Any], root: Path) -> None:
    """Correct extraction-only syntax warnings using docxtpl's XML preprocessing.

    Parse only: never render expressions or execute interview code. Leave warnings
    intact if the real XML cannot be parsed. This does not validate variable values.
    """
    from docxtpl import DocxTemplate
    from jinja2 import Environment
    from dayamlchecker.readiness_review import review_view

    changed = False
    for check in report.get("checks", []):
        if check.get("id") != "document_templates":
            continue
        for template in check.get("templates", []):
            notes = template.get("notes", [])
            if not any(n.get("kind") == "template_syntax_unverified" for n in notes):
                continue
            path = (root / template["file"]).resolve()
            if not path.is_relative_to(root.resolve()):
                continue
            try:
                engine = DocxTemplate(path)
                with ZipFile(path) as archive:
                    parts = [
                        name
                        for name in archive.namelist()
                        if re.fullmatch(
                            r"word/(?:document|header\d+|footer\d+|footnotes|endnotes)\.xml",
                            name,
                        )
                    ]
                    if "word/document.xml" not in parts:
                        continue
                    for name in parts:
                        Environment().parse(
                            engine.patch_xml(archive.read(name).decode("utf-8"))
                        )
            except Exception:
                continue
            template["notes"] = [
                n for n in notes if n.get("kind") != "template_syntax_unverified"
            ]
            template["syntax_recheck"] = (
                "Parsed Word XML after docxtpl preprocessing; variable values and runtime rendering were not tested."
            )
            changed = True
        if changed:
            check["templates"] = [
                t for t in check.get("templates", []) if t.get("notes")
            ]
            if not check["templates"]:
                check.update(status="pass", severity="info", release_gate=False)
    if changed:
        report["review"] = review_view(report, report.get("local_scope", {}))


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


def author_review(report: Mapping[str, Any]) -> dict[str, Any]:
    """Present concrete actions while preserving the checker's raw evidence."""
    view = deepcopy(report.get("review") or {})
    # Weaver does not collect or validate human-review attestations.
    view.pop("process_evidence", None)
    if report.get("research"):
        # The methodology already shows the actual research gaps. A second,
        # generic "review the coverage limits" finding adds no action.
        view["coverage"] = [
            item
            for item in view.get("coverage", [])
            if (item.get("check_id") or item.get("id")) != "instructions_research"
        ]
    view.setdefault("cleanup", [])
    actionable = []
    findings = report.get("findings", [])
    for item in view.get("actionable", []):
        evidence = item.get("evidence") or {}
        if item.get("check_id") == "metadata" and evidence.get("missing"):
            item["message"] = (
                "Add publication metadata: " + ", ".join(evidence["missing"]) + "."
            )
            item["reason"] = (
                "These metadata fields help people identify the interview and understand who can use it and what to prepare."
            )
        elif item.get("check_id") == "entrypoint_metadata":
            item["message"] = (
                "Add a metadata block with a title to the interview's starting YAML file."
            )
            entrypoints = (report.get("local_scope") or {}).get("entrypoints", [])
            if len(entrypoints) == 1:
                item["file"] = entrypoints[0].get("file")
            item["reason"] = (
                "No local question file has a metadata title, so the checker could not identify a titled entrypoint. This does not mean the interview cannot run."
            )
        originals = [
            findings[i]
            for i in item.get("finding_indexes", [])
            if item.get("source") == "static" and 0 <= i < len(findings)
        ]
        if originals and all(
            f.get("message_id") == "missing_question_id" for f in originals
        ):
            item.update(
                release_gate=False,
                priority="low",
                reason="Stable question IDs help maintain interviews across edits, but a missing ID alone does not prevent publication.",
            )
            view["cleanup"].append(item)
            continue
        errors = (item.get("evidence") or {}).get("errors")
        if isinstance(errors, list) and errors:
            for error in errors:
                entry = dict(item)
                entry.update(
                    file=error.get("file", item.get("file")),
                    line=error.get("line"),
                    message=error.get("detail") or item.get("message"),
                    evidence=error,
                )
                if item.get("check_id") == "document_delivery" and error.get(
                    "reference"
                ):
                    entry.update(
                        message="Add the missing template "
                        + error["reference"]
                        + ", or correct the attachment's template reference.",
                        reason="This interview references a local template that is absent from the package, so that attachment cannot be generated from this snapshot.",
                    )
                actionable.append(entry)
        else:
            actionable.append(item)
    grouped = {}
    for item in actionable:
        # Repeated advice for the same file is one action with all locations.
        key = (
            item.get("source"),
            item.get("file"),
            item.get("message"),
            item.get("priority"),
            item.get("release_gate"),
        )
        if key not in grouped:
            grouped[key] = item
            item["lines"] = [item["line"]] if item.get("line") else []
        else:
            existing = grouped[key]
            if item.get("line") and item["line"] not in existing["lines"]:
                existing["lines"].append(item["line"])
            for index in item.get("finding_indexes", []):
                if index not in existing.setdefault("finding_indexes", []):
                    existing["finding_indexes"].append(index)
    view["actionable"] = list(grouped.values())
    return view


def check_package_snapshot(
    files: Mapping[str, Mapping[str, Any]],
    *,
    package: str,
    filename: str,
    raw_yaml: str,
    evidence: dict[str, Any] | None = None,
    review_level: str = "precision",
    ai_second_opinion: bool = False,
    include_research: bool = True,
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
                style_enabled=False,
                style_review_level=review_level,
                style_include_llm=False,
                style_openai_model=model,
                spellcheck=None,
            ),
        )
        recheck_template_syntax(report, root)

        research_timed_out = False
        if include_research:
            from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
            from dayamlchecker.readiness_research import (
                DEFAULT_MODEL,
                ResearchOptions,
                research_readiness,
            )
            from dayamlchecker.readiness_review import review_view

            try:
                report["research"] = research_readiness(
                    root,
                    ResearchOptions(
                        model=model or DEFAULT_MODEL,
                        timeout=READINESS_AI_TIMEOUT,
                        api_key=openai_api_key,
                        base_url=openai_base_url,
                    ),
                )
            except SoftTimeLimitExceeded:
                research_timed_out = True
                report["research"] = {
                    "status": "needs_review",
                    "execution_status": "failed",
                    "error": "Legal-source research timed out. Local checks are available.",
                    "findings": [],
                    "coverage_gaps": ["Legal-source research did not finish."],
                }
            research = report["research"]
            report["checks"].append(
                {
                    "id": "instructions_research",
                    "status": research["status"],
                    "execution_status": research["execution_status"],
                    "detail": research.get("error")
                    or "Review the sourced research findings and coverage limits.",
                }
            )
            if report["status"] == "pass" and research["status"] != "pass":
                report["status"] = "needs_review"
            report["review"] = review_view(report, report["local_scope"])

        if ai_second_opinion and research_timed_out:
            report["ai_review"] = {
                "execution_status": "failed",
                "error": "Second opinion was not started because research exhausted the job time limit.",
            }
        if ai_second_opinion and not research_timed_out:
            from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
            from dayamlchecker.readiness_ai_review import (
                AIReviewOptions,
                DEFAULT_MODEL,
                apply_ai_review,
                review_candidates,
            )

            options = AIReviewOptions(
                model=model or DEFAULT_MODEL,
                timeout=READINESS_AI_TIMEOUT,
                api_key=openai_api_key,
                base_url=openai_base_url,
            )
            try:
                report["ai_review"] = review_candidates(report, root, options)
                apply_ai_review(report)
            except SoftTimeLimitExceeded:
                report["ai_review"] = {
                    "execution_status": "failed",
                    "error": "AI second opinion timed out. All local findings are available.",
                }

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
        report["author_review"] = author_review(report)
        report["review_level"] = review_level
        report["ai_second_opinion"] = ai_second_opinion
        report["include_research"] = include_research
        return report

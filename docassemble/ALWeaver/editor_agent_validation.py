"""The one validator that decides whether Weaver may present a candidate edit.

Every agent mutation, every source patch and the editor's own unsaved-source
check run through :func:`validate_candidate_source`. Keeping a single answer to
"may Weaver accept this source?" is what stops agent editing from acquiring a
weaker standard than ordinary editing.

This module deliberately imports Docassemble-facing helpers lazily so that the
deterministic pipeline stays unit-testable without a Docassemble server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .source_document import (
    SourceDocument,
    parse_source_document,
    source_revision,
)

# Findings the linter reports are advisory unless they are outright errors.
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


def lint_level_from_severity(severity: Any) -> str:
    value = str(severity or "").strip().lower()
    if value == "red":
        return SEVERITY_ERROR
    if value == "yellow":
        return SEVERITY_WARNING
    if value == "green":
        return SEVERITY_INFO
    if value in {SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO}:
        return value
    return SEVERITY_ERROR


def block_lookup_map(blocks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for block in blocks:
        block_id = str(block.get("id") or "").strip()
        if block_id:
            lookup[block_id] = block
    return lookup


def block_line_span(block: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    try:
        line_start = int(block.get("line_start") or 0)
        line_end = int(block.get("line_end") or 0)
    except Exception:
        return None
    if line_start <= 0 or line_end < line_start:
        return None
    return (line_start, line_end)


def resolve_lint_block_id(
    finding: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    lookup = lookup or block_lookup_map(blocks)

    for key in ("block_id", "screen_id"):
        candidate = str(finding.get(key) or "").strip()
        if candidate and candidate in lookup:
            return candidate

    screen_link = str(finding.get("screen_link") or "").strip()
    if screen_link.startswith("#screen-"):
        candidate = screen_link[len("#screen-") :].strip()
        if candidate and candidate in lookup:
            return candidate

    line_number = finding.get("line_number")
    numeric_line: Optional[int]
    if isinstance(line_number, int):
        numeric_line = line_number
    elif isinstance(line_number, str):
        try:
            numeric_line = int(line_number.strip())
        except ValueError:
            numeric_line = None
    else:
        numeric_line = None
    if numeric_line:
        for block in blocks:
            span = block_line_span(block)
            if not span:
                continue
            if span[0] <= numeric_line <= span[1]:
                return str(block.get("id") or "").strip() or None

    rule_id = str(finding.get("rule_id") or "").strip()
    if rule_id in {"missing-metadata-fields", "missing-custom-theme"}:
        for block in blocks:
            if block.get("type") == "metadata":
                return str(block.get("id") or "").strip() or None

    problematic_text = str(finding.get("problematic_text") or "").strip()
    if problematic_text:
        for block in blocks:
            if problematic_text in str(block.get("yaml") or ""):
                return str(block.get("id") or "").strip() or None
            if problematic_text in str(block.get("title") or ""):
                return str(block.get("id") or "").strip() or None

    return None


def annotate_lint_findings(
    findings: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
    *,
    source_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Attach block identity and a normalised level to raw linter findings."""
    lookup = block_lookup_map(blocks)
    annotated: List[Dict[str, Any]] = []
    for finding in findings:
        item = dict(finding)
        if item.get("severity") is not None:
            item["level"] = lint_level_from_severity(item.get("severity"))
        else:
            item["level"] = lint_level_from_severity(item.get("level"))
        # Both spellings are published: the editor drawer reads `level` and the
        # agent diagnostic contract reads `severity`.
        item["severity"] = item["level"]
        block_id = resolve_lint_block_id(item, blocks, lookup)
        if block_id:
            item["block_id"] = block_id
            block = lookup.get(block_id)
            if block:
                item.setdefault("block_title", block.get("title"))
                item.setdefault("block_type", block.get("type"))
                item.setdefault("line_start", block.get("line_start"))
                item.setdefault("line_end", block.get("line_end"))
        if source_name:
            item.setdefault("source_name", source_name)
        annotated.append(item)
    return annotated


def lint_summary_for_findings(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 0, SEVERITY_INFO: 0}
    for finding in findings:
        level = lint_level_from_severity(
            finding.get("level") or finding.get("severity")
        )
        if level not in summary:
            level = SEVERITY_ERROR
        summary[level] += 1
    return summary


def source_range_for_line(
    raw_yaml: str, line_number: Any, column_number: Any = 1
) -> Optional[Dict[str, Any]]:
    """Return a one-line source range with line, column, and character offsets."""
    try:
        line = int(line_number)
        column = max(1, int(column_number or 1))
    except (TypeError, ValueError):
        return None
    source_lines = raw_yaml.splitlines(keepends=True)
    if line == len(source_lines) + 1 and raw_yaml.endswith(("\n", "\r")):
        return {
            "start": {"line": line, "column": column, "offset": len(raw_yaml)},
            "end": {"line": line, "column": column, "offset": len(raw_yaml)},
        }
    if line < 1 or line > len(source_lines):
        return None
    line_text = source_lines[line - 1]
    line_content = line_text.rstrip("\r\n")
    start_of_line = sum(len(item) for item in source_lines[: line - 1])
    start_offset = start_of_line + min(column - 1, len(line_content))
    end_offset = start_of_line + len(line_content)
    return {
        "start": {"line": line, "column": column, "offset": start_offset},
        "end": {
            "line": line,
            "column": len(line_content) + 1,
            "offset": end_offset,
        },
    }


def dayamlchecker_findings(raw_yaml: str, filename: str) -> List[Dict[str, Any]]:
    """Run DAYamlChecker and translate its errors into editor diagnostics.

    Indirected through a module-level function so tests can substitute the
    checker without installing it.

    The checker itself can raise on constructs Weaver deliberately preserves —
    a custom YAML tag under a key it tries to compile as Mako, for instance. A
    checker that cannot run is not the same as a file that failed a check, so
    that is reported as a warning rather than crashing the request or being
    silently swallowed.
    """
    from dayamlchecker.yaml_structure import find_errors_from_string  # type: ignore

    findings: List[Dict[str, Any]] = []
    try:
        checker_errors = list(find_errors_from_string(raw_yaml, input_file=filename))
    except Exception as exc:  # noqa: BLE001 - the checker is third-party
        return [
            {
                "level": SEVERITY_WARNING,
                "severity": SEVERITY_WARNING,
                "message": (
                    "DAYamlChecker could not analyse this interview, so its checks "
                    f"were skipped ({type(exc).__name__}). Weaver's own structural "
                    "checks still apply."
                ),
                "variable": "",
                "filename": filename,
                "line_number": None,
                "source_range": None,
                "yaml_path": None,
                "source": "dayamlchecker",
            }
        ]

    for checker_error in checker_errors:
        message = str(getattr(checker_error, "err_str", "") or checker_error).strip()
        lowered = message.lower()
        level = SEVERITY_ERROR
        if lowered.startswith("warning:"):
            level = SEVERITY_WARNING
            message = message[len("warning:") :].strip()
        elif lowered.startswith("info:"):
            level = SEVERITY_INFO
            message = message[len("info:") :].strip()
        variable = ""
        quoted = re.search(r'"([^"]+)"', message) or re.search(r"'([^']+)'", message)
        if quoted:
            variable = quoted.group(1)
        yaml_path = getattr(checker_error, "yaml_path", None) or getattr(
            checker_error, "path", None
        )
        line_number = getattr(checker_error, "line_number", None)
        findings.append(
            {
                "level": level,
                "severity": level,
                "message": message,
                "variable": variable,
                "filename": filename,
                "line_number": line_number,
                "source_range": source_range_for_line(raw_yaml, line_number),
                "yaml_path": None if yaml_path is None else str(yaml_path),
                "source": "dayamlchecker",
            }
        )
    return findings


def _yaml_stream_findings(raw_yaml: str, filename: str) -> List[Dict[str, Any]]:
    try:
        list(yaml.compose_all(raw_yaml))
    except yaml.MarkedYAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line_number = getattr(mark, "line", None)
        column_number = getattr(mark, "column", None)
        line_number = line_number + 1 if isinstance(line_number, int) else None
        column_number = column_number + 1 if isinstance(column_number, int) else 1
        message = str(getattr(exc, "problem", "") or "Invalid YAML syntax").strip()
        return [
            {
                "level": SEVERITY_ERROR,
                "severity": SEVERITY_ERROR,
                "message": message,
                "filename": filename,
                "line_number": line_number,
                "source_range": source_range_for_line(
                    raw_yaml, line_number, column_number
                ),
                "yaml_path": None,
                "source": "yaml-parser",
            }
        ]
    except yaml.YAMLError as exc:
        return [
            {
                "level": SEVERITY_ERROR,
                "severity": SEVERITY_ERROR,
                "message": str(exc).strip() or "Invalid YAML syntax",
                "filename": filename,
                "line_number": None,
                "source_range": None,
                "yaml_path": None,
                "source": "yaml-parser",
            }
        ]
    return []


def _dedupe(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set = set()
    for finding in findings:
        key = (
            str(finding.get("level") or ""),
            str(finding.get("message") or ""),
            str(finding.get("line_number") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def validate_source_text(raw_yaml: str, filename: str) -> List[Dict[str, Any]]:
    """Validate exactly ``raw_yaml`` and return Weaver-owned diagnostics."""
    from .editor_utils import parse_interview_yaml

    findings = _yaml_stream_findings(raw_yaml, filename)
    findings.extend(dayamlchecker_findings(raw_yaml, filename))
    model = parse_interview_yaml(raw_yaml)
    return annotate_lint_findings(
        _dedupe(findings), model.get("blocks", []), source_name="unsaved-source"
    )


def _document_diagnostic_to_dict(diagnostic: Any, filename: str) -> Dict[str, Any]:
    item = diagnostic.to_dict()
    level = lint_level_from_severity(item.get("severity"))
    item["level"] = level
    item["severity"] = level
    item.setdefault("filename", filename)
    item["source"] = "source-document"
    source_range = item.get("source_range")
    line_number = None
    if isinstance(source_range, dict):
        start = source_range.get("start")
        if isinstance(start, dict):
            line_number = start.get("line")
    item.setdefault("line_number", line_number)
    return item


def deterministic_style_findings(raw_yaml: str) -> List[Dict[str, Any]]:
    """Run the ALDashboard linter with the LLM reviewer disabled.

    An LLM linter may stay advisory, but it must never decide whether Weaver
    accepts a candidate, so the automatic gate always passes ``include_llm=False``.
    """
    from docassemble.ALDashboard.interview_linter import (  # type: ignore
        lint_interview_content,
    )

    result = lint_interview_content(raw_yaml, include_llm=False)
    findings = result.get("findings", []) if isinstance(result, dict) else []
    return findings if isinstance(findings, list) else []


@dataclass
class CandidateValidation:
    """The verdict on one complete candidate source document."""

    structurally_valid: bool
    blocking: bool
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    model: Optional[Dict[str, Any]] = None
    source_document: Optional[SourceDocument] = None
    revision: str = ""

    @property
    def summary(self) -> Dict[str, int]:
        return lint_summary_for_findings(self.diagnostics)

    def blocking_diagnostics(self) -> List[Dict[str, Any]]:
        return [
            item
            for item in self.diagnostics
            if lint_level_from_severity(item.get("level") or item.get("severity"))
            == SEVERITY_ERROR
        ]

    def public_summary(self) -> Dict[str, Any]:
        counts = self.summary
        return {
            "count": len(self.diagnostics),
            "errors": counts[SEVERITY_ERROR],
            "warnings": counts[SEVERITY_WARNING],
            "infos": counts[SEVERITY_INFO],
        }


def validate_candidate_source(
    *,
    filename: str,
    raw_yaml: str,
    run_style_checks: bool = False,
) -> CandidateValidation:
    """Answer: may Weaver present this candidate as a valid edit?

    The pipeline is parse_source_document → YAML stream check →
    parse_interview_yaml → Weaver source diagnostics → DAYamlChecker →
    optional deterministic ALDashboard lint. Any error-severity diagnostic is
    blocking; warnings and infos are reported but do not block.
    """
    revision = source_revision(raw_yaml)
    source_document = parse_source_document(filename, raw_yaml)
    diagnostics: List[Dict[str, Any]] = [
        _document_diagnostic_to_dict(item, filename)
        for item in source_document.diagnostics
    ]

    if not source_document.structurally_valid:
        # A broken YAML stream makes every later stage report noise about
        # damage the first diagnostic already explains.
        return CandidateValidation(
            structurally_valid=False,
            blocking=True,
            diagnostics=diagnostics,
            model=None,
            source_document=source_document,
            revision=revision,
        )

    from .editor_utils import parse_interview_yaml

    model = parse_interview_yaml(raw_yaml)
    blocks = model.get("blocks", [])

    weaver_findings = _yaml_stream_findings(raw_yaml, filename)
    weaver_findings.extend(dayamlchecker_findings(raw_yaml, filename))
    diagnostics.extend(
        annotate_lint_findings(
            _dedupe(weaver_findings), blocks, source_name="candidate"
        )
    )

    if run_style_checks:
        diagnostics.extend(
            annotate_lint_findings(
                deterministic_style_findings(raw_yaml),
                blocks,
                source_name="style-check",
            )
        )

    validation = CandidateValidation(
        structurally_valid=True,
        blocking=False,
        diagnostics=diagnostics,
        model=model,
        source_document=source_document,
        revision=revision,
    )
    validation.blocking = bool(validation.blocking_diagnostics())
    return validation

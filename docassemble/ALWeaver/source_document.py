"""Lossless source documents and atomic text-range patches for Weaver."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import difflib
import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml
from yaml.nodes import MappingNode, ScalarNode

_DOCUMENT_SEPARATOR_RE = re.compile(r"(?m)^---[ \t]*(?:#[^\r\n]*)?(?:\r\n|\n|\r|$)")


@dataclass(frozen=True)
class SourcePosition:
    offset: int
    line: int
    column: int


@dataclass(frozen=True)
class SourceRange:
    start: SourcePosition
    end: SourcePosition


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    message: str
    filename: str
    source_range: Optional[SourceRange] = None
    block_id: Optional[str] = None
    yaml_path: Optional[List[Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SourceBlock:
    block_id: str
    document_index: int
    start_offset: int
    end_offset: int
    raw_text: str
    parsed_value: Any = None
    block_type: Optional[str] = None
    supported: bool = False
    unsupported_reasons: List[str] = field(default_factory=list)
    property_ranges: Dict[str, SourceRange] = field(default_factory=dict)


@dataclass
class SourceDocument:
    filename: str
    raw_text: str
    revision: str
    documents: List[SourceBlock]
    diagnostics: List[Diagnostic]

    @property
    def structurally_valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)


def source_revision(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def _position(raw_text: str, offset: int) -> SourcePosition:
    line = raw_text.count("\n", 0, offset) + 1
    previous_newline = raw_text.rfind("\n", 0, offset)
    column = offset + 1 if previous_newline < 0 else offset - previous_newline
    return SourcePosition(offset=offset, line=line, column=column)


def _range(raw_text: str, start: int, end: int) -> SourceRange:
    return SourceRange(start=_position(raw_text, start), end=_position(raw_text, end))


def _document_bodies(raw_text: str) -> List[Tuple[int, int, str]]:
    bodies: List[Tuple[int, int, str]] = []
    start = 0
    for separator in _DOCUMENT_SEPARATOR_RE.finditer(raw_text):
        bodies.append((start, separator.start(), raw_text[start : separator.start()]))
        start = separator.end()
    bodies.append((start, len(raw_text), raw_text[start:]))
    return bodies


def _block_type(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    keys = set(value)
    if "metadata" in keys:
        return "metadata"
    if keys & {"include", "includes"}:
        return "includes"
    if "default screen parts" in keys:
        return "default_screen_parts"
    if "review" in keys:
        return "review"
    if keys & {"attachment", "attachments"}:
        return "attachment"
    if "question" in keys:
        return "question"
    if "code" in keys:
        return "code"
    if "objects" in keys:
        return "objects"
    if "template" in keys:
        return "template"
    if "table" in keys:
        return "table"
    return "other"


def _block_id(document_index: int, start: int, raw_text: str, value: Any) -> str:
    if isinstance(value, dict) and value.get("id"):
        return str(value["id"])
    fingerprint = hashlib.sha256(
        (str(start) + "\0" + raw_text).encode("utf-8")
    ).hexdigest()[:12]
    return f"block-{document_index}-{fingerprint}"


def _property_ranges(
    full_source: str, body_start: int, node: Optional[MappingNode]
) -> Dict[str, SourceRange]:
    ranges: Dict[str, SourceRange] = {}
    if not isinstance(node, MappingNode):
        return ranges
    for key_node, value_node in node.value:
        if not isinstance(key_node, ScalarNode):
            continue
        key = str(key_node.value)
        start = body_start + value_node.start_mark.index
        end = body_start + value_node.end_mark.index
        if key not in ranges:
            ranges[key] = _range(full_source, start, end)
    return ranges


def parse_source_document(filename: str, raw_text: str) -> SourceDocument:
    """Parse source for analysis while retaining every original character."""
    documents: List[SourceBlock] = []
    diagnostics: List[Diagnostic] = []
    for document_index, (start, end, body) in enumerate(_document_bodies(raw_text)):
        parsed_value: Any = None
        node = None
        unsupported_reasons: List[str] = []
        if not body.strip():
            unsupported_reasons.append("empty document")
        else:
            try:
                node = yaml.compose(body)
            except yaml.YAMLError as exc:
                mark = getattr(exc, "problem_mark", None)
                error_start = start + (getattr(mark, "index", 0) or 0)
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        message=str(exc),
                        filename=filename,
                        source_range=_range(raw_text, error_start, error_start),
                    )
                )
                unsupported_reasons.append("structurally invalid YAML")
            if node is not None:
                try:
                    parsed_value = yaml.safe_load(body)
                except yaml.YAMLError as exc:
                    unsupported_reasons.append(
                        "YAML tags or values are not supported by the graphical parser"
                    )
                    diagnostics.append(
                        Diagnostic(
                            severity="warning",
                            message=str(exc),
                            filename=filename,
                            source_range=_range(raw_text, start, end),
                        )
                    )
        if node is not None and not isinstance(node, MappingNode):
            unsupported_reasons.append("top-level document is not a mapping")
        block_id = _block_id(document_index, start, body, parsed_value)
        documents.append(
            SourceBlock(
                block_id=block_id,
                document_index=document_index,
                start_offset=start,
                end_offset=end,
                raw_text=body,
                parsed_value=parsed_value,
                block_type=_block_type(parsed_value),
                supported=bool(
                    isinstance(node, MappingNode)
                    and isinstance(parsed_value, dict)
                    and not unsupported_reasons
                ),
                unsupported_reasons=unsupported_reasons,
                property_ranges=_property_ranges(
                    raw_text, start, node if isinstance(node, MappingNode) else None
                ),
            )
        )
    return SourceDocument(
        filename=filename,
        raw_text=raw_text,
        revision=source_revision(raw_text),
        documents=documents,
        diagnostics=diagnostics,
    )


def apply_range_operations(
    raw_text: str, operations: Sequence[Dict[str, Any]]
) -> Tuple[str, List[Dict[str, Any]]]:
    """Validate and atomically apply operations expressed against one revision."""
    normalized: List[Dict[str, Any]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError(f"Operation {index} must be an object")
        if operation.get("type") != "replace-range":
            raise ValueError(f"Operation {index} has an unsupported type")
        start = operation.get("start")
        end = operation.get("end")
        text = operation.get("text")
        if type(start) is not int or type(end) is not int:  # bool is not an offset
            raise ValueError(f"Operation {index} offsets must be integers")
        if not isinstance(text, str):
            raise ValueError(f"Operation {index} text must be a string")
        if start < 0 or end < start or end > len(raw_text):
            raise ValueError(f"Operation {index} range is outside the source")
        normalized.append(
            {"type": "replace-range", "start": start, "end": end, "text": text}
        )

    ordered = sorted(normalized, key=lambda item: (item["start"], item["end"]))
    previous_end = -1
    previous_start = -1
    for operation in ordered:
        if operation["start"] < previous_end or operation["start"] == previous_start:
            raise ValueError(
                "Patch operations must not overlap or share a start offset"
            )
        previous_start = operation["start"]
        previous_end = operation["end"]

    updated = raw_text
    for operation in reversed(ordered):
        updated = (
            updated[: operation["start"]]
            + operation["text"]
            + updated[operation["end"] :]
        )
    return updated, ordered


def unified_source_diff(before: str, after: str, filename: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=filename,
            tofile=filename,
        )
    )

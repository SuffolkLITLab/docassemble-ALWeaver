"""Utilities for the WYSIWYM interview editor.

Provides YAML parsing into a normalized block model, order-builder
translation (structured steps <-> Python code), and playground helpers
for reading/writing interview files.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from .docassemble_compat import create_playground, create_saved_file

__all__ = [
    "parse_interview_yaml",
    "source_revision",
    "metadata_source_slice",
    "update_metadata_documents_in_yaml",
    "serialize_blocks_to_yaml",
    "parse_order_code",
    "serialize_order_steps",
    "generate_draft_order",
    "canonicalize_block_yaml",
    "insert_block_in_yaml",
    "update_block_in_yaml",
    "delete_block_from_yaml",
    "comment_out_block_in_yaml",
    "enable_commented_block_in_yaml",
    "reorder_blocks_in_yaml",
    "playground_read_yaml",
    "playground_write_yaml",
    "playground_list_projects",
    "playground_list_yaml_files",
    "playground_get_variables",
    "rename_saved_file",
    "delete_saved_file",
]


# ---------------------------------------------------------------------------
# Block model
# ---------------------------------------------------------------------------

BLOCK_TYPE_QUESTION = "question"
BLOCK_TYPE_CODE = "code"
BLOCK_TYPE_METADATA = "metadata"
BLOCK_TYPE_INCLUDES = "includes"
BLOCK_TYPE_DEFAULT_SCREEN_PARTS = "default_screen_parts"
BLOCK_TYPE_OBJECTS = "objects"
BLOCK_TYPE_ATTACHMENT = "attachment"
BLOCK_TYPE_REVIEW = "review"
BLOCK_TYPE_TABLE = "table"
BLOCK_TYPE_TEMPLATE = "template"
BLOCK_TYPE_TERMS = "terms"
BLOCK_TYPE_SECTIONS = "sections"
BLOCK_TYPE_COMMENTED = "commented"
BLOCK_TYPE_OTHER = "other"

# Keys whose presence unambiguously identifies certain block types.
_METADATA_KEYS = {"metadata"}
_INCLUDE_KEYS = {"include", "includes"}
_DEFAULT_SCREEN_KEYS = {"default screen parts"}

_METADATA_DOCUMENT_TYPES = {
    BLOCK_TYPE_METADATA,
    BLOCK_TYPE_INCLUDES,
    BLOCK_TYPE_DEFAULT_SCREEN_PARTS,
}

_YAML_DOCUMENT_SEPARATOR_RE = re.compile(
    r"(?m)^---[ \t]*(?:#[^\r\n]*)?(?:\r\n|\n|\r|$)"
)

_BLOCK_KEY_ORDER = [
    "metadata",
    "modules",
    "features",
    "include",
    "includes",
    "default screen parts",
    "sections",
    "terms",
    "event",
    "id",
    "generic object",
    "mandatory",
    "if",
    "template",
    "subject",
    "content",
    "question",
    "subquestion",
    "under",
    "buttons",
    "fields",
    "review",
    "tabular",
    "table",
    "rows",
    "columns",
    "show incomplete",
    "show if empty",
    "edit",
    "attachment",
    "attachments",
    "continue button field",
    "continue button label",
    "sets",
    "only sets",
    "need",
    "objects",
    "code",
]

_LITERAL_TEXT_KEYS = {
    "question",
    "subquestion",
    "under",
    "continue button label",
}

# Keys whose values are always serialised as block-literal (|) style, even
# when the text is a single line.
_FORCE_LITERAL_KEYS: set = {"question", "subquestion", "code"}


class _CanonicalDumper(yaml.SafeDumper):
    pass


def _represent_canonical_str(dumper: yaml.SafeDumper, data: str):
    normalized = data.rstrip("\n")
    if "\n" in normalized:
        return dumper.represent_scalar("tag:yaml.org,2002:str", normalized, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", normalized)


_CanonicalDumper.add_representer(str, _represent_canonical_str)


class _LiteralStr(str):
    """String subtype that always serialises as a block-literal (|) scalar."""

    __slots__ = ()


def _represent_literal_str(dumper: yaml.SafeDumper, data: str):
    # Keep trailing newline in value so YAML emits '|' (not '|-').
    text = str(data)
    if not text.endswith("\n"):
        text += "\n"
    return dumper.represent_scalar("tag:yaml.org,2002:str", text, style="|")


_CanonicalDumper.add_representer(_LiteralStr, _represent_literal_str)


def _ordered_block_dict(block: Dict[str, Any]) -> Dict[str, Any]:
    ordered: Dict[str, Any] = {}
    for key in _BLOCK_KEY_ORDER:
        if key in block:
            ordered[key] = _canonicalize_value(block[key], key=key)
    for key, value in block.items():
        if key not in ordered:
            ordered[key] = _canonicalize_value(value, key=key)
    return ordered


def _normalize_literal_text(value: str) -> str:
    if "\n" not in value and "\\n" not in value and '\\"' not in value:
        return value
    normalized = value.replace("\\r\\n", "\n").replace("\\n", "\n")
    normalized = normalized.replace('\\"', '"')
    return normalized


def _canonicalize_value(value: Any, key: Optional[str] = None) -> Any:
    if isinstance(value, dict):
        return {
            inner_key: _canonicalize_value(inner, key=inner_key)
            for inner_key, inner in value.items()
        }
    if isinstance(value, list):
        return [_canonicalize_value(item) for item in value]
    if isinstance(value, str):
        if key in _LITERAL_TEXT_KEYS:
            value = _normalize_literal_text(value)
        if key in _FORCE_LITERAL_KEYS:
            if not value.endswith("\n"):
                value += "\n"
            return _LiteralStr(value)
        return value.rstrip("\n") if "\n" in value else value
    return value


def _split_top_level_commas(text: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    quote: Optional[str] = None
    escaped = False

    for char in str(text):
        current.append(char)
        if quote:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote:
                quote = None
            continue

        if char in {'"', "'"}:
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char in ",\n" and depth == 0:
            # Newlines separate arguments as well as commas: a multi-argument
            # call is displayed one argument per line with the commas removed,
            # and that display form comes back through here on the way out.
            segment = "".join(current[:-1]).strip()
            if segment:
                parts.append(segment)
            current = []

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _split_object_using_expression(expression: str) -> Optional[Tuple[str, str]]:
    match = re.match(
        r"^(?P<class_name>[A-Za-z_][A-Za-z0-9_\.]*)\.using\((?P<args>[\s\S]*)\)$",
        str(expression or "").strip(),
    )
    if not match:
        return None
    return match.group("class_name").strip(), match.group("args").strip()


def _is_object_class_name(expression: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_\.]*$", str(expression or "").strip()))


def _should_multiline_object_args(raw_expression: str, args: Sequence[str]) -> bool:
    if "\n" in raw_expression:
        return True
    if len(args) > 1:
        return True
    compact = ", ".join(part.strip() for part in args if part.strip())
    return len(compact) > 88


def _format_object_using_args(args_text: str, raw_expression: str = "") -> str:
    args = _split_top_level_commas(args_text)
    if not args:
        return ""
    if _should_multiline_object_args(raw_expression, args):
        return "\n".join(part.strip() for part in args)
    return ", ".join(part.strip() for part in args)


def _compose_object_using_expression(class_name: str, using_args: str) -> str:
    cleaned_class_name = str(class_name or "").strip()
    cleaned_args = str(using_args or "").strip()
    if not cleaned_class_name:
        return ""
    if not cleaned_args:
        return cleaned_class_name
    if "\n" not in cleaned_args:
        return f"{cleaned_class_name}.using({cleaned_args})"
    # The display form drops the commas between arguments. Put them back, or
    # the composed expression is not valid Python.
    arguments = _split_top_level_commas(cleaned_args)
    if not arguments:
        return cleaned_class_name
    indented_args = ",\n".join(f"  {argument}" for argument in arguments)
    return f"{cleaned_class_name}.using(\n{indented_args}\n)"


def _serialize_inline_scalar(value: str) -> str:
    text = str(value or "")
    if text == "":
        return '""'
    if re.search(r"""[:#{}\[\],&*!>|'"%@`]""", text) or text.strip() != text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _serialize_objects_value(objects: Any) -> Optional[str]:
    if not isinstance(objects, list):
        return None

    lines: List[str] = ["objects:"]
    for item in objects:
        if not isinstance(item, dict) or len(item) != 1:
            return None
        name, expression = next(iter(item.items()))
        rendered_name = _serialize_inline_scalar(str(name).strip())
        expression_text = str(expression or "").strip()
        if "\n" not in expression_text:
            rendered_expression = _serialize_inline_scalar(expression_text)
            lines.append(f"  - {rendered_name}: {rendered_expression}")
            continue
        expression_lines = expression_text.splitlines()
        lines.append(f"  - {rendered_name}: {expression_lines[0].rstrip()}")
        for line in expression_lines[1:]:
            lines.append(f"      {line.rstrip()}" if line else "      ")
    return "\n".join(lines)


def _build_editor_objects(objects: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(objects, list):
        return rows

    for item in objects:
        if not isinstance(item, dict) or not item:
            continue
        name, expression = next(iter(item.items()))
        expression_text = str(expression or "").strip()
        parsed = _split_object_using_expression(expression_text)
        if parsed:
            class_name, args_text = parsed
            formatted_args = _format_object_using_args(
                args_text, raw_expression=expression_text
            )
            rows.append(
                {
                    "name": str(name).strip(),
                    "mode": "using",
                    "expression": _compose_object_using_expression(
                        class_name, formatted_args
                    ),
                    "raw_expression": expression_text,
                    "class_name": class_name,
                    "using_args": formatted_args,
                    "is_document_bundle": class_name == "ALDocumentBundle",
                }
            )
            continue
        if _is_object_class_name(expression_text):
            rows.append(
                {
                    "name": str(name).strip(),
                    "mode": "using",
                    "expression": expression_text,
                    "raw_expression": expression_text,
                    "class_name": expression_text,
                    "using_args": "",
                    "is_document_bundle": expression_text == "ALDocumentBundle",
                }
            )
            continue
        rows.append(
            {
                "name": str(name).strip(),
                "mode": "raw",
                "expression": expression_text,
                "raw_expression": expression_text,
                "class_name": "",
                "using_args": "",
                "is_document_bundle": False,
            }
        )
    return rows


def _dump_canonical_fragment(key: str, value: Any) -> str:
    return yaml.dump(
        {key: value},
        Dumper=_CanonicalDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    ).rstrip()


def canonical_block_yaml(block: Dict[str, Any]) -> str:
    ordered_block = _ordered_block_dict(block)
    if "objects" not in ordered_block:
        return yaml.dump(
            ordered_block,
            Dumper=_CanonicalDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=1000,
        ).rstrip()

    fragments: List[str] = []
    for key, value in ordered_block.items():
        if key == "objects":
            serialized_objects = _serialize_objects_value(value)
            if serialized_objects is not None:
                fragments.append(serialized_objects)
                continue
        fragments.append(_dump_canonical_fragment(key, value))
    return "\n".join(fragment for fragment in fragments if fragment).rstrip()


def canonicalize_block_yaml(block_yaml: str) -> str:
    try:
        parsed = yaml.safe_load(block_yaml)
    except yaml.YAMLError:
        return block_yaml.strip()
    if not isinstance(parsed, dict):
        return block_yaml.strip()
    if "objects" in parsed:
        return block_yaml.strip()
    return canonical_block_yaml(parsed)


def rename_saved_file(
    area: Any, directory: str, old_filename: str, new_filename: str
) -> None:
    """Rename a playground-backed file and sync the backing SavedFile storage."""

    old_path = os.path.join(directory, old_filename)
    if not os.path.isfile(old_path):
        raise FileNotFoundError(f"{old_filename} not found")

    new_path = os.path.join(directory, new_filename)
    if os.path.exists(new_path):
        raise ValueError(f"{new_filename} already exists")

    os.rename(old_path, new_path)
    area.finalize()


def delete_saved_file(area: Any, directory: str, filename: str) -> None:
    """Delete a playground-backed file and sync the backing SavedFile storage."""

    path = os.path.join(directory, filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{filename} not found")

    os.remove(path)
    area.finalize()


def _stable_block_id(index: int, block: Dict[str, Any]) -> str:
    """Derive a stable id for a parsed block.

    Uses the ``id`` key if present, otherwise falls back to a
    content-based hash combined with the positional index.
    """
    explicit_id = block.get("id")
    if explicit_id:
        return str(explicit_id)
    stable_block = {
        key: value for key, value in block.items() if not str(key).startswith("_")
    }
    raw = canonical_block_yaml(stable_block)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"block-{index}-{digest}"


def _uncomment_yaml_block(block_yaml: str) -> str:
    uncommented_lines = []
    for line in block_yaml.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        stripped = content.lstrip()
        if stripped.startswith("#"):
            comment_offset = content.index("#")
            remainder = content[comment_offset + 1 :]
            if remainder.startswith(" "):
                remainder = remainder[1:]
            uncommented_lines.append(remainder + ending)
        else:
            uncommented_lines.append(line)
    return "".join(uncommented_lines)


def _detect_block_type(block: Dict[str, Any]) -> str:
    if block.get("_commented"):
        return BLOCK_TYPE_COMMENTED
    if _METADATA_KEYS & set(block):
        return BLOCK_TYPE_METADATA
    if _INCLUDE_KEYS & set(block):
        return BLOCK_TYPE_INCLUDES
    if _DEFAULT_SCREEN_KEYS & set(block):
        return BLOCK_TYPE_DEFAULT_SCREEN_PARTS
    if "sections" in block:
        return BLOCK_TYPE_SECTIONS
    if block.get("variable name") == "al_nav_sections" and (
        "data from code" in block or "data" in block
    ):
        return BLOCK_TYPE_SECTIONS
    if "terms" in block:
        return BLOCK_TYPE_TERMS
    if "template" in block and ("content" in block or "subject" in block):
        return BLOCK_TYPE_TEMPLATE
    if "table" in block:
        return BLOCK_TYPE_TABLE
    if "review" in block:
        return BLOCK_TYPE_REVIEW
    if "attachment" in block or "attachments" in block:
        return BLOCK_TYPE_ATTACHMENT
    if "question" in block:
        return BLOCK_TYPE_QUESTION
    if "code" in block:
        return BLOCK_TYPE_CODE
    if "objects" in block:
        return BLOCK_TYPE_OBJECTS
    return BLOCK_TYPE_OTHER


def _extract_order_block_label(code_str: str, block: Dict[str, Any]) -> str:
    """Derive a meaningful label for an interview-order code block.

    Priority:
      1) Final trailing ``interview_order_xyz = True`` variable name
      2) The block's ``id:`` key
      3) First comment line (stripped of ``#``)
      4) First code line (fallback)
    """
    lines = code_str.strip().splitlines()
    # 1) Walk backwards for a trailing named-block assignment
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^(\w[\w.]*?)\s*=\s*True\s*$", stripped)
        if m:
            return m.group(1)
        break
    # 2) id: key on the block
    block_id_key = str(block.get("id", "")).strip()
    if block_id_key:
        return block_id_key
    # 3) First comment in the code
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            label = stripped.lstrip("#").strip()
            if label:
                return label
        elif stripped:
            break
    # 4) First code line
    return lines[0].strip()[:60] if lines else "Code block"


def _extract_title(block: Dict[str, Any], block_type: str) -> str:
    if block_type == BLOCK_TYPE_QUESTION:
        return str(block.get("question", "Untitled question"))
    if block_type == BLOCK_TYPE_CODE:
        code_str = str(block.get("code", ""))
        block_id_key = str(block.get("id", ""))
        is_order = (
            bool(block.get("mandatory"))
            or block_id_key.startswith("interview_order")
            or block_id_key.startswith("interview order")
        )
        if is_order:
            return _extract_order_block_label(code_str, block)
        first_line = code_str.strip().split("\n", 1)[0][:60]
        return first_line or "Code block"
    if block_type == BLOCK_TYPE_METADATA:
        meta = block.get("metadata", {})
        return (
            str(meta.get("title", "Metadata")) if isinstance(meta, dict) else "Metadata"
        )
    if block_type == BLOCK_TYPE_INCLUDES:
        return "Includes"
    if block_type == BLOCK_TYPE_DEFAULT_SCREEN_PARTS:
        return "Default screen parts"
    if block_type == BLOCK_TYPE_OBJECTS:
        return "Objects"
    if block_type == BLOCK_TYPE_ATTACHMENT:
        if "attachment" in block and isinstance(block.get("attachment"), dict):
            name = str((block.get("attachment") or {}).get("name") or "").strip()
            return name or "Attachment"
        return "Attachments"
    if block_type == BLOCK_TYPE_REVIEW:
        question = str(block.get("question") or "").strip()
        return question or "Review"
    if block_type == BLOCK_TYPE_TABLE:
        return str(block.get("table") or "Table")
    if block_type == BLOCK_TYPE_TEMPLATE:
        return str(block.get("template") or "Template")
    if block_type == BLOCK_TYPE_TERMS:
        return "Vocabulary terms"
    if block_type == BLOCK_TYPE_SECTIONS:
        if block.get("variable name") == "al_nav_sections":
            return "AL navigation sections (al_nav_sections)"
        return "Sections"
    return "Block"


def _extract_variable(block: Dict[str, Any], block_type: str) -> Optional[str]:
    # Explicit field setter
    csf = block.get("continue button field") or block.get("sets")
    if csf:
        return str(csf) if not isinstance(csf, list) else str(csf[0]) if csf else None
    if block_type == BLOCK_TYPE_QUESTION:
        fields = block.get("fields")
        if isinstance(fields, list) and fields:
            first = fields[0]
            if isinstance(first, dict):
                for val in first.values():
                    return str(val)
    if block_type == BLOCK_TYPE_CODE:
        code_str = str(block.get("code", ""))
        # Look for simple assignments
        match = re.match(r"^\s*(\S+)\s*=", code_str)
        if match:
            return match.group(1)
    return None


def _extract_tags(block: Dict[str, Any], block_type: str) -> List[str]:
    tags: List[str] = [block_type]
    if block.get("mandatory"):
        tags.append("mandatory")
    if block.get("continue button field"):
        tags.append("continue")
    if "attachment" in block or "attachments" in block:
        tags.append("attachment")
    if block_type == BLOCK_TYPE_CODE:
        code_str = str(block.get("code", ""))
        if ".gather()" in code_str:
            tags.append("gather")
    return tags


def parse_interview_yaml(raw_yaml: str) -> Dict[str, Any]:
    """Parse a multi-document Docassemble YAML into a normalised model.

    Returns a dict with keys:
        blocks: List of all blocks with metadata
        metadata_blocks: indices of metadata blocks
        include_blocks: indices of include blocks
        default_screen_parts_blocks: indices of default-screen-parts blocks
        order_blocks: indices of mandatory code blocks (interview order)
        raw_yaml: the original YAML text
    """

    def _is_comment_only_segment(segment: str) -> bool:
        lines = [line for line in segment.splitlines() if line.strip()]
        if not lines:
            return False
        return all(line.lstrip().startswith("#") for line in lines)

    segments: List[Dict[str, Any]] = []
    body_start = 0
    for separator in _YAML_DOCUMENT_SEPARATOR_RE.finditer(raw_yaml):
        body = raw_yaml[body_start : separator.start()]
        start_line = raw_yaml.count("\n", 0, body_start) + 1
        segments.append(
            {
                "start_line": start_line,
                "end_line": start_line + len(body.splitlines()) - 1,
                "text": body,
            }
        )
        body_start = separator.end()
    body = raw_yaml[body_start:]
    start_line = raw_yaml.count("\n", 0, body_start) + 1
    segments.append(
        {
            "start_line": start_line,
            "end_line": start_line + len(body.splitlines()) - 1,
            "text": body,
        }
    )

    blocks: List[Dict[str, Any]] = []
    metadata_indices: List[int] = []
    include_indices: List[int] = []
    default_sp_indices: List[int] = []
    order_indices: List[int] = []

    for i, segment in enumerate(segments):
        segment_text_raw = str(segment["text"])
        segment_text = segment_text_raw.strip()
        line_start = int(segment["start_line"])
        line_end = int(segment["end_line"])
        if not segment_text:
            continue

        if _is_comment_only_segment(segment_text_raw):
            uncommented = _uncomment_yaml_block(segment_text)
            try:
                parsed_commented = yaml.safe_load(uncommented)
            except yaml.YAMLError:
                parsed_commented = None
            underlying_type = BLOCK_TYPE_OTHER
            if isinstance(parsed_commented, dict):
                doc = dict(parsed_commented)
                underlying_type = _detect_block_type(doc)
            elif parsed_commented is None:
                doc = {"_raw": uncommented}
            else:
                doc = {"_raw": str(parsed_commented)}
            if isinstance(doc, dict):
                doc["_commented"] = True
                doc["_commented_type"] = underlying_type
                doc["_commented_yaml"] = segment_text
            block_type = BLOCK_TYPE_COMMENTED
            block_id = _stable_block_id(i, doc)
            tags = [BLOCK_TYPE_COMMENTED]
            for tag in _extract_tags(doc, underlying_type):
                if tag not in tags:
                    tags.append(tag)
            commented_entry: Dict[str, Any] = {
                "id": block_id,
                "index": i,
                "line_start": line_start,
                "line_end": line_end,
                "type": block_type,
                "title": _extract_title(doc, underlying_type),
                "variable": _extract_variable(doc, underlying_type),
                "tags": tags,
                "yaml": segment_text,
                "data": doc,
            }
            blocks.append(commented_entry)
            continue

        try:
            doc = yaml.safe_load(segment_text_raw)
        except yaml.YAMLError:
            blocks.append(
                {
                    "id": _stable_block_id(i, {"_raw": segment_text}),
                    "index": i,
                    "line_start": line_start,
                    "line_end": line_end,
                    "type": BLOCK_TYPE_OTHER,
                    "title": "Unparseable block",
                    "variable": None,
                    "tags": [BLOCK_TYPE_OTHER],
                    "yaml": segment_text,
                    "data": {"_unparseable": True, "_raw": segment_text},
                }
            )
            continue

        if doc is None:
            continue

        if not isinstance(doc, dict):
            doc = {"_raw": str(doc)}

        block_type = _detect_block_type(doc)
        block_id = _stable_block_id(i, doc)
        editor_objects = (
            _build_editor_objects(doc.get("objects")) if "objects" in doc else []
        )
        # The source shown in a block's YAML tab must be the source the user
        # wrote.  Canonicalizing it here silently discarded comments, anchors,
        # quoting and scalar styles before the user had made any edit.
        block_yaml = segment_text_raw.strip("\r\n")

        block_entry: Dict[str, Any] = {
            "id": block_id,
            "index": i,
            "line_start": line_start,
            "line_end": line_end,
            "type": block_type,
            "title": _extract_title(doc, block_type),
            "variable": _extract_variable(doc, block_type),
            "tags": _extract_tags(doc, block_type),
            "yaml": block_yaml,
            "data": doc,
        }
        if editor_objects:
            block_entry["editor_objects"] = editor_objects

        blocks.append(block_entry)

        if block_type == BLOCK_TYPE_METADATA:
            metadata_indices.append(i)
        elif block_type == BLOCK_TYPE_INCLUDES:
            include_indices.append(i)
        elif block_type == BLOCK_TYPE_DEFAULT_SCREEN_PARTS:
            default_sp_indices.append(i)
        elif block_type == BLOCK_TYPE_CODE and doc.get("mandatory"):
            order_indices.append(i)
        elif block_type == BLOCK_TYPE_CODE:
            block_id_str = str(doc.get("id", ""))
            if block_id_str.startswith("interview_order") or block_id_str.startswith(
                "interview order"
            ):
                order_indices.append(i)

    return {
        "blocks": blocks,
        "metadata_blocks": metadata_indices,
        "include_blocks": include_indices,
        "default_screen_parts_blocks": default_sp_indices,
        "order_blocks": order_indices,
        "raw_yaml": raw_yaml,
    }


def source_revision(raw_yaml: str) -> str:
    """Return the content revision used for optimistic source updates."""
    return hashlib.sha256(raw_yaml.encode("utf-8")).hexdigest()


def _source_document_bodies(raw_yaml: str) -> List[Tuple[int, int, str]]:
    """Split YAML documents while retaining exact source offsets for each body."""
    bodies: List[Tuple[int, int, str]] = []
    body_start = 0
    for separator in _YAML_DOCUMENT_SEPARATOR_RE.finditer(raw_yaml):
        bodies.append(
            (body_start, separator.start(), raw_yaml[body_start : separator.start()])
        )
        body_start = separator.end()
    bodies.append((body_start, len(raw_yaml), raw_yaml[body_start:]))
    return bodies


def _metadata_document_type(document_body: str) -> Optional[str]:
    if not document_body.strip():
        return None
    try:
        value = yaml.safe_load(document_body)
    except yaml.YAMLError as exc:
        raise ValueError(f"Unable to parse metadata YAML: {exc}") from exc
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Metadata editor documents must be YAML mappings")
    block_type = _detect_block_type(value)
    if block_type not in _METADATA_DOCUMENT_TYPES:
        raise ValueError(
            "Metadata editor content may contain only metadata, include, and "
            "default screen parts documents"
        )
    return block_type


def metadata_source_slice(raw_yaml: str) -> str:
    """Return exact metadata-related document bodies for source-mode editing."""
    documents: List[str] = []
    for _start, _end, body in _source_document_bodies(raw_yaml):
        try:
            block_type = _metadata_document_type(body)
        except ValueError:
            continue
        if block_type is not None:
            documents.append(body.strip("\r\n"))
    return "\n---\n".join(documents)


def update_metadata_documents_in_yaml(full_yaml: str, edited_yaml: str) -> str:
    """Replace only safely identified metadata-related YAML document bodies.

    Document separators and every non-metadata source byte remain untouched. The
    submitted documents must correspond one-for-one, by type and order, with the
    existing metadata-related documents. Insertion is intentionally refused until
    the general lossless patch model can place a new document safely.
    """
    current_documents: List[Tuple[int, int, str, str]] = []
    for start, end, body in _source_document_bodies(full_yaml):
        try:
            block_type = _metadata_document_type(body)
        except ValueError:
            # Invalid or unsupported non-target source must not prevent an exact
            # replacement of a separately identifiable metadata document.
            continue
        if block_type is not None:
            current_documents.append((start, end, body, block_type))

    if not current_documents:
        raise ValueError(
            "No metadata-related document could be identified safely. "
            "Edit this interview in full source mode."
        )

    edited_documents: List[Tuple[str, str]] = []
    for _start, _end, body in _source_document_bodies(edited_yaml):
        block_type = _metadata_document_type(body)
        if block_type is not None:
            edited_documents.append((body.strip("\r\n"), block_type))

    current_types = [item[3] for item in current_documents]
    edited_types = [item[1] for item in edited_documents]
    if edited_types != current_types:
        raise ValueError(
            "Metadata documents no longer match the source file. "
            "Reload the file or edit it in full source mode."
        )

    updated = full_yaml
    for (start, end, original_body, _block_type), (
        edited_body,
        _edited_type,
    ) in reversed(list(zip(current_documents, edited_documents))):
        leading_length = len(original_body) - len(original_body.lstrip("\r\n"))
        trailing_length = len(original_body) - len(original_body.rstrip("\r\n"))
        leading = original_body[:leading_length]
        trailing = (
            original_body[len(original_body) - trailing_length :]
            if trailing_length
            else ""
        )
        replacement = leading + edited_body + trailing
        updated = updated[:start] + replacement + updated[end:]
    return updated


def serialize_blocks_to_yaml(blocks: Sequence[Dict[str, Any]]) -> str:
    """Re-serialize a list of block dicts (with ``yaml`` key) back to a full
    multi-document YAML string."""
    parts: List[str] = []
    for block in blocks:
        block_yaml = block.get("yaml", "").strip()
        if block_yaml and block_yaml != "{}":
            parts.append(block_yaml)
    return "\n---\n".join(parts)


def _unique_block_document(
    full_yaml: str, block_id: str
) -> Tuple[Dict[str, Any], int, int, str]:
    """Return one block and its exact document-body source range."""
    matches = [
        block
        for block in parse_interview_yaml(full_yaml)["blocks"]
        if block["id"] == block_id
    ]
    if not matches:
        raise ValueError(f"Block with id {block_id!r} not found in interview YAML")
    if len(matches) != 1:
        raise ValueError(
            f"Block id {block_id!r} is duplicated; edit the IDs in source mode first"
        )
    block = matches[0]
    bodies = _source_document_bodies(full_yaml)
    document_index = int(block["index"])
    if document_index < 0 or document_index >= len(bodies):
        raise ValueError(f"Could not map block {block_id!r} safely to source")
    start, end, body = bodies[document_index]
    return block, start, end, body


def _mapping_value_ranges(yaml_text: str) -> Dict[str, Tuple[int, int]]:
    """Return exact top-level YAML value ranges, or an empty mapping."""
    try:
        node = yaml.compose(yaml_text)
    except yaml.YAMLError:
        return {}
    if not isinstance(node, yaml.MappingNode):
        return {}
    ranges: Dict[str, Tuple[int, int]] = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, yaml.ScalarNode):
            return {}
        key = str(key_node.value)
        if key in ranges:
            return {}
        ranges[key] = (value_node.start_mark.index, value_node.end_mark.index)
    return ranges


def _merge_changed_mapping_values(
    original_body: str, edited_body: str
) -> Optional[str]:
    """Patch only semantically changed values in a graphical block edit.

    This keeps comments, anchors, quote choices and scalar styles on unchanged
    properties.  It is deliberately limited to edits with the same top-level
    keys; structural changes fall back to exact document-body replacement.
    """
    try:
        original = yaml.safe_load(original_body)
        edited = yaml.safe_load(edited_body)
    except yaml.YAMLError:
        return None
    if not isinstance(original, dict) or not isinstance(edited, dict):
        return None
    if list(original.keys()) != list(edited.keys()):
        return None
    original_ranges = _mapping_value_ranges(original_body)
    edited_ranges = _mapping_value_ranges(edited_body)
    if set(original_ranges) != set(original) or set(edited_ranges) != set(edited):
        return None

    def normalized_graphical_value(key: str, value: Any) -> Any:
        """Remove explicit values that are identical to graphical defaults."""
        if isinstance(value, str):
            # Textareas do not represent YAML's final line break separately.
            # Treat it as presentation so touching another control does not
            # collapse an unchanged literal block scalar to a plain scalar.
            return value.rstrip("\r\n")
        if key == "fields" and isinstance(value, list):
            normalized_fields: List[Any] = []
            for field in value:
                if not isinstance(field, dict):
                    normalized_fields.append(field)
                    continue
                normalized_field = dict(field)
                if str(normalized_field.get("datatype", "")).lower() == "text":
                    normalized_field.pop("datatype", None)
                if normalized_field.get("required") is True:
                    normalized_field.pop("required", None)
                normalized_fields.append(normalized_field)
            return normalized_fields
        return value

    operations: List[Tuple[int, int, str]] = []
    for key in original:
        if normalized_graphical_value(
            str(key), original[key]
        ) == normalized_graphical_value(str(key), edited[key]):
            continue
        start, end = original_ranges[str(key)]
        edited_start, edited_end = edited_ranges[str(key)]
        replacement = edited_body[edited_start:edited_end]
        original_fragment = original_body[start:end]
        if original_fragment.endswith("\r\n") and not replacement.endswith(
            ("\r", "\n")
        ):
            replacement += "\r\n"
        elif original_fragment.endswith("\n") and not replacement.endswith(
            ("\r", "\n")
        ):
            replacement += "\n"
        elif original_fragment.endswith("\r") and not replacement.endswith(
            ("\r", "\n")
        ):
            replacement += "\r"
        operations.append((start, end, replacement))
    updated = original_body
    for start, end, replacement in reversed(operations):
        updated = updated[:start] + replacement + updated[end:]
    return updated


def _replace_document_body(
    full_yaml: str, start: int, end: int, replacement: str
) -> str:
    return full_yaml[:start] + replacement + full_yaml[end:]


def update_block_in_yaml(
    full_yaml: str,
    block_id: str,
    new_block_yaml: str,
    *,
    preserve_unchanged_annotations: bool = False,
) -> str:
    """Replace a single block in a full interview YAML by its id.

    Locates the block matching *block_id* and replaces only its exact source
    range.  Other documents and separators are never serialized again.
    """
    _block, start, end, original_body = _unique_block_document(full_yaml, block_id)
    edited_body = new_block_yaml.strip("\r\n")
    replacement: Optional[str] = None
    if preserve_unchanged_annotations:
        replacement = _merge_changed_mapping_values(original_body, edited_body)
    if replacement is None:
        leading_len = len(original_body) - len(original_body.lstrip("\r\n"))
        trailing_len = len(original_body) - len(original_body.rstrip("\r\n"))
        leading = original_body[:leading_len]
        trailing = original_body[-trailing_len:] if trailing_len else ""
        replacement = leading + edited_body + trailing
    return _replace_document_body(full_yaml, start, end, replacement)


def insert_block_in_yaml(
    full_yaml: str, new_block_yaml: str, insert_after_id: Optional[str] = None
) -> str:
    """Insert one new document without serializing any existing document."""
    edited_body = new_block_yaml.strip("\r\n")
    if not edited_body:
        raise ValueError("block_yaml must be a non-empty YAML string")
    try:
        inserted_value = yaml.safe_load(edited_body)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(inserted_value, dict):
        raise ValueError("block_yaml must contain exactly one YAML mapping block")
    inserted_id = str(inserted_value.get("id") or "").strip()
    if inserted_id:
        existing_ids = {
            str(block.get("id") or "").strip()
            for block in parse_interview_yaml(full_yaml)["blocks"]
        }
        if inserted_id in existing_ids:
            raise ValueError(f"Block id {inserted_id!r} already exists")

    newline = (
        "\r\n"
        if "\r\n" in full_yaml and "\n" not in full_yaml.replace("\r\n", "")
        else "\n"
    )
    document = edited_body + newline
    if not full_yaml:
        return document
    separator = "---" + newline
    if not insert_after_id:
        if full_yaml.startswith("%"):
            raise ValueError(
                "Top insertion is not safe when the YAML stream begins with directives"
            )
        return document + separator + full_yaml

    _block, _start, end, _body = _unique_block_document(full_yaml, insert_after_id)
    prefix = full_yaml[:end]
    line_break = "" if prefix.endswith(("\n", "\r")) else newline
    return prefix + line_break + separator + document + full_yaml[end:]


def delete_block_from_yaml(full_yaml: str, block_id: str) -> str:
    """Delete a single block from a full interview YAML by its id.

    Locates the block matching *block_id* in the parsed output, then
    rebuilds the YAML without it.
    """
    _block, start, end, _body = _unique_block_document(full_yaml, block_id)
    bodies = _source_document_bodies(full_yaml)
    body_index = next(i for i, item in enumerate(bodies) if item[0] == start)
    if body_index > 0:
        # Remove the separator immediately before the deleted body too.
        start = bodies[body_index - 1][1]
    elif len(bodies) > 1:
        # The first document has no preceding separator, so consume the next.
        end = bodies[1][0]
    return _replace_document_body(full_yaml, start, end, "")


def _comment_yaml_block(block_yaml: str) -> str:
    commented_lines = []
    for line in block_yaml.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        commented_lines.append((f"# {content}" if content else "#") + ending)
    return "".join(commented_lines)


def comment_out_block_in_yaml(full_yaml: str, block_id: str) -> str:
    """Comment out a single block in a full interview YAML by its id."""
    _block, start, end, body = _unique_block_document(full_yaml, block_id)
    return _replace_document_body(full_yaml, start, end, _comment_yaml_block(body))


def enable_commented_block_in_yaml(full_yaml: str, block_id: str) -> str:
    """Restore a previously commented-out block in a full interview YAML."""
    block, start, end, body = _unique_block_document(full_yaml, block_id)
    if block.get("type") != BLOCK_TYPE_COMMENTED:
        raise ValueError(f"Block with id {block_id!r} is not commented out")
    uncommented = _uncomment_yaml_block(body)
    return _replace_document_body(full_yaml, start, end, uncommented)


def reorder_blocks_in_yaml(full_yaml: str, block_ids: List[str]) -> str:
    """Reorder blocks in a full interview YAML to match the given block_ids order.

    Locates each block matching the ids in *block_ids*, then rebuilds the YAML
    in the specified order.
    """
    blocks = parse_interview_yaml(full_yaml)["blocks"]
    existing_ids = [str(block["id"]) for block in blocks]
    if len(set(existing_ids)) != len(existing_ids):
        raise ValueError("Cannot reorder while duplicate block IDs exist")
    if len(set(block_ids)) != len(block_ids):
        raise ValueError("block_ids must not contain duplicates")
    if set(block_ids) != set(existing_ids) or len(block_ids) != len(existing_ids):
        raise ValueError("block_ids must contain every interview block exactly once")
    bodies = _source_document_bodies(full_yaml)
    block_map = {str(block["id"]): block for block in blocks}
    destination_indexes = sorted(int(block["index"]) for block in blocks)
    replacements = {
        destination_index: bodies[int(block_map[block_id]["index"])][2]
        for destination_index, block_id in zip(destination_indexes, block_ids)
    }
    updated = full_yaml
    for destination_index in reversed(destination_indexes):
        start, end, _body = bodies[destination_index]
        updated = updated[:start] + replacements[destination_index] + updated[end:]
    return updated


# ---------------------------------------------------------------------------
# Order-builder: structured steps <-> Python code
# ---------------------------------------------------------------------------

STEP_SCREEN = "screen"
STEP_GATHER = "gather"
STEP_SECTION = "section"
STEP_PROGRESS = "progress"
STEP_FUNCTION = "function"
STEP_CONDITION = "condition"
STEP_RAW = "raw"

# Patterns for parsing order code lines
_RE_SET_PARTS = re.compile(r"""set_parts\(\s*subtitle\s*=\s*['"](.+?)['"]\s*\)""")
_RE_NAV_SET_SECTION = re.compile(r"""nav\.set_section\(\s*['"](.+?)['"]\s*\)""")
_RE_SET_PROGRESS = re.compile(r"set_progress\(\s*(\d+)\s*\)")
_RE_GATHER = re.compile(r"(\S+)\.gather\(\)")
_RE_FUNCTION_CALL = re.compile(r"(\S+\(.*\))")
_RE_IF = re.compile(r"if\s+(.+):$")
_RE_ELIF = re.compile(r"elif\s+(.+):$")
_RE_ELSE = re.compile(r"else:$")


def _join_continuation_lines(lines: list) -> list:
    """Collapse implicit multi-line expressions (open brackets) into single lines.

    Python allows implicit continuation inside ``()``, ``[]``, and ``{}``.  This
    helper joins those so the order-step parser treats them as one step.
    """
    result: list = []
    depth = 0
    accumulator: list = []

    for line in lines:
        stripped = line.strip()
        if depth == 0 and not accumulator:
            accumulator.append(line)
            for ch in stripped:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth = max(depth - 1, 0)
            if depth == 0:
                result.append(accumulator[0])
                accumulator = []
        else:
            if accumulator:
                accumulator.append(stripped)
            for ch in stripped:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth = max(depth - 1, 0)
            if depth == 0:
                joined = accumulator[0].rstrip() + " " + " ".join(accumulator[1:])
                result.append(joined)
                accumulator = []

    if accumulator:
        result.append(accumulator[0].rstrip() + " " + " ".join(accumulator[1:]))

    return result


def parse_order_code(code: str) -> List[Dict[str, Any]]:
    """Parse a mandatory code block's body into structured order steps.

    Recognises:
        set_parts(subtitle='...') → section step
        set_progress(N) → progress step
        X.gather() → gather step
        simple_variable → screen step
        function_call(...) → function step
        anything else → raw step

    Multi-line expressions joined by open brackets are treated as a single step.
    """
    raw_lines = _join_continuation_lines(code.splitlines())

    def _line_indent(raw_line: str) -> int:
        return len(raw_line) - len(raw_line.lstrip(" "))

    def _next_child_indent(start_index: int, parent_indent: int) -> int:
        for candidate in raw_lines[start_index:]:
            stripped = candidate.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = _line_indent(candidate)
            if indent > parent_indent:
                return indent
            break
        return parent_indent + 2

    def _parse_line(stripped_line: str, step_id: str) -> Dict[str, Any]:
        m = _RE_SET_PARTS.search(stripped_line)
        if m:
            return {
                "id": step_id,
                "kind": STEP_SECTION,
                "label": "Start section",
                "summary": f"Set section to {m.group(1)}",
                "value": m.group(1),
            }

        m = _RE_NAV_SET_SECTION.search(stripped_line)
        if m:
            return {
                "id": step_id,
                "kind": STEP_SECTION,
                "label": "Start section",
                "summary": f"Set section to {m.group(1)}",
                "value": m.group(1),
            }

        m = _RE_SET_PROGRESS.search(stripped_line)
        if m:
            return {
                "id": step_id,
                "kind": STEP_PROGRESS,
                "label": "Progress",
                "summary": f"Set progress to {m.group(1)}%",
                "value": m.group(1),
            }

        m = _RE_GATHER.search(stripped_line)
        if m:
            return {
                "id": step_id,
                "kind": STEP_GATHER,
                "label": "List gather",
                "summary": f"Gather {m.group(1)} list",
                "invoke": stripped_line,
            }

        if "(" in stripped_line and ")" in stripped_line:
            return {
                "id": step_id,
                "kind": STEP_FUNCTION,
                "label": "Function",
                "summary": stripped_line,
                "invoke": stripped_line,
            }

        if re.match(r"^[A-Za-z_][\w.\[\]]*$", stripped_line):
            return {
                "id": step_id,
                "kind": STEP_SCREEN,
                "label": "Screen",
                "summary": stripped_line,
                "invoke": stripped_line,
            }

        return {
            "id": step_id,
            "kind": STEP_RAW,
            "label": "Raw Python",
            "summary": stripped_line[:80],
            "code": stripped_line,
        }

    def _parse_block(
        start_index: int,
        base_indent: int,
        step_counter: int,
        stop_on_else_indent: int | None = None,
    ):
        steps: List[Dict[str, Any]] = []
        index = start_index

        while index < len(raw_lines):
            raw_line = raw_lines[index]
            stripped_line = raw_line.strip()
            if not stripped_line or stripped_line.startswith("#"):
                index += 1
                continue

            indent = _line_indent(raw_line)
            if indent < base_indent:
                break

            if (
                stop_on_else_indent is not None
                and indent == stop_on_else_indent
                and (_RE_ELSE.match(stripped_line) or _RE_ELIF.match(stripped_line))
            ):
                break

            if indent > base_indent:
                step_counter += 1
                steps.append(
                    {
                        "id": f"step-{step_counter}",
                        "kind": STEP_RAW,
                        "label": "Raw Python",
                        "summary": stripped_line[:80],
                        "code": stripped_line,
                    }
                )
                index += 1
                continue

            step_counter += 1
            step_id = f"step-{step_counter}"

            m = _RE_IF.match(stripped_line)
            if m:
                child_indent = _next_child_indent(index + 1, indent)
                children, next_index, step_counter = _parse_block(
                    index + 1, child_indent, step_counter, stop_on_else_indent=indent
                )
                (
                    has_else,
                    else_children,
                    next_index,
                    step_counter,
                ) = _parse_conditional_tail(next_index, indent, step_counter)
                steps.append(
                    {
                        "id": step_id,
                        "kind": STEP_CONDITION,
                        "label": "Condition",
                        "summary": m.group(1),
                        "condition": m.group(1),
                        "children": children,
                        "has_else": has_else,
                        "else_children": else_children,
                    }
                )
                index = next_index
                continue

            steps.append(_parse_line(stripped_line, step_id))
            index += 1

        return steps, index, step_counter

    def _parse_conditional_tail(
        index: int, indent: int, step_counter: int
    ) -> Tuple[bool, List[Dict[str, Any]], int, int]:
        """Parse the ``elif``/``else`` tail of an ``if`` block at ``indent``.

        ``elif`` is represented as an ``else`` branch holding a single nested
        condition step, which is what it means in Python.  Keeping it in the
        existing shape means a chain of any length round-trips through
        :func:`serialize_order_steps` and renders in the order builder without
        a separate step kind for it.  Before this, an ``elif`` was not
        recognised at all: it became a raw step and its body became *sibling*
        steps, so saving the order block silently moved those screens out of
        the branch and ran them unconditionally.
        """
        if index >= len(raw_lines):
            return False, [], index, step_counter

        line = raw_lines[index]
        if _line_indent(line) != indent:
            return False, [], index, step_counter
        stripped = line.strip()

        elif_match = _RE_ELIF.match(stripped)
        if elif_match:
            step_counter += 1
            step_id = f"step-{step_counter}"
            child_indent = _next_child_indent(index + 1, indent)
            children, next_index, step_counter = _parse_block(
                index + 1, child_indent, step_counter, stop_on_else_indent=indent
            )
            (
                nested_has_else,
                nested_else_children,
                next_index,
                step_counter,
            ) = _parse_conditional_tail(next_index, indent, step_counter)
            nested_step = {
                "id": step_id,
                "kind": STEP_CONDITION,
                "label": "Condition",
                "summary": elif_match.group(1),
                "condition": elif_match.group(1),
                "children": children,
                "has_else": nested_has_else,
                "else_children": nested_else_children,
            }
            return True, [nested_step], next_index, step_counter

        if _RE_ELSE.match(stripped):
            else_child_indent = _next_child_indent(index + 1, indent)
            else_children, next_index, step_counter = _parse_block(
                index + 1, else_child_indent, step_counter
            )
            return True, else_children, next_index, step_counter

        return False, [], index, step_counter

    parsed_steps, _next_index, _final_counter = _parse_block(0, 0, 0)
    return parsed_steps


def serialize_order_steps(steps: Sequence[Dict[str, Any]]) -> str:
    """Convert structured order steps back into Python code for a mandatory
    code block."""
    lines: List[str] = []

    def _append_condition(step: Dict[str, Any], indent: int, keyword: str) -> None:
        """Write one link of an ``if``/``elif``/``else`` chain.

        An ``else`` branch whose only content is a condition is written back as
        ``elif`` rather than as a nested ``if``.  That is the same code either
        way, and it is what :func:`parse_order_code` produces for an ``elif``,
        so a chain survives a parse/serialize round trip unchanged.
        """
        prefix = " " * indent
        condition = str(step.get("condition") or step.get("summary") or "True")
        lines.append(f"{prefix}{keyword} {condition}:")
        children = step.get("children") or []
        if children:
            _append_steps(children, indent + 2)
        else:
            lines.append(f"{' ' * (indent + 2)}pass")

        if not step.get("has_else"):
            return

        else_children = step.get("else_children") or []
        if (
            len(else_children) == 1
            and isinstance(else_children[0], dict)
            and else_children[0].get("kind") == STEP_CONDITION
        ):
            _append_condition(else_children[0], indent, "elif")
            return

        lines.append(f"{prefix}else:")
        if else_children:
            _append_steps(else_children, indent + 2)
        else:
            lines.append(f"{' ' * (indent + 2)}pass")

    def _append_steps(step_list: Sequence[Dict[str, Any]], indent: int) -> None:
        prefix = " " * indent
        for step in step_list:
            kind = step.get("kind", STEP_RAW)
            if kind == STEP_SECTION:
                value = step.get("value", "")
                lines.append(f"{prefix}nav.set_section('{value}')")
            elif kind == STEP_PROGRESS:
                value = step.get("value", "0")
                lines.append(f"{prefix}set_progress({value})")
            elif kind == STEP_GATHER:
                lines.append(f"{prefix}{step.get('invoke', '')}")
            elif kind == STEP_SCREEN:
                lines.append(f"{prefix}{step.get('invoke', '')}")
            elif kind == STEP_FUNCTION:
                lines.append(f"{prefix}{step.get('invoke', '')}")
            elif kind == STEP_CONDITION:
                _append_condition(step, indent, "if")
            elif kind == STEP_RAW:
                code = step.get("code", "")
                for raw_line in str(code).splitlines() or [""]:
                    lines.append(f"{prefix}{raw_line}")

    _append_steps(steps, 0)
    return "\n".join(lines)


def generate_draft_order(blocks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Produce a draft interview order from a list of parsed blocks.

    Uses heuristics to build a sensible initial ordering:
        - Skip metadata/includes/default screen parts
        - Place question blocks as screen steps
        - Detect gather patterns
        - Guess sections from block titles
        - Place progress markers at intervals
    """
    question_blocks = [
        b
        for b in blocks
        if b["type"] in (BLOCK_TYPE_QUESTION, BLOCK_TYPE_CODE)
        and not b.get("data", {}).get("mandatory")
    ]

    if not question_blocks:
        return []

    steps: List[Dict[str, Any]] = []
    step_counter = 0
    total = len(question_blocks)

    for i, block in enumerate(question_blocks):
        step_counter += 1

        # Insert progress at start, ~33%, ~66%, and end
        if total > 3:
            pct_position = i / total
            nearest_quarter = round(pct_position * 4) / 4
            if i == 0 or (i > 0 and round((i - 1) / total * 4) / 4 != nearest_quarter):
                progress_val = int(nearest_quarter * 100)
                if progress_val > 0:
                    steps.append(
                        {
                            "id": f"step-{step_counter}",
                            "kind": STEP_PROGRESS,
                            "label": "Progress",
                            "summary": f"Set progress to {progress_val}%",
                            "value": str(progress_val),
                        }
                    )
                    step_counter += 1

        variable = block.get("variable")
        tags = block.get("tags", [])

        if "gather" in tags and variable:
            steps.append(
                {
                    "id": f"step-{step_counter}",
                    "kind": STEP_GATHER,
                    "label": "List gather",
                    "summary": f"Gather {variable.split('.')[0]} list",
                    "invoke": variable,
                }
            )
        elif variable:
            steps.append(
                {
                    "id": f"step-{step_counter}",
                    "kind": STEP_SCREEN,
                    "label": "Screen",
                    "summary": f"Ask {block['title']}",
                    "invoke": variable,
                    "blockId": block["id"],
                }
            )
        else:
            steps.append(
                {
                    "id": f"step-{step_counter}",
                    "kind": STEP_RAW,
                    "label": "Raw Python",
                    "summary": block["title"],
                    "code": f"# TODO: {block['title']}",
                }
            )

    # Final progress
    if steps:
        step_counter += 1
        steps.append(
            {
                "id": f"step-{step_counter}",
                "kind": STEP_PROGRESS,
                "label": "Progress",
                "summary": "Set progress to 100%",
                "value": "100",
            }
        )

    return steps


# ---------------------------------------------------------------------------
# Playground helpers
# ---------------------------------------------------------------------------


def _playground_user_context(user_id: int):
    """Temporarily set the docassemble thread user context.

    Follows the same pattern used in ALDashboard.
    """
    import docassemble.base.functions

    original_info = copy.deepcopy(
        getattr(docassemble.base.functions.this_thread, "current_info", {}) or {}
    )
    current_info = copy.deepcopy(original_info)
    current_info.setdefault("user", {})
    current_info["user"].update({"is_anonymous": False, "theid": user_id})
    docassemble.base.functions.this_thread.current_info = current_info

    class _Context:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            docassemble.base.functions.this_thread.current_info = original_info

    return _Context()


def playground_list_projects(user_id: int) -> List[str]:
    """Return sorted list of playground project names."""
    playground = create_saved_file(user_id, fix=False, section="playground")
    projects = playground.list_of_dirs() or []
    projects = [p for p in projects if isinstance(p, str) and p.strip()]
    if "default" not in projects:
        projects.append("default")
    return sorted(set(projects))


def playground_list_yaml_files(user_id: int, project: str) -> List[Dict[str, str]]:
    """List YAML interview files in a playground project."""
    with _playground_user_context(user_id):
        pg = create_playground(project=project)
        return [
            {"filename": fn, "label": fn}
            for fn in pg.file_list
            if isinstance(fn, str) and fn.lower().endswith((".yml", ".yaml"))
        ]


def playground_read_yaml(user_id: int, project: str, filename: str) -> str:
    """Read a YAML file from the playground, returning its text content."""
    with _playground_user_context(user_id):
        pg = create_playground(project=project)
        if filename not in pg.file_list:
            raise FileNotFoundError(
                f"File {filename!r} not found in project {project!r}"
            )
        content = pg.read_file(filename)
    return content or ""


def playground_write_yaml(
    user_id: int, project: str, filename: str, content: str
) -> None:
    """Write YAML content to a playground file."""
    with _playground_user_context(user_id):
        pg = create_playground(project=project)
        pg.write_file(filename, content)


def _al_individual_primitive_groups(model: Dict[str, Any]) -> Dict[str, List[str]]:
    """Return index-aware ALIndividual receivers found in parsed blocks."""

    individual_objects: set[str] = set()
    people_lists: set[str] = set()
    field_method_names = {
        "name_fields",
        "address_fields",
        "gender_fields",
        "pronoun_fields",
        "language_fields",
    }
    # ALIndividual.contact_fields() is presently a pass/None stub, so it is
    # not a usable dynamic field-list helper yet.
    method_pattern = re.compile(
        r"(?P<receiver>[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]\n]+\]|\.[A-Za-z_][A-Za-z0-9_]*)*)"
        r"\.(?:" + "|".join(sorted(field_method_names)) + r")\s*\("
    )
    for block in model.get("blocks", []):
        data = block.get("data", {}) or {}
        objects = data.get("objects")
        if isinstance(objects, list):
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                for name, cls_value in obj.items():
                    object_name = str(name or "").strip()
                    class_name = str(cls_value or "").strip().split(".using(", 1)[0]
                    class_basename = class_name.rsplit(".", 1)[-1]
                    if not object_name:
                        continue
                    if class_basename == "ALPeopleList":
                        people_lists.add(f"{object_name}[i]")
                    elif class_basename == "ALIndividual":
                        individual_objects.add(object_name)

        generic_class = str(data.get("generic object") or "").strip().rsplit(".", 1)[-1]
        if generic_class == "ALPeopleList":
            people_lists.add("x[i]")
        elif generic_class == "ALIndividual":
            individual_objects.add("x")

        fields = data.get("fields")
        if isinstance(fields, list):
            for field in fields:
                if not isinstance(field, dict):
                    continue
                code_value = field.get("code")
                if not isinstance(code_value, str):
                    continue
                for match in method_pattern.finditer(code_value):
                    receiver = match.group("receiver").strip()
                    if receiver:
                        individual_objects.add(receiver)

    result: Dict[str, List[str]] = {}
    if individual_objects:
        result["al_individual_objects"] = sorted(individual_objects)
    if people_lists:
        result["al_people_lists"] = sorted(people_lists)
    combined = sorted(individual_objects | people_lists)
    if combined:
        result["al_individual_primitives"] = combined
    return result


def playground_get_variables(
    user_id: int, project: str, filename: str
) -> Dict[str, Any]:
    """Extract variable names from a playground YAML file."""
    with _playground_user_context(user_id):
        pg = create_playground(project=project)
        if filename not in pg.file_list:
            raise FileNotFoundError(
                f"File {filename!r} not found in project {project!r}"
            )
        variable_info = pg.variables_from_file(filename)

    if not isinstance(variable_info, dict):
        variable_info = {}

    all_names = sorted(
        str(name).strip()
        for name in (variable_info.get("all_names_reduced") or [])
        if str(name).strip()
    )
    top_level = sorted(
        {name.split(".", 1)[0].split("[", 1)[0] for name in all_names if name}
    )
    symbol_groups: Dict[str, List[str]] = {}
    yaml_files: List[str] = []
    for key, value in variable_info.items():
        if key == "all_names_reduced":
            continue
        if isinstance(value, list):
            cleaned = sorted(
                {
                    str(item).strip()
                    for item in value
                    if isinstance(item, (str, int, float)) and str(item).strip()
                }
            )
            if cleaned:
                symbol_groups[str(key)] = cleaned

    try:
        with _playground_user_context(user_id):
            pg = create_playground(project=project)
            yaml_files = sorted(
                {
                    str(file_name).strip()
                    for file_name in pg.file_list
                    if isinstance(file_name, str)
                    and str(file_name).strip().lower().endswith((".yml", ".yaml"))
                }
            )
    except Exception:
        yaml_files = []
    if yaml_files:
        symbol_groups["yaml_files"] = yaml_files

    # Derive classes and functions directly from parsed interview blocks to
    # provide role-specific suggestions (objects class picker, function picker).
    classes: set[str] = set()
    functions: set[str] = set()
    try:
        yaml_text = playground_read_yaml(user_id, project, filename)
        model = parse_interview_yaml(yaml_text)
        for block in model.get("blocks", []):
            data = block.get("data", {}) or {}
            objects = data.get("objects")
            if isinstance(objects, list):
                for obj in objects:
                    if not isinstance(obj, dict):
                        continue
                    for _name, cls_value in obj.items():
                        cls_text = str(cls_value or "").strip()
                        if not cls_text:
                            continue
                        base_cls = cls_text.split(".using(", 1)[0].strip()
                        if re.match(r"^[A-Za-z_][A-Za-z0-9_\.]*$", base_cls):
                            classes.add(base_cls)

            code_text = str(data.get("code") or "")
            if code_text:
                for match in re.finditer(
                    r"(?m)^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", code_text
                ):
                    fn = match.group(1).strip()
                    if fn:
                        functions.add(fn)
    except Exception:
        classes = set()
        functions = set()

    if classes:
        symbol_groups["classes"] = sorted(classes)
    if functions:
        symbol_groups["functions"] = sorted(functions)

    # Field-list helpers such as ``name_fields()`` need an ALIndividual
    # receiver, not an arbitrary interview variable.  Keep that richer type
    # information alongside the ordinary AST/name catalog so the graphical
    # editor can offer useful, index-aware suggestions.  Object declarations
    # are authoritative: an ALPeopleList is addressed through ``[i]`` while a
    # single ALIndividual is not.  Existing helper calls are also retained so
    # interviews that get their objects from an included file still round-trip
    # cleanly.
    try:
        symbol_groups.update(_al_individual_primitive_groups(model))
    except Exception:
        pass

    # Include files from the project's templates folder to power template pickers.
    template_files: List[str] = []
    try:
        template_area = create_saved_file(
            user_id, fix=False, section="playgroundtemplate"
        )
        template_project_dir = os.path.join(template_area.directory, project)
        if os.path.isdir(template_project_dir):
            template_files = sorted(
                file_name
                for file_name in os.listdir(template_project_dir)
                if os.path.isfile(os.path.join(template_project_dir, file_name))
            )
    except Exception:
        template_files = []
    if template_files:
        symbol_groups["template_files"] = template_files

    # Include static file names from the project's static folder.
    image_exts = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".bmp",
        ".tif",
        ".tiff",
    }
    static_files: List[str] = []
    static_images: List[str] = []
    try:
        static_area = create_saved_file(user_id, fix=False, section="playgroundstatic")
        static_project_dir = os.path.join(static_area.directory, project)
        if os.path.isdir(static_project_dir):
            static_files = sorted(
                file_name
                for file_name in os.listdir(static_project_dir)
                if os.path.isfile(os.path.join(static_project_dir, file_name))
            )
            static_images = [
                file_name
                for file_name in static_files
                if os.path.splitext(file_name.lower())[1] in image_exts
            ]
    except Exception:
        static_files = []
        static_images = []
    if static_files:
        symbol_groups["static_files"] = static_files
    if static_images:
        symbol_groups["static_images"] = static_images

    return {
        "project": project,
        "filename": filename,
        "all_names": all_names,
        "top_level_names": top_level,
        "classes": sorted(classes),
        "functions": sorted(functions),
        "yaml_files": yaml_files,
        "template_files": template_files,
        "static_files": static_files,
        "symbol_groups": symbol_groups,
    }


def playground_interview_url(user_id: int, project: str, filename: str) -> str:
    """Build a preview URL for a playground interview."""
    import docassemble.base.functions

    project_suffix = "" if project == "default" else project
    package = f"docassemble.playground{user_id}{project_suffix}"
    return docassemble.base.functions.url_of(
        "interview", i=f"{package}:{filename}", reset=1, cache=0
    )

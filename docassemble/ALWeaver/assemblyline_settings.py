"""Round-trip helpers for graphical AssemblyLine interview settings.

AssemblyLine has two distinct setting families: publishing metadata stored in a
``metadata`` document, and exact-name Python variables normally defined in
``code`` blocks.  This module keeps that distinction explicit and writes the
latter to one Weaver-owned block so the graphical editor never has to guess
which arbitrary author code it is allowed to replace.
"""

from __future__ import annotations

import ast
import copy
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml

MANAGED_BLOCK_ID = "alweaver assemblyline settings"
DOCS_URL = (
    "https://assemblyline.suffolklitlab.org/docs/components/AssemblyLine/"
    "magic_variables/"
)


def _field(
    key: str,
    label: str,
    kind: str = "text",
    default: Any = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    result = {"key": key, "label": label, "kind": kind, "default": default}
    result.update(kwargs)
    return result


SETTINGS_SCHEMA: List[Dict[str, Any]] = [
    {
        "id": "identity",
        "label": "Form identity and publishing",
        "fields": [
            _field("title", "Title", scope="metadata", pair="title"),
            _field("short title", "Short title", scope="metadata", pair="title"),
            _field("description", "Description", "area", scope="metadata"),
            _field(
                "can_I_use_this_form",
                "Who can use this form?",
                "area",
                scope="metadata",
            ),
            _field("before_you_start", "Before you start", "area", scope="metadata"),
            _field(
                "when_you_are_finished",
                "When you are finished",
                "area",
                scope="metadata",
            ),
            _field(
                "landing_page_url", "Public landing page URL", "url", scope="metadata"
            ),
            _field("authors", "Authors", "list", [], scope="metadata"),
            _field("LIST_topics", "LIST topics", "list", [], scope="metadata"),
            _field("original_form", "Original form URLs", "list", [], scope="metadata"),
            _field("jurisdiction", "Jurisdiction code", scope="metadata"),
            _field("allowed_courts", "Allowed courts", "list", [], scope="both"),
            _field(
                "typical_role",
                "Typical user role",
                "choice",
                "unknown",
                scope="metadata",
                choices=["plaintiff", "defendant", "unknown", "na"],
            ),
            _field(
                "efiling_enabled",
                "E-filing enabled",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "integrated_efiling",
                "Integrated e-filing",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "integrated_email_filing",
                "Integrated email filing",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "requires_notarization",
                "Requires notarization",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "unlisted",
                "Keep interview unlisted",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "estimated_completion_minutes",
                "Estimated completion minutes",
                "integer",
                10,
                scope="metadata",
                pair="timing",
            ),
            _field(
                "estimated_completion_delta",
                "Estimate plus or minus",
                "integer",
                5,
                scope="metadata",
                pair="timing",
            ),
        ],
    },
    {
        "id": "organization",
        "label": "Organization and locale",
        "fields": [
            _field("AL_ORGANIZATION_TITLE", "Organization title"),
            _field("AL_ORGANIZATION_HOMEPAGE", "Organization homepage", "url"),
            _field(
                "AL_DEFAULT_COUNTRY", "Default country", default="US", pair="locale"
            ),
            _field("AL_DEFAULT_STATE", "Default state or province", pair="locale"),
            _field("AL_DEFAULT_LANGUAGE", "Default document language", default="en"),
            _field(
                "AL_DEFAULT_OVERFLOW_MESSAGE", "PDF overflow message", default="..."
            ),
        ],
    },
    {
        "id": "interview",
        "label": "Interview behavior",
        "fields": [
            _field(
                "al_form_type",
                "Form type",
                "choice",
                "other",
                choices=[
                    "starts_case",
                    "existing_case",
                    "appeal",
                    "other_form",
                    "letter",
                    "other",
                ],
            ),
            _field(
                "user_ask_role",
                "User role",
                "choice",
                "unknown",
                choices=["plaintiff", "defendant", "unknown"],
            ),
            _field(
                "al_person_answering",
                "Person answering",
                "choice",
                "user",
                choices=["user", "attorney", "advocate", "other"],
            ),
            _field(
                "al_form_requires_digital_signature",
                "Require a digital signature",
                "boolean",
                False,
            ),
            _field(
                "al_typed_signature_prefix", "Typed-signature prefix", default="/s/"
            ),
            _field("al_typed_signature_font", "Typed-signature font"),
            _field("speak_text", "Enable read-aloud control", "boolean", True),
        ],
    },
    {
        "id": "language",
        "label": "Languages",
        "fields": [
            _field(
                "enable_al_language",
                "Enable AssemblyLine language switching",
                "boolean",
                True,
            ),
            _field("al_user_default_language", "Default user language", default="en"),
            _field("al_interview_languages", "Supported languages", "list", ["en"]),
        ],
    },
    {
        "id": "repository",
        "label": "Repository and feedback",
        "fields": [
            _field("github_repo_name", "GitHub repository name", pair="github"),
            _field("github_user", "GitHub owner", pair="github"),
        ],
    },
    {
        "id": "next_steps",
        "label": "Next steps document",
        "fields": [
            _field("al_next_steps_enabled", "Include next steps", "boolean", True),
            _field(
                "al_next_steps_document_title",
                "Document name",
                default="form",
                pair="document_names",
            ),
            _field(
                "al_next_steps_document_purpose",
                "Request name",
                default="request",
                pair="document_names",
            ),
            _field("al_next_steps_help_organization", "Help organization", pair="help"),
            _field("al_next_steps_help_url", "Help URL", "url", pair="help"),
            _field("al_next_steps_generate_qr_code", "Add a QR code", "boolean", False),
            _field("al_next_steps_what_happens_next", "What happens next", "area"),
            _field(
                "al_next_steps_what_can_decision_maker_do",
                "What the decision maker can do",
                "area",
            ),
            _field(
                "al_next_steps_what_happens_if_i_win",
                "What happens if the request is granted",
                "area",
            ),
        ],
    },
    {
        "id": "advanced",
        "label": "Advanced and derived variables",
        "readonly": True,
        "notes": [
            "al_logo is an object backed by a file; edit it in Objects and Static files.",
            "addresses_to_search is executable court-routing logic; edit its code block directly.",
            "al_intro_screen is an interview-order event, not metadata.",
            "al_user_bundle, al_court_bundle, signature_fields, and trial_court are runtime structure.",
            "user_role and user_started_case are derived from al_form_type and user_ask_role.",
            "users and other_parties are AssemblyLine objects and should be edited in the object/screen tools.",
            "al_menu_items_custom_items may contain dynamic code; edit its data block directly.",
            "Server-wide AssemblyLine configuration is intentionally not editable here.",
        ],
        "fields": [],
    },
]


CODE_FIELDS = {
    field["key"]: field
    for section in SETTINGS_SCHEMA
    for field in section.get("fields", [])
    if field.get("scope") in {None, "both"}
}
METADATA_FIELDS = {
    field["key"]: field
    for section in SETTINGS_SCHEMA
    for field in section.get("fields", [])
    if field.get("scope") in {"metadata", "both"}
}


_SEPARATOR_RE = re.compile(r"(?m)^---[ \t]*(?:\r?\n|$)")


def _documents(source: str) -> List[Tuple[int, int, str]]:
    result: List[Tuple[int, int, str]] = []
    start = 0
    for match in _SEPARATOR_RE.finditer(source):
        result.append((start, match.start(), source[start : match.start()]))
        start = match.end()
    result.append((start, len(source), source[start:]))
    return result


def _literal_assignments(code: str) -> Dict[str, Any]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    result: Dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value_node = node.value
        if value_node is None:
            continue
        try:
            value = ast.literal_eval(value_node)
        except (ValueError, TypeError):
            value = ast.get_source_segment(code, value_node) or ""
        for target in targets:
            if isinstance(target, ast.Name) and target.id in CODE_FIELDS:
                result[target.id] = value
    return result


def _metadata(source: str) -> Tuple[Dict[str, Any], Optional[Tuple[int, int, str]]]:
    for start, end, body in _documents(source):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("metadata"), dict):
            return dict(parsed["metadata"]), (start, end, body)
    return {}, None


def read_settings(source: str) -> Dict[str, Any]:
    """Read metadata and supported literal assignments from an interview."""
    values: Dict[str, Any] = {
        key: copy.deepcopy(field.get("default"))
        for key, field in {**METADATA_FIELDS, **CODE_FIELDS}.items()
    }
    metadata, _location = _metadata(source)
    for key in METADATA_FIELDS:
        if key in metadata:
            values[key] = metadata[key]

    sources: Dict[str, str] = {}
    for _start, _end, body in _documents(source):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if not isinstance(parsed, dict) or not isinstance(parsed.get("code"), str):
            continue
        assignments = _literal_assignments(parsed["code"])
        block_id = str(parsed.get("id") or "code block")
        for key, value in assignments.items():
            values[key] = value
            sources[key] = block_id

    return {
        "schema": copy.deepcopy(SETTINGS_SCHEMA),
        "values": values,
        "sources": sources,
        "docs_url": DOCS_URL,
    }


def _coerce_value(field: Mapping[str, Any], value: Any) -> Any:
    kind = field.get("kind")
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{field['label']} must be true or false")
    elif kind == "integer":
        if value is None or (isinstance(value, str) and not value.strip()):
            return ""
        if isinstance(value, bool):
            raise ValueError(f"{field['label']} must be an integer")
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field['label']} must be an integer") from exc
    elif kind == "list":
        if isinstance(value, str):
            value = [line.strip() for line in value.splitlines() if line.strip()]
        if not isinstance(value, list):
            raise ValueError(f"{field['label']} must be a list")
    elif kind == "choice":
        value = str(value or "")
        if value not in field.get("choices", []):
            raise ValueError(f"{field['label']} has an unsupported value")
    else:
        value = str(value or "")
    return value


def _managed_block(values: Mapping[str, Any]) -> str:
    lines = [
        f"id: {MANAGED_BLOCK_ID}",
        "initial: True",
        "code: |",
        "  # Managed by the graphical AssemblyLine settings editor.",
    ]
    for key in CODE_FIELDS:
        if key not in values:
            continue
        value = values[key]
        if CODE_FIELDS[key].get("kind") == "python":
            rendered = str(value or "None")
            try:
                ast.parse(rendered, mode="eval")
            except SyntaxError as exc:
                raise ValueError(
                    f"{CODE_FIELDS[key]['label']} is not valid Python"
                ) from exc
        else:
            rendered = repr(value)
        lines.append(f"  {key} = {rendered}")
    return "\n".join(lines) + "\n"


def _replace_or_insert_managed(source: str, block: str) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"
    block = block.replace("\n", newline)
    for start, end, body in _documents(source):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and parsed.get("id") == MANAGED_BLOCK_ID:
            leading = body[: len(body) - len(body.lstrip("\r\n"))]
            trailing = body[len(body.rstrip("\r\n")) :]
            return (
                source[:start]
                + leading
                + block.rstrip("\r\n")
                + trailing
                + source[end:]
            )

    # Put initial settings before the first mandatory block. Existing document
    # bytes are otherwise untouched.
    insertion = None
    for start, _end, body in _documents(source):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and parsed.get("mandatory") is True:
            insertion = start
            break
    document = block.rstrip("\r\n") + newline + "---" + newline
    if insertion is None:
        prefix = source
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += newline
        if prefix:
            prefix += "---" + newline
        return prefix + block
    return source[:insertion] + document + source[insertion:]


def _yaml_scalar(value: Any) -> str:
    """Serialize one scalar without PyYAML's document-end marker."""
    rendered = yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=True,
        width=10_000,
    ).strip()
    if rendered.endswith("\n..."):
        rendered = rendered[:-4]
    elif rendered == "...":
        rendered = "''"
    return rendered


def _literal_block_value(
    value: str,
    *,
    content_indent: int,
    newline: str,
    original_fragment: str = "",
) -> str:
    """Render text as a literal block, retaining an existing chomping marker."""
    header_match = re.match(r"^([|>][1-9]?[+-]?)", original_fragment)
    if header_match:
        header = header_match.group(1).replace(">", "|", 1)
    else:
        header = "|" if value.endswith(("\n", "\r")) else "|-"
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not normalized:
        return header
    indentation = " " * content_indent
    return (
        header
        + newline
        + newline.join(
            indentation + line if line else "" for line in normalized.split("\n")
        )
    )


def _metadata_value_fragment(
    value: Any,
    *,
    value_node: Optional[yaml.Node],
    original_fragment: str,
    key_indent: int,
    newline: str,
) -> str:
    """Serialize one changed value while favoring readable literal text."""
    existing_block = isinstance(value_node, yaml.ScalarNode) and value_node.style in {
        "|",
        ">",
    }
    if isinstance(value, str) and (existing_block or "\n" in value or "\r" in value):
        return _literal_block_value(
            value,
            content_indent=key_indent + 2,
            newline=newline,
            original_fragment=original_fragment,
        )
    if isinstance(value, list):
        if not value:
            return "[]"
        indentation = " " * (key_indent + 2)
        items: List[str] = []
        for item in value:
            if isinstance(item, str) and ("\n" in item or "\r" in item):
                literal = _literal_block_value(
                    item,
                    content_indent=key_indent + 4,
                    newline=newline,
                )
                items.append("- " + literal)
            else:
                items.append("- " + _yaml_scalar(item))
        if isinstance(value_node, yaml.SequenceNode) and not value_node.flow_style:
            return items[0] + "".join(
                newline + indentation + item for item in items[1:]
            )
        return newline + newline.join(indentation + item for item in items)
    return _yaml_scalar(value)


def _metadata_mapping_node(body: str) -> Optional[yaml.MappingNode]:
    try:
        root = yaml.compose(body)
    except yaml.YAMLError:
        return None
    if not isinstance(root, yaml.MappingNode):
        return None
    for key_node, value_node in root.value:
        if (
            isinstance(key_node, yaml.ScalarNode)
            and key_node.value == "metadata"
            and isinstance(value_node, yaml.MappingNode)
        ):
            return value_node
    return None


def _update_metadata(source: str, updates: Mapping[str, Any]) -> str:
    """Patch changed metadata values without re-serializing the document."""
    _metadata_values, location = _metadata(source)
    if location is None:
        raise ValueError("No metadata document was found")
    start, end, body = location
    metadata_node = _metadata_mapping_node(body)
    if metadata_node is None:
        raise ValueError("The metadata mapping could not be edited safely")
    newline = "\r\n" if "\r\n" in body else "\n"
    existing: Dict[str, Tuple[yaml.Node, yaml.Node]] = {}
    for key_node, value_node in metadata_node.value:
        if not isinstance(key_node, yaml.ScalarNode) or key_node.value in existing:
            raise ValueError("The metadata mapping contains unsupported duplicate keys")
        existing[str(key_node.value)] = (key_node, value_node)

    operations: List[Tuple[int, int, str]] = []
    missing: List[Tuple[str, Any]] = []
    for key, value in updates.items():
        if key not in existing:
            missing.append((key, value))
            continue
        key_node, value_node = existing[key]
        value_start = value_node.start_mark.index
        value_end = value_node.end_mark.index
        fragment = body[value_start:value_end]
        replacement = _metadata_value_fragment(
            value,
            value_node=value_node,
            original_fragment=fragment,
            key_indent=key_node.start_mark.column,
            newline=newline,
        )
        if fragment.endswith("\r\n") and not replacement.endswith(("\r", "\n")):
            replacement += "\r\n"
        elif fragment.endswith("\n") and not replacement.endswith(("\r", "\n")):
            replacement += "\n"
        elif fragment.endswith("\r") and not replacement.endswith(("\r", "\n")):
            replacement += "\r"
        operations.append((value_start, value_end, replacement))

    if missing:
        key_indent = (
            metadata_node.value[0][0].start_mark.column
            if metadata_node.value
            else metadata_node.start_mark.column
        )
        insertion_at = len(body.rstrip("\r\n"))
        addition_lines: List[str] = []
        for key, value in missing:
            fragment = _metadata_value_fragment(
                value,
                value_node=None,
                original_fragment="",
                key_indent=key_indent,
                newline=newline,
            )
            separator = "" if fragment.startswith(newline) else " "
            addition_lines.append(" " * key_indent + key + ":" + separator + fragment)
        prefix = (
            ""
            if insertion_at == 0 or body[:insertion_at].endswith(("\n", "\r"))
            else newline
        )
        operations.append(
            (insertion_at, insertion_at, prefix + newline.join(addition_lines))
        )

    updated_body = body
    for operation_start, operation_end, replacement in sorted(
        operations, key=lambda item: item[0], reverse=True
    ):
        updated_body = (
            updated_body[:operation_start] + replacement + updated_body[operation_end:]
        )

    # Refuse a patch that does not round-trip to the submitted values.
    parsed = yaml.safe_load(updated_body)
    parsed_metadata = parsed.get("metadata") if isinstance(parsed, dict) else None
    if not isinstance(parsed_metadata, dict):
        raise ValueError("The metadata mapping could not be edited safely")
    for key, value in updates.items():
        parsed_value = parsed_metadata.get(key)
        if isinstance(value, str) and isinstance(parsed_value, str):
            if parsed_value.rstrip("\r\n") != value.rstrip("\r\n"):
                raise ValueError(f"Metadata value {key!r} did not round-trip safely")
        elif parsed_value != value:
            raise ValueError(f"Metadata value {key!r} did not round-trip safely")
    return source[:start] + updated_body + source[end:]


def update_settings(source: str, submitted: Mapping[str, Any]) -> str:
    """Update supported settings, preserving every unrelated YAML document."""
    if not isinstance(submitted, Mapping):
        raise ValueError("settings must be an object")
    unknown = set(submitted) - set(METADATA_FIELDS) - set(CODE_FIELDS)
    if unknown:
        raise ValueError("Unsupported settings: " + ", ".join(sorted(unknown)))

    current = read_settings(source)["values"]
    metadata_updates: Dict[str, Any] = {}
    code_values = {key: current[key] for key in CODE_FIELDS}
    for key, raw_value in submitted.items():
        field = METADATA_FIELDS.get(key) or CODE_FIELDS[key]
        value = _coerce_value(field, raw_value)
        if key in METADATA_FIELDS and value != current.get(key):
            metadata_updates[key] = value
        if key in CODE_FIELDS:
            code_values[key] = value

    updated = _update_metadata(source, metadata_updates) if metadata_updates else source
    return _replace_or_insert_managed(updated, _managed_block(code_values))

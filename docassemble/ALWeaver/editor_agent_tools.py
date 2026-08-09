"""The only editing capabilities the Weaver agent model can reach.

This module is the security and accuracy boundary. The model never writes YAML
and never names a project or a file: it asks for a semantic command, and Weaver
compiles that command into an exact source replacement, validates the whole
candidate, and only then accepts it.

Two rules hold everywhere in here:

* A tool that is not registered cannot run, no matter what the model emits.
* A mutation that does not survive :func:`validate_candidate_source` leaves the
  candidate exactly as it was.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .editor_agent_models import (
    TOOL_STATUS_ERROR,
    TOOL_STATUS_REJECTED,
    TOOL_STATUS_SUCCESS,
    AgentCandidate,
    AgentToolCall,
    AgentToolResult,
    truncate_diff,
)
from .editor_agent_validation import validate_candidate_source
from .source_document import (
    SourceBlock,
    SourceDocument,
    apply_range_operations,
    document_content_offset,
    parse_source_document,
)

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

# v1 exposes low-risk tools plus a small set of deliberately implemented
# medium-risk ones. High-risk capabilities (Python/Mako/code blocks, includes,
# modules, file creation, arbitrary source edits) are not registered at all, so
# no prompt can talk the model into reaching them.
EXPOSED_RISKS = frozenset({RISK_LOW, RISK_MEDIUM})

MAX_FIELDS_PER_SCREEN = 7
MAX_BLOCKS_PER_READ = 10
MAX_OUTLINE_BLOCKS = 200
MAX_SEARCH_RESULTS = 60

UNSUPPORTED_BLOCK_MESSAGE = (
    "The target block contains source that Weaver cannot losslessly represent "
    "as a graphical block. It may be inspected but cannot be modified by this "
    "tool."
)

# Editable block types per tool family. Anything else is read-only in v1.
QUESTION_BLOCK_TYPES = frozenset({"question"})
REVIEW_BLOCK_TYPES = frozenset({"review"})
ORDER_BLOCK_TYPES = frozenset({"code"})


class ToolArgumentError(ValueError):
    """Raised when tool arguments fail schema validation."""


# ---------------------------------------------------------------------------
# Minimal, deterministic JSON schema validation
# ---------------------------------------------------------------------------


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validate_against_schema(
    schema: Dict[str, Any], value: Any, path: str = "arguments"
) -> List[str]:
    """Validate ``value`` against a small subset of JSON Schema.

    Unknown properties are always an error: that is what stops a model from
    smuggling ``project`` or ``filename`` into a tool call.
    """
    errors: List[str] = []
    expected_types = schema.get("type")
    if expected_types:
        if isinstance(expected_types, str):
            expected_types = [expected_types]
        if not any(_type_matches(value, item) for item in expected_types):
            errors.append(f"{path} must be of type {' or '.join(expected_types)}")
            return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path} must be at least {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path} must be at most {schema['maxLength']} characters")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path} must have at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path} must have at most {schema['maxItems']} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(
                    validate_against_schema(item_schema, item, f"{path}[{index}]")
                )

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}.{required} is required")
        # Only enforced where the schema says so. Every tool schema sets it
        # explicitly, which is what stops a model from smuggling `project` or
        # `filename` into a call; free-form objects (a scenario's variables,
        # for instance) declare no properties and must stay open.
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key} is not an accepted argument")
        for key, sub_schema in properties.items():
            if key in value:
                errors.extend(
                    validate_against_schema(sub_schema, value[key], f"{path}.{key}")
                )

    return errors


# ---------------------------------------------------------------------------
# Source location helpers
# ---------------------------------------------------------------------------


@dataclass
class LocatedBlock:
    """A block identified in both the editor model and the exact source text."""

    block_id: str
    editor_block: Dict[str, Any]
    source_block: SourceBlock
    document: SourceDocument

    @property
    def block_type(self) -> str:
        return str(self.editor_block.get("type") or "other")

    @property
    def data(self) -> Dict[str, Any]:
        value = self.editor_block.get("data")
        return deepcopy(value) if isinstance(value, dict) else {}

    @property
    def replace_range(self) -> Tuple[int, int]:
        """The span to overwrite, keeping any leading comment lines intact."""
        offset = document_content_offset(self.source_block.raw_text)
        return (self.source_block.start_offset + offset, self.source_block.end_offset)


def _line_of_offset(raw_source: str, offset: int) -> int:
    return raw_source.count("\n", 0, offset) + 1


def locate_block(
    raw_source: str, filename: str, block_id: str
) -> Optional[LocatedBlock]:
    """Bridge an editor block id to its exact byte range in the source.

    The graphical model and the lossless source document split documents with
    slightly different separator rules, so the mapping is confirmed by line
    number before any edit is calculated. A disagreement means the block is not
    safely addressable and the caller must refuse rather than guess.
    """
    from .editor_utils import parse_interview_yaml

    model = parse_interview_yaml(raw_source)
    editor_block = None
    for block in model.get("blocks", []):
        if str(block.get("id")) == str(block_id):
            editor_block = block
            break
    if editor_block is None:
        return None

    document = parse_source_document(filename, raw_source)
    index = editor_block.get("index")
    if not isinstance(index, int) or index < 0 or index >= len(document.documents):
        return None
    source_block = document.documents[index]
    if _line_of_offset(raw_source, source_block.start_offset) != int(
        editor_block.get("line_start") or 0
    ):
        return None
    return LocatedBlock(
        block_id=str(block_id),
        editor_block=editor_block,
        source_block=source_block,
        document=document,
    )


def _document_body_text(source_block: SourceBlock) -> str:
    body = source_block.raw_text
    return body if body.endswith("\n") else body + "\n"


# ---------------------------------------------------------------------------
# Tool context and registry
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Everything a tool may see.

    ``project`` and ``filename`` come from the server-bound session. A tool
    handler receives them here and never from model-supplied arguments.
    """

    project: str
    filename: str
    owner_user_id: int
    candidate: AgentCandidate
    runtime_enabled: bool = False
    runtime: Any = None
    runtime_session_started: bool = False
    scenario_seeded: bool = False


@dataclass
class AgentToolSpec:
    name: str
    risk: str
    description: str
    schema: Dict[str, Any]
    handler: Callable[[ToolContext, Dict[str, Any]], AgentToolResult]
    mutating: bool = False
    requires_runtime: bool = False

    def public_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "risk": self.risk,
            "mutating": self.mutating,
            "description": self.description,
            "schema": self.schema,
        }


TOOL_REGISTRY: Dict[str, AgentToolSpec] = {}


def register_tool(spec: AgentToolSpec) -> AgentToolSpec:
    TOOL_REGISTRY[spec.name] = spec
    return spec


def available_tools(*, runtime_enabled: bool = False) -> List[AgentToolSpec]:
    """The tools a given deployment may run, in a stable order."""
    tools = []
    for name in sorted(TOOL_REGISTRY):
        spec = TOOL_REGISTRY[name]
        if spec.risk not in EXPOSED_RISKS:
            continue
        if spec.requires_runtime and not runtime_enabled:
            continue
        tools.append(spec)
    return tools


def available_tool_names(*, runtime_enabled: bool = False) -> List[str]:
    return [spec.name for spec in available_tools(runtime_enabled=runtime_enabled)]


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


def _ok(tool: str, label: str, data: Dict[str, Any], **kwargs: Any) -> AgentToolResult:
    return AgentToolResult(
        tool=tool, status=TOOL_STATUS_SUCCESS, label=label, data=data, **kwargs
    )


def _reject(
    tool: str,
    reason: str,
    message: str,
    *,
    diagnostics: Optional[List[Dict[str, Any]]] = None,
    label: str = "",
) -> AgentToolResult:
    return AgentToolResult(
        tool=tool,
        status=TOOL_STATUS_REJECTED,
        label=label or f"{tool.replace('_', ' ')} was rejected",
        reason=reason,
        message=message,
        diagnostics=diagnostics or [],
    )


def _commit(
    context: ToolContext,
    tool: str,
    arguments: Dict[str, Any],
    proposed_source: str,
    label: str,
    extra: Optional[Dict[str, Any]] = None,
) -> AgentToolResult:
    """Copy-on-write commit: validate first, mutate the candidate only on pass.

    A rejected mutation leaves ``context.candidate`` at its last valid revision,
    which is what keeps candidate validity monotonic across a conversation.
    """
    before_revision = context.candidate.revision
    validation = validate_candidate_source(
        filename=context.filename, raw_yaml=proposed_source
    )
    if validation.blocking:
        return AgentToolResult(
            tool=tool,
            status=TOOL_STATUS_REJECTED,
            label=f"{label} failed validation",
            reason="candidate_validation_failed",
            message=(
                "The edit was not applied. The candidate is unchanged at "
                f"revision {before_revision}."
            ),
            diagnostics=validation.blocking_diagnostics(),
            before_revision=before_revision,
            after_revision=before_revision,
        )

    context.candidate.accept(
        proposed_source, tool=tool, arguments=arguments, validation=validation
    )
    data: Dict[str, Any] = {
        "validation_summary": validation.public_summary(),
        "non_blocking_diagnostics": [
            item
            for item in validation.diagnostics
            if str(item.get("level") or item.get("severity")) != "error"
        ],
    }
    if extra:
        data.update(extra)
    return AgentToolResult(
        tool=tool,
        status=TOOL_STATUS_SUCCESS,
        label=label,
        data=data,
        before_revision=before_revision,
        after_revision=context.candidate.revision,
    )


def _apply_operations(raw_source: str, operations: Sequence[Dict[str, Any]]) -> str:
    updated, _applied = apply_range_operations(raw_source, operations)
    return updated


# ---------------------------------------------------------------------------
# Structured content normalisation
# ---------------------------------------------------------------------------


def _normalized_fields(raw_fields: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Normalise a field list, refusing rather than silently dropping fields."""
    from .editor_ai_utils import DEFAULT_FIELD_TYPES, normalize_generated_fields

    if not isinstance(raw_fields, list):
        return [], "fields must be a list"
    if len(raw_fields) > MAX_FIELDS_PER_SCREEN:
        return [], (
            f"A screen may define at most {MAX_FIELDS_PER_SCREEN} fields. "
            "Split the request across more screens."
        )
    normalized = normalize_generated_fields(
        raw_fields,
        allowed_datatypes=DEFAULT_FIELD_TYPES,
        preferred_count=MAX_FIELDS_PER_SCREEN,
        hard_max=MAX_FIELDS_PER_SCREEN,
    )
    if len(normalized) != len(raw_fields):
        return [], (
            "One or more fields could not be represented. Every field needs a "
            "label and a variable name."
        )

    # A field name that is not a usable variable reference passes YAML and
    # DAYamlChecker but breaks at runtime, so it is caught here rather than
    # being written into the candidate.
    from .editor_agent_rename import validate_variable_reference

    for entry in normalized:
        invalid = validate_variable_reference(str(entry.get("field") or ""))
        if invalid:
            return [], f"Field {entry.get('label')!r}: {invalid}"
    return normalized, None


def _normalized_screen(raw_screen: Dict[str, Any]) -> Dict[str, Any]:
    from .editor_ai_utils import DEFAULT_FIELD_TYPES, normalize_generated_screen

    return normalize_generated_screen(raw_screen, allowed_datatypes=DEFAULT_FIELD_TYPES)


def _apply_screen_to_block(
    block_data: Dict[str, Any],
    spec: Dict[str, Any],
    fields: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Merge a structured screen spec onto an existing block, key by key."""
    screen = _normalized_screen(
        {
            "question": spec.get("question"),
            "subquestion": spec.get("subquestion"),
            "fields": [],
        }
    )
    updated = dict(block_data)
    updated["question"] = screen["question"]
    if "subquestion" in spec:
        if screen["subquestion"]:
            updated["subquestion"] = screen["subquestion"]
        else:
            updated.pop("subquestion", None)
    if fields is not None:
        if fields:
            updated["fields"] = fields
        else:
            # `fields: []` is not a screen with no questions, it is malformed.
            # A screen that asks nothing simply has no fields key.
            updated.pop("fields", None)
    # Only ever written when the caller asked for it: silently adding a
    # continue button field changes how a screen behaves.
    if "continue_button_field" in spec:
        value = str(spec.get("continue_button_field") or "").strip()
        if value:
            updated["continue button field"] = value
        else:
            updated.pop("continue button field", None)
    return updated


def _serialize_block(block_data: Dict[str, Any]) -> str:
    from .editor_utils import canonical_block_yaml

    text = canonical_block_yaml(block_data)
    return text if text.endswith("\n") else text + "\n"


def _normalized_review_items(items: Sequence[Dict[str, Any]]) -> List[Any]:
    """Turn structured review items into Docassemble review entries."""
    entries: List[Any] = []
    for item in items:
        note = item.get("note")
        if isinstance(note, str) and note.strip():
            entries.append({"note": note.strip()})
            continue
        fields = [
            str(name).strip() for name in item.get("fields", []) if str(name).strip()
        ]
        entry: Dict[str, Any] = {"Edit": fields}
        button = str(item.get("button") or "").strip()
        if button:
            entry["button"] = button
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


def _outline_rows(context: ToolContext) -> List[Dict[str, Any]]:
    from .editor_utils import parse_interview_yaml

    model = parse_interview_yaml(context.candidate.raw_source)
    document = parse_source_document(context.filename, context.candidate.raw_source)
    supported_by_index = {item.document_index: item for item in document.documents}
    rows: List[Dict[str, Any]] = []
    for block in model.get("blocks", [])[:MAX_OUTLINE_BLOCKS]:
        source_block = supported_by_index.get(block.get("index"))
        rows.append(
            {
                "block_id": block.get("id"),
                "type": block.get("type"),
                "title": block.get("title"),
                "variable": block.get("variable"),
                "line_start": block.get("line_start"),
                "line_end": block.get("line_end"),
                "editable": bool(source_block and source_block.supported),
                "unsupported_reasons": (
                    list(source_block.unsupported_reasons) if source_block else []
                ),
            }
        )
    return rows


def _tool_get_interview_outline(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    rows = _outline_rows(context)
    return _ok(
        "get_interview_outline",
        "Read interview structure",
        {
            "filename": context.filename,
            "candidate_revision": context.candidate.revision,
            "blocks": rows,
            "fact_source": "static_analysis",
        },
    )


def _block_payload(located: LocatedBlock) -> Dict[str, Any]:
    return {
        "block_id": located.block_id,
        "type": located.block_type,
        "title": located.editor_block.get("title"),
        "variable": located.editor_block.get("variable"),
        "editable": bool(located.source_block.supported),
        "unsupported_reasons": list(located.source_block.unsupported_reasons),
        "source": located.source_block.raw_text,
        "fact_source": "static_analysis",
    }


def _tool_get_block(context: ToolContext, arguments: Dict[str, Any]) -> AgentToolResult:
    block_id = str(arguments["block_id"])
    located = locate_block(context.candidate.raw_source, context.filename, block_id)
    if located is None:
        return _reject(
            "get_block",
            "block_not_found",
            f"No block with id {block_id!r} exists in the candidate.",
        )
    return _ok("get_block", f"Read block {block_id}", _block_payload(located))


def _tool_get_blocks(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    payloads: List[Dict[str, Any]] = []
    missing: List[str] = []
    for block_id in arguments["block_ids"][:MAX_BLOCKS_PER_READ]:
        located = locate_block(
            context.candidate.raw_source, context.filename, str(block_id)
        )
        if located is None:
            missing.append(str(block_id))
        else:
            payloads.append(_block_payload(located))
    return _ok(
        "get_blocks",
        f"Read {len(payloads)} blocks",
        {"blocks": payloads, "missing_block_ids": missing},
    )


def _variable_catalog(raw_source: str) -> List[Dict[str, Any]]:
    from .editor_utils import parse_interview_yaml

    catalog: List[Dict[str, Any]] = []
    seen: set = set()

    def add(name: Any, block_id: Any, kind: str) -> None:
        text = str(name or "").strip()
        if not text or (text, block_id) in seen:
            return
        seen.add((text, block_id))
        catalog.append({"variable": text, "block_id": block_id, "kind": kind})

    for block in parse_interview_yaml(raw_source).get("blocks", []):
        block_id = block.get("id")
        add(block.get("variable"), block_id, "block")
        data = block.get("data")
        if not isinstance(data, dict):
            continue
        for entry in data.get("fields", []) or []:
            if not isinstance(entry, dict):
                continue
            named = entry.get("field") or entry.get("variable")
            if named:
                add(named, block_id, "field")
                continue
            # docassemble field shorthand is `{<label>: <variable>}`, so the
            # variable is the value rather than a `field:` key.
            if len(entry) == 1:
                key, value = next(iter(entry.items()))
                if isinstance(value, str) and str(key).lower() not in {
                    "note",
                    "html",
                    "code",
                }:
                    add(value, block_id, "field")
        sets_value = data.get("sets")
        if isinstance(sets_value, str):
            add(sets_value, block_id, "sets")
        elif isinstance(sets_value, list):
            for item in sets_value:
                add(item, block_id, "sets")
        objects = data.get("objects")
        if isinstance(objects, list):
            for item in objects:
                if isinstance(item, dict):
                    for key in item:
                        add(key, block_id, "object")
    return catalog


def _tool_search_variables(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    query = str(arguments.get("query") or "").strip().lower()
    catalog = _variable_catalog(context.candidate.raw_source)
    if query:
        catalog = [item for item in catalog if query in str(item["variable"]).lower()]
    return _ok(
        "search_variables",
        "Searched interview variables",
        {
            "query": query,
            "variables": catalog[:MAX_SEARCH_RESULTS],
            "truncated": len(catalog) > MAX_SEARCH_RESULTS,
            "fact_source": "static_analysis",
        },
    )


def _tool_find_variable_references(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    import re as _re

    variable = str(arguments["variable"]).strip()
    pattern = _re.compile(r"(?<![\w.])" + _re.escape(variable) + r"(?![\w])")
    document = parse_source_document(context.filename, context.candidate.raw_source)
    from .editor_utils import parse_interview_yaml

    model = parse_interview_yaml(context.candidate.raw_source)
    ids_by_index = {
        block.get("index"): block.get("id") for block in model.get("blocks", [])
    }
    references: List[Dict[str, Any]] = []
    for source_block in document.documents:
        matches = list(pattern.finditer(source_block.raw_text))
        if not matches:
            continue
        references.append(
            {
                "block_id": ids_by_index.get(source_block.document_index),
                "match_count": len(matches),
                "editable": bool(source_block.supported),
            }
        )
    return _ok(
        "find_variable_references",
        f"Found {len(references)} blocks referencing {variable}",
        {
            "variable": variable,
            "references": references,
            "fact_source": "static_analysis",
        },
    )


def _find_order_block(context: ToolContext) -> Optional[LocatedBlock]:
    from .editor_utils import parse_interview_yaml

    model = parse_interview_yaml(context.candidate.raw_source)
    order_indices = model.get("order_blocks") or []
    if not order_indices:
        return None
    blocks = model.get("blocks", [])
    for index in order_indices:
        for block in blocks:
            if block.get("index") == index:
                return locate_block(
                    context.candidate.raw_source,
                    context.filename,
                    str(block.get("id")),
                )
    return None


def _tool_get_order(context: ToolContext, arguments: Dict[str, Any]) -> AgentToolResult:
    from .editor_utils import parse_order_code

    located = _find_order_block(context)
    if located is None:
        return _ok(
            "get_order",
            "Read interview order",
            {"exists": False, "steps": [], "fact_source": "static_analysis"},
        )
    code = str(located.data.get("code") or "")
    return _ok(
        "get_order",
        "Read interview order",
        {
            "exists": True,
            "block_id": located.block_id,
            "editable": bool(located.source_block.supported),
            "code": code,
            "steps": parse_order_code(code),
            "fact_source": "static_analysis",
        },
    )


def _find_review_block(context: ToolContext) -> Optional[LocatedBlock]:
    from .editor_utils import parse_interview_yaml

    for block in parse_interview_yaml(context.candidate.raw_source).get("blocks", []):
        if block.get("type") == "review":
            return locate_block(
                context.candidate.raw_source, context.filename, str(block.get("id"))
            )
    return None


def _tool_get_review_screen(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    block_id = str(arguments.get("block_id") or "").strip()
    located = (
        locate_block(context.candidate.raw_source, context.filename, block_id)
        if block_id
        else _find_review_block(context)
    )
    if located is None:
        return _ok(
            "get_review_screen",
            "Read review screen",
            {"exists": False, "fact_source": "static_analysis"},
        )
    payload = _block_payload(located)
    payload["exists"] = True
    payload["review"] = located.data.get("review")
    return _ok("get_review_screen", "Read review screen", payload)


def _tool_validate_candidate(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    validation = validate_candidate_source(
        filename=context.filename, raw_yaml=context.candidate.raw_source
    )
    status_label = (
        "Validation passed" if not validation.blocking else "Validation failed"
    )
    return _ok(
        "validate_candidate",
        status_label,
        {
            "blocking": validation.blocking,
            "structurally_valid": validation.structurally_valid,
            "summary": validation.public_summary(),
            "diagnostics": validation.diagnostics,
            "candidate_revision": context.candidate.revision,
            "fact_source": "static_analysis",
        },
    )


def _tool_get_candidate_diff(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    diff_text = context.candidate.diff(context.filename)
    payload = truncate_diff(diff_text)
    payload["candidate_revision"] = context.candidate.revision
    payload["fact_source"] = "static_analysis"
    return _ok("get_candidate_diff", "Compared candidate with working source", payload)


# ---------------------------------------------------------------------------
# Edit tools
# ---------------------------------------------------------------------------


def _require_editable(
    tool: str, located: Optional[LocatedBlock], block_id: str, allowed_types: frozenset
) -> Optional[AgentToolResult]:
    if located is None:
        return _reject(
            tool,
            "block_not_found",
            f"No block with id {block_id!r} exists in the candidate.",
        )
    if not located.source_block.supported:
        return _reject(tool, "unsupported_block", UNSUPPORTED_BLOCK_MESSAGE)
    if located.block_type not in allowed_types:
        return _reject(
            tool,
            "wrong_block_type",
            f"Block {block_id!r} is a {located.block_type} block, which this tool "
            f"cannot modify. Accepted types: {', '.join(sorted(allowed_types))}.",
        )
    return None


def _tool_replace_question(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    block_id = str(arguments["block_id"])
    located = locate_block(context.candidate.raw_source, context.filename, block_id)
    refusal = _require_editable(
        "replace_question", located, block_id, QUESTION_BLOCK_TYPES
    )
    if refusal is not None:
        return refusal
    assert located is not None

    spec = arguments["question"]
    fields: Optional[List[Dict[str, Any]]] = None
    if "fields" in spec:
        fields, error = _normalized_fields(spec["fields"])
        if error:
            return _reject("replace_question", "invalid_fields", error)

    block_data = _apply_screen_to_block(located.data, spec, fields)
    start, end = located.replace_range
    proposed = _apply_operations(
        context.candidate.raw_source,
        [
            {
                "type": "replace-range",
                "start": start,
                "end": end,
                "text": _serialize_block(block_data),
            }
        ],
    )
    return _commit(
        context,
        "replace_question",
        arguments,
        proposed,
        f"Updated question “{block_id}”",
        {"block_id": block_id},
    )


def _tool_replace_fields(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    block_id = str(arguments["block_id"])
    located = locate_block(context.candidate.raw_source, context.filename, block_id)
    refusal = _require_editable(
        "replace_fields", located, block_id, QUESTION_BLOCK_TYPES
    )
    if refusal is not None:
        return refusal
    assert located is not None

    fields, error = _normalized_fields(arguments["fields"])
    if error:
        return _reject("replace_fields", "invalid_fields", error)

    block_data = located.data
    block_data["fields"] = fields
    start, end = located.replace_range
    proposed = _apply_operations(
        context.candidate.raw_source,
        [
            {
                "type": "replace-range",
                "start": start,
                "end": end,
                "text": _serialize_block(block_data),
            }
        ],
    )
    return _commit(
        context,
        "replace_fields",
        arguments,
        proposed,
        f"Replaced fields on “{block_id}”",
        {"block_id": block_id, "field_count": len(fields)},
    )


def _insertion_operation(
    raw_source: str, anchor: Optional[SourceBlock], position: str, body: str
) -> Dict[str, Any]:
    """Build the single range operation that inserts a new YAML document."""
    if anchor is None:
        prefix = "" if not raw_source or raw_source.endswith("\n") else "\n"
        return {
            "type": "replace-range",
            "start": len(raw_source),
            "end": len(raw_source),
            "text": f"{prefix}---\n{body}" if raw_source.strip() else body,
        }
    if position == "before":
        return {
            "type": "replace-range",
            "start": anchor.start_offset,
            "end": anchor.start_offset,
            "text": f"{body}---\n",
        }
    prefix = "" if anchor.raw_text.endswith("\n") or not anchor.raw_text else "\n"
    return {
        "type": "replace-range",
        "start": anchor.end_offset,
        "end": anchor.end_offset,
        "text": f"{prefix}---\n{body}",
    }


def _tool_insert_question(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    spec = arguments["question"]
    new_block_id = str(arguments["new_block_id"]).strip()
    from .editor_utils import parse_interview_yaml

    existing_ids = {
        str(block.get("id"))
        for block in parse_interview_yaml(context.candidate.raw_source).get(
            "blocks", []
        )
    }
    if new_block_id in existing_ids:
        return _reject(
            "insert_question",
            "duplicate_block_id",
            f"A block with id {new_block_id!r} already exists. Choose another id "
            "or use replace_question.",
        )

    fields, error = _normalized_fields(spec.get("fields", []))
    if error:
        return _reject("insert_question", "invalid_fields", error)

    block_data = _apply_screen_to_block({"id": new_block_id}, spec, fields)

    anchor_source: Optional[SourceBlock] = None
    anchor_id = str(arguments.get("relative_to_block_id") or "").strip()
    position = str(arguments.get("position") or "after")
    if anchor_id:
        anchor = locate_block(context.candidate.raw_source, context.filename, anchor_id)
        if anchor is None:
            return _reject(
                "insert_question",
                "block_not_found",
                f"No block with id {anchor_id!r} exists in the candidate.",
            )
        anchor_source = anchor.source_block

    operation = _insertion_operation(
        context.candidate.raw_source,
        anchor_source,
        position,
        _serialize_block(block_data),
    )
    proposed = _apply_operations(context.candidate.raw_source, [operation])
    return _commit(
        context,
        "insert_question",
        arguments,
        proposed,
        f"Inserted new screen “{new_block_id}”",
        {"block_id": new_block_id},
    )


def _tool_insert_exit_screen(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    """Create a terminal screen: an event block that asks nothing and stops.

    This is a different shape from a question screen — no fields, an ``event``
    name, and it is reached by naming that event in the interview order under a
    condition. Without a tool for it a model produces a question screen with an
    empty field list, which is not a valid screen at all.
    """
    from .editor_utils import parse_interview_yaml

    new_block_id = str(arguments["new_block_id"]).strip()
    event_name = str(arguments.get("event_name") or new_block_id).strip()
    if not event_name.isidentifier():
        return _reject(
            "insert_exit_screen",
            "invalid_event_name",
            f"{event_name!r} is not a usable event name. Use a plain name like "
            "no_fax_exit.",
        )

    existing_ids = {
        str(block.get("id"))
        for block in parse_interview_yaml(context.candidate.raw_source).get(
            "blocks", []
        )
    }
    if new_block_id in existing_ids:
        return _reject(
            "insert_exit_screen",
            "duplicate_block_id",
            f"A block with id {new_block_id!r} already exists.",
        )

    spec = arguments["screen"]
    block_data: Dict[str, Any] = {"id": new_block_id, "event": event_name}
    block_data = _apply_screen_to_block(block_data, spec, None)

    buttons = arguments.get("buttons")
    if buttons:
        block_data["buttons"] = [
            {str(item["label"]): str(item["action"])} for item in buttons
        ]

    anchor_source: Optional[SourceBlock] = None
    anchor_id = str(arguments.get("relative_to_block_id") or "").strip()
    if anchor_id:
        anchor = locate_block(context.candidate.raw_source, context.filename, anchor_id)
        if anchor is None:
            return _reject(
                "insert_exit_screen",
                "block_not_found",
                f"No block with id {anchor_id!r} exists in the candidate.",
            )
        anchor_source = anchor.source_block

    operation = _insertion_operation(
        context.candidate.raw_source,
        anchor_source,
        str(arguments.get("position") or "after"),
        _serialize_block(block_data),
    )
    proposed = _apply_operations(context.candidate.raw_source, [operation])
    return _commit(
        context,
        "insert_exit_screen",
        arguments,
        proposed,
        f"Inserted exit screen “{new_block_id}”",
        {
            "block_id": new_block_id,
            "event_name": event_name,
            "next_step": (
                "Now call replace_order_steps so the interview order reaches it, "
                'for example {"kind": "condition", "condition": "not '
                f'recipient_has_fax", "children": ["{event_name}"]}}.'
            ),
        },
    )


def _tool_move_block(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    block_id = str(arguments["block_id"])
    anchor_id = str(arguments["relative_to_block_id"])
    position = str(arguments["position"])
    if block_id == anchor_id:
        return _reject(
            "move_block", "invalid_move", "A block cannot be moved relative to itself."
        )

    located = locate_block(context.candidate.raw_source, context.filename, block_id)
    if located is None:
        return _reject(
            "move_block",
            "block_not_found",
            f"No block with id {block_id!r} exists in the candidate.",
        )
    anchor = locate_block(context.candidate.raw_source, context.filename, anchor_id)
    if anchor is None:
        return _reject(
            "move_block",
            "block_not_found",
            f"No block with id {anchor_id!r} exists in the candidate.",
        )

    documents = located.document.documents
    index = located.source_block.document_index
    anchor_index = anchor.source_block.document_index
    if (position == "after" and anchor_index == index - 1) or (
        position == "before" and anchor_index == index + 1
    ):
        return _reject(
            "move_block",
            "no_op_move",
            f"Block {block_id!r} is already {position} {anchor_id!r}.",
        )

    body = _document_body_text(located.source_block)
    if index + 1 < len(documents):
        removal = {
            "type": "replace-range",
            "start": located.source_block.start_offset,
            "end": documents[index + 1].start_offset,
            "text": "",
        }
    elif index > 0:
        removal = {
            "type": "replace-range",
            "start": documents[index - 1].end_offset,
            "end": located.source_block.end_offset,
            "text": "",
        }
    else:
        return _reject(
            "move_block",
            "invalid_move",
            "A single-document interview has nothing to move the block past.",
        )

    insertion = _insertion_operation(
        context.candidate.raw_source, anchor.source_block, position, body
    )
    try:
        proposed = _apply_operations(context.candidate.raw_source, [removal, insertion])
    except ValueError as exc:
        return _reject("move_block", "invalid_move", str(exc))

    return _commit(
        context,
        "move_block",
        arguments,
        proposed,
        f"Moved “{block_id}” {position} “{anchor_id}”",
        {"block_id": block_id},
    )


def _normalize_order_steps(raw_steps: Any) -> List[Dict[str, Any]]:
    """Coerce an order-step list into the shape the serializer expects.

    A bare string in a step list can only mean "show this screen", and models
    write it that way constantly. Normalising it here turns what used to be an
    unhandled crash into an ordinary edit.
    """
    normalized: List[Dict[str, Any]] = []
    for item in raw_steps or []:
        if isinstance(item, str):
            name = item.strip()
            if name:
                normalized.append({"kind": "screen", "invoke": name})
            continue
        if not isinstance(item, dict):
            continue
        step = dict(item)
        for key in ("children", "else_children"):
            if key in step:
                step[key] = _normalize_order_steps(step.get(key))
        normalized.append(step)
    return normalized


def _invoked_names(steps: Sequence[Dict[str, Any]]) -> set:
    """Every screen or gather a step list reaches, at any nesting depth."""
    names: set = set()
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        invoke = str(step.get("invoke") or "").strip()
        if invoke:
            names.add(invoke)
        for key in ("children", "else_children"):
            names |= _invoked_names(step.get(key) or [])
    return names


def _tool_replace_order_steps(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    from .editor_utils import parse_order_code, serialize_order_steps

    steps = _normalize_order_steps(arguments["steps"])
    try:
        code_body = serialize_order_steps(steps)
    except Exception as exc:  # noqa: BLE001 - report the shape problem, do not crash
        return _reject(
            "replace_order_steps",
            "invalid_steps",
            "Those steps could not be turned into interview-order code "
            f"({type(exc).__name__}). Each step is an object such as "
            '{"kind": "screen", "invoke": "screen_id"} or '
            '{"kind": "condition", "condition": "not x", "children": [...]}.',
        )
    if not code_body.strip():
        return _reject(
            "replace_order_steps",
            "empty_order",
            "The interview order cannot be emptied. Supply at least one step.",
        )

    located = _find_order_block(context)
    if located is None:
        block_data = {"id": "interview_order", "mandatory": True, "code": code_body}
        operation = _insertion_operation(
            context.candidate.raw_source, None, "after", _serialize_block(block_data)
        )
        proposed = _apply_operations(context.candidate.raw_source, [operation])
        return _commit(
            context,
            "replace_order_steps",
            arguments,
            proposed,
            "Created the interview order",
            {"block_id": "interview_order", "step_count": len(steps)},
        )

    refusal = _require_editable(
        "replace_order_steps", located, located.block_id, ORDER_BLOCK_TYPES
    )
    if refusal is not None:
        return refusal

    # Only the block's own keys are preserved. Weaver's synthetic block ids are
    # content fingerprints, so writing one back as a real `id:` would invent a
    # name the developer never chose.
    block_data = located.data
    block_data["mandatory"] = True
    block_data["code"] = code_body
    start, end = located.replace_range
    proposed = _apply_operations(
        context.candidate.raw_source,
        [
            {
                "type": "replace-range",
                "start": start,
                "end": end,
                "text": _serialize_block(block_data),
            }
        ],
    )
    return _commit(
        context,
        "replace_order_steps",
        arguments,
        proposed,
        "Updated interview order",
        {"block_id": located.block_id, "step_count": len(steps)},
    )


def _tool_suggest_object_conversion(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    from .editor_agent_rename import suggest_object_conversion

    proposal = suggest_object_conversion(
        raw_yaml=context.candidate.raw_source,
        prefix=str(arguments.get("prefix") or ""),
    )
    proposal["fact_source"] = "static_analysis"
    count = len(proposal["renames"])
    return _ok(
        "suggest_object_conversion",
        f"Proposed {count} object conversions",
        proposal,
    )


def _tool_rename_variables(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    from .editor_agent_rename import (
        check_rename_batch,
        plan_rename_operations,
    )

    renames = arguments["renames"]
    analyses, problems = check_rename_batch(
        filename=context.filename,
        raw_yaml=context.candidate.raw_source,
        renames=renames,
    )
    if problems:
        return _reject(
            "rename_variables",
            "unsafe_rename",
            " ".join(problems[:4]),
            diagnostics=[
                item
                for analysis in analyses
                for item in analysis.public_dict()["unsafe_references"]
            ],
        )
    if not analyses:
        return _reject(
            "rename_variables",
            "unsafe_rename",
            "No rename could be carried out safely.",
        )

    operations = plan_rename_operations(analyses)
    try:
        proposed = _apply_operations(context.candidate.raw_source, operations)
    except ValueError as exc:
        return _reject("rename_variables", "overlapping_rename", str(exc))

    touched: List[str] = []
    for analysis in analyses:
        for block_id in analysis.blocks_touched:
            if block_id not in touched:
                touched.append(block_id)
    names = ", ".join(f"{item.old_name} → {item.new_name}" for item in analyses[:3])
    label = (
        f"Renamed {len(analyses)} variables"
        if len(analyses) > 1
        else f"Renamed {analyses[0].old_name} to {analyses[0].new_name}"
    )
    return _commit(
        context,
        "rename_variables",
        arguments,
        proposed,
        label,
        {
            "renames": [analysis.public_dict() for analysis in analyses],
            "blocks_touched": touched,
            "summary": names,
        },
    )


def _tool_replace_review_screen(
    context: ToolContext, arguments: Dict[str, Any]
) -> AgentToolResult:
    spec = arguments["review"]
    entries = _normalized_review_items(spec["items"])
    if not entries:
        return _reject(
            "replace_review_screen",
            "empty_review",
            "A review screen needs at least one item.",
        )

    block_id = str(arguments.get("block_id") or "").strip()
    located = (
        locate_block(context.candidate.raw_source, context.filename, block_id)
        if block_id
        else _find_review_block(context)
    )
    if located is not None:
        refusal = _require_editable(
            "replace_review_screen", located, located.block_id, REVIEW_BLOCK_TYPES
        )
        if refusal is not None:
            return refusal
        block_data = located.data
    elif block_id:
        return _reject(
            "replace_review_screen",
            "block_not_found",
            f"No block with id {block_id!r} exists in the candidate.",
        )
    else:
        block_data = {"id": "review_answers", "event": "review_answers"}

    screen = _normalized_screen(
        {"question": spec.get("question"), "subquestion": spec.get("subquestion")}
    )
    block_data["question"] = screen["question"]
    if screen["subquestion"]:
        block_data["subquestion"] = screen["subquestion"]
    block_data["review"] = entries

    if located is None:
        operation = _insertion_operation(
            context.candidate.raw_source, None, "after", _serialize_block(block_data)
        )
        proposed = _apply_operations(context.candidate.raw_source, [operation])
        label = "Created the review screen"
        target_id = str(block_data.get("id"))
    else:
        start, end = located.replace_range
        proposed = _apply_operations(
            context.candidate.raw_source,
            [
                {
                    "type": "replace-range",
                    "start": start,
                    "end": end,
                    "text": _serialize_block(block_data),
                }
            ],
        )
        label = "Updated the review screen"
        target_id = located.block_id

    return _commit(
        context,
        "replace_review_screen",
        arguments,
        proposed,
        label,
        {"block_id": target_id, "item_count": len(entries)},
    )


# ---------------------------------------------------------------------------
# Runtime tools (read-only, optional, always labelled observed_runtime)
# ---------------------------------------------------------------------------


def _runtime_result(
    tool: str, label: str, context: ToolContext, payload: Dict[str, Any]
) -> AgentToolResult:
    data = dict(payload)
    data["fact_source"] = "observed_runtime"
    data["scenario_seeded"] = context.scenario_seeded
    return _ok(tool, label, data)


def _require_runtime(tool: str, context: ToolContext) -> Optional[AgentToolResult]:
    if not context.runtime_enabled or context.runtime is None:
        return _reject(
            tool,
            "runtime_unavailable",
            "Runtime inspection is not enabled on this installation.",
        )
    if tool != "runtime_start_session" and not context.runtime_session_started:
        return _reject(
            tool,
            "runtime_session_missing",
            "Call runtime_start_session before inspecting runtime facts.",
        )
    return None


def _runtime_tool(
    name: str,
    label: str,
    invoke: Callable[[ToolContext, Dict[str, Any]], Dict[str, Any]],
) -> Callable[[ToolContext, Dict[str, Any]], AgentToolResult]:
    def handler(context: ToolContext, arguments: Dict[str, Any]) -> AgentToolResult:
        refusal = _require_runtime(name, context)
        if refusal is not None:
            return refusal
        try:
            payload = invoke(context, arguments)
        except Exception as exc:  # noqa: BLE001 - surfaced to the model as a rejection
            return _reject(
                name,
                "runtime_operation_failed",
                f"Docassemble could not complete the runtime request: {type(exc).__name__}",
            )
        return _runtime_result(name, label, context, payload)

    return handler


def _runtime_start(context: ToolContext, arguments: Dict[str, Any]) -> Dict[str, Any]:
    payload = context.runtime.start_session()
    context.runtime_session_started = True
    context.scenario_seeded = False
    return payload


def _runtime_scenario(
    context: ToolContext, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    payload = context.runtime.apply_scenario(
        arguments.get("variables", {}), arguments.get("delete", [])
    )
    # A seeded scenario is a fixture. Later observations must stay marked so the
    # model never presents them as proof the interview naturally reached a state.
    context.scenario_seeded = True
    result = dict(payload)
    result["warning"] = (
        "Seeded scenario values are a test fixture. They may bypass earlier "
        "gathering behaviour, so this does not prove the interview reaches this "
        "state on its own."
    )
    return result


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------


def _datatype_schema() -> Dict[str, Any]:
    """List the real datatypes rather than accepting free text.

    Normalisation quietly falls back to "text" for a datatype it does not
    recognise, which turns a yes/no question into a text box without telling
    anyone. Enumerating them makes an unknown datatype a schema rejection that
    names the valid options, and shows the model what it can choose from.
    """
    try:
        from .editor_ai_utils import DEFAULT_FIELD_TYPES

        datatypes = [str(item) for item in DEFAULT_FIELD_TYPES if str(item).strip()]
    except Exception:
        datatypes = []
    if not datatypes:
        return {"type": "string", "maxLength": 40}
    return {"type": "string", "enum": datatypes}


_FIELD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["label", "field"],
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string", "minLength": 1, "maxLength": 2000},
        "field": {"type": "string", "minLength": 1, "maxLength": 200},
        "datatype": _datatype_schema(),
        "choices": {"type": "array", "items": {"type": "string"}, "maxItems": 40},
    },
}

_SCREEN_SCHEMA = {
    "type": "object",
    "required": ["question"],
    "additionalProperties": False,
    "properties": {
        "question": {"type": "string", "minLength": 1, "maxLength": 4000},
        "subquestion": {"type": "string", "maxLength": 8000},
        "continue_button_field": {"type": "string", "maxLength": 200},
        "fields": {
            "type": "array",
            "items": _FIELD_SCHEMA,
            "maxItems": MAX_FIELDS_PER_SCREEN,
        },
    },
}


def _order_step_schema(depth: int = 2) -> Dict[str, Any]:
    """Build the order-step schema, nested to a bounded depth.

    Nesting is expressed by copying rather than self-reference: the catalog is
    serialised into the system prompt, and a cyclic schema cannot be written as
    JSON.
    """
    nested: Dict[str, Any]
    if depth > 0:
        nested = _order_step_schema(depth - 1)
    else:
        nested = {"type": ["object", "string"]}
    schema = deepcopy(_ORDER_STEP_BASE)
    schema["properties"]["children"] = {
        "type": "array",
        "maxItems": 60,
        "items": nested,
    }
    schema["properties"]["else_children"] = {
        "type": "array",
        "maxItems": 60,
        "items": nested,
    }
    return schema


_ORDER_STEP_BASE: Dict[str, Any] = {
    # A step is an object, or just the name of a screen to show. Both spellings
    # are accepted because models write both, and the shorthand has exactly one
    # possible meaning.
    "type": ["object", "string"],
    "maxLength": 400,
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "maxLength": 200},
        "kind": {
            "type": "string",
            "enum": [
                "screen",
                "gather",
                "section",
                "progress",
                "function",
                "condition",
                "raw",
            ],
        },
        "label": {"type": "string", "maxLength": 200},
        "summary": {"type": "string", "maxLength": 400},
        "value": {"type": "string", "maxLength": 200},
        "invoke": {"type": "string", "maxLength": 400},
        "code": {"type": "string", "maxLength": 2000},
        "condition": {"type": "string", "maxLength": 400},
        "has_else": {"type": "boolean"},
        # Replaced by _order_step_schema with a validated nested item schema.
        # Leaving these unconstrained let a list of bare strings reach the
        # serializer and raise, which the model could only read as "the tool is
        # broken".
        "children": {"type": "array", "maxItems": 60},
        "else_children": {"type": "array", "maxItems": 60},
    },
}

_ORDER_STEP_SCHEMA: Dict[str, Any] = _order_step_schema()

_REVIEW_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fields": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
            "maxItems": 20,
        },
        "button": {"type": "string", "maxLength": 1000},
        "note": {"type": "string", "maxLength": 2000},
    },
}


def _register_all() -> None:
    register_tool(
        AgentToolSpec(
            name="get_interview_outline",
            risk=RISK_LOW,
            description=(
                "List every block in the candidate with its id, type, title and "
                "whether Weaver can edit it."
            ),
            schema={"type": "object", "additionalProperties": False, "properties": {}},
            handler=_tool_get_interview_outline,
        )
    )
    register_tool(
        AgentToolSpec(
            name="get_block",
            risk=RISK_LOW,
            description="Read the exact source of one block.",
            schema={
                "type": "object",
                "required": ["block_id"],
                "additionalProperties": False,
                "properties": {"block_id": {"type": "string", "minLength": 1}},
            },
            handler=_tool_get_block,
        )
    )
    register_tool(
        AgentToolSpec(
            name="get_blocks",
            risk=RISK_LOW,
            description="Read the exact source of several blocks at once.",
            schema={
                "type": "object",
                "required": ["block_ids"],
                "additionalProperties": False,
                "properties": {
                    "block_ids": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "maxItems": MAX_BLOCKS_PER_READ,
                    }
                },
            },
            handler=_tool_get_blocks,
        )
    )
    register_tool(
        AgentToolSpec(
            name="search_variables",
            risk=RISK_LOW,
            description="Search the variables this interview defines.",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"query": {"type": "string", "maxLength": 200}},
            },
            handler=_tool_search_variables,
        )
    )
    register_tool(
        AgentToolSpec(
            name="find_variable_references",
            risk=RISK_LOW,
            description="List the blocks that mention one variable.",
            schema={
                "type": "object",
                "required": ["variable"],
                "additionalProperties": False,
                "properties": {
                    "variable": {"type": "string", "minLength": 1, "maxLength": 200}
                },
            },
            handler=_tool_find_variable_references,
        )
    )
    register_tool(
        AgentToolSpec(
            name="get_order",
            risk=RISK_LOW,
            description="Read the interview order as structured steps.",
            schema={"type": "object", "additionalProperties": False, "properties": {}},
            handler=_tool_get_order,
        )
    )
    register_tool(
        AgentToolSpec(
            name="get_review_screen",
            risk=RISK_LOW,
            description="Read the review screen block.",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"block_id": {"type": "string", "maxLength": 200}},
            },
            handler=_tool_get_review_screen,
        )
    )
    register_tool(
        AgentToolSpec(
            name="validate_candidate",
            risk=RISK_LOW,
            description=(
                "Validate the whole candidate. This result is authoritative: an "
                "edit is only valid when this tool says so."
            ),
            schema={"type": "object", "additionalProperties": False, "properties": {}},
            handler=_tool_validate_candidate,
        )
    )
    register_tool(
        AgentToolSpec(
            name="get_candidate_diff",
            risk=RISK_LOW,
            description="Show the unified diff between the working source and the candidate.",
            schema={"type": "object", "additionalProperties": False, "properties": {}},
            handler=_tool_get_candidate_diff,
        )
    )

    register_tool(
        AgentToolSpec(
            name="replace_question",
            risk=RISK_LOW,
            mutating=True,
            description=(
                "Rewrite the question text, subquestion and optionally the fields "
                "of one existing question block. Question, subquestion and label "
                "text is Markdown and may span multiple lines."
            ),
            schema={
                "type": "object",
                "required": ["block_id", "question"],
                "additionalProperties": False,
                "properties": {
                    "block_id": {"type": "string", "minLength": 1},
                    "question": _SCREEN_SCHEMA,
                },
            },
            handler=_tool_replace_question,
        )
    )
    register_tool(
        AgentToolSpec(
            name="replace_fields",
            risk=RISK_LOW,
            mutating=True,
            description="Replace the field list of one existing question block.",
            schema={
                "type": "object",
                "required": ["block_id", "fields"],
                "additionalProperties": False,
                "properties": {
                    "block_id": {"type": "string", "minLength": 1},
                    "fields": {
                        "type": "array",
                        "items": _FIELD_SCHEMA,
                        "minItems": 1,
                        "maxItems": MAX_FIELDS_PER_SCREEN,
                    },
                },
            },
            handler=_tool_replace_fields,
        )
    )
    register_tool(
        AgentToolSpec(
            name="insert_question",
            risk=RISK_LOW,
            mutating=True,
            description=(
                "Insert a new question screen. Omit relative_to_block_id to append "
                "the screen at the end of the interview."
            ),
            schema={
                "type": "object",
                "required": ["new_block_id", "question"],
                "additionalProperties": False,
                "properties": {
                    "new_block_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                    },
                    "question": _SCREEN_SCHEMA,
                    "relative_to_block_id": {"type": "string", "maxLength": 200},
                    "position": {"type": "string", "enum": ["before", "after"]},
                },
            },
            handler=_tool_insert_question,
        )
    )
    register_tool(
        AgentToolSpec(
            name="insert_exit_screen",
            risk=RISK_LOW,
            mutating=True,
            description=(
                "Insert a dead-end screen that tells the user why the interview "
                "is stopping and asks nothing. Use this — not insert_question — "
                "whenever a screen ends the interview: an exit screen, a "
                "screening failure, an ineligibility notice. It has no fields; "
                "it has an `event` name. Follow it with replace_order_steps so "
                "the order reaches it, as "
                '{"kind": "condition", "condition": "not eligible", '
                '"children": ["the_event_name"]}.'
            ),
            schema={
                "type": "object",
                "required": ["new_block_id", "screen"],
                "additionalProperties": False,
                "properties": {
                    "new_block_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                    },
                    "event_name": {"type": "string", "maxLength": 200},
                    "screen": {
                        "type": "object",
                        "required": ["question"],
                        "additionalProperties": False,
                        "properties": {
                            "question": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 4000,
                            },
                            "subquestion": {"type": "string", "maxLength": 8000},
                        },
                    },
                    "buttons": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "required": ["label", "action"],
                            "additionalProperties": False,
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 200,
                                },
                                "action": {
                                    "type": "string",
                                    "enum": ["exit", "restart", "leave"],
                                },
                            },
                        },
                    },
                    "relative_to_block_id": {"type": "string", "maxLength": 200},
                    "position": {"type": "string", "enum": ["before", "after"]},
                },
            },
            handler=_tool_insert_exit_screen,
        )
    )
    register_tool(
        AgentToolSpec(
            name="move_block",
            risk=RISK_LOW,
            mutating=True,
            description="Move one block before or after another block.",
            schema={
                "type": "object",
                "required": ["block_id", "relative_to_block_id", "position"],
                "additionalProperties": False,
                "properties": {
                    "block_id": {"type": "string", "minLength": 1},
                    "relative_to_block_id": {"type": "string", "minLength": 1},
                    "position": {"type": "string", "enum": ["before", "after"]},
                },
            },
            handler=_tool_move_block,
        )
    )
    register_tool(
        AgentToolSpec(
            name="suggest_object_conversion",
            risk=RISK_LOW,
            description=(
                "Propose object paths for a family of flat variables, using "
                "Weaver's own naming table — persons1_name becomes "
                "persons[0].name.first, persons1_address becomes "
                "persons[0].address.address. Read-only: pass the result to "
                "rename_variables to carry it out."
            ),
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "prefix": {"type": "string", "maxLength": 100},
                },
            },
            handler=_tool_suggest_object_conversion,
        )
    )
    register_tool(
        AgentToolSpec(
            name="rename_variables",
            risk=RISK_MEDIUM,
            mutating=True,
            description=(
                "Rename one or more variables everywhere they are referenced. "
                "Weaver finds the references itself and refuses the whole batch "
                "if any appearance cannot be rewritten safely — a name inside a "
                "string, a call, display prose, or a block it cannot edit. Never "
                "rename by editing blocks one at a time."
            ),
            schema={
                "type": "object",
                "required": ["renames"],
                "additionalProperties": False,
                "properties": {
                    "renames": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 40,
                        "items": {
                            "type": "object",
                            "required": ["old_name", "new_name"],
                            "additionalProperties": False,
                            "properties": {
                                "old_name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 200,
                                },
                                "new_name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 200,
                                },
                            },
                        },
                    }
                },
            },
            handler=_tool_rename_variables,
        )
    )
    register_tool(
        AgentToolSpec(
            name="replace_order_steps",
            risk=RISK_MEDIUM,
            mutating=True,
            description=(
                "Replace the mandatory interview-order code with structured steps. "
                "Weaver serialises the Python; never write order code by hand."
            ),
            schema={
                "type": "object",
                "required": ["steps"],
                "additionalProperties": False,
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": _ORDER_STEP_SCHEMA,
                        "minItems": 1,
                        "maxItems": 200,
                    }
                },
            },
            handler=_tool_replace_order_steps,
        )
    )
    register_tool(
        AgentToolSpec(
            name="replace_review_screen",
            risk=RISK_MEDIUM,
            mutating=True,
            description=(
                "Replace the review screen items. Each item either edits a list of "
                "variables or is a note."
            ),
            schema={
                "type": "object",
                "required": ["review"],
                "additionalProperties": False,
                "properties": {
                    "block_id": {"type": "string", "maxLength": 200},
                    "review": {
                        "type": "object",
                        "required": ["question", "items"],
                        "additionalProperties": False,
                        "properties": {
                            "question": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 2000,
                            },
                            "subquestion": {"type": "string", "maxLength": 4000},
                            "items": {
                                "type": "array",
                                "items": _REVIEW_ITEM_SCHEMA,
                                "minItems": 1,
                                "maxItems": 60,
                            },
                        },
                    },
                },
            },
            handler=_tool_replace_review_screen,
        )
    )

    runtime_specs = [
        (
            "runtime_start_session",
            "Started a separate Docassemble test session",
            {"type": "object", "additionalProperties": False, "properties": {}},
            lambda context, arguments: _runtime_start(context, arguments),
        ),
        (
            "runtime_current_question",
            "Observed the current Docassemble question",
            {"type": "object", "additionalProperties": False, "properties": {}},
            lambda context, arguments: context.runtime.current_question(),
        ),
        (
            "runtime_variables",
            "Read Docassemble session variables",
            {"type": "object", "additionalProperties": False, "properties": {}},
            lambda context, arguments: context.runtime.variables(),
        ),
        (
            "runtime_apply_scenario",
            "Seeded a test scenario",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "variables": {"type": "object"},
                    "delete": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "maxItems": 40,
                    },
                },
            },
            _runtime_scenario,
        ),
        (
            "runtime_back",
            "Stepped the test session back",
            {"type": "object", "additionalProperties": False, "properties": {}},
            lambda context, arguments: context.runtime.back(),
        ),
        (
            "runtime_inspect_variable",
            "Inspected a runtime variable",
            {
                "type": "object",
                "required": ["name"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 200}
                },
            },
            lambda context, arguments: context.runtime.inspect(
                "al_weaver.inspect_variable", {"name": arguments["name"]}
            ),
        ),
        (
            "runtime_inspect_gathering_state",
            "Inspected gathering state",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "maxLength": 200},
                },
            },
            lambda context, arguments: context.runtime.inspect(
                "al_weaver.inspect_gathering_state",
                {"name": arguments["name"]} if arguments.get("name") else {},
            ),
        ),
    ]
    for name, label, schema, invoke in runtime_specs:
        register_tool(
            AgentToolSpec(
                name=name,
                risk=RISK_LOW,
                requires_runtime=True,
                description=f"{label}. Results are observed runtime facts.",
                schema=schema,
                handler=_runtime_tool(name, label, invoke),
            )
        )


_register_all()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def execute_tool(context: ToolContext, tool_call: AgentToolCall) -> AgentToolResult:
    """Run one model-requested tool against the candidate.

    Every refusal path returns a result rather than raising, so the loop can
    hand structured feedback back to the model and let it try again.
    """
    name = str(tool_call.tool or "").strip()
    allowed = available_tool_names(runtime_enabled=context.runtime_enabled)
    if name not in allowed:
        return _reject(
            name or "unknown",
            "unknown_tool",
            f"{name!r} is not an available tool. Available tools: "
            + ", ".join(allowed),
        )
    spec = TOOL_REGISTRY[name]

    arguments = tool_call.arguments
    if not isinstance(arguments, dict):
        return _reject(name, "invalid_arguments", "arguments must be a JSON object")

    schema_errors = validate_against_schema(spec.schema, arguments)
    if schema_errors:
        return _reject(
            name,
            "invalid_arguments",
            "; ".join(schema_errors[:6]),
        )

    expected = tool_call.expected_candidate_revision
    if expected and expected != context.candidate.revision:
        return _reject(
            name,
            "stale_candidate",
            "The candidate moved on since this call was planned. It is now at "
            f"revision {context.candidate.revision}.",
        )

    try:
        return spec.handler(context, arguments)
    except ToolArgumentError as exc:
        return _reject(name, "invalid_arguments", str(exc))
    except Exception as exc:  # noqa: BLE001 - never let one tool abort the loop
        return AgentToolResult(
            tool=name,
            status=TOOL_STATUS_ERROR,
            label=f"{name.replace('_', ' ')} failed",
            reason="tool_execution_failed",
            message=f"The tool could not complete: {type(exc).__name__}",
        )

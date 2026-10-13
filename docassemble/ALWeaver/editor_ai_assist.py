"""AI-assisted questions in the editor: one field, AI help, a review screen.

An author adds AI help to a field from the question's field list. That one
action writes four ordinary pieces of interview source:

* an ``objects:`` entry, ``<name>: AIAssist.using(...)``, holding the settings;
* ``docassemble.ALToolbox:ai_assist.yml`` in an ``include:`` block, which asks
  the person's permission and calls the AI service;
* a review question that shows the AI's suggestion in editable fields; and
* a line in the interview order that asks the review question right after the
  question with the field.

The runtime lives in ALToolbox (`AIAssist`), so a generated interview never
imports the Weaver. Everything here is static: it reads and writes source, and
never runs the interview or calls an AI service.

The ``objects:`` entry is the record of which field has AI help. Its settings
are literals; an entry the author has rewritten with expressions is described
as computed and left for YAML editing.
"""

from __future__ import annotations

import ast
import json
import keyword
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

AI_ASSIST_CLASS = "AIAssist"
AI_ASSIST_INCLUDE = "docassemble.ALToolbox:ai_assist.yml"

# The output each task produces, matching ALToolbox's AI_ASSIST_TASKS.
AI_ASSIST_TASKS: Dict[str, str] = {
    "rewrite": "text",
    "goal": "text",
    "summarize": "text",
    "translate": "text",
    "prompt": "text",
    "extract": "fields",
    "extract_file": "fields",
    "classify": "choice",
}

# The `.using()` keywords the editor writes, in the order it writes them.
_SETTING_ORDER = (
    "task",
    "source",
    "inputs",
    "instructions",
    "outputs",
    "choices",
    "language",
    "rubric",
    "initial_question",
    "question_limit",
    "model",
    "ask_permission",
)

# Datatypes an extracted value can be reviewed as. Each takes a text default.
REVIEW_DATATYPES = ("text", "area", "date", "number", "currency", "integer", "email")

_VARIABLE_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*|\[(?:[0-9]+|[ijklmn]|'[^'\]]*'|\"[^\"\]]*\")\])*$"
)


# ---------------------------------------------------------------------------
# Reading and writing the objects entry
# ---------------------------------------------------------------------------


def parse_ai_assist_expression(expression: str) -> Optional[Dict[str, Any]]:
    """Read an ``AIAssist.using(...)`` declaration without running it.

    Returns the literal settings, plus ``computed``: the keywords whose values
    are expressions the editor cannot show as plain settings. Returns None if
    the expression does not construct an ``AIAssist``.
    """
    text = str(expression or "").strip()
    try:
        node = ast.parse(text, mode="eval").body
    except SyntaxError:
        return None
    if isinstance(node, ast.Name) and node.id == AI_ASSIST_CLASS:
        return {"settings": {}, "computed": []}
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "using"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == AI_ASSIST_CLASS
    ):
        return None
    settings: Dict[str, Any] = {}
    computed: List[str] = []
    if node.args:
        computed.append("*args")
    for item in node.keywords:
        if item.arg is None:
            computed.append("**kwargs")
            continue
        try:
            settings[item.arg] = ast.literal_eval(item.value)
        except (ValueError, SyntaxError, TypeError):
            computed.append(item.arg)
    return {"settings": settings, "computed": computed}


def _python_literal(value: Any, indent: str) -> str:
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, dict) and len(value) > 1:
        inner = indent + "  "
        rows = [
            f"{inner}{json.dumps(str(k), ensure_ascii=False)}: "
            f"{json.dumps(str(v), ensure_ascii=False)},"
            for k, v in value.items()
        ]
        return "{\n" + "\n".join(rows) + "\n" + indent + "}"
    return json.dumps(value, ensure_ascii=False)


def render_ai_assist_expression(settings: Dict[str, Any]) -> str:
    """The ``AIAssist.using(...)`` expression for these settings, one per line.

    Settings left at their runtime default are omitted, so the declaration
    reads as what the author changed.
    """
    lines = [f"{AI_ASSIST_CLASS}.using("]
    for key in _SETTING_ORDER:
        if key not in settings:
            continue
        value = settings[key]
        if value in ("", None, [], {}) and key != "task":
            continue
        if key == "ask_permission" and value is True:
            continue
        lines.append(f"  {key}={_python_literal(value, '  ')},")
    lines.append(")")
    return "\n".join(lines)


def describe_ai_assists(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every AIAssist the file declares, with its review question and outputs.

    The editor uses this to draw a field with AI help as one item and to fill
    the AI settings dialog. The review question is the one that shows
    ``<name>.suggestion(...)``; its fields are the outputs.
    """
    blocks = model.get("blocks") or []
    found: List[Dict[str, Any]] = []
    for block in blocks:
        for row in block.get("editor_objects") or []:
            if row.get("class_name") != AI_ASSIST_CLASS:
                continue
            parsed = parse_ai_assist_expression(
                str(row.get("raw_expression") or row.get("expression") or "")
            )
            if parsed is None:
                continue
            name = str(row.get("name") or "").strip()
            review = _find_review_block(blocks, name)
            settings = parsed["settings"]
            task = str(settings.get("task") or "rewrite")
            found.append(
                {
                    "name": name,
                    "objects_block_id": block.get("id"),
                    "settings": settings,
                    "computed": parsed["computed"],
                    "task": task,
                    "output_kind": AI_ASSIST_TASKS.get(task, "text"),
                    "review_block_id": review.get("id") if review else None,
                    "review_question": (
                        str((review.get("data") or {}).get("question") or "").strip()
                        if review
                        else ""
                    ),
                    "review_fields": _review_fields(review) if review else [],
                }
            )
    return found


def _find_review_block(
    blocks: Sequence[Dict[str, Any]], name: str
) -> Optional[Dict[str, Any]]:
    pattern = re.compile(r"\b" + re.escape(name) + r"\.suggestion\(")
    for block in blocks:
        if block.get("type") != "question" and "question" not in (
            block.get("data") or {}
        ):
            continue
        if pattern.search(str(block.get("yaml") or "")):
            return block
    return None


def _review_fields(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The variable, label, datatype and choices of each review field."""
    fields = (block.get("data") or {}).get("fields")
    if isinstance(fields, dict):
        fields = [fields]
    out: List[Dict[str, Any]] = []
    for item in fields if isinstance(fields, list) else []:
        if not isinstance(item, dict):
            continue
        variable = item.get("field")
        label = item.get("label")
        if variable is None:
            for key, value in item.items():
                if key in _FIELD_MODIFIERS or not isinstance(value, str):
                    continue
                variable, label = value, ("" if key == "no label" else key)
                break
        if not variable:
            continue
        choices = []
        for choice in item.get("choices") or []:
            if isinstance(choice, dict) and len(choice) == 1:
                ((choice_label, choice_value),) = choice.items()
                choices.append({"label": str(choice_label), "value": str(choice_value)})
            elif isinstance(choice, str):
                choices.append({"label": choice, "value": choice})
        out.append(
            {
                "variable": str(variable),
                "label": str(label or ""),
                "datatype": str(item.get("datatype") or "text"),
                "choices": choices,
            }
        )
    return out


_FIELD_MODIFIERS = {
    "datatype",
    "input type",
    "default",
    "required",
    "choices",
    "show if",
    "hide if",
    "help",
    "hint",
    "rows",
    "label",
    "field",
    "under text",
    "maxlength",
    "minlength",
    "validate",
    "code",
}


# ---------------------------------------------------------------------------
# Validating what the dialog sent
# ---------------------------------------------------------------------------


def _is_variable(text: str) -> bool:
    head = text.split(".", 1)[0].split("[", 1)[0]
    return bool(_VARIABLE_RE.match(text)) and not keyword.iskeyword(head)


def _require_variable(text: Any, what: str) -> str:
    value = str(text or "").strip()
    if not value:
        raise ValueError(f"Enter a variable name for {what}")
    if not _is_variable(value):
        raise ValueError(
            f"{value!r} is not a variable name docassemble can use for {what}"
        )
    return value


def normalize_ai_assist_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Check the dialog's settings and turn them into what gets written.

    Returns ``settings`` (the ``.using()`` keywords), ``outputs`` (the review
    fields) and ``review_question``.
    """
    task = str(config.get("task") or "").strip()
    if task not in AI_ASSIST_TASKS:
        raise ValueError("Choose the kind of AI help")
    kind = AI_ASSIST_TASKS[task]
    source = _require_variable(config.get("source"), "the answer AI reads")
    settings: Dict[str, Any] = {"task": task, "source": source}

    instructions = str(config.get("instructions") or "").strip()
    if task == "prompt" and not instructions:
        raise ValueError("Write the prompt: what AI should do with the answer")
    settings["instructions"] = instructions

    inputs = []
    for raw in config.get("inputs") or []:
        name = _require_variable(raw, "another answer to send")
        if name != source and name not in inputs:
            inputs.append(name)
    settings["inputs"] = inputs

    outputs: List[Dict[str, Any]] = []
    if kind == "fields":
        described: Dict[str, str] = {}
        for row in config.get("outputs") or []:
            if not isinstance(row, dict):
                continue
            variable = _require_variable(row.get("variable"), "an extracted answer")
            if variable in described or variable == source:
                raise ValueError(f"{variable} is listed twice")
            label = str(row.get("label") or "").strip() or variable
            datatype = str(row.get("datatype") or "text").strip()
            if datatype not in REVIEW_DATATYPES:
                raise ValueError(f"{datatype!r} is not a type AI can fill in")
            described[variable] = str(row.get("description") or "").strip() or label
            outputs.append({"variable": variable, "label": label, "datatype": datatype})
        if not outputs:
            raise ValueError("Add at least one answer for AI to find")
        settings["outputs"] = described
    else:
        output = _require_variable(config.get("output"), "the reviewed answer")
        if output == source:
            raise ValueError(
                "The reviewed answer needs its own variable, so the person's "
                "original answer is kept"
            )
        if kind == "choice":
            choices: List[Dict[str, str]] = []
            described = {}
            for row in config.get("choices") or []:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label") or "").strip()
                value = str(row.get("value") or "").strip() or label
                if not value:
                    continue
                if value in described:
                    raise ValueError(f"The choice {value!r} is listed twice")
                described[value] = str(row.get("description") or "").strip() or label
                choices.append({"label": label or value, "value": value})
            if len(choices) < 2:
                raise ValueError("Add at least two choices for AI to pick from")
            settings["choices"] = described
            outputs.append(
                {
                    "variable": output,
                    "label": "",
                    "datatype": "radio",
                    "choices": choices,
                }
            )
        else:
            outputs.append({"variable": output, "label": "", "datatype": "area"})

    if task == "translate":
        language = str(config.get("language") or "").strip()
        if not re.match(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?$", language):
            raise ValueError("Choose the language to translate into")
        settings["language"] = language
    if task == "goal":
        settings["rubric"] = str(config.get("rubric") or "").strip()
        settings["initial_question"] = str(config.get("initial_question") or "").strip()
        try:
            limit = int(config.get("question_limit") or 3)
        except (TypeError, ValueError):
            raise ValueError("The most follow-up questions has to be a number")
        if not 1 <= limit <= 10:
            raise ValueError("Ask between 1 and 10 follow-up questions")
        settings["question_limit"] = limit
        if not settings["rubric"]:
            raise ValueError("Describe what a complete answer includes")

    model = str(config.get("model") or "").strip()
    if model and not re.match(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$", model):
        raise ValueError(f"{model!r} is not a model name")
    settings["model"] = model
    settings["ask_permission"] = config.get("ask_permission") is not False

    review_question = str(config.get("review_question") or "").strip()
    if not review_question:
        raise ValueError("Write the review screen's question")
    return {
        "settings": settings,
        "outputs": outputs,
        "review_question": review_question,
    }


# ---------------------------------------------------------------------------
# Source edits
# ---------------------------------------------------------------------------


def _yaml_scalar(text: str) -> str:
    """``text`` as a YAML scalar: plain when that reads back the same."""
    try:
        if text and yaml.safe_load(f"k: {text}") == {"k": text}:
            return text
    except yaml.YAMLError:
        pass
    return json.dumps(text, ensure_ascii=False)


def _block_scalar(key: str, text: str, indent: str) -> str:
    body = "\n".join(
        (indent + "  " + line) if line else "" for line in text.splitlines()
    )
    return f"{indent}{key}: |\n{body}"


def render_review_question(
    name: str, block_id: str, normalized: Dict[str, Any], subquestion: str = ""
) -> str:
    """The review question's YAML for a new AI field."""
    lines = [f"id: {_yaml_scalar(block_id)}"]
    lines.append(_block_scalar("question", normalized["review_question"], ""))
    lines.append(
        _block_scalar("subquestion", subquestion or f"${{ {name}.review_note() }}", "")
    )
    lines.append("fields:")
    lines.extend(_render_review_fields(name, normalized))
    return "\n".join(lines)


def _review_shape(fields: Sequence[Dict[str, Any]]) -> List[Any]:
    """What the dialog controls about the review fields, for spotting changes."""
    return [
        (
            f["variable"],
            f.get("label") or "",
            f["datatype"],
            [(c["label"], c["value"]) for c in f.get("choices") or []],
        )
        for f in fields
    ]


_REVIEW_FIELD_OWNED = {"label", "field", "datatype", "default", "choices"}


def _review_field_extras(block: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Each review field's other settings, by variable."""
    fields = (block.get("data") or {}).get("fields")
    if isinstance(fields, dict):
        fields = [fields]
    extras: Dict[str, Dict[str, Any]] = {}
    for item in fields if isinstance(fields, list) else []:
        if not isinstance(item, dict):
            continue
        variable = item.get("field")
        if variable is None:
            variable = next(
                (
                    value
                    for key, value in item.items()
                    if key not in _FIELD_MODIFIERS and isinstance(value, str)
                ),
                None,
            )
        if not isinstance(variable, str):
            continue
        extras[variable] = {
            key: value
            for key, value in item.items()
            if key in _FIELD_MODIFIERS and key not in _REVIEW_FIELD_OWNED
        }
    return extras


def _yaml_entry(key: str, value: Any, indent: str) -> List[str]:
    if isinstance(value, str) and "\n" in value:
        return _block_scalar(key, value.rstrip("\n"), indent).split("\n")
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = value if isinstance(value, str) else yaml.safe_dump(value).split("\n")[0]
        return [
            f"{indent}{key}: {_yaml_scalar(text) if isinstance(value, str) else text}"
        ]
    dumped = yaml.safe_dump(value, default_flow_style=False, sort_keys=False)
    return [f"{indent}{key}:"] + [
        indent + "  " + line for line in dumped.rstrip("\n").split("\n")
    ]


def _render_review_fields(
    name: str,
    normalized: Dict[str, Any],
    extras: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    lines: List[str] = []
    kind = AI_ASSIST_TASKS[normalized["settings"]["task"]]
    for output in normalized["outputs"]:
        variable = output["variable"]
        label = output.get("label") or ""
        if kind == "fields":
            default = f"${{ {name}.suggestion({json.dumps(variable)}) }}"
        else:
            default = f"${{ {name}.suggestion() }}"
        if label and _yaml_scalar(label) == label and ":" not in label:
            lines.append(f"  - {label}: {variable}")
        elif label:
            lines.append(f"  - label: {_yaml_scalar(label)}")
            lines.append(f"    field: {variable}")
        else:
            lines.append(f"  - no label: {variable}")
        if output["datatype"] != "text":
            lines.append(f"    datatype: {output['datatype']}")
        for choice in output.get("choices") or []:
            if choice is output["choices"][0]:
                lines.append("    choices:")
            lines.append(
                f"      - {_yaml_scalar(choice['label'])}: "
                f"{_yaml_scalar(choice['value'])}"
            )
        lines.append(f"    default: {_yaml_scalar(default)}")
        for key, value in ((extras or {}).get(variable) or {}).items():
            lines.extend(_yaml_entry(key, value, "    "))
    return lines


def _patch_top_level_keys(
    full_yaml: str, block_id: str, replacements: Dict[str, str]
) -> str:
    """Rewrite only the named top-level keys of one block.

    Every other key, comment and blank line of the block keeps its source.
    """
    from .editor_utils import _replace_document_body, _unique_block_document

    _b, start, end, body = _unique_block_document(full_yaml, block_id)
    node = yaml.compose(body)
    original = yaml.safe_load(body)
    if not isinstance(node, yaml.MappingNode) or not isinstance(original, dict):
        raise ValueError("The review question is not a mapping; edit it in YAML")
    spans = []
    for key, value in node.value:
        if getattr(key, "value", None) not in replacements:
            continue
        span_start = body.rfind("\n", 0, key.start_mark.index) + 1
        span_end = value.end_mark.index
        if body[span_end - 1 : span_end] != "\n":
            newline = body.find("\n", span_end)
            span_end = len(body) if newline == -1 else newline + 1
        spans.append((span_start, span_end, replacements[key.value]))
    edited = body
    for span_start, span_end, text in sorted(spans, reverse=True):
        ending = "\n" if edited[span_start:span_end].endswith("\n") else ""
        edited = edited[:span_start] + text + ending + edited[span_end:]
    parsed = yaml.safe_load(edited)
    expected = yaml.safe_load("\n".join(replacements.values()) + "\n")
    if not isinstance(parsed, dict) or any(
        parsed.get(key) != (original.get(key) if key not in expected else expected[key])
        for key in set(original) | set(parsed)
    ):
        raise ValueError("Could not update the review question safely; edit it in YAML")
    return _replace_document_body(full_yaml, start, end, edited)


def _order_code_lines(body: str) -> Tuple[List[str], int]:
    lines = body.split("\n")
    key_line = next(
        (i for i, text in enumerate(lines) if re.match(r"^code\s*:", text)), -1
    )
    return lines, key_line


_ORDER_STATEMENT = re.compile(r"^(\s*)(\S.*?)(\s*#.*)?$")


def _rename_order_line(
    full_yaml: str, model: Dict[str, Any], old: str, new: str
) -> str:
    """Ask for ``new`` wherever the interview order asked for ``old``."""
    from .editor_utils import _replace_document_body, _unique_block_document

    updated = full_yaml
    for block in model["blocks"]:
        if block.get("index") not in (model.get("order_blocks") or []):
            continue
        _b, start, end, body = _unique_block_document(updated, block["id"])
        lines, key_line = _order_code_lines(body)
        changed = False
        for index in range(key_line + 1, len(lines)):
            match = _ORDER_STATEMENT.match(lines[index])
            if key_line >= 0 and match and match.group(2) == old:
                lines[index] = match.group(1) + new + (match.group(3) or "")
                changed = True
        if changed:
            updated = _replace_document_body(updated, start, end, "\n".join(lines))
            model = _reparse(updated)
    return updated


def _reparse(full_yaml: str) -> Dict[str, Any]:
    from .editor_utils import parse_interview_yaml

    return parse_interview_yaml(full_yaml)


def _objects_entry_ranges(body: str) -> Dict[str, Tuple[int, int, int, int]]:
    """Where each ``objects:`` entry sits in a block's source.

    Maps each name to ``(line start, key start, value end, entry end)``:
    the entry's line, its key, the end of its value, and where the next entry
    or key begins.
    """
    try:
        node = yaml.compose(body)
    except yaml.YAMLError:
        return {}
    if not isinstance(node, yaml.MappingNode):
        return {}
    objects_node = next(
        (
            value
            for key, value in node.value
            if getattr(key, "value", None) == "objects"
        ),
        None,
    )
    if objects_node is None:
        return {}
    pairs: List[Tuple[Any, Any]] = []
    if isinstance(objects_node, yaml.SequenceNode):
        for item in objects_node.value:
            if isinstance(item, yaml.MappingNode) and len(item.value) == 1:
                pairs.append(item.value[0])
    elif isinstance(objects_node, yaml.MappingNode):
        pairs = list(objects_node.value)
    ranges: Dict[str, Tuple[int, int, int, int]] = {}
    for index, (key, value) in enumerate(pairs):
        line_start = body.rfind("\n", 0, key.start_mark.index) + 1
        if index + 1 < len(pairs):
            next_key = pairs[index + 1][0]
            entry_end = body.rfind("\n", 0, next_key.start_mark.index) + 1
        else:
            entry_end = value.end_mark.index
            if not body[entry_end - 1 : entry_end] == "\n":
                newline = body.find("\n", entry_end)
                entry_end = len(body) if newline == -1 else newline + 1
        ranges[str(key.value)] = (
            line_start,
            key.start_mark.index,
            value.end_mark.index,
            entry_end,
        )
    return ranges


def _append_object_entry(body: str, name: str) -> str:
    """Add ``name: AIAssist`` after the last entry of an objects block.

    Works from the parsed entries rather than from indentation, because an
    entry written as a ``|`` scalar has lines indented deeper than its key.
    """
    ranges = _objects_entry_ranges(body)
    if not ranges:
        raise ValueError("This block has no entries to add to")
    entries = sorted(ranges.values())
    line_start, key_start, _value_end, _entry_end = entries[0]
    prefix = body[line_start:key_start]
    last_end = entries[-1][3]
    newline = "" if body[:last_end].endswith("\n") else "\n"
    edited = (
        body[:last_end]
        + newline
        + f"{prefix}{name}: {AI_ASSIST_CLASS}\n"
        + body[last_end:]
    )
    if _declared_expression(edited, name) != AI_ASSIST_CLASS:
        raise ValueError(f"Could not add {name} to this block")
    return edited


def _declared_expression(body: str, name: str) -> Optional[str]:
    from .editor_utils import _declared_objects

    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = dict(_declared_objects(data)).get(name)
    return str(value).strip() if value is not None else None


def _set_object_entry(body: str, name: str, expression: str) -> str:
    """Replace one entry's value in an objects block with a ``|`` scalar."""
    ranges = _objects_entry_ranges(body)
    if name not in ranges:
        raise ValueError(f"{name} is not declared in this block")
    _line_start, key_start, value_end, _entry_end = ranges[name]
    column = key_start - (body.rfind("\n", 0, key_start) + 1)
    original = body[key_start:value_end]
    trailing = original[len(original.rstrip("\r\n")) :]
    pad = " " * (column + 2)
    rendered = f"{name}: |\n" + "\n".join(
        pad + line for line in expression.splitlines()
    )
    edited = body[:key_start] + rendered + (trailing or "") + body[value_end:]
    if _declared_expression(edited, name) != expression.strip():
        raise ValueError(f"Could not write the settings for {name} into this block")
    return edited


def _upsert_declaration(
    full_yaml: str, model: Dict[str, Any], name: str, expression: str
) -> str:
    from .editor_utils import (
        _replace_document_body,
        _unique_block_document,
        insert_block_in_yaml,
    )

    for block in model["blocks"]:
        if any(
            str(row.get("name") or "").strip() == name
            for row in block.get("editor_objects") or []
        ):
            _b, start, end, body = _unique_block_document(
                full_yaml, block["id"], parsed_model=model
            )
            return _replace_document_body(
                full_yaml, start, end, _set_object_entry(body, name, expression)
            )

    # A new declaration joins a block that already declares AI help, or else
    # the first objects block; failing both it gets a block of its own.
    objects_blocks = [
        b
        for b in model["blocks"]
        if b.get("type") == "objects" and not (b.get("data") or {}).get("_commented")
    ]
    preferred = [
        b
        for b in objects_blocks
        if any(
            r.get("class_name") == AI_ASSIST_CLASS
            for r in b.get("editor_objects") or []
        )
    ] + objects_blocks
    for block in preferred:
        _b, start, end, body = _unique_block_document(
            full_yaml, block["id"], parsed_model=model
        )
        try:
            edited = _set_object_entry(
                _append_object_entry(body, name), name, expression
            )
        except ValueError:
            continue
        return _replace_document_body(full_yaml, start, end, edited)
    block_text = _set_object_entry(
        f"objects:\n  - {name}: {AI_ASSIST_CLASS}\n", name, expression
    )
    return insert_block_in_yaml(full_yaml, block_text, _preamble_anchor(model))


def _preamble_anchor(model: Dict[str, Any]) -> Optional[str]:
    """The last metadata or include block, which new setup blocks follow."""
    head = set(model.get("metadata_blocks") or []) | set(
        model.get("include_blocks") or []
    )
    anchor = None
    for block in model["blocks"]:
        if block.get("index") in head:
            anchor = str(block.get("id") or "") or anchor
    return anchor


def _ensure_include(full_yaml: str, model: Dict[str, Any]) -> str:
    """Add ``ai_assist.yml`` to the includes unless it is there already."""
    from .editor_utils import (
        _replace_document_body,
        _unique_block_document,
        insert_block_in_yaml,
    )

    include_blocks = [
        b
        for b in model["blocks"]
        if b.get("index") in (model.get("include_blocks") or [])
    ]
    for block in include_blocks:
        items = (block.get("data") or {}).get("include")
        items = [items] if isinstance(items, str) else items or []
        if AI_ASSIST_INCLUDE in items:
            return full_yaml
    for block in include_blocks:
        _b, start, end, body = _unique_block_document(
            full_yaml, block["id"], parsed_model=model
        )
        try:
            node = yaml.compose(body)
        except yaml.YAMLError:
            continue
        include_node = next(
            (
                value
                for key, value in getattr(node, "value", [])
                if getattr(key, "value", None) == "include"
            ),
            None,
        )
        if not isinstance(include_node, yaml.SequenceNode) or not include_node.value:
            continue
        if include_node.flow_style:
            continue
        last = include_node.value[-1]
        first_line = body.splitlines()[include_node.value[0].start_mark.line]
        dash = first_line.index("-")
        edited = (
            body[: last.end_mark.index]
            + "\n"
            + " " * dash
            + "- "
            + AI_ASSIST_INCLUDE
            + body[last.end_mark.index :]
        )
        try:
            includes = (yaml.safe_load(edited) or {}).get("include")
        except yaml.YAMLError:
            continue
        current = (block.get("data") or {}).get("include")
        if isinstance(current, list) and includes == current + [AI_ASSIST_INCLUDE]:
            return _replace_document_body(full_yaml, start, end, edited)
    anchor = None
    for block in model["blocks"]:
        if block.get("index") in (model.get("metadata_blocks") or []):
            anchor = str(block.get("id") or "") or anchor
    return insert_block_in_yaml(full_yaml, f"include:\n  - {AI_ASSIST_INCLUDE}", anchor)


def _unique_name(base: str, taken: set) -> str:
    candidate = base
    number = 2
    while candidate in taken:
        candidate = f"{base}_{number}"
        number += 1
    return candidate


def ai_assist_object_name(source: str, taken: set) -> str:
    """``incident_description`` -> ``incident_description_ai``."""
    base = re.sub(r"[^A-Za-z0-9_]+", "_", source).strip("_") or "answer"
    if base[0].isdigit():
        base = "ai_" + base
    return _unique_name(base + "_ai", taken)


def _question_variables(block: Dict[str, Any]) -> List[str]:
    """The variables a question sets, in order, for finding it in the order."""
    data = block.get("data") or {}
    names: List[str] = []
    for key in ("field", "continue button field"):
        if isinstance(data.get(key), str):
            names.append(data[key])
    fields = data.get("fields")
    if isinstance(fields, dict):
        fields = [fields]
    for item in fields if isinstance(fields, list) else []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("field"), str):
            names.append(item["field"])
            continue
        for key, value in item.items():
            if key not in _FIELD_MODIFIERS and isinstance(value, str):
                names.append(value)
                break
    return names


def insert_order_line(
    full_yaml: str, model: Dict[str, Any], after: Sequence[str], line: str
) -> Tuple[str, bool]:
    """Add ``line`` to the interview order right after the first of ``after``.

    Only a statement that is exactly one of ``after`` counts, at any depth.
    Nothing changes, and False is returned, when the order already has
    ``line`` or has none of ``after``.
    """
    from .editor_utils import _replace_document_body, _unique_block_document

    order_blocks = [
        b
        for b in model["blocks"]
        if b.get("index") in (model.get("order_blocks") or [])
    ]
    statement = re.compile(r"^(\s*)(\S.*?)\s*(#.*)?$")
    for want in after:
        for block in order_blocks:
            code = (block.get("data") or {}).get("code")
            if not isinstance(code, str):
                continue
            code_lines = code.split("\n")
            stripped = [
                (m.group(2) if (m := statement.match(text)) else "")
                for text in code_lines
            ]
            if line in stripped:
                return full_yaml, False
            if want not in stripped:
                continue
            _b, start, end, body = _unique_block_document(
                full_yaml, block["id"], parsed_model=model
            )
            position = stripped.index(want)
            indent = statement.match(code_lines[position]).group(1)  # type: ignore[union-attr]
            expected = "\n".join(
                code_lines[: position + 1]
                + [indent + line]
                + code_lines[position + 1 :]
            )
            body_lines = body.split("\n")
            # The code scalar's lines appear in the body with the YAML indent
            # in front; find this one by its text, after the `code:` key.
            key_line = next(
                (
                    i
                    for i, text in enumerate(body_lines)
                    if re.match(r"^code\s*:", text)
                ),
                None,
            )
            if key_line is None:
                continue
            seen = -1
            for index in range(key_line + 1, len(body_lines)):
                match = statement.match(body_lines[index])
                if match and match.group(2) == want:
                    seen = index
                    break
            if seen == -1:
                continue
            yaml_indent = body_lines[seen][
                : len(body_lines[seen]) - len(body_lines[seen].lstrip())
            ]
            new_lines = (
                body_lines[: seen + 1] + [yaml_indent + line] + body_lines[seen + 1 :]
            )
            edited = "\n".join(new_lines)
            try:
                if (yaml.safe_load(edited) or {}).get("code") != expected:
                    continue
            except yaml.YAMLError:
                continue
            return _replace_document_body(full_yaml, start, end, edited), True
    return full_yaml, False


def apply_ai_assist(
    full_yaml: str,
    config: Dict[str, Any],
    *,
    name: Optional[str] = None,
    question_block_id: Optional[str] = None,
    add_to_order: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """Write or update one field's AI help. Returns the source and a summary.

    ``name`` is the existing ``AIAssist`` to change; without it a new one is
    named after the source variable. ``question_block_id`` is the question
    with the field, which the review question follows.
    """
    from .editor_utils import (
        insert_block_in_yaml,
        parse_interview_yaml,
        update_block_in_yaml,
    )

    normalized = normalize_ai_assist_config(config)
    settings = normalized["settings"]
    model = parse_interview_yaml(full_yaml)
    existing = {a["name"]: a for a in describe_ai_assists(model)}
    if name and name not in existing:
        raise ValueError(f"{name} is not AI help in this file")
    if name and existing[name]["computed"]:
        raise ValueError(
            f"{name} uses expressions for "
            + ", ".join(existing[name]["computed"])
            + "; edit it in YAML"
        )
    declared = {
        str(row.get("name") or "").strip()
        for block in model["blocks"]
        for row in block.get("editor_objects") or []
    }
    if not name:
        name = ai_assist_object_name(settings["source"], declared)

    updated = _upsert_declaration(
        full_yaml, model, name, render_ai_assist_expression(settings)
    )
    updated = _ensure_include(updated, parse_interview_yaml(updated))
    model = parse_interview_yaml(updated)

    review = _find_review_block(model["blocks"], name)
    review_block_id: Optional[str]
    if review is None:
        ids = {str(b.get("id") or "") for b in model["blocks"]}
        review_block_id = _unique_name(
            "review " + normalized["outputs"][0]["variable"], ids
        )
        anchor = question_block_id if question_block_id in ids else None
        if anchor is None:
            anchor = str(model["blocks"][-1]["id"]) if model["blocks"] else None
        updated = insert_block_in_yaml(
            updated, render_review_question(name, review_block_id, normalized), anchor
        )
    else:
        review_block_id = str(review.get("id"))
        data = review.get("data") or {}
        current_fields = _review_fields(review)
        replacements: Dict[str, str] = {}
        if str(data.get("question") or "").strip() != normalized["review_question"]:
            replacements["question"] = _block_scalar(
                "question", normalized["review_question"], ""
            )
        if _review_shape(current_fields) != _review_shape(normalized["outputs"]):
            # Settings the author added to a review field, such as `required`
            # or `help`, stay with its variable.
            replacements["fields"] = "fields:\n" + "\n".join(
                _render_review_fields(name, normalized, _review_field_extras(review))
            )
        if replacements:
            updated = _patch_top_level_keys(updated, review_block_id, replacements)
        old_output = current_fields[0]["variable"] if current_fields else ""
        new_output = normalized["outputs"][0]["variable"]
        if old_output and old_output != new_output:
            updated = _rename_order_line(
                updated, parse_interview_yaml(updated), old_output, new_output
            )
    model = parse_interview_yaml(updated)

    placed = False
    if add_to_order:
        question = next(
            (b for b in model["blocks"] if b.get("id") == question_block_id), None
        )
        after = [settings["source"]]
        if question is not None:
            after += [v for v in _question_variables(question) if v not in after]
        updated, placed = insert_order_line(
            updated, model, after, normalized["outputs"][0]["variable"]
        )
    return updated, {
        "name": name,
        "review_block_id": review_block_id,
        "added_to_order": placed,
    }


def _order_code_parses(body_lines: List[str]) -> bool:
    try:
        code = (yaml.safe_load("\n".join(body_lines)) or {}).get("code")
        ast.parse(str(code or ""))
    except (SyntaxError, yaml.YAMLError):
        return False
    return True


def remove_ai_assist(full_yaml: str, name: str) -> str:
    """Take AI help off a field: its declaration, review question and order line.

    The field itself, and the include, stay.
    """
    from .editor_utils import (
        _replace_document_body,
        _unique_block_document,
        delete_block_from_yaml,
        parse_interview_yaml,
    )

    model = parse_interview_yaml(full_yaml)
    assist = next((a for a in describe_ai_assists(model) if a["name"] == name), None)
    if assist is None:
        raise ValueError(f"{name} is not AI help in this file")
    updated = full_yaml
    review_line = (
        assist["review_fields"][0]["variable"] if assist["review_fields"] else None
    )
    # The order goes first: if it can't be fixed, nothing has been deleted.
    if review_line:
        for block in model["blocks"]:
            if block.get("index") not in (model.get("order_blocks") or []):
                continue
            _b, start, end, body = _unique_block_document(
                updated, block["id"], parsed_model=model
            )
            lines, key_line = _order_code_lines(body)
            hits = [
                index
                for index in range(key_line + 1, len(lines))
                if key_line >= 0
                and (match := _ORDER_STATEMENT.match(lines[index]))
                and match.group(2) == review_line
            ]
            if not hits:
                continue
            for index in reversed(hits):
                kept = lines[:index] + lines[index + 1 :]
                if not _order_code_parses(kept):
                    # It was the only statement in an `if` or `for`.
                    indent = _ORDER_STATEMENT.match(lines[index]).group(1)  # type: ignore[union-attr]
                    kept = lines[:index] + [indent + "pass"] + lines[index + 1 :]
                if not _order_code_parses(kept):
                    raise ValueError(
                        f"Could not take {review_line} out of the interview order; "
                        "edit the order first"
                    )
                lines = kept
            updated = _replace_document_body(updated, start, end, "\n".join(lines))
            model = parse_interview_yaml(updated)
    if assist["review_block_id"]:
        updated = delete_block_from_yaml(updated, assist["review_block_id"])
    model = parse_interview_yaml(updated)
    for block in model["blocks"]:
        if not any(
            str(row.get("name") or "").strip() == name
            for row in block.get("editor_objects") or []
        ):
            continue
        _b, start, end, body = _unique_block_document(
            updated, block["id"], parsed_model=model
        )
        ranges = _objects_entry_ranges(body)
        if name not in ranges:
            raise ValueError(f"Could not find {name} in its objects block")
        if len(ranges) == 1:
            return delete_block_from_yaml(updated, block["id"])
        line_start, _key, _value_end, entry_end = ranges[name]
        edited = body[:line_start] + body[entry_end:]
        if _declared_expression(edited, name) is not None:
            raise ValueError(f"Could not remove {name} from its objects block")
        return _replace_document_body(updated, start, end, edited)
    return updated

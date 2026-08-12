from __future__ import annotations

import json
import re
import textwrap

from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_FIELD_TYPES: List[str] = [
    "text",
    "yesno",
    "yesnomaybe",
    "radio",
    "checkboxes",
    "combobox",
    "multiselect",
    "dropdown",
    "currency",
    "number",
    "integer",
    "date",
    "time",
    "datetime",
    "email",
    "url",
    "file",
    "files",
    "camera",
    "code",
    "range",
    "area",
    "signature",
]

CHOICE_TYPES = {"radio", "checkboxes", "combobox", "multiselect", "dropdown"}


def pick_small_model_name(llms_module: Any) -> str:
    """Pick the small/default model using ALToolbox helpers when available."""
    if llms_module is None:
        return "gpt-5-nano"

    getter = getattr(llms_module, "get_default_model", None)
    if callable(getter):
        try:
            model = getter("small")
        except Exception:
            model = None
        if isinstance(model, str) and model.strip():
            return model.strip()

    getter = getattr(llms_module, "get_first_small_model", None)
    if callable(getter):
        try:
            model = getter()
        except Exception:
            model = None
        if isinstance(model, str) and model.strip():
            return model.strip()

    return "gpt-5-nano"


def _safe_text(value: Any) -> str:
    """Normalise a value that must stay on one line.

    Use this for identifiers and datatypes — anything where a newline would be
    meaningless. Prose belongs in :func:`_safe_prose`.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


_BLOCK_SCALAR_MARKER = re.compile(r"^[|>][+-]?\d*[ \t]*\n")


def _strip_block_scalar_marker(text: str) -> str:
    """Drop a YAML block-scalar indicator a generator put inside the value.

    Models routinely hand back ``"|\\n  Some text"`` for a field that Weaver is
    going to serialise as a block scalar anyway. Left alone it is emitted as
    literal text, producing a doubled ``question: |`` / ``|`` in the source.
    Weaver owns scalar style, so the stray marker is simply removed.
    """
    if not _BLOCK_SCALAR_MARKER.match(text):
        return text
    body = text.split("\n", 1)[1]
    return textwrap.dedent(body)


def _safe_prose(value: Any) -> str:
    """Normalise author-facing text without destroying its line structure.

    Question text, subquestions and field labels are Markdown. Collapsing every
    run of whitespace flattens paragraph breaks, bullet lists and indented
    blocks into one unreadable line, so only the things that are always safe to
    normalise are touched: line endings, trailing spaces on each line, runs of
    blank lines, and blank lines at either end. Leading indentation is left
    alone because Markdown gives it meaning.
    """
    if value is None:
        return ""
    text = _strip_block_scalar_marker(
        str(value).replace("\r\n", "\n").replace("\r", "\n")
    )
    lines: List[str] = []
    blank_run = 0
    for line in text.split("\n"):
        stripped = line.rstrip()
        if stripped:
            blank_run = 0
            lines.append(stripped)
            continue
        blank_run += 1
        # One blank line is a paragraph break; more than one adds nothing.
        if blank_run == 1:
            lines.append("")
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _varname_like(label: str, fallback: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "_", (label or "").strip())
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        base = fallback
    if base and base[0].isdigit():
        base = "field_" + base
    return base.lower()


def _normalize_choices(value: Any) -> List[str]:
    if isinstance(value, list):
        return [_safe_text(v) for v in value if _safe_text(v)]
    if isinstance(value, str):
        split_items = [item.strip() for item in value.split("\n") if item.strip()]
        if split_items:
            return split_items
    return []


def normalize_generated_fields(
    raw_fields: Any,
    allowed_datatypes: Optional[Iterable[str]] = None,
    preferred_count: int = 3,
    hard_max: int = 7,
) -> List[Dict[str, Any]]:
    allowed = [
        d
        for d in (allowed_datatypes or DEFAULT_FIELD_TYPES)
        if isinstance(d, str) and d.strip()
    ]
    if not allowed:
        allowed = list(DEFAULT_FIELD_TYPES)
    allowed_set = {d.lower(): d for d in allowed}

    if not isinstance(raw_fields, list):
        return []

    normalized: List[Dict[str, Any]] = []
    seen_var = set()

    for idx, item in enumerate(raw_fields):
        if len(normalized) >= hard_max:
            break
        if not isinstance(item, dict):
            continue

        label = _safe_prose(
            item.get("label")
            or item.get("question")
            or item.get("name")
            or f"Field {idx + 1}"
        )
        variable = _safe_text(
            item.get("variable")
            or item.get("field")
            or _varname_like(label, f"field_{idx + 1}")
        )
        datatype_raw = _safe_text(
            item.get("datatype") or item.get("type") or "text"
        ).lower()
        datatype = allowed_set.get(datatype_raw, "text")

        if not label:
            label = f"Field {idx + 1}"
        if not variable:
            variable = f"field_{idx + 1}"
        if variable in seen_var:
            suffix = 2
            base = variable
            while f"{base}_{suffix}" in seen_var:
                suffix += 1
            variable = f"{base}_{suffix}"
        seen_var.add(variable)

        row: Dict[str, Any] = {
            "label": label,
            "field": variable,
            "datatype": datatype,
        }

        if datatype in CHOICE_TYPES:
            choices = _normalize_choices(item.get("choices"))
            if choices:
                row["choices"] = choices

        normalized.append(row)

    if len(normalized) > preferred_count:
        # Keep at most 3 by default unless caller explicitly provided fewer than or equal to hard max existing fields.
        normalized = normalized[:hard_max]

    return normalized


def normalize_generated_screen(
    raw_screen: Any,
    allowed_datatypes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    if not isinstance(raw_screen, dict):
        raw_screen = {}

    fields = normalize_generated_fields(
        raw_screen.get("fields", []), allowed_datatypes=allowed_datatypes
    )
    if len(fields) > 7:
        fields = fields[:7]

    question = (
        _safe_prose(raw_screen.get("question"))
        or "Please answer the following questions."
    )
    subquestion = _safe_prose(raw_screen.get("subquestion"))

    continue_button_field = _safe_text(raw_screen.get("continue_button_field"))
    # A Docassemble question is completed either by its input fields or by a
    # continue button field. Combining both makes the generated screen define
    # an unrelated completion variable (models commonly return a generic
    # ``continue`` here) and can create collisions elsewhere in the interview.
    if fields:
        continue_button_field = ""

    return {
        "question": question,
        "subquestion": subquestion,
        "fields": fields,
        "continue_button_field": continue_button_field,
    }


def validate_yaml_with_dayamlchecker(
    yaml_text: str,
) -> Tuple[bool, str]:
    """Validate YAML content using DAYamlChecker's Python API."""
    from dayamlchecker.yaml_structure import find_errors_from_string

    errors = find_errors_from_string(yaml_text)
    if not errors:
        return True, ""
    details = "\n".join(
        str(getattr(error, "err_str", "") or error).strip() for error in errors
    )
    return False, details or "DAYamlChecker validation failed"

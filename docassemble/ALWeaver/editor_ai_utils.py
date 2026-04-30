from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
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

    try:
        getter = getattr(llms_module, "get_default_model", None)
        if callable(getter):
            model = getter("small")
            if isinstance(model, str) and model.strip():
                return model.strip()
    except Exception:
        pass

    try:
        getter = getattr(llms_module, "get_first_small_model", None)
        if callable(getter):
            model = getter()
            if isinstance(model, str) and model.strip():
                return model.strip()
    except Exception:
        pass

    return "gpt-5-nano"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


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

        label = _safe_text(
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
        _safe_text(raw_screen.get("question"))
        or "Please answer the following questions."
    )
    subquestion = _safe_text(raw_screen.get("subquestion"))

    continue_button_field = _safe_text(raw_screen.get("continue_button_field"))
    if not continue_button_field and fields:
        continue_button_field = _safe_text(fields[0].get("field"))

    return {
        "question": question,
        "subquestion": subquestion,
        "fields": fields,
        "continue_button_field": continue_button_field,
    }


def validate_yaml_with_dayamlchecker(
    yaml_text: str,
    checker_module: str = "dayamlchecker",
) -> Tuple[bool, str]:
    """Validate YAML content via DAYamlChecker CLI module."""
    temp_path: Optional[Path] = None
    try:
        fd, raw_path = tempfile.mkstemp(suffix=".yml")
        temp_path = Path(raw_path)
        with open(fd, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(yaml_text)
        result = subprocess.run(
            [sys.executable, "-m", checker_module, str(temp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True, (result.stdout or "").strip()
        combined = "\n".join(
            part for part in [result.stdout, result.stderr] if part
        ).strip()
        return False, combined or "DAYamlChecker validation failed"
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

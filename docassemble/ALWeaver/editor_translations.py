"""Weaver adapters for ALDashboard's translation workflow.

Extraction, translation, stable-value protection and validation belong to the
Dashboard. This module only connects its results to editor source and reports.
"""

import re
from copy import deepcopy

import yaml

from .review_screen_sync import ALDashboardUnavailable


def language_code(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*", value):
        raise ValueError("Enter a language code such as es, fr, or pt-BR.")
    return value


def language_codes(value):
    """Accept Dashboard's whitespace-separated input or an API list."""
    if isinstance(value, str):
        value = value.split()
    if not isinstance(value, list) or not value:
        raise ValueError("Enter at least one language code, one per line.")
    if not all(isinstance(item, str) for item in value):
        raise ValueError("Language codes must be text.")
    return list(dict.fromkeys(language_code(item) for item in value))


def dashboard_translation(interview_path, language, use_gpt=False):
    try:
        from docassemble.ALDashboard.api_dashboard_utils import (
            translation_payload_from_options,
        )
    except ImportError as exc:
        raise ALDashboardUnavailable(
            "Install or update ALDashboard to use interview translations."
        ) from exc
    # Background report jobs have no interview session. DAFile's private-file
    # lookup needs a session key even while producing a download-only workbook.
    from docassemble.base.functions import get_uid, set_uid
    import uuid

    original_uid = get_uid()
    if original_uid is None:
        set_uid(uuid.uuid4().hex)
    try:
        return translation_payload_from_options(
            {
                "interview_path": interview_path,
                "tr_langs": language_codes(language),
                "use_gpt": use_gpt,
                "include_xlsx_base64": True,
            }
        )
    finally:
        set_uid(original_uid)


def validate_workbook(content, filename):
    try:
        from docassemble.ALDashboard.api_dashboard_utils import (
            validate_translation_payload_from_options,
        )
    except ImportError as exc:
        raise ALDashboardUnavailable(
            "Install or update ALDashboard to validate translations."
        ) from exc
    result = validate_translation_payload_from_options(
        {
            "filename": filename,
            "file_content_base64": content,
        }
    )
    if result.get("errors"):
        raise ValueError(
            "Translation workbook has errors: "
            + "; ".join(str(item["message"]) for item in result["errors"][:5])
        )
    return result


def add_translation_reference(source, filename):
    """Append a separate declaration without rewriting any author-owned YAML."""
    for document in yaml.safe_load_all(source):
        if isinstance(document, dict) and filename in (
            document.get("translations") or []
        ):
            return source
    return (
        source
        + ("\n" if not source.endswith("\n") else "")
        + "---\ntranslations:\n  - "
        + filename
        + "\n"
    )


def localize_report(scan, interview_path, language):
    """Use Dashboard's cached translations, never make AI calls for reports."""
    import base64
    import io
    import pandas as pd

    language = language_code(language)
    generated = dashboard_translation(interview_path, language)
    table = pd.read_excel(
        io.BytesIO(base64.b64decode(generated["translations"][0]["xlsx_base64"])),
        keep_default_na=False,
        usecols="A:H",
    )
    translations = {
        str(row.orig_text): str(row.tr_text)
        for row in table.itertuples()
        if str(row.tr_lang) == language and str(row.tr_text)
    }
    result = deepcopy(scan)
    # Only display-bearing properties are localized. Python, variable names,
    # choice values, actions, ids, and source identity remain untouched.
    text_keys = {
        "question",
        "subquestion",
        "under",
        "help",
        "hint",
        "note",
        "html",
        "label",
        "continue button label",
        "back button label",
        "resume button label",
        "content",
        "subject",
        "terms",
        "auto terms",
        "sections",
    }

    def text(value):
        if isinstance(value, str):
            return translations.get(value, value)
        if isinstance(value, dict):
            return {key: text(item) for key, item in value.items()}
        if isinstance(value, list):
            return [text(item) for item in value]
        return value

    def display(data):
        if not isinstance(data, dict):
            return data
        out = deepcopy(data)
        for key, value in data.items():
            if key in text_keys:
                out[key] = text(value)
            elif key == "fields" and isinstance(value, list):
                out[key] = []
                from .interview_scan import FIELD_OPTIONS

                for field in value:
                    if not isinstance(field, dict):
                        out[key].append(field)
                        continue
                    translated = display(field)
                    out[key].append(
                        {
                            translations.get(k, k) if k not in FIELD_OPTIONS else k: v
                            for k, v in translated.items()
                        }
                    )
            elif key in {"choices", "buttons"} and isinstance(value, list):
                out[key] = [
                    (
                        translations.get(item, item)
                        if isinstance(item, str)
                        else (
                            {translations.get(k, k): v for k, v in item.items()}
                            if isinstance(item, dict)
                            else item
                        )
                    )
                    for item in value
                ]
        return out

    selected = [
        block
        for block in result["blocks"]
        if (block.get("data") or {}).get("language") == language
    ]
    selected_definitions = {
        tuple(sorted(block.get("defines") or []))
        for block in selected
        if block.get("defines")
    }
    selected_ids = {
        (block.get("sourceFile"), (block.get("data") or {}).get("id"))
        for block in selected
        if (block.get("data") or {}).get("id")
    }
    result["blocks"] = [
        block
        for block in result["blocks"]
        if (block.get("data") or {}).get("language", "*") in ("*", "en", language)
        and (
            block in selected
            or not (
                tuple(sorted(block.get("defines") or [])) in selected_definitions
                or (block.get("sourceFile"), (block.get("data") or {}).get("id"))
                in selected_ids
            )
        )
    ]
    for block in result["blocks"]:
        block["data"] = display(block.get("data") or {})
        for key in ("title", "report_title"):
            if key in block:
                block[key] = translations.get(block[key], block[key])
    result["translations"] = translations
    result["language"] = language
    # Use Docassemble's installed UI translations for standard controls too.
    from docassemble.base.functions import word, word_collection

    result["language_labels"] = {
        label: word(label, language=language)
        for label in (
            "Continue",
            "Next",
            "Undo",
            "Back",
            "Yes",
            "No",
            "I don't know",
            "I am not sure",
        )
    }
    result["language_labels"].update(word_collection.get(language, {}))
    result["language_labels"]["I don’t know"] = result["language_labels"][
        "I don't know"
    ]
    remaining = generated["translations"][0].get("untranslated_segments", 0)
    if remaining:
        result["warnings"].append(
            f"{remaining} untranslated segments use their original language. This is a simulated report, not a runtime language verification."
        )
    return result

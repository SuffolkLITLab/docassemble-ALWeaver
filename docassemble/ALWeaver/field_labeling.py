"""Reviewable ALDashboard labeling and field identity tracking.

Original templates are never edited. A proposal is a separate file plus a map;
callers must obtain the author's choice before generating or applying it.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List


class LabelingError(ValueError):
    """Labeling was unavailable or could not preserve field identities."""


MAX_LABELING_BYTES = 10 * 1024 * 1024


def settable_reference(name: str) -> str:
    """Keep exact scalar components, translating known display methods only."""
    from .interview_generator import substitute_suffix
    from .generator_constants import generator_constants

    name = substitute_suffix(
        name, generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX
    )
    name = re.sub(r"\.name\.full\(\)$", ".name.first", name)
    if re.fullmatch(r"\w+\[\d+\]", name):
        name += ".name.first"
    return name


def template_fields(path: str) -> List[Dict[str, str]]:
    if path.lower().endswith(".pdf"):
        import pikepdf

        result = []
        with pikepdf.open(path) as pdf:
            pages = {page.obj.objgen: index for index, page in enumerate(pdf.pages)}

            def layout(node):
                page = node.get("/P")
                return (
                    pages.get(page.objgen) if page is not None else None,
                    tuple(float(n) for n in node.get("/Rect", [])),
                )

            def visit(nodes, prefix="", inherited_type=""):
                for node in nodes:
                    name = str(node.get("/T", ""))
                    full = ".".join(filter(None, (prefix, name)))
                    kind = str(node.get("/FT", inherited_type))
                    if kind == "/Btn" and int(node.get("/Ff", 0)) & 65536:
                        continue
                    children = node.get("/Kids", [])
                    if children and any("/T" in child for child in children):
                        visit(children, full, kind)
                    elif full:
                        result.append(
                            {
                                "name": full,
                                "type": kind,
                                "layout": repr(
                                    (
                                        layout(node),
                                        [layout(child) for child in children],
                                    )
                                ),
                            }
                        )

            form: Any = pdf.Root.get("/AcroForm", {})
            visit(form.get("/Fields", []))
        return result
    if path.lower().endswith(".docx"):
        from .interview_generator import (
            docx_template_text,
            _raw_variables_from_template,
        )

        return [
            {"name": name, "type": "jinja"}
            for name in _raw_variables_from_template(docx_template_text(path))
        ]
    raise LabelingError("Only PDF and DOCX templates can be labeled.")


def assess_template(path: str) -> Dict[str, Any]:
    from .generator_constants import generator_constants
    from .editor_agent_rename import validate_variable_reference

    fields = template_fields(path)
    pdf = path.lower().endswith(".pdf")
    issues = []
    if not fields:
        issues.append(
            {
                "field": "",
                "code": "unlabeled",
                "message": "No fillable fields or template variables were found.",
            }
        )
    prefixes = generator_constants.RESERVED_PREFIXES
    for field in fields:
        name = field["name"]
        reasons = []
        if re.search(r"\s", name):
            reasons.append(("spaces", "The field name contains spaces."))
        if name != name.lower():
            reasons.append(("mixed_case", "The field name uses uppercase letters."))
        # Object paths are expected in Word templates, but PDF labels use underscores.
        if pdf and any(char in name for char in "[]."):
            reasons.append(
                (
                    "pdf_object_path",
                    "PDF labels should use underscores instead of brackets or dots.",
                )
            )
        if not pdf and validate_variable_reference(settable_reference(name)):
            reasons.append(
                ("invalid_reference", "This is not an assignable template variable.")
            )
        if (
            not any(
                re.match(r"^" + re.escape(prefix) + r"(?:\d|_|\[|\.|$)", name)
                for prefix in prefixes
            )
            and name not in generator_constants.RESERVED_WHOLE_WORDS
        ):
            reasons.append(
                (
                    "unrecognized_noun",
                    "This name does not match an expected AssemblyLine noun; it may be a valid custom field.",
                )
            )
        if (
            pdf
            and re.search(r"(?:^|[_.])signature(?:__\d+)?$", name, re.I)
            and field["type"] != "/Sig"
        ):
            reasons.append(
                (
                    "signature_type",
                    "This field is labeled as a signature but is not a PDF signature field. Review its type in a PDF editor; renaming alone will not fix it.",
                )
            )
        issues.extend(
            {"field": name, "code": code, "message": message}
            for code, message in reasons
        )
    return {
        "filename": os.path.basename(path),
        "fields": fields,
        "issues": issues,
        "suggest_labeling": any(issue["code"] != "signature_type" for issue in issues),
    }


def propose_labels(path: str, output_path: str) -> Dict[str, Any]:
    """Ask ALDashboard to label a copy, retaining a verified old/new map."""
    if os.path.getsize(path) > MAX_LABELING_BYTES:
        raise LabelingError(
            "AI labeling supports templates up to 10 MiB. Keep this original or use a smaller copy."
        )
    before = template_fields(path)
    old = [item["name"] for item in before]
    mappings = []
    try:
        if path.lower().endswith(".pdf"):
            from docassemble.ALDashboard.pdf_field_labeler import (
                relabel_existing_pdf_fields,
                detect_pdf_fields_and_optionally_relabel,
            )

            if old:
                stats = relabel_existing_pdf_fields(
                    input_pdf_path=path,
                    output_pdf_path=output_path,
                    relabel_with_ai=True,
                )
                source_names = stats.get("fields_old", [])
                targets = stats.get("fields", [])
                if set(source_names) != set(old) or len(targets) != len(source_names):
                    raise LabelingError(
                        "The labeler did not return a complete field mapping."
                    )
                # AcroForm traversal retains field identity across renames;
                # Dashboard's page-sorted statistics can change order when a
                # name supplies a missing page hint.
                after_fields = template_fields(output_path)
                if len(before) != len(after_fields) or any(
                    (a["type"], a["layout"]) != (b["type"], b["layout"])
                    for a, b in zip(before, after_fields)
                ):
                    raise LabelingError(
                        "The labeler changed the PDF field structure. Review it manually."
                    )
                mappings = [
                    {"old_name": a, "new_name": b}
                    for a, b in zip(old, [item["name"] for item in after_fields])
                ]
            else:
                detect_pdf_fields_and_optionally_relabel(
                    input_pdf_path=path,
                    output_pdf_path=output_path,
                    relabel_with_ai=True,
                )
        else:
            from docassemble.ALDashboard.docx_wrangling import (
                get_labeled_docx_runs,
                update_docx,
                get_docx_run_text,
                defragment_docx_runs,
                validate_docx_template_syntax,
            )
            from .interview_generator import _raw_variables_from_template
            import docx

            edits = get_labeled_docx_runs(
                path,
                defragment_runs=True,
                additional_instructions=(
                    "Correct existing variable names as well as unlabeled blanks. Use AssemblyLine object paths. "
                    "Keep existing fields in the same run and order so their identities can be tracked."
                ),
            )
            original, _ = defragment_docx_runs(docx.Document(path))
            for paragraph, run, replacement, insertion in edits:
                if insertion:
                    continue
                previous = get_docx_run_text(original, paragraph, run)
                sources = _raw_variables_from_template(previous)
                targets = _raw_variables_from_template(replacement)
                if sources and len(sources) != len(targets):
                    raise LabelingError(
                        "A Word edit changes field identities ambiguously. Review the template manually."
                    )
                mappings.extend(
                    {"old_name": a, "new_name": b} for a, b in zip(sources, targets)
                )
            updated_document = update_docx(path, edits, defragment_runs=True)
            updated_document, _ = defragment_docx_runs(updated_document)
            if validate_docx_template_syntax(updated_document).get("errors"):
                raise LabelingError(
                    "The proposed Word labels have invalid template syntax. Keep the original and review the suggestions manually."
                )
            updated_document.save(output_path)
    except ImportError as exc:
        raise LabelingError(
            "ALDashboard's field labeling modules are unavailable. Install or update ALDashboard, or keep the original labels."
        ) from exc
    except LabelingError:
        raise
    except Exception as exc:
        raise LabelingError(
            "ALDashboard could not label this document. The original is unchanged; keep its labels or try again."
        ) from exc
    if os.path.getsize(output_path) > MAX_LABELING_BYTES:
        raise LabelingError(
            "The labeled copy exceeds the 10 MiB labeling limit. Keep the original."
        )
    after = template_fields(output_path)
    new = [item["name"] for item in after]
    mapping: Dict[str, str] = {}
    for item in mappings:
        source, target = item["old_name"], item["new_name"]
        if source in mapping and mapping[source] != target:
            if path.lower().endswith(".pdf") and re.sub(
                r"__\d+$", "", mapping[source]
            ) == re.sub(r"__\d+$", "", target):
                continue
            raise LabelingError(
                f"Conflicting labels were proposed for {source}. Radio groups and repeated widgets must retain one answer identity."
            )
        mapping[source] = target
    for name in old:
        if name not in mapping and name in new:
            mapping[name] = name
    unresolved = [
        name for name in old if name not in mapping or mapping[name] not in new
    ]
    if unresolved:
        raise LabelingError("Fields could not be tracked: " + ", ".join(unresolved))
    if any(source != target and source in new for source, target in mapping.items()):
        raise LabelingError(
            "Some renamed fields still occur under their old names. Review all occurrences before applying."
        )
    if len(set(mapping.values())) != len(mapping):
        raise LabelingError(
            "The proposed labels would merge distinct fields. Review them manually."
        )
    from .editor_agent_rename import validate_variable_reference
    from .interview_generator import map_raw_to_final_display

    destinations = [
        map_raw_to_final_display(name) if path.lower().endswith(".pdf") else name
        for name in new
    ]
    checked_names = (
        new
        if path.lower().endswith(".pdf")
        else [settable_reference(name) for name in destinations]
    )
    if any(validate_variable_reference(name) for name in checked_names):
        raise LabelingError(
            "Some proposed labels are not valid variable names. Review the template manually."
        )
    if len(set(destinations)) != len({re.sub(r"__\d+$", "", name) for name in new}):
        raise LabelingError(
            "Distinct labels would map to the same interview answer. Review them manually."
        )
    if not new:
        raise LabelingError(
            "No fields were found by the labeler. Keep the original and add fields manually."
        )
    return {
        "mappings": [{"old_name": a, "new_name": b} for a, b in mapping.items()],
        "added_fields": [name for name in new if name not in mapping.values()],
        "assessment": assess_template(output_path),
    }


def attached_template_names(source: str) -> List[str]:
    """Literal template filenames the Assistant can inspect in this interview."""
    from .source_document import parse_source_document

    names = []
    for block in parse_source_document("interview.yml", source).documents:
        data = block.parsed_value
        if not isinstance(data, dict):
            continue
        attachments = data.get("attachments", data.get("attachment", []))
        if isinstance(attachments, dict):
            attachments = [attachments]
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            for key in ("pdf template file", "docx template file"):
                name = attachment.get(key)
                if isinstance(name, str) and name not in names:
                    names.append(name)
    return names

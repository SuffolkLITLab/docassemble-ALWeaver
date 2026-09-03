"""Draft a starter DOCX template from an interview's own questions.

Authors are told to build the output document first and automate it second,
which is backwards for an intake: the questions are the point, and the document
is just a record of the answers (SuffolkLITLab/docassemble-ALWeaver#819, and the
generic-template request in #498).

ALDashboard already does this under "Generate variable report" / its Interview
Intake Document Generator, walking the YAML and writing a DOCX whose Jinja
fields line up with the variables the interview gathers. This module imports
that at runtime -- the Dashboard is an optional dependency, as it is for the
review screen generator and the linter -- and drops the result straight into the
project's templates folder, where the Weaver's document setup can pick it up.

The Dashboard can also arrange those same variables into a court filing rather
than a list of fields (ALDashboard#272, and the "generic court form output
document" ask in #498). A jurisdiction profile there supplies the caption,
running footer, signature block and certificate of service; the interview's
screens become the middle of the document. This module exposes that as the
``shape`` argument and asks the Dashboard which shapes and profiles a given
server actually has, because the answer depends on which ALDashboard is
installed -- an older one has none of this, and the Weaver has to keep working
against it.

Every shape is drafted twice by the Dashboard: once as the DOCX, and once as a
Mako + Markdown source that says the same thing in text. The Dashboard's own
screen saves both, and ``markdown_path`` does the same here -- a Markdown
template is the one an author can diff, and it is what an attachment's
``content file:`` wants.
"""

import os
from typing import Any, Dict, List, Optional, Sequence

from .review_screen_sync import ALDashboardUnavailable

__all__ = [
    "ALDashboardUnavailable",
    "DEFAULT_SHAPE",
    "court_form_options",
    "suggested_report_names",
    "supports_court_form_shapes",
    "write_variable_report_docx",
]

# The shape that behaves exactly as this module always has.
DEFAULT_SHAPE = "intake"


def _load_dashboard_report():
    try:
        from docassemble.ALDashboard.variable_report_generator import (  # type: ignore
            extract_interview_metadata_info,
            generate_variable_report,
        )
    except Exception as err:  # pragma: no cover - depends on the server's packages
        raise ALDashboardUnavailable(
            "Drafting a variable report needs the ALDashboard package. Install "
            "docassemble.ALDashboard on this server and try again."
        ) from err
    return extract_interview_metadata_info, generate_variable_report


def _load_dashboard_court_forms():
    """The Dashboard's court form listing helpers, or ``None`` if it predates them.

    Returning ``None`` rather than raising is deliberate: a server running an
    older ALDashboard should still be offered the intake report, just without
    the court shapes.
    """
    try:
        from docassemble.ALDashboard.variable_report_generator import (  # type: ignore
            list_court_form_profile_choices,
            list_court_form_shapes,
        )
    except Exception:  # pragma: no cover - depends on the server's packages
        return None
    return list_court_form_shapes, list_court_form_profile_choices


def supports_court_form_shapes() -> bool:
    """Whether the installed ALDashboard can draft court shapes at all."""
    return _load_dashboard_court_forms() is not None


def court_form_options() -> Dict[str, Any]:
    """The shapes and jurisdiction profiles this server can offer.

    ``supported`` is false against an ALDashboard that predates court shapes; the
    caller should then offer the intake report alone rather than a dropdown of
    choices that would fail on use.
    """
    loaded = _load_dashboard_court_forms()
    if loaded is None:
        return {"supported": False, "shapes": [], "profiles": []}
    list_shapes, list_profiles = loaded
    try:
        shapes = [
            {"value": str(item["value"]), "label": str(item["label"])}
            for item in list_shapes()
        ]
        profiles = [
            {"value": str(item["value"]), "label": str(item["label"])}
            for item in list_profiles()
        ]
    except Exception:  # pragma: no cover - a malformed profile on the server
        return {"supported": False, "shapes": [], "profiles": []}
    return {"supported": True, "shapes": shapes, "profiles": profiles}


def suggested_report_names(
    yaml_texts: Sequence[str], *, primary_filename: Optional[str] = None
) -> Dict[str, str]:
    """The title and filename ALDashboard would give this interview's report."""
    extract_interview_metadata_info, _generate = _load_dashboard_report()
    info = extract_interview_metadata_info(
        [str(text or "") for text in yaml_texts], primary_filename=primary_filename
    )
    return {
        "title": str(info.get("display_title") or "Interview Document Draft"),
        "filename": str(info.get("docx_filename") or "interview_document_draft.docx"),
    }


def write_variable_report_docx(
    yaml_texts: Sequence[str],
    output_path: str,
    *,
    report_title: Optional[str] = None,
    show_variable_names: bool = False,
    show_variable_types: bool = False,
    max_list_cols: Optional[int] = None,
    shape: str = DEFAULT_SHAPE,
    court_profile: Optional[str] = None,
    include_certificate_of_service: Optional[bool] = None,
    numbered_paragraphs: Optional[bool] = None,
    markdown_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the report to ``output_path`` and describe what went into it.

    ``shape`` defaults to the intake summary this has always produced. Any other
    shape -- ``court_form``, ``motion``, ``affidavit``, ``letter`` -- drafts a
    court document using the jurisdiction profile named by ``court_profile``,
    and the returned summary then also carries which profile was used and which
    template each fixed section came from.

    ``show_variable_types`` and ``max_list_cols`` shape the intake summary's
    tables and are ignored by the court shapes. ``numbered_paragraphs`` is the
    reverse -- it belongs to the court body, and leaving it ``None`` keeps
    whatever the jurisdiction profile says, which is what an author who has not
    thought about it should get.

    Passing ``markdown_path`` also writes the Mako + Markdown draft the
    Dashboard produces alongside every DOCX, and reports its size as
    ``markdown_size``. A Dashboard old enough to return no markdown simply
    writes no file, and the key is absent.

    Raises ``ALDashboardUnavailable`` when the Dashboard package is not
    installed, or when it is too old to draft the requested shape.
    """
    _extract, generate_variable_report = _load_dashboard_report()
    texts: List[str] = [
        str(text or "") for text in yaml_texts if str(text or "").strip()
    ]
    if not texts:
        raise ValueError("There is no YAML to draft a template from.")

    shape_name = str(shape or DEFAULT_SHAPE).strip().lower() or DEFAULT_SHAPE

    options: Dict[str, Any] = {
        "report_title": report_title,
        "show_variable_names": show_variable_names,
        "show_variable_types": show_variable_types,
        "output_docx_path": output_path,
    }
    # Left out rather than passed as None: the Dashboard's default is an int,
    # and an older one has no notion of "unset" for it.
    if max_list_cols is not None:
        options["max_list_cols"] = int(max_list_cols)
    if shape_name != DEFAULT_SHAPE:
        if not supports_court_form_shapes():
            raise ALDashboardUnavailable(
                f"Drafting a {shape_name.replace('_', ' ')} needs a newer "
                "ALDashboard. Update docassemble.ALDashboard on this server, or "
                "draft the intake report instead."
            )
        options["shape"] = shape_name
        if court_profile:
            options["court_profile"] = str(court_profile)
        if include_certificate_of_service is not None:
            options["include_certificate_of_service"] = bool(
                include_certificate_of_service
            )
        if numbered_paragraphs is not None:
            options["numbered_paragraphs"] = bool(numbered_paragraphs)

    result = generate_variable_report(texts, **options)

    summary: Dict[str, Any] = {
        "variables_count": int(result.get("variables_count") or 0),
        "list_count": int(result.get("list_count") or 0),
        "scalar_count": int(result.get("scalar_count") or 0),
        "size": os.path.getsize(output_path) if os.path.exists(output_path) else 0,
        "shape": str(result.get("shape") or shape_name),
    }
    # Only a court shape has these, and only a Dashboard new enough to report
    # them. Passing them through lets the editor say which caption it drew and
    # whether a Word-authored override replaced it.
    for key in ("profile_id", "profile_name", "sections"):
        if result.get(key):
            summary[key] = result[key]

    if markdown_path:
        markdown = str(result.get("mako_markdown") or "")
        if markdown.strip():
            with open(markdown_path, "w", encoding="utf-8") as handle:
                handle.write(markdown)
            summary["markdown_size"] = os.path.getsize(markdown_path)
    return summary

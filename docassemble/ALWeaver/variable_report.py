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
"""

import os
from typing import Any, Dict, List, Optional, Sequence

from .review_screen_sync import ALDashboardUnavailable

__all__ = [
    "ALDashboardUnavailable",
    "suggested_report_names",
    "write_variable_report_docx",
]


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
) -> Dict[str, Any]:
    """Write the report to ``output_path`` and describe what went into it.

    Raises ``ALDashboardUnavailable`` when the Dashboard package is not
    installed on this server.
    """
    _extract, generate_variable_report = _load_dashboard_report()
    texts: List[str] = [
        str(text or "") for text in yaml_texts if str(text or "").strip()
    ]
    if not texts:
        raise ValueError("There is no YAML to draft a template from.")

    result = generate_variable_report(
        texts,
        report_title=report_title,
        show_variable_names=show_variable_names,
        output_docx_path=output_path,
    )
    return {
        "variables_count": int(result.get("variables_count") or 0),
        "list_count": int(result.get("list_count") or 0),
        "scalar_count": int(result.get("scalar_count") or 0),
        "size": os.path.getsize(output_path) if os.path.exists(output_path) else 0,
    }

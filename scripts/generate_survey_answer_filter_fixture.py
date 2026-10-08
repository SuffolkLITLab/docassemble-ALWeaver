#!/usr/bin/env python3
"""Generate a disposable survey interview for the saved-answer filter smoke test."""

import argparse
import importlib.util
import json
import mimetypes
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfWriter


def _local_file_finder(reference, **kwargs):
    if not isinstance(reference, str):
        return {"fullpath": None, "mimetype": None}
    if ":" in reference:
        package, relative = reference.split(":", 1)
    else:
        package, relative = "docassemble.ALWeaver", reference
    if package == "ALWeaver":
        package = "docassemble.ALWeaver"
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        return {"fullpath": None, "mimetype": None}
    path = Path(next(iter(spec.submodule_search_locations))) / relative
    mimetype, _encoding = mimetypes.guess_type(path.name)
    return {
        "fullpath": str(path) if path.exists() else None,
        "mimetype": mimetype,
        "filename": path.name,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        help="Directory for the generated PDF, YAML, and package ZIP (default: a new /tmp directory)",
    )
    args = parser.parse_args()
    output_dir = args.output_dir or tempfile.mkdtemp(prefix="alweaver-survey-filter-")
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(output_dir, "survey.pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as pdf_file:
        writer.write(pdf_file)

    import docassemble.base.dates as da_dates
    import docassemble.base.functions as da_functions
    import docassemble.base.util as da_util
    from docassemble.base.thread_context import empty_globals, global_context

    da_functions.get_configuration = lambda: {}
    da_dates.get_configuration = lambda: {}
    da_dates.get_default_timezone = lambda: "UTC"
    da_util.file_finder = _local_file_finder

    from docassemble.ALWeaver.interview_generator import generate_interview_from_path

    globals_for_test = empty_globals()
    globals_for_test.current_question = SimpleNamespace(package="ALWeaver")
    with global_context(globals_for_test):
        result = generate_interview_from_path(
            pdf_path,
            output_dir=output_dir,
            title="Survey Answer Filter Smoke Test",
            exact_name="survey.pdf",
            create_package_zip=True,
            include_download_screen=False,
            include_next_steps=False,
            field_definitions=[
                {
                    "field": "survey_name",
                    "label": "Name for live survey check",
                    "datatype": "text",
                },
                {
                    "field": "survey_count",
                    "label": "Number for live survey check",
                    "datatype": "integer",
                },
                {
                    "field": "internal_skipped_answer",
                    "datatype": "skip",
                    "value": "'secret skipped value'",
                },
                {
                    "field": "internal_computed_answer",
                    "datatype": "code",
                    "value": "'secret computed value'",
                },
            ],
        )
    print(
        json.dumps(
            {
                "output_dir": output_dir,
                "yaml_path": result.yaml_path,
                "package_zip_path": result.package_zip_path,
            }
        )
    )


if __name__ == "__main__":
    main()

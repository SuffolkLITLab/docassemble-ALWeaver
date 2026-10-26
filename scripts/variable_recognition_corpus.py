#!/usr/bin/env python3
"""Snapshot real template recognition in a chosen checkout, without editing inputs.

Run with the Weaver virtualenv. Compare JSON outputs from the base checkout and
working checkout; inspect every changed mapping, group, datatype, or object.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["ISUNITTEST"] = "true"
    sys.path.insert(0, str(args.checkout.resolve()))
    import defusedxml.ElementTree  # type: ignore  # Initialize before NLTK imports.
    import docassemble.base.functions as functions
    from docassemble.base.thread_context import empty_globals, global_context
    from docassemble.base.util import DAStaticFile
    from docassemble.ALWeaver import interview_generator as generator

    if not Path(generator.__file__).resolve().is_relative_to(args.checkout.resolve()):
        raise RuntimeError(f"Wrong checkout imported: {generator.__file__}")
    functions.get_configuration = lambda: {}

    class LocalTemplate(DAStaticFile):
        def init(self, *pargs, **kwargs):
            self.full_path = kwargs.pop("full_path")
            kwargs["filename"] = Path(self.full_path).name
            kwargs["extension"] = Path(self.full_path).suffix[1:]
            kwargs["mimetype"] = (
                "application/pdf"
                if kwargs["extension"] == "pdf"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            super().init(*pargs, **kwargs)

        def path(self):
            return self.full_path

    paths = sorted(
        path
        for path in args.corpus.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pdf", ".docx"}
    )
    result = {
        "checkout": str(args.checkout),
        "corpus": str(args.corpus),
        "documents": {},
        "errors": {},
    }
    started = time.perf_counter()
    for index, path in enumerate(paths, 1):
        relative = str(path.relative_to(args.corpus))
        try:
            context = empty_globals()
            context.current_question = SimpleNamespace(package="docassemble.ALWeaver")
            with global_context(context):
                document = LocalTemplate(full_path=str(path))
                fields = generator.DAFieldList(
                    "fields", auto_gather=False, gathered=True
                )
                fields.add_fields_from_file(document)
                fields.auto_label_fields()
                fields.auto_mark_people_as_builtins()
                fields.consolidate_repeated_rows()
                fields.gathered = True
                interview = generator.DAInterview("interview", all_fields=fields)
                result["documents"][relative] = {
                    "fields": sorted(
                        [
                            {
                                "raw": sorted(field.raw_field_names),
                                "display": field.final_display_var,
                                "type": field.field_type,
                                "group": str(field.group),
                                "trigger": field.trigger_gather(
                                    fields.custom_people_plurals.values()
                                ),
                            }
                            for field in fields
                        ],
                        key=lambda row: (row["raw"], row["display"]),
                    ),
                    "objects": sorted(
                        [
                            {
                                "name": spec.name,
                                "type": spec.type,
                                "params": {
                                    key: str(value)
                                    for key, value in spec.params.items()
                                },
                            }
                            for spec in interview._guess_objects_list()
                        ],
                        key=lambda row: row["name"],
                    ),
                }
        except Exception as exc:
            result["errors"][relative] = f"{type(exc).__name__}: {exc}"
        if index % 25 == 0:
            print(f"{index}/{len(paths)} documents", flush=True)
    result["elapsed_seconds"] = time.perf_counter() - started
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "documents": len(result["documents"]),
                "errors": len(result["errors"]),
                "seconds": result["elapsed_seconds"],
            }
        ),
        flush=True,
    )

    if not result["documents"]:
        raise SystemExit(
            "No documents were successfully inspected; see the errors in the snapshot"
        )


if __name__ == "__main__":
    main()

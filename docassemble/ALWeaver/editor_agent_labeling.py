"""Server-bound template access and staged Assistant labeling proposals."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
import tempfile
import uuid

from .field_labeling import (
    LabelingError,
    assess_template,
    propose_labels,
    attached_template_names,
)


def template_directory(user_id: int, project: str):
    from .docassemble_compat import create_saved_file

    area = create_saved_file(user_id, fix=True, section="playgroundtemplate")
    directory = (
        Path(area.directory) if project == "default" else Path(area.directory) / project
    )
    return area, directory


def read_template(context, name: str) -> bytes:
    if (
        not name
        or os.path.basename(name) != name
        or not name.lower().endswith((".pdf", ".docx"))
    ):
        raise LabelingError(
            "Choose a PDF or DOCX filename from this project's attachments."
        )
    _, directory = template_directory(context.storage_user_id, context.project)
    path = directory / name
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 50 * 1024 * 1024
    ):
        raise LabelingError(
            f"Template {name!r} is missing or too large to label. Use an exact template filename from the interview: {attached_template_names(context.candidate.raw_source)}"
        )
    return path.read_bytes()


def inspect_template(context, name):
    with tempfile.TemporaryDirectory(prefix="weaver-label-") as directory:
        path = Path(directory) / name
        content = read_template(context, name)
        path.write_bytes(content)
        return assess_template(str(path))


def stage_relabel(context, name):
    from .field_remapping import remap_interview
    from .editor_utils import playground_list_yaml_files, playground_read_yaml

    if len(context.candidate.template_assets) >= 3:
        raise LabelingError(
            "Apply or reset the existing template proposals before labeling more documents."
        )

    # The Assistant session owns one source buffer. Do not strand a second
    # interview's template references when it is outside that transaction.
    other_sources = {}
    for item in playground_list_yaml_files(context.storage_user_id, context.project):
        other = item["filename"]
        if other != context.filename:
            text = playground_read_yaml(context.storage_user_id, context.project, other)
            other_sources[other] = text
            if name in text:
                raise LabelingError(
                    f"{other} also uses this template. Relabeling requires reviewing that interview too."
                )
    content = read_template(context, name)
    replacement = (
        f"{Path(name).stem}_labeled_{uuid.uuid4().hex[:12]}{Path(name).suffix}"
    )
    with tempfile.TemporaryDirectory(prefix="weaver-label-") as directory:
        original = Path(directory) / name
        output = Path(directory) / replacement
        original.write_bytes(content)
        proposal = propose_labels(str(original), str(output))
        source = remap_interview(
            context.candidate.raw_source,
            context.filename,
            name,
            replacement,
            proposal["mappings"],
            proposal["added_fields"],
        )
        from .editor_agent_tools import _variable_catalog
        from .field_labeling import template_fields

        before_variables = {
            item["variable"] for item in _variable_catalog(context.candidate.raw_source)
        }
        after_variables = {item["variable"] for item in _variable_catalog(source)}
        changed_variables = before_variables - after_variables
        for asset in context.candidate.template_assets:
            if not asset["filename"].lower().endswith(".docx"):
                continue
            staged_names = [item["new_name"] for item in asset["mappings"]] + asset[
                "added_fields"
            ]
            if any(
                name == variable
                or name.startswith(variable + ".")
                or name.startswith(variable + "[")
                for name in staged_names
                for variable in changed_variables
            ):
                raise LabelingError(
                    "A staged Word template uses a renamed answer. Review or reset that proposal before relabeling another template."
                )
        for other, text in other_sources.items():
            if any(
                re.search(r"(?<![\w.])" + re.escape(variable) + r"(?!\w)", text)
                for variable in changed_variables
            ):
                raise LabelingError(
                    f"{other} also refers to a renamed answer. Review the included interview before relabeling."
                )
        _, project_directory = template_directory(
            context.storage_user_id, context.project
        )
        referenced = set(attached_template_names(context.candidate.raw_source))
        for text in other_sources.values():
            referenced.update(attached_template_names(text))
        for other in project_directory.glob("*.docx"):
            if other.name == name:
                continue
            if other.name not in referenced:
                continue
            names = {item["name"] for item in template_fields(str(other))}
            if names & changed_variables:
                raise LabelingError(
                    f"{other.name} also uses a renamed answer. Relabel these Word templates together before applying."
                )
        if proposal["added_fields"]:
            from .template_analysis import analyze_template
            from .editor_utils import (
                insert_block_in_yaml,
                parse_interview_yaml,
                add_object_declaration,
            )
            import yaml

            analysis = analyze_template(
                template_path=str(output),
                template_filename=replacement,
                interview_yaml=source,
                use_llm_assist=False,
            )
            if analysis.objects:
                declarations = yaml.safe_load(analysis.objects.yaml).get("objects", [])
                existing_objects = next(
                    (
                        b
                        for b in parse_interview_yaml(source)["blocks"]
                        if not b.get("data", {}).get("_commented")
                        and b.get("data", {}).get("objects")
                    ),
                    None,
                )
                if existing_objects:
                    for declaration in declarations:
                        for root, expression in declaration.items():
                            source = add_object_declaration(
                                source, existing_objects["id"], root, expression
                            )
                else:
                    source = insert_block_in_yaml(
                        source,
                        "id: labeled_template_objects_"
                        + uuid.uuid4().hex[:8]
                        + "\n"
                        + analysis.objects.yaml,
                        None,
                    )
            for question in analysis.questions:
                # A new stable id avoids collisions with an authored screen.
                block = re.sub(r"(?m)^id:.*\n", "", question.yaml)
                source = insert_block_in_yaml(
                    source,
                    "id: labeled_template_question_"
                    + uuid.uuid4().hex[:8]
                    + "\n"
                    + block,
                    None,
                )
        asset = {
            "filename": replacement,
            "original_filename": name,
            "original_revision": hashlib.sha256(content).hexdigest(),
            "content_base64": base64.b64encode(output.read_bytes()).decode("ascii"),
            "mappings": proposal["mappings"],
            "added_fields": proposal["added_fields"],
        }
    return source, asset, proposal


def materialize_templates(user_id, project, assets):
    """Write immutable copies on Apply, preserving every original template.

    The API holds the source/template locks. A failed save never rewrites an
    original and the YAML remains unsaved until the existing Save action.
    """
    area, directory = template_directory(user_id, project)
    directory.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        original = directory / asset["original_filename"]
        if (
            original.is_symlink()
            or not original.is_file()
            or hashlib.sha256(original.read_bytes()).hexdigest()
            != asset["original_revision"]
        ):
            raise LabelingError(
                "A template changed since labeling. Start a new proposal before applying."
            )
        output = directory / asset["filename"]
        content = base64.b64decode(asset["content_base64"], validate=True)
        if output.exists() and (output.is_symlink() or output.read_bytes() != content):
            raise LabelingError("The proposed template filename is already in use.")
    for asset in assets:
        output = directory / asset["filename"]
        if not output.exists():
            with output.open("xb") as stream:
                stream.write(base64.b64decode(asset["content_base64"], validate=True))
    area.finalize()

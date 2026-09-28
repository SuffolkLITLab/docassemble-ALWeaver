# do not pre-load

"""Work out what importing a template into an existing interview would take.

This is the engine behind the editor's **Import into this interview** action.
Importing is what the author is doing; reading and comparing the template's
fields is how it happens, which is what the functions here are named for.

Weaver's document analysis used to be spent once, when a project was created.
Adding a second form to a finished interview -- or re-reading a form the court
has revised -- meant dropping to raw YAML.

The work here runs the ordinary generator over one template and then keeps only
the parts an existing interview is missing: the `attachment` block for the
template, question screens for fields nothing asks about yet, and the `objects`
entries those screens depend on. Each is separately acceptable, because an
author adding a cover sheet to a working interview usually wants the attachment
and nothing else.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .document_bundles import (
    interview_documents,
    objects_declarations as _objects_declarations,
    reference_root as _reference_root,
    render_objects_block as _render_objects_block,
    with_declaration_keyword,
)
from .editor_utils import (
    BLOCK_TYPE_ATTACHMENT,
    BLOCK_TYPE_CODE,
    BLOCK_TYPE_OBJECTS,
    BLOCK_TYPE_QUESTION,
    BLOCK_TYPE_TEMPLATE,
    canonical_block_yaml,
    parse_interview_yaml,
)
from .interview_generator import (
    DocumentName,
    document_names,
    generate_interview_from_path,
)

__all__ = [
    "TemplateAnalysis",
    "analyze_template",
    "document_variable_for",
    "interview_defined_variables",
]


def document_variable_for(
    template_filename: str, taken: Optional[Iterable[str]] = None
) -> DocumentName:
    """Name the ``ALDocument`` a template joining an interview attaches to.

    The same rule the generator uses for a multi-document interview, applied to
    one newcomer: normally the filename without its extension, and the
    extension kept when that name is already spoken for -- which is what
    happens when the interview already assembles a `petition.pdf` and a
    `petition.docx` arrives.

    Args:
        template_filename (str): the template's filename.
        taken (Optional[Iterable[str]]): document variables already in use.

    Returns:
        DocumentName: the variable to declare, and the name to download under.
    """
    filename = os.path.basename(template_filename)
    return document_names([filename], taken=taken)[filename]


_ASSIGNMENT_RE = re.compile(
    r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]*\])?(?:\.[A-Za-z0-9_.\[\]]+)?\s*(?:=[^=]|\+=)"
)

# Question keys whose value is the variable the screen sets.
_SINGLE_VARIABLE_KEYS = (
    "field",
    "yesno",
    "noyes",
    "signature",
    "variable name",
    "generic object",
    "sets",
)


@dataclass
class ProposedBlock:
    """One block the author can accept into the interview, or not."""

    kind: str
    title: str
    yaml: str
    #: Variables this block would newly define, for the "what does this add?" line.
    variables: List[str] = field(default_factory=list)
    #: The block this one replaces, when the template is already imported and
    #: the offer is a re-read rather than an addition.
    replaces_block_id: Optional[str] = None
    #: Whether accepting this by default would be a reasonable guess. A
    #: replacement is not: it discards whatever the author did to that block.
    recommended: bool = True
    #: Blocks required for this candidate to work. The editor adds these when
    #: this candidate is selected, so a document object cannot outlive its
    #: generated display-title template.
    supporting_blocks: List["ProposedBlock"] = field(default_factory=list)


@dataclass
class TemplateAnalysis:
    """What adding one template to an existing interview would take."""

    template_filename: str
    document_variable: str
    #: The `attachment` block for this template.
    attachment: Optional[ProposedBlock] = None
    #: The `ALDocument` declaration the attachment's `variable name` refers to.
    document_object: Optional[ProposedBlock] = None
    #: `objects` entries for people the new screens talk about.
    objects: Optional[ProposedBlock] = None
    #: One per question screen worth adding.
    questions: List[ProposedBlock] = field(default_factory=list)
    #: Bundles that should gain this document, and where in them it would go.
    bundle_additions: List[Dict[str, Any]] = field(default_factory=list)
    #: True when an `attachment` block already fills this template, so the
    #: offer is to re-read a revised form rather than to import a new one.
    already_imported: bool = False
    new_variables: List[str] = field(default_factory=list)
    known_variables: List[str] = field(default_factory=list)
    #: Field-name changes when a previously attached template is read again.
    mapping_changes: Dict[str, List[str]] = field(
        default_factory=lambda: {"added": [], "removed": [], "retained": []}
    )
    #: Existing question variables that still refer to removed template fields.
    stale_question_variables: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return the analysis in the shape the editor API sends over the wire.

        Returns:
            Dict[str, Any]: a JSON-serializable copy.
        """

        def block(proposed: Optional[ProposedBlock]) -> Optional[Dict[str, Any]]:
            if proposed is None:
                return None
            return {
                "kind": proposed.kind,
                "title": proposed.title,
                "yaml": proposed.yaml,
                "variables": list(proposed.variables),
                "replaces_block_id": proposed.replaces_block_id,
                "recommended": proposed.recommended,
                "supporting_blocks": [
                    block(supporting) for supporting in proposed.supporting_blocks
                ],
            }

        return {
            "template_filename": self.template_filename,
            "document_variable": self.document_variable,
            "attachment": block(self.attachment),
            "document_object": block(self.document_object),
            "objects": block(self.objects),
            "questions": [block(question) for question in self.questions],
            "bundle_additions": list(self.bundle_additions),
            "already_imported": self.already_imported,
            "new_variables": list(self.new_variables),
            "known_variables": list(self.known_variables),
            "mapping_changes": {
                key: list(values) for key, values in self.mapping_changes.items()
            },
            "stale_question_variables": list(self.stale_question_variables),
            "warnings": list(self.warnings),
        }


def _variables_in_question_block(data: Dict[str, Any]) -> Set[str]:
    """Every variable a question block sets."""
    found: Set[str] = set()
    for key in _SINGLE_VARIABLE_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            found.add(value.strip())
    fields = data.get("fields")
    if isinstance(fields, list):
        for entry in fields:
            if isinstance(entry, dict):
                for label, value in entry.items():
                    if label in {
                        "datatype",
                        "default",
                        "choices",
                        "hint",
                        "help",
                        "required",
                        "show if",
                        "hide if",
                        "maxlength",
                        "min",
                        "max",
                        "step",
                        "input type",
                        "code",
                        "note",
                        "html",
                        "label",
                        "field",
                    }:
                        if label == "field" and isinstance(value, str):
                            found.add(value.strip())
                        continue
                    if isinstance(value, str) and value.strip():
                        found.add(value.strip())
            elif isinstance(entry, str):
                found.add(entry.strip())
    buttons = data.get("buttons")
    if isinstance(buttons, list):
        for entry in buttons:
            if isinstance(entry, dict) and isinstance(entry.get("field"), str):
                found.add(str(entry["field"]).strip())
    return {value for value in found if value}


def _attachment_mapping_field_names(data: Dict[str, Any]) -> Set[str]:
    """Return the external template field names declared in an attachment."""
    attachment = data.get("attachment")
    if not isinstance(attachment, dict):
        attachment = data
    fields = attachment.get("fields") if isinstance(attachment, dict) else None
    entries = fields if isinstance(fields, list) else [fields]
    found = {
        str(key)
        for entry in entries
        if isinstance(entry, dict)
        for key in entry
        if str(key).strip()
    }
    return found


_DOCX_FIELD_MANIFEST_PREFIX = "# ALWeaver DOCX template field manifest: "


def _question_field_variables(data: Dict[str, Any]) -> Set[str]:
    """Return variables declared by fields, excluding question expressions."""
    fields = data.get("fields")
    if not isinstance(fields, list):
        return set()
    found: Set[str] = set()
    for entry in fields:
        if isinstance(entry, (dict, str)):
            found.update(_variables_in_question_block({"fields": [entry]}))
    return found


def _docx_field_manifest(block_yaml: str) -> Set[str]:
    for line in block_yaml.splitlines():
        if not line.startswith(_DOCX_FIELD_MANIFEST_PREFIX):
            continue
        try:
            fields = json.loads(line[len(_DOCX_FIELD_MANIFEST_PREFIX) :])
        except (TypeError, ValueError):
            return set()
        if isinstance(fields, list):
            return {value for value in fields if isinstance(value, str) and value}
    return set()


def _with_docx_field_manifest(block_yaml: str, fields: Set[str]) -> str:
    manifest = _DOCX_FIELD_MANIFEST_PREFIX + json.dumps(sorted(fields))
    lines = [
        line
        for line in block_yaml.splitlines()
        if not line.startswith(_DOCX_FIELD_MANIFEST_PREFIX)
    ]
    return manifest + "\n" + "\n".join(lines)


def _question_variables_for_fields(
    model: Dict[str, Any], field_names: Set[str]
) -> List[str]:
    """Find authored question variables whose names match stale template fields."""
    references: Set[str] = set()
    for entry in model.get("blocks", []):
        data = entry.get("data")
        if not isinstance(data, dict) or data.get("_commented"):
            continue
        if entry.get("type") != BLOCK_TYPE_QUESTION:
            continue
        references.update(_variables_in_question_block(data))
    return sorted(
        reference
        for reference in references
        if (_reference_root(reference) or "") in field_names
    )


def interview_defined_variables(raw_yaml: str) -> Set[str]:
    """Every variable name an interview already has a way to define.

    This is deliberately root-level: an interview that asks for
    `users[0].name.first` has `users`, and adding a screen that asks for
    `users[0].name.last` again is duplication, not a missing definition.

    Args:
        raw_yaml (str): the interview's YAML source.

    Returns:
        Set[str]: the variable roots the interview defines.
    """
    defined: Set[str] = set()
    model = parse_interview_yaml(raw_yaml)
    for entry in model["blocks"]:
        data = entry.get("data")
        if not isinstance(data, dict) or data.get("_commented"):
            continue
        block_type = entry.get("type")
        if block_type == BLOCK_TYPE_QUESTION:
            for reference in _variables_in_question_block(data):
                root = _reference_root(reference)
                if root:
                    defined.add(root)
        elif block_type == BLOCK_TYPE_OBJECTS:
            objects = data.get("objects")
            if isinstance(objects, dict):
                defined.update(str(name) for name in objects)
            elif isinstance(objects, list):
                for item in objects:
                    if isinstance(item, dict):
                        defined.update(str(name) for name in item)
                    elif isinstance(item, str):
                        defined.add(item.strip())
        elif block_type == BLOCK_TYPE_CODE:
            code = data.get("code")
            if isinstance(code, str):
                defined.update(_ASSIGNMENT_RE.findall(code))
        elif block_type == BLOCK_TYPE_TEMPLATE:
            root = _reference_root(data.get("template"))
            if root:
                defined.add(root)
        elif block_type == BLOCK_TYPE_ATTACHMENT:
            root = _reference_root(data.get("variable name"))
            if root:
                defined.add(root)
    return defined


def _rename_attachment_variable(text: str, old_name: str, new_name: str) -> str:
    if not old_name or old_name == new_name:
        return text
    return re.sub(rf"\b{re.escape(old_name)}\b", new_name, text)


def _rename_attachment_output(block_yaml: str, filename: str) -> str:
    """Point an attachment block's own output at a different name.

    A draft built from one template names the finished file after the
    interview. Joining an interview that already assembles a document of that
    name, the newcomer needs its own -- two attachments writing one filename is
    the same collision as two sharing a variable.

    Args:
        block_yaml (str): the attachment block.
        filename (str): the name the finished document should download under.

    Returns:
        str: the block, with its top-level `name:` and `filename:` rewritten.
    """
    block_yaml = re.sub(
        r"(?m)^(?P<lead>  filename: ).*$",
        lambda match: match.group("lead") + filename,
        block_yaml,
        count=1,
    )
    return re.sub(
        r"(?m)^(?P<lead>  name: ).*$",
        lambda match: match.group("lead") + filename.replace("_", " "),
        block_yaml,
        count=1,
    )


def _trim_question_fields(
    data: Dict[str, Any], already_defined: Set[str]
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Drop the fields the interview already asks about.

    Args:
        data (Dict[str, Any]): the parsed question block.
        already_defined (Set[str]): variable roots the interview defines.

    Returns:
        Tuple[Optional[Dict[str, Any]], List[str]]: the block with only the new
        fields left (None when nothing new remains), and those field names.
    """
    fields = data.get("fields")
    if not isinstance(fields, list):
        undefined = sorted(
            reference
            for reference in _variables_in_question_block(data)
            if (_reference_root(reference) or "") not in already_defined
        )
        return (dict(data), undefined) if undefined else (None, [])

    kept: List[Any] = []
    variables: List[str] = []
    for entry in fields:
        entry_variables = (
            _variables_in_question_block({"fields": [entry]})
            if isinstance(entry, (dict, str))
            else set()
        )
        new_variables = [
            reference
            for reference in sorted(entry_variables)
            if (_reference_root(reference) or "") not in already_defined
        ]
        if not entry_variables or new_variables:
            kept.append(entry)
            variables.extend(new_variables)
    if not variables:
        return None, []
    trimmed = dict(data)
    trimmed["fields"] = kept
    return trimmed, variables


def analyze_template(
    *,
    template_path: str,
    template_filename: str,
    interview_yaml: str,
    use_llm_assist: bool = False,
    generation_options: Optional[Dict[str, Any]] = None,
) -> TemplateAnalysis:
    """Work out what adding this template to this interview would take.

    Args:
        template_path (str): where the template file is on disk.
        template_filename (str): the name it has in the project.
        interview_yaml (str): the YAML source of the interview it is joining.
        use_llm_assist (bool): whether to let the generator refine labels and
            screen grouping with AI.
        generation_options (Optional[Dict[str, Any]]): further options passed
            through to the generator.

    Returns:
        TemplateAnalysis: the separately-acceptable pieces, and what is already
        covered.
    """
    already_defined = interview_defined_variables(interview_yaml)
    existing = interview_documents(interview_yaml)
    existing_model = parse_interview_yaml(interview_yaml)
    # An `attachment` block already filling this template is the interview
    # telling us the template is imported, whatever the document is called. A
    # re-read has to stay with that name, or the screens and the bundle entry
    # would point at a second document nobody asked for.
    imported_as = next(
        (
            document
            for document in existing.documents
            if document.template_filename == template_filename
        ),
        None,
    )
    plain_name = document_names([template_filename])[template_filename].variable
    if imported_as is not None:
        document_variable = imported_as.name
        # Nothing about the existing document's naming is up for negotiation
        # on a re-read, so there is no second name to work out.
        disambiguated = False
        output_filename = ""
    else:
        # A newcomer must not take a name another document already holds --
        # including one an author renamed by hand. The plain name of every
        # template already attached is reserved too, so a `petition.docx`
        # joining a `petition.pdf` is `petition_docx` even when the interview
        # calls that PDF's document something else, which is what a project
        # generated from a single template does.
        taken = {document.name for document in existing.documents}
        for document in existing.documents:
            attached = document.template_filename
            if attached:
                taken.add(document_names([attached])[attached].variable)
        naming = document_variable_for(template_filename, taken=taken)
        document_variable = naming.variable
        output_filename = naming.filename
        # True when this template could not have the name its filename
        # suggests, because the interview already assembles one called that.
        disambiguated = document_variable != plain_name

    options: Dict[str, Any] = {
        "create_package_zip": False,
        "include_next_steps": False,
        "include_download_screen": True,
        # The interview being joined already has whatever person questions it
        # wanted; copying AssemblyLine's again would only duplicate them.
        "copy_baseline_questions": False,
        "use_llm_assist": use_llm_assist,
    }
    options.update(generation_options or {})
    output_dir = tempfile.mkdtemp(prefix="alweaver-analyze-")
    try:
        result = generate_interview_from_path(
            template_path,
            output_dir=output_dir,
            exact_name=template_filename,
            **options,
        )
        draft_yaml = result.yaml_text
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)

    # A draft generated from one template names its document after the
    # interview. Joining an interview that already has documents, it needs the
    # name `output.mako` gives every document in a multi-document bundle.
    draft_model = parse_interview_yaml(draft_yaml)
    draft_attachment_variable = ""
    for entry in draft_model["blocks"]:
        data = entry.get("data")
        if isinstance(data, dict) and entry.get("type") == BLOCK_TYPE_ATTACHMENT:
            attachment = data.get("attachment")
            if not isinstance(attachment, dict):
                attachment = data
            draft_attachment_variable = (
                _reference_root(attachment.get("variable name")) or ""
            )
            break

    analysis = TemplateAnalysis(
        template_filename=template_filename,
        document_variable=document_variable,
        already_imported=imported_as is not None,
    )
    draft_attachment_fields: Set[str] = set()
    draft_docx_template_fields: Set[str] = set()
    draft_title_template: Optional[ProposedBlock] = None
    existing_template_names = {
        _reference_root(entry.get("data", {}).get("template"))
        for entry in existing_model.get("blocks", [])
        if entry.get("type") == BLOCK_TYPE_TEMPLATE
        and isinstance(entry.get("data"), dict)
    }
    draft_interview_label = (
        draft_attachment_variable[: -len("_attachment")]
        if draft_attachment_variable.endswith("_attachment")
        else draft_attachment_variable
    )
    expected_draft_title = f"{draft_interview_label}_attachment_title"
    target_title = (
        f"{document_variable}_title"
        if document_variable.endswith("_attachment")
        else f"{document_variable}_attachment_title"
    )
    for entry in draft_model["blocks"]:
        data = entry.get("data")
        if (
            entry.get("type") == BLOCK_TYPE_TEMPLATE
            and isinstance(data, dict)
            and _reference_root(data.get("template")) == expected_draft_title
            and target_title not in existing_template_names
        ):
            title_yaml = str(entry.get("yaml") or "").strip()
            if disambiguated:
                title_yaml = _rename_attachment_variable(
                    title_yaml, expected_draft_title, target_title
                )
            draft_title_template = ProposedBlock(
                kind="template",
                title=f"Display title for {template_filename}",
                yaml=title_yaml,
                variables=[target_title],
            )
            break
    if template_filename.lower().endswith(".docx"):
        for entry in draft_model["blocks"]:
            data = entry.get("data")
            if entry.get("type") == BLOCK_TYPE_QUESTION and isinstance(data, dict):
                draft_docx_template_fields.update(_question_field_variables(data))
    new_variables: List[str] = []
    known_variables: List[str] = []
    # A draft can declare people across more than one `objects:` block, and
    # they are offered as one.
    person_object_declarations: List[Tuple[str, str]] = []

    for entry in draft_model["blocks"]:
        data = entry.get("data")
        block_yaml = str(entry.get("yaml") or "").strip()
        if not isinstance(data, dict) or data.get("_commented") or not block_yaml:
            continue
        block_type = entry.get("type")

        if block_type == BLOCK_TYPE_ATTACHMENT:
            draft_attachment_fields = _attachment_mapping_field_names(data)
            attachment_yaml = _rename_attachment_variable(
                block_yaml, draft_attachment_variable, document_variable
            )
            if disambiguated:
                attachment_yaml = _rename_attachment_output(
                    attachment_yaml, output_filename
                )
            if template_filename.lower().endswith(".docx"):
                attachment_yaml = _with_docx_field_manifest(
                    attachment_yaml, draft_docx_template_fields
                )
            analysis.attachment = ProposedBlock(
                kind="attachment",
                title=f"Attachment for {template_filename}",
                yaml=attachment_yaml,
                variables=[document_variable],
            )
        elif block_type == BLOCK_TYPE_OBJECTS:
            declarations = _objects_declarations(data)
            document_declarations = [
                (name, declaration)
                for name, declaration in declarations
                if "ALDocument.using" in declaration
            ]
            person_declarations = [
                (name, declaration)
                for name, declaration in declarations
                if "ALDocument" not in declaration
                and name not in already_defined
                and name != draft_attachment_variable
            ]
            if document_declarations and analysis.document_object is None:
                name, declaration = document_declarations[0]
                # Two documents downloading under one filename is the same
                # collision as two sharing a variable, so both names move.
                declaration = _rename_attachment_variable(
                    declaration, name, document_variable
                )
                # The `_attachment_title` suffix starts with an underscore,
                # which is a word character in regex terms; the generic
                # identifier-boundary rename above intentionally leaves it
                # alone. Rename this exact generated companion explicitly.
                declaration = declaration.replace(expected_draft_title, target_title)
                if disambiguated:
                    declaration = with_declaration_keyword(
                        declaration, "filename", f'"{output_filename}"'
                    )
                analysis.document_object = ProposedBlock(
                    kind="document_object",
                    title=f"ALDocument for {template_filename}",
                    yaml=_render_objects_block([(document_variable, declaration)]),
                    variables=[document_variable],
                )
                if draft_title_template is not None:
                    analysis.document_object.supporting_blocks.append(
                        draft_title_template
                    )
            person_object_declarations.extend(person_declarations)
        elif block_type == BLOCK_TYPE_QUESTION:
            trimmed, variables = _trim_question_fields(data, already_defined)
            covered = sorted(
                reference
                for reference in _variables_in_question_block(data)
                if (_reference_root(reference) or "") in already_defined
            )
            known_variables.extend(covered)
            if trimmed is None:
                continue
            new_variables.extend(variables)
            analysis.questions.append(
                ProposedBlock(
                    kind="question",
                    title=str(entry.get("title") or "Question"),
                    yaml=(
                        block_yaml if trimmed == data else canonical_block_yaml(trimmed)
                    ),
                    variables=variables,
                )
            )

    if person_object_declarations:
        analysis.objects = ProposedBlock(
            kind="objects",
            title="Objects the new screens need",
            yaml=_render_objects_block(person_object_declarations),
            variables=[name for name, _declaration in person_object_declarations],
        )

    if imported_as is not None:
        existing_attachment_fields: Set[str] = set()
        existing_docx_fields: Set[str] = set()
        if imported_as.attachment_block_id:
            for entry in existing_model.get("blocks", []):
                if (
                    str(entry.get("id")) == imported_as.attachment_block_id
                    and entry.get("type") == BLOCK_TYPE_ATTACHMENT
                    and isinstance(entry.get("data"), dict)
                ):
                    existing_attachment_fields = _attachment_mapping_field_names(
                        entry["data"]
                    )
                    if template_filename.lower().endswith(".docx"):
                        existing_docx_fields = _docx_field_manifest(
                            str(entry.get("yaml") or "")
                        )
                    break
        if template_filename.lower().endswith(".docx"):
            existing_fields = existing_docx_fields
            revised_fields = draft_docx_template_fields
            if not existing_docx_fields:
                analysis.warnings.append(
                    "This DOCX attachment has no saved template-field manifest, "
                    "so fields removed before this revision cannot be identified. "
                    "Review existing questions; applying the revised attachment "
                    "will save a manifest for future comparisons."
                )
        else:
            existing_fields = existing_attachment_fields
            revised_fields = draft_attachment_fields
        if existing_fields or revised_fields:
            added_fields = revised_fields - existing_fields
            removed_fields = existing_fields - revised_fields
            analysis.mapping_changes = {
                "added": sorted(added_fields),
                "removed": sorted(removed_fields),
                "retained": sorted(existing_fields & revised_fields),
            }
            if removed_fields:
                analysis.stale_question_variables = _question_variables_for_fields(
                    existing_model, removed_fields
                )
                analysis.warnings.append(
                    "The revised template no longer contains mapped fields: "
                    + ", ".join(sorted(removed_fields))
                    + ". Existing mappings and authored questions are preserved; "
                    "review them before using the revised form."
                )
                if analysis.stale_question_variables:
                    analysis.warnings.append(
                        "Existing question screens still ask for removed template "
                        "fields: "
                        + ", ".join(analysis.stale_question_variables)
                        + ". Update those screens if the questions no longer apply."
                    )
        # The document exists, so the only thing worth offering about it is a
        # freshly read attachment block -- which is how a revised form gets its
        # new fields. It replaces rather than adds, and it is not ticked by
        # default, because it discards whatever the author did to that block.
        analysis.document_object = None
        if analysis.attachment is not None:
            analysis.attachment = ProposedBlock(
                kind="attachment_replacement",
                title=(
                    f"Replace the attachment block for {template_filename} with "
                    "one read from the file as it is now"
                ),
                yaml=analysis.attachment.yaml,
                variables=[],
                replaces_block_id=imported_as.attachment_block_id,
                recommended=False,
            )
            if imported_as.attachment_block_id is None:
                # Nothing to replace: the attachment is there, but not as a
                # block this editor can address.
                analysis.attachment = None
                analysis.warnings.append(
                    f"{template_filename} is already attached, but Weaver could "
                    "not find the attachment block to re-read it into."
                )
            elif draft_title_template is not None:
                # Legacy imports can be missing the title template. Tie the
                # repair to the explicitly accepted attachment replacement;
                # existing authored titles are never overwritten.
                analysis.attachment.supporting_blocks.append(draft_title_template)
    else:
        if disambiguated:
            analysis.warnings.append(
                f"This interview already has a document called `{plain_name}`, "
                f"so this one is `{document_variable}` and downloads as "
                f"{output_filename}."
            )
        for bundle in existing.bundles:
            if document_variable in bundle.elements:
                continue
            analysis.bundle_additions.append(
                {
                    "bundle": bundle.name,
                    "block_id": bundle.block_id,
                    "element": document_variable,
                    "elements": bundle.elements + [document_variable],
                }
            )

    if (
        analysis.attachment is not None
        and not analysis.already_imported
        and not existing.bundles
    ):
        analysis.warnings.append(
            "This interview has no ALDocumentBundle, so an attachment on its "
            "own will not appear in any download."
        )

    analysis.new_variables = sorted(set(new_variables))
    analysis.known_variables = sorted(set(known_variables))
    return analysis

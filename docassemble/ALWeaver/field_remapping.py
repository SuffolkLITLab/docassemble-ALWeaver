"""Lossless source changes accompanying a reviewed template relabeling."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .field_labeling import LabelingError
from .source_document import parse_source_document, apply_range_operations


def remap_interview(
    source: str,
    filename: str,
    template_name: str,
    replacement_name: str,
    mappings: List[Dict[str, str]],
    added_fields: List[str],
) -> str:
    """Retarget one attachment and every unambiguous variable reference.

    PDF keys are physical field names, distinct from interview variables. Read
    their actual expressions rather than assuming a field name was the variable.
    Refuse computed mappings, cross-template dependencies, and ambiguous merges.
    """
    import yaml
    from .editor_agent_rename import check_rename_batch, plan_rename_operations
    from .interview_generator import map_raw_to_final_display

    is_pdf = template_name.lower().endswith(".pdf")
    field_map = {item["old_name"]: item["new_name"] for item in mappings}
    variable_map: Dict[str, str] = {}
    display_overrides: Dict[str, str] = {}
    operations = []
    found = False
    document = parse_source_document(filename, source)
    # YAML node offsets refer to the raw block, allowing exact scalar edits.
    for block in document.documents:
        node = yaml.compose(block.raw_text)
        if not isinstance(node, yaml.MappingNode):
            continue
        roots = dict((key.value, value) for key, value in node.value)
        attachment = roots.get("attachment") or roots.get("attachments")
        if attachment is None:
            continue
        entries = (
            attachment.value
            if isinstance(attachment, yaml.SequenceNode)
            else [attachment]
        )
        for entry in entries:
            if not isinstance(entry, yaml.MappingNode):
                continue
            attrs = {key.value: value for key, value in entry.value}
            template = attrs.get("pdf template file") or attrs.get("docx template file")
            if (
                template is None
                or not isinstance(template, yaml.ScalarNode)
                or template.value != template_name
            ):
                continue
            found = True

            def replace(node, value):
                # Keep the author's scalar quoting while changing its value.
                if isinstance(node, yaml.ScalarNode):
                    if node.style == '"':
                        import json

                        value = json.dumps(value, ensure_ascii=False)
                    elif node.style == "'":
                        value = "'" + value.replace("'", "''") + "'"
                operations.append(
                    {
                        "type": "replace-range",
                        "start": block.start_offset + node.start_mark.index,
                        "end": block.start_offset + node.end_mark.index,
                        "text": value,
                    }
                )

            replace(template, replacement_name)
            if is_pdf:
                fields = attrs.get("fields")
                if isinstance(fields, yaml.ScalarNode) and fields.tag.endswith(":null"):
                    fields = None
                if fields is not None and not isinstance(
                    fields, (yaml.MappingNode, yaml.SequenceNode)
                ):
                    raise LabelingError(
                        "This PDF attachment has computed or unsupported field mappings. Review it manually."
                    )
                pairs = []
                if isinstance(fields, yaml.MappingNode):
                    pairs = fields.value
                elif isinstance(fields, yaml.SequenceNode):
                    for field_entry in fields.value:
                        if not isinstance(field_entry, yaml.MappingNode):
                            raise LabelingError(
                                "This PDF attachment uses computed fields. Review its mappings manually."
                            )
                        pairs.extend(field_entry.value)
                seen = set()
                for key, value in pairs:
                    if key.value not in field_map:
                        continue
                    seen.add(key.value)
                    new_name = field_map[key.value]
                    if not isinstance(value, yaml.ScalarNode):
                        raise LabelingError(
                            "A PDF field has a computed mapping that cannot be safely remapped."
                        )
                    expression = re.fullmatch(
                        r"\s*\$\{\s*([\w.\[\]]+)\s*\}\s*", value.value
                    )
                    if not expression:
                        raise LabelingError(
                            f"Review the computed mapping for {key.value} before relabeling."
                        )
                    from .interview_generator import substitute_suffix
                    from .generator_constants import generator_constants

                    destination = substitute_suffix(
                        map_raw_to_final_display(new_name),
                        generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX,
                    )
                    if re.fullmatch(r"\w+\[\d+\]", destination):
                        destination += ".name.first"
                    old_root = re.split(r"[.\[]", expression[1])[0]
                    new_root = re.split(r"[.\[]", destination)[0]
                    if old_root != new_root and re.search(
                        r"\b" + re.escape(old_root) + r"\.gather\(", source
                    ):
                        raise LabelingError(
                            "This rename changes an existing gathered object's root. Review its object declaration and gather rules before relabeling."
                        )
                    if (
                        expression[1] in variable_map
                        and variable_map[expression[1]] != destination
                    ):
                        raise LabelingError(
                            "One interview answer would split into multiple variables. Review the attachment mappings first."
                        )
                    variable_map[expression[1]] = destination
                    replace(key, new_name)
                    display_overrides[new_name] = map_raw_to_final_display(new_name)
                if added_fields:
                    indent = next(
                        key.start_mark.column
                        for key, value in entry.value
                        if value is template
                    )
                    sequence = isinstance(fields, yaml.SequenceNode)
                    row_indent = (
                        pairs[0][0].start_mark.column - (2 if sequence else 0)
                        if pairs
                        else indent + 2
                    )
                    rows = "".join(
                        "\n"
                        + " " * row_indent
                        + ("- " if sequence else "")
                        + yaml.safe_dump(name, default_flow_style=True).splitlines()[0]
                        + ": ${ "
                        + map_raw_to_final_display(name)
                        + " }"
                        for name in added_fields
                    )
                    if fields is None:
                        blank_fields = attrs.get("fields")
                        if blank_fields is not None:
                            replace(blank_fields, rows)
                            continue
                        end = template.end_mark.index
                        text = " " * indent + "fields:" + rows + "\n"
                    elif not fields.value:
                        replace(fields, rows)
                        continue
                    elif fields.flow_style or (
                        sequence and any(item.flow_style for item in fields.value)
                    ):
                        raise LabelingError(
                            "Expand the PDF field mapping to block style before adding fields."
                        )
                    else:
                        end = (
                            fields.value[-1].end_mark.index
                            if sequence
                            else pairs[-1][1].end_mark.index
                        )
                        text = rows.lstrip("\n") + "\n"
                    # Keep inline comments on their original lines. Block scalars
                    # already end at the next line's beginning.
                    if end and block.raw_text[end - 1] != "\n":
                        newline = block.raw_text.find("\n", end)
                        end = len(block.raw_text) if newline < 0 else newline + 1
                        if newline < 0:
                            text = "\n" + text
                    operations.append(
                        {
                            "type": "replace-range",
                            "start": block.start_offset + end,
                            "end": block.start_offset + end,
                            "text": text,
                        }
                    )
    if not found:
        raise LabelingError(
            "No literal attachment references this template in the current interview."
        )
    if not is_pdf:
        from .field_labeling import settable_reference

        variable_map = {
            settable_reference(a): settable_reference(b)
            for a, b in field_map.items()
            if a != b
        }
    # Patch physical names first. Variable analysis must not mistake those keys
    # for old variable references. The referenced binary is staged separately.
    updated, _ = apply_range_operations(source, operations)
    renames = [
        {"old_name": a, "new_name": b} for a, b in variable_map.items() if a != b
    ]
    if renames:
        analyses, problems = check_rename_batch(
            filename=filename, raw_yaml=updated, renames=renames
        )
        if problems:
            raise LabelingError(" ".join(problems))
        updated, _ = apply_range_operations(updated, plan_rename_operations(analyses))
        updated = consolidate_people(
            updated, filename, [item["new_name"] for item in renames]
        )
    if is_pdf and display_overrides:
        # Question variables must be assignable, while attachment values may
        # call formatting methods or display a whole person.
        fixes = []
        for block in parse_source_document(filename, updated).documents:
            node = yaml.compose(block.raw_text)
            if not isinstance(node, yaml.MappingNode):
                continue
            roots = {key.value: value for key, value in node.value}
            attachments = roots.get("attachment") or roots.get("attachments")
            entries = (
                attachments.value
                if isinstance(attachments, yaml.SequenceNode)
                else [attachments]
            )
            for entry in entries:
                if not isinstance(entry, yaml.MappingNode):
                    continue
                attrs = {key.value: value for key, value in entry.value}
                template = attrs.get("pdf template file")
                if template is None or template.value != replacement_name:
                    continue
                fields = attrs.get("fields")
                pairs = (
                    fields.value
                    if isinstance(fields, yaml.MappingNode)
                    else (
                        [pair for item in fields.value for pair in item.value]
                        if isinstance(fields, yaml.SequenceNode)
                        else []
                    )
                )
                for key, value in pairs:
                    if key.value in display_overrides:
                        import json

                        text = "${ " + display_overrides[key.value] + " }"
                        if value.style == '"':
                            text = json.dumps(text)
                        elif value.style == "'":
                            text = "'" + text.replace("'", "''") + "'"
                        elif value.style in {"|", ">"}:
                            text = json.dumps(text) + "\n"
                        fixes.append(
                            {
                                "type": "replace-range",
                                "start": block.start_offset + value.start_mark.index,
                                "end": block.start_offset + value.end_mark.index,
                                "text": text,
                            }
                        )
        updated = apply_range_operations(updated, fixes)[0]
    return updated


def consolidate_people(source: str, filename: str, names: List[str]) -> str:
    """Declare converted people and gather at the first unconditional order use.

    Keep conditional and assigned expressions intact: moving a gather across a
    condition can change which questions are asked. Only collapse adjacent bare
    references with the same indentation.
    """
    import ast
    from .editor_utils import parse_interview_yaml, add_object_declaration
    from .generator_constants import generator_constants

    roots: Dict[str, int] = {}
    for name in names:
        match = re.fullmatch(
            r"([A-Za-z_]\w*)\[(\d+)\]\.(?:name(?:\.\w+)?|address\.\w+|email|phone_number|signature|birthdate)",
            name,
        )
        if match:
            roots[match[1]] = max(roots.get(match[1], 0), int(match[2]) + 1)
    if not roots:
        return source
    model = parse_interview_yaml(source)
    from .document_bundles import objects_declarations

    declared = {
        key: value
        for block in model["blocks"]
        if not block.get("data", {}).get("_commented")
        for key, value in objects_declarations(block.get("data") or {})
    }
    for root, size in roots.items():
        baseline_people = {
            "users",
            "children",
            "other_parties",
            "witnesses",
            "caregivers",
            "guardians_ad_litem",
            "attorneys",
            "translators",
            "debt_collectors",
            "creditors",
            "spouses",
            "parents",
            "decedents",
            "interested_parties",
            "guardians",
            "adoptees",
        }
        has_baseline = "docassemble.AssemblyLine:" in source
        if (
            root not in declared
            and root not in generator_constants.AL_MANAGED_OBJECTS
            and not (has_baseline and root in baseline_people)
        ):
            objects = next(
                (
                    b
                    for b in model["blocks"]
                    if not b.get("data", {}).get("_commented")
                    and b.get("data", {}).get("objects")
                ),
                None,
            )
            expression = "ALPeopleList.using(ask_number=True)"
            if objects:
                source = add_object_declaration(source, objects["id"], root, expression)
            else:
                source += f"\n---\nid: weaver_labeled_people_{root}\nobjects:\n  - {root}: {expression}\n"
            model = parse_interview_yaml(source)
    operations = []
    for block in parse_source_document(filename, source).documents:
        import yaml

        data = yaml.safe_load(block.raw_text)
        if not isinstance(data, dict) or not isinstance(data.get("code"), str):
            continue
        code = data["code"]
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        lines = block.raw_text.splitlines(keepends=True)
        key_index = next(
            (i for i, line in enumerate(lines) if re.match(r"^code:\s*\|", line)), None
        )
        if key_index is None:
            continue
        gathered = set()
        for statement in tree.body:
            value = (
                ast.get_source_segment(code, statement)
                if isinstance(statement, ast.Expr)
                else None
            )
            existing_gather = re.fullmatch(r"(\w+)\.gather\(\)", value or "")
            if existing_gather:
                gathered.add(existing_gather[1])
            match = re.fullmatch(
                r"(\w+)\[\d+\]\.(?:name|address|email|phone_number|birthdate|signature)(?:\.\w+)*",
                value or "",
            )
            gather_root = match[1] if match and match[1] in roots else None
            if gather_root:
                index = key_index + statement.lineno
                line = lines[index]
                start = block.start_offset + sum(len(part) for part in lines[:index])
                # gather() may only require a person's first name. Keep
                # authored requests for last names and other components so
                # their questions still run before the next order step.
                gather = (
                    ""
                    if gather_root in gathered
                    else line[: len(line) - len(line.lstrip())]
                    + gather_root
                    + ".gather()\n"
                )
                text = gather + line
                operations.append(
                    {
                        "type": "replace-range",
                        "start": start,
                        "end": start + len(line),
                        "text": text,
                    }
                )
                gathered.add(gather_root)
    return apply_range_operations(source, operations)[0]

"""Read attachment mappings and patch only the values an author edits."""

import json
import re
from typing import Any, Dict, List

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


def _mapping(node):
    if not isinstance(node, MappingNode) or (node.flow_style and node.value):
        raise ValueError(
            "Use YAML mode for flow-style or computed attachment mappings."
        )
    result = {}
    for key, value in node.value:
        if not isinstance(key, ScalarNode) or key.value in result or key.value == "<<":
            raise ValueError("Use YAML mode for duplicate keys or merged mappings.")
        result[key.value] = value
    return result


def _attachments(source):
    # Aliases share node offsets and cannot be patched independently.
    if any(
        isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken))
        for token in yaml.scan(source)
    ):
        raise ValueError("Use YAML mode for attachments with anchors or aliases.")
    root = _mapping(yaml.compose(source))
    key = "attachment" if "attachment" in root else "attachments"
    node = root.get(key)
    if isinstance(node, SequenceNode):
        if node.flow_style:
            raise ValueError("Use YAML mode for flow-style attachments.")
        return node.value
    if isinstance(node, MappingNode):
        return [node]
    raise ValueError("This block has no editable attachment mapping.")


def attachment_mappings(source: str) -> List[Dict[str, Any]]:
    """Describe scalar field mappings, preserving complex values as read-only."""
    result = []
    for index, node in enumerate(_attachments(source)):
        props = _mapping(node)
        template = props.get("pdf template file", props.get("docx template file"))
        fields = props.get("fields")
        rows = []
        if fields is not None:
            groups = fields.value if isinstance(fields, SequenceNode) else [fields]
            seen = set()
            for group in groups:
                for name, value in _mapping(group).items():
                    if name in seen:
                        raise ValueError(
                            "Use YAML mode for repeated attachment fields."
                        )
                    seen.add(name)
                    scalar = (
                        isinstance(value, ScalarNode)
                        and value.tag == "tag:yaml.org,2002:str"
                    )
                    rows.append(
                        {
                            "name": name,
                            "value": (
                                value.value
                                if scalar
                                else source[
                                    value.start_mark.index : value.end_mark.index
                                ]
                            ),
                            "editable": scalar,
                        }
                    )
        result.append(
            {
                "index": index,
                "template": template.value if isinstance(template, ScalarNode) else "",
                "kind": "pdf" if "pdf template file" in props else "docx",
                "rows": rows,
                "dynamic": any(
                    key in props
                    for key in (
                        "code",
                        "field code",
                        "field variables",
                        "raw field variables",
                    )
                ),
            }
        )
    return result


def update_attachment_mappings(source: str, updates: list) -> str:
    """Patch scalar values or append missing fields without reserializing YAML."""
    nodes = _attachments(source)
    patches = []
    seen = set()
    for update in updates:
        if not isinstance(update, dict):
            raise ValueError("Each attachment update must be an object.")
        index = update.get("index")
        values = update.get("values")
        if type(index) is not int or not 0 <= index < len(nodes) or index in seen:
            raise ValueError("Invalid or repeated attachment index.")
        seen.add(index)
        if not isinstance(values, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()
        ):
            raise ValueError("Field names and values must be strings.")
        if not values:
            continue
        node = nodes[index]
        props = _mapping(node)
        fields = props.get("fields")
        entries = {}
        if fields is not None:
            groups = fields.value if isinstance(fields, SequenceNode) else [fields]
            if not isinstance(fields, (MappingNode, SequenceNode)) or (
                fields.flow_style and fields.value
            ):
                raise ValueError("Use YAML mode for flow-style fields.")
            for group in groups:
                for name, value in _mapping(group).items():
                    if name in entries:
                        raise ValueError("Repeated field name.")
                    entries[name] = value
        additions = {}
        for name, value in values.items():
            if name not in entries:
                additions[name] = value
                continue
            old = entries[name]
            if not isinstance(old, ScalarNode) or old.tag != "tag:yaml.org,2002:str":
                raise ValueError("Complex or typed values must be edited in YAML mode.")
            if old.value == value:
                continue
            replacement = json.dumps(value, ensure_ascii=False)
            # Block scalars include their final newline; preserve the next key's line.
            if old.style in ("|", ">"):
                header = source[
                    old.start_mark.index : source.find("\n", old.start_mark.index)
                ]
                if "#" in header:
                    replacement += " " + header[header.index("#") :]
                replacement += "\n"
            patches.append((old.start_mark.index, old.end_mark.index, replacement))
        if additions:
            if fields is not None and not fields.value:
                field_key = next(
                    key for key, value in node.value if key.value == "fields"
                )
                indentation = " " * (field_key.start_mark.column + 2)
                added = "\n" + "\n".join(
                    indentation
                    + "- "
                    + json.dumps(name, ensure_ascii=False)
                    + ": "
                    + json.dumps(value, ensure_ascii=False)
                    for name, value in additions.items()
                )
                patches.append((fields.start_mark.index, fields.end_mark.index, added))
                continue
            if fields is None:
                last = node.value[-1][1]
                indent = node.value[0][0].start_mark.column
                added = " " * indent + "fields:\n"
                field_indent = indent + 2
                sequence = True
            else:
                last = (
                    fields.value[-1]
                    if isinstance(fields, SequenceNode)
                    else fields.value[-1][1]
                )
                field_indent = fields.start_mark.column
                sequence = isinstance(fields, SequenceNode)
                added = ""
            while isinstance(last, (MappingNode, SequenceNode)) and last.value:
                last = (
                    last.value[-1][1]
                    if isinstance(last, MappingNode)
                    else last.value[-1]
                )
            end = last.end_mark.index
            # Append after the last entry's inline comment, before any following key.
            if end and source[end - 1] != "\n":
                newline = source.find("\n", end)
                end = len(source) if newline < 0 else newline + 1
            if end and source[end - 1] != "\n":
                added = "\n" + added
            for name, value in additions.items():
                added += (
                    " " * field_indent
                    + ("- " if sequence else "")
                    + json.dumps(name, ensure_ascii=False)
                    + ": "
                    + json.dumps(value, ensure_ascii=False)
                    + "\n"
                )
            patches.append((end, end, added))
    for start, end, replacement in sorted(patches, reverse=True):
        source = source[:start] + replacement + source[end:]
    yaml.safe_load(source)
    return source


def remove_attachment(source: str, document_name: str) -> str:
    """Remove matching attachment entries while retaining a containing question."""
    nodes = _attachments(source)
    targets = []
    for node in nodes:
        variable = _mapping(node).get("variable name")
        if isinstance(variable, ScalarNode) and re.match(
            r"^" + re.escape(document_name) + r"(?:\[|\.|$)", variable.value
        ):
            targets.append(node)
    if not targets:
        return source
    root = yaml.compose(source)
    key, attachment = next(
        (key, value)
        for key, value in root.value
        if key.value in ("attachment", "attachments")
    )
    if len(targets) == len(nodes):
        spans = [(key, attachment)]
    else:
        spans = [(node, node) for node in targets]
    patches = []
    for first, last in spans:
        start = source.rfind("\n", 0, first.start_mark.index) + 1
        while isinstance(last, (MappingNode, SequenceNode)) and last.value:
            last = (
                last.value[-1][1] if isinstance(last, MappingNode) else last.value[-1]
            )
        end = last.end_mark.index
        if end and source[end - 1] != "\n":
            newline = source.find("\n", end)
            end = len(source) if newline < 0 else newline + 1
        patches.append((start, end))
    expected = yaml.safe_load(source)
    if len(targets) == len(nodes):
        del expected[key.value]
    else:
        expected[key.value] = [
            item
            for index, item in enumerate(expected[key.value])
            if nodes[index] not in targets
        ]
    for start, end in sorted(patches, reverse=True):
        source = source[:start] + source[end:]
    if (yaml.safe_load(source) or {}) != expected:
        raise ValueError("Use YAML mode to remove this attachment safely.")
    return source

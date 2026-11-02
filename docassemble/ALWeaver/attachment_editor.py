"""Read attachment mappings and patch only the values an author edits."""

import json
import re
from typing import Any, Dict, List, Tuple

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


def attachment_matches(variable_name: Any, document_name: str) -> bool:
    """True when an attachment's ``variable name`` assigns this document.

    Callers that select attachments and callers that remove them must agree
    about this: a block one selects and the other declines to touch would be
    rewritten forever.
    """
    return bool(
        re.match(
            r"^" + re.escape(document_name) + r"(?:\[|\.|$)",
            str(variable_name or "").strip(),
        )
    )


def _blank(node) -> bool:
    """True when a key is absent or written with no value at all (``fields:``)."""
    return node is None or (
        isinstance(node, ScalarNode) and node.tag == "tag:yaml.org,2002:null"
    )


STR_TAG = "tag:yaml.org,2002:str"
BOOL_TAG = "tag:yaml.org,2002:bool"
NULL_TAG = "tag:yaml.org,2002:null"

# Settings the graphical attachment editor may write. Everything else an
# attachment carries is shown read-only and edited in YAML mode.
TEXT_SETTINGS = (
    "name",
    "filename",
    "description",
    "variable name",
    "language",
    "pdf template file",
    "docx template file",
)
# Choosing a template only replaces the file an attachment already uses: adding
# a second template key would change what kind of attachment it is.
EXISTING_ONLY_SETTINGS = ("pdf template file", "docx template file")
BOOL_SETTINGS = ("editable", "pdf/a", "tagged pdf", "skip undefined")
LIST_SETTINGS = ("valid formats",)
VALID_FORMATS = ("pdf", "docx", "rtf", "rtf to docx", "tex", "html", "md", "raw")


def _is_true(node) -> bool:
    return str(node.value).strip().lower() in ("true", "yes", "on", "y")


def _describe_setting(source: str, key: str, node) -> Dict[str, Any]:
    """Report one attachment key so the editor can show or edit it."""
    if isinstance(node, ScalarNode):
        kind = {
            STR_TAG: "str",
            BOOL_TAG: "bool",
            NULL_TAG: "null",
        }.get(node.tag, "scalar")
        result: Dict[str, Any] = {"key": key, "type": kind, "value": node.value}
        if kind == "bool":
            result["value"] = _is_true(node)
        elif kind == "null":
            result["value"] = ""
        return result
    if (
        isinstance(node, SequenceNode)
        and node.value
        and all(
            isinstance(item, ScalarNode) and item.tag == STR_TAG for item in node.value
        )
    ):
        result = {
            "key": key,
            "type": "list",
            "value": [item.value for item in node.value],
        }
        if "#" in source[node.start_mark.index : _list_end(node)]:
            # Rewriting the list would drop these; it stays a YAML-mode edit.
            result["commented"] = True
        return result
    return {
        "key": key,
        "type": "complex",
        "value": source[node.start_mark.index : node.end_mark.index].rstrip(),
    }


def _list_end(node) -> int:
    """End of a sequence's own text: a block list's end mark is the next key."""
    return node.end_mark.index if node.flow_style else node.value[-1].end_mark.index


def _end_of_node(source: str, node) -> int:
    """Index just past a node's last line, including any inline comment."""
    last = node
    while isinstance(last, (MappingNode, SequenceNode)) and last.value:
        last = last.value[-1][1] if isinstance(last, MappingNode) else last.value[-1]
    end = last.end_mark.index
    if end and source[end - 1] != "\n":
        newline = source.find("\n", end)
        end = len(source) if newline < 0 else newline + 1
    return end


def _scalar_patch(source: str, old, replacement: str):
    """Replace a scalar's text, keeping a block scalar's trailing newline."""
    if old.style in ("|", ">"):
        header = source[old.start_mark.index : source.find("\n", old.start_mark.index)]
        if "#" in header:
            replacement += " " + header[header.index("#") :]
        replacement += "\n"
    return (old.start_mark.index, old.end_mark.index, replacement)


def _setting_text(key: str, value: Any) -> str:
    if key in TEXT_SETTINGS:
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text.")
        if key in EXISTING_ONLY_SETTINGS:
            if not value.strip():
                raise ValueError(f"Choose a file for {key}.")
            wanted = "." + key.split()[0]
            other = ".docx" if wanted == ".pdf" else ".pdf"
            if value.strip().lower().endswith(other):
                raise ValueError(f"A {key} must be a {wanted} file.")
        return json.dumps(value, ensure_ascii=False)
    if key in BOOL_SETTINGS:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be on or off.")
        return "True" if value else "False"
    if key in LIST_SETTINGS:
        if (
            not isinstance(value, list)
            or not value
            or any(item not in VALID_FORMATS for item in value)
            or len(set(value)) != len(value)
        ):
            raise ValueError("Choose at least one valid file format.")
        return json.dumps(value, ensure_ascii=False)
    raise ValueError(f"Edit {key} in YAML mode.")


def _setting_patches(source: str, node, settings: Dict[str, Any]) -> list:
    """Patches that write the requested settings into one attachment mapping."""
    props = _mapping(node)
    keys = {key.value: key for key, _ in node.value}
    patches = []
    additions = []
    for name, value in settings.items():
        text = _setting_text(name, value)
        old = props.get(name)
        if old is None:
            if name in EXISTING_ONLY_SETTINGS:
                raise ValueError(f"Edit {name} in YAML mode.")
            # Only whitelisted keys reach here, all plain YAML scalars.
            additions.append(name + ": " + text)
            continue
        if (
            isinstance(old, ScalarNode)
            and old.tag == NULL_TAG
            and (old.start_mark.index == old.end_mark.index)
        ):
            patches.append((old.start_mark.index, old.end_mark.index, " " + text))
            continue
        if name in LIST_SETTINGS:
            if not isinstance(old, SequenceNode) or not old.value:
                raise ValueError(f"Edit {name} in YAML mode.")
            end = _list_end(old)
            if "#" in source[keys[name].end_mark.index : end]:
                raise ValueError(f"{name} has comments; edit it in YAML mode.")
            patches.append((keys[name].end_mark.index, end, ": " + text))
            continue
        expected_tag = BOOL_TAG if name in BOOL_SETTINGS else STR_TAG
        if not isinstance(old, ScalarNode) or old.tag not in (expected_tag, NULL_TAG):
            raise ValueError(f"{name} is computed; edit it in YAML mode.")
        patches.append(_scalar_patch(source, old, text))
    if additions:
        if not node.value:
            raise ValueError("Use YAML mode to add settings to an empty attachment.")
        end = _end_of_node(source, node)
        indent = " " * node.value[0][0].start_mark.column
        added = "" if not end or source[end - 1] == "\n" else "\n"
        added += "".join(indent + line + "\n" for line in additions)
        patches.append((end, end, added))
    return patches


def _loaded_attachments(document) -> list:
    value = document.get("attachment", document.get("attachments"))
    return value if isinstance(value, list) else [value]


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
        if not _blank(fields):
            if not isinstance(fields, (MappingNode, SequenceNode)):
                raise ValueError("Use YAML mode for computed attachment fields.")
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
                "kind": (
                    "pdf"
                    if "pdf template file" in props
                    else "docx" if "docx template file" in props else "other"
                ),
                "rows": rows,
                "settings": [
                    _describe_setting(source, key, value)
                    for key, value in props.items()
                    if key != "fields"
                ],
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
    """Patch field values and simple settings without reserializing YAML.

    Each update names an attachment ``index`` and carries ``values`` (template
    field to text or Mako) and/or ``settings`` (attachment key to new value).
    """
    original = source
    nodes = _attachments(source)
    patches: List[Tuple[int, int, int, str]] = []
    setting_updates = {}
    seen = set()
    for update in updates:
        if not isinstance(update, dict):
            raise ValueError("Each attachment update must be an object.")
        index = update.get("index")
        values = update.get("values", {})
        settings = update.get("settings", {})
        if type(index) is not int or not 0 <= index < len(nodes) or index in seen:
            raise ValueError("Invalid or repeated attachment index.")
        seen.add(index)
        if not isinstance(values, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()
        ):
            raise ValueError("Field names and values must be strings.")
        if not isinstance(settings, dict):
            raise ValueError("Attachment settings must be an object.")
        node = nodes[index]
        if settings:
            setting_updates[index] = settings
            patches.extend(
                (start, end, 1, text)
                for start, end, text in _setting_patches(source, node, settings)
            )
        if not values:
            continue
        props = _mapping(node)
        fields = props.get("fields")
        entries = {}
        if not _blank(fields):
            if not isinstance(fields, (MappingNode, SequenceNode)) or (
                fields.flow_style and fields.value
            ):
                raise ValueError("Use YAML mode for computed or flow-style fields.")
            groups = fields.value if isinstance(fields, SequenceNode) else [fields]
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
            # Block scalars include their final newline; preserve the next key's line.
            start, end, text = _scalar_patch(
                source, old, json.dumps(value, ensure_ascii=False)
            )
            patches.append((start, end, 0, text))
        if additions:
            if fields is not None and (_blank(fields) or not fields.value):
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
                patches.append(
                    (fields.start_mark.index, fields.end_mark.index, 0, added)
                )
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
            patches.append((end, end, 0, added))
    # At one insertion point new fields come before new settings, so a setting
    # appended after the field list never ends up inside it.
    for start, end, _, replacement in sorted(
        patches, key=lambda patch: (patch[0], patch[2]), reverse=True
    ):
        source = source[:start] + replacement + source[end:]
    updated = yaml.safe_load(source)
    if setting_updates:
        expected = yaml.safe_load(original)
        for index, settings in setting_updates.items():
            _loaded_attachments(expected)[index].update(settings)
        for document in (expected, updated):
            for attachment in _loaded_attachments(document):
                if isinstance(attachment, dict):
                    attachment.pop("fields", None)
        if expected != updated:
            raise ValueError("Use YAML mode to change these attachment settings.")
    return source


def remove_attachment(source: str, document_name: str) -> str:
    """Remove matching attachment entries while retaining a containing question."""
    nodes = _attachments(source)
    targets = []
    for node in nodes:
        variable = _mapping(node).get("variable name")
        if isinstance(variable, ScalarNode) and attachment_matches(
            variable.value, document_name
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

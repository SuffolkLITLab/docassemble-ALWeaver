# do not pre-load

"""Read and edit the documents an interview assembles.

AssemblyLine puts every finished document in an ``ALDocument``, and groups them
into ``ALDocumentBundle`` objects whose ``elements`` list is the order they come
out in and whose ``enabled`` expression decides whether they come out at all.
Both live inside ``.using()`` calls in an ``objects:`` block, which is a Python
expression inside a YAML string -- not something an author should have to hand
edit to move a cover sheet above a petition.

The edits here are deliberately surgical: they rewrite one keyword argument
inside one declaration and leave the rest of the block's text, including its
comments, exactly as it was.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .editor_utils import (
    BLOCK_TYPE_ATTACHMENT,
    BLOCK_TYPE_OBJECTS,
    BLOCK_TYPE_TEMPLATE,
    _split_top_level_commas,
    parse_interview_yaml,
    update_block_in_yaml,
)

__all__ = [
    "BundleEntry",
    "DocumentEntry",
    "InterviewDocuments",
    "interview_documents",
    "set_bundle_elements",
    "set_enabled_expression",
]

_ROOT_OF_REFERENCE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)")
_USING_RE = re.compile(
    r"^(?P<class_name>[A-Za-z_][A-Za-z0-9_.]*)\.using\((?P<args>[\s\S]*)\)$"
)


@dataclass
class DocumentEntry:
    """One ``ALDocument`` an interview assembles."""

    name: str
    #: The `objects:` block the declaration lives in.
    block_id: Optional[str]
    declaration: str
    #: The template the matching `attachment` block fills, when there is one.
    template_filename: str = ""
    attachment_block_id: Optional[str] = None
    #: The `enabled=` expression, or "" when the declaration leaves it out.
    enabled: str = ""
    title: str = ""


@dataclass
class BundleEntry:
    """One ``ALDocumentBundle``: an ordered, switchable group of documents."""

    name: str
    block_id: Optional[str]
    declaration: str
    elements: List[str] = field(default_factory=list)
    enabled: str = ""
    title: str = ""


@dataclass
class InterviewDocuments:
    """Everything the Templates tab needs to show what a template becomes."""

    documents: List[DocumentEntry] = field(default_factory=list)
    bundles: List[BundleEntry] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return the model in the shape the editor API sends over the wire.

        Returns:
            Dict[str, Any]: a JSON-serializable copy.
        """
        return {
            "documents": [
                {
                    "name": document.name,
                    "block_id": document.block_id,
                    "declaration": document.declaration,
                    "template_filename": document.template_filename,
                    "attachment_block_id": document.attachment_block_id,
                    "enabled": document.enabled,
                    "title": document.title,
                }
                for document in self.documents
            ],
            "bundles": [
                {
                    "name": bundle.name,
                    "block_id": bundle.block_id,
                    "declaration": bundle.declaration,
                    "elements": list(bundle.elements),
                    "enabled": bundle.enabled,
                    "title": bundle.title,
                }
                for bundle in self.bundles
            ],
        }


def reference_root(reference: Any) -> Optional[str]:
    """Return the assignable part of a variable reference.

    Args:
        reference (Any): something like ``users[0].name.first``.

    Returns:
        Optional[str]: the leading identifier, or None if there isn't one.
    """
    match = _ROOT_OF_REFERENCE_RE.match(str(reference or "").strip())
    return match.group(1) if match else None


def objects_declarations(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Pull ``(variable, expression)`` pairs out of a parsed objects block.

    Args:
        data (Dict[str, Any]): the parsed block.

    Returns:
        List[Tuple[str, str]]: the declarations, in source order.
    """
    objects = data.get("objects")
    if isinstance(objects, dict):
        return [(str(name), str(value)) for name, value in objects.items()]
    declarations: List[Tuple[str, str]] = []
    if isinstance(objects, list):
        for item in objects:
            if isinstance(item, dict):
                declarations.extend(
                    (str(name), str(value)) for name, value in item.items()
                )
    return declarations


def _keyword_value(expression: str, keyword: str) -> str:
    match = _USING_RE.match(str(expression or "").strip())
    if not match:
        return ""
    for argument in _split_top_level_commas(match.group("args")):
        name, separator, value = argument.partition("=")
        if separator and name.strip() == keyword:
            return value.strip()
    return ""


def _with_keyword(expression: str, keyword: str, value: Optional[str]) -> str:
    """Set, replace, or drop one keyword argument of a ``.using()`` call.

    Args:
        expression (str): the object declaration.
        keyword (str): the argument to change.
        value (Optional[str]): its new source text, or None to remove it.

    Returns:
        str: the rewritten declaration.

    Raises:
        ValueError: when the declaration is not a ``.using()`` call, which is
            the only form these edits understand.
    """
    text = str(expression or "").strip()
    match = _USING_RE.match(text)
    if not match:
        raise ValueError(
            f"{text!r} is not a .using() declaration, so Weaver cannot edit it here."
        )
    class_name = match.group("class_name")
    arguments = [
        argument.strip()
        for argument in _split_top_level_commas(match.group("args"))
        if argument.strip()
    ]
    rewritten: List[str] = []
    replaced = False
    for argument in arguments:
        name, separator, _old = argument.partition("=")
        if separator and name.strip() == keyword:
            replaced = True
            if value is not None:
                rewritten.append(f"{keyword}={value}")
            continue
        rewritten.append(argument)
    if not replaced and value is not None:
        rewritten.append(f"{keyword}={value}")
    if not rewritten:
        return class_name
    return f"{class_name}.using({', '.join(rewritten)})"


def _entry_span(block_yaml: str, name: str) -> Optional[Tuple[int, int, str]]:
    """Find the source lines of one ``- name: expression`` entry.

    Args:
        block_yaml (str): the objects block's text.
        name (str): the variable being declared.

    Returns:
        Optional[Tuple[int, int, str]]: the first line index, the line index
        after the entry, and the entry's leading ``- name: `` text.
    """
    lines = block_yaml.splitlines()
    pattern = re.compile(
        rf"""^(?P<lead>\s*-\s*(?:"|')?{re.escape(name)}(?:"|')?\s*:\s*)(?P<value>.*)$"""
    )
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        indent = len(line) - len(line.lstrip())
        end = index + 1
        while end < len(lines):
            following = lines[end]
            if not following.strip():
                break
            following_indent = len(following) - len(following.lstrip())
            if following_indent <= indent:
                break
            end += 1
        return index, end, match.group("lead")
    return None


def _rewrite_declaration_in_block(
    block_yaml: str, name: str, new_declaration: str
) -> str:
    """Replace one declaration's expression, leaving the rest of the block alone.

    Args:
        block_yaml (str): the objects block's text.
        name (str): the variable being declared.
        new_declaration (str): the expression to put there.

    Returns:
        str: the block's text with that one entry rewritten.

    Raises:
        ValueError: when the block has no such declaration.
    """
    span = _entry_span(block_yaml, name)
    if span is None:
        raise ValueError(f"{name} is not declared in this block.")
    start, end, lead = span
    lines = block_yaml.splitlines()
    return "\n".join(lines[:start] + [lead + new_declaration] + lines[end:])


def _find_declaration(
    raw_yaml: str, name: str
) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """Locate the objects block that declares a variable.

    Args:
        raw_yaml (str): the interview's YAML source.
        name (str): the variable to find.

    Returns:
        Tuple[Optional[str], str, Dict[str, Any]]: the block id, the current
        declaration, and the raw block entry.

    Raises:
        ValueError: when nothing declares the variable.
    """
    for entry in parse_interview_yaml(raw_yaml)["blocks"]:
        data = entry.get("data")
        if not isinstance(data, dict) or entry.get("type") != BLOCK_TYPE_OBJECTS:
            continue
        for declared_name, declaration in objects_declarations(data):
            if declared_name == name:
                return entry.get("id"), declaration, entry
    raise ValueError(f"{name} is not declared in this interview.")


def interview_documents(raw_yaml: str) -> InterviewDocuments:
    """Read the documents and bundles an interview declares.

    Args:
        raw_yaml (str): the interview's YAML source.

    Returns:
        InterviewDocuments: the documents, the bundles, and how they connect.
    """
    model = parse_interview_yaml(raw_yaml)
    documents: List[DocumentEntry] = []
    bundles: List[BundleEntry] = []
    titles: Dict[str, str] = {}
    attachments: Dict[str, Tuple[str, Optional[str]]] = {}

    for entry in model["blocks"]:
        data = entry.get("data")
        if not isinstance(data, dict) or data.get("_commented"):
            continue
        block_type = entry.get("type")
        if block_type == BLOCK_TYPE_TEMPLATE:
            template_name = str(data.get("template") or "").strip()
            if template_name.endswith(".title"):
                titles[template_name[: -len(".title")]] = str(
                    data.get("content") or ""
                ).strip()
        elif block_type == BLOCK_TYPE_ATTACHMENT:
            attachment = data.get("attachment")
            if not isinstance(attachment, dict):
                attachment = data
            root = reference_root(attachment.get("variable name"))
            if root:
                attachments[root] = (
                    str(
                        attachment.get("pdf template file")
                        or attachment.get("docx template file")
                        or ""
                    ).strip(),
                    entry.get("id"),
                )

    for entry in model["blocks"]:
        data = entry.get("data")
        if not isinstance(data, dict) or entry.get("type") != BLOCK_TYPE_OBJECTS:
            continue
        if data.get("_commented"):
            continue
        for name, declaration in objects_declarations(data):
            if "ALDocumentBundle" in declaration:
                elements_text = _keyword_value(declaration, "elements").strip()
                elements = [
                    element.strip()
                    for element in elements_text.strip("[]").split(",")
                    if element.strip()
                ]
                bundles.append(
                    BundleEntry(
                        name=name,
                        block_id=entry.get("id"),
                        declaration=declaration,
                        elements=elements,
                        enabled=_keyword_value(declaration, "enabled"),
                        title=titles.get(name, ""),
                    )
                )
            elif "ALDocument" in declaration:
                template_filename, attachment_block_id = attachments.get(
                    name, ("", None)
                )
                documents.append(
                    DocumentEntry(
                        name=name,
                        block_id=entry.get("id"),
                        declaration=declaration,
                        template_filename=template_filename,
                        attachment_block_id=attachment_block_id,
                        enabled=_keyword_value(declaration, "enabled"),
                        title=titles.get(name, ""),
                    )
                )
    return InterviewDocuments(documents=documents, bundles=bundles)


def set_bundle_elements(
    raw_yaml: str, bundle_name: str, elements: Sequence[str]
) -> str:
    """Put a bundle's documents in a given order.

    Args:
        raw_yaml (str): the interview's YAML source.
        bundle_name (str): the bundle to reorder.
        elements (Sequence[str]): the document variables, in the order they
            should be assembled.

    Returns:
        str: the interview's YAML with that bundle rewritten.

    Raises:
        ValueError: when the bundle is missing, or an element is not a variable
            name.
    """
    cleaned: List[str] = []
    for element in elements:
        name = str(element or "").strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            raise ValueError(f"{name!r} is not a document variable name.")
        if name not in cleaned:
            cleaned.append(name)
    block_id, declaration, entry = _find_declaration(raw_yaml, bundle_name)
    updated = _with_keyword(declaration, "elements", "[" + ", ".join(cleaned) + "]")
    block_yaml = _rewrite_declaration_in_block(
        str(entry.get("yaml") or ""), bundle_name, updated
    )
    return update_block_in_yaml(raw_yaml, str(block_id), block_yaml)


def set_enabled_expression(raw_yaml: str, name: str, expression: Optional[str]) -> str:
    """Set the rule that decides whether a document or bundle is assembled.

    Args:
        raw_yaml (str): the interview's YAML source.
        name (str): the ``ALDocument`` or ``ALDocumentBundle`` variable.
        expression (Optional[str]): the Python expression to use, or None to
            leave the decision to AssemblyLine's default.

    Returns:
        str: the interview's YAML with that declaration rewritten.

    Raises:
        ValueError: when nothing declares the variable, or the expression is
            not something that can be evaluated.
    """
    cleaned = None if expression is None else str(expression).strip()
    if cleaned == "":
        cleaned = None
    if cleaned is not None:
        if "\n" in cleaned:
            raise ValueError("An enabled rule has to be a single expression.")
        try:
            compile(cleaned, "<enabled>", "eval")
        except SyntaxError as exc:
            raise ValueError(f"{cleaned!r} is not a valid Python expression.") from exc
    block_id, declaration, entry = _find_declaration(raw_yaml, name)
    updated = _with_keyword(declaration, "enabled", cleaned)
    block_yaml = _rewrite_declaration_in_block(
        str(entry.get("yaml") or ""), name, updated
    )
    return update_block_in_yaml(raw_yaml, str(block_id), block_yaml)

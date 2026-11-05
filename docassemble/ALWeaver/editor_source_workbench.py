"""Read-only previews for source-mode operations; the browser owns application.

Nothing in this module writes a Playground file or executes interview code.
All edits are exact text spans, with UTF-16 offsets for CodeMirror.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List

from .source_document import parse_source_document, source_revision, unified_source_diff


def _playground_examples() -> List[Dict[str, Any]]:
    from importlib import import_module

    # Docassemble moved Playground helpers out of server.py in newer releases.
    try:
        module = import_module("docassemble.webapp.develop.helpers")
    except ModuleNotFoundError as exc:
        if exc.name not in {
            "docassemble.webapp.develop",
            "docassemble.webapp.develop.helpers",
        }:
            raise
        module = import_module("docassemble.webapp.server")
    return module.get_examples()


def playground_recipes() -> List[Dict[str, Any]]:
    """Use the installed Playground catalog, including configured package examples.

    Keep its category hierarchy and selected example ranges. Do not send the
    server's highlighted HTML to the client; source and context are plain text.
    """
    from html.parser import HTMLParser

    class PlainText(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: List[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    def plain(html: str) -> str:
        parser = PlainText()
        parser.feed(html)
        return "".join(parser.parts)

    def convert(
        entries: List[Dict[str, Any]], prefix: str = ""
    ) -> List[Dict[str, Any]]:
        result = []
        for index, entry in enumerate(entries):
            identifier = f"{prefix}{index}"
            node: Dict[str, Any] = {
                "id": identifier,
                "title": str(entry.get("title", "Untitled")),
            }
            if "list" in entry:
                node["children"] = convert(entry["list"], identifier + "/")
            else:
                node.update(
                    source=entry.get("source", ""),
                    documentation=entry.get("documentation"),
                    interview=entry.get("interview"),
                    before=plain(entry.get("before_html", "")),
                    after=plain(entry.get("after_html", "")),
                )
            result.append(node)
        return result

    return convert(_playground_examples())


def utf16_offset(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def python_offset(text: str, offset: int) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("The source cursor must be a non-negative integer")
    encoded = text.encode("utf-16-le")
    if offset * 2 > len(encoded):
        raise ValueError("The source cursor is outside the submitted source")
    try:
        return len(encoded[: offset * 2].decode("utf-16-le"))
    except UnicodeDecodeError as exc:
        raise ValueError("The source cursor splits a Unicode character") from exc


def source_changes(saved: str, working: str) -> List[Dict[str, Any]]:
    """Offer independently reversible line hunks against this exact buffer."""
    old = saved.splitlines(keepends=True)
    new = working.splitlines(keepends=True)
    starts = [0]
    for line in new:
        starts.append(starts[-1] + utf16_offset(line))
    return [
        {
            "from": starts[j1],
            "to": starts[j2],
            "before": "".join(new[j1:j2]),
            "insert": "".join(old[i1:i2]),
            "line": j1 + 1,
            "diff": "".join(
                difflib.unified_diff(
                    old[i1:i2], new[j1:j2], fromfile="saved", tofile="working"
                )
            ),
        }
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, old, new, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]


def preview_source_action(
    filename: str, saved: str, working: str, action: str, **options: Any
) -> Dict[str, Any]:
    """Return a proposal. Saving still uses the normal revision-aware API."""
    base = {"source_revision": source_revision(working)}
    if action == "diff":
        return {
            **base,
            "diff": unified_source_diff(saved, working, filename),
            "hunks": source_changes(saved, working),
            "saved_source": saved,
        }
    if action == "recipes":
        return {**base, "recipes": playground_recipes()}
    if action == "repair":
        from .editor_agent_repair import preview_id_repairs

        repair = preview_id_repairs(filename=filename, raw_yaml=working)
        return {
            **base,
            **repair.public_dict(),
            "source": repair.raw_yaml,
            "diff": unified_source_diff(working, repair.raw_yaml, filename),
        }
    if action == "outline":
        from .editor_utils import parse_interview_yaml

        document = parse_source_document(filename, working)
        if not document.structurally_valid:
            raise ValueError("Fix the YAML syntax before refreshing the source outline")
        blocks = parse_interview_yaml(working).get("blocks", [])
        return {
            **base,
            "blocks": [
                {
                    key: block.get(key)
                    for key in (
                        "id",
                        "title",
                        "type",
                        "variable",
                        "line_start",
                        "line_end",
                    )
                }
                for block in blocks
            ],
        }
    if action == "insert-block":
        snippet = options.get("block_yaml")
        if not isinstance(snippet, str) or not snippet.strip():
            raise ValueError("Choose a block or example to insert")
        if len(snippet.encode("utf-8")) > 1024 * 1024:
            raise ValueError("The block is too large to insert")
        document = parse_source_document(filename, working)
        if not document.structurally_valid:
            raise ValueError("Fix the YAML syntax before inserting a block")
        existing_ids = {
            str(b.parsed_value["id"])
            for b in document.documents
            if isinstance(b.parsed_value, dict) and "id" in b.parsed_value
        }
        recipe_document = parse_source_document(filename, snippet)
        if any(
            isinstance(b.parsed_value, dict)
            and str(b.parsed_value.get("id")) in existing_ids
            for b in recipe_document.documents
        ):
            raise ValueError(
                "Rename the existing block IDs before inserting these blocks again"
            )
        if options.get("at_start") is True:
            # File-level comments such as '# use jinja' must stay first.
            offset = 0
            for line in working.splitlines(keepends=True):
                if line.strip() and not line.lstrip().startswith("#"):
                    break
                offset += len(line)
            marker = re.match(r"---[ \t]*(?:#[^\n]*)?(?:\n|$)", working[offset:])
            if marker:
                offset += marker.end()
            insert = snippet.rstrip("\n") + "\n"
            if offset and working[offset - 1] != "\n":
                insert = "\n" + insert
            if working[offset:].strip():
                insert += "---\n"
        else:
            cursor = python_offset(working, options.get("cursor", 0))
            block = next(
                (
                    b
                    for b in document.documents
                    if b.start_offset <= cursor <= b.end_offset
                ),
                None,
            )
            if block is None and working.strip():
                raise ValueError(
                    "Place the cursor inside a YAML document before inserting"
                )
            offset = block.end_offset if block else len(working)
            insert = (
                ("\n---\n" if working[:offset].strip() else "")
                + snippet.rstrip("\n")
                + "\n"
            )
        candidate = working[:offset] + insert + working[offset:]
        if not parse_source_document(filename, candidate).structurally_valid:
            raise ValueError(
                "These blocks cannot be inserted at the selected document boundary"
            )
        return {
            **base,
            "source": candidate,
            "diff": unified_source_diff(working, candidate, filename),
            "edit": {
                "from": utf16_offset(working[:offset]),
                "to": utf16_offset(working[:offset]),
                "before": "",
                "insert": insert,
            },
        }
    raise ValueError("Unknown source preview action")

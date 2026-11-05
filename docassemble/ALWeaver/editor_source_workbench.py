"""Read-only previews for source-mode operations; the browser owns application.

Nothing in this module writes a Playground file or executes interview code.
All edits are exact text spans, with UTF-16 offsets for CodeMirror.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List

from .source_document import parse_source_document, source_revision, unified_source_diff

RECIPES = [
    {
        "id": "computed-choices",
        "title": "Computed choices",
        "description": "Build choices in Python, then ask a question using that list. Rename the example variables for your interview.",
        "documentation": "https://docassemble.org/docs/fields.html#choices",
        "dependencies": "Core docassemble; no additional package.",
        "source": "id: example choices data\ncode: |\n  example_options = ['One', 'Two', 'Three']\n---\nid: example choices question\nquestion: Choose an option\nfields:\n  - Option: example_choice\n    choices: example_options\n",
    },
    {
        "id": "review-screen",
        "title": "Review screen",
        "description": "An event screen that lets the user revisit an answer. Replace example_answer with a variable your interview gathers.",
        "documentation": "https://docassemble.org/docs/fields.html#review",
        "dependencies": "A question defining example_answer; link to example_review with an action button.",
        "source": "id: example review screen\nevent: example_review\nquestion: Review your answers\nreview:\n  - Edit answer: example_answer\n",
    },
    {
        "id": "list-collect",
        "title": "Collect a list of items",
        "description": "Declare a list and collect each item's name. Use example_items.gather() in your interview order when you want to gather it.",
        "documentation": "https://docassemble.org/docs/groups.html#list%20collect",
        "dependencies": "Core docassemble DAList and DAObject classes.",
        "source": "objects:\n  - example_items: DAList.using(object_type=DAObject, there_are_any=True)\n---\nid: example item name\nquestion: Tell us about an item\nfields:\n  - Name: example_items[i].name\nlist collect: True\n---\nid: example more items\nquestion: Are there more items?\nyesno: example_items.there_is_another\n",
    },
    {
        "id": "text-template",
        "title": "Reusable text template",
        "description": "Define reusable text and include it with ${ example_text } in a question or document.",
        "documentation": "https://docassemble.org/docs/initial.html#template",
        "dependencies": "Core docassemble; no additional package.",
        "source": "id: example text template\ntemplate: example_text\ncontent: |\n  Replace this paragraph with text you want to reuse.\n",
    },
]


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
        return {**base, "recipes": RECIPES}
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
    if action == "recipe":
        recipe = next((r for r in RECIPES if r["id"] == options.get("recipe_id")), None)
        if recipe is None:
            raise ValueError("Choose a known source recipe")
        document = parse_source_document(filename, working)
        if not document.structurally_valid:
            raise ValueError("Fix the YAML syntax before inserting a recipe")
        existing_ids = {
            str(b.parsed_value["id"])
            for b in document.documents
            if isinstance(b.parsed_value, dict) and "id" in b.parsed_value
        }
        recipe_document = parse_source_document(filename, recipe["source"])
        if any(
            isinstance(b.parsed_value, dict)
            and str(b.parsed_value.get("id")) in existing_ids
            for b in recipe_document.documents
        ):
            raise ValueError(
                "Rename the existing example block IDs before inserting this recipe again"
            )
        cursor = python_offset(working, options.get("cursor", 0))
        block = next(
            (b for b in document.documents if b.start_offset <= cursor <= b.end_offset),
            None,
        )
        if block is None and working.strip():
            raise ValueError("Place the cursor inside a YAML document before inserting")
        offset = block.end_offset if block else len(working)
        insert = ("\n---\n" if working[:offset].strip() else "") + recipe["source"]
        candidate = working[:offset] + insert + working[offset:]
        if not parse_source_document(filename, candidate).structurally_valid:
            raise ValueError(
                "This recipe cannot be inserted at the selected document boundary"
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

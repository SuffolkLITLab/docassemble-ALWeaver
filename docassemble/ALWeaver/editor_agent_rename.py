"""Variable renaming, including flattening a family of fields onto an object.

Renaming is not "find and replace". The same word can be a variable reference
in one place, display prose in another, and a string key handed to a dynamic
lookup in a third. Getting that wrong silently changes what an interview says
or which question it asks.

So this module only rewrites occurrences it can positively recognise as
references. Everything else it found is reported back, and the rename is
refused rather than guessed at. That is what makes the operation safe enough to
hand to a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .source_document import SourceBlock, parse_source_document

# Reference-position classifications.
CONTEXT_CODE = "code"
CONTEXT_MAKO = "mako_interpolation"
CONTEXT_FIELD = "field_reference"
CONTEXT_LIST_ITEM = "list_reference"
CONTEXT_OBJECT_DEFINITION = "object_definition"

# Why an occurrence is not rewritten. These split two very different cases:
# something that is definitely not a reference is simply left alone, while
# something that might be a reference and cannot be told apart blocks the whole
# rename rather than being guessed at.
REASON_DISPLAY_TEXT = "display_text"  # ignored
REASON_UNSUPPORTED_BLOCK = "unsupported_block"  # blocking
REASON_QUOTED_STRING = "quoted_string"  # blocking
REASON_CALL = "call_expression"  # blocking
REASON_PARTIAL_PATH = "partial_path_reference"  # blocking
REASON_UNRECOGNISED = "unrecognised_context"  # blocking
REASON_OBJECT_DECLARATION = "object_declaration"  # blocking

IGNORED_REASONS = frozenset({REASON_DISPLAY_TEXT})

# Top-level keys whose value is Python. A bare identifier here is a reference.
_CODE_KEYS = {"code", "if", "validation code", "initial", "reconsider"}

# Top-level keys whose value is author-facing text. A bare word here is prose;
# only a ${ ... } interpolation is a reference.
_TEXT_KEYS = {
    "question",
    "subquestion",
    "under",
    "help",
    "content",
    "terms",
    "buttons",
    "continue button label",
    "back button label",
}

# `<key>: <variable>` lines where the value is unambiguously a variable.
_REFERENCE_KEYS = {
    "field",
    "edit",
    "sets",
    "need",
    "variable name",
    "generic object",
    "continue button field",
    "depends on",
    "action",
    "show if",
    "hide if",
    "enable if",
    "disable if",
}

# Longhand attributes of a `fields:` entry. Anything else on a `- x: y` line
# inside `fields:` is docassemble's shorthand, where `x` is the label and `y`
# is the variable.
_FIELD_TEXT_SUBKEYS = {
    "label",
    "hint",
    "help",
    "note",
    "html",
    "raw label",
}
_FIELD_OTHER_SUBKEYS = {
    "datatype",
    "choices",
    "default",
    "input type",
    "required",
    "maxlength",
    "minlength",
    "min",
    "max",
    "step",
    "rows",
    "accept",
    "validate",
    "address autocomplete",
    "code",
    "object labeler",
    "exclude",
    "none of the above",
}

# Top-level keys whose value is a list of field entries.
_FIELD_LIST_KEYS = {"fields", "review", "table", "columns"}

# A usable variable reference: a name, optionally indexed by a number or by a
# loop variable (`users[i]`), with attributes. Empty brackets are the notable
# exclusion — `users[0].children[].name` looks plausible and is not valid.
_VALID_REFERENCE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\[(?:[0-9]+|[ijkmn])\]|\.[A-Za-z_][A-Za-z0-9_]*)*$"
)

MAX_REPORTED_OCCURRENCES = 60


@dataclass
class VariableOccurrence:
    """One place the name appears, and whether Weaver may rewrite it."""

    start: int
    end: int
    line: int
    text: str
    excerpt: str
    block_id: Optional[str] = None
    block_type: Optional[str] = None
    context: Optional[str] = None
    safe: bool = False
    reason: Optional[str] = None

    def public_dict(self) -> Dict[str, Any]:
        return {
            "line": self.line,
            "block_id": self.block_id,
            "block_type": self.block_type,
            "context": self.context,
            "safe": self.safe,
            "reason": self.reason,
            "excerpt": self.excerpt,
        }


@dataclass
class RenameAnalysis:
    old_name: str
    new_name: str
    occurrences: List[VariableOccurrence] = field(default_factory=list)

    @property
    def safe_occurrences(self) -> List[VariableOccurrence]:
        return [item for item in self.occurrences if item.safe]

    @property
    def ignored_occurrences(self) -> List[VariableOccurrence]:
        """Appearances that are definitely not references, so left untouched."""
        return [
            item
            for item in self.occurrences
            if not item.safe and item.reason in IGNORED_REASONS
        ]

    @property
    def blocking_occurrences(self) -> List[VariableOccurrence]:
        """Appearances that might be references and cannot be told apart."""
        return [
            item
            for item in self.occurrences
            if not item.safe and item.reason not in IGNORED_REASONS
        ]

    @property
    def blocks_touched(self) -> List[str]:
        seen: List[str] = []
        for item in self.safe_occurrences:
            if item.block_id and item.block_id not in seen:
                seen.append(item.block_id)
        return seen

    def public_dict(self) -> Dict[str, Any]:
        return {
            "old_name": self.old_name,
            "new_name": self.new_name,
            "reference_count": len(self.safe_occurrences),
            "blocks_touched": self.blocks_touched,
            "left_as_display_text": [
                item.public_dict()
                for item in self.ignored_occurrences[:MAX_REPORTED_OCCURRENCES]
            ],
            "unsafe_references": [
                item.public_dict()
                for item in self.blocking_occurrences[:MAX_REPORTED_OCCURRENCES]
            ],
        }


def validate_variable_reference(name: str) -> Optional[str]:
    """Return why ``name`` is unusable as a variable, or None if it is fine."""
    import keyword

    text = str(name or "").strip()
    if not text:
        return "A variable name is required"
    if not _VALID_REFERENCE.match(text):
        return (
            f"{text!r} is not a plain variable reference. Use a name like "
            "users[0].name.first, with no calls, spaces or quotes."
        )
    base = re.split(r"[\[.]", text)[0]
    if keyword.iskeyword(base):
        return f"{base!r} is a reserved Python keyword"
    try:
        from .validate_template_files import matching_reserved_names

        if matching_reserved_names({text}):
            return (
                f"{base!r} already has a different meaning in Python, Docassemble "
                "or the AssemblyLine package"
            )
    except Exception:
        # The reserved-name table is a nicety; its absence must not block a
        # rename that is otherwise well formed.
        pass
    return None


def _line_bounds(raw_yaml: str, offset: int) -> Tuple[int, int]:
    start = raw_yaml.rfind("\n", 0, offset) + 1
    end = raw_yaml.find("\n", offset)
    return (start, len(raw_yaml) if end < 0 else end)


def _inside_quotes(line: str, column: int) -> bool:
    quote: Optional[str] = None
    for char in line[:column]:
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
    return quote is not None


def _inside_interpolation(line: str, column: int) -> bool:
    opened = line.rfind("${", 0, column)
    if opened < 0:
        return False
    return line.find("}", opened, column) < 0


def _top_level_key(source_block: SourceBlock, offset: int) -> Optional[str]:
    for key, source_range in source_block.property_ranges.items():
        if source_range.start.offset <= offset < source_range.end.offset:
            return key
    return None


def _classify(
    raw_yaml: str,
    source_block: Optional[SourceBlock],
    block_id: Optional[str],
    block_type: Optional[str],
    match: "re.Match[str]",
    old_name: str,
    new_name: str,
) -> VariableOccurrence:
    start, end = match.start(), match.end()
    line_start, line_end = _line_bounds(raw_yaml, start)
    line = raw_yaml[line_start:line_end]
    column = start - line_start
    occurrence = VariableOccurrence(
        start=start,
        end=end,
        line=raw_yaml.count("\n", 0, start) + 1,
        text=match.group(0),
        excerpt=line.strip()[:200],
        block_id=block_id,
        block_type=block_type,
    )

    if source_block is None or not source_block.supported:
        occurrence.reason = REASON_UNSUPPORTED_BLOCK
        return occurrence

    following = raw_yaml[end : end + 1]
    if following in {".", "["}:
        # Renaming the head of a longer path would silently retarget an
        # attribute the caller never mentioned.
        occurrence.reason = REASON_PARTIAL_PATH
        return occurrence
    if following == "(":
        occurrence.reason = REASON_CALL
        return occurrence

    key = _top_level_key(source_block, start)
    normalized_key = str(key or "").strip().lower()

    if _inside_interpolation(line, column):
        occurrence.context = CONTEXT_MAKO
        occurrence.safe = True
        return occurrence

    if normalized_key in _CODE_KEYS:
        if _inside_quotes(line, column):
            # A name inside a string is a dynamic reference: defined("x"),
            # getattr(obj, "x"), or just prose in a comment.
            occurrence.reason = REASON_QUOTED_STRING
            return occurrence
        occurrence.context = CONTEXT_CODE
        occurrence.safe = True
        return occurrence

    if normalized_key in _TEXT_KEYS:
        # Outside an interpolation this is prose the author wrote, not a
        # reference. Left alone rather than treated as an obstacle.
        occurrence.reason = REASON_DISPLAY_TEXT
        return occurrence

    escaped = re.escape(old_name)
    stripped = line.strip()
    if normalized_key == "objects" and re.match(rf"^-\s*{escaped}\s*:", stripped):
        if not new_name.isidentifier():
            # `objects:` declares a base name and its class. Rewriting the entry
            # to an attribute path would produce `persons[0].name.first:
            # ALIndividual`, which is not a declaration at all — the object the
            # path hangs off has to be declared instead.
            occurrence.reason = REASON_OBJECT_DECLARATION
            return occurrence
        occurrence.context = CONTEXT_OBJECT_DEFINITION
        occurrence.safe = True
        return occurrence
    if re.match(rf"^-\s*{escaped}\s*$", stripped):
        occurrence.context = CONTEXT_LIST_ITEM
        occurrence.safe = True
        return occurrence

    # Split the line into its key and value once, then judge by which side the
    # name sits on. Deciding from the key alone misreads a name mentioned in
    # the middle of a label; deciding from an exact value match alone misses it
    # entirely.
    key_match = re.match(r"^(\s*-?\s*)([^:]+?):\s*", line)
    if key_match:
        label = key_match.group(2).strip().strip("\"'").lower()
        value = line[key_match.end() :].strip()
        in_value = column >= key_match.end()

        if label in _FIELD_TEXT_SUBKEYS:
            occurrence.reason = REASON_DISPLAY_TEXT
            return occurrence
        if in_value and value == old_name:
            if label in _REFERENCE_KEYS:
                occurrence.context = CONTEXT_FIELD
                occurrence.safe = True
                return occurrence
            if label not in _FIELD_OTHER_SUBKEYS and normalized_key in _FIELD_LIST_KEYS:
                # docassemble field shorthand: `- <label>: <variable>`.
                occurrence.context = CONTEXT_FIELD
                occurrence.safe = True
                return occurrence

    # A key we do not recognise, or the name buried mid-line somewhere that
    # cannot be accounted for.
    occurrence.reason = REASON_UNRECOGNISED
    return occurrence


def analyze_rename(
    *, filename: str, raw_yaml: str, old_name: str, new_name: str
) -> RenameAnalysis:
    """Find and classify every appearance of ``old_name`` in the source."""
    from .editor_utils import parse_interview_yaml

    analysis = RenameAnalysis(old_name=old_name, new_name=new_name)
    document = parse_source_document(filename, raw_yaml)
    model = parse_interview_yaml(raw_yaml)
    blocks_by_index = {block.get("index"): block for block in model.get("blocks", [])}

    pattern = re.compile(rf"(?<![\w.]){re.escape(old_name)}(?![\w])")
    for match in pattern.finditer(raw_yaml):
        source_block = None
        for candidate in document.documents:
            if candidate.start_offset <= match.start() < candidate.end_offset:
                source_block = candidate
                break
        editor_block = (
            blocks_by_index.get(source_block.document_index) if source_block else None
        )
        analysis.occurrences.append(
            _classify(
                raw_yaml,
                source_block,
                str(editor_block.get("id")) if editor_block else None,
                str(editor_block.get("type")) if editor_block else None,
                match,
                old_name,
                new_name,
            )
        )
    return analysis


def plan_rename_operations(
    analyses: Sequence[RenameAnalysis],
) -> List[Dict[str, Any]]:
    """Turn safe occurrences into non-overlapping source-range operations."""
    operations: List[Dict[str, Any]] = []
    for analysis in analyses:
        for occurrence in analysis.safe_occurrences:
            operations.append(
                {
                    "type": "replace-range",
                    "start": occurrence.start,
                    "end": occurrence.end,
                    "text": analysis.new_name,
                }
            )
    return operations


def check_rename_batch(
    *, filename: str, raw_yaml: str, renames: Sequence[Dict[str, str]]
) -> Tuple[List[RenameAnalysis], List[str]]:
    """Analyse a batch of renames and collect every reason to refuse it."""
    from .editor_agent_tools import _variable_catalog

    problems: List[str] = []
    analyses: List[RenameAnalysis] = []

    existing_names = {
        str(entry.get("variable")) for entry in _variable_catalog(raw_yaml)
    }

    old_names = [str(item.get("old_name") or "") for item in renames]
    new_names = [str(item.get("new_name") or "") for item in renames]

    for index, item in enumerate(renames):
        old_name = str(item.get("old_name") or "").strip()
        new_name = str(item.get("new_name") or "").strip()
        if not old_name:
            problems.append(f"Rename {index + 1} has no old_name")
            continue
        invalid = validate_variable_reference(new_name)
        if invalid:
            problems.append(f"{old_name} → {new_name}: {invalid}")
            continue
        if old_name == new_name:
            problems.append(f"{old_name} is already named that")
            continue
        if new_names.count(new_name) > 1:
            problems.append(
                f"Two variables would both become {new_name}; that would merge them"
            )
            continue
        if new_name in existing_names and new_name not in old_names:
            problems.append(
                f"{new_name} is already used by another field; renaming "
                f"{old_name} onto it would merge two variables"
            )
            continue

        analysis = analyze_rename(
            filename=filename,
            raw_yaml=raw_yaml,
            old_name=old_name,
            new_name=new_name,
        )
        if not analysis.occurrences:
            problems.append(f"{old_name} does not appear anywhere in this interview")
            continue
        if analysis.blocking_occurrences:
            lines = ", ".join(
                f"line {item.line} ({item.reason})"
                for item in analysis.blocking_occurrences[:5]
            )
            problems.append(
                f"{old_name} appears in {len(analysis.blocking_occurrences)} place(s) "
                f"Weaver cannot tell apart from a reference: {lines}. Update those "
                "by hand first."
            )
            continue
        if not analysis.safe_occurrences:
            problems.append(
                f"{old_name} only appears as display text, so there is nothing to rename"
            )
            continue
        analyses.append(analysis)

    return analyses, problems


# ---------------------------------------------------------------------------
# Flat family → object attributes
# ---------------------------------------------------------------------------


def _flat_variable_names(raw_yaml: str) -> List[str]:
    from .editor_agent_tools import _variable_catalog

    names: List[str] = []
    for entry in _variable_catalog(raw_yaml):
        name = str(entry.get("variable") or "")
        # Only genuinely flat names are candidates; anything already using an
        # index or an attribute has been converted.
        if name and name.isidentifier() and name not in names:
            names.append(name)
    return names


def suggest_object_conversion(*, raw_yaml: str, prefix: str = "") -> Dict[str, Any]:
    """Propose object paths for a family of flat, similarly named variables.

    The mapping is Weaver's existing one — the same table that turns PDF field
    names into AssemblyLine objects — so a conversion here agrees with what the
    Weaver produces for a fresh interview.
    """
    from .interview_generator import map_raw_to_final_display

    suggestions: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    targets: Dict[str, str] = {}
    needle = str(prefix or "").strip()

    for name in _flat_variable_names(raw_yaml):
        if needle and not name.startswith(needle):
            continue
        try:
            mapped = map_raw_to_final_display(name)
        except Exception:
            continue
        if not mapped or mapped == name:
            continue
        if "(" in mapped:
            # e.g. birthdate.format() — a display expression, not somewhere a
            # question can store an answer.
            skipped.append(
                {
                    "old_name": name,
                    "proposed": mapped,
                    "reason": "maps to a display expression, not an assignable variable",
                }
            )
            continue
        if mapped in targets:
            skipped.append(
                {
                    "old_name": name,
                    "proposed": mapped,
                    "reason": f"would collide with {targets[mapped]}",
                }
            )
            continue
        invalid = validate_variable_reference(mapped)
        if invalid:
            skipped.append({"old_name": name, "proposed": mapped, "reason": invalid})
            continue
        targets[mapped] = name
        suggestions.append({"old_name": name, "new_name": mapped})

    return {
        "prefix": needle,
        "renames": suggestions,
        "skipped": skipped,
    }

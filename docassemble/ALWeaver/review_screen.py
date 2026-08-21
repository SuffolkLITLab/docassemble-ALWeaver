"""Build the model behind a generated interview's review screen.

The Weaver used to emit one review "Edit" entry per parent collection, which
meant one entry per variable for the many interviews whose fields are mostly
loose primitives. ALDashboard's review screen generator groups by the question
screen instead, which reads like a recap of the interview rather than a wall of
single-value rows (SuffolkLITLab/docassemble-ALWeaver#865).

This module holds the grouping decisions so the Mako template only has to
render them, and so the same rules can be checked by unit tests without
rendering a whole interview.

Nothing here imports ``interview_generator``: the builders take the collection
and screen objects that module already produces and only read attributes off
them. That keeps the import one-directional.
"""

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

__all__ = [
    "ReviewEntry",
    "ReviewRow",
    "build_review_entries",
    "table_edit_attributes",
]

# Attributes AssemblyLine gathers in `basic_questions_signature_flow`, right
# before the download screen. Following up on one of these from a review table's
# "Edit" button re-opens a signature pad the author never meant to re-ask, and
# any answer given there is overwritten moments later
# (SuffolkLITLab/docassemble-ALWeaver#482).
SIGNATURE_ATTRIBUTES = {"signature", "signature_date"}

# Field types the interview never asks a question for, so there is nothing for a
# review screen to link back to.
UNASKED_FIELD_TYPES = {"code", "skip this field"}


@dataclass
class ReviewRow:
    """One ``Label: value`` line inside a review entry's button text."""

    label: str
    #: A complete Mako expression body, without the surrounding ``${ }``. It is
    #: always written so that an undefined variable renders as empty rather than
    #: sending the user back into the interview: a review screen should never
    #: force the definition of a variable.
    expression: str


@dataclass
class ReviewEntry:
    """One entry in the generated ``review:`` block."""

    #: The variable the "Edit" link seeks. For a list this is ``<name>.revisit``;
    #: for a question screen it is the variable that triggers that screen.
    edit_var: str
    #: Bolded heading for the entry -- the question text, or the name of the
    #: list or object being summarized.
    title: str
    rows: List[ReviewRow] = dataclass_field(default_factory=list)
    #: Set for list collections, which are summarized as a bulleted loop over
    #: the items rather than as ``Label: value`` rows.
    list_var: Optional[str] = None


def _humanize(var_name: str) -> str:
    """`my_user_address` -> `My user address`, matching the old review titles."""
    return str(var_name or "").replace("_", " ").capitalize()


def _field_label(field: Any) -> str:
    """The label to show for a field, falling back to its variable name."""
    if getattr(field, "has_label", False):
        label = str(getattr(field, "label", "") or "").strip()
        if label:
            return label
    return _humanize(str(getattr(field, "final_display_var", "") or ""))


def _is_signature_field(field: Any) -> bool:
    if getattr(field, "group", None) is not None and (
        getattr(getattr(field, "group", None), "value", None) == "signature"
    ):
        return True
    return (
        str(getattr(field, "final_display_var", "") or "").rsplit(".", 1)[-1]
        in SIGNATURE_ATTRIBUTES
    )


def _is_asked(field: Any) -> bool:
    field_type = getattr(field, "field_type", None)
    return field_type not in UNASKED_FIELD_TYPES


def _primitive_expression(field: Any) -> str:
    """A Mako expression that shows a field's answer without demanding it.

    ``showifdef()`` covers the plain cases in one short call. Anything that
    needs a formatting function has to guard the call itself, because
    ``currency('')`` and ``yesno('')`` would happily report a wrong answer for a
    variable that was never asked.
    """
    variable = str(getattr(field, "final_display_var", "") or "")
    field_type = getattr(field, "field_type", None)
    if field_type in ("yesno", "yesnomaybe", "yesnoradio", "yesnowide", "noyes"):
        return f"word(yesno({variable})) if defined('{variable}') else ''"
    if field_type == "currency":
        return f"currency({variable}) if defined('{variable}') else ''"
    if field_type == "area":
        return f"single_paragraph({variable}) if defined('{variable}') else ''"
    return f"showifdef('{variable}')"


def _object_rows(collection: Any) -> List[ReviewRow]:
    """Rows for a single (non-list) object, e.g. `trial_court.address`.

    ``attribute_map`` already collapses the sub-attributes of a name or an
    address into one displayable expression, which is the "better handling of
    common attributes" #865 asks for: one `Address:` line showing
    `address.block()`, not six lines of street, unit, city, state, zip.
    """
    rows: List[ReviewRow] = []
    var_name = str(getattr(collection, "var_name", "") or "")
    for attribute, (display_att, settable_att) in getattr(
        collection, "attribute_map", {}
    ).items():
        if attribute in SIGNATURE_ATTRIBUTES:
            continue
        rows.append(
            ReviewRow(
                label=_humanize(attribute),
                expression=(
                    f"{var_name}.{display_att} "
                    f"if defined('{var_name}.{settable_att}') else ''"
                ),
            )
        )
    return rows


def _collection_entry(collection: Any) -> Optional[ReviewEntry]:
    """The entry for a collection whose fields no generated screen asks about.

    AssemblyLine's own question library gathers things like `docket_number` and
    `trial_court`, so those never appear on a Weaver-authored screen but still
    belong on the review screen.
    """
    var_name = str(getattr(collection, "var_name", "") or "")
    var_type = getattr(collection, "var_type", "primitive")
    if not var_name:
        return None

    if var_type == "list":
        return ReviewEntry(
            edit_var=f"{var_name}.revisit",
            title=_humanize(var_name),
            list_var=var_name,
        )

    fields = [
        field
        for field in getattr(collection, "fields", [])
        if _is_asked(field) and not _is_signature_field(field)
    ]
    if not fields:
        return None

    if var_type == "object":
        rows = _object_rows(collection)
        if not rows:
            return None
        return ReviewEntry(
            edit_var=var_name,
            title=_humanize(var_name),
            rows=rows,
        )

    first = fields[0]
    return ReviewEntry(
        edit_var=str(first.get_settable_var()),
        title=_field_label(first),
        rows=[
            ReviewRow(
                label=_field_label(first), expression=_primitive_expression(first)
            )
        ],
    )


def _screen_entry(
    screen: Any,
    collection_for_field: Dict[int, Any],
) -> Tuple[Optional[ReviewEntry], List[Any], List[Any]]:
    """Summarize one question screen, and say which collections it covered.

    Returns ``(entry, list_collections, covered_collections)``. Fields that
    belong to a list are kept out of the entry -- the list gets its own revisit
    entry instead, because an "Edit" link pointing at `users[i].name.first`
    would edit whichever item Docassemble happened to be iterating over -- but
    the screen is still where that list is asked about, so its collection is
    reported back to be emitted at this position.
    """
    rows: List[ReviewRow] = []
    trigger: Optional[str] = None
    list_collections: List[Any] = []
    covered: List[Any] = []
    for field in getattr(screen, "field_list", []) or []:
        collection = collection_for_field.get(id(field))
        if collection is not None and getattr(collection, "var_type", "") == "list":
            if collection not in list_collections:
                list_collections.append(collection)
            continue
        if not _is_asked(field) or _is_signature_field(field):
            continue
        if collection is not None and collection not in covered:
            covered.append(collection)
        if trigger is None:
            trigger = str(field.get_settable_var())
        rows.append(
            ReviewRow(
                label=_field_label(field), expression=_primitive_expression(field)
            )
        )

    if trigger is None or not rows:
        return None, list_collections, covered

    title = " ".join(str(getattr(screen, "question_text", "") or "").split())
    entry = ReviewEntry(edit_var=trigger, title=title or _humanize(trigger), rows=rows)
    return entry, list_collections, covered


def build_review_entries(
    collections: Sequence[Any],
    screens: Optional[Iterable[Any]] = None,
) -> List[ReviewEntry]:
    """Group the review screen by question screen, in the order they are asked.

    ``collections`` is the output of ``DAFieldList.review_collections()`` --
    already filtered and sorted -- and ``screens`` is the interview's draft
    screen order. Every collection ends up in exactly one entry: a list keeps
    its own revisit entry, a collection asked on a screen is folded into that
    screen's entry, and anything left over (AssemblyLine's built-in questions)
    gets an entry of its own at the position the collection ordering gives it.
    """
    collection_for_field: Dict[int, Any] = {}
    for collection in collections:
        for field in getattr(collection, "fields", []):
            collection_for_field.setdefault(id(field), collection)

    entries: List[ReviewEntry] = []
    emitted: Set[str] = set()

    def emit_collection(collection: Any) -> None:
        var_name = str(getattr(collection, "var_name", "") or "")
        if not var_name or var_name in emitted:
            return
        entry = _collection_entry(collection)
        emitted.add(var_name)
        if entry is not None:
            entries.append(entry)

    for screen in screens or []:
        if getattr(screen, "field_list", None) is not None:
            entry, list_collections, covered = _screen_entry(
                screen, collection_for_field
            )
            for collection in list_collections:
                emit_collection(collection)
            for collection in covered:
                emitted.add(str(getattr(collection, "var_name", "")))
            if entry is not None:
                entries.append(entry)
            continue
        # A bare field in the screen order: Docassemble asks for it through
        # AssemblyLine's question library, so review it as its own collection.
        collection = collection_for_field.get(id(screen))
        if collection is not None:
            emit_collection(collection)

    for collection in collections:
        emit_collection(collection)

    return entries


def table_edit_attributes(collection: Any) -> List[str]:
    """The attributes a list's revisit table should let the user edit.

    Docassemble turns `edit:` into a "follow up" list, and it seeks *every*
    variable named there, defining any that the interview never asked. Listing
    a signature that way sends the user to a signature pad they did not ask for
    and that the signature flow overwrites anyway, so signatures stay out
    (SuffolkLITLab/docassemble-ALWeaver#482). One attribute per group is enough:
    the screen that sets `name.first` sets the rest of the name with it.
    """
    attributes: List[str] = []
    for attribute, (_display_att, settable_att) in getattr(
        collection, "attribute_map", {}
    ).items():
        if attribute in SIGNATURE_ATTRIBUTES:
            continue
        if settable_att and settable_att not in attributes:
            attributes.append(settable_att)
    return attributes

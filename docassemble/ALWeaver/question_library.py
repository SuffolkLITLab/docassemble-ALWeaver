"""Work out which AssemblyLine baseline questions to copy into a generated interview.

AssemblyLine asks about people with `generic object:` questions in
``ql_baseline.yml``: one question serves ``users``, ``parents``, ``witnesses`` and
every other ``ALPeopleList``.  That is efficient for AssemblyLine, but it makes the
questions hard to *edit*.  Somebody who wants to reword "Name of the 2nd child"
cannot copy the block out of ``ql_baseline.yml`` as-is -- they have to know to drop
the ``generic object:`` line and rewrite every ``x`` into ``children``.  New
authors reliably get stuck here.

So the Weaver can copy the questions in for them, already specialized to the
objects the interview actually declares.  This module decides *which* questions to
copy; ``data/templates/question_library.mako`` holds the question text itself, so
the copies can be kept in sync with ``ql_baseline.yml`` by editing that template.

The entry point is :func:`baseline_question_specs`.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
import re

from .generator_constants import generator_constants

__all__ = [
    "baseline_question_specs",
    "singular_label",
    "plural_label",
]


# Plural object name -> the singular AssemblyLine uses for it, e.g. "children" ->
# "child".  RESERVED_PERSON_PLURALIZERS_MAP is keyed the other way around and
# includes identity entries ("users" -> "users") that say nothing about the
# singular, so those are skipped.
_PLURAL_TO_SINGULAR: Dict[str, str] = {
    plural: singular
    for singular, plural in generator_constants.RESERVED_PERSON_PLURALIZERS_MAP.items()
    if singular != plural
}


# The attribute questions worth copying, in the order they are emitted.  The key is
# the first segment of the attribute (``users[0].address.zip`` -> ``address``) and
# the value is the ``kind`` the Mako template dispatches on.
#
# Deliberately left out: ``name`` (the gather flow already asks it), ``signature``
# (AssemblyLine's `basic_questions_signature_flow` owns those screens), and
# anything AssemblyLine does not have a reusable question for.
_ATTRIBUTE_KINDS: List[Tuple[str, str]] = [
    ("address", "address"),
    ("mailing_address", "mailing_address"),
    ("birthdate", "birthdate"),
    ("gender", "gender"),
    ("pronouns", "pronouns"),
    ("language", "language"),
    ("phone_number", "phone_number"),
    ("mobile_number", "mobile_number"),
    ("email", "email"),
]

_ATTRIBUTE_KIND_BY_SEGMENT: Dict[str, str] = dict(_ATTRIBUTE_KINDS)

_VARIABLE_PATTERN = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)(\[[^\]]+\])?(?:\.(.+))?$",
)


def _split_variable(variable: str) -> Optional[Tuple[str, bool, str]]:
    """Break ``users[0].address.zip`` into ``("users", True, "address.zip")``.

    Returns ``None`` for anything that is not a plain object reference, such as
    the method calls (``plaintiffs[0].address.on_one_line()``) that show up among
    the built-in fields.
    """
    match = _VARIABLE_PATTERN.match(variable.strip())
    if not match:
        return None
    prefix, index, attribute = match.group(1), match.group(2), match.group(3) or ""
    if "(" in attribute or ")" in attribute:
        return None
    return prefix, bool(index), attribute


def singular_label(name: str) -> str:
    """A human-readable singular for an object name, e.g. ``parents`` -> ``parent``."""
    base = _PLURAL_TO_SINGULAR.get(name)
    if base is None:
        base = _naive_singular(name)
    return base.replace("_", " ")


def plural_label(name: str) -> str:
    """A human-readable plural for an object name, e.g. ``other_parties`` -> ``other parties``."""
    return name.replace("_", " ")


def _naive_singular(name: str) -> str:
    """Best-effort singular for list names AssemblyLine does not know about."""
    if name.endswith("ies") and len(name) > 3:
        return name[:-3] + "y"
    if name.endswith("sses") or name.endswith("ches") or name.endswith("shes"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def _attribute_kinds_for(attributes: Iterable[str]) -> List[str]:
    """The attribute question kinds implied by a set of attribute paths."""
    segments: Set[str] = set()
    for attribute in attributes:
        if not attribute:
            continue
        segment = attribute.split(".", 1)[0]
        if segment.startswith("gender"):
            segment = "gender"
        if segment in _ATTRIBUTE_KIND_BY_SEGMENT:
            segments.add(segment)
    return [kind for segment, kind in _ATTRIBUTE_KINDS if segment in segments]


def _gather_kinds(params: Dict[str, Any]) -> List[str]:
    """The gather-flow questions a list still needs, given its ``objects:`` params.

    A list declared as ``ALPeopleList.using(there_are_any=True)`` never asks
    ``there_are_any``, and one declared with ``ask_number=True`` asks
    ``target_number`` instead of ``there_is_another``.  Copying in a question
    Docassemble will never reach is just noise, so each one is conditional.
    """
    asks_number = bool(params.get("ask_number"))
    knows_target = "target_number" in params
    knows_there_are_any = "there_are_any" in params

    kinds: List[str] = []
    if asks_number:
        if not knows_target:
            kinds.append("how_many")
    elif not knows_there_are_any:
        kinds.append("there_are_any")
    kinds.append("names")
    if not asks_number:
        kinds.append("there_is_another")
    return kinds


def baseline_question_specs(
    interview: Any,
    objects: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Describe the baseline questions to copy into ``interview``'s generated YAML.

    Args:
      interview: the ``DAInterview`` being generated.
      objects: the entries of the generated ``objects:`` block.  Only objects
        declared there get copies -- names like ``plaintiffs`` that AssemblyLine
        derives and manages itself are left to AssemblyLine.

    Returns:
      A list of plain dicts, one per question block to emit, each with a ``kind``
      the Mako template dispatches on plus the labels that template needs.  Empty
      when the author turned the option off.
    """
    if not bool(getattr(interview, "copy_baseline_questions", True)):
        return []
    if not objects:
        return []

    all_fields = getattr(interview, "all_fields", None)
    builtins = list(all_fields.builtins()) if all_fields is not None else []

    attributes_by_prefix: Dict[str, Set[str]] = {}
    for field in builtins:
        parsed = _split_variable(str(getattr(field, "final_display_var", "") or ""))
        if parsed is None:
            continue
        prefix, _indexed, attribute = parsed
        attributes_by_prefix.setdefault(prefix, set()).add(attribute)

    specs: List[Dict[str, Any]] = []
    for spec in objects:
        name = str(getattr(spec, "name", "") or "")
        if not name.isidentifier():
            continue
        object_type = str(getattr(spec, "type", "ALPeopleList") or "ALPeopleList")
        params = dict(getattr(spec, "params", None) or {})
        is_list = object_type.endswith("List")

        common = {
            "var": name,
            "is_list": is_list,
            "singular": singular_label(name) if is_list else plural_label(name),
            "plural": plural_label(name),
        }

        kinds = _gather_kinds(params) if is_list else ["name"]
        kinds.extend(_attribute_kinds_for(attributes_by_prefix.get(name, set())))

        for kind in kinds:
            specs.append({"kind": kind, **common})

    return specs

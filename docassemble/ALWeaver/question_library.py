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

The entry point for interview generation is :func:`baseline_question_specs`.
The graphical editor reaches the same questions through :func:`library_catalog`,
which offers them for the objects an already-written file declares, and
:func:`render_baseline_question`, which turns one of those offers into YAML.
"""

import ast
import os
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .generator_constants import generator_constants

__all__ = [
    "attribute_references",
    "baseline_question_specs",
    "library_catalog",
    "render_baseline_question",
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


# ---------------------------------------------------------------------------
# The same questions, offered to an interview that already exists
# ---------------------------------------------------------------------------
#
# `baseline_question_specs` runs once, while the Weaver is writing a brand new
# interview.  An author who declares another `ALPeopleList` a week later in the
# graphical editor needs the same questions, so the editor asks for a *catalog*
# instead: every question this module could write for the objects a file
# declares, labelled well enough to pick from a list.


# The object classes AssemblyLine's `ql_baseline.yml` questions actually serve.
# Anything else in an `objects:` block -- an `ALDocumentBundle`, an `ALCourt` --
# has no baseline question to copy, so it is left out of the catalog.
PERSON_LIST_CLASSES: Tuple[str, ...] = ("ALPeopleList",)
PERSON_CLASSES: Tuple[str, ...] = ("ALIndividual",)


# kind -> (group, label, what the question does).  ``{singular}`` and
# ``{plural}`` are filled in with the object's own words, so the catalog reads
# "Is there another child?" rather than "there_is_another".
_KIND_DESCRIPTIONS: Dict[str, Tuple[str, str, str]] = {
    "there_are_any": (
        "gather",
        "Are there any {plural}?",
        "Asks whether this form involves any {plural} at all.",
    ),
    "how_many": (
        "gather",
        "How many {plural}?",
        "Asks whether there are any {plural} and, if so, how many.",
    ),
    "names": (
        "gather",
        "Name of each {singular}",
        "The name screen, asked once for each {singular}.",
    ),
    "there_is_another": (
        "gather",
        "Is there another {singular}?",
        "Asks after each {singular} whether there is one more.",
    ),
    "name": ("gather", "Name of {singular}", "Asks for the name of {singular}."),
    "address": ("attribute", "Address", "Where the {singular} lives."),
    "mailing_address": (
        "attribute",
        "Mailing address",
        "A separate address for mail, offered alongside the home address.",
    ),
    "birthdate": ("attribute", "Birthdate", "The date the {singular} was born."),
    "gender": ("attribute", "Gender", "AssemblyLine's gender question."),
    "pronouns": ("attribute", "Pronouns", "The pronouns to use for the {singular}."),
    "language": ("attribute", "Language", "The language the {singular} speaks."),
    "phone_number": ("attribute", "Phone number", "The {singular}'s phone number."),
    "mobile_number": ("attribute", "Mobile number", "The {singular}'s mobile number."),
    "email": ("attribute", "Email address", "The {singular}'s email address."),
}


_REFERENCE_PATTERN = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]\n]*\])?\.([A-Za-z_][A-Za-z0-9_.]*)"
)

_ID_LINE_PATTERN = re.compile(r"(?m)^id:[ \t]*(.+?)[ \t]*$")

_template_lock = threading.Lock()
_template: Any = None


def _fix_id(string: str) -> str:
    """The block id AssemblyLine style gives a phrase.

    ``interview_generator.fix_id`` cannot be imported here -- that module
    imports this one -- so this repeats it for the phrases the template passes,
    and ``test_question_library`` checks the two stay in step.  It stays
    deterministic where ``fix_id`` falls back to a random id: the catalog tells
    the editor which id a block will have before the block is written, so the
    same phrase has to produce the same id twice.
    """
    return re.sub(r"[\W_]+", " ", string).strip()


def _library_template() -> Any:
    """The Mako template holding the question text, parsed once."""
    global _template
    with _template_lock:
        if _template is None:
            import mako.template

            path = os.path.join(
                os.path.dirname(__file__),
                "data",
                "templates",
                "question_library.mako",
            )
            with open(path, "r", encoding="utf-8") as handle:
                # This template renders Docassemble YAML, not HTML output.
                _template = mako.template.Template(  # nosec B702
                    handle.read(), input_encoding="utf-8"
                )
    return _template


def _params_from_arguments(arguments: str) -> Dict[str, Any]:
    """The keyword arguments of an ``ALPeopleList.using(...)`` call.

    A value that is not a literal -- ``there_are_any=user_has_children`` -- is
    recorded as ``None``.  What decides which gather questions a list still
    needs is whether its declaration answers them at all, not what it answers,
    and a declaration that answers one from code answers it just as finally.
    """
    text = str(arguments or "").strip()
    if not text:
        return {}
    try:
        call = ast.parse(f"_f({text})", mode="eval").body
    except SyntaxError:
        return {}
    if not isinstance(call, ast.Call):
        return {}
    params: Dict[str, Any] = {}
    for keyword in call.keywords:
        if not keyword.arg:
            continue
        try:
            params[keyword.arg] = ast.literal_eval(keyword.value)
        except ValueError:
            params[keyword.arg] = None
    return params


def _normalize_object(spec: Any) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Read one object declaration into ``(name, class name, parameters)``.

    Accepts the editor's parsed ``objects:`` rows -- ``{"name": "users",
    "class_name": "ALPeopleList", "using_args": "there_are_any=True"}`` -- as
    well as the generated-interview specs ``baseline_question_specs`` takes.
    """
    if isinstance(spec, dict):
        name = str(spec.get("name") or "").strip()
        class_name = str(spec.get("class_name") or spec.get("type") or "").strip()
        raw_params = spec.get("params")
        if isinstance(raw_params, dict):
            params = dict(raw_params)
        else:
            params = _params_from_arguments(str(spec.get("using_args") or ""))
    else:
        name = str(getattr(spec, "name", "") or "").strip()
        class_name = str(getattr(spec, "type", "") or "").strip()
        params = dict(getattr(spec, "params", None) or {})
    if not name.isidentifier():
        return None
    return name, class_name, params


def attribute_references(text: str) -> Dict[str, Set[str]]:
    """Every ``object.attribute`` path some YAML mentions, grouped by object.

    Used to work out which attribute questions to recommend: a file that already
    writes ``users[i].birthdate`` somewhere wants the birthdate question.
    """
    found: Dict[str, Set[str]] = {}
    for prefix, attribute in _REFERENCE_PATTERN.findall(str(text or "")):
        found.setdefault(prefix, set()).add(attribute)
    return found


def render_baseline_question(
    var: str,
    kind: str,
    is_list: bool = True,
) -> str:
    """The YAML for one baseline question, specialized for ``var``.

    Returns the block on its own, without the leading ``---`` the generated
    interview needs, so callers can insert it wherever they like.
    """
    if kind not in _KIND_DESCRIPTIONS:
        raise ValueError(f"Unknown question library kind: {kind!r}")
    entry = {
        "kind": kind,
        "var": var,
        "is_list": bool(is_list),
        "singular": singular_label(var) if is_list else plural_label(var),
        "plural": plural_label(var),
    }
    rendered = (
        _library_template()
        .get_def("baseline_question_yaml")
        .render(entry=entry, fix_id=_fix_id)
    )
    body = rendered.strip("\r\n")
    if body.startswith("---"):
        body = body[3:].lstrip("\r\n")
    return body


def library_catalog(
    objects: Sequence[Any],
    references: Optional[Dict[str, Set[str]]] = None,
    existing_ids: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """Every baseline question that can be copied for a file's own objects.

    Args:
      objects: the declarations from the file's ``objects:`` blocks.
      references: ``attribute_references`` of the file, used to recommend the
        attribute questions it already asks about.
      existing_ids: the block ids the file already uses, so a question already
        copied in once is marked rather than offered as new.

    Returns:
      One entry per person-shaped object, each with the questions available for
      it: ``kind``, a readable ``label``, the rendered ``yaml``, whether the
      file already has it (``present``), and whether it is worth pre-selecting
      (``recommended``).
    """
    taken = {
        str(block_id).strip() for block_id in existing_ids if str(block_id).strip()
    }
    catalog: List[Dict[str, Any]] = []
    for spec in objects or []:
        normalized = _normalize_object(spec)
        if normalized is None:
            continue
        name, class_name, params = normalized
        if class_name in PERSON_LIST_CLASSES:
            is_list = True
        elif class_name in PERSON_CLASSES:
            is_list = False
        else:
            continue

        singular = singular_label(name) if is_list else plural_label(name)
        plural = plural_label(name)
        gather_kinds = _gather_kinds(params) if is_list else ["name"]
        attribute_kinds = [kind for _segment, kind in _ATTRIBUTE_KINDS]
        used_attributes = (references or {}).get(name, set())
        recommended_attributes = set(_attribute_kinds_for(used_attributes))

        questions: List[Dict[str, Any]] = []
        for kind in gather_kinds + attribute_kinds:
            group, label, summary = _KIND_DESCRIPTIONS[kind]
            block_yaml = render_baseline_question(name, kind, is_list=is_list)
            id_match = _ID_LINE_PATTERN.search(block_yaml)
            question_id = id_match.group(1).strip("'\" ") if id_match else ""
            questions.append(
                {
                    "kind": kind,
                    "group": group,
                    "label": label.format(singular=singular, plural=plural),
                    "summary": summary.format(singular=singular, plural=plural),
                    "question_id": question_id,
                    "yaml": block_yaml,
                    "present": bool(question_id) and question_id in taken,
                    "recommended": group == "gather" or kind in recommended_attributes,
                }
            )

        catalog.append(
            {
                "var": name,
                "class_name": class_name,
                "is_list": is_list,
                "singular": singular,
                "plural": plural,
                "questions": questions,
            }
        )
    return catalog

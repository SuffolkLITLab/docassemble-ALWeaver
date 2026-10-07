"""Find the numbered rows of a PDF form and turn them into lists.

A form with room for three vehicles names its boxes `vehicle_year_make_model_1`,
`vehicle_pv_1`, `vehicle_loan_balance_1`, then `_2` and `_3`. Those are three
items of one list, each with the same attributes, but drafts used to ask for
twelve unrelated text fields. On 54 real court forms there were 59 numbered
families like this, and authors wrote them as lists (`vehicles`, `real_estate`,
`accounts`) every time.

Rows of something AssemblyLine already models use its class, so its questions
and totals come along: vehicles become an `ALVehicleList`, accounts and property
an `ALAssetList`. Anything else becomes a plain `DAList` of objects with the
attributes the form names. A numbered name with no attribute of its own, like
`judge0` next to `judge0_role`, is that person's name, so the family is a list
of people.
"""

import keyword
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .generator_constants import generator_constants
from .question_library import render_baseline_question

__all__ = ["RowFamily", "find_row_families"]


@dataclass
class RowFamily:
    """One numbered family of fields, as the list it becomes."""

    stem: str
    """What one row is about, as the form names it: `vehicle`."""
    list_name: str
    """The list variable: `vehicles`."""
    object_type: str
    """`ALVehicleList`, `ALAssetList`, `ALPeopleList` or `DAList`."""
    capacity: int
    """How many rows the form has room for."""
    attributes: Dict[str, str] = field(default_factory=dict)
    """Each attribute the form fills, mapped to the item attribute it reads."""
    variables: Dict[str, str] = field(default_factory=dict)
    """Each field variable, mapped to the expression it now reads."""

    @property
    def uses_al_income(self) -> bool:
        return self.object_type in AL_INCOME_LIST_TYPES

    def question_attributes(self) -> List[str]:
        """Item attributes nothing else will ask about.

        AssemblyLine's `al_income.yml` asks for the standard attributes of its
        own types, and the people questions ask for names, so only the rest
        need a question written for them.
        """
        standard = AL_INCOME_STANDARD_ATTRIBUTES.get(self.object_type, set())
        asked = []
        for attribute in self.attributes.values():
            settable = attribute.split("(")[0]
            if settable in standard or settable in ("", "year_make_model"):
                continue
            if settable not in asked:
                asked.append(settable)
        return asked

    def overflow_headers(self) -> List[Dict[str, str]]:
        """The columns of the addendum table for rows the form has no room for."""
        return [
            {attribute: _label(attribute)}
            for attribute in dict.fromkeys(self.attributes.values())
            if attribute and not attribute.endswith(")")
        ] or [{"name": "Name"}]


# Rows of these are modelled by ALToolbox's al_income classes
_KNOWN_ROW_TYPES: Dict[str, str] = {
    "vehicle": "ALVehicleList",
    "car": "ALVehicleList",
    "asset": "ALAssetList",
    "property": "ALAssetList",
    "real_estate": "ALAssetList",
    "real_property": "ALAssetList",
    "account": "ALAssetList",
    "bank_account": "ALAssetList",
}
AL_INCOME_LIST_TYPES = frozenset({"ALVehicleList", "ALAssetList"})
# What al_income.yml already asks about each item
AL_INCOME_STANDARD_ATTRIBUTES: Dict[str, Set[str]] = {
    "ALVehicleList": {"year", "make", "model", "market_value", "balance", "owner"},
    "ALAssetList": {"market_value", "balance", "value", "owner", "source"},
}
# The form's word for an attribute, and the al_income attribute it means
_AL_INCOME_ATTRIBUTE_WORDS: Dict[str, str] = {
    "pv": "market_value",
    "present_value": "market_value",
    "current_value": "market_value",
    "fmv": "market_value",
    "market_value": "market_value",
    "value": "market_value",
    "loan_balance": "balance",
    "loan": "balance",
    "balance": "balance",
    "amount_owed": "balance",
    "owner": "owner",
    "ower": "owner",
    "owners": "owner",
    "income": "value",
    "year": "year",
    "make": "make",
    "model": "model",
    "year_make_model": "year_make_model()",
}

# `vehicle_pv_1`
_TRAILING_INDEX = re.compile(r"^([a-z][a-z0-9_]*?)_(\d{1,2})$")
# `other_case_1_docket`
_MIDDLE_INDEX = re.compile(r"^([a-z][a-z_]*?)_(\d{1,2})_([a-z][a-z0-9_]*)$")
# `judge0`, `judge0_role`, `account1_owner`
_JOINED_INDEX = re.compile(r"^([a-z][a-z_]*?[a-z])(\d{1,2})(?:_([a-z][a-z0-9_]*))?$")


def _plural(stem: str) -> str:
    if stem.endswith("_estate") or stem.endswith("_property"):
        return stem
    if stem.endswith("y") and not stem.endswith(("ay", "ey", "oy", "uy")):
        return stem[:-1] + "ies"
    if stem.endswith("s") and not stem.endswith("ss"):
        # `savings`, `other_parties`: already a plural
        return stem
    if stem.endswith(("ss", "x", "ch", "sh")):
        return stem + "es"
    return stem + "s"


def _split_bases(
    bases: Dict[str, List[Tuple[str, int]]],
) -> List[Tuple[str, Dict[str, List[Tuple[str, int]]]]]:
    """Split numbered bases that share their leading words into families.

    `real_estate_value` and `real_estate_owner` share `real_estate`, so they
    are one family's `value` and `owner`; the longest shared start that still
    covers two different attributes wins.
    """
    remaining = dict(bases)
    families: List[Tuple[str, Dict[str, List[Tuple[str, int]]]]] = []
    longest = max((len(base.split("_")) for base in remaining), default=0)
    for length in range(longest - 1, 0, -1):
        groups: Dict[str, List[str]] = {}
        for base in remaining:
            words = base.split("_")
            if len(words) > length:
                groups.setdefault("_".join(words[:length]), []).append(base)
        for stem, members in groups.items():
            if len(members) < 2:
                continue
            families.append(
                (
                    stem,
                    {base[len(stem) + 1 :]: remaining[base] for base in members},
                )
            )
            for base in members:
                del remaining[base]
    return families


# A stem ending like this is half a phrase (`wants_custody_of_1_name`), not a thing
_TRAILING_CONNECTIVES = frozenset(
    {"of", "for", "to", "with", "from", "by", "in", "on", "at", "and", "or"}
)


def find_row_families(
    variables: Iterable[str],
    taken: Iterable[str] = (),
    people: Iterable[str] = (),
) -> List[RowFamily]:
    """Find the numbered row families among a template's plain field variables.

    A family needs at least two rows and at least two things per row (two
    attributes, or a person's name and an attribute). One numbered field on
    its own, like `income_monthly_1` to `_3`, stays as it is.

    Args:
        variables (Iterable[str]): field variables still in plain form, in
            template order.
        taken (Iterable[str]): names already in use, which a list can't take.
        people (Iterable[str]): the singular and plural names of people lists
            the interview already has. `users1_relationship_to_minor` belongs
            to `users`, so it doesn't start a new list.

    Returns:
        List[RowFamily]: the families found.
    """
    taken_names = set(taken)
    people_names = set(people)
    by_base: Dict[str, List[Tuple[str, int]]] = {}
    by_joined_stem: Dict[str, Dict[Optional[str], List[Tuple[str, int]]]] = {}
    for variable in variables:
        joined = _JOINED_INDEX.match(variable)
        trailing = _TRAILING_INDEX.match(variable)
        if not (joined and (joined.group(3) or not trailing)):
            joined = None
        stemmed = _MIDDLE_INDEX.match(variable) or joined
        if stemmed:
            stem, index, attribute = stemmed.group(1, 2, 3)
            by_joined_stem.setdefault(stem, {}).setdefault(attribute, []).append(
                (variable, int(index))
            )
        elif trailing:
            by_base.setdefault(trailing.group(1), []).append(
                (variable, int(trailing.group(2)))
            )

    candidates: List[Tuple[str, Dict[Optional[str], List[Tuple[str, int]]]]] = []
    for stem, split in _split_bases(by_base):
        attributes: Dict[Optional[str], List[Tuple[str, int]]] = dict(split.items())
        candidates.append((stem, attributes))
    candidates += list(by_joined_stem.items())

    families: List[RowFamily] = []
    for stem, attributes in candidates:
        indexes = sorted({index for rows in attributes.values() for _v, index in rows})
        if len(indexes) < 2 or len(attributes) < 2:
            continue
        if (
            stem in people_names
            or _plural(stem) in people_names
            or stem.split("_")[-1] in _TRAILING_CONNECTIVES
        ):
            continue
        # Forms count rows from 1 unless one is numbered 0
        first = 0 if indexes[0] == 0 else 1
        has_name = None in attributes
        object_type = (
            "ALPeopleList" if has_name else _KNOWN_ROW_TYPES.get(stem, "DAList")
        )
        list_name = _plural(stem)
        if list_name in taken_names or not list_name.isidentifier():
            continue
        family = RowFamily(
            stem=stem,
            list_name=list_name,
            object_type=object_type,
            capacity=indexes[-1] - first + 1,
        )
        for attribute, rows in attributes.items():
            if attribute is None:
                item_attribute = ""
            elif object_type in AL_INCOME_LIST_TYPES:
                item_attribute = _AL_INCOME_ATTRIBUTE_WORDS.get(attribute, attribute)
            else:
                item_attribute = attribute
            if keyword.iskeyword(item_attribute):
                # `from` can't be an attribute name in Python
                item_attribute += "_"
            family.attributes[attribute or ""] = item_attribute
            for variable, index in rows:
                expression = f"{list_name}[{index - first}]"
                if item_attribute:
                    expression += f".{item_attribute}"
                family.variables[variable] = expression
        taken_names.add(list_name)
        families.append(family)
    return families


# Item attributes that hold money in AssemblyLine's al_income classes
MONEY_ATTRIBUTES = frozenset({"market_value", "balance", "value"})


def _label(attribute: str) -> str:
    return attribute.replace("_", " ").capitalize()


def _field_lines(
    list_name: str, attributes: Iterable[str], datatypes: Dict[str, str]
) -> List[str]:
    lines = []
    for attribute in attributes:
        lines.append(f'  - "{_label(attribute)}": {list_name}[i].{attribute}')
        lines += [
            f"    {line}"
            for line in generator_constants.FIELD_TYPE_YAML.get(
                datatypes.get(attribute, "text"), []
            )
        ]
    return lines


def row_family_yaml(family: RowFamily, datatypes: Dict[str, str]) -> str:
    """The question and code blocks that gather one family's rows.

    AssemblyLine's own questions ask for the standard attributes of its list
    classes and for people's names; these blocks ask for everything else and
    mark each item complete only once all of it is known. That matters because
    the attachment is filled with `skip undefined`, so anything not gathered
    here would print blank rather than be asked.

    Args:
        family (RowFamily): the family.
        datatypes (Dict[str, str]): the Weaver field type of each attribute.

    Returns:
        str: YAML blocks, each starting with `---`.
    """
    name = family.list_name
    singular = family.stem.replace("_", " ")
    extra = family.question_attributes()
    blocks: List[str] = []
    if family.object_type == "DAList":
        blocks.append("---\n" + render_baseline_question(name, "there_are_any"))
        blocks.append(
            "\n".join(
                [
                    "---",
                    f"id: {name} item",
                    "question: |",
                    f"  Tell us about the ${{ ordinal(i) }} {singular}",
                    "fields:",
                ]
                + _field_lines(name, extra, datatypes)
            )
        )
        blocks.append("---\n" + render_baseline_question(name, "there_is_another"))
        first = f"{name}[i].{extra[0]}" if extra else f"{name}[i]"
    else:
        if extra:
            blocks.append(
                "\n".join(
                    [
                        "---",
                        f"id: more about {name}",
                        "question: |",
                        f"  More about the ${{ ordinal(i) }} {singular}",
                        "fields:",
                    ]
                    + _field_lines(name, extra, datatypes)
                )
            )
        first = {
            "ALVehicleList": f"{name}[i].year",
            "ALAssetList": f"{name}[i].market_value",
            "ALPeopleList": f"{name}[i].name.first",
        }[family.object_type]
    completion = ["---", f"id: {name} item is complete", "code: |", f"  {first}"]
    completion += [
        f"  {name}[i].{attribute}"
        for attribute in extra
        if f"{name}[i].{attribute}" != first
    ]
    completion.append(f"  {name}[i].complete = True")
    blocks.append("\n".join(completion))
    return "\n".join(blocks) + "\n"

"""Let a language model propose structure the rules can't see, and check it.

The rest of AI drafting only touches labels, datatypes and screens. What
authors actually change when they finish a draft is structure: which field is
really `users[0].birthdate`, which checkboxes are one question and whether only
one may be ticked, and which field only matters after a particular answer.

The model is asked for exactly those three kinds of proposal, in a fixed JSON
shape, each with a quote from the form that supports it. Nothing it says is
applied unless it checks out:

* A **remap** names an AssemblyLine label for a field, like `user_birthdate`.
  The Weaver's own labelling rules have to recognize that label, so a remap
  can only ever land on something the Weaver already knows how to ask about.
* A **choice group** names checkboxes that already exist, are yes/no boxes, and
  aren't already in a group, or names a group the rules made and says whether
  only one of its boxes may be ticked.
* A **condition** ties a field to a yes/no box or to one choice of a group.

Every proposal must quote text that is really in the form. Whatever is applied
is reported back so the author can see it, with that quote.
"""

import json
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

__all__ = ["STRUCTURE_PROMPT", "build_structure_request", "validated_proposals"]

STRUCTURE_PROMPT = """
You are helping turn a court form into a guided interview. You get the form's
text and its fields. Propose only changes the form's own text supports, and
quote that text exactly (a short phrase is enough) as `evidence`.

Return a JSON object with these keys, each a list (empty if nothing applies):

- "remaps": a field that is really a standard fact about a person, court or
  case. "field" is copied exactly from the Fields list; "assemblyline_label"
  is the standard label it should have, built like user_birthdate,
  user_name_full, user_address_city, user_phone, user_email,
  user2_name_first, other_party_name_full, child1_birthdate,
  user_pronouns, trial_court_division, docket_number or signature_date.
  When the form asks for someone's pronouns, remap that field to
  user_pronouns (or other_party_pronouns, and so on): AssemblyLine has its
  own pronouns question, so never leave pronouns as a text field.
  Shape: {"field": "...", "assemblyline_label": "...", "evidence": "..."}
  Example: {"field": "date_of_birth", "assemblyline_label": "user_birthdate", "evidence": "Date of Birth"}
- "choice_groups": separate yes/no boxes that are really answers to one
  question, or an existing group whose boxes the form says only one of may
  be ticked. Use "radio" only when the form says to pick one (for example
  "check one"); otherwise "checkboxes".
  Shape: {"fields": ["...", "..."], "variable": "short_name", "kind": "radio"|"checkboxes", "evidence": "..."}
  For an existing group, give just {"field": "group_variable", "kind": "radio", "evidence": "..."}.
- "conditions": a field that only applies after a particular answer, like
  "If yes, explain". Name the controlling field and, for a group, the choice.
  Shape: {"field": "...", "when": "controlling_field", "choice": "optional choice value", "evidence": "..."}

Every name in "field", "fields" and "when" must be copied exactly from the
Fields list; choices are not fields. Never invent fields. Leave a list empty
rather than guess.
""".strip()


def build_structure_request(fields: Sequence[Mapping[str, Any]]) -> str:
    """The field list the model sees, one JSON object per field."""
    return json.dumps(list(fields), indent=0)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text).lower())).strip()


def _supported(evidence: Any, context: str, min_words: int = 1) -> bool:
    """True if the quote is really in the form (ignoring case and punctuation)."""
    quote = _normalized(evidence or "")
    return (
        len(quote) >= 3
        and len(quote.split()) >= min_words
        and quote in _normalized(context)
    )


def _differ_only_by_numbers(names: Sequence[str]) -> bool:
    """`is_guardian1_update` and `is_guardian2_update` are one question per person."""
    return len({re.sub(r"\d+", "#", name) for name in names}) == 1


def validated_proposals(
    response: Any,
    context: str,
    fields: Mapping[str, Mapping[str, Any]],
    label_maps_to: Callable[[str], Optional[str]],
) -> Dict[str, List[Dict[str, Any]]]:
    """The proposals in a model reply that pass every check.

    Args:
        response (Any): the model's JSON reply.
        context (str): the form text the model saw.
        fields (Mapping[str, Mapping[str, Any]]): the fields it may name, by
            variable, each with `type`, `pdf` and, for a group, `choices`.
        label_maps_to (Callable[[str], Optional[str]]): what the Weaver's
            labelling rules make of a label, or None if they don't recognize it.

    Returns:
        Dict[str, List[Dict[str, Any]]]: the accepted `remaps`,
        `choice_groups` and `conditions`.
    """
    accepted: Dict[str, List[Dict[str, Any]]] = {
        "remaps": [],
        "choice_groups": [],
        "conditions": [],
    }
    if not isinstance(response, dict):
        return accepted
    used: set = set()

    for remap in response.get("remaps") or []:
        if not isinstance(remap, dict):
            continue
        field = str(remap.get("field", ""))
        label = str(remap.get("assemblyline_label") or remap.get("label") or "")
        if field not in fields and label in fields:
            # Models sometimes swap the two; one side has to be a real field
            field, label = label, field
        info = fields.get(field)
        if not info or not info.get("pdf") or field in used:
            continue
        target = label_maps_to(label)
        if not target or not _supported(remap.get("evidence"), context):
            continue
        accepted["remaps"].append(
            {
                "field": field,
                "label": label,
                "target": target,
                "evidence": remap["evidence"],
            }
        )
        used.add(field)

    for group in response.get("choice_groups") or []:
        if not isinstance(group, dict) or not _supported(
            group.get("evidence"), context
        ):
            continue
        kind = group.get("kind")
        if kind not in ("radio", "checkboxes"):
            continue
        if "fields" not in group and isinstance(group.get("field"), str):
            # Deciding that an existing group allows only one answer
            info = fields.get(group["field"])
            if (
                info
                and info.get("type") == "multiple choice checkboxes"
                and kind == "radio"
            ):
                accepted["choice_groups"].append(
                    {
                        "field": group["field"],
                        "kind": "radio",
                        "evidence": group["evidence"],
                    }
                )
            continue
        members = [str(name) for name in group.get("fields") or []]
        variable = str(group.get("variable", ""))
        # A pair of boxes is far more often two separate yes/no questions than
        # one question's choices, and "Yes/No" is not evidence of either
        if (
            len(members) < 3
            or not _supported(group.get("evidence"), context, min_words=3)
            or _differ_only_by_numbers(members)
            or len(set(members)) != len(members)
            or not variable.isidentifier()
            or variable in fields
            or any(
                name in used
                or not fields.get(name, {}).get("pdf")
                or fields.get(name, {}).get("type") != "yesno"
                for name in members
            )
        ):
            continue
        accepted["choice_groups"].append(
            {
                "fields": members,
                "variable": variable,
                "kind": kind,
                "evidence": group["evidence"],
            }
        )
        used.update(members)

    for condition in response.get("conditions") or []:
        if not isinstance(condition, dict) or not _supported(
            condition.get("evidence"), context
        ):
            continue
        field, when = str(condition.get("field", "")), str(condition.get("when", ""))
        dependent, control = fields.get(field), fields.get(when)
        if not dependent or not control or field == when or field in used:
            continue
        choice = condition.get("choice")
        if control.get("type") == "yesno" and not choice:
            accepted["conditions"].append(
                {
                    "field": field,
                    "when": when,
                    "choice": None,
                    "evidence": condition["evidence"],
                }
            )
        elif choice is not None and str(choice) in control.get("choices", []):
            accepted["conditions"].append(
                {
                    "field": field,
                    "when": when,
                    "choice": str(choice),
                    "evidence": condition["evidence"],
                }
            )
    return accepted

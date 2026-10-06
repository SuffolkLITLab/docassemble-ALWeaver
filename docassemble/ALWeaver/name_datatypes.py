"""Guess a field's datatype from the words in its name.

These rules only ever replace a plain `text` guess: a type the template states
outright (a PDF checkbox, a DOCX `currency()` call, a date suffix the Weaver
already knew) always wins.

They were checked against 969 variables that both a Weaver draft and the
author's published interview define, across 159 real court forms. Applied on
top of the older rules they raised agreement with the author's datatype from
68% to 74%. The exclusions below come from the counterexamples that check
turned up: `parent1_date_month` is one part of a date split across three
boxes, `rental_income_source` is a description rather than an amount, and
`user_mail_address_city` is not an email address.
"""

import re
from typing import Optional

__all__ = ["datatype_from_name", "label_calls_for_area"]

# Names that look like a type below but aren't: parts of a split date, and
# words that describe an amount or a date rather than being one
_NOT_A_TYPED_VALUE = re.compile(
    r"_(year|month|day|yr|mo)$"
    r"|(^|_)(source|location|number|contents|address|account|type|name|id)$"
)
_DATE = re.compile(r"(^|_)(date|birthdate|dob)($|_)|(^|_)(deadline|expiration)($|_)")
_EMAIL = re.compile(r"email")
# Money words count only at the end: `rent_amount` is money, `rent_address` isn't
_CURRENCY = re.compile(
    r"(^|_)(amount|amt|rent|wages|damages|debt|arrears|owed|balance|fee|fees"
    r"|cost|costs|price|salary|income|payment|deposit|expenses?)$"
)
_WHOLE_NUMBER = re.compile(
    r"(^|_)(count|days|number_of|years|months|household_size|age)($|_)"
)
_NARRATIVE = re.compile(
    r"(^|_)(describe|description|explain|explanation|explination|reason|reasons"
    r"|because|facts|arguments?|details|issues|conclusion|summary|relief_sought"
    r"|basis|harm|narrative|comments?|statement)($|_)"
)
# The same idea for a label someone reads ("Legal arguments", "What
# happened"). Checked separately: of 135 text-or-area fields in authored
# interviews whose labels use these words, 65% were text areas.
_NARRATIVE_LABEL = re.compile(
    r"\b(explain|explanation|describe|description|arguments?|facts|reasons?"
    r"|what happened|details|conclusion|relief|issues|circumstances|summary"
    r"|statement|history|background|narrative)\b",
    re.IGNORECASE,
)
_QUESTION_WORD = re.compile(
    r"^(is|has|have|had|was|were|did|does|do|dont|can|will|wants?|needs?"
    r"|should|are)_"
)


def _leaf(variable: str) -> str:
    """The last part of a variable: `users[0].monthly_rent` -> `monthly_rent`."""
    return re.split(r"[\.\]]", variable)[-1].lower()


def datatype_from_name(
    variable: str, document_type: str, knows_box_size: bool = False
) -> Optional[str]:
    """The datatype a field's name suggests, or None if it suggests nothing.

    Args:
        variable (str): the field's variable name.
        document_type (str): "pdf" or "docx".
        knows_box_size (bool): whether the size of the PDF box is known. A box
            already says whether an answer fits on one line, which beats a
            word like "reason" in the name.

    Returns:
        Optional[str]: a Weaver field type, or None.
    """
    leaf = _leaf(variable)
    if _NOT_A_TYPED_VALUE.search(leaf):
        return None
    if _DATE.search(leaf):
        return "date"
    if _EMAIL.search(leaf):
        return "email"
    if _CURRENCY.search(leaf):
        return "currency"
    if _WHOLE_NUMBER.search(leaf):
        return "integer"
    if not knows_box_size and _NARRATIVE.search(leaf):
        return "area"
    if document_type == "docx" and _QUESTION_WORD.search(leaf):
        return "yesno"
    return None


def label_calls_for_area(label: str) -> bool:
    """True if a field's label asks for an answer longer than a line.

    Args:
        label (str): the label someone reads.

    Returns:
        bool: True for labels like "Legal arguments" or "What happened".
    """
    return bool(_NARRATIVE_LABEL.search(label or ""))

"""Group a template's fields into screens without asking a language model.

Fields arrive in the order they appear in the template, which is already a
good guide to what belongs together: a form asks for an address, line by line,
before it moves on to something else. The rules here only decide where one
topic ends and the next begins, and keep any one screen short.

Measured against the screens authors actually wrote for 73 real court forms,
these rules agreed on twice as many "these two fields share a screen" pairs as
FormFyxer's keyword fallback (pairwise F1 0.39 against 0.17), which put every
unmatched field on a single screen of up to 180 fields.
"""

import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "FILLER_NAME_WORDS",
    "MAX_FIELDS_PER_SCREEN",
    "group_fields_into_screens",
    "unique_titles",
]

# Authors' screens average under 3 fields; 6 leaves room for an address block
MAX_FIELDS_PER_SCREEN = 6

# Words that start many unrelated names, so they can't say what a field is about
FILLER_NAME_WORDS = frozenset(
    {
        "a",
        "are",
        "client",
        "did",
        "do",
        "does",
        "has",
        "if",
        "is",
        "my",
        "of",
        "other",
        "the",
        "user",
        "users",
        "was",
    }
)


def _words(variable: str) -> List[str]:
    """The lowercase words of a variable name, without index numbers."""
    return [
        word
        for word in re.split(r"[_\.\[\]'\"]+", variable.lower())
        if word and not word.isdigit()
    ]


def _topic(variable: str) -> str:
    """The first word that says what a field is about, plus any filler before it.

    `notice_type_mail` is about "notice"; `is_tenant_disabled` is about
    "is tenant", so it doesn't land with every other `is_` question.
    """
    topic: List[str] = []
    for word in _words(variable):
        topic.append(word)
        if word not in FILLER_NAME_WORDS:
            break
    return "_".join(topic)


def _screen_title(variables: Sequence[str], label_for: Callable[[str], str]) -> str:
    """A title from the words every field on the screen starts with."""
    if len(variables) == 1:
        return label_for(variables[0])
    word_lists = [_words(variable) for variable in variables]
    shared: List[str] = []
    for position_words in zip(*word_lists):
        if len(set(position_words)) != 1:
            break
        shared.append(position_words[0])
    if not shared:
        return label_for(variables[0])
    return " ".join(shared).capitalize()


def group_fields_into_screens(
    variables: Sequence[str],
    label_for: Optional[Callable[[str], str]] = None,
    max_per_screen: int = MAX_FIELDS_PER_SCREEN,
) -> List[Tuple[str, List[str]]]:
    """Split fields, in template order, into short screens about one topic each.

    A new screen starts when the topic of the field names changes, or when the
    current screen is full. Two one-field screens in a row are merged, since a
    string of single unrelated questions is what a form's loose ends look like.

    Args:
        variables (Sequence[str]): the field variables, in template order.
        label_for (Optional[Callable[[str], str]]): the label for a variable,
            used to title a screen with only one field on it.
        max_per_screen (int): the most fields one screen may hold.

    Returns:
        List[Tuple[str, List[str]]]: each screen's title and its variables.
    """
    if label_for is None:
        label_for = lambda variable: variable.replace("_", " ").capitalize()
    runs: List[List[str]] = []
    current_topic = None
    for variable in dict.fromkeys(variables):
        topic = _topic(variable)
        if runs and topic == current_topic and len(runs[-1]) < max_per_screen:
            runs[-1].append(variable)
        else:
            runs.append([variable])
        current_topic = topic

    screens: List[List[str]] = []
    for run in runs:
        if screens and len(run) == 1 and len(screens[-1]) == 1:
            screens[-1].append(run[0])
        else:
            screens.append(run)
    return [(_screen_title(screen, label_for), screen) for screen in screens]


def unique_titles(screens: Sequence[Tuple[str, List[str]]]) -> Dict[str, List[str]]:
    """Key the screens by title, numbering any title that repeats."""
    grouped: Dict[str, List[str]] = {}
    for title, variables in screens:
        key = title
        number = 2
        while key in grouped:
            key = f"{title} {number}"
            number += 1
        grouped[key] = list(variables)
    return grouped

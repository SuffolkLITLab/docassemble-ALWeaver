"""Keep AI-written interview text plain and useful.

Two checks on what a model writes for a draft interview:

* :func:`is_filler_subquestion` spots helper text that only tells someone to
  do what the screen already asks ("Type your contact information below",
  "Have the appeal details ready"). A subquestion earns its place by saying
  why a question is asked or how to answer it correctly; filler adds reading
  without adding either.
* :func:`plain_language_flags` finds formal or legalistic words using the
  replacement table DAYamlChecker's style linter uses, so the Weaver and the
  linter agree on which words to avoid. A word is flagged even when the form
  uses it: complex forms use plenty of legal words, and the draft should
  still read plainly. The author can put a term back where it is needed.
"""

import re
from functools import lru_cache
from typing import Dict, List, Sequence, Tuple

__all__ = [
    "flags_by_text",
    "is_filler_subquestion",
    "plain_language_flags",
    "PLAIN_LANGUAGE_GUIDANCE",
]

# A sentence that only restates the screen's job: "Enter your address below",
# "Have your docket number ready", "Confirm the method of filing"
_FILLER_START = re.compile(
    r"^(please\s+)?("
    r"type|enter|fill\s+(in|out)|provide|give|add|answer|complete|confirm|review"
    r"|tell\s+us|share|list|write|select|choose|pick|check|input|use"
    r"|let\s+us\s+know|have\b.*\bready|gather|get\b.*\bready"
    r"|this\s+(screen|section|page|step)\s+(asks|is|collects|covers)"
    r"|(the\s+)?(questions|fields)\s+below"
    r"|(we|we'll|we\s+will)\s+(ask|need|collect)"
    r")\b",
    re.IGNORECASE,
)
# Words that make an instruction worth reading: a reason, a condition, an
# example, what counts, how much to write, or where to find the answer.
# Calibrated on 523 short subquestions authors wrote in published interviews.
_EXPLAINS = re.compile(
    r"\b(who|whose|which|where\s+you|that\s+(apply|are\s+true|is\s+true)|everything"
    r"|at\s+least|one\s+at\s+a\s+time|as\s+(many|much|specific)"
    r"|detailed|in\s+a\s+few|sentences?|in\s+dollars|including|matches|same\s+as"
    r"|because|so\s+that|so\s+the|if|unless|even|only|except|do\s+not|don't"
    r"|never|for\s+example|e\.g\.|such\s+as|must|required|law|court\s+(needs|uses)"
    r"|found\s+on|listed\s+on|printed\s+on|you\s+can\s+find|from\s+your|on\s+your"
    r"|top\s+of|bottom\s+of|deadline|within|before|after)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def is_filler_subquestion(text: str) -> bool:
    """True if every sentence of a subquestion only restates the screen's job.

    Args:
        text (str): the subquestion.

    Returns:
        bool: True if it can be dropped without losing anything.
    """
    if not text or "${" in text or "%" in text:
        return False
    sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip()]
    if not sentences:
        return False
    return all(
        _FILLER_START.search(sentence) and not _EXPLAINS.search(sentence)
        for sentence in sentences
    )


# What the plain-language rewrite asks for
PLAIN_LANGUAGE_GUIDANCE = """
Write the way a helpful person talks, at about a 6th grade reading level:
- Use everyday words: "get" not "obtain", "want" not "seek", "ask the court"
  not "petition the court", "before" not "prior to", "about" not "regarding".
- Leave legal words out, even when the form uses them: say what the word
  means instead. The author can add a term back where the person needs it to
  take part in the case.
- No acronyms unless the form uses them.
- Address the person as "you". Avoid formal phrasing like "presented",
  "pursuant to", "herein", "set forth", "the undersigned" or "said".
""".strip()


# Entries from SuffolkLITLab/DAYamlChecker#95, until a release includes them.
# The table only matches exact words, so the tense-matched forms are listed
# one by one: checked against 180 published interviews, matching every ending
# of every word also flagged ordinary words like "required" and "completed".
_SUPPLEMENT: Dict[str, str] = {
    "advised": "[told, recommended]",
    "aforementioned": "[this, that, (omit)]",
    "anticipated": "expected",
    "are employed": "[are working, have jobs]",
    "attained": "[reached, finished]",
    "commenced": "[started, began]",
    "currently employed": "[working now, have a job]",
    "expired": "[ran out, ended]",
    "granted": "[approved, given]",
    "in the event that": "if",
    "incurred": "[had, owed]",
    "indicated": "[said, showed]",
    "is employed": "[is working, has a job]",
    "notified": "told",
    "obligated": "[required, must]",
    "obtained": "[got, received]",
    "obtaining": "[getting, receiving]",
    "permitted": "allowed",
    "presented": "[shown, given]",
    "prohibited": "not allowed",
    "provided": "[gave, given]",
    "providing": "giving",
    "purchased": "bought",
    "set forth": "[listed, written, explained]",
    "submitted": "[sent, given]",
    "submitting": "sending",
    "terminated": "[ended, stopped]",
    "utilized": "used",
    "whereby": "[by which, so]",
}
# Fine in context, as DAYamlChecker's linter also treats them
_CONTEXTUAL = frozenset(
    {"request", "report", "benefit", "following", "please", "select", "option"}
)


def _load_table() -> Dict[str, str]:
    """DAYamlChecker's plain-language replacement table, plus the supplement."""
    table: Dict[str, str] = {}
    try:
        import yaml
        from importlib.resources import files

        loaded = yaml.safe_load(
            files("dayamlchecker")
            .joinpath("data", "plain_language_replacements.yml")
            .read_text(encoding="utf-8")
        )
    except Exception:  # pragma: no cover - dayamlchecker is a dependency
        loaded = {}
    for key, value in {
        **(loaded if isinstance(loaded, dict) else {}),
        **_SUPPLEMENT,
    }.items():
        term = str(key).strip().lower().replace("\u2019", "'")
        replacement = str(value).strip().strip("[]").strip()
        if (
            term
            and replacement
            and term not in _CONTEXTUAL
            and re.search(r"[a-z]", term)
        ):
            table[term] = replacement
    return table


@lru_cache(maxsize=1)
def _replacement_patterns() -> Tuple[Tuple[str, "re.Pattern[str]"], ...]:
    """Each formal term's suggestion and pattern, longest terms first, matched
    the way DAYamlChecker's linter matches them."""
    return tuple(
        (
            replacement,
            re.compile(
                rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", re.IGNORECASE
            ),
        )
        for term, replacement in sorted(
            _load_table().items(), key=lambda item: len(item[0]), reverse=True
        )
    )


def plain_language_flags(text: str) -> List[Tuple[str, str]]:
    """Formal words in `text`, each with the plainer words to use instead.

    Args:
        text (str): text a model wrote.

    Returns:
        List[Tuple[str, str]]: `(word as written, suggested replacements)`.
    """
    if not text:
        return []
    found: List[Tuple[str, str]] = []
    taken: List[Tuple[int, int]] = []
    for replacement, pattern in _replacement_patterns():
        match = pattern.search(text)
        if not match:
            continue
        span = match.span()
        if any(not (span[1] <= start or span[0] >= end) for start, end in taken):
            continue
        taken.append(span)
        found.append((match.group(0), replacement))
    return found


def flags_by_text(texts: Sequence[str]) -> Dict[str, List[Tuple[str, str]]]:
    """:func:`plain_language_flags` for each text that has any."""
    out: Dict[str, List[Tuple[str, str]]] = {}
    for text in texts:
        flags = plain_language_flags(text)
        if flags:
            out[text] = flags
    return out

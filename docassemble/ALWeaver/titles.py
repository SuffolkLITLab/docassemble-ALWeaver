"""Turn an uploaded template's filename into a title a person would write."""

import os
import re
from typing import List

__all__ = ["title_from_filename"]

# Words that describe the upload, not the form: how it was prepared for the
# Weaver, or which copy of it this is. All were found in real filenames, like
# `petition_to_name_change_minor_cjp25_fielded.pdf` and
# `Interpreternotice-with variables.docx`.
_UPLOAD_WORDS = re.compile(
    r"\b(?:fielded|re[- ]?labell?ed|labell?ed|highlighted|with variables|variables"
    r"|templates?|docassemble project|docassemble|weaver|draft|final|copy|fillable"
    r"|qc|v\d+(?:\.\d+)*)\b",
    re.IGNORECASE,
)
# `(1)` or a trailing ` 1` that a download or upload added to make the name unique
_COPY_NUMBER = re.compile(r"\s*\(\d+\)\s*$|(?<=[a-z])\s+\d$", re.IGNORECASE)
# A form number written as one word: `cjp25`, `mpc821`, `eoir28`
_JOINED_FORM_NUMBER = re.compile(r"^([a-z]{2,5})(\d{1,6}[a-z]?)$", re.IGNORECASE)
# A form number's letters on their own, when the number follows: `mpc 821`
_FORM_LETTERS = re.compile(r"^[a-z]{2,4}$", re.IGNORECASE)


def _spell_form_numbers(words: List[str]) -> List[str]:
    spelled: List[str] = []
    for index, word in enumerate(words):
        joined = _JOINED_FORM_NUMBER.match(word)
        following = words[index + 1] if index + 1 < len(words) else ""
        if joined:
            spelled.append(f"{joined.group(1).upper()} {joined.group(2).upper()}")
        elif re.fullmatch(r"\d+[a-z]", word, re.IGNORECASE):
            # `209a` is a statute or form number, written `209A`
            spelled.append(word.upper())
        elif _FORM_LETTERS.match(word) and re.fullmatch(r"\d[\d-]*", following):
            spelled.append(word.upper())
        else:
            spelled.append(word)
    return spelled


def title_from_filename(filename: str) -> str:
    """A title from an uploaded template's filename.

    `petition_to_name_change_minor_cjp25_fielded.pdf` becomes
    "Petition to name change minor CJP 25". The words the upload adds, like
    "fielded" or "v1.3", are dropped, and form numbers keep their capitals.
    If nothing is left after that, the plain cleaned-up name is used.

    Args:
        filename (str): a filename or path.

    Returns:
        str: the title.
    """
    base = os.path.splitext(os.path.basename(str(filename or "").strip()))[0]
    spaced = re.sub(r"[_\s]+|(?<=\w)-(?=\w)", " ", base)
    plain = re.sub(r"\s+", " ", spaced).strip()
    cleaned = _COPY_NUMBER.sub("", _UPLOAD_WORDS.sub(" ", plain))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    # `plaintiff_s_motion` lost its apostrophe on the way to being a filename
    cleaned = re.sub(r"(?<=[a-z]) s(?= |$)", "'s", cleaned or plain, flags=re.I)
    words = cleaned.split(" ")
    if not words or not words[0]:
        return ""
    words = _spell_form_numbers(
        [words[0].capitalize()] + [w.lower() for w in words[1:]]
    )
    return " ".join(words)

"""Filenames a Docassemble project can actually use.

Docassemble resolves a Playground template reference by stripping every
character outside ``[A-Za-z0-9-_. ]`` out of the name written in the YAML and
then looking for a file called what is left. A template uploaded as
``93A_demand_letter (1).docx`` lands in the templates folder under that name,
but the ``docx template file:`` line pointing at it resolves to
``93A_demand_letter 1.docx``, which is not there -- so the interview reports a
missing template for a file the author can plainly see. See
``package_template_filename`` in ``docassemble.base.functions``.

The fix is to never let such a name into a project in the first place: an
upload is renamed once, at the door, and the stored file and every reference
the generated YAML makes to it use that one name.
"""

import os
import re
import unicodedata

__all__ = ["safe_project_filename", "is_safe_project_filename"]

# Anything outside this set becomes an underscore. Spaces are inside what
# Docassemble will resolve, but they make for awkward YAML, shell arguments and
# package contents, so they go too.
_UNSAFE_RUN = re.compile(r"[^A-Za-z0-9._-]+")
# `report - final` should read `report-final`, not `report_-_final`.
_PADDED_PUNCTUATION = re.compile(r"_*([.-])_*")
_REPEATED_UNDERSCORES = re.compile(r"__+")


def _clean(part: str) -> str:
    """Reduce one piece of a filename to characters Docassemble keeps."""
    cleaned = _UNSAFE_RUN.sub("_", part)
    cleaned = _PADDED_PUNCTUATION.sub(r"\1", cleaned)
    cleaned = _REPEATED_UNDERSCORES.sub("_", cleaned)
    return cleaned.strip("._-")


def safe_project_filename(filename: str, *, default_stem: str = "file") -> str:
    """Rename a file to something a Docassemble project can refer to.

    The name keeps its extension and as much of its stem as survives: letters,
    digits, ``.``, ``-`` and ``_``. Everything else -- spaces, parentheses,
    accents, quotes -- collapses to a single underscore.

    Args:
        filename (str): the name as uploaded, which may include a directory.
        default_stem (str): what to call a file whose stem is left empty, as
            an upload named only with punctuation would be.

    Returns:
        str: a filename with no directory part and no surprising characters.
    """
    name = os.path.basename(str(filename or "").strip())
    # Turn accented letters into their plain equivalents rather than dropping
    # them: `Citación.pdf` should be `Citacion.pdf`, not `Citacin.pdf`.
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")

    stem, extension = os.path.splitext(name)
    stem = _clean(stem)
    extension = _clean(extension)
    if not stem:
        stem = _clean(default_stem) or "file"
    return f"{stem}.{extension}" if extension else stem


def is_safe_project_filename(filename: str) -> bool:
    """True when :func:`safe_project_filename` would leave this name alone."""
    return bool(filename) and safe_project_filename(filename) == filename

from jinja2 import DebugUndefined
from jinja2.utils import missing
from docxtpl import DocxTemplate
from docx2python import docx2python
from jinja2 import Environment, BaseLoader
import jinja2.exceptions
from docassemble.base.util import DAFile
from docassemble.base.parse import (
    DAEnvironment,
    DAExtension,
    registered_jinja_filters,
)

try:
    # Pre 1.4.56
    from docassemble.base.parse import builtin_jinja_filters
except:
    from docassemble.base.parse import get_builtin_jinja_filters

    builtin_jinja_filters = get_builtin_jinja_filters()
import docassemble.base.util
import keyword
import docassemble.AssemblyLine.al_general
import docassemble.AssemblyLine.al_document
import docassemble.AssemblyLine.language

# import docassemble.AssemblyLine.sessions
import docassemble.ALToolbox.misc
from typing import Optional, Iterable, Set, Union, List
import re
import pikepdf

__all__ = [
    "CallAndDebugUndefined",
    "get_jinja_errors",
    "get_mako_matches",
    "matching_reserved_names",
    "all_reserved_names",
    "has_fields",
]


all_reserved_names = set(
    docassemble.base.util.__all__
    + docassemble.AssemblyLine.al_general.__all__
    + docassemble.AssemblyLine.al_document.__all__
    + docassemble.AssemblyLine.language.__all__
    # + docassemble.AssemblyLine.sessions.__all__
    + docassemble.ALToolbox.misc.__all__
    + keyword.kwlist
    + list(dir(__builtins__))
    + [
        "_attachment_email_address",
        "_attachment_include_editable",
        "_back_one",
        "_checkboxes",
        "_datatypes",
        "_email_attachments",
        "_files",
        "_question_number",
        "_question_name",
        "_save_as",
        "_success",
        "_the_image",
        "_track_location",
        "_tracker",
        "_varnames",
        "_internal",
        "nav",
        "session_local",
        "device_local",
        "user_local",
        "url_args",
        "role_needed",
        "x",
        "i",
        "j",
        "k",
        "l",
        "m",
        "n",
        "role",
        "speak_text",
        "track_location",
        "multi_user",
        "menu_items",
        "allow_cron",
        "incoming_email",
        "role_event",
        "cron_hourly",
        "cron_daily",
        "cron_weekly",
        "cron_monthly",
        "_internal",
        "allow_cron",
        "cron_daily",
        "cron_hourly",
        "cron_monthly",
        "cron_weekly",
        "caller",
        "device_local",
        "loop",
        "incoming_email",
        "menu_items",
        "multi_user",
        "nav",
        "role_event",
        "role_needed",
        "row_index",
        "row_item",
        "self",
        "session_local",
        "speak_text",
        "STOP_RENDERING",
        "track_location",
        "url_args",
        "user_local",
        "user_dict",
        "allow_cron",
    ]
)

just_keywords_and_builtins = set(list(keyword.kwlist) + list(dir(__builtins__)))


def matching_reserved_names(
    field_names: Iterable[str], keywords_and_builtins_only: bool = False
) -> Set[str]:
    """
    Returns a list of the matching reserved keywords in the given list of
    field names. Will parse to remove brackets and attribute names.
    """
    word_part = re.compile(r"(^\w+)[\[\.]*")
    matches = set()
    for word in field_names:
        match = word_part.match(word)
        if match:
            matches.add(match[0])
    if keywords_and_builtins_only:
        return matches.intersection(just_keywords_and_builtins)
    return matches.intersection(all_reserved_names)


class CallAndDebugUndefined(DebugUndefined):
    """Handles Jinja2 undefined errors by printing the name of the undefined variable.
    Extended to handle callable methods.
    """

    def __call__(self, *pargs, **kwargs):
        return self

    def __getattr__(self, _: str) -> "CallAndDebugUndefined":
        return self

    __getitem__ = __getattr__  # type: ignore


def get_jinja_errors(the_file: DAFile) -> Optional[str]:
    """Just try rendering the DOCX file as a Jinja2 template and catch any errors.
    Returns a string with the errors, if any.
    """
    env = DAEnvironment(undefined=CallAndDebugUndefined, extensions=[DAExtension])
    env.filters.update(registered_jinja_filters)
    env.filters.update(builtin_jinja_filters)

    doc = DocxTemplate(the_file.path())
    try:
        doc.render({}, jinja_env=env)
        return None
    except jinja2.exceptions.TemplateSyntaxError as the_error:
        errmess = str(the_error)
        extra_context = the_error.docx_context if hasattr(the_error, "docx_context") else []  # type: ignore
        if extra_context:
            errmess += "\n\nContext:\n" + "\n".join(
                map(lambda x: "  " + x, extra_context)
            )
        return errmess


def get_mako_matches(the_file: DAFile) -> Iterable[str]:
    """Find's instances of mako in the file's DOCX content's"""
    match_mako = (
        r"\${[^{].*\}"  # look for ${ without a double {{, for cases of dollar values
    )
    docx_data = docx2python(the_file.path())  # Will error with invalid value
    return re.findall(match_mako, docx_data.text)


def has_fields(pdf_file: str) -> bool:
    """
    Check if a PDF has at least one form field using PikePDF.

    Args:
        pdf_file (str): The path to the PDF file.

    Returns:
        bool: True if the PDF has at least one form field, False otherwise.
    """
    with pikepdf.open(pdf_file) as pdf:
        for page in pdf.pages:
            if "/Annots" in page:
                for annot in page.Annots:  # type: ignore
                    try:
                        if annot.Type == "/Annot" and annot.Subtype == "/Widget":
                            return True
                    except:
                        continue
    return False

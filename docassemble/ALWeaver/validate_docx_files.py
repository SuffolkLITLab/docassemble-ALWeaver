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
    builtin_jinja_filters,
)

from typing import Optional, Iterable
import re

__all__ = ["CallAndDebugUndefined", "get_jinja_errors", "get_mako_matches"]


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

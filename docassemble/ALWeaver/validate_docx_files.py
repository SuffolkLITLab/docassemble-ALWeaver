from jinja2 import Undefined
from jinja2.utils import missing
from docxtpl import DocxTemplate
from jinja2 import Environment, BaseLoader
import jinja2.exceptions
from docassemble.base.util import DAFile

__all__ = ['CallAndDebugUndefined', 'get_jinja_errors']

class CallAndDebugUndefined(Undefined):
    """Handles Jinja2 undefined errors by printing the name of the undefined variable.
    Extended to handle callable methods.
    """

    __slots__ = ()

    def __str__(self) -> str:
        if self._undefined_hint:
            message = f"undefined value printed: {self._undefined_hint}"

        elif self._undefined_obj is missing:
            message = self._undefined_name  # type: ignore

        else:
            message = (
                f"no such element: {object_type_repr(self._undefined_obj)}"
                f"[{self._undefined_name!r}]"
            )

        return f"{{{{ {message} }}}}"
      
    def __call__(self, *pargs, **kwargs):
        return self
      
    def __getattr__(self, _: str) -> "CallAndDebugUndefined":
        return self

    __getitem__ = __getattr__  # type: ignore      
    

def get_jinja_errors(the_file:DAFile)->str:
  """Just try rendering the DOCX file as a Jinja2 template and catch any errors.
  Returns a string with the errors, if any.
  """
  env = Environment(loader=BaseLoader,undefined=CallAndDebugUndefined)
  
  doc = DocxTemplate(the_file.path())
  try: 
    doc.render({}, jinja_env=env)
  except jinja2.exceptions.TemplateSyntaxError as the_error:
    errmess = str(the_error)
    if hasattr(the_error, 'docx_context'):
      errmess += "\n\nContext:\n" + "\n".join(map(lambda x: "  " + x, the_error.docx_context))
    return errmess
  
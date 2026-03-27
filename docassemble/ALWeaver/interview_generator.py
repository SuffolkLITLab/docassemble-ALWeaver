from .custom_values import get_matching_deps, get_output_mako_package_and_path
from .generator_constants import generator_constants
from .validate_template_files import matching_reserved_names, has_fields
from collections import defaultdict
from dataclasses import field
from docassemble.base.util import (
    bold,
    comma_list,
    comma_and_list,
    current_context,
    DADict,
    DAEmpty,
    DAFile,
    DAFileCollection,
    DAFileList,
    DAList,
    DAObject,
    DAStaticFile,
    get_config,
    log,
    path_and_mimetype,
    pdf_concatenate,
    space_to_underscore,
    user_info,
    user_logged_in,
)
from docx2python import docx2python
from enum import Enum
from itertools import zip_longest, chain
from pdfminer.high_level import extract_text
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSEOF
from pikepdf import Pdf
from typing import (
    Any,
    Dict,
    List,
    NotRequired,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    Iterable,
    Literal,
    TypedDict,
    cast,
)
from urllib.parse import urlparse
from zipfile import BadZipFile
import ast
import datetime
import docassemble.base.functions
import docassemble.base.parse
import docassemble.base.pdftk
import formfyxer
import importlib
import json
import mako.runtime
import mako.template
import more_itertools
import os
import re
import tempfile
import uuid
import zipfile
import ipaddress
import socket
from dataclasses import dataclass
import pycountry
import yaml
from urllib.request import Request, urlopen

mako.runtime.UNDEFINED = DAEmpty()


TypeType = type(type(None))
_PROMPTS_CACHE: Optional[Dict[str, Any]] = None


@dataclass
class WeaverGenerationResult:
    yaml_text: str
    yaml_path: Optional[str] = None
    package_zip_path: Optional[str] = None


@dataclass
class WeaverInterviewArtifacts:
    yaml_text: str
    yaml_file: Any
    package_file: Optional[Any] = None


__all__ = [
    "attachment_download_html",
    "base_name",
    "create_package_zip",
    "DAField",
    "DAFieldGroup",
    "DAFieldList",
    "DAInterview",
    "DAQuestion",
    "DAQuestionList",
    "escape_double_quoted_yaml",
    "escape_quotes",
    "field_type_options",
    "fix_id",
    "generate_interview_from_path",
    "generate_interview_artifacts",
    "get_character_limit",
    "get_court_choices",
    "get_docx_validation_errors",
    "get_docx_variables",
    "get_fields",
    "get_help_document_text",
    "get_question_file_variables",
    "get_pdf_validation_errors",
    "get_pdf_variable_name_matches",
    "get_variable_name_warnings",
    "indent_by",
    "is_reserved_docx_label",
    "is_reserved_label",
    "is_url",
    "is_valid_python",
    "map_raw_to_final_display",
    "oneline",
    "ParsingException",
    "pdf_field_type_str",
    "reflect_fields",
    "remove_multiple_appearance_indicator",
    "to_yaml_file",
    "using_string",
    "varname",
    "logic_to_code_block",
    "WeaverGenerationResult",
    "WeaverInterviewArtifacts",
]

always_defined = set(
    [
        "dict",
        "False",
        "i",
        "list",
        "menu_items",
        "multi_user",
        "nav",
        "None",
        "PY2",
        "role_event",
        "role_needed",
        "role",
        "speak_text",
        "string_types",
        "track_location",
        "True",
        "url_args",
        "x",
    ]
)
replace_square_brackets = re.compile(r"\\\[ *([^\\]+)\\\]")
end_spaces = re.compile(r" +$")
spaces = re.compile(r"[ \n]+")
invalid_var_characters = re.compile(r"[^A-Za-z0-9_]+")
digit_start = re.compile(r"^[0-9]+")
newlines = re.compile(r"\n")
remove_u = re.compile(r"^u")


class ParsingException(Exception):
    """Throws an error if we can't understand the labels somehow, so we can tell the user"""

    def __init__(
        self, message: str, description: Optional[str] = None, url: Optional[str] = None
    ):
        self.main_issue = message
        self.description = description
        self.url = url

        super().__init__(
            "main_issue: {}, description: {}, url: {}".format(message, description, url)
        )

    def __reduce__(self):
        return (ParsingException, (self.main_issue, self.description, self.url))


def get_court_choices() -> List[str]:
    return generator_constants.COURT_CHOICES


def attachment_download_html(url, label) -> str:
    return '<a href="' + url + '" download="">' + label + "</a>"


def get_character_limit(pdf_field_tuple, char_width=6, row_height=12) -> Optional[int]:
    """
    Take the pdf_field_tuple and estimate the number of characters that can fit
    in the field, based on the x/y bounding box.

    0: horizontal start
    1: vertical start
    2: horizontal end
    3: vertical end
    """
    # Make sure it's the right kind of tuple
    if (
        len(pdf_field_tuple) < 4
        or not pdf_field_tuple[3]
        or len(pdf_field_tuple[3]) < 4
    ):
        return None  # we can't really guess

    # Did a little testing for typical field width/number of chars with both w and e.
    # 176 = 25-34 chars. from w to e
    # 121 = 17-22
    # Average about 6 pixels width per character
    # about 12 pixels high is one row

    length = pdf_field_tuple[3][2] - pdf_field_tuple[3][0]
    height = pdf_field_tuple[3][3] - pdf_field_tuple[3][1]
    num_rows = int(height / row_height) if height > 12 else 1
    num_cols = int(length / char_width)

    max_chars = num_rows * num_cols
    return max_chars


def varname(var_name: str) -> str:
    if var_name:
        var_name = var_name.strip()
        var_name = spaces.sub(r"_", var_name)
        var_name = invalid_var_characters.sub(r"", var_name)
        var_name = digit_start.sub(r"", var_name)
        return var_name
    return var_name


def logic_to_code_block(items: List[Union[Dict, str]], indent_level=0) -> str:
    """Converts a list of logic items to a code block with the given indentation level

    Args:
        items (list): A list of logic items, of the form ['var0', {'condition': '...', 'children': ['var1']}, 'var2', 'var3', ...]
        indent_level (int, optional): The indentation level to use. Defaults to 0. Used for recursion.

    Returns:
        str: The code block, as a string
    """
    code_lines = []
    indent = "  " * indent_level  # Define the indentation (e.g., 2 spaces per level)
    for item in items:
        if isinstance(item, str):  # If the item is a string, it's a variable
            code_lines.append(f"{indent}{item}")
        elif isinstance(item, dict):  # If the item is a dictionary, it's a condition
            # Add the condition line with the current indentation
            condition_line = item["condition"]
            if not condition_line.startswith("if "):
                condition_line = (
                    "if " + condition_line
                )  # Add 'if' if it's not already there
            if not condition_line.endswith(":"):
                condition_line += ":"
            code_lines.append(f"{indent}{condition_line}")

            # Recursively process the children with increased indentation
            children_code = logic_to_code_block(item["children"], indent_level + 1)
            code_lines.append(children_code)

    return "\n".join(code_lines)


def _load_llms_module():
    """Load ALToolbox llms lazily so Weaver still works without it."""
    try:
        from docassemble.ALToolbox import llms

        return llms
    except Exception as exc:
        log(f"Unable to load docassemble.ALToolbox.llms: {exc!r}")
        return None


def _safe_short_label(label: str, max_length: int = 45) -> str:
    cleaned = re.sub(r"\s+", " ", str(label or "")).strip(" .:-")
    if not cleaned:
        return ""
    return cleaned[:max_length].strip()


def _load_prompts_config() -> Dict[str, Any]:
    global _PROMPTS_CACHE
    if _PROMPTS_CACHE is not None:
        return _PROMPTS_CACHE
    path, _ = path_and_mimetype("data/sources/prompts.yml")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
            if isinstance(loaded, dict):
                _PROMPTS_CACHE = loaded
            else:
                _PROMPTS_CACHE = {}
    except Exception as exc:
        log(f"Unable to load Weaver prompts from {path}: {exc!r}")
        _PROMPTS_CACHE = {}
    return _PROMPTS_CACHE


def _prompt_str(key: str, default: str) -> str:
    value = _load_prompts_config().get(key, default)
    return value if isinstance(value, str) else default


def _prompt_dict(key: str, default: Dict[str, str]) -> Dict[str, str]:
    value = _load_prompts_config().get(key, default)
    return value if isinstance(value, dict) else default


def _extract_help_page_text(url: str, max_chars: int = 12000) -> str:
    if not url or not is_url(url):
        return ""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = parsed.hostname
    if not host:
        return ""

    def _is_private_or_local(hostname: str) -> bool:
        try:
            ip_obj = ipaddress.ip_address(hostname)
            return (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            )
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(hostname, None)
        except Exception:
            return True
        for info in infos:
            address = info[4][0]
            try:
                ip_obj = ipaddress.ip_address(address)
            except ValueError:
                return True
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                return True
        return False

    if _is_private_or_local(host):
        log(f"Blocked unsafe help_page_url host={host!r}")
        return ""

    try:
        req = Request(
            url,
            headers={"User-Agent": "ALWeaver/1.0 (+docassemble)"},
        )
        # url checked for SSRF above, so marking as audited for bandit
        with urlopen(req, timeout=10) as response:  # nosec B310
            content_type = str(response.headers.get("Content-Type", "") or "").lower()
            if content_type and (
                "text/html" not in content_type
                and "application/xhtml+xml" not in content_type
            ):
                log(
                    f"Skipped help_page_url={url!r} because content-type is {content_type!r}"
                )
                return ""
            max_bytes = 2_000_000
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raw = raw[:max_bytes]
            html_text = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        log(f"Unable to fetch help_page_url={url!r}: {exc!r}")
        return ""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(
            ["script", "style", "noscript", "svg", "canvas", "nav", "footer"]
        ):
            tag.decompose()
        text = soup.get_text("\n")
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
        return cleaned[:max_chars]
    except ImportError:
        log("Unable to parse help page HTML: beautifulsoup4 is not installed")
        return ""
    except Exception as exc:
        log(f"Unable to parse help page HTML for {url!r}: {exc!r}")
        return ""


def _normalize_field_type(value: str) -> Optional[str]:
    if not value:
        return None
    normalized = str(value).strip().lower()
    aliases = {
        "radio": "multiple choice radio",
        "checkbox": "yesno",
        "checkboxes": "multiple choice checkboxes",
        "dropdown": "multiple choice dropdown",
        "combobox": "multiple choice combobox",
        "multichoice": "multiple choice radio",
        "multiple_choice_radio": "multiple choice radio",
        "multiple_choice_checkboxes": "multiple choice checkboxes",
        "multiple_choice_dropdown": "multiple choice dropdown",
        "multiple_choice_combobox": "multiple choice combobox",
    }
    candidate = aliases.get(normalized, normalized)
    allowed = {
        option_key
        for option in field_type_options()
        for option_key in option.keys()
        if option_key not in {"skip this field", "code"}
    }
    return candidate if candidate in allowed else None


def _field_updates_from_llm_response(
    response: Dict[str, Any], custom_fields: List["DAField"]
) -> Dict[str, Dict[str, str]]:
    updates: Dict[str, Dict[str, str]] = {}
    by_variable = {field.variable: field for field in custom_fields}
    for variable, llm_value in response.items():
        if variable not in by_variable:
            continue
        if isinstance(llm_value, dict):
            new_label = llm_value.get("label", "")
            new_datatype = llm_value.get("datatype", "")
        else:
            new_label = llm_value
            new_datatype = ""
        cleaned = _safe_short_label(str(new_label), 45)
        normalized_datatype = _normalize_field_type(str(new_datatype))
        if not cleaned and not normalized_datatype:
            continue
        updates[variable] = {}
        if cleaned:
            updates[variable]["label"] = cleaned
        if normalized_datatype:
            updates[variable]["datatype"] = normalized_datatype
    return updates


class DAFieldGroup(Enum):
    RESERVED = "reserved"
    BUILT_IN = "built in"
    SIGNATURE = "signature"
    CUSTOM = "custom"


def field_type_options() -> List[Dict[str, str]]:
    return [
        {"text": "Text"},
        {"area": "Area"},
        {"yesno": "Yes/no checkbox"},
        {"noyes": "No/yes checkbox"},
        {"yesnoradio": "Yes/no radio"},
        {"noyesradio": "No/yes radio"},
        {"integer": "Whole number"},
        {"number": "Number"},
        {"currency": "Currency"},
        {"date": "Date"},
        {"email": "Email"},
        {"multiple choice dropdown": "Drop-down"},
        {"multiple choice combobox": "Combobox"},
        {"multiple choice radio": "Radio buttons"},
        {"multiple choice checkboxes": "Checkboxes"},
        {"multiselect": "Multi-select"},
        {"file": "Uploaded file"},
        {"code": "Python code"},
        {"skip this field": "[Skip this field]"},
    ]


class DAField(DAObject):
    """A field represents a Docassemble field/variable. I.e., a single piece of input we are gathering from the user.
    Has several important attributes that need to be set:
    * `raw_field_names`: list of field names directly from the PDF or the template text directly from the DOCX.
      In the case of PDFs, there could be multiple, i.e. `child__0` and `child__1`
    * `variable`: the field name that has been turned into a valid identifier, spaces to `_` and stripped of
      non identifier characters
    * `final_display_var`: the docassemble python code that computes exactly what the author wants in their PDF

    In many of the methods, you'll also find two other common versions of the field, computed on the fly:
    * `trigger_gather`: returns the statement that causes docassemble to correctly ask the question for this variable,
       e.g. `users.gather()` to get the `user.name.first`
    * `settable_var`: the settable / assignable data backing `final_display_var`, e.g. `address.address` for `address.block()`
    * `full_visual`: shows the full version of the backing data in a readable way, i.e. `address.block()` for `address.zip`
      TODO(brycew): not fully implemented yet
    """

    def init(self, **kwargs):
        return super().init(**kwargs)

    @property
    def complete(self) -> bool:
        self.variable
        self.label
        if not hasattr(self, "group"):
            self.group = DAFieldGroup.CUSTOM
        return True

    def fill_in_docx_attributes(
        self,
        new_field_name: str,
        reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
    ):
        """The DAField class expects a few attributes to be filled in.
        In a future version of this, maybe we can use context to identify
        true/false variables. For now, we can only use the name.
        We have a lot less info than for PDF fields.
        """
        self.raw_field_names: List[str] = [new_field_name]
        # For docx, we can't change the field name from the document itself, has to be the same
        self.variable: str = new_field_name
        self.final_display_var: str = new_field_name
        self.has_label: bool = True

        # variable_name_guess is the placeholder label for the field
        variable_name_guess = self.variable.replace("_", " ").capitalize()
        self.variable_name_guess = variable_name_guess

        if self.variable.endswith("_date"):
            self.field_type_guess = "date"
            self.variable_name_guess = f"Date of {variable_name_guess[:-5]}"
        elif self.variable.endswith("_amount"):
            self.field_type_guess = "currency"
        elif self.variable.endswith("_value"):
            self.field_type_guess = "currency"
        elif self.variable.endswith(".signature"):
            self.field_type_guess = "signature"
        else:
            self.field_type_guess = "text"

    def fill_in_pdf_attributes(
        self, pdf_field_tuple: Any, custom_plurals: Dict[str, str]
    ) -> None:
        """Let's guess the type of each field from the name / info from PDF"""
        if not custom_plurals:
            custom_plurals = {}
        # The raw name of the field from the PDF: must go in attachment block
        self.raw_field_names = [pdf_field_tuple[0]]
        # turns field_name into a valid python identifier: must be one per field
        self.variable = remove_multiple_appearance_indicator(
            varname(self.raw_field_names[0])
        )
        # the variable, in python: i.e., users[1].name.first
        self.final_display_var = map_raw_to_final_display(
            self.variable, custom_people_plurals_map=custom_plurals
        )

        variable_name_guess = self.variable.replace("_", " ").capitalize()
        self.has_label = True
        self.maxlength = get_character_limit(pdf_field_tuple)
        self.variable_name_guess = variable_name_guess

        self.export_value = pdf_field_tuple[5] if len(pdf_field_tuple) >= 6 else ""
        if self.variable.endswith("_date"):
            self.field_type_guess = "date"
            self.variable_name_guess = "Date of " + self.variable[:-5].replace("_", " ")
        elif self.variable.endswith("_yes") or self.variable.endswith("_no"):
            self.field_type_guess = "yesno"
            name_no_suffix = (
                self.variable[:-3]
                if self.variable.endswith("_no")
                else self.variable[:-4]
            )
            self.variable_name_guess = name_no_suffix.replace("_", " ").capitalize()
        elif pdf_field_tuple[4] == "/Btn":
            if str(self.export_value.lower()) in [
                "yes",
                "true",
                "on",
                "no",
                "false",
                "off",
                "",
            ]:
                self.field_type_guess = "yesno"
            else:
                self.field_type_guess = "multiple choice radio"
                self.choice_options = [self.export_value]
        elif pdf_field_tuple[4] == "/Sig":
            self.field_type_guess = "signature"
        elif self.maxlength and self.maxlength > 100:
            self.field_type_guess = "area"
        elif self.variable.endswith("_amount"):
            self.field_type_guess = "currency"
        elif self.variable.endswith("_value"):
            self.field_type_guess = "currency"
        else:
            self.field_type_guess = "text"

        if pdf_field_tuple[4] not in ["/Sig", "/Btn", "/Tx"]:
            self.field_type_unhandled = True

    def mark_as_paired_yesno(self, paired_field_names: List[str]):
        """Marks this field as actually representing multiple template fields:
        some with `variable_name`_yes and some with `variable_name`_no
        """
        self.paired_yesno = True
        if self.variable.endswith("_no"):
            self.raw_field_names = paired_field_names + self.raw_field_names
            self.variable = self.variable[:-3]
            self.final_display_var = self.final_display_var[:-3]
        elif self.variable.endswith("_yes"):
            self.raw_field_names = self.raw_field_names + paired_field_names
            self.variable = self.variable[:-4]
            self.final_display_var = self.final_display_var[:-4]

    def mark_with_duplicate(self, duplicate_field_names: List[str]):
        """Marks this field as actually representing multiple template fields, and
        hanging on to the original names of all of the duplicates
        """
        self.raw_field_names += duplicate_field_names

    def get_single_field_screen(self) -> str:
        settable_version = self.get_settable_var()
        if self.field_type == "yesno":
            return "yesno: {}".format(settable_version)
        elif self.field_type == "yesnomaybe":
            return "yesnomaybe: {}".format(settable_version)
        else:
            return ""

    def need_maxlength(self) -> bool:
        if hasattr(self, "field_type") and self.field_type not in [
            "email",
            "area",
            "text",
        ]:
            return False
        return (
            hasattr(self, "maxlength")
            and bool(self.maxlength)
            and not (hasattr(self, "send_to_addendum") and self.send_to_addendum)
        )

    def _maxlength_str(self) -> str:
        if (
            hasattr(self, "maxlength")
            and self.maxlength
            and not (hasattr(self, "send_to_addendum") and self.send_to_addendum)
        ):
            return "    maxlength: {}".format(self.maxlength)
        else:
            return ""

    def user_ask_about_field(self):
        field_questions = []
        settable_var = self.get_settable_var()
        if hasattr(self, "paired_yesno") and self.paired_yesno:
            field_title = (
                f"{ self.final_display_var } (will be expanded to include _yes and _no)"
            )
        elif len(self.raw_field_names) > 1:
            field_title = f"{ settable_var } (will be expanded to all instances)"
        elif self.raw_field_names[0] != settable_var:
            field_title = (
                f"{ settable_var } (will be renamed to { self.raw_field_names[0] })"
            )
        else:
            field_title = self.final_display_var

        field_questions.append({"note": f"""
                                <h2 class="h5 prompt-heading">{self.final_display_var}</h2>
                                """})
        field_questions.append(
            {
                "label": f"Prompt",
                # "label above field": True,
                "field": self.attr_name("label"),
                "default": self.variable_name_guess,
                "label above field": True,
                "grid": 6,
                "js hide if": f"val('{ self.attr_name('field_type') }') === 'skip this field' || val('{ self.attr_name('field_type') }') === 'code'",
            }
        )
        field_questions.append(
            {
                "label": "Type",
                # "label above field": True,
                "field": self.attr_name("field_type"),
                "label above field": True,
                "grid": 3,
                "code": "field_type_options()",
                "default": (
                    self.field_type_guess if hasattr(self, "field_type_guess") else None
                ),
            }
        )
        field_questions.append(
            {
                "label": "Optional",
                "field": self.attr_name("is_optional"),
                "datatype": "yesnowide",
                "label above field": True,
                "grid": 3,
                "help": "Check the box if this field is not required",
                "js hide if": f"val('{ self.attr_name('field_type') }') === 'skip this field' || val('{ self.attr_name('field_type') }') === 'code'",
            }
        )
        field_questions.append(
            {
                "label": f"Complete the expression, `{self.final_display_var} = `",
                "field": self.attr_name("code"),
                "show if": {"variable": self.attr_name("field_type"), "is": "code"},
                "help": f"Enter a valid Python expression, such as `'Hello World'` or `users[0].birthdate.plus(days=10)`. This will create a code block like `{self.final_display_var} = expression`",
            }
        )
        field_questions.append(
            {
                "label": "Options (one per line)",
                "field": self.attr_name("choices"),
                "datatype": "area",
                "js show if": f"['multiple choice dropdown','multiple choice combobox','multiselect', 'multiple choice radio', 'multiple choice checkboxes'].includes(val('{ self.attr_name('field_type') }'))",
                "default": (
                    "\n".join(
                        [
                            f"{opt.capitalize().replace('_', ' ')}: {opt}"
                            for opt in self.choice_options
                        ]
                    )
                    if hasattr(self, "choice_options")
                    else None
                ),
                "help": "Like `Descriptive name: key_name`, or just `Descriptive name`",
                "hint": "Descriptive name: key_name",
            }
        )
        if hasattr(self, "maxlength"):
            field_questions.append(
                {
                    "label": "Send overflow text to addendum",
                    "field": self.attr_name("send_to_addendum"),
                    "datatype": "yesno",
                    "js show if": f"val('{ self.attr_name('field_type') }') === 'area' ",
                    "help": "Check the box to send text that doesn't fit in the PDF to an additional page, instead of limiting the input length.",
                }
            )
        return field_questions

    def trigger_gather(
        self,
        custom_plurals: Optional[Iterable[str]] = None,
        reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
        undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
        reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
    ):
        """Turn the docassemble variable string into an expression
        that makes DA ask a question for it. This is mostly
        calling `gather()` for lists

        Args:
          custom_plurals: a list of variables strs that users have marked as being lists of people
        """

        GATHER_CALL = ".gather()"
        # HACK LITCon 2023 TODO
        # preferred_name and previous_names won't work w/ current structure of generator_constants
        if self.final_display_var.endswith(".preferred_name"):
            return self.final_display_var + ".first"
        if self.final_display_var.endswith(".preferred_name.first"):
            return self.final_display_var
        if self.final_display_var.endswith("previous_names"):
            return self.final_display_var + GATHER_CALL
        if re.search(r"previous_names\[\d\]$", self.final_display_var):
            return self.final_display_var[: -len("[0]")] + GATHER_CALL
        # NOTE: this only works through previous_names[9]

        if not custom_plurals:
            custom_plurals = []
        if self.final_display_var in reserved_whole_words:
            return self.final_display_var

        if (
            self.final_display_var in reserved_pluralizers_map.values()
            or self.final_display_var in custom_plurals
        ):
            return self.final_display_var + GATHER_CALL

        # Deal with more complex matches to prefixes
        # Everything before the first period and everything from the first period to the end
        var_with_attribute = self.get_settable_var()
        var_parts = re.findall(r"([^.]+)(\.[^.]*)?", var_with_attribute)

        # test for existence (empty strings result in a tuple)
        if not var_parts:
            return self.final_display_var
        # The prefix, ensuring no key or index
        prefix = re.sub(r"\[.+\]", "", var_parts[0][0])
        has_plural_prefix = (
            prefix in reserved_pluralizers_map.values() or prefix in custom_plurals
        )
        has_singular_prefix = prefix in undefined_person_prefixes

        if has_plural_prefix or has_singular_prefix:
            first_attribute = var_parts[0][1]
            if has_plural_prefix and (
                # HACK LITCon 2023 - hardcode previous_names list
                first_attribute == ""
                or first_attribute == ".name"
                or first_attribute
                in [
                    ".previous_names[0]",
                    ".previous_names[1]",
                    ".previous_names[2]",
                    ".previous_names[3]",
                    ".previous_names[4]",
                ]
            ):
                return prefix + GATHER_CALL
            elif first_attribute == ".address" or first_attribute == ".mailing_address":
                return var_parts[0][0] + first_attribute + ".address"
            else:
                return var_parts[0][0] + first_attribute
        else:
            return self.final_display_var

    def get_settable_var(
        self,
        display_to_settable_suffix=generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX,
    ):
        return substitute_suffix(self.final_display_var, display_to_settable_suffix)

    def _get_attributes(
        self,
        full_display_map=generator_constants.FULL_DISPLAY,
        primitive_pluralizer=generator_constants.RESERVED_PRIMITIVE_PLURALIZERS_MAP,
    ):
        """Returns attributes of this DAField, notably without the leading "prefix", or object name
        * the plain attribute, not ParentCollection, but the direct attribute of the ParentCollection
        * the "full display", an expression that shows the whole attribute in human readable form
        * an expression that causes DA to set to this field

        For example: the DAField `user[0].address.zip` would return ('address', 'address.block()', 'address.address')
        """
        label_parts = re.findall(r"([^.]*)(\..*)*", self.get_settable_var())

        prefix_with_index = label_parts[0][0]
        prefix = re.sub(r"\[.+\]", "", prefix_with_index)
        settable_attribute = label_parts[0][1].lstrip(".")
        if prefix in primitive_pluralizer.keys():
            # It's just a primitive (either by itself or in a list). I.e. docket_numbers
            settable_attribute = ""
            plain_att = ""
            full_display_att = ""
        else:
            if settable_attribute == "" or settable_attribute == "name":
                settable_attribute = "name.first"
            if (
                settable_attribute == "address"
                or settable_attribute == "mailing_address"
            ):
                settable_attribute += ".address"
            plain_att = re.findall(r"([^.]*)(\..*)*", settable_attribute)[0][0]
            full_display_att = substitute_suffix(
                "." + plain_att, full_display_map
            ).lstrip(".")
        return (plain_att, full_display_att, settable_attribute)

    @staticmethod
    def _get_parent_variable(
        var_with_attribute: str,
        custom_plurals: Iterable[str],
        undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
        reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
    ) -> Tuple[str, str]:
        """Gets the parent object or list that holds the data that is in var_with_attribute, as well
        as what type the object is
        For example, `users[0].name` and `users[1].name.last` will both return `users`.
        """
        if not custom_plurals:
            custom_plurals = []
        var_parts = re.findall(r"([^.]+)(\.[^.]*)?", var_with_attribute)
        if not var_parts:
            return var_with_attribute, "not var"

        # Either indexed, or no need to be indexed
        indexed_var = var_parts[0][0]

        # The prefix, ensuring no key or index
        prefix = re.sub(r"\[.+\]", "", indexed_var)

        has_plural_prefix = (
            prefix in reserved_pluralizers_map.values() or prefix in custom_plurals
        )
        if has_plural_prefix:
            return prefix, "list"

        has_singular_prefix = prefix in undefined_person_prefixes
        if has_singular_prefix:
            return prefix, "object"
        return var_with_attribute, "primitive"

    def __str__(self) -> str:
        return self.variable

    def __repr__(self) -> str:
        return f"{self.variable} ({self.raw_field_names}, {self.final_display_var})"


class ParentCollection(object):
    """A ParentCollection is "highest" level of data structure containing some DAField.
    For example, the parent collection for `users[0].name.first` is `users`, since that is the list
    that contains the user object of the `name` attribute that we are referencing.

    Some other examples: `trial_court` is the parent of `trial_court.division`, and for primitive
    variables like `my_string`, the parent collection is just `my_string`.

    The parent collection is useful for review screens, where we want to group related fields
    """

    def __init__(
        self,
        var_name: str,
        var_type: str,
        fields: List[DAField],
        custom_plurals: Iterable[str],
    ):
        """Constructor:
        @param var_name: the name of this parent collection variable
        @param var_type: the type of this parent collection variable. Can be 'list', 'object', or 'primitive'
        @param fields: the DAFields that all share this parent collection variable
        """
        self.var_name = var_name
        self.fields = fields
        self.attribute_map = {}
        self.var_type = var_type
        self.custom_plurals = custom_plurals
        # this base var is more complex than a simple primitive type
        if self.var_type != "primitive":
            for field in self.fields:
                plain_att, disp_att, settable_att = field._get_attributes()
                if plain_att:
                    self.attribute_map[plain_att] = (disp_att, settable_att)

    def table_page(self) -> str:
        # TODO: migrate to Mako format
        if self.var_type != "list":
            return ""
        content = """table: {var_name}.table
rows: {var_name}
columns:
{all_columns}
edit:
{settable_list}
confirm: True
"""
        all_columns = ""
        settable_list = ""
        for att, disp_and_set in self.attribute_map.items():
            all_columns += "  - {0}: |\n".format(att.capitalize().replace("_", " "))
            all_columns += (
                '      row_item.{0} if defined("row_item.{1}") else ""\n'.format(
                    disp_and_set[0], disp_and_set[1]
                )
            )
            settable_list += "  - {}\n".format(disp_and_set[1])
        if len(self.attribute_map) == 0:
            all_columns += "  - Name: |\n"
            all_columns += "      row_item\n"
            settable_list += "  True\n"
        return content.format(
            var_name=self.var_name,
            all_columns=all_columns.rstrip("\n"),
            settable_list=settable_list.rstrip("\n"),
        )

    def full_display(self) -> str:
        settable_var = self.fields[0].get_settable_var()
        parent_var = DAField._get_parent_variable(
            settable_var, custom_plurals=self.custom_plurals
        )[0]
        # NOTE: we rely on the "stock" full_display map here
        return substitute_suffix(parent_var)


class DAFieldList(DAList):
    """A DAFieldList contains multiple DAFields."""

    def init(self, **kwargs):
        super().init(**kwargs)
        self.object_type = DAField
        self.auto_gather = False
        self.complete_attribute = "complete"
        self.initializeAttribute(
            "custom_people_plurals", DADict.using(auto_gather=False, gathered=True)
        )

    def __str__(self) -> str:
        return docassemble.base.functions.comma_and_list(
            map(lambda x: "`" + x.variable + "`", self.complete_elements())
        )

    def consolidate_yesnos(self) -> None:
        """Combines separate yes/no questions into a single variable, and writes back out to the yes
        and no variables"""
        yesno_map: Dict[str, Any] = defaultdict(list)
        mark_to_remove: List[int] = []
        for idx, field in enumerate(self.elements):
            if not field.variable.endswith("_yes") and not field.variable.endswith(
                "_no"
            ):
                continue

            if len(yesno_map[field.variable_name_guess]) == 1:
                yesno_map[field.variable_name_guess][0].mark_as_paired_yesno(
                    field.raw_field_names
                )
            yesno_map[field.variable_name_guess].append(field)

            if len(yesno_map[field.variable_name_guess]) > 1:
                mark_to_remove.append(idx)

        self.delitem(*mark_to_remove)
        self.there_are_any = len(self.elements) > 0

    def consolidate_radios(self) -> None:
        """Combines separate radio buttons into a single variable"""
        radio_map: Dict[str, Any] = defaultdict(list)
        mark_to_remove: List[int] = []
        for idx, field in enumerate(self.elements):
            if field.field_type_guess != "multiple choice radio":
                continue

            if len(radio_map[field.variable_name_guess]) > 0:
                radio_map[field.variable_name_guess][0].choice_options.append(
                    field.export_value
                )
            radio_map[field.variable_name_guess].append(field)

            if len(radio_map[field.variable_name_guess]) > 1:
                mark_to_remove.append(idx)

        self.delitem(*mark_to_remove)
        self.there_are_any = len(self.elements) > 0

    def consolidate_duplicate_fields(self, document_type: str = "pdf") -> None:
        """Removes all duplicate fields from a PDF (docx's are handled elsewhere) that really just
        represent a single variable, leaving one remaining field that writes all of the original vars
        """
        if document_type.lower() == "docx":
            return

        field_map: Dict[str, DAField] = {}
        mark_to_remove: List[int] = []
        for idx, field in enumerate(self.elements):
            if field.final_display_var in field_map.keys():
                field_map[field.final_display_var].mark_with_duplicate(
                    field.raw_field_names
                )
                mark_to_remove.append(idx)
            else:
                field_map[field.final_display_var] = field
        self.delitem(*mark_to_remove)
        self.there_are_any = len(self.elements) > 0

    def find_parent_collections(
        self, skip_skipped_and_code_fields: bool = True
    ) -> List[ParentCollection]:
        """Gets all of the individual ParentCollections from the DAFields in this list.

        Args:
            skip_skipped_and_code_fields: if True, skips fields that are marked as "skip this field" or "code",
                which are not fields that should be on the review screen
        """
        parent_coll_map = defaultdict(list)
        for field in [
            field
            for field in self.elements
            if not hasattr(field, "field_type")
            or (
                not skip_skipped_and_code_fields
                or not field.field_type in ["skip this field", "code"]
            )
        ]:
            parent_var_and_type = DAField._get_parent_variable(
                field.final_display_var,
                custom_plurals=self.custom_people_plurals.values(),
            )
            parent_coll_map[parent_var_and_type].append(field)

        return [
            ParentCollection(
                var_and_type[0],
                var_and_type[1],
                fields,
                self.custom_people_plurals.values(),
            )
            for var_and_type, fields in parent_coll_map.items()
        ]

    def add_fields_from_file(self, document: Union[DAFile, DAFileList]) -> None:
        """
        Given a DAFile or DAFileList, process the raw fields in each file and
        add to the current list. Deduplication happens after every field is
        added.
        """
        if isinstance(document, DAFileList):
            for document in document:
                self.add_fields_from_file(document)
            return None

        all_fields = get_fields(document)
        if document.filename.lower().endswith("pdf"):
            document_type = "pdf"
        elif document.filename.lower().endswith("docx"):
            document_type = "docx"
        else:
            raise Exception(
                f"{document.filename} doesn't appear to be a PDF or DOCX file. Check the filename extension."
            )

        if document_type == "pdf":
            # Use pikepdf to get more info about each field
            pike_fields: Dict = {}
            pike_obj = Pdf.open(document.path())
            if (
                hasattr(pike_obj.Root, "AcroForm")
                and pike_obj.Root.AcroForm.Fields
                and isinstance(pike_obj.Root.AcroForm.Fields, Iterable)
            ):
                for pike_info in pike_obj.Root.AcroForm.Fields:
                    pike_fields[str(pike_info.T)] = pike_info
            pike_obj.close()
            for pdf_field_tuple, pike_info in zip_longest(all_fields, pike_fields):
                pdf_field_name = pdf_field_tuple[0]
                if pdf_field_name in pike_fields:
                    pike_info = pike_fields[pdf_field_name]
                    # PDF fields have bit flags that set specific options. The 17th bit (or hex
                    # 10000) on Buttons says it's a "push button", that "does not retain a
                    # permanent value" (e.g. a "Print this PDF" button.) They generally aren't
                    # really fields, and don't play well with PDF editing tools. Just skip them.
                    if (
                        hasattr(pike_info, "FT")
                        and hasattr(pike_info, "Ff")
                        and pike_info.FT == "/Btn"
                        and bool(pike_info.Ff & 0x10000)
                    ):
                        continue

                new_field: DAField = self.appendObject()
                new_field.source_document_type = "pdf"

                # Built-in fields and signatures don't get custom questions written
                if is_reserved_label(pdf_field_name):
                    new_field.group = DAFieldGroup.BUILT_IN
                elif len(pdf_field_tuple) > 4 and pdf_field_tuple[4] == "/Sig":
                    new_field.group = DAFieldGroup.SIGNATURE
                else:
                    new_field.group = DAFieldGroup.CUSTOM

                # This function determines what type of variable
                # we're dealing with
                new_field.fill_in_pdf_attributes(
                    pdf_field_tuple, self.custom_people_plurals
                )
                if new_field.group == DAFieldGroup.BUILT_IN:
                    new_field.label = new_field.variable_name_guess
        else:
            # if this is a docx, fields are a list of strings, not a list of tuples
            for field in all_fields:
                new_field = self.appendObject()
                new_field.source_document_type = "docx"
                if matching_reserved_names({field}):
                    new_field.group = DAFieldGroup.RESERVED
                elif is_reserved_docx_label(field):
                    new_field.group = DAFieldGroup.BUILT_IN
                elif field.endswith(".signature"):
                    new_field.group = DAFieldGroup.SIGNATURE
                else:
                    new_field.group = DAFieldGroup.CUSTOM
                new_field.fill_in_docx_attributes(field)
                if new_field.group in [DAFieldGroup.BUILT_IN, DAFieldGroup.RESERVED]:
                    new_field.label = new_field.variable_name_guess

        self.consolidate_radios()
        self.consolidate_duplicate_fields(document_type)
        self.consolidate_yesnos()

    def ask_about_fields(self) -> List[dict]:
        """
        Return a list of Docassemble fields that ask the user to verify type and
        label each "custom" field in the field list
        """
        return [
            item
            for item in chain.from_iterable(
                [field.user_ask_about_field() for field in self.custom()]
            )
        ]

    def matching_pdf_fields_from_file(self, document: DAFile) -> List[str]:
        """
        Helper function for generating an attachment block in Docassemble YAML
        file.

        Provided a DAFile, will return either the intersection of fields that
        are contained in both the DAFile and the DAFieldList, or if the file is a
        DOCX, immediately returns an empty list.
        """
        matches: list = []
        if not document.mimetype == "application/pdf":
            return matches
        document_fields = get_fields(document)
        document_fields = [item[0] for item in document_fields]
        for field in self:
            if set(field.raw_field_names).intersection(document_fields):
                matches.append(field)
        return matches

    def get_person_candidates(
        self,
        undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
        people_suffixes=generator_constants.PEOPLE_SUFFIXES,
        people_suffixes_map=generator_constants.PEOPLE_SUFFIXES_MAP,
        reserved_person_pluralizers_map=generator_constants.RESERVED_PERSON_PLURALIZERS_MAP,
        reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
        custom_only=False,
    ) -> Set[str]:
        """
        Identify the field names that appear to represent people in the list of
        string fields pulled from docx/PDF. Exclude people we know
        are singular Persons (such as trial_court).
        """
        people_vars = reserved_person_pluralizers_map.values()
        people = set()
        if custom_only:
            suffixes_to_use = set(people_suffixes_map.keys()) - set(["_name"])
        else:
            suffixes_to_use = people_suffixes_map.keys()
        match_pdf_person_suffixes = r"(.+?)(?:(" + "$)|(".join(suffixes_to_use) + "$))"
        for field in self:
            # fields are currently tuples for PDF and strings for docx
            file_type = field.source_document_type
            if file_type == "pdf":
                # map_raw_to_final_display will only transform names that are built-in to the constants
                field_to_check = map_raw_to_final_display(
                    field.variable, custom_people_plurals_map=self.custom_people_plurals
                )
            else:
                field_to_check = field.variable
            # Exact match
            if field_to_check in people_vars:
                people.add(field_to_check)
            elif field_to_check in undefined_person_prefixes:
                pass  # Do not ask how many there will be about a singluar person
            elif file_type == "docx" and (
                "[" in field_to_check or "." in field_to_check
            ):
                # Check for a valid Python identifier before brackets or .
                match_with_brackets_or_attribute = r"([A-Za-z_]\w*)((\[.*)|(\..*))"
                matches = re.match(match_with_brackets_or_attribute, field_to_check)
                if matches:
                    if matches.groups()[0] in undefined_person_prefixes:
                        # Ignore singular objects like trial_court
                        pass
                    # Is the name before attribute/index a predetermined person?
                    elif matches.groups()[0] in people_vars:
                        people.add(matches.groups()[0])
                    # Maybe this is the singular version of a person's name?
                    elif matches.groups()[0] in reserved_person_pluralizers_map.keys():
                        people.add(reserved_person_pluralizers_map[matches.groups()[0]])
                    else:
                        # This will be reached only for a DOCX and we decided to make
                        # custom people all be plural. So we ALWAYS strip off the leading
                        # index, like [0].name.first
                        possible_suffix = re.sub(r"^\[\d+\]", "", matches.groups()[1])
                        # Look for suffixes normally associated with people like .name.first for a DOCX
                        if possible_suffix in people_suffixes:
                            people.add(matches.groups()[0])
            elif file_type == "pdf":
                # If it's a PDF name that wasn't transformed by map_raw_to_final_display, do one last check
                # regex to check for matching suffixes, and catch things like mailing_address_address
                # instead of just _address_address, if the longer one matches
                matches = re.match(match_pdf_person_suffixes, field_to_check)
                if matches:
                    if not matches.groups()[0] in undefined_person_prefixes:
                        # Skip pre-defined but singular objects since they are not "people" that
                        # need to turn into lists.
                        # currently this is only trial_court
                        # strip trailing numbers so we end up with just the people object, i.e. `users`
                        people.add(re.sub(r"\d+$", "", matches.groups()[0]))
        if custom_only:
            return people - set(reserved_pluralizers_map.values())
        else:
            return people - (set(reserved_pluralizers_map.values()) - set(people_vars))

    def mark_people_as_builtins(self, people_list: Iterable[str]) -> None:
        self.custom_people_plurals = {
            var_name: var_name for var_name in list(people_list)
        }
        """Scan the list of fields and see if any of them should be renamed
        or marked as built-ins given the list of new, custom prefixes."""
        for field in self:
            if field.source_document_type == "pdf":
                if is_reserved_label(field.variable, reserved_prefixes=people_list):
                    field.group = DAFieldGroup.BUILT_IN
                    field.label = field.variable_name_guess
                    # Try checking to see if the custom prefix + predefined suffixes
                    # result in a new variable name
                    new_potential_name = map_raw_to_final_display(
                        field.variable,
                        document_type=field.source_document_type,
                        reserved_prefixes=people_list,
                        custom_people_plurals_map=self.custom_people_plurals,
                    )
                    if new_potential_name != field.variable:
                        field.final_display_var = new_potential_name
            elif is_reserved_docx_label(
                field.variable, reserved_pluralizers_map=dict(enumerate(people_list))
            ):
                field.group = DAFieldGroup.BUILT_IN
                field.label = field.variable_name_guess

        # This treats all fields as PDF fields, which should be a reasonable
        # restriction on how people write DOCX variable names
        self.consolidate_duplicate_fields()

    def auto_mark_people_as_builtins(self):
        """
        Mark people as built-ins if they match heuristics, without asking. For
        use with "I'm feeling lucky" feature.
        """
        # Use stricter candidates to avoid false positives like generic `_name`
        # fields becoming list gathers (e.g., `County.gather()`).
        candidates = self.get_person_candidates(custom_only=True)
        candidates = {
            candidate
            for candidate in candidates
            if re.match(r"^[a-z][a-z0-9_]*$", candidate)
        }
        self.mark_people_as_builtins(candidates)

    def auto_label_fields(self):
        for field in self.elements:
            field.field_type = (
                field.field_type_guess if hasattr(field, "field_type_guess") else "text"
            )
            field.label = field.variable_name_guess

    def builtins(self):
        """Returns "built-in" fields, including ones the user indicated contain
        custom person-prefixes"""
        # Can't use .filter() because that would create new intrinsicNames
        return [
            item
            for item in self.elements
            if hasattr(item, "group") and item.group == DAFieldGroup.BUILT_IN
        ]

    def reserved(self):
        """Returns "reserved" fields that aren't supposed to ever be asked
        or triggered in the interview order block.
        """
        return [
            item
            for item in self.elements
            if hasattr(item, "group") and item.group == DAFieldGroup.RESERVED
        ]

    def built_in_signature_triggers(self) -> List[str]:
        return [
            field.trigger_gather(custom_plurals=self.custom_people_plurals.values())
            for field in self.builtins()
            if field.trigger_gather(
                custom_plurals=self.custom_people_plurals.values()
            ).endswith(".signature")
        ]

    def signatures(self) -> List[DAField]:
        """Returns all signature fields in list"""
        return [
            item
            for item in self.elements
            if hasattr(item, "group") and item.group == DAFieldGroup.SIGNATURE
        ]

    def custom_signatures(self) -> List[DAField]:
        """Returns signatures that aren't builtin and aren't a part of people.
        These signatures need new signature blocks in the resulting interview."""
        return [
            item
            for item in self.elements
            if (
                hasattr(item, "group")
                and item.group == DAFieldGroup.SIGNATURE
                and not item.trigger_gather(
                    custom_plurals=self.custom_people_plurals.values()
                ).endswith(".signature")
            )
        ]

    def custom(self) -> List[DAField]:
        """Returns the fields that can be assigned to screens and which will require
        custom labels"""
        return [
            item
            for item in self.elements
            if not hasattr(item, "group") or item.group == DAFieldGroup.CUSTOM
        ]

    def remove_incorrect_names(self) -> None:
        """
        If any fields have invalid variable names, remove them from the DAField list.
        """
        to_remove = [
            item for item in self.elements if bad_name_reason(item) is not None
        ]
        for val in to_remove:
            self.remove(val)

    def skip_fields(self) -> List[DAField]:
        return [
            item
            for item in self.elements
            if hasattr(item, "field_type") and item.field_type == "skip this field"
        ]

    def code_fields(self) -> List[DAField]:
        return [
            item
            for item in self.elements
            if hasattr(item, "field_type") and item.field_type == "code"
        ]

    def has_addendum_fields(self) -> bool:
        return any(
            field
            for field in self
            if hasattr(field, "send_to_addendum") and field.send_to_addendum
        )

    def addendum_fields(self) -> List[DAField]:
        return [
            field
            for field in self
            if hasattr(field, "send_to_addendum") and field.send_to_addendum
        ]

    def hook_after_gather(self):
        for field in self.elements:
            if not hasattr(field, "group"):
                field.group = DAFieldGroup.CUSTOM


class DAQuestion(DAObject):
    """
    A block in a Docassemble interview YAML file that represents a question screen
    """

    def init(self, *pargs, **kwargs):
        super().init(*pargs, **kwargs)
        self.initializeAttribute("field_list", DAFieldList)
        # Ensure list-collect bookkeeping variables always exist, even before
        # the question is complete or any fields are selected.
        self.field_list.gathered = False
        self.field_list.there_are_any = False
        self.field_list.there_is_another = False

    @property
    def complete(self) -> bool:
        self.question_text
        # see https://github.com/SuffolkLITLab/docassemble-ALWeaver/issues/783
        # We no longer expose this option to use a "continue button field" on a
        # regular question page. User can still manually add this in Playground.
        self.has_mandatory_field = True  # Means at least one question is required. If False, we add a continue button field
        if self.is_informational_screen:
            self.field_list.clear()
            self.field_list.gathered = True

        # Simplify the abstraction
        if not self.has_mandatory_field or self.is_informational_screen:
            # assigning continue button field name here is messy
            self.needs_continue_button_field = True
        else:
            self.needs_continue_button_field = False
        return True


class DAQuestionList(DAList):
    """This represents a list of DAQuestions."""

    def init(self, **kwargs):
        super().init(**kwargs)
        self.object_type = DAQuestion
        self.complete_attribute = "complete"

    def all_fields_used(self, all_fields: Optional[List] = None) -> set:
        """This method is used to help us iteratively build a list of fields that have already been assigned to a
        screen/question. It makes sure the fields aren't displayed to the Weaver user on multiple screens.
        It will also filter out fields that shouldn't appear on any screen based on the field_type if the optional
        parameter "all_fields" is provided.
        """
        fields = set()
        for question in self.elements:
            if hasattr(question, "field_list"):
                for field in question.field_list.elements:
                    if (
                        not hasattr(field, "group")
                        or field.group == DAFieldGroup.CUSTOM
                    ):
                        fields.add(field)
        if all_fields:
            fields.update(
                [
                    field
                    for field in all_fields
                    if field.field_type in ["code", "skip this field"]
                ]
            )
        return fields

    def interview_order_list(
        self,
        all_fields: DAFieldList,
        screens: Optional[List[Union["DAQuestion", "DAField"]]] = None,
        sections: Optional[List[str]] = None,
        set_progress=True,
    ) -> List[str]:
        """
        Creates a list of fields for use in creating an interview order block.
        Fairly opinionated/tied to current expectations of AssemblyLine.
        """
        if not screens:
            screens = list(self)

        logic_list = []

        total_num_screens = len(screens)

        # We'll have a progress step every 5 screens,
        # unless it's very short
        if total_num_screens > 20:
            screen_divisor = 5
        else:
            screen_divisor = 3

        total_steps = (
            round(total_num_screens / screen_divisor) + 2
        )  # signature screen adds two steps
        increment = int(100 / total_steps)
        progress = 0

        saved_answer_name_flag = False
        current_section: Optional[str] = None
        for index, question in enumerate(screens):
            if sections and index < len(sections):
                section_id = str(sections[index] or "").strip()
                if section_id and section_id != current_section:
                    logic_list.append(f'nav.set_section("{section_id}")')
                    current_section = section_id
            if set_progress and index and index % screen_divisor == 0:
                progress += increment
                logic_list.append(f"set_progress({int(progress)})")
            if (
                isinstance(question, DAQuestion)
                and question.type == "question"
                and (
                    question.needs_continue_button_field
                    or hasattr(question, "field_list")
                    and question.field_list
                )
            ):
                # TODO(bryce): make OOP: don't refer to question.type
                # Add the first field in every question to our logic tree
                # This can be customized to control the order of questions later
                if question.needs_continue_button_field:
                    logic_list.append(varname(question.question_text))
                else:
                    logic_list.append(
                        question.field_list[0].trigger_gather(
                            custom_plurals=all_fields.custom_people_plurals.values()
                        )
                    )
            else:
                # it's a built-in field OR a signature, not a question block
                trigger_gather = question.trigger_gather(
                    custom_plurals=all_fields.custom_people_plurals.values()
                )
                if not (
                    question in all_fields.builtins()
                    and trigger_gather.endswith(".signature")
                ):
                    logic_list.append(trigger_gather)
                    # set the saved answer name so it includes the user's name in saved
                    # answer list
                    # NOTE: this is redundant now that we have a custom interview list, but leaving for now
                    if (
                        trigger_gather == "users.gather()"
                        and not saved_answer_name_flag
                    ):
                        logic_list.append("set_parts(subtitle=str(users))")
                        saved_answer_name_flag = True

        unique_lines: List[str] = []
        seen_non_nav: Set[str] = set()
        for line in logic_list:
            if line.startswith('nav.set_section("'):
                unique_lines.append(line)
                continue
            if line in seen_non_nav:
                continue
            seen_non_nav.add(line)
            unique_lines.append(line)
        return unique_lines


class DADataType(Enum):
    TEXT = "text"
    AREA = "area"
    YESNO = "yesno"
    NOYES = "noyes"
    YESNORADIO = "yesnoradio"
    NOYESRADIO = "noyesradio"
    YESNOWIDE = "yesnowide"
    NOYESWIDE = "noyeswide"
    NUMBER = "number"
    INTEGER = "integer"
    CURRENCY = "currency"
    EMAIL = "email"
    DATE = "date"
    FILE = "file"
    RADIO = "radio"
    COMBOBOX = "combobox"
    CHECKBOXES = "checkboxes"


FieldTypeToken = Literal[
    "text",
    "area",
    "yesno",
    "noyes",
    "yesnoradio",
    "noyesradio",
    "yesnowide",
    "noyeswide",
    "number",
    "integer",
    "currency",
    "email",
    "date",
    "file",
    "radio",
    "combobox",
    "checkboxes",
    "dropdown",
    "multiple choice radio",
    "multiple choice checkboxes",
    "multiple choice dropdown",
    "multiple choice combobox",
    "code",
    "skip",
    "skip this field",
    "skip_this_field",
]

FieldTypeInput = Union[DADataType, FieldTypeToken]

Field = TypedDict(
    "Field",
    {
        "label": NotRequired[Optional[str]],
        "field": NotRequired[Optional[str]],
        "datatype": NotRequired[Optional[FieldTypeInput]],
        "field_type": NotRequired[Optional[FieldTypeInput]],
        "input_type": NotRequired[Optional[FieldTypeInput]],
        "input type": NotRequired[Optional[FieldTypeInput]],
        "default": NotRequired[Optional[Any]],
        "value": NotRequired[Optional[Any]],
        "code": NotRequired[Optional[Any]],
        "maxlength": NotRequired[Optional[int]],
        "choices": NotRequired[Optional[Sequence[str]]],
        "min": NotRequired[Optional[Union[int, float]]],
        "max": NotRequired[Optional[Union[int, float]]],
        "step": NotRequired[Optional[Union[int, float]]],
        "required": NotRequired[Optional[bool]],
    },
    total=False,
)

# Legacy shorthand shape: {"Label": "variable_name"}.
LabeledFieldMapping = Mapping[str, str]

FieldDefinition = Union[Field, LabeledFieldMapping]

Screen = TypedDict(
    "Screen",
    {
        "continue_button_field": NotRequired[Optional[str]],
        "continue button field": NotRequired[Optional[str]],
        "question": NotRequired[Optional[str]],
        "subquestion": NotRequired[Optional[str]],
        "fields": NotRequired[Optional[List[FieldDefinition]]],
    },
    total=False,
)


class DAInterview(DAObject):
    """
    This class is a container for the various questions and metadata
    associated with an interview.
    """

    def init(self, *pargs, **kwargs):
        super().init(*pargs, **kwargs)
        self.initializeAttribute("questions", DAQuestionList)
        self.initializeAttribute("all_fields", DAFieldList.using(auto_gather=False))

    def has_unassigned_fields(self) -> bool:
        return len(
            self.questions.all_fields_used(all_fields=self.all_fields.custom())
        ) < len(self.all_fields.custom())

    def draft_screen_order(self, instanceName: str = "screen_order") -> DAList:
        """
        Create a draft screen order. We ask for the user's name first, then
        for each question screen, then the "built-in" fields.

        If the field has a duplicate "trigger gather" we only include it once.
        """
        screen_order = DAList(instanceName, auto_gather=False)
        builtins = []
        unique_fields = set()
        has_user = False
        for field in self.all_fields.builtins():
            # Don't add the users[0].signature field to this list
            if field.final_display_var == "users[0].signature":
                continue
            if field.trigger_gather() == "users.gather()":
                has_user = True
                user_field = field
                unique_fields.add(field.trigger_gather())
            if not field.trigger_gather() in unique_fields:
                unique_fields.add(field.trigger_gather())
                builtins.append(field)
        if has_user:
            screen_order.append(user_field)

        for question in self.questions:
            screen_order.append(question)

        screen_order.extend(builtins)
        screen_order.extend(self.all_fields.signatures())
        screen_order.gathered = True
        return screen_order

    def package_info(self) -> Dict[str, Any]:
        assembly_line_dep = "docassemble.AssemblyLine"
        if not hasattr(self, "dependencies"):
            self.dependencies: List[str] = []
        if not self.dependencies:
            self.dependencies = [assembly_line_dep]
        elif assembly_line_dep not in self.dependencies:
            self.dependencies.append(assembly_line_dep)

        info: Dict[str, Union[str, List[str]]] = {}
        for field in [
            "interview_files",
            "template_files",
            "module_files",
            "static_files",
        ]:
            if field not in info:
                info[field] = list()
        info["dependencies"] = self.dependencies
        info["author_name"] = ""
        info["readme"] = ""
        info["description"] = self.title
        info["version"] = "1.0"
        info["license"] = "The MIT License"
        info["url"] = "https://courtformsonline.org"
        return info

    @property
    def package_title(self):
        return re.sub(r"\W|_", "", self.interview_label.title())

    def create_package(
        self,
        interview_mako_output: DAFileCollection,
        generate_download_screen: bool = True,
        output_file: Optional[DAFile] = None,
    ) -> DAFile:
        # 2. Build data for folders_and_files and package_info
        folders_and_files = {
            "questions": [interview_mako_output],
            "modules": [],
            "static": [],
            "sources": [],
        }

        if generate_download_screen:
            if self.include_next_steps:
                folders_and_files["templates"] = [
                    self.instructions
                ] + self.uploaded_templates
            else:
                folders_and_files["templates"] = self.uploaded_templates
        else:
            folders_and_files["templates"] = []

        package_info = self.package_info()

        if self.author and str(self.author).splitlines():
            # TODO(qs): is it worth ever adding email here?
            # It would conflict with listing multiple authors
            default_vals = {"author name and email": str(self.author).splitlines()[0]}
            package_info["author_name"] = default_vals["author name and email"]
        else:
            default_vals = {"author name and email": "author@example.com"}

        # 3. Generate the output package
        return create_package_zip(
            self.package_title,
            package_info,
            default_vals,
            folders_and_files,
            output_file,
        )

    def attachment_varnames(self) -> str:
        if len(self.uploaded_templates) == 1:
            return f"{self.interview_label }_attachment"
        else:
            return comma_list(
                [
                    varname(base_name(document.filename))
                    for document in self.uploaded_templates
                ]
            )

    def _initialize_basic_attributes(
        self,
        url: Optional[str] = None,
        input_file: Optional[Union[DAFileList, DAFile, DAStaticFile]] = None,
        title: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        categories: Optional[str] = None,
        default_country_code: str = "US",
    ):
        """
        Set basic, fast attributes. Use this on the main thread before deferring
        heavy field processing to the background.
        """
        try:
            if user_logged_in():
                self.author = f"{user_info().first_name} {user_info().last_name}"
            else:
                self.author = "Court Forms Online"
        except:
            self.author = "Court Forms Online"
        if url:
            self._set_template_from_url(url)
        elif input_file:
            self._set_template_from_file(input_file)

        # Title extraction - very fast, safe to do on main thread
        self.title = self._set_title(url=url, input_file=input_file)
        if title:
            self.title = title
        self.short_title = self.title
        self.description = self.title
        self.short_filename_with_spaces = self.title
        self.short_filename = space_to_underscore(
            varname(self.short_filename_with_spaces)
        )

        # Heuristics-based attributes - all fast, no file access
        if jurisdiction:
            try:
                if jurisdiction.upper() in {
                    subdivision.code.split("-")[1]
                    for subdivision in pycountry.subdivisions.get(country_code="US")
                }:
                    self.jurisdiction = "NAM-US-US+" + jurisdiction.upper()
                    self.state = jurisdiction.upper()
                else:
                    self.jurisdiction = jurisdiction
                    self.state = jurisdiction
            except:
                self.jurisdiction = jurisdiction
                self.state = jurisdiction
        if categories:
            nsmi_tmp = (
                categories[1:-1].replace("'", "").strip()
            )  # they aren't valid JSON right now
            categories_tmp = nsmi_tmp.split(",")
            self.categories = DADict(
                elements={cat.strip(): True for cat in categories_tmp},
                auto_gather=False,
                gathered=True,
            )
            self.categories["Other"] = False
        self.typical_role = self._guess_role(self.title)
        self.form_type = self._guess_posture(self.title)
        self.jurisdiction_choices = get_matching_deps("jurisdiction", jurisdiction)
        self.org_choices = get_matching_deps("organization", jurisdiction)
        self.getting_started = "Before you get started, you need to..."
        self.intro_prompt = self._guess_intro_prompt(self.title)
        self.court_related = not (self.form_type == "letter")
        self.landing_page_url = ""
        self.efiling_enabled = False
        self.integrated_efiling = False
        self.integrated_email_filing = False
        self.requires_notarization = False
        self.unlisted = False
        self.footer = ""
        self.when_you_are_finished = ""
        self.allowed_courts = DADict(auto_gather=False, gathered=True)
        self.default_country_code = default_country_code
        self.output_mako_choice = "Default configuration:standard AssemblyLine"

    def _load_and_label_fields(self) -> None:
        """Fast field extraction and labeling. Safe to run on the main thread."""
        self._auto_load_fields()
        self.all_fields.auto_label_fields()
        self.all_fields.auto_mark_people_as_builtins()

    def _process_fields_and_group(
        self,
        interview_logic: Optional[List[Union[Dict, str]]] = None,
        screens: Optional[List[Screen]] = None,
    ):
        """
        Full field processing including slow grouping step.
        """
        self._load_and_label_fields()
        if interview_logic:
            self.interview_logic = interview_logic
        if screens:
            if not interview_logic:
                # using typing.cast to explicitly indicate a list of strings is OK for the interview_logic
                self.interview_logic = cast(
                    List[Union[Dict, str]], get_question_file_variables(screens)
                )
            self.create_questions_from_screen_list(screens)
        else:
            self.auto_group_fields()

    def auto_assign_attributes(
        self,
        url: Optional[str] = None,
        input_file: Optional[Union[DAFileList, DAFile, DAStaticFile]] = None,
        title: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        categories: Optional[str] = None,
        default_country_code: str = "US",
        interview_logic: Optional[List[Union[Dict, str]]] = None,
        screens: Optional[List[Screen]] = None,
    ):
        """
        Automatically assign interview attributes based on the template
        assigned to the interview object.
        To assist with "I'm feeling lucky" button.

        Args:
            url (Optional[str]): URL to a template file
            input_file (Optional[Union[DAFileList, DAFile, DAStaticFile]]): A file
                object
            title (Optional[str]): Title of the interview
            jurisdiction (Optional[str]): Jurisdiction of the interview
            categories (Optional[str]): Categories of the interview
            default_country_code (str): Default country code for the interview. Defaults to "US".
            interview_logic (Optional[List[Union[Dict, str]]]): Interview logic, represented as a tree
            screens (Optional[List[Dict]]): Interview screens, represented in the same structure as Docassemble's dictionary for a question block
        """
        self._initialize_basic_attributes(
            url=url,
            input_file=input_file,
            title=title,
            jurisdiction=jurisdiction,
            categories=categories,
            default_country_code=default_country_code,
        )
        self._process_fields_and_group(interview_logic=interview_logic, screens=screens)

    def auto_assign_attributes_fast(
        self,
        url: Optional[str] = None,
        input_file: Optional[Union[DAFileList, DAFile, DAStaticFile]] = None,
        title: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        categories: Optional[str] = None,
        default_country_code: str = "US",
    ):
        """Like auto_assign_attributes but skips the slow formfyxer.cluster_screens()
        call. Use when LLM-based grouping will be done in a background task instead."""
        self._initialize_basic_attributes(
            url=url,
            input_file=input_file,
            title=title,
            jurisdiction=jurisdiction,
            categories=categories,
            default_country_code=default_country_code,
        )
        self._load_and_label_fields()

    def _llm_default_model(self) -> str:
        return (
            get_config("assembly line", {}).get("weaver llm model")
            or get_config("open ai", {}).get("model")
            or "gpt-4o-mini"
        )

    def _cached_template_context_text(self) -> str:
        template_fingerprints: List[Tuple[str, Optional[int], Optional[int]]] = []
        if hasattr(self, "uploaded_templates"):
            for template in self.uploaded_templates:
                path = ""
                mtime_ns: Optional[int] = None
                size: Optional[int] = None
                try:
                    path = str(template.path())
                    stat_result = os.stat(path)
                    mtime_ns = stat_result.st_mtime_ns
                    size = stat_result.st_size
                except Exception:
                    pass
                template_fingerprints.append((path, mtime_ns, size))

        cache_key = tuple(template_fingerprints)
        if getattr(
            self, "_llm_template_context_cache_key", None
        ) == cache_key and hasattr(self, "_llm_template_context_cache"):
            return str(getattr(self, "_llm_template_context_cache", "") or "")

        chunks: List[str] = []
        if hasattr(self, "uploaded_templates"):
            for template in self.uploaded_templates:
                extracted = ""
                try:
                    if template.filename.lower().endswith(".pdf"):
                        extracted = extract_text(template.path())
                    elif template.filename.lower().endswith(".docx"):
                        extracted = docx2python(template.path()).text
                except Exception as exc:
                    log(
                        f"Failed to extract text from {template.filename}: {exc!r}",
                        "warning",
                    )
                    extracted = ""
                if extracted:
                    chunks.append(extracted)
                else:
                    if hasattr(template, "filename"):
                        log(
                            f"No text extracted from {template.filename} (file may be empty or unreadable)",
                            "warning",
                        )

        combined = "\n\n".join(chunks).strip()
        self._llm_template_context_cache_key = cache_key
        self._llm_template_context_cache = combined
        return combined

    def _llm_context_text(
        self, max_chars: int = 18000, skip_reference_site: bool = True
    ) -> str:
        chunks: List[str] = []
        template_text = self._cached_template_context_text()
        if template_text:
            chunks.append(template_text)
        if hasattr(self, "help_source_text") and self.help_source_text:
            chunks.append(str(self.help_source_text))
        if (
            not skip_reference_site
            and hasattr(self, "help_page_url")
            and self.help_page_url
        ):
            if not hasattr(self, "help_page_text"):
                self.help_page_text = _extract_help_page_text(str(self.help_page_url))
            if self.help_page_text:
                chunks.append(str(self.help_page_text))
        elif hasattr(self, "help_page_text") and self.help_page_text:
            # Use cached help_page_text if available
            chunks.append(str(self.help_page_text))
        full_text = "\n\n".join(chunks).strip()
        if len(full_text) > max_chars:
            return full_text[:max_chars]
        return full_text

    def _prefetch_reference_site(self) -> None:
        """Fetch and cache the help page content. This should be called in background tasks."""
        if (
            hasattr(self, "help_page_url")
            and self.help_page_url
            and not hasattr(self, "help_page_text")
        ):
            self.help_page_text = _extract_help_page_text(str(self.help_page_url))

    def llm_prefill_metadata(self, apply: bool = True) -> bool:
        llms = _load_llms_module()
        if not llms:
            log("LLM prefill_metadata skipped: llms module not available", "warning")
            return False
        context_text = self._llm_context_text()
        if not context_text:
            log(
                "LLM prefill_metadata skipped: no document context text extracted",
                "warning",
            )
            return False

        log(
            f"LLM prefill_metadata starting with {len(context_text)} chars of context",
            "info",
        )

        try:
            form_type_choices = _prompt_dict(
                "form_type_choices",
                {
                    "starts_case": "Starts a new court case",
                    "existing_case": "Filed in or responding to an existing court case",
                    "appeal": "Part of an appeal of a court case",
                    "letter": "Letter/correspondence",
                    "other_form": "Administrative or non-court form",
                    "other": "Other or unknown",
                },
            )
            role_choices = _prompt_dict(
                "role_choices",
                {
                    "plaintiff": "Most likely user is starting the case/request",
                    "defendant": "Most likely user is responding to a case/request",
                    "unknown": "Cannot confidently determine role from available text",
                },
            )
            form_type = llms.classify_text(
                text=f"Title: {self.title}\n\n{context_text[:6000]}",
                choices=form_type_choices,
                default_response=getattr(self, "form_type", "other"),
                model=self._llm_default_model(),
            )
            role = llms.classify_text(
                text=f"Title: {self.title}\n\n{context_text[:6000]}",
                choices=role_choices,
                default_response=getattr(self, "typical_role", "unknown"),
                model=self._llm_default_model(),
            )

            prompt_template = _prompt_str(
                "metadata_system_prompt",
                """
Return a JSON object with keys:
- intro_prompt (short action phrase, <= 60 chars)
- description (1-2 plain-language sentences)
- can_I_use_this_form (2-4 lines, plain language)
- getting_started (markdown text with short "Before you get started" and "When you are finished" lists)
- when_you_are_finished (2-5 plain-language lines about what to do after finishing)
- landing_page_url (optional https URL for the form's public landing page; return empty string if unknown)
- next_steps_document_title (single word like motion/petition/letter/form)
- next_steps_document_concept (single word like request/motion/petition/application/appeal)
- next_steps_help_organization (optional organization name)
- next_steps_help_url (optional https URL; may match help/landing page)
- next_steps_what_happens_next (2-5 lines; should align with when_you_are_finished)
- next_steps_what_can_decision_maker_do (2-5 lines)
- next_steps_what_happens_if_i_win (2-5 lines)

Use this title: {{TITLE}}
Predicted form_type: {{FORM_TYPE}}
Predicted role: {{ROLE}}
""".strip(),
            )
            prompt = (
                prompt_template.replace("{{TITLE}}", str(self.title))
                .replace("{{FORM_TYPE}}", str(form_type))
                .replace("{{ROLE}}", str(role))
            )
            drafted = llms.chat_completion(
                system_message=prompt,
                user_message=context_text[:12000],
                json_mode=True,
                model=self._llm_default_model(),
            )
            if isinstance(drafted, dict):
                drafted_title = _safe_short_label(str(drafted.get("title", "")), 100)
                intro_prompt = _safe_short_label(
                    str(drafted.get("intro_prompt", "")), 60
                )
                drafted_description = str(drafted.get("description") or "").strip()
                drafted_can_use = str(drafted.get("can_I_use_this_form") or "").strip()
                drafted_getting_started = str(
                    drafted.get("getting_started") or ""
                ).strip()
                drafted_when_finished = str(
                    drafted.get("when_you_are_finished") or ""
                ).strip()

                log(
                    f"LLM metadata response received: title={bool(drafted_title)}, getting_started={bool(drafted_getting_started)}, when_finished={bool(drafted_when_finished)}",
                    "info",
                )
                drafted_landing_page_url = str(
                    drafted.get("landing_page_url") or ""
                ).strip()
                drafted_next_steps_document_title = str(
                    drafted.get("next_steps_document_title") or ""
                ).strip()
                drafted_next_steps_document_concept = str(
                    drafted.get("next_steps_document_concept") or ""
                ).strip()
                drafted_next_steps_help_organization = str(
                    drafted.get("next_steps_help_organization") or ""
                ).strip()
                drafted_next_steps_help_url = str(
                    drafted.get("next_steps_help_url") or ""
                ).strip()
                drafted_next_steps_what_happens_next = str(
                    drafted.get("next_steps_what_happens_next") or ""
                ).strip()
                drafted_next_steps_what_can_decision_maker_do = str(
                    drafted.get("next_steps_what_can_decision_maker_do") or ""
                ).strip()
                drafted_next_steps_what_happens_if_i_win = str(
                    drafted.get("next_steps_what_happens_if_i_win") or ""
                ).strip()
                if drafted_landing_page_url and not is_url(drafted_landing_page_url):
                    drafted_landing_page_url = ""
                if drafted_next_steps_help_url and not is_url(
                    drafted_next_steps_help_url
                ):
                    drafted_next_steps_help_url = ""

                # Keep this aligned: next-steps "what happens next" should mirror
                # "when you are finished" unless the model omitted one of them.
                if drafted_when_finished and not drafted_next_steps_what_happens_next:
                    drafted_next_steps_what_happens_next = drafted_when_finished
                elif drafted_next_steps_what_happens_next and not drafted_when_finished:
                    drafted_when_finished = drafted_next_steps_what_happens_next
                elif drafted_when_finished and drafted_next_steps_what_happens_next:
                    drafted_next_steps_what_happens_next = drafted_when_finished
                if apply:
                    if drafted_title:
                        self.title = drafted_title
                        self.short_title = drafted_title[:25]
                        self.short_filename_with_spaces = drafted_title
                        self.short_filename = space_to_underscore(
                            varname(drafted_title)
                        )
                    if intro_prompt:
                        self.intro_prompt = intro_prompt
                    if drafted_description:
                        self.description = drafted_description
                    if drafted_can_use:
                        self.can_I_use_this_form = drafted_can_use
                    if drafted_getting_started:
                        self.getting_started = drafted_getting_started
                    if drafted_when_finished:
                        self.when_you_are_finished = drafted_when_finished
                    if drafted_landing_page_url:
                        self.landing_page_url = drafted_landing_page_url
                    if drafted_next_steps_document_title:
                        self.next_steps_document_title = (
                            drafted_next_steps_document_title
                        )
                    if drafted_next_steps_document_concept:
                        self.next_steps_document_concept = (
                            drafted_next_steps_document_concept
                        )
                    if drafted_next_steps_help_organization:
                        self.next_steps_help_organization = (
                            drafted_next_steps_help_organization
                        )
                    if drafted_next_steps_help_url:
                        self.next_steps_help_url = drafted_next_steps_help_url
                    if not hasattr(self, "custom_next_steps_instructions"):
                        self.custom_next_steps_instructions = {}
                    if drafted_next_steps_what_happens_next:
                        self.custom_next_steps_instructions["what_happens_next"] = (
                            drafted_next_steps_what_happens_next
                        )
                    if drafted_next_steps_what_can_decision_maker_do:
                        self.custom_next_steps_instructions[
                            "what_can_decision_maker_do"
                        ] = drafted_next_steps_what_can_decision_maker_do
                    if drafted_next_steps_what_happens_if_i_win:
                        self.custom_next_steps_instructions["what_happens_if_i_win"] = (
                            drafted_next_steps_what_happens_if_i_win
                        )
                else:
                    if drafted_title:
                        self.llm_draft_title = drafted_title
                    if intro_prompt:
                        self.llm_draft_intro_prompt = intro_prompt
                    if drafted_description:
                        self.llm_draft_description = drafted_description
                    if drafted_can_use:
                        self.llm_draft_can_i_use_this_form = drafted_can_use
                    if drafted_getting_started:
                        self.llm_draft_getting_started = drafted_getting_started
                    if drafted_when_finished:
                        self.llm_draft_when_you_are_finished = drafted_when_finished
                    if drafted_landing_page_url:
                        self.llm_draft_landing_page_url = drafted_landing_page_url
                    if drafted_next_steps_document_title:
                        self.llm_draft_next_steps_document_title = (
                            drafted_next_steps_document_title
                        )
                    if drafted_next_steps_document_concept:
                        self.llm_draft_next_steps_document_concept = (
                            drafted_next_steps_document_concept
                        )
                    if drafted_next_steps_help_organization:
                        self.llm_draft_next_steps_help_organization = (
                            drafted_next_steps_help_organization
                        )
                    if drafted_next_steps_help_url:
                        self.llm_draft_next_steps_help_url = drafted_next_steps_help_url
                    if drafted_next_steps_what_happens_next:
                        self.llm_draft_next_steps_what_happens_next = (
                            drafted_next_steps_what_happens_next
                        )
                    if drafted_next_steps_what_can_decision_maker_do:
                        self.llm_draft_next_steps_what_can_decision_maker_do = (
                            drafted_next_steps_what_can_decision_maker_do
                        )
                    if drafted_next_steps_what_happens_if_i_win:
                        self.llm_draft_next_steps_what_happens_if_i_win = (
                            drafted_next_steps_what_happens_if_i_win
                        )

            if form_type in {
                "starts_case",
                "existing_case",
                "appeal",
                "letter",
                "other_form",
                "other",
            }:
                if apply:
                    self.form_type = form_type
                    self.court_related = self.form_type in {
                        "starts_case",
                        "existing_case",
                        "appeal",
                    }
                else:
                    self.llm_draft_form_type = form_type
                    self.llm_draft_court_related = form_type in {
                        "starts_case",
                        "existing_case",
                        "appeal",
                    }
            if role in {"plaintiff", "defendant", "unknown"}:
                if apply:
                    self.typical_role = role
                else:
                    self.llm_draft_typical_role = role
            log("LLM metadata prefill completed successfully", "info")
            return True
        except Exception as exc:
            log(f"LLM metadata prefill failed: {exc!r}")
            return False

    def llm_predict_state(self, apply: bool = True) -> bool:
        llms = _load_llms_module()
        if not llms:
            return False
        context_text = self._llm_context_text(max_chars=8000)
        if not context_text:
            return False

        try:
            us_subdivisions = pycountry.subdivisions.get(country_code="US") or []
            choices = {
                subdivision.code.split("-")[1]: subdivision.name
                for subdivision in us_subdivisions
                if subdivision.code.startswith("US-")
            }
            if not choices:
                return False
            predicted_state = llms.classify_text(
                text=f"Title: {self.title}\nJurisdiction: {getattr(self, 'jurisdiction', '')}\n\n{context_text}",
                choices=choices,
                default_response=(getattr(self, "state", "") or "MA"),
                model=self._llm_default_model(),
            )
            predicted_state = str(predicted_state or "").strip().upper()
            if predicted_state not in choices:
                return False
            if apply:
                self.default_country_code = "US"
                self.state = predicted_state
                self.jurisdiction = "NAM-US-US+" + predicted_state
            else:
                self.llm_draft_default_country_code = "US"
                self.llm_draft_state = predicted_state
                self.llm_draft_jurisdiction = "NAM-US-US+" + predicted_state
            return True
        except Exception as exc:
            log(f"LLM state prediction failed: {exc!r}")
            return False

    def llm_refine_field_labels(
        self, apply: bool = True
    ) -> Union[int, Dict[str, Dict[str, str]]]:
        llms = _load_llms_module()
        if not llms:
            return 0

        custom_fields = [
            field
            for field in self.all_fields.custom()
            if not (
                hasattr(field, "field_type")
                and field.field_type in ["code", "skip this field"]
            )
        ]
        if not custom_fields:
            return 0

        context_text = self._llm_context_text(max_chars=12000)
        if not context_text:
            return 0

        try:
            field_payload = {
                field.variable: {
                    "current_label": (
                        field.label
                        if hasattr(field, "label")
                        else field.variable_name_guess
                    ),
                    "datatype": getattr(
                        field, "field_type", getattr(field, "field_type_guess", "text")
                    ),
                }
                for field in custom_fields
            }
            prompt = _prompt_str(
                "label_datatype_refinement_system_prompt",
                """
Rewrite each field label and suggest datatype.
Rules:
- keep legal meaning from context
- max 45 characters
- sentence fragment, not a sentence
- no variable names or underscores
- keep each key exactly the same
Return JSON object with shape:
{
  "field_variable": {
    "label": "Improved label",
    "datatype": "text"
  }
}
""".strip(),
            )
            response = llms.chat_completion(
                system_message=prompt,
                user_message="Context:\n"
                + context_text
                + "\n\nFields:\n"
                + json.dumps(field_payload),
                json_mode=True,
                model=self._llm_default_model(),
            )
            if not isinstance(response, dict):
                return {} if not apply else 0

            updates = _field_updates_from_llm_response(response, custom_fields)
            if not apply:
                return updates

            self.apply_llm_field_updates(updates)
            return len(updates)
        except Exception as exc:
            log(f"LLM field-label refinement failed: {exc!r}")
            return {} if not apply else 0

    def llm_group_fields(self, apply: bool = True) -> Union[bool, List[Screen]]:
        llms = _load_llms_module()
        if not llms:
            return False

        custom_fields = [
            field
            for field in self.all_fields.custom()
            if not (
                hasattr(field, "field_type")
                and field.field_type in ["code", "skip this field"]
            )
        ]
        if not custom_fields:
            return False

        try:
            context_text = self._llm_context_text(max_chars=10000)
            field_rows = [
                {
                    "field": field.variable,
                    "label": (
                        field.label
                        if hasattr(field, "label")
                        else field.variable_name_guess
                    ),
                }
                for field in custom_fields
            ]
            prompt = _prompt_str(
                "grouping_system_prompt",
                """
Group fields into interview screens.
Return JSON object with this key:
- screens: list of objects, each with:
  - question (short screen title)
  - subquestion (optional short helper text)
  - fields (list of field variable names)

Rules:
- Use each field at most once
- Prefer 2-8 fields per screen
- Keep related fields together
""".strip(),
            )
            response = llms.chat_completion(
                system_message=prompt,
                user_message="Context:\n"
                + context_text
                + "\n\nFields:\n"
                + json.dumps(field_rows),
                json_mode=True,
                model=self._llm_default_model(),
            )
            if not isinstance(response, dict) or not isinstance(
                response.get("screens"), list
            ):
                return [] if not apply else False

            by_variable = {field.variable: field for field in custom_fields}
            used: Set[str] = set()
            screen_list: List[Screen] = []
            for raw_screen in response.get("screens", []):
                if not isinstance(raw_screen, dict):
                    continue
                fields = raw_screen.get("fields")
                if not isinstance(fields, list):
                    continue
                field_defs: List[FieldDefinition] = []
                for variable in fields:
                    if (
                        not isinstance(variable, str)
                        or variable not in by_variable
                        or variable in used
                    ):
                        continue
                    used.add(variable)
                    field_obj = by_variable[variable]
                    field_defs.append(
                        {
                            "field": variable,
                            "label": (
                                field_obj.label
                                if hasattr(field_obj, "label")
                                else field_obj.variable_name_guess
                            ),
                            "datatype": getattr(
                                field_obj,
                                "field_type",
                                getattr(field_obj, "field_type_guess", "text"),
                            ),
                        }
                    )
                if field_defs:
                    screen_list.append(
                        {
                            "question": str(
                                raw_screen.get("question") or "More information"
                            ),
                            "subquestion": str(raw_screen.get("subquestion") or ""),
                            "fields": field_defs,
                        }
                    )

            for field in custom_fields:
                if field.variable in used:
                    continue
                screen_list.append(
                    {
                        "question": (
                            field.label
                            if hasattr(field, "label")
                            else field.variable_name_guess
                        ),
                        "subquestion": "",
                        "fields": [
                            {
                                "field": field.variable,
                                "label": (
                                    field.label
                                    if hasattr(field, "label")
                                    else field.variable_name_guess
                                ),
                                "datatype": getattr(
                                    field,
                                    "field_type",
                                    getattr(field, "field_type_guess", "text"),
                                ),
                            }
                        ],
                    }
                )

            if not screen_list:
                return [] if not apply else False
            if not apply:
                return screen_list
            if hasattr(self, "questions"):
                try:
                    self.questions.clear()
                except Exception:
                    self.initializeAttribute("questions", DAQuestionList)
            else:
                self.initializeAttribute("questions", DAQuestionList)
            self.questions.gathered = False
            self.create_questions_from_screen_list(screen_list)
            return True
        except Exception as exc:
            log(f"LLM screen grouping failed: {exc!r}")
            return [] if not apply else False

    def apply_llm_field_updates(
        self, field_updates: Mapping[str, Mapping[str, str]]
    ) -> int:
        if not field_updates:
            return 0
        by_variable = {field.variable: field for field in self.all_fields.custom()}
        updated = 0
        for variable, update in field_updates.items():
            if variable not in by_variable:
                continue
            field_obj = by_variable[variable]
            label = _safe_short_label(str(update.get("label", "")), 45)
            datatype = _normalize_field_type(str(update.get("datatype", "")))
            if label:
                field_obj.label = label
                field_obj.has_label = True
            if datatype:
                field_obj.field_type = datatype
            if label or datatype:
                updated += 1
        return updated

    def llm_generate_draft_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        # Fetch reference site content upfront in background task
        self._prefetch_reference_site()
        self.llm_prefill_metadata(apply=False)
        self.llm_predict_state(apply=False)
        for key in [
            "llm_draft_title",
            "llm_draft_intro_prompt",
            "llm_draft_description",
            "llm_draft_can_i_use_this_form",
            "llm_draft_getting_started",
            "llm_draft_when_you_are_finished",
            "llm_draft_landing_page_url",
            "llm_draft_next_steps_document_title",
            "llm_draft_next_steps_document_concept",
            "llm_draft_next_steps_help_organization",
            "llm_draft_next_steps_help_url",
            "llm_draft_next_steps_what_happens_next",
            "llm_draft_next_steps_what_can_decision_maker_do",
            "llm_draft_next_steps_what_happens_if_i_win",
            "llm_draft_form_type",
            "llm_draft_court_related",
            "llm_draft_typical_role",
            "llm_draft_default_country_code",
            "llm_draft_state",
            "llm_draft_jurisdiction",
        ]:
            if hasattr(self, key):
                payload[key] = getattr(self, key)

        field_updates = self.llm_refine_field_labels(apply=False)
        if not isinstance(field_updates, dict):
            field_updates = {}
        payload["field_updates"] = field_updates

        # Keep labels in grouped screen payload aligned with drafted updates.
        if field_updates:
            self.apply_llm_field_updates(field_updates)
        payload["screen_list"] = self.llm_group_fields(apply=False)
        return payload

    def apply_llm_draft_payload(self, payload: Mapping[str, Any]) -> None:
        if not payload:
            return
        for key in [
            "llm_draft_title",
            "llm_draft_intro_prompt",
            "llm_draft_description",
            "llm_draft_can_i_use_this_form",
            "llm_draft_getting_started",
            "llm_draft_when_you_are_finished",
            "llm_draft_landing_page_url",
            "llm_draft_next_steps_document_title",
            "llm_draft_next_steps_document_concept",
            "llm_draft_next_steps_help_organization",
            "llm_draft_next_steps_help_url",
            "llm_draft_next_steps_what_happens_next",
            "llm_draft_next_steps_what_can_decision_maker_do",
            "llm_draft_next_steps_what_happens_if_i_win",
            "llm_draft_form_type",
            "llm_draft_court_related",
            "llm_draft_typical_role",
            "llm_draft_default_country_code",
            "llm_draft_state",
            "llm_draft_jurisdiction",
        ]:
            if key in payload:
                setattr(self, key, payload[key])

        # Apply drafted next-steps values to live fields so lucky mode can use them
        # even when skipping the step-by-step customization screen.
        if hasattr(self, "llm_draft_next_steps_document_title"):
            self.next_steps_document_title = self.llm_draft_next_steps_document_title
        if hasattr(self, "llm_draft_next_steps_document_concept"):
            self.next_steps_document_concept = (
                self.llm_draft_next_steps_document_concept
            )
        if hasattr(self, "llm_draft_next_steps_help_organization"):
            self.next_steps_help_organization = (
                self.llm_draft_next_steps_help_organization
            )
        if hasattr(self, "llm_draft_next_steps_help_url"):
            self.next_steps_help_url = self.llm_draft_next_steps_help_url
        if not hasattr(self, "custom_next_steps_instructions"):
            self.custom_next_steps_instructions = {}
        if hasattr(self, "llm_draft_next_steps_what_happens_next"):
            self.custom_next_steps_instructions["what_happens_next"] = (
                self.llm_draft_next_steps_what_happens_next
            )
        if hasattr(self, "llm_draft_next_steps_what_can_decision_maker_do"):
            self.custom_next_steps_instructions["what_can_decision_maker_do"] = (
                self.llm_draft_next_steps_what_can_decision_maker_do
            )
        if hasattr(self, "llm_draft_next_steps_what_happens_if_i_win"):
            self.custom_next_steps_instructions["what_happens_if_i_win"] = (
                self.llm_draft_next_steps_what_happens_if_i_win
            )

        field_updates = payload.get("field_updates")
        if isinstance(field_updates, Mapping):
            self.apply_llm_field_updates(field_updates)

        screen_list = payload.get("screen_list")
        if isinstance(screen_list, list) and screen_list:
            if isinstance(field_updates, Mapping) and field_updates:
                refreshed_screens: List[Screen] = []
                for raw_screen in screen_list:
                    if not isinstance(raw_screen, Mapping):
                        continue
                    rewritten_screen = dict(raw_screen)
                    fields = rewritten_screen.get("fields")
                    if isinstance(fields, list):
                        refreshed_fields: List[FieldDefinition] = []
                        for raw_field in fields:
                            if not isinstance(raw_field, Mapping):
                                continue
                            rewritten_field = dict(raw_field)
                            variable = rewritten_field.get("field")
                            update = (
                                field_updates.get(variable)
                                if isinstance(variable, str)
                                else None
                            )
                            if isinstance(update, Mapping):
                                label = _safe_short_label(
                                    str(update.get("label", "")), 45
                                )
                                datatype = _normalize_field_type(
                                    str(update.get("datatype", ""))
                                )
                                if label:
                                    rewritten_field["label"] = label
                                if datatype:
                                    rewritten_field["datatype"] = datatype
                            refreshed_fields.append(
                                cast(FieldDefinition, rewritten_field)
                            )
                        rewritten_screen["fields"] = refreshed_fields
                    refreshed_screens.append(cast(Screen, rewritten_screen))
                screen_list = refreshed_screens
            if hasattr(self, "questions"):
                try:
                    self.questions.clear()
                except Exception:
                    self.initializeAttribute("questions", DAQuestionList)
            else:
                self.initializeAttribute("questions", DAQuestionList)
            self.questions.gathered = False
            self.create_questions_from_screen_list(cast(List[Screen], screen_list))

    def _set_title(self, url=None, input_file=None):
        if url:
            draft_title = url
        elif input_file:
            draft_title = input_file.path()
        else:
            draft_title = self.uploaded_templates[0].filename
        return (
            os.path.splitext(os.path.basename(draft_title))[0]
            .replace("_", " ")
            .capitalize()
        )

    def _set_template_from_url(self, url: str):
        self.uploaded_templates = DAFileList(
            self.attr_name("uploaded_templates"), auto_gather=False, gathered=True
        )
        self.uploaded_templates[0] = DAFile(
            self.attr_name("uploaded_templates") + "[0]"
        )
        self.uploaded_templates[0].initialize(extension="pdf")
        self.uploaded_templates[0].from_url(url)
        self.uploaded_templates[0].created = True

    def _set_template_from_file(
        self, input_file: Union[DAFileList, DAFile, DAStaticFile]
    ):
        if isinstance(input_file, DAFileList):
            self.uploaded_templates = input_file.copy_deep(
                self.attr_name("uploaded_templates")
            )
            return
        self.uploaded_templates = DAFileList(
            self.attr_name("uploaded_templates"), auto_gather=False, gathered=True
        )
        self.uploaded_templates[0] = input_file.copy_deep(
            self.attr_name("uploaded_templates") + "[0]"
        )

    def _guess_posture(self, title: str):
        """
        Guess posture of the case using simple heuristics.
        """
        title = title.lower()

        starts_case_keywords = [
            "petition",
            "complaint",
            "initiation",
            "application",
            "claim",
            "suit",
            "filing",
        ]
        existing_case_keywords = [
            "motion",
            "response",
            "reply",
            "answer",
            "counterclaim",
            "rejoinder",
            "objection",
            "brief",
            "memorandum",
            "declaration",
            "affidavit",
        ]
        appeal_keywords = ["appeal", "appellate", "review", "reversal", "circuit"]
        letter_keywords = ["letter", "correspondence", "notice", "communication"]
        other_form_keywords = ["form", "certificate", "record"]

        if any(keyword in title for keyword in starts_case_keywords):
            return "starts_case"
        if any(keyword in title for keyword in existing_case_keywords):
            return "existing_case"
        if any(keyword in title for keyword in appeal_keywords):
            return "appeal"
        if any(keyword in title for keyword in letter_keywords):
            return "letter"
        if any(keyword in title for keyword in other_form_keywords):
            return "other_form"

        return "other"

    def _guess_intro_prompt(self, title: str):
        """Create a reasonable opening prompt for the form based on its title

        Args:
            title (str): The title of the form
        """

        if self.form_type == "starts_case":
            return "Ask the court for a " + title
        elif self.form_type == "existing_case":
            return "File a " + title
        elif self.form_type == "letter":
            return "Write a " + title
        return "Get a " + title

    def _guess_role(self, title: str):
        """Guess role from the form's title, using some simple heuristics.

        Args:
            title (str): The title of the form
        """
        title = title.lower()

        defendant_keywords = [
            "answer",
            "defendant",
            "respondent",
            "rebuttal",
            "counterclaim",
            "objection",
        ]
        plaintiff_keywords = [
            "complaint",
            "petition",
            "plaintiff",
            "probate",
            "guardian",
            "application",
            "appeal",
            "claim",
            "suit",
            "action",
        ]

        if any(keyword in title for keyword in defendant_keywords):
            return "defendant"
        if any(keyword in title for keyword in plaintiff_keywords):
            return "plaintiff"

        return "unknown"

    def _guess_categories(self, title) -> List[str]:
        """
        Use the SPOT API to predict the form's categories. If SPOT is not available,
        use basic heuristics applied on the title.

        Returns:
            List[str]: A list of categories
        """
        # Get the full text of all templates
        full_text = ""
        for template in self.uploaded_templates:
            if template.filename.lower().endswith(".pdf"):
                full_text += extract_text(template.path())
            elif template.filename.lower().endswith(".docx"):
                docx_data = docx2python(
                    template.path()
                )  # Will error with invalid value
                full_text += docx_data.text
        categories = formfyxer.spot(
            title + ": " + full_text,
            token=get_config("assembly line", {}).get("spot api key", None),
        )
        if categories and not "401" in categories:
            return categories
        # Top hits: Housing, Family, Consumer, Probate, Criminal, Traffic, Consumer, Health, Immigration, Employment
        if any(
            keyword in title.lower()
            for keyword in [
                "eviction",
                "foreclosure",
                "housing",
                "landlord",
                "tenant",
                "rent",
                "lease",
                "housing court",
                "unlawful detainer",
                "holdover",
                "evict",
            ]
        ):
            return ["HO-00-00-00-00"]
        elif any(
            keyword in title.lower()
            for keyword in [
                "divorce",
                "custody",
                "child",
                "family",
                "marriage",
                "marital",
                "parent",
                "guardian",
                "adoption",
            ]
        ):
            return ["FA-00-00-00-00"]
        elif any(
            keyword in title.lower()
            for keyword in [
                "consumer",
                "debt",
                "credit",
                "loan",
                "bankruptcy",
                "small claims",
            ]
        ):
            return ["MO-00-00-00-00"]
        elif any(
            keyword in title.lower()
            for keyword in [
                "probate",
                "estate",
                "will",
                "trust",
                "inheritance",
                "executor",
                "administrator",
                "personal representative",
                "guardian",
                "conservator",
                "power of attorney",
            ]
        ):
            return ["ES-00-00-00-00"]
        elif any(
            keyword in title.lower()
            for keyword in ["criminal", "crime", "misdemeanor", "felony"]
        ):
            return ["CR-00-00-00-00"]
        elif any(
            keyword in title.lower()
            for keyword in [
                "traffic",
                "ticket",
                "speeding",
                "speed",
                "driving",
                "license",
                "suspension",
                "revocation",
                "revoked",
                "suspended",
                "violation",
                "violate",
                "infraction",
                "fine",
                "fee",
                "court costs",
                "court fee",
                "court fine",
            ]
        ):
            return ["TR-00-00-00-00"]
        elif any(
            keyword in title.lower()
            for keyword in [
                "disability",
                "health",
                "medical",
                "medicaid",
                "medicare",
                "insurance",
                "benefits",
                "benefit",
                "social security",
                "ssi",
                "ssdi",
                "disability insurance",
                "disability benefits",
                "disability insurance benefits",
                "disability insurance benefit",
                "ssi",
                "social security",
            ]
        ):
            return ["HE-00-00-00-00"]
        elif any(
            keyword in title.lower()
            for keyword in [
                "visa",
                "asylum",
                "refugee",
                "naturalization",
                "citizenship",
                "alien",
                "deportation",
                "adjustment of status",
                "i-130",
                "n-400",
                "immigration",
                "immigrant",
            ]
        ):
            return ["IM-00-00-00-00"]
        elif any(
            keyword in title.lower()
            for keyword in [
                "employment",
                "unemployment",
                "insurance",
                "claim",
                "benefit",
                "wage",
                "jobless",
                "compensation",
                "workforce",
                "layoff",
            ]
        ):
            return ["WO-00-00-00-00"]
        return []

    def _null_group_fields(self):
        return {"Screen 1": [field.variable for field in self.all_fields.custom()]}

    def create_questions_from_screen_list(self, screen_list: List[Screen]):
        """
        Create a question for each screen in the screen list. This is an alternative to
        allow an author to upload a list of fields and then create a question for each
        without using FormFyxer's auto field creation.

        Args:
            screen_list (list): A list of dictionaries, each representing a screen
        """
        self.questions.auto_gather = False
        for screen in screen_list:
            question_text = str(screen.get("question", "") or "")
            subquestion_text = str(screen.get("subquestion", "") or "")
            continue_button_field = _get_continue_button_field(screen)
            has_any_fields = bool(screen.get("fields"))
            if (
                not question_text.strip()
                and not subquestion_text.strip()
                and not has_any_fields
                and not continue_button_field
            ):
                continue
            if not question_text.strip():
                continue
            new_screen = self.questions.appendObject()
            if continue_button_field:
                new_screen.continue_button_field = continue_button_field
                new_screen.is_informational = True
                new_screen.needs_continue_button_field = True
            else:
                new_screen.is_informational = False
                new_screen.needs_continue_button_field = False
            new_screen.type = "question"
            new_screen.question_text = question_text
            new_screen.subquestion_text = subquestion_text
            for field in screen.get("fields", []) or []:
                field_type = _field_type_from_definition(field)
                if field_type in ["skip this field", "code"]:
                    continue
                new_field = new_screen.field_list.appendObject()

                if field.get("label") and field.get("field"):
                    new_field.variable = field.get("field")
                    new_field.label = field.get("label")
                else:
                    first_item = next(iter(field.items()))
                    new_field.variable = first_item[1]
                    new_field.label = first_item[0]
                # Keep screen-list-created fields consistent with DAField objects
                # produced by template scanning and manual field editing.
                new_field.has_label = True
                new_field.final_display_var = new_field.variable
                new_field.source_document_type = "docx"
                # For some reason we made the field_type not exactly the same as the datatype in Docassemble
                # TODO: consider refactoring this
                if field_type:
                    new_field.field_type = field_type
                else:
                    new_field.field_type = "text"
                if field.get("maxlength"):
                    new_field.maxlength = field.get("maxlength", None)
                if field.get("choices"):
                    # We turn choices into a newline separated string
                    new_field.choices = "\n".join(field.get("choices") or [])
                if field.get("default") is not None:
                    new_field.default = field.get("default")
                if field.get("min"):
                    new_field.range_min = field.get("min", None)
                if field.get("max"):
                    new_field.range_max = field.get("max", None)
                if field.get("step"):
                    new_field.range_step = field.get("step", None)
                if field.get("required") == False:
                    new_field.is_optional = True
            new_screen.field_list.gathered = True
            if not screen.get("fields"):
                new_screen.needs_continue_button_field = True
        self.questions.gathered = True

    def auto_group_fields(self):
        """
        Use FormFyxer to assign fields to screens.
        To assist with "I'm feeling lucky" button
        """
        try:
            field_grouping = formfyxer.cluster_screens(
                [field.variable for field in self.all_fields.custom()],
                tools_token=get_config("assembly line", {}).get(
                    "tools.suffolklitlab.org api key", None
                ),
            )
            if not field_grouping:
                field_grouping = self._null_group_fields()
        except:
            log(
                f"Auto field grouping failed. Tried using tools.suffolklitlab.org api key {get_config('assembly line',{}).get('tools.suffolklitlab.org api key', None)}"
            )
            field_grouping = self._null_group_fields()
        self.field_grouping = field_grouping
        self.questions.auto_gather = False
        for group in field_grouping:
            group_fields = [
                str(name).strip()
                for name in (field_grouping.get(group) or [])
                if isinstance(name, str) and str(name).strip()
            ]
            if not group_fields:
                continue
            new_screen = self.questions.appendObject()
            new_screen.is_informational_screen = False
            new_screen.has_mandatory_field = True
            new_screen.type = "question"
            new_screen.needs_continue_button_field = False
            new_screen.question_text = group_fields[0].capitalize().replace("_", " ")
            new_screen.subquestion_text = ""
            new_screen.field_list.clear()
            for field in self.all_fields:
                if field.variable in group_fields:
                    new_screen.field_list.append(field)
            new_screen.field_list.gathered = True
            if not new_screen.field_list:
                new_screen.needs_continue_button_field = True
        self.questions.gathered = True

    def _auto_load_fields(self):
        """
        Automatically scan the interview's templates for fields and process
        them.
        """
        self.all_fields.clear()
        self.all_fields.add_fields_from_file(self.uploaded_templates)
        self.all_fields.gathered = True

    def get_file_types(self) -> Literal["pdf", "docx", "mixed"]:
        """
        Return the type of templates this interview assembles
        """
        kinds = set()
        for f in self.uploaded_templates:
            if f.filename.lower().endswith(".pdf"):
                if "docx" in kinds:
                    return "mixed"
                kinds.add("pdf")
            elif f.filename.lower().endswith(".docx"):
                if "pdf" in kinds:
                    return "mixed"
                kinds.add("docx")
        if len(kinds) == 1:
            if "pdf" in kinds:
                return "pdf"
            return "docx"
        return "mixed"

    def has_all_unlabeled_pdfs(self) -> bool:
        """
        Returns true only if the uploaded templates are:
         1. all PDFs
         2. without form fields.
        """
        if self.get_file_types() in ["docx", "mixed"]:
            return False

        return not any(has_fields(f.path()) for f in self.uploaded_templates)


def fix_id(string: str) -> str:
    """Returns a valid, readable docassemble YAML block id"""
    if string and isinstance(string, str):
        return re.sub(r"[\W_]+", " ", string).strip()
    else:
        return str(uuid.uuid4())


def fix_variable_name(match) -> str:
    var_name = match.group(1)
    var_name = end_spaces.sub(r"", var_name)
    var_name = spaces.sub(r"_", var_name)
    var_name = invalid_var_characters.sub(r"", var_name)
    var_name = digit_start.sub(r"", var_name)
    if len(var_name):
        return r"${ " + var_name + " }"
    return r""


def indent_by(text: str, num: int) -> str:
    if not text:
        return ""
    return (" " * num) + re.sub(r"\r*\n", "\n" + (" " * num), text).rstrip() + "\n"


def oneline(text: str) -> str:
    """Replaces all new line characters with a space"""
    if text:
        return newlines.sub(r" ", text)
    return ""


def escape_quotes(text: str) -> str:
    """Escape both single and double quotes in strings"""
    return text.replace('"', '\\"').replace("'", "\\'")


def escape_double_quoted_yaml(text: str) -> str:
    """Escape only double quotes in a string and the escape character itself"""
    return text.replace("\\", r"\\").replace('"', r"\"")


def to_yaml_file(text: str) -> str:
    text = varname(text)
    text = re.sub(r"\..*", r"", text)
    text = re.sub(r"[^A-Za-z0-9]+", r"_", text)
    return text + ".yml"


def base_name(filename: str) -> str:
    return os.path.splitext(filename)[0]


def repr_str(text: str) -> str:
    return remove_u.sub(r"", repr(text))


def docx_variable_fix(variable: str) -> str:
    variable = re.sub(r"\\", "", variable)
    variable = re.sub(r"^([A-Za-z\_][A-Za-z\_0-9]*).*", r"\1", variable)
    return variable


def get_fields(document: Union[DAFile, DAFileList]) -> Iterable:
    """Get the list of fields needed inside a template file (PDF or Docx Jinja
    tags). This will include attributes referenced. Assumes a file that
    has a valid and exiting filepath."""
    # TODO(qs): refactor to use DAField object at this stage
    if isinstance(document, DAFileList):
        if document[0].mimetype == "application/pdf":
            return document[0].get_pdf_fields()
    else:
        if document.mimetype == "application/pdf":
            return document.get_pdf_fields()

    docx_data = docx2python(document.path())  # Will error with invalid value
    text = docx_data.text
    return get_docx_variables(text)


def get_question_file_variables(screens: List[Screen]) -> List[str]:
    """Extract the fields from a list of screens representing a Docassemble interview,
    such as might be supplied as an input to the Weaver in JSON format.

    Args:
        screens (List[Screen]): A list of screens, each represented as a dictionary

    Returns:
        List[str]: A list of variables
    """
    fields: List[str] = []
    for screen in screens:
        continue_button_field = _get_continue_button_field(screen)
        if continue_button_field:
            fields.append(continue_button_field)
        if screen.get("fields"):
            for field in screen.get("fields", []) or []:
                raw_field = field.get("field")
                if isinstance(raw_field, str) and raw_field:
                    fields.append(raw_field)
                else:
                    # Append the first value in the field dictionary, which is the variable name
                    fld_tmp = next(iter(field.values()))
                    if isinstance(fld_tmp, str):
                        fields.append(fld_tmp)
    # remove duplicates without changing order
    return list(dict.fromkeys(fields))


def get_docx_variables(text: str) -> set:
    """
    Given the string from a docx file with fairly simple
    code), returns a list of everything that looks like a jinja variable in the string.

    Limits: some attributes and methods might not be designed to be directly
    assigned in docassemble. Methods are stripped, but you may be left with
    something you didn't intend. This is only going to help reach a draft interview.

    Special handling for methods that look like they belong to Individual/Address classes.
    """
    #   Can be easily tested in a repl using the libs keyword and re
    minimally_filtered = set()
    for possible_variable in re.findall(
        r"{{ *([^\} ]+) *}}", text
    ):  # Simple single variable use
        minimally_filtered.add(possible_variable)
    # Variables in the second parts of for loops (allow paragraph and whitespace flags)
    for possible_variable in re.findall(
        r"\{%[^ \t]* +for [A-Za-z\_][A-Za-z0-9\_]* in ([^\} ]+) +[^ \t]*%}", text
    ):
        minimally_filtered.add(possible_variable)
    # Variables in very simple `if` statements (allow paragraph and whitespace flags)
    for possible_variable in re.findall(r"{%[^ \t]* +if ([^\} ]+) +[^ \t]*%}", text):
        minimally_filtered.add(possible_variable)
    # Capture variables in `if` statements that contain a comparison
    for possible_variable in re.findall(
        r"{%[^ \t]* +if ([^\} ]+) ==|is|>|<|!=|<=|>= .* +[^ \t]*%}", text
    ):
        minimally_filtered.add(possible_variable)

    fields = set()

    for possible_var in minimally_filtered:
        # If no suffix exists, it's just the whole string
        prefix = re.findall(r"([^.]*)(?:\..+)*", possible_var)
        if not prefix[0]:
            continue  # This should never occur as they're all strings
        prefix_with_key = prefix[0]  # might have brackets

        prefix_root = re.sub(r"\[.+\]", "", prefix_with_key)  # no brackets
        # Filter out non-identifiers (invalid variable names), like functions
        if not prefix_root.isidentifier():
            continue

        if ".mailing_address" in possible_var:  # a mailing address
            if ".mailing_address.county" in possible_var:  # a county is special
                fields.add(possible_var)
            else:  # all other mailing addresses (replaces .zip and such)
                fields.add(
                    re.sub(
                        r"\.mailing_address.*", ".mailing_address.address", possible_var
                    )
                )
            continue

        # Help gathering actual address as an attribute when document says something
        # like address.block()
        if ".address" in possible_var:  # an address
            if ".address.county" in possible_var:  # a county is special
                fields.add(possible_var)
            else:  # all other addresses and methods on addresses (replaces .address_block() and .address.block())
                fields.add(re.sub(r"\.address.*", ".address.address", possible_var))
            # fields.add( prefix_with_key ) # Can't recall who added or what was this supposed to do?
            # It will add an extra, erroneous entry of the object root, which usually doesn't
            # make sense for a docassemble question
            continue

        if ".name" in possible_var:  # a name
            if ".name.text" in possible_var:  # Names for non-Individuals
                fields.add(possible_var)
            else:  # Names for Individuals
                fields.add(re.sub(r"\.name.*", ".name.first", possible_var))
            continue

        # Replace any methods at the end of the variable with the attributes they use
        possible_var = substitute_suffix(
            possible_var, generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX
        )
        methods_removed = re.sub(r"(.*)\..*\(.*\)", "\\1", possible_var)
        fields.add(methods_removed)

    return fields


########################################################
# Map names code


def map_raw_to_final_display(
    label: str,
    document_type: str = "pdf",
    reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
    custom_people_plurals_map: Optional[Dict[str, str]] = None,
    reserved_prefixes=generator_constants.RESERVED_PREFIXES,
    undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
    reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
    reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP,
) -> str:
    """For a given set of specific cases, transform a
    PDF field name into a standardized object name
    that will be the value for the attachment field."""
    if not custom_people_plurals_map:
        custom_people_plurals_map = {}
    if document_type.lower() == "docx" or "." in label:
        return label  # don't transform DOCX variables

    # Turn spaces into `_`, strip non identifier characters
    label = varname(label)

    # Remove multiple appearance indicator, e.g. '__4' of 'users__4'
    label = remove_multiple_appearance_indicator(label)

    if (
        label in reserved_whole_words
        or label in reserved_pluralizers_map.values()
        or label in undefined_person_prefixes
        or label in custom_people_plurals_map.values()
    ):
        return label

    # Break up label into its parts: prefix, digit, the rest
    all_prefixes = list(reserved_prefixes) + list(custom_people_plurals_map.values())
    label_groups = get_reserved_label_parts(all_prefixes, label)

    # If no matches to automateable labels were found,
    # just use the label as it is
    if label_groups is None or label_groups[1] == "":
        return label

    prefix = label_groups[1]
    # Map prefix to an adjusted version
    # At the moment, turn any singulars into plurals if needed, e.g. 'user' into 'users'
    adjusted_prefix = reserved_pluralizers_map.get(prefix, prefix)
    adjusted_prefix = custom_people_plurals_map.get(prefix, adjusted_prefix)
    # With reserved plurals, we're always using an index
    # of the plural version of the prefix of the label
    if (
        adjusted_prefix in reserved_pluralizers_map.values()
        or adjusted_prefix in custom_people_plurals_map.values()
    ):
        digit_str = label_groups[2]
        if digit_str == "":
            index = "[0]"
        else:
            try:
                digit = int(digit_str)
            except ValueError as ex:
                main_issue = f"{digit_str} is not a digit"
                err_str = f"Full issue: {ex}. This is likely a developer error! Please [let us know](https://github.com/SuffolkLITLab/docassemble.ALWeaver/issues/new)!"
                raise ParsingException(main_issue, err_str)

            if digit == 0:
                correct_label = adjusted_prefix + "1" + label_groups[3]
                main_issue = "Cannot get the 0th item in a list"
                err_str = f'The "{label}" label refers to the 0th item in a list, when it is likely meant the 1st item. You should replace that label with "{correct_label}".'
                url = "https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/label_variables/#special-situation-for-names-of-people-in-pdfs"
                raise ParsingException(main_issue, err_str, url)
            else:
                index = "[" + str(digit - 1) + "]"
    else:
        digit_str = ""
        index = ""

    # it's just a standalone, like "defendant", or it's a numbered singular
    # prefix, e.g. user3
    if label == prefix or label == prefix + digit_str:
        return adjusted_prefix + index  # Return the pluralized standalone variable

    suffix = label_groups[3]
    # Avoid transforming arbitrary suffixes into attributes
    if not suffix in reserved_suffixes_map:
        return label  # return it as is

    # Get the mapped suffix attribute if present, else just use the same suffix
    suffix_as_attribute = reserved_suffixes_map.get(suffix, suffix)
    return "".join([adjusted_prefix, index, suffix_as_attribute])


def is_reserved_docx_label(
    label: str,
    docx_only_suffixes=generator_constants.DOCX_ONLY_SUFFIXES,
    reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
    undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
    reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
    reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP,
    allow_singular_suffixes=generator_constants.ALLOW_SINGULAR_SUFFIXES,
) -> bool:
    """Given a string, will return whether the string matches
    reserved variable names. `label` must be a string."""
    if label in reserved_whole_words:
        return True

    # Everything before the first period and everything from the first period to the end
    label_parts = re.findall(r"([^.]*)(\..*)*", label)

    # test for existence (empty strings result in a tuple)
    if not label_parts[0]:
        return False
    # The prefix, ensuring no key or index
    # Not sure this handles keys/attributes
    prefix = re.sub(r"\[.+\]", "", label_parts[0][0])
    is_reserved = (
        prefix in reserved_pluralizers_map.values()
        or prefix in undefined_person_prefixes
    )

    if is_reserved:
        suffix = label_parts[0][1]
        if not suffix:  # If only the prefix
            return True
        # If the suffix is also reserved
        # Regex for finding all exact matches of docx suffixes
        docx_only_suffixes_regex = "^" + "$|^".join(docx_only_suffixes) + "$"
        docx_suffixes_matches = re.findall(docx_only_suffixes_regex, suffix)
        if (
            suffix in reserved_suffixes_map.values() or len(docx_suffixes_matches) > 0
        ) and (prefix in allow_singular_suffixes or label_parts[0][0].endswith("]")):
            # We do NOT want users.address.address to match, only users[0].address.address
            # but we do allow trial_court.address.address. Make sure we don't overmatch
            return True

    # For all other cases
    return False


############################
#  Identify reserved PDF labels
############################
def is_reserved_label(
    label,
    reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
    reserved_prefixes=generator_constants.RESERVED_PREFIXES,
    reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
    reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP,
) -> bool:
    """Given a PDF label, returns whether the label fully
    matches a reserved prefix or a reserved prefix with a
    reserved suffix"""

    # Get rid of all multi-appearance indicators, e.g. '__4' of 'user_name__4'
    # Doesn't matter if it's a first appearance or more
    label = remove_multiple_appearance_indicator(label)

    if label in reserved_whole_words:
        return True
    # For the sake of time, this is the fastest way to get around something being plural
    if label in reserved_pluralizers_map.values():
        return True

    # Break up label into its parts
    label_groups = get_reserved_label_parts(reserved_prefixes, label)
    # If no other matches to reserved prefixes were found
    if label_groups is None or label_groups[1] == "":
        return False
    # If there are no suffixes, just the reserved prefix
    suffix = label_groups[3]
    if suffix == "":
        return True

    return suffix in reserved_suffixes_map


############################
#  Label processing helper functions
############################
def remove_multiple_appearance_indicator(label: str) -> str:
    return re.sub(r"_{2,}\d+", "", label)


def substitute_suffix(
    label: str, display_suffixes: Dict[str, str] = generator_constants.FULL_DISPLAY
) -> str:
    """Map attachment/displayable attributes or methods into interview order
    attributes. For example, `.address()` will become `.address.address`"""
    for suffix in display_suffixes:
        match_regex = re.compile(".*" + suffix)
        if re.match(match_regex, label):
            sub_regex = re.compile(suffix)
            new_label = re.sub(sub_regex, display_suffixes[suffix], label)
            return new_label
    return label


def get_reserved_label_parts(prefixes: list, label: str):
    """
    Return an re.matches object for all matching variable names,
    like user1_something, etc.
    """
    return re.search(r"^(" + "|".join(prefixes) + r")(\d*)(.*)", label)


def using_string(params: dict, elements_as_variable_list: bool = False) -> str:
    """
    Create a text representation of a .using method of a DAObject class.
    Provide a dictionary of parameters as an argument.
    Returns a string like: ".using(param='value', param2=True, param3=3)"
    given a dictionary of {"param":"value","param2":True, "param3":3}.

    Parameters will be converted using `repr`.
    Special case: the parameter "elements" given a list of strings will
    be rendered as a list of variables instead if elements_as_variable_list=True.

    TODO: this is relatively rigid, but is simplest for current needs. Could easily
    adjust the template or not use this function.
    """
    if not params or len(params) < 1:
        return ""
    retval = ".using("
    params_string_builder = []
    for param in params:
        if elements_as_variable_list and param == "elements":
            params_string_builder.append(
                "elements=[" + ",".join([str(p) for p in params[param]]) + "]"
            )
        else:
            params_string_builder.append(str(param) + "=" + repr(params[param]))
    retval += ",".join(params_string_builder)
    return retval + ")"


def pdf_field_type_str(field) -> str:
    """Gets a human readable string from a PDF field code, like '/Btn'"""
    if not isinstance(field, tuple) or len(field) < 4 or not isinstance(field[4], str):
        return ""
    else:
        if field[4] == "/Sig":
            return "Signature"
        elif field[4] == "/Btn":
            return "Checkbox"
        elif field[4] == "/Tx":
            return "Text"
        else:
            return ":skull-crossbones:"


######################################
# Recognizing errors with PDF and DOCX files and variable names
######################################


def is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def bad_name_reason(field: DAField) -> Optional[str]:
    """Returns if a PDF or DOCX field name is valid for AssemblyLine or not"""
    if field.source_document_type == "docx":
        # We can't map DOCX fields to valid variable names, but we can tell if they are valid expressions
        # TODO(brycew): this needs more work, we already filter out bad names in get_docx_variables()
        if matching_reserved_names({field.variable}, keywords_and_builtins_only=True):
            return f"`{field.variable}` is a [reserved Python keyword](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/framework/reserved_keywords) and cannot be used as a variable name"
        if not is_valid_python(field.variable):
            return f"`{ field.variable }` is not a valid python expression"
        return None
    else:
        if matching_reserved_names({field.variable}):
            return f"`{ field.variable }` is already used with a [different meaning](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/framework/reserved_keywords) in Python, Docassemble, or the AssemblyLine package"
        if len(field.variable) == 0:
            if len(field.raw_field_names) == 0:
                start = f"A { field.field_type_guess } field has no name. "
            if len(field.raw_field_names) == 1:
                start = f"A { field.field_type_guess } field has no name. In the PDF, it is called "
            else:
                start = f"Some { field.field_type_guess } fields have no name. In the PDF, they are called "
            if len(field.raw_field_names) > 0:
                start += (
                    comma_and_list(
                        [n.replace("`", r"\`") for n in field.raw_field_names]
                    )
                    + ". "
                )
            return (
                start
                + "All field names should be in [snake case](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/naming#pdf-variables--snake_case)."
            )
        # log(field[0], "console")
        python_var = map_raw_to_final_display(
            remove_multiple_appearance_indicator(varname(field.variable)),
            document_type="pdf",
        )
        if len(python_var) == 0:
            return f"`{ field.variable }`, the { field.field_type_guess } field, should be in [snake case](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/naming#pdf-variables--snake_case) and use alphabetical characters"
        return None


ValidationError = Tuple[str, Union[str, ParsingException]]


def get_pdf_validation_errors(document: DAFile) -> Optional[ValidationError]:
    try:
        fields = DAFieldList()
        fields.add_fields_from_file(document)
    except ParsingException as ex:
        return ("parsing_exception", ex)
    except PDFSyntaxError:
        return ("invalid_pdf", "Invalid PDF")
    except PSEOF:
        return (
            "pseof",
            "File appears incomplete (PSEOF error). Is this a valid PDF file?",
        )
    except:
        return ("unknown", "Unknown error reading PDF file. Is this a valid PDF?")
    try:
        pdf_concatenate(document, document)
    except:
        return (
            "concatenation_error",
            "Unknown error concatenating PDF file to itself. The file may be invalid.",
        )
    return None


def get_docx_validation_errors(document: DAFile) -> Optional[ValidationError]:
    try:
        fields = DAFieldList()
        fields.add_fields_from_file(document)
    except (BadZipFile, KeyError):
        return ("bad_docx", "Error opening DOCX. Is this a valid DOCX file?")
    try:
        pdf_concatenate(document)
    except:
        return (
            "unable_to_convert_to_pdf",
            "Unable to convert to PDF. Is this is a valid DOCX file?",
        )
    return None


def get_help_document_text(document: DAFile) -> str:
    """
    Extract readable text from an uploaded PDF or DOCX help document.
    Returns an empty string when text cannot be extracted.
    """
    if not document or not hasattr(document, "path"):
        return ""

    filename = str(getattr(document, "filename", "") or "").lower()
    try:
        if filename.endswith(".pdf"):
            return extract_text(document.path()) or ""
        if filename.endswith(".docx"):
            return docx2python(document.path()).text or ""
    except (PDFSyntaxError, PSEOF, BadZipFile, KeyError, ValueError):
        return ""
    except Exception:
        return ""
    return ""


def get_variable_name_warnings(fields: Iterable[DAField]) -> Iterable[str]:
    """
    If any fields have invalid variable names, get a list of those reasons.
    """
    return [
        reason
        for reason in (bad_name_reason(field) for field in fields)
        if reason is not None
    ]


def get_pdf_variable_name_matches(document: Union[DAFile, str]) -> Set[Tuple[str, str]]:
    """
    Identify any variable names that look like they are intended to be for a PDF
    in a DOCX template.
    """
    if isinstance(document, DAFile):
        docx_data = docx2python(document.path())
    else:
        docx_data = docx2python(document)
    text = docx_data.text
    fields = get_docx_variables(text)
    res = set()
    for field in fields:
        # See if the docx fields would change at all if they were actually in a PDF.
        # This means that the author may have been following the PDF labeling tutorials
        try:
            possible_new_field = map_raw_to_final_display(field, document_type="pdf")
            if possible_new_field != field:
                res.add((field, possible_new_field))
        except ParsingException:
            # ParsingExceptions are fine, because we aren't really parsing a PDF
            pass
    return res


def reflect_fields(
    pdf_field_tuples: List[Tuple], image_placeholder: DAFile = None
) -> List[Dict[str, str]]:
    """Return a mapping between the field names and either the same name, or "yes"
    if the field is a checkbox value, in order to visually capture the location of
    labeled fields on the PDF."""
    mapping = []
    for field in pdf_field_tuples:
        if field[4] == "/Btn":
            export_val = field[5] if len(field) >= 6 else ""
            if str(export_val).lower() in ["yes", "on", "true", ""]:
                mapping.append({field[0]: "Yes"})
            else:
                if field[0] not in [
                    next(iter(field_val.keys())) for field_val in mapping
                ]:
                    mapping.append({field[0]: export_val})
        elif field[4] == "/Sig" and image_placeholder:
            mapping.append({field[0]: image_placeholder})
        else:
            mapping.append({field[0]: field[0]})
    return mapping


def is_url(url: str) -> bool:
    """
    Returns True if and only if the input string is in the format of a valid URL
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


############################
# Create a Docassemble .zip package
############################


def create_package_zip(
    pkgname: str,
    info: dict,
    author_info: dict,
    folders_and_files: dict,
    fileobj: DAFile = None,
) -> DAFile:
    """
    Given a dictionary of lists, with the keys representing folders and the values
    representing a list of DAFiles, create a Python package with Docassemble conventions.
    info: (created by DAInterview.package_info())
      license
      author_name
      readme
      description
      url
      version
      dependencies
      // interview_files replaced with folders_and_files
      // template_files
      // module_files
      // static_files
    author_info:
      author name and email
    folders_and_files:
      questions->list of DAFiles/DAFile-like objects
      templates
      modules
      static
      sources

    Structure of a docassemble package:
    + docassemble-PKGNAME/
        LICENSE
        MANIFEST.in
        README.md
        setup.cfg
        setup.py
        +-------docassemble
            __init__.py
            +------PKGNAME
                __init__.py
                SOME_MODULE.py
                +------data
                    +------questions
                        README.md
                    +------sources
                        README.md
                    +------static
                        README.md
                    +------templates
                        README.md
    """
    pkgname = space_to_underscore(pkgname)
    if fileobj:
        zip_download = fileobj
    else:
        zip_download = DAFile()
    pkg_path_prefix = "docassemble-" + pkgname
    pkg_path_init_prefix = os.path.join(pkg_path_prefix, "docassemble")
    pkg_path_deep_prefix = os.path.join(pkg_path_init_prefix, pkgname)
    pkg_path_data_prefix = os.path.join(pkg_path_deep_prefix, "data")
    pkg_path_questions_prefix = os.path.join(pkg_path_data_prefix, "questions")
    pkg_path_sources_prefix = os.path.join(pkg_path_data_prefix, "sources")
    pkg_path_static_prefix = os.path.join(pkg_path_data_prefix, "static")
    pkg_path_templates_prefix = os.path.join(pkg_path_data_prefix, "templates")

    zip_download.initialize(filename="docassemble-" + pkgname + ".zip")
    zip_obj = zipfile.ZipFile(zip_download.path(), "w")

    dependencies = ",".join(["'" + dep + "'" for dep in info["dependencies"]])

    initpy = """\
try:
    __import__('pkg_resources').declare_namespace(__name__)
except ImportError:
    __path__ = __import__('pkgutil').extend_path(__path__, __name__)
"""
    licensetext = str(info["license"])
    if re.search(r"MIT License", licensetext):
        licensetext += (
            "\n\nCopyright (c) "
            + str(datetime.datetime.now().year)
            + " "
            + str(info.get("author_name", ""))
            + """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
        )
    if info["readme"] and re.search(r"[A-Za-z]", info["readme"]):
        readme = str(info["readme"])
    else:
        readme = (
            "# docassemble."
            + str(pkgname)
            + "\n\n"
            + info["description"]
            + "\n\n## Author\n\n"
            + author_info["author name and email"]
            + "\n\n"
        )
    manifestin = """\
include README.md
"""
    setupcfg = """\
[metadata]
description_file = README.md
"""
    setuppy = """\
import os
import sys
from setuptools import setup, find_packages
from fnmatch import fnmatchcase
from distutils.util import convert_path
standard_exclude = ('*.pyc', '*~', '.*', '*.bak', '*.swp*')
standard_exclude_directories = ('.*', 'CVS', '_darcs', './build', './dist', 'EGG-INFO', '*.egg-info')
def find_package_data(where='.', package='', exclude=standard_exclude, exclude_directories=standard_exclude_directories):
    out = {}
    stack = [(convert_path(where), '', package)]
    while stack:
        where, prefix, package = stack.pop(0)
        for name in os.listdir(where):
            fn = os.path.join(where, name)
            if os.path.isdir(fn):
                bad_name = False
                for pattern in exclude_directories:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        break
                if bad_name:
                    continue
                if os.path.isfile(os.path.join(fn, '__init__.py')):
                    if not package:
                        new_package = name
                    else:
                        new_package = package + '.' + name
                        stack.append((fn, '', new_package))
                else:
                    stack.append((fn, prefix + name + '/', package))
            else:
                bad_name = False
                for pattern in exclude:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        break
                if bad_name:
                    continue
                out.setdefault(package, []).append(prefix+name)
    return out
"""
    setuppy += (
        "setup(name='docassemble."
        + str(pkgname)
        + "',\n"
        + """\
      version="""
        + repr(info.get("version", ""))
        + """,
      description=("""
        + repr(info.get("description", ""))
        + """),
      long_description="""
        + repr(readme)
        + """,
      long_description_content_type='text/markdown',
      author="""
        + repr(info.get("author_name", ""))
        + """,
      author_email="""
        + repr(info.get("author_email", ""))
        + """,
      license="""
        + repr(info.get("license", ""))
        + """,
      url="""
        + repr(info["url"] if info["url"] else "https://docassemble.org")
        + """,
      packages=find_packages(),
      namespace_packages=['docassemble'],
      install_requires=["""
        + dependencies
        + """],
      zip_safe=False,
      package_data=find_package_data(where='docassemble/"""
        + str(pkgname)
        + """/', package='docassemble."""
        + str(pkgname)
        + """'),
     )
"""
    )
    templatereadme = """\
# Template directory
If you want to use templates for document assembly, put them in this directory.
"""
    staticreadme = """\
# Static file directory
If you want to make files available in the web app, put them in
this directory.
"""
    sourcesreadme = """\
# Sources directory
This directory is used to store word translation files,
machine learning training files, and other source files.
"""
    templatesreadme = """\
# Template directory
This directory is used to store templates.
"""
    # Write the standard files
    zip_obj.writestr(os.path.join(pkg_path_prefix, "LICENSE"), licensetext)
    zip_obj.writestr(os.path.join(pkg_path_prefix, "MANIFEST.in"), manifestin)
    zip_obj.writestr(os.path.join(pkg_path_prefix, "README.md"), readme)
    zip_obj.writestr(os.path.join(pkg_path_prefix, "setup.cfg"), setupcfg)
    zip_obj.writestr(os.path.join(pkg_path_prefix, "setup.py"), setuppy)
    zip_obj.writestr(os.path.join(pkg_path_init_prefix, "__init__.py"), initpy)
    zip_obj.writestr(
        os.path.join(pkg_path_deep_prefix, "__init__.py"),
        ("__version__ = " + repr(info.get("version", "")) + "\n"),
    )
    zip_obj.writestr(
        os.path.join(pkg_path_questions_prefix, "README.md"), templatereadme
    )
    zip_obj.writestr(os.path.join(pkg_path_sources_prefix, "README.md"), sourcesreadme)
    zip_obj.writestr(os.path.join(pkg_path_static_prefix, "README.md"), staticreadme)
    zip_obj.writestr(
        os.path.join(pkg_path_templates_prefix, "README.md"), templatesreadme
    )

    # Modules
    for file in folders_and_files.get("modules", []):
        try:
            zip_obj.write(
                file.path(), os.path.join(pkg_path_deep_prefix, file.filename)
            )
        except:
            log("Unable to add file " + repr(file))
    # Templates
    for file in folders_and_files.get("templates", []):
        try:
            zip_obj.write(
                file.path(), os.path.join(pkg_path_templates_prefix, file.filename)
            )
        except:
            log("Unable to add file " + repr(file))
    # sources
    for file in folders_and_files.get("sources", []):
        try:
            zip_obj.write(
                file.path(), os.path.join(pkg_path_sources_prefix, file.filename)
            )
        except:
            log("Unable to add file " + repr(file))
    # static
    for file in folders_and_files.get("static", []):
        try:
            zip_obj.write(
                file.path(), os.path.join(pkg_path_static_prefix, file.filename)
            )
        except:
            log("Unable to add file " + repr(file))
    # questions
    for file in folders_and_files.get("questions", []):
        try:
            zip_obj.write(
                file.path(), os.path.join(pkg_path_questions_prefix, file.filename)
            )
        except:
            log("Unable to add file " + repr(file))

    zip_obj.close()
    zip_download.commit()
    return zip_download


def _ensure_current_question_package(package_name: str = "ALWeaver") -> None:
    # DAStaticFile.init expects this_thread.current_question.package even outside
    # interview runtime; synthesize it for direct Python entry points.
    try:
        current_question = docassemble.base.functions.this_thread.current_question
    except Exception:
        return
    if not current_question:
        docassemble.base.functions.this_thread.current_question = type("", (), {})()
    docassemble.base.functions.this_thread.current_question.package = package_name


class _LocalDAStaticFile(DAStaticFile):
    def init(self, *pargs, **kwargs):
        if "full_path" in kwargs:
            full_path = kwargs["full_path"]
            self.full_path = str(full_path)
            filename = os.path.basename(self.full_path)
            extension = os.path.splitext(filename)[1][1:]
            kwargs.setdefault("filename", filename)
            kwargs.setdefault("extension", extension)
            if extension.lower() == "pdf":
                kwargs.setdefault("mimetype", "application/pdf")
            elif extension.lower() == "docx":
                kwargs.setdefault(
                    "mimetype",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
        super().init(*pargs, **kwargs)

    def path(self):
        return self.full_path


def _make_static_file_from_path(path: str) -> DAStaticFile:
    return _LocalDAStaticFile(full_path=path)


def _resolve_template_path(template_ref: str) -> str:
    """
    Resolve the path to a template file using docassemble's path_and_mimetype.
    This works correctly in both Playground and installed package contexts.
    """
    if os.path.isabs(template_ref) and os.path.exists(template_ref):
        return template_ref

    template_name = (
        template_ref.split(":", 1)[1] if ":" in template_ref else template_ref
    )
    file_path = None
    try:
        if ":" in template_ref:
            # Format: package_name:template_name
            package_name, template_name = template_ref.split(":", 1)
            file_path, _ = path_and_mimetype(
                f"{package_name}:data/templates/{template_name}"
            )
        else:
            file_path, _ = path_and_mimetype(f"data/templates/{template_name}")
    except Exception:
        file_path = None

    if file_path and os.path.exists(file_path):
        return file_path

    local_path = os.path.join(
        os.path.dirname(__file__), "data", "templates", template_name
    )
    if os.path.exists(local_path):
        return local_path
    raise FileNotFoundError(f"Could not resolve template path for: {template_ref}")


def _field_type_from_definition(field_def: FieldDefinition) -> Optional[str]:
    raw = (
        field_def.get("datatype")
        or field_def.get("field_type")
        or field_def.get("input type")
        or field_def.get("input_type")
    )
    if not raw:
        return None
    if isinstance(raw, DADataType):
        raw = raw.value
    raw_normalized = str(raw).strip().lower()
    if raw_normalized in ["skip", "skip this field", "skip_this_field"]:
        return "skip this field"
    if raw_normalized == "code":
        return "code"
    if raw_normalized == "radio":
        return "multiple choice radio"
    if raw_normalized == "checkboxes":
        return "multiple choice checkboxes"
    if raw_normalized == "dropdown":
        return "multiple choice dropdown"
    if raw_normalized == "combobox":
        return "multiple choice combobox"
    return raw if isinstance(raw, str) else str(raw)


def _coerce_optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _apply_field_definition(field: DAField, field_def: FieldDefinition) -> None:
    field_type = _field_type_from_definition(field_def)
    if field_def.get("label") is not None:
        field.label = field_def.get("label")
        field.has_label = True
    if field_type:
        field.field_type = field_type
    raw_maxlength = field_def.get("maxlength")
    maxlength = _coerce_optional_int(raw_maxlength)
    if maxlength is not None:
        field.maxlength = maxlength
    if field_def.get("choices") is not None:
        field.choices = "\n".join(field_def.get("choices") or [])
    if field_def.get("min") is not None:
        field.range_min = field_def.get("min")
    if field_def.get("max") is not None:
        field.range_max = field_def.get("max")
    if field_def.get("step") is not None:
        field.range_step = field_def.get("step")
    if field_def.get("required") is False:
        field.is_optional = True
    if field_def.get("required") is True:
        field.is_optional = False
    if field_def.get("default") is not None:
        field.default = field_def.get("default")
    if field_type == "code":
        code_value = field_def.get("value", field_def.get("code"))
        if code_value is not None:
            field.code = code_value
    if field_type == "skip this field":
        if field_def.get("value") is not None:
            field.value = field_def.get("value")


def _field_matches_name(field: DAField, field_name: str) -> bool:
    if field_name == field.get_settable_var():
        return True
    if field_name == field.final_display_var:
        return True
    if field_name == field.variable:
        return True
    if hasattr(field, "raw_field_names") and field_name in field.raw_field_names:
        return True
    return False


def _ensure_field_in_interview(
    interview: DAInterview, field_name: str
) -> Tuple[DAField, bool]:
    for field in interview.all_fields:
        if _field_matches_name(field, field_name):
            return field, False
    new_field = interview.all_fields.appendObject()
    new_field.source_document_type = "docx"
    new_field.raw_field_names = [field_name]
    new_field.variable = field_name
    new_field.final_display_var = field_name
    new_field.has_label = True
    new_field.variable_name_guess = field_name.replace("_", " ").capitalize()
    new_field.field_type_guess = "text"
    new_field.field_type = "text"
    new_field.group = DAFieldGroup.CUSTOM
    new_field.label = new_field.variable_name_guess
    return new_field, True


def _apply_field_definitions_to_interview(
    interview: DAInterview, field_definitions: Optional[List[FieldDefinition]]
) -> bool:
    if not field_definitions:
        return False
    added_fields = False
    for field_def in field_definitions:
        field_name = field_def.get("field")
        if not field_name:
            continue
        field, created = _ensure_field_in_interview(interview, field_name)
        if created:
            added_fields = True
        _apply_field_definition(field, field_def)
    interview.all_fields.gathered = True
    return added_fields


def _normalize_screen_field(field_entry: FieldDefinition) -> Dict[str, Any]:
    if "field" in field_entry:
        return dict(field_entry)
    if len(field_entry) == 1:
        label, field_name = next(iter(field_entry.items()))
        return {"label": label, "field": field_name}
    return dict(field_entry)


def _as_field_definition(value: Mapping[str, Any]) -> Field:
    """Filter an arbitrary mapping down to keys/types allowed by the Field TypedDict."""
    out: Field = {}
    if "label" in value and (value["label"] is None or isinstance(value["label"], str)):
        out["label"] = value["label"]
    if "field" in value and (value["field"] is None or isinstance(value["field"], str)):
        out["field"] = value["field"]
    if "datatype" in value:
        out["datatype"] = value["datatype"]  # validated downstream
    if "field_type" in value:
        out["field_type"] = value["field_type"]  # validated downstream
    if "input_type" in value:
        out["input_type"] = value["input_type"]  # validated downstream
    if "input type" in value:
        out["input type"] = value["input type"]  # validated downstream
    if "default" in value:
        out["default"] = value["default"]
    if "value" in value:
        out["value"] = value["value"]
    if "code" in value:
        out["code"] = value["code"]
    if "maxlength" in value:
        out["maxlength"] = _coerce_optional_int(value["maxlength"])
    if "choices" in value and (
        value["choices"] is None or isinstance(value["choices"], (list, tuple))
    ):
        out["choices"] = value["choices"]
    if "min" in value:
        out["min"] = value["min"]
    if "max" in value:
        out["max"] = value["max"]
    if "step" in value:
        out["step"] = value["step"]
    if "required" in value and (
        value["required"] is None or isinstance(value["required"], bool)
    ):
        out["required"] = value["required"]
    return out


def _get_continue_button_field(screen: Screen) -> Optional[str]:
    for key in ("continue_button_field", "continue button field"):
        raw_value = screen.get(key)
        if isinstance(raw_value, str):
            normalized = raw_value.strip()
            if normalized:
                return normalized
    return None


def _is_renderable_question_screen(screen: Any) -> bool:
    """Return True if a DAQuestion has enough content to safely emit YAML."""
    if not isinstance(screen, DAQuestion):
        return True
    if getattr(screen, "type", None) != "question":
        return True

    question_text = str(getattr(screen, "question_text", "") or "").strip()
    if not question_text:
        return False

    field_list = getattr(screen, "field_list", None)
    has_fields = bool(field_list and len(field_list) > 0)
    if has_fields:
        return True

    if bool(getattr(screen, "needs_continue_button_field", False)):
        # If needed, we can always fall back to varname(question_text) when an explicit
        # continue button variable is absent.
        return True

    subquestion_text = str(getattr(screen, "subquestion_text", "") or "").strip()
    return bool(subquestion_text)


def _merge_field_definitions_into_screens(
    screen_definitions: List[Screen],
    field_definitions: Optional[List[FieldDefinition]] = None,
) -> List[Screen]:
    definitions_by_field: Dict[str, FieldDefinition] = {}
    for field_def in field_definitions or []:
        field_name = field_def.get("field")
        if field_name:
            definitions_by_field[field_name] = field_def

    merged_screens: List[Screen] = []
    for screen in screen_definitions or []:
        merged_screen: Dict[str, Any] = dict(screen)
        continue_button_field = _get_continue_button_field(screen)
        if continue_button_field:
            merged_screen["continue button field"] = continue_button_field
        merged_fields: List[FieldDefinition] = []
        for field_entry in screen.get("fields", []) or []:
            normalized = _normalize_screen_field(field_entry)
            field_name = normalized.get("field")
            if not isinstance(field_name, str) or not field_name:
                continue
            base_def = definitions_by_field.get(field_name)
            base: Dict[str, Any] = {}
            # FieldDefinition allows a legacy {Label: "var"} mapping; ignore it here.
            if isinstance(base_def, dict) and "field" in base_def:
                base = dict(base_def)
            base.update(normalized)
            merged = _as_field_definition(base)
            field_type = _field_type_from_definition(merged)
            if field_type in ["skip this field", "code"]:
                continue
            merged_fields.append(merged)
        merged_screen["fields"] = merged_fields
        merged_screens.append(cast(Screen, merged_screen))
    return merged_screens


def _metadata_defaults_for_lint(interview: DAInterview) -> Dict[str, str]:
    state_value = str(getattr(interview, "state", "") or "").strip().upper()
    country_value = (
        str(getattr(interview, "default_country_code", "US") or "US").strip().upper()
    )
    jurisdiction_value = str(getattr(interview, "jurisdiction", "") or "").strip()
    if not jurisdiction_value:
        if country_value == "US" and state_value:
            jurisdiction_value = f"NAM-US-US+{state_value}"
        elif country_value:
            jurisdiction_value = f"NAM-{country_value}"
        else:
            jurisdiction_value = "NAM-US"

    landing_page_url_value = str(
        getattr(interview, "landing_page_url", "") or ""
    ).strip()
    if not landing_page_url_value:
        original_form_url = str(getattr(interview, "original_form", "") or "").strip()
        if original_form_url.startswith(("http://", "https://")):
            landing_page_url_value = original_form_url
        else:
            landing_page_url_value = "https://courtformsonline.org/"

    return {
        "jurisdiction": jurisdiction_value,
        "landing_page_url": landing_page_url_value,
        "default_topic": "CO-00-00-00-00",
    }


def _screen_heading(screen: Union["DAQuestion", "DAField"]) -> str:
    if isinstance(screen, DAQuestion):
        return str(getattr(screen, "question_text", "") or "").strip()
    try:
        return str(screen.variable)
    except Exception:
        return ""


def _deterministic_section_id_for_screen(
    screen: Union["DAQuestion", "DAField"], trigger: str
) -> str:
    heading = _screen_heading(screen).lower()
    trigger_l = (trigger or "").lower()
    text = f"{heading} {trigger_l}".strip()
    if "signature" in text or trigger_l.endswith(".signature") or "sign" in heading:
        return "sign_and_submit"
    if "serve" in text or "service" in text or "notice" in text:
        return "service_and_notice"
    if (
        "plaintiff" in text
        or "defendant" in text
        or "attorney" in text
        or "party" in text
        or "users.gather()" in trigger_l
    ):
        return "people"
    if "name" in text or "address" in text or "phone" in text or "email" in text:
        return "about_you"
    return "case_details"


def _section_label(section_id: str) -> str:
    labels = {
        "about_you": "About You",
        "people": "People",
        "case_details": "Case Details",
        "service_and_notice": "Service and Notice",
        "sign_and_submit": "Sign and Submit",
    }
    return labels.get(section_id, fix_id(section_id).title())


def _normalize_section_id(value: str, fallback: str = "section") -> str:
    normalized = varname(str(value or "")).lower().strip("_")
    return normalized or fallback


def _sections_from_frontend(interview: DAInterview) -> List[Dict[str, str]]:
    if not bool(getattr(interview, "enable_navigation", False)):
        return []
    raw_sections = getattr(interview, "sections", None)
    if not raw_sections:
        return []
    output: List[Dict[str, str]] = []
    seen_ids: Set[str] = set()
    for idx, item in enumerate(raw_sections):
        key = str(getattr(item, "key", "") or "").strip()
        label = str(getattr(item, "value", "") or "").strip()
        if not key and isinstance(item, dict):
            key = str(item.get("key", "")).strip()
            label = str(item.get("value", "")).strip()
        section_id = _normalize_section_id(key, fallback=f"section_{idx + 1}")
        section_label = label or _section_label(section_id)
        if section_id in seen_ids:
            continue
        seen_ids.add(section_id)
        output.append({"id": section_id, "label": section_label})
    return output


def _llm_refine_section_catalog(
    screen_summaries: Sequence[str], base_sections: Sequence[Dict[str, str]]
) -> Optional[List[Dict[str, str]]]:
    llms = _load_llms_module()
    if not llms or not screen_summaries or not base_sections:
        return None
    prompt = _prompt_str(
        "navigation_sections_catalog_system_prompt",
        (
            "Improve the section list used for interview navigation. "
            "Return JSON with key `sections`: array of objects with `id` and `label`. "
            "Keep 3 to 8 sections, use concise plain-language labels, and keep legal flow order."
        ),
    )
    user_message = (
        "Current sections:\n"
        + json.dumps(list(base_sections), ensure_ascii=True)
        + "\n\nScreens:\n"
        + "\n".join(screen_summaries)
    )
    try:
        rewritten = llms.chat_completion(
            system_message=prompt,
            user_message=user_message,
            json_mode=True,
            model="gpt-5-mini",
        )
        if not isinstance(rewritten, dict):
            return None
        candidate = rewritten.get("sections")
        if not isinstance(candidate, list):
            return None
        cleaned: List[Dict[str, str]] = []
        seen_ids: Set[str] = set()
        for idx, item in enumerate(candidate):
            if not isinstance(item, dict):
                continue
            section_id = _normalize_section_id(
                str(item.get("id", "") or ""), fallback=f"section_{idx + 1}"
            )
            if section_id in seen_ids:
                continue
            seen_ids.add(section_id)
            label = str(item.get("label", "") or "").strip() or _section_label(
                section_id
            )
            cleaned.append({"id": section_id, "label": label})
        if 3 <= len(cleaned) <= 8:
            return cleaned
        return None
    except Exception:
        return None


def _llm_refine_section_ids(
    screen_summaries: Sequence[str],
    section_ids: Sequence[str],
    deterministic: Sequence[str],
) -> Optional[List[str]]:
    llms = _load_llms_module()
    if not llms or not screen_summaries:
        return None
    allowed = sorted(set(section_ids))
    prompt = _prompt_str(
        "navigation_sections_system_prompt",
        (
            "Assign each screen to one section id to improve navigation. "
            "Return JSON with key `section_ids` as an array of ids with exactly one id per screen. "
            "Use only allowed ids and keep legal flow logical."
        ),
    )
    user_message = (
        "Allowed section ids:\n- "
        + "\n- ".join(allowed)
        + "\n\nScreens with deterministic section:\n"
        + "\n".join(screen_summaries)
        + "\n\nCurrent deterministic section_ids:\n"
        + json.dumps(list(deterministic))
    )
    try:
        rewritten = llms.chat_completion(
            system_message=prompt,
            user_message=user_message,
            json_mode=True,
            model="gpt-5-mini",
        )
        if not isinstance(rewritten, dict):
            return None
        candidate = rewritten.get("section_ids")
        if not isinstance(candidate, list) or len(candidate) != len(deterministic):
            return None
        cleaned = [str(item) for item in candidate]
        if any(item not in allowed for item in cleaned):
            return None
        return cleaned
    except Exception:
        return None


def _navigation_sections_and_assignments(
    interview: DAInterview,
    screens: Sequence[Union["DAQuestion", "DAField"]],
    trigger_lines: Sequence[str],
) -> Tuple[List[Dict[str, str]], List[str]]:
    if (
        hasattr(interview, "enable_navigation")
        and getattr(interview, "enable_navigation") is False
    ):
        return [], ["" for _ in screens]

    deterministic_ids = [
        _deterministic_section_id_for_screen(
            screen, trigger_lines[idx] if idx < len(trigger_lines) else ""
        )
        for idx, screen in enumerate(screens)
    ]
    deterministic_ids = [item if item else "case_details" for item in deterministic_ids]

    summaries = [
        f"{idx}. title={_screen_heading(screen)!r}; trigger={trigger_lines[idx] if idx < len(trigger_lines) else ''!r}; section={deterministic_ids[idx]}"
        for idx, screen in enumerate(screens)
    ]

    frontend_sections = _sections_from_frontend(interview)
    if frontend_sections:
        section_catalog = frontend_sections
    else:
        ordered_base_ids: List[str] = []
        for section_id in deterministic_ids:
            if section_id not in ordered_base_ids:
                ordered_base_ids.append(section_id)
        section_catalog = [
            {"id": section_id, "label": _section_label(section_id)}
            for section_id in ordered_base_ids
        ]

    llm_enabled = bool(getattr(interview, "use_llm_assist", False))
    if llm_enabled:
        refined_catalog = _llm_refine_section_catalog(summaries, section_catalog)
        if refined_catalog:
            section_catalog = refined_catalog

    allowed_ids = [section["id"] for section in section_catalog]
    if not allowed_ids:
        allowed_ids = ["case_details"]
        section_catalog = [{"id": "case_details", "label": "Case Details"}]
    fallback_section_id = (
        "case_details" if "case_details" in allowed_ids else allowed_ids[0]
    )
    seeded_ids = [
        section_id if section_id in allowed_ids else fallback_section_id
        for section_id in deterministic_ids
    ]
    llm_ids: Optional[List[str]] = None
    if llm_enabled:
        llm_ids = _llm_refine_section_ids(
            screen_summaries=summaries,
            section_ids=allowed_ids,
            deterministic=seeded_ids,
        )
    assigned = llm_ids or seeded_ids

    # Collapse rapid jitter to avoid noisy section changes.
    smoothed: List[str] = []
    for idx, section_id in enumerate(assigned):
        if idx > 0 and idx < len(assigned) - 1:
            if assigned[idx - 1] == assigned[idx + 1] != section_id:
                smoothed.append(assigned[idx - 1])
                continue
        smoothed.append(section_id)

    # Keep section flow forward-moving for cleaner navigation.
    canonical_order = {
        "about_you": 0,
        "people": 1,
        "case_details": 2,
        "service_and_notice": 3,
        "sign_and_submit": 4,
    }
    monotonic: List[str] = []
    highest_rank = -1
    for section_id in smoothed:
        rank = canonical_order.get(section_id, highest_rank if highest_rank >= 0 else 0)
        if rank < highest_rank:
            # Prevent jumping backwards to earlier sections.
            kept = next(
                (
                    sid
                    for sid, sid_rank in canonical_order.items()
                    if sid_rank == highest_rank
                ),
                section_id,
            )
            monotonic.append(kept)
        else:
            monotonic.append(section_id)
            highest_rank = rank

    sections = list(section_catalog)
    return sections, monotonic


def _ensure_question_block_ids(yaml_text: str) -> str:
    """Add deterministic ids to question blocks that are missing an id."""
    docs = re.split(r"(?m)^---\s*$", yaml_text)
    updated_docs: List[str] = []
    generated_counter = 1

    for raw_doc in docs:
        doc_text = raw_doc
        if not doc_text.strip():
            updated_docs.append(doc_text)
            continue
        has_top_level_id = re.search(r"(?m)^id:\s*", doc_text) is not None
        has_question = re.search(r"(?m)^question:\s*", doc_text) is not None
        if not has_top_level_id and has_question:
            title = ""
            question_match = re.search(r"(?m)^question:\s*(.*)$", doc_text)
            if question_match:
                first_value = (question_match.group(1) or "").strip()
                if first_value and not first_value.startswith(("|", ">")):
                    title = first_value
                else:
                    after = doc_text[question_match.end() :]
                    for line in after.splitlines():
                        if not line.strip():
                            continue
                        if line.startswith((" ", "\t")):
                            stripped = line.strip()
                            if stripped and not stripped.startswith("#"):
                                title = stripped
                                break
                        else:
                            break
            title = title or f"auto generated screen {generated_counter}"
            generated_counter += 1
            id_line = f"id: {fix_id(title)}\n"
            # Insert before the first top-level key when possible.
            first_key = re.search(r"(?m)^[A-Za-z_][A-Za-z0-9_ ]*:\s*", doc_text)
            if first_key:
                doc_text = (
                    doc_text[: first_key.start()]
                    + id_line
                    + doc_text[first_key.start() :]
                )
            else:
                doc_text = id_line + doc_text
        updated_docs.append(doc_text)

    return "---\n".join(updated_docs)


def _ensure_unique_question_ids(yaml_text: str) -> str:
    """Ensure top-level `id:` values are unique by appending a numeric suffix."""
    lines = yaml_text.splitlines()
    seen: Dict[str, int] = {}
    in_metadata = False

    for idx, line in enumerate(lines):
        if line.strip() == "metadata:":
            in_metadata = True
            continue
        if in_metadata and line.strip() == "---":
            in_metadata = False
            continue
        if in_metadata:
            continue
        if not line.startswith("id: "):
            continue
        raw_id = line[4:].strip()
        if not raw_id:
            continue
        count = seen.get(raw_id, 0) + 1
        seen[raw_id] = count
        if count > 1:
            lines[idx] = f"id: {raw_id} {count}"
    output = "\n".join(lines)
    return output + ("\n" if yaml_text.endswith("\n") else "")


def _ensure_required_metadata_values(yaml_text: str, interview: DAInterview) -> str:
    """Ensure required metadata fields are present and non-empty for lint."""
    defaults = _metadata_defaults_for_lint(interview)
    lines = yaml_text.splitlines()
    metadata_start = None
    for idx, line in enumerate(lines):
        if line.strip() == "metadata:":
            metadata_start = idx
            break
    if metadata_start is None:
        return yaml_text
    metadata_end = len(lines)
    for idx in range(metadata_start + 1, len(lines)):
        if lines[idx].strip() == "---" and not lines[idx].startswith(" "):
            metadata_end = idx
            break

    block = lines[metadata_start:metadata_end]
    block_text = "\n".join(block)

    # Ensure a non-empty jurisdiction scalar.
    if re.search(r"(?m)^\s{2}jurisdiction:\s*(\"\"|''|\s*)$", block_text):
        block_text = re.sub(
            r"(?m)^\s{2}jurisdiction:\s*(?:\"\"|''|\s*)$",
            f'  jurisdiction: "{escape_double_quoted_yaml(defaults["jurisdiction"])}"',
            block_text,
            count=1,
        )
    elif re.search(r"(?m)^\s{2}jurisdiction:\s*", block_text) is None:
        block_text += (
            f'\n  jurisdiction: "{escape_double_quoted_yaml(defaults["jurisdiction"])}"'
        )

    # Ensure a non-empty landing_page_url scalar.
    landing_scalar_missing = re.search(
        r"(?m)^\s{2}landing_page_url:\s*(\"\"|''|\s*)$", block_text
    )
    if landing_scalar_missing:
        block_text = re.sub(
            r"(?m)^\s{2}landing_page_url:\s*(?:\"\"|''|\s*)$",
            f'  landing_page_url: "{escape_double_quoted_yaml(defaults["landing_page_url"])}"',
            block_text,
            count=1,
        )
    elif re.search(r"(?m)^\s{2}landing_page_url:\s*", block_text) is None:
        block_text += f'\n  landing_page_url: "{escape_double_quoted_yaml(defaults["landing_page_url"])}"'

    # Ensure LIST_topics exists and has at least one value.
    list_topics_inline_empty = re.search(
        r"(?m)^\s{2}LIST_topics:\s*(\[\s*\]|\"\"|''|\s*)$", block_text
    )
    if list_topics_inline_empty:
        block_text = re.sub(
            r"(?m)^\s{2}LIST_topics:\s*(?:\[\s*\]|\"\"|''|\s*)$",
            f'  LIST_topics:\n    - "{defaults["default_topic"]}"',
            block_text,
            count=1,
        )
    elif re.search(r"(?m)^\s{2}LIST_topics:\s*$", block_text):
        list_topics_match = re.search(
            r"(?ms)^  LIST_topics:\s*\n((?:    .*\n?)*)", block_text
        )
        list_topics_body = list_topics_match.group(1) if list_topics_match else ""
        has_list_item = re.search(r"(?m)^    -\s+\S", list_topics_body) is not None
        if not has_list_item:
            block_text = re.sub(
                r"(?m)^  LIST_topics:\s*$",
                f'  LIST_topics:\n    - "{defaults["default_topic"]}"',
                block_text,
                count=1,
            )
    elif re.search(r"(?m)^\s{2}LIST_topics:\s*", block_text) is None:
        block_text += f'\n  LIST_topics:\n    - "{defaults["default_topic"]}"'

    new_lines = lines[:metadata_start] + block_text.splitlines() + lines[metadata_end:]
    return "\n".join(new_lines) + ("\n" if yaml_text.endswith("\n") else "")


def _lint_with_aldashboard_interview_linter(
    yaml_text: str,
    include_llm: bool = False,
) -> Optional[Dict[str, Any]]:
    try:
        from docassemble.ALDashboard.interview_linter import lint_interview_content

        return cast(
            Dict[str, Any],
            lint_interview_content(yaml_text, include_llm=include_llm),
        )
    except Exception as exc:
        log(f"ALDashboard interview linter unavailable for local repair: {exc!r}")
        return None


def _llm_rewrite_for_plain_language(text: str) -> str:
    llms = _load_llms_module()
    if not llms or not text.strip():
        return text
    if "${" in text or "<%text>" in text or "% if" in text:
        return text
    try:
        rewritten = llms.chat_completion(
            system_message=(
                "Rewrite the text in plain, respectful language at about 6th-grade reading level. "
                "Preserve legal meaning. Keep similar length. Return JSON with key `rewrite`."
            ),
            user_message=text,
            json_mode=True,
            model="gpt-5-mini",
        )
        if isinstance(rewritten, dict):
            candidate = str(rewritten.get("rewrite", "") or "").strip()
            if candidate:
                return candidate
    except Exception:
        pass
    return text


def _apply_plain_language_repairs(yaml_text: str, max_rewrites: int = 8) -> str:
    lint_result = _lint_with_aldashboard_interview_linter(yaml_text, include_llm=True)
    if not lint_result:
        return yaml_text
    findings = lint_result.get("findings", []) or []
    candidates: List[str] = []
    for finding in findings:
        if finding.get("source") != "llm":
            continue
        rule_id = str(finding.get("rule_id", ""))
        if rule_id not in {"tone-and-respect", "plain-language-rewrite-opportunities"}:
            continue
        problematic_text = str(finding.get("problematic_text", "") or "").strip()
        if not problematic_text or len(problematic_text) < 8:
            continue
        if problematic_text not in candidates:
            candidates.append(problematic_text)

    updated = yaml_text
    rewrite_count = 0
    for original in sorted(candidates, key=len, reverse=True):
        if rewrite_count >= max_rewrites:
            break
        if original not in updated:
            continue
        rewritten = _llm_rewrite_for_plain_language(original)
        if not rewritten or rewritten == original:
            continue
        updated = updated.replace(original, rewritten, 1)
        rewrite_count += 1
    return updated


def _repair_generated_yaml_with_lint(
    yaml_text: str, interview: DAInterview, max_passes: int = 3
) -> str:
    """Generate-then-repair loop using deterministic lint fixes."""
    updated = yaml_text
    # Always enforce ID uniqueness, even when lint is unavailable.
    updated = _ensure_unique_question_ids(updated)
    for _ in range(max_passes):
        lint_result = _lint_with_aldashboard_interview_linter(updated)
        if not lint_result:
            break
        findings = lint_result.get("findings", []) or []
        red_rules = {
            str(finding.get("rule_id"))
            for finding in findings
            if str(finding.get("severity")) == "red"
        }
        if not red_rules:
            break
        before = updated
        if "missing-question-id" in red_rules:
            updated = _ensure_question_block_ids(updated)
        if "missing-metadata-fields" in red_rules:
            updated = _ensure_required_metadata_values(updated, interview)
        updated = _ensure_unique_question_ids(updated)
        if updated == before:
            break
    # Optional readability/tone cleanup as a second try only when lint still fails.
    final_lint = _lint_with_aldashboard_interview_linter(updated)
    has_red_failures = bool(
        final_lint
        and any(
            str(finding.get("severity")) == "red"
            for finding in (final_lint.get("findings", []) or [])
        )
    )
    if has_red_failures:
        updated = _apply_plain_language_repairs(updated)
    updated = _ensure_unique_question_ids(updated)
    return updated


def _render_interview_yaml(
    interview: DAInterview,
    include_download_screen: bool,
    output_mako_choice: str,
    objects: Optional[List[Any]] = None,
    screen_reordered: Optional[List[Any]] = None,
) -> str:
    try:
        from . import __version__
    except ImportError:
        __version__ = "0.0.0"
    from .custom_values import get_yml_deps_from_choices
    from docassemble.base.util import (
        action_button_html,
        currency,
        indent,
        single_paragraph,
        showifdef,
        today,
        url_action,
        word,
        yesno,
    )

    output_defs_path = _resolve_template_path("output_defs.mako")
    output_mako_ref = get_output_mako_package_and_path(output_mako_choice)
    output_mako_path = _resolve_template_path(output_mako_ref)
    with open(output_defs_path, "r", encoding="utf-8") as defs_handle:
        output_defs_text = defs_handle.read()
    with open(output_mako_path, "r", encoding="utf-8") as mako_handle:
        output_mako_text = mako_handle.read()

    template_text = output_defs_text + "\n" + output_mako_text
    # This mako template is making a docassemble YAML, so it's not directly at risk of XSS injection.
    template = mako.template.Template(
        template_text, input_encoding="utf-8"
    )  # nosec B702

    if screen_reordered is None:
        # The interview order block needs both the authored question screens and any
        # built-in fields (e.g., users.gather(), docket_number) so the generated
        # interview actually asks for values it references in review/download screens.
        # `draft_screen_order()` includes built-ins and signatures in a sensible order.
        screen_reordered = list(interview.draft_screen_order())
    for question in screen_reordered:
        if isinstance(question, DAQuestion) and not hasattr(question, "type"):
            question.type = "question"
    screen_reordered = [
        screen for screen in screen_reordered if _is_renderable_question_screen(screen)
    ]
    render_questions = [
        question
        for question in interview.questions
        if _is_renderable_question_screen(question)
    ]

    screen_triggers: List[str] = []
    for screen in screen_reordered:
        if (
            isinstance(screen, DAQuestion)
            and screen.type == "question"
            and (
                screen.needs_continue_button_field
                or (hasattr(screen, "field_list") and screen.field_list)
            )
        ):
            if screen.needs_continue_button_field:
                screen_triggers.append(varname(screen.question_text))
            else:
                screen_triggers.append(
                    screen.field_list[0].trigger_gather(
                        custom_plurals=interview.all_fields.custom_people_plurals.values()
                    )
                )
        else:
            screen_triggers.append(
                screen.trigger_gather(
                    custom_plurals=interview.all_fields.custom_people_plurals.values()
                )
            )
    navigation_sections, section_assignments = _navigation_sections_and_assignments(
        interview, screen_reordered, screen_triggers
    )
    interview_order_lines = interview.questions.interview_order_list(
        interview.all_fields,
        screen_reordered,
        sections=section_assignments,
    )

    context = {
        "interview": interview,
        "render_questions": render_questions,
        "objects": objects or [],
        "generate_download_screen": include_download_screen,
        "screen_reordered": screen_reordered,
        "navigation_sections": navigation_sections,
        "interview_order_lines": interview_order_lines,
        "package_version_number": __version__,
        "action_button_html": action_button_html,
        "currency": currency,
        "indent": indent,
        "showifdef": showifdef,
        "today": today,
        "url_action": url_action,
        "word": word,
        "yesno": yesno,
        "single_paragraph": single_paragraph,
        "escape_double_quoted_yaml": escape_double_quoted_yaml,
        "oneline": oneline,
        "indent_by": indent_by,
        "base_name": base_name,
        "using_string": using_string,
        "fix_id": fix_id,
        "varname": varname,
        "remove_multiple_appearance_indicator": remove_multiple_appearance_indicator,
        "get_yml_deps_from_choices": get_yml_deps_from_choices,
    }
    yaml_text = template.render(**context)
    return _repair_generated_yaml_with_lint(yaml_text, interview)


def _assign_next_steps_template(interview: DAInterview) -> None:
    template_map = {
        "starts_case": "next_steps_starts_case.docx",
        "existing_case": "next_steps_existing_case.docx",
        "appeal": "next_steps_appeal.docx",
        "letter": "next_steps_letter.docx",
        "other_form": "next_steps_other_form.docx",
        "other": "next_steps_other.docx",
    }
    template_name = template_map.get(interview.form_type, "next_steps_other.docx")
    template_path = _resolve_template_path(template_name)
    instructions_filename = f"{interview.interview_label}_next_steps.docx"
    interview.instructions = _LocalFile(
        path=template_path, filename=instructions_filename
    )


class _LocalFile:
    def __init__(self, path: str, filename: Optional[str] = None):
        self._path = path
        self.filename = filename or os.path.basename(path)

    def path(self):
        return self._path


class _LocalDAFileAdapter:
    def __init__(self, path: str):
        self._path = path
        self.filename = os.path.basename(path)

    def initialize(self, filename: Optional[str] = None, **kwargs):
        if filename:
            self.filename = filename
            self._path = os.path.join(os.path.dirname(self._path), filename)
        os.makedirs(os.path.dirname(self._path), exist_ok=True)

    def path(self):
        return self._path

    def commit(self):
        return None


def generate_interview_artifacts(
    interview: DAInterview,
    *,
    include_download_screen: bool = True,
    create_package_archive: bool = True,
    output_mako_choice: Optional[str] = None,
    yaml_output_file: Optional[Any] = None,
    package_output_file: Optional[Any] = None,
) -> WeaverInterviewArtifacts:
    yaml_filename = f"{interview.interview_label}.yml"
    chosen_output_mako_raw = output_mako_choice
    if chosen_output_mako_raw is None:
        chosen_output_mako_raw = getattr(
            interview,
            "output_mako_choice",
            "Default configuration:standard AssemblyLine",
        )
    chosen_output_mako = (
        chosen_output_mako_raw
        if isinstance(chosen_output_mako_raw, str)
        else "Default configuration:standard AssemblyLine"
    )
    yaml_text = _render_interview_yaml(
        interview=interview,
        include_download_screen=include_download_screen,
        output_mako_choice=chosen_output_mako,
        objects=[],
        screen_reordered=None,
    )

    yaml_file = yaml_output_file or DAFile(filename=yaml_filename)
    yaml_file.initialize(filename=yaml_filename)
    with open(yaml_file.path(), "w", encoding="utf-8") as handle:
        handle.write(yaml_text)
    yaml_file.commit()

    package_file = None
    if create_package_archive:
        include_next_steps = getattr(interview, "include_next_steps", True)
        if include_next_steps and not hasattr(interview, "instructions"):
            _assign_next_steps_template(interview)

        folders_and_files = {
            "questions": [yaml_file],
            "modules": [],
            "static": [],
            "sources": [],
            "templates": [],
        }
        if include_download_screen:
            if include_next_steps and hasattr(interview, "instructions"):
                folders_and_files["templates"] = [interview.instructions] + list(
                    interview.uploaded_templates
                )
            else:
                folders_and_files["templates"] = list(interview.uploaded_templates)

        package_info = interview.package_info()
        if interview.author and str(interview.author).splitlines():
            default_vals = {
                "author name and email": str(interview.author).splitlines()[0]
            }
            package_info["author_name"] = default_vals["author name and email"]
        else:
            default_vals = {"author name and email": "author@example.com"}

        package_file = create_package_zip(
            interview.package_title,
            package_info,
            default_vals,
            folders_and_files,
            fileobj=package_output_file,
        )

    return WeaverInterviewArtifacts(
        yaml_text=yaml_text, yaml_file=yaml_file, package_file=package_file
    )


def generate_interview_from_path(
    input_path: str,
    *,
    output_dir: Optional[str] = None,
    title: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    categories: Optional[str] = None,
    default_country_code: str = "US",
    output_mako_choice: str = "Default configuration:standard AssemblyLine",
    create_package_zip: bool = True,
    include_next_steps: bool = True,
    include_download_screen: bool = True,
    interview_overrides: Optional[Dict[str, Any]] = None,
    field_definitions: Optional[List[FieldDefinition]] = None,
    screen_definitions: Optional[List[Screen]] = None,
) -> WeaverGenerationResult:
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Template file not found: {input_path}")
    _ensure_current_question_package()
    da_file = _make_static_file_from_path(input_path)

    merged_screens = None
    if screen_definitions:
        merged_screens = _merge_field_definitions_into_screens(
            screen_definitions, field_definitions
        )

    interview = DAInterview()
    interview.auto_assign_attributes(
        input_file=da_file,
        title=title,
        jurisdiction=jurisdiction,
        categories=categories,
        default_country_code=default_country_code,
        screens=merged_screens,
    )

    interview.output_mako_choice = output_mako_choice
    interview.include_next_steps = include_next_steps

    if interview_overrides:
        for key, value in interview_overrides.items():
            setattr(interview, key, value)

    if not hasattr(interview, "categories"):
        interview.categories = DADict(elements={}, auto_gather=False, gathered=True)
    if not hasattr(interview, "has_other_categories"):
        interview.has_other_categories = False
    if not hasattr(interview, "other_categories"):
        interview.other_categories = ""
    if not hasattr(interview, "original_form"):
        interview.original_form = ""
    if not hasattr(interview, "help_page_url"):
        interview.help_page_url = ""
    if not hasattr(interview, "help_page_title"):
        interview.help_page_title = ""
    if not hasattr(interview, "state"):
        interview.state = ""
    if not hasattr(interview, "landing_page_url"):
        interview.landing_page_url = ""
    if not hasattr(interview, "efiling_enabled"):
        interview.efiling_enabled = False
    if not hasattr(interview, "integrated_efiling"):
        interview.integrated_efiling = False
    if not hasattr(interview, "integrated_email_filing"):
        interview.integrated_email_filing = False
    if not hasattr(interview, "requires_notarization"):
        interview.requires_notarization = False
    if not hasattr(interview, "unlisted"):
        interview.unlisted = False
    if not hasattr(interview, "footer"):
        interview.footer = ""
    if not hasattr(interview, "when_you_are_finished"):
        interview.when_you_are_finished = ""

    added_fields = _apply_field_definitions_to_interview(interview, field_definitions)
    for field in interview.all_fields:
        if (
            hasattr(field, "field_type")
            and field.field_type
            in [
                "multiple choice radio",
                "multiple choice checkboxes",
                "multiple choice dropdown",
                "multiple choice combobox",
                "multiselect",
            ]
            and not hasattr(field, "choices")
        ):
            if hasattr(field, "choice_options"):
                field.choices = "\n".join(field.choice_options)
            else:
                field.choices = ""
    if screen_definitions:
        for screen in merged_screens or []:
            for field_entry in screen.get("fields", []) or []:
                field_name = field_entry.get("field")
                if field_name:
                    _ensure_field_in_interview(interview, field_name)
    elif added_fields:
        interview.auto_group_fields()

    interview_label = varname(interview.title)
    if not interview_label:
        interview_label = varname("ending_variable_" + interview.title)
    interview.interview_label = interview_label.lower()

    if include_next_steps:
        _assign_next_steps_template(interview)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        yaml_path = os.path.join(output_dir, f"{interview.interview_label}.yml")
    else:
        tmp_dir = tempfile.mkdtemp()
        yaml_path = os.path.join(tmp_dir, f"{interview.interview_label}.yml")
    yaml_output_file = _LocalDAFileAdapter(yaml_path)

    package_output_file = None
    if create_package_zip:
        if output_dir:
            package_zip_path = os.path.join(
                output_dir, f"docassemble-{interview.package_title}.zip"
            )
        else:
            package_zip_path = os.path.join(
                os.path.dirname(yaml_path),
                f"docassemble-{interview.package_title}.zip",
            )
        package_output_file = _LocalDAFileAdapter(package_zip_path)
    else:
        package_zip_path = None

    artifacts = generate_interview_artifacts(
        interview=interview,
        include_download_screen=include_download_screen,
        create_package_archive=create_package_zip,
        output_mako_choice=output_mako_choice,
        yaml_output_file=yaml_output_file,
        package_output_file=package_output_file,
    )

    yaml_path = artifacts.yaml_file.path()
    if artifacts.package_file:
        package_zip_path = artifacts.package_file.path()

    return WeaverGenerationResult(
        yaml_text=artifacts.yaml_text,
        yaml_path=yaml_path,
        package_zip_path=package_zip_path,
    )

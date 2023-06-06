from .custom_values import get_matching_deps
from .generator_constants import generator_constants
from .validate_template_files import matching_reserved_names, has_fields
from collections import defaultdict
from dataclasses import field
from docassemble.base.util import (
    bold,
    comma_list,
    comma_and_list,
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
    pdf_concatenate,
    space_to_underscore,
    user_info,
    user_logged_in,
)
from docx2python import docx2python
from enum import Enum
from itertools import zip_longest, chain
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSEOF
from pikepdf import Pdf
from typing import Any, Dict, List, Optional, Set, Tuple, Union, Iterable, Literal
from urllib.parse import urlparse
from zipfile import BadZipFile
import ast
import ast
import datetime
import docassemble.base.functions
import docassemble.base.parse
import docassemble.base.pdftk
import formfyxer
import mako.runtime
import mako.template
import more_itertools
import os
import re
import uuid
import zipfile
import spacy

mako.runtime.UNDEFINED = DAEmpty()


def formfyxer_available():
    if get_config("assembly line", {}).get("tools.suffolklitlab.org api key"):
        return True
    return spacy.util.is_package("en_core_web_lg")


TypeType = type(type(None))

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
    "formfyxer_available",
    "get_character_limit",
    "get_court_choices",
    "get_docx_validation_errors",
    "get_docx_variables",
    "get_fields",
    "get_pdf_validation_errors",
    "get_pdf_variable_name_matches",
    "get_variable_name_warnings",
    "indent_by",
    "install_spacy_model",
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


def install_spacy_model(model="en_core_web_lg"):
    if not spacy.util.is_package(model):
        spacy.cli.download(model)


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

        field_questions.append(
            {
                "note": f"""
                                <h2 class="h5 prompt-heading">{self.final_display_var}</h2>
                                """
            }
        )
        field_questions.append(
            {
                "label": f"Prompt",
                # "label above field": True,
                "field": self.attr_name("label"),
                "default": self.variable_name_guess,
            }
        )
        field_questions.append(
            {
                "label": f"Type",
                # "label above field": True,
                "field": self.attr_name("field_type"),
                "code": "field_type_options()",
                "default": self.field_type_guess
                if hasattr(self, "field_type_guess")
                else None,
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
                "default": "\n".join(
                    [
                        f"{opt.capitalize().replace('_', ' ')}: {opt}"
                        for opt in self.choice_options
                    ]
                )
                if hasattr(self, "choice_options")
                else None,
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
        if re.search("previous_names\[\d\]$", self.final_display_var):
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

    def find_parent_collections(self) -> List[ParentCollection]:
        """Gets all of the individual ParentCollections from the DAFields in this list."""
        parent_coll_map = defaultdict(list)
        for field in self.elements:
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
                        possible_suffix = re.sub("^\[\d+\]", "", matches.groups()[1])
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
        candidates = self.get_person_candidates()
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
        self.field_list = DAFieldList()

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
        sections: Optional[List] = None,
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
        for index, question in enumerate(screens):
            if set_progress and index and index % screen_divisor == 0:
                progress += increment
                logic_list.append(f"set_progress({int(progress)})")
            if isinstance(question, DAQuestion) and question.type == "question":
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

        return list(more_itertools.unique_everseen(logic_list))


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
        return re.sub("\W|_", "", self.interview_label.title())

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
            folders_and_files["templates"] = [
                self.instructions
            ] + self.uploaded_templates
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

    def auto_assign_attributes(
        self,
        url: Optional[str] = None,
        input_file: Optional[Union[DAFileList, DAFile, DAStaticFile]] = None,
        title: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        categories: Optional[str] = None,
        default_country_code: str = "US",
    ):
        """
        Automatically assign interview attributes based on the template
        assigned to the interview object.
        To assist with "I'm feeling lucky" button.
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
        self.title = self._set_title(url=url, input_file=input_file)

        if title:
            self.title = title
        self.short_title = self.title
        self.description = self.title
        self.short_filename_with_spaces = self.title
        self.short_filename = space_to_underscore(
            varname(self.short_filename_with_spaces)
        )

        if jurisdiction:
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
        self.allowed_courts = DADict(auto_gather=False, gathered=True)
        self.default_country_code = default_country_code
        self.output_mako_choice = "Default configuration:standard AssemblyLine"
        self._auto_load_fields()
        self.all_fields.auto_label_fields()
        self.all_fields.auto_mark_people_as_builtins()
        self.auto_group_fields()

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
        self.uploaded_templates = input_file.copy_deep(
            self.attr_name("uploaded_templates")
        )

    def _guess_posture(self, title: str):
        """
        Guess posture of the case using simple heuristics
        """
        title = title.lower()
        if "petition" in title or "complaint" in title:
            return "starts_case"
        if "motion" in title:
            return "existing_case"
        if "appeal" in title or "appellate" in title:
            return "appeal"
        if "letter" in title:
            return "letter"
        if "form" in title:
            return "other_form"
        return "other"

    def _guess_intro_prompt(self, title: str):
        if self.form_type == "starts_case":
            return "Ask the court for a " + title
        elif self.form_type == "existing_case":
            return "File a " + title
        elif self.form_type == "letter":
            return "Write a " + title
        return "Get a " + title

    def _guess_role(self, title: str):
        """
        Guess role from the form's title, using some simple heuristics.
        """
        title = title.lower()
        if "answer" in title:
            return "defendant"
        if "complaint" in title or "petition" in title:
            return "plaintiff"
        if "defendant" in title or "respondent" in title:
            return "defendant"
        if "plaintiff" in title or "probate" in title or "guardian" in title:
            return "plaintiff"

        return "unknown"

    def _null_group_fields(self):
        return {"Screen 1": [field.variable for field in self.all_fields.custom()]}

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
        except:
            log(
                f"Auto field grouping failed. Tried using tools.suffolklitlab.org api key {get_config('assembly line',{}).get('tools.suffolklitlab.org api key', None)}"
            )
            field_grouping = self._null_group_fields()
        self.questions.auto_gather = False
        for group in field_grouping:
            new_screen = self.questions.appendObject()
            new_screen.is_informational_screen = False
            new_screen.has_mandatory_field = True
            new_screen.question_text = (
                next(iter(field_grouping[group]), "").capitalize().replace("_", " ")
            )
            new_screen.subquestion_text = ""
            new_screen.field_list = [
                field
                for field in self.all_fields
                if field.variable in field_grouping[group]
            ]
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
    return re.search(r"^(" + "|".join(prefixes) + ")(\d*)(.*)", label)


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
                        [n.replace("`", "\`") for n in field.raw_field_names]
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

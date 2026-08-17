# do not pre-load
"""Grouping PDF checkboxes into one multiple-choice question.

A form that offers three ways to serve papers usually has three separate
checkboxes. Naming them `service_method+by_mail`, `service_method+in_hand` and
`service_method+by_email` tells the Weaver they are one question, so the
interview asks once and the attachment ticks the right box.

`+` is not legal in a Python identifier, so it can never be mistaken for part
of a variable name.
"""

import os
import unittest
from pathlib import Path

from .interview_generator import (
    DAField,
    DAFieldList,
    option_label,
    split_option_field_name,
)
from docassemble.base.util import DAStaticFile
import docassemble.base.functions


class MockDAStaticFile(DAStaticFile):
    def init(self, *pargs, **kwargs):
        self.full_path = str(kwargs.pop("full_path"))
        kwargs["filename"] = os.path.basename(self.full_path)
        kwargs["extension"] = "pdf"
        kwargs["mimetype"] = "application/pdf"
        super().init(*pargs, **kwargs)

    def path(self):
        return self.full_path


class TestSplitOptionFieldName(unittest.TestCase):
    def test_splits_on_the_first_plus(self):
        self.assertEqual(
            split_option_field_name("service_method+by_mail"),
            ("service_method", "by_mail"),
        )

    def test_later_pluses_belong_to_the_option(self):
        self.assertEqual(
            split_option_field_name("relief+rent+and+utilities"),
            ("relief", "rentandutilities"),
        )

    def test_ordinary_names_are_not_option_fields(self):
        self.assertIsNone(split_option_field_name("users1_name_first"))
        self.assertIsNone(split_option_field_name("docket_number"))

    def test_a_missing_half_is_not_a_grouping(self):
        self.assertIsNone(split_option_field_name("+by_mail"))
        self.assertIsNone(split_option_field_name("service_method+"))

    def test_multiple_appearance_indicators_are_stripped(self):
        self.assertEqual(
            split_option_field_name("service_method__2+by_mail"),
            ("service_method", "by_mail"),
        )

    def test_option_labels_are_readable(self):
        self.assertEqual(option_label("by_mail"), "By mail")


class TestOptionGroupFields(unittest.TestCase):
    @staticmethod
    def _fields_from(*raw_field_names):
        fields = DAFieldList()
        for raw_field_name in raw_field_names:
            field = fields.appendObject()
            field.source_document_type = "pdf"
            field.fill_in_pdf_attributes(
                (raw_field_name, "", 0, [0, 0, 100, 20], "/Btn", "On"), {}
            )
        fields.consolidate_options()
        fields.gathered = True
        return fields

    def test_options_collapse_into_one_field(self):
        fields = self._fields_from(
            "service_method+by_mail",
            "service_method+in_hand",
            "docket_number",
        )
        by_variable = {field.variable: field for field in fields}
        self.assertEqual(sorted(by_variable), ["docket_number", "service_method"])
        service_method = by_variable["service_method"]
        self.assertEqual(service_method.field_type_guess, "multiple choice radio")
        self.assertEqual(service_method.choice_options, ["by_mail", "in_hand"])
        self.assertEqual(
            service_method.raw_field_names,
            ["service_method+by_mail", "service_method+in_hand"],
        )

    def test_separate_parents_stay_separate(self):
        fields = self._fields_from(
            "service_method+by_mail", "relief_sought+rent", "relief_sought+utilities"
        )
        self.assertEqual(
            sorted(field.variable for field in fields),
            ["relief_sought", "service_method"],
        )

    def test_choices_get_readable_labels(self):
        fields = self._fields_from("service_method+by_mail", "service_method+in_hand")
        self.assertEqual(
            fields[0].choices_string(), "By mail: by_mail\nIn hand: in_hand"
        )

    def test_single_answer_questions_compare_against_the_choice(self):
        fields = self._fields_from("service_method+by_mail", "service_method+in_hand")
        field = fields[0]
        self.assertEqual(
            field.option_fill_expression("service_method+by_mail"),
            "service_method == 'by_mail'",
        )

    def test_multi_answer_questions_read_their_own_key(self):
        fields = self._fields_from("relief_sought+rent", "relief_sought+utilities")
        field = fields[0]
        field.field_type = "multiple choice checkboxes"
        self.assertEqual(
            field.option_fill_expression("relief_sought+rent"),
            "relief_sought['rent']",
        )

    def test_ordinary_fields_are_not_option_groups(self):
        fields = self._fields_from("docket_number")
        self.assertFalse(fields[0].is_option_group())

    def test_parent_name_still_maps_to_assemblyline_variables(self):
        """Only the half before the `+` is a variable name, so it still maps."""
        fields = self._fields_from(
            "user_address_county+suffolk", "user_address_county+norfolk"
        )
        self.assertEqual(fields[0].final_display_var, "users[0].address.county")
        self.assertEqual(
            fields[0].option_fill_expression("user_address_county+suffolk"),
            "users[0].address.county == 'suffolk'",
        )


class TestOptionGroupsFromAPdf(unittest.TestCase):
    def _fields(self):
        option_pdf = Path(__file__).parent / "test/test_option_groups.pdf"
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        fields = DAFieldList()
        fields.add_fields_from_file(MockDAStaticFile(full_path=option_pdf))
        fields.gathered = True
        return fields

    def test_grouping_happens_when_reading_the_file(self):
        by_variable = {field.variable: field for field in self._fields()}
        self.assertEqual(
            sorted(by_variable),
            ["relief_sought", "service_method", "users1_name_first"],
        )
        self.assertEqual(
            by_variable["service_method"].choice_options,
            ["by_mail", "in_hand", "by_email"],
        )
        self.assertFalse(by_variable["users1_name_first"].is_option_group())

    def test_export_values_do_not_become_choices(self):
        """These are checkboxes, so their `/On` export value is not an answer."""
        by_variable = {field.variable: field for field in self._fields()}
        self.assertNotIn("On", by_variable["service_method"].choice_options)

    def test_auto_labelling_fills_in_the_choices(self):
        fields = self._fields()
        fields.auto_label_fields()
        by_variable = {field.variable: field for field in fields}
        self.assertEqual(
            by_variable["relief_sought"].choices, "Rent: rent\nUtilities: utilities"
        )
        self.assertFalse(hasattr(by_variable["users1_name_first"], "choices"))


class TestDAFieldChoicesString(unittest.TestCase):
    def test_no_choice_options_gives_an_empty_string(self):
        field = DAField()
        self.assertEqual(field.choices_string(), "")

# do not pre-load
import unittest
from .interview_generator import (
    DAField,
    get_character_limit,
    get_input_dimensions,
    varname,
)


class test_fill_in_pdf_attributes(unittest.TestCase):
    def test_simple_pdf_field(self):
        pdf_field_tuple = ("field_name", "default text", 0, [10, 10, 100, 30], "/Tx")
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple, {})
        self.assertEqual(new_field.variable, "field_name")
        self.assertEqual(new_field.final_display_var, "field_name")
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, "text")
        self.assertEqual(new_field.variable_name_guess, "Field name")

    def test_date_field(self):
        pdf_field_tuple = ("birth_date", "", 0, [10, 10, 100, 30], "/Tx")
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple, {})
        self.assertEqual(new_field.variable, "birth_date")
        self.assertEqual(new_field.final_display_var, "birth_date")
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, "date")
        self.assertEqual(new_field.variable_name_guess, "Date of birth")

    def test_yes_text_field(self):
        pdf_field_tuple = ("has_ssn_yes", "", 0, [10, 10, 100, 30], "/Tx")
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple, {})
        self.assertEqual(new_field.variable, "has_ssn_yes")
        self.assertEqual(new_field.final_display_var, "has_ssn_yes")
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, "yesno")
        self.assertEqual(new_field.variable_name_guess, "Has ssn")

    def test_no_text_field(self):
        pdf_field_tuple = ("has_ssn_no", "", 0, [10, 10, 100, 30], "/Tx")
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple, {})
        self.assertEqual(new_field.variable, "has_ssn_no")
        self.assertEqual(new_field.final_display_var, "has_ssn_no")
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, "yesno")
        self.assertEqual(new_field.variable_name_guess, "Has ssn")

    def test_yesno_btn_field(self):
        pdf_field_tuple = ("has_ssn", "", 0, [10, 10, 100, 30], "/Btn")
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple, {})
        self.assertEqual(new_field.variable, "has_ssn")
        self.assertEqual(new_field.final_display_var, "has_ssn")
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, "yesno")
        self.assertEqual(new_field.variable_name_guess, "Has ssn")

    def test_sig_field(self):
        pdf_field_tuple = ("signature", "", 0, [10, 10, 100, 30], "/Sig")
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple, {})
        self.assertEqual(new_field.variable, "signature")
        self.assertEqual(new_field.final_display_var, "signature")
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, "signature")
        self.assertEqual(new_field.variable_name_guess, "Signature")

    def test_multiple_choice(self):
        # From an Adobe-Acrobat made radio button field
        pdf_field_tuple = (
            "Group1",
            "No",
            1,
            [162.9, 631.3, 180.9, 649.3],
            "/Btn",
            "Choice3",
        )
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple, {})
        self.assertEqual(new_field.variable, "Group1")
        self.assertEqual(new_field.final_display_var, "Group1")
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, "multiple choice radio")
        self.assertEqual(new_field.variable_name_guess, "Group1")

    def test_python_keyword_field(self):
        # "from" is a legal PDF field name but not a legal Python identifier
        pdf_field_tuple = ("from", "", 0, [10, 10, 100, 30], "/Tx")
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple, {})
        self.assertEqual(new_field.raw_field_names, ["from"])
        self.assertEqual(new_field.variable, "from_")
        self.assertEqual(new_field.final_display_var, "from_")


class test_varname(unittest.TestCase):
    def test_python_keywords_are_escaped(self):
        for reserved in ["from", "class", "return", "import", "None", "lambda"]:
            self.assertEqual(varname(reserved), reserved + "_")

    def test_ordinary_names_are_untouched(self):
        for ordinary in ["from_fax", "classification", "match", "user_name_first"]:
            self.assertEqual(varname(ordinary), ordinary)


if __name__ == "__main__":
    unittest.main()


class test_input_dimensions(unittest.TestCase):
    def test_single_row_field(self):
        # 90 pixels wide, 20 tall: one row of 15 characters
        self.assertEqual(
            get_input_dimensions(("f", "", 0, [10, 10, 100, 30], "/Tx")), (1, 15)
        )

    def test_multi_row_field(self):
        # 150 wide, 48 tall: 4 rows of 25 characters
        self.assertEqual(
            get_input_dimensions(("f", "", 0, [0, 0, 150, 48], "/Tx")), (4, 25)
        )
        self.assertEqual(get_character_limit(("f", "", 0, [0, 0, 150, 48], "/Tx")), 100)

    def test_field_without_a_bounding_box(self):
        self.assertIsNone(get_input_dimensions(("f", "", 0, None, "/Tx")))
        self.assertIsNone(get_character_limit(("f", "", 0, None, "/Tx")))

    def test_field_too_small_to_hold_a_character(self):
        self.assertIsNone(get_input_dimensions(("f", "", 0, [0, 0, 3, 10], "/Tx")))


class test_safe_value_kwargs(unittest.TestCase):
    def test_line_width_comes_from_the_pdf_geometry(self):
        field = DAField()
        field.fill_in_pdf_attributes(("story", "", 0, [0, 0, 150, 48], "/Tx"), {})
        self.assertEqual(field.input_width, 25)
        self.assertEqual(field.input_rows, 4)
        self.assertEqual(field.maxlength, 100)
        self.assertEqual(field.safe_value_kwargs(), ", input_width=25")

    def test_no_kwargs_without_a_measurable_field(self):
        field = DAField()
        field.fill_in_pdf_attributes(("story", "", 0, None, "/Tx"), {})
        self.assertEqual(field.safe_value_kwargs(), "")

import unittest
from .interview_generator import DAField

class test_fill_in_pdf_attributes(unittest.TestCase):

    def test_simple_pdf_field(self):
        pdf_field_tuple = ('field_name', 'default text', 0, [10, 10, 100, 30], '/Tx')
        new_field = DAField()
        new_field.fill_in_pdf_attributes(pdf_field_tuple)
        self.assertEqual(new_field.variable, 'field_name')
        self.assertEqual(new_field.final_display_var, 'field_name')
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, 'text')
        self.assertEqual(new_field.variable_name_guess, 'Field name')

    def test_date_field(self):
        pdf_field_tuple = ('birth_date', '', 0, [10, 10, 100, 30], '/Tx')
        new_field = DAField() 
        new_field.fill_in_pdf_attributes(pdf_field_tuple)
        self.assertEqual(new_field.variable, 'birth_date')
        self.assertEqual(new_field.final_display_var, 'birth_date')
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, 'date')
        self.assertEqual(new_field.variable_name_guess, 'Date of birth')

    def test_yes_text_field(self):
        pdf_field_tuple = ('has_ssn_yes', '', 0, [10, 10, 100, 30], '/Tx')
        new_field = DAField() 
        new_field.fill_in_pdf_attributes(pdf_field_tuple)
        self.assertEqual(new_field.variable, 'has_ssn_yes')
        self.assertEqual(new_field.final_display_var, 'has_ssn_yes')
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, 'yesno')
        self.assertEqual(new_field.variable_name_guess, 'Has ssn')

    def test_no_text_field(self):
        pdf_field_tuple = ('has_ssn_no', '', 0, [10, 10, 100, 30], '/Tx')
        new_field = DAField() 
        new_field.fill_in_pdf_attributes(pdf_field_tuple)
        self.assertEqual(new_field.variable, 'has_ssn_no')
        self.assertEqual(new_field.final_display_var, 'has_ssn_no')
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, 'yesno')
        self.assertEqual(new_field.variable_name_guess, 'Has ssn')

    def test_yesno_btn_field(self):
        pdf_field_tuple = ('has_ssn', '', 0, [10, 10, 100, 30], '/Btn')
        new_field = DAField() 
        new_field.fill_in_pdf_attributes(pdf_field_tuple)
        self.assertEqual(new_field.variable, 'has_ssn')
        self.assertEqual(new_field.final_display_var, 'has_ssn')
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, 'yesno')
        self.assertEqual(new_field.variable_name_guess, 'Has ssn')

    def test_sig_field(self):
        pdf_field_tuple = ('signature', '', 0, [10, 10, 100, 30], '/Sig')
        new_field = DAField() 
        new_field.fill_in_pdf_attributes(pdf_field_tuple)
        self.assertEqual(new_field.variable, 'signature')
        self.assertEqual(new_field.final_display_var, 'signature')
        self.assertEqual(new_field.has_label, True)
        self.assertEqual(new_field.field_type_guess, 'signature')
        self.assertEqual(new_field.variable_name_guess, 'Signature')


if __name__ == "__main__":
    unittest.main()
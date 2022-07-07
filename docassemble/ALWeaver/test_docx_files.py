import unittest
from .interview_generator import DAField, get_docx_variables, is_reserved_docx_label, get_pdf_variable_name_matches
from docassemble.base.util import DAFile
from docx2python import docx2python
from pathlib import Path


class test_docxs(unittest.TestCase):
    def test_unmap_suffixes(self):
        unmap_suffixes_file = Path(__file__).parent / "test/unmap_suffixes.docx"
        docx_data = docx2python(unmap_suffixes_file)
        text = docx_data.text
        all_vars = get_docx_variables(text)
        self.assertEqual(len(all_vars), 9, str(all_vars))
        self.assertIn("children[0].phone_number", all_vars)
        self.assertIn("children[1].birthdate", all_vars)
        self.assertIn("children[0].birthdate", all_vars)
        self.assertIn("children[0].birthdate", all_vars)
        self.assertIn("children[0].name.first", all_vars)
        self.assertIn("children[0].mailing_address.address", all_vars)
        self.assertIn("children[0].mailing_address.county", all_vars)
        self.assertIn("children[0].address.address", all_vars)
        self.assertIn("children[0].address.county", all_vars)
        self.assertIn("milkman.attorney.firm", all_vars)

    def test_reserved_docx_labels(self):
        reserved_labels_files = (
            Path(__file__).parent / "test/reserved_docx_variables.docx"
        )
        docx_data = docx2python(reserved_labels_files)
        text = docx_data.text
        all_vars = get_docx_variables(text)
        reserved_labels = []
        for label in all_vars:
            if is_reserved_docx_label(label):
                reserved_labels.append(label)
        self.assertEqual(len(reserved_labels), 2, str(reserved_labels))
        self.assertIn("trial_court.address.county", reserved_labels)
        self.assertIn("users[0].address.address", reserved_labels)
        self.assertNotIn("users.address.zip", reserved_labels)

    def test_pdf_variables_in_docx(self):
        pdf_variables_file = (
            Path(__file__).parent / "test/pdf_variables_in_docx.docx"            
        )

        matching_fields = get_pdf_variable_name_matches(pdf_variables_file)
        self.assertIn(("petitioner_email", "petitioners[0].email"), matching_fields)
        self.assertIn(("users1_mailing_address", "users[0].mailing_address"), matching_fields)
        self.assertNotIn(("users", "users"), matching_fields)
        self.assertNotIn(("other_parties", "other_parties"), matching_fields)



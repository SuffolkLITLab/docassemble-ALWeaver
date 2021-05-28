import unittest
from .interview_generator import DAField, get_docx_variables, is_reserved_docx_label
from docx2python import docx2python
from pathlib import Path

class test_docxs(unittest.TestCase):

  def test_unmap_suffixes(self):
    unmap_suffixes_file = Path(__file__).parent / 'test/unmap_suffixes.docx'
    docx_data = docx2python(unmap_suffixes_file)
    text = docx_data.text
    all_vars = get_docx_variables(text)
    self.assertEqual(len(all_vars), 9, str(all_vars))
    self.assertIn('children[0].phone_number', all_vars)
    self.assertIn('children[1].birthdate', all_vars)
    self.assertIn('children[0].birthdate', all_vars)
    self.assertIn('children[0].birthdate', all_vars)
    self.assertIn('children[0].name.first', all_vars)
    self.assertIn('children[0].mailing_address.address', all_vars)
    self.assertIn('children[0].mailing_address.county', all_vars)
    self.assertIn('children[0].address.address', all_vars)
    self.assertIn('children[0].address.county', all_vars)
    self.assertIn('milkman.attorney.firm', all_vars)

  def test_reserved_docx_labels(self):
    reserved_labels_files = Path(__file__).parent / 'test/reserved_docx_variables.docx'
    docx_data = docx2python(reserved_labels_files)
    text = docx_data.text
    all_vars = get_docx_variables(text)
    reserved_labels = []
    for label in all_vars:
      if is_reserved_docx_label(label):
        reserved_labels.append(label)
    self.assertEqual(len(reserved_labels), 2, str(reserved_labels))
    self.assertIn('trial_court.address.county', reserved_labels)
    self.assertIn('users[0].address.address', reserved_labels)
    self.assertNotIn('users.address.zip', reserved_labels)
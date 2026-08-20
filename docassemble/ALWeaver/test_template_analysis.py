# do not pre-load

"""Analyzing a template that is joining an interview which already exists."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from . import interview_generator as interview_generator_module
from .template_analysis import (
    analyze_template,
    document_variable_for,
    interview_defined_variables,
)
from .test_generate_from_path import _build_pdf_with_fields

# A working one-document interview, of the shape Weaver generates.
EXISTING_INTERVIEW = """---
include:
  - docassemble.AssemblyLine:assembly_line.yml
---
objects:
  - users: ALPeopleList.using(there_are_any=True)
---
objects:
  - petition: ALDocument.using(filename="petition", enabled=True, has_addendum=False)
---
objects:
  - al_user_bundle: ALDocumentBundle.using(elements=[petition], filename="petition", enabled=True)
  - al_court_bundle: ALDocumentBundle.using(elements=[petition], filename="petition", enabled=True)
---
id: user name
question: |
  What is your name?
fields:
  - First name: users[0].name.first
  - Last name: users[0].name.last
---
id: rent
question: |
  Rent
fields:
  - Monthly rent: rent_amount
    datatype: currency
---
code: |
  hearing_date = today()
---
attachment:
  name: Petition
  filename: petition
  variable name: petition[i]
  pdf template file: petition.pdf
  fields:
    - "users_name": ${ users[0] }
"""


class TestInterviewIntrospection(unittest.TestCase):
    def test_a_document_is_named_the_way_output_mako_names_it(self):
        # `output.mako` uses `varname(base_name(filename))`, which keeps case.
        self.assertEqual(
            document_variable_for("Affidavit of Indigency.pdf"),
            "Affidavit_of_Indigency",
        )

    def test_it_finds_what_the_interview_already_defines(self):
        defined = interview_defined_variables(EXISTING_INTERVIEW)
        self.assertIn("users", defined)
        self.assertIn("rent_amount", defined)
        self.assertIn("hearing_date", defined)
        self.assertIn("petition", defined)
        self.assertNotIn("landlord_visits", defined)


class TestAnalyzeTemplate(unittest.TestCase):
    def _analyze(self, field_names, filename="affidavit.pdf", interview=None):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, True)
        template_path = _build_pdf_with_fields(
            os.path.join(tmpdir, filename), field_names
        )
        with patch.object(
            interview_generator_module.formfyxer,
            "cluster_screens",
            side_effect=lambda fields, tools_token=None: {
                "Screen 1": list(dict.fromkeys(fields or []))
            },
        ):
            return analyze_template(
                template_path=template_path,
                template_filename=filename,
                interview_yaml=(EXISTING_INTERVIEW if interview is None else interview),
            )

    def test_it_offers_an_attachment_named_after_the_template(self):
        analysis = self._analyze(["users1_name_first", "landlord_visits"])

        self.assertEqual(analysis.document_variable, "affidavit")
        self.assertIsNotNone(analysis.attachment)
        assert analysis.attachment is not None
        self.assertIn("pdf template file: affidavit.pdf", analysis.attachment.yaml)
        self.assertIn("variable name: affidavit[i]", analysis.attachment.yaml)
        self.assertIsNotNone(analysis.document_object)
        assert analysis.document_object is not None
        self.assertIn("- affidavit: ALDocument.using(", analysis.document_object.yaml)

    def test_it_only_offers_screens_for_fields_nothing_asks_about_yet(self):
        analysis = self._analyze(["users1_name_first", "landlord_visits"])

        self.assertIn("landlord_visits", analysis.new_variables)
        self.assertNotIn("users[0].name.first", analysis.new_variables)
        offered = "\n".join(question.yaml for question in analysis.questions)
        self.assertIn("landlord_visits", offered)
        self.assertNotIn("users[0].name.first", offered)

    def test_a_template_that_adds_nothing_new_offers_no_screens(self):
        analysis = self._analyze(["users1_name_first"])

        self.assertEqual(analysis.questions, [])
        self.assertIsNotNone(analysis.attachment)

    def test_it_says_which_bundles_the_document_should_join(self):
        analysis = self._analyze(["landlord_visits"])

        self.assertEqual(
            [
                (addition["bundle"], addition["elements"])
                for addition in analysis.bundle_additions
            ],
            [
                ("al_user_bundle", ["petition", "affidavit"]),
                ("al_court_bundle", ["petition", "affidavit"]),
            ],
        )

    def test_an_imported_template_is_offered_as_a_re_read_not_a_duplicate(self):
        """The court revises a form; the fields have to be read again."""
        analysis = self._analyze(
            ["users1_name_first", "landlord_visits"], filename="petition.pdf"
        )

        self.assertTrue(analysis.already_imported)
        self.assertIsNone(analysis.document_object)
        self.assertEqual(analysis.bundle_additions, [])
        assert analysis.attachment is not None
        self.assertEqual(analysis.attachment.kind, "attachment_replacement")
        # It overwrites whatever the author did to that block, so it is offered
        # rather than assumed.
        self.assertFalse(analysis.attachment.recommended)
        self.assertTrue(analysis.attachment.replaces_block_id)
        # A field the revised form added is still offered as a new screen.
        self.assertIn("landlord_visits", analysis.new_variables)

    def test_a_document_name_that_is_taken_by_another_template_is_refused(self):
        """Two templates cannot share one ALDocument."""
        interview = EXISTING_INTERVIEW.replace(
            "pdf template file: petition.pdf", "pdf template file: something_else.pdf"
        )
        analysis = self._analyze(
            ["users1_name_first"], filename="petition.pdf", interview=interview
        )

        self.assertFalse(analysis.already_imported)
        self.assertIsNone(analysis.attachment)
        self.assertIsNone(analysis.document_object)
        self.assertTrue(
            any("already exists" in warning for warning in analysis.warnings),
            analysis.warnings,
        )

    def test_an_interview_with_no_bundle_is_told_the_attachment_goes_nowhere(self):
        survey = """---
objects:
  - users: ALPeopleList.using(there_are_any=True)
---
id: user name
question: |
  What is your name?
fields:
  - First name: users[0].name.first
"""
        analysis = self._analyze(["landlord_visits"], interview=survey)

        self.assertIsNotNone(analysis.attachment)
        self.assertTrue(
            any("no ALDocumentBundle" in warning for warning in analysis.warnings),
            analysis.warnings,
        )

    def test_the_objects_it_offers_are_only_the_ones_the_interview_lacks(self):
        analysis = self._analyze(["users1_name_first", "patient1_name_first"])

        self.assertIsNotNone(analysis.objects)
        assert analysis.objects is not None
        self.assertIn("patient", analysis.objects.yaml)
        self.assertNotIn("users:", analysis.objects.yaml)


if __name__ == "__main__":
    unittest.main()

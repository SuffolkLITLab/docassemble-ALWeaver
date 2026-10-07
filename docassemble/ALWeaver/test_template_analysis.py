# do not pre-load

"""Analyzing a template that is joining an interview which already exists."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from docx import Document

from .template_analysis import (
    _attachment_mapping_field_names,
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
    def test_nested_mapping_expression_keys_are_not_template_field_names(self):
        data = {
            "attachment": {
                "fields": [
                    {"form_field": {"code": "${ value }", "value": "value"}},
                    {"other_form_field": "${ other_value }"},
                ]
            }
        }
        self.assertEqual(
            _attachment_mapping_field_names(data),
            {"form_field", "other_form_field"},
        )

    def test_a_document_is_named_the_way_output_mako_names_it(self):
        # `output.mako` uses `varname(base_name(filename))`, which keeps case.
        naming = document_variable_for("Affidavit of Indigency.pdf")
        self.assertEqual(naming.variable, "Affidavit_of_Indigency")
        self.assertEqual(naming.filename, "Affidavit of Indigency")

    def test_a_name_already_taken_falls_back_to_the_extension(self):
        naming = document_variable_for("petition.docx", taken=["petition"])
        self.assertEqual(naming.variable, "petition_docx")
        self.assertEqual(naming.filename, "petition_docx")

    def test_it_finds_what_the_interview_already_defines(self):
        defined = interview_defined_variables(EXISTING_INTERVIEW)
        self.assertIn("users", defined)
        self.assertIn("rent_amount", defined)
        self.assertIn("hearing_date", defined)
        self.assertIn("petition", defined)
        self.assertNotIn("landlord_visits", defined)


class TestAnalyzeTemplate(unittest.TestCase):
    def _analyze(
        self, field_names, filename="affidavit.pdf", interview=None, docx_fields=None
    ):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, True)
        template_path = os.path.join(tmpdir, filename)
        if filename.lower().endswith(".docx"):
            if docx_fields is None:
                # The generator really opens the file, so a DOCX has to be one.
                shutil.copyfile(
                    Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx",
                    template_path,
                )
            else:
                document = Document()
                for field_name in docx_fields:
                    document.add_paragraph("{{ " + field_name + " }}")
                document.save(template_path)
        else:
            _build_pdf_with_fields(template_path, field_names)
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

    def test_revised_template_reports_added_removed_and_stale_fields(self):
        """A re-read previews field changes without deleting authored work."""
        old_fields = EXISTING_INTERVIEW.replace(
            '"users_name": ${ users[0] }',
            '"matrix_doc_revision_primary": ${ matrix_doc_revision_primary }\n'
            '    - "matrix_doc_revision_removed": ${ matrix_doc_revision_removed }\n'
            '    - "matrix_doc_revision_old_name": ${ matrix_doc_revision_old_name }',
        )
        old_fields += """---
id: authored removed-field question
question: Existing authored question
fields:
  - Removed value: matrix_doc_revision_removed
"""

        analysis = self._analyze(
            [
                "matrix_doc_revision_primary",
                "matrix_doc_revision_added",
                "matrix_doc_revision_new_name",
            ],
            filename="petition.pdf",
            interview=old_fields,
        )

        self.assertTrue(analysis.already_imported)
        self.assertEqual(
            analysis.mapping_changes,
            {
                "added": [
                    "matrix_doc_revision_added",
                    "matrix_doc_revision_new_name",
                ],
                "removed": [
                    "matrix_doc_revision_old_name",
                    "matrix_doc_revision_removed",
                ],
                "retained": ["matrix_doc_revision_primary"],
            },
        )
        self.assertEqual(
            analysis.stale_question_variables, ["matrix_doc_revision_removed"]
        )
        self.assertTrue(
            any(
                "no longer contains mapped fields" in item for item in analysis.warnings
            )
        )
        self.assertTrue(
            any(
                "Existing question screens still ask" in item
                for item in analysis.warnings
            )
        )
        self.assertIn("matrix_doc_revision_removed", old_fields)
        data = analysis.to_dict()
        self.assertEqual(data["mapping_changes"], analysis.mapping_changes)
        self.assertEqual(
            data["stale_question_variables"], ["matrix_doc_revision_removed"]
        )

    def test_revised_docx_compares_its_saved_field_manifest(self):
        docx_interview = EXISTING_INTERVIEW.replace(
            "pdf template file: petition.pdf",
            "docx template file: petition.docx",
        )
        docx_interview = docx_interview.replace(
            "attachment:\n",
            "# ALWeaver DOCX template field manifest: "
            '["matrix_doc_revision_primary", "matrix_doc_revision_removed", '
            '"matrix_doc_revision_old_name"]\nattachment:\n',
        )
        docx_interview += """---
id: authored old DOCX fields
question: Existing questions from the previous DOCX
fields:
  - Removed value: matrix_doc_revision_removed
  - Old spelling: matrix_doc_revision_old_name
"""

        analysis = self._analyze(
            [],
            filename="petition.docx",
            interview=docx_interview,
            docx_fields=[
                "matrix_doc_revision_primary",
                "matrix_doc_revision_added",
                "matrix_doc_revision_new_name",
            ],
        )

        self.assertTrue(analysis.already_imported)
        self.assertEqual(
            analysis.mapping_changes,
            {
                "added": [
                    "matrix_doc_revision_added",
                    "matrix_doc_revision_new_name",
                ],
                "removed": [
                    "matrix_doc_revision_old_name",
                    "matrix_doc_revision_removed",
                ],
                "retained": ["matrix_doc_revision_primary"],
            },
        )
        self.assertEqual(
            analysis.stale_question_variables,
            ["matrix_doc_revision_old_name", "matrix_doc_revision_removed"],
        )
        self.assertIsNotNone(analysis.attachment)
        assert analysis.attachment is not None
        self.assertIn(
            "# ALWeaver DOCX template field manifest: "
            '["matrix_doc_revision_added", "matrix_doc_revision_new_name", '
            '"matrix_doc_revision_primary"]',
            analysis.attachment.yaml,
        )

    def test_legacy_docx_without_manifest_warns_about_unknown_removed_fields(self):
        legacy = EXISTING_INTERVIEW.replace(
            "pdf template file: petition.pdf",
            "docx template file: petition.docx",
        )

        analysis = self._analyze(
            [], filename="petition.docx", interview=legacy, docx_fields=["new_field"]
        )

        self.assertTrue(
            any(
                "no saved template-field manifest" in item for item in analysis.warnings
            )
        )

    def test_a_name_another_template_holds_is_taken_by_extension(self):
        """A `petition.docx` joining an interview that assembles `petition`."""
        analysis = self._analyze(["users1_name_first"], filename="petition.docx")

        self.assertFalse(analysis.already_imported)
        self.assertEqual(analysis.document_variable, "petition_docx")
        assert analysis.document_object is not None
        self.assertIn(
            '- petition_docx: ALDocument.using(filename="petition_docx"',
            analysis.document_object.yaml,
        )
        assert analysis.attachment is not None
        self.assertIn("variable name: petition_docx[i]", analysis.attachment.yaml)
        self.assertIn("filename: petition_docx", analysis.attachment.yaml)
        # The existing `petition` keeps everything it had.
        self.assertNotIn("variable name: petition[i]", analysis.attachment.yaml)
        self.assertEqual(
            [addition["element"] for addition in analysis.bundle_additions],
            ["petition_docx", "petition_docx"],
        )
        self.assertTrue(
            any("`petition_docx`" in warning for warning in analysis.warnings),
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

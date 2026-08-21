# do not pre-load

"""Reading and rearranging the documents an interview assembles."""

import unittest

from .document_bundles import (
    interview_documents,
    template_status,
    set_bundle_elements,
    set_enabled_expression,
)

EXISTING_INTERVIEW = """---
include:
  - docassemble.AssemblyLine:assembly_line.yml
---
objects:
  - users: ALPeopleList.using(there_are_any=True)
---
# ALDocument objects specify the metadata for each template
objects:
  - petition: ALDocument.using(filename="petition", enabled=True, has_addendum=False)
  - affidavit: ALDocument.using(filename="affidavit", enabled=True, has_addendum=False)
---
# Bundles group the ALDocuments into separate downloads
objects:
  - al_user_bundle: ALDocumentBundle.using(elements=[petition, affidavit], filename="petition", enabled=True)
  - al_court_bundle: ALDocumentBundle.using(elements=[petition, affidavit], filename="petition", enabled=True)
---
template: petition.title
content: |
  Petition to enforce
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
---
attachment:
  name: Affidavit
  filename: affidavit
  variable name: affidavit[i]
  pdf template file: affidavit.pdf
  fields:
    - "users_name": ${ users[0] }
"""


class TestReadingDocuments(unittest.TestCase):
    def test_each_document_is_matched_to_the_template_it_fills(self):
        model = interview_documents(EXISTING_INTERVIEW)
        self.assertEqual(
            [
                (document.name, document.template_filename, document.enabled)
                for document in model.documents
            ],
            [
                ("petition", "petition.pdf", "True"),
                ("affidavit", "affidavit.pdf", "True"),
            ],
        )

    def test_a_documents_title_comes_from_its_template_block(self):
        model = interview_documents(EXISTING_INTERVIEW)
        self.assertEqual(model.documents[0].title, "Petition to enforce")

    def test_bundles_report_their_order(self):
        model = interview_documents(EXISTING_INTERVIEW)
        self.assertEqual(
            [(bundle.name, bundle.elements) for bundle in model.bundles],
            [
                ("al_user_bundle", ["petition", "affidavit"]),
                ("al_court_bundle", ["petition", "affidavit"]),
            ],
        )


class TestTemplateStatus(unittest.TestCase):
    """A file in `templates/` is not part of anything until something uses it."""

    def test_a_template_an_attachment_fills_is_attached(self):
        statuses = template_status(EXISTING_INTERVIEW, ["petition.pdf"])
        self.assertEqual(
            statuses["petition.pdf"],
            {"status": "attached", "document": "petition"},
        )

    def test_a_template_used_some_other_way_is_referenced_not_attached(self):
        interview = EXISTING_INTERVIEW + """---
question: |
  Hello
subquestion: |
  ${ logo_png }
content file: logo.png
"""
        statuses = template_status(interview, ["logo.png"])
        self.assertEqual(statuses["logo.png"]["status"], "referenced")
        self.assertEqual(statuses["logo.png"]["document"], "")

    def test_a_template_nothing_mentions_has_not_been_imported(self):
        statuses = template_status(
            EXISTING_INTERVIEW, ["cover_sheet.pdf", "notice.docx"]
        )
        self.assertEqual(
            statuses["cover_sheet.pdf"],
            {"status": "not_imported", "document": ""},
        )
        self.assertEqual(
            statuses["notice.docx"],
            {"status": "not_imported", "document": ""},
        )

    def test_a_stray_file_that_could_never_be_a_document_is_not_an_import(self):
        """Offering to import a PNG would be nonsense."""
        statuses = template_status(EXISTING_INTERVIEW, ["seal.png", "notes.txt"])
        self.assertEqual(
            [entry["status"] for entry in statuses.values()], ["unused", "unused"]
        )


class TestRearrangingDocuments(unittest.TestCase):
    def test_reordering_a_bundle_leaves_everything_else_alone(self):
        updated = set_bundle_elements(
            EXISTING_INTERVIEW, "al_user_bundle", ["affidavit", "petition"]
        )
        model = interview_documents(updated)
        self.assertEqual(model.bundles[0].elements, ["affidavit", "petition"])
        # The other bundle in the same block, and the block's comment, survive.
        self.assertEqual(model.bundles[1].elements, ["petition", "affidavit"])
        self.assertIn("# Bundles group the ALDocuments", updated)
        self.assertIn("- Monthly rent: rent_amount", updated)

    def test_a_bundle_can_gain_a_document(self):
        updated = set_bundle_elements(
            EXISTING_INTERVIEW,
            "al_court_bundle",
            ["petition", "affidavit", "cover_sheet"],
        )
        self.assertIn(
            "elements=[petition, affidavit, cover_sheet]",
            updated,
        )

    def test_a_document_can_be_turned_on_by_a_rule(self):
        updated = set_enabled_expression(
            EXISTING_INTERVIEW, "affidavit", "user_is_low_income"
        )
        model = interview_documents(updated)
        self.assertEqual(model.documents[1].enabled, "user_is_low_income")
        # The petition's own declaration is untouched.
        self.assertEqual(model.documents[0].enabled, "True")

    def test_clearing_the_rule_leaves_assemblyline_its_default(self):
        updated = set_enabled_expression(EXISTING_INTERVIEW, "affidavit", None)
        model = interview_documents(updated)
        self.assertEqual(model.documents[1].enabled, "")
        self.assertIn(
            '- affidavit: ALDocument.using(filename="affidavit", has_addendum=False)',
            updated,
        )

    def test_a_bundle_can_be_switched_off_by_a_rule(self):
        updated = set_enabled_expression(
            EXISTING_INTERVIEW, "al_court_bundle", "form_is_being_filed"
        )
        model = interview_documents(updated)
        self.assertEqual(model.bundles[1].enabled, "form_is_being_filed")

    def test_a_rule_that_is_not_an_expression_is_refused(self):
        with self.assertRaises(ValueError):
            set_enabled_expression(EXISTING_INTERVIEW, "affidavit", "if x: y")

    def test_a_mapping_form_objects_block_is_editable_too(self):
        """`objects:` also accepts a plain mapping, and both forms are read."""
        mapping_form = """---
objects:
  petition: ALDocument.using(filename="petition", enabled=True)
  al_user_bundle: ALDocumentBundle.using(elements=[petition, affidavit], filename="p")
"""
        updated = set_bundle_elements(
            mapping_form, "al_user_bundle", ["affidavit", "petition"]
        )
        self.assertEqual(
            interview_documents(updated).bundles[0].elements,
            ["affidavit", "petition"],
        )

    def test_a_rule_containing_a_colon_does_not_destroy_the_block(self):
        """A declaration is a Python expression living in a YAML scalar."""
        updated = set_enabled_expression(
            EXISTING_INTERVIEW, "affidavit", "{'yes': True}.get(answer)"
        )
        model = interview_documents(updated)
        self.assertEqual(
            [document.name for document in model.documents],
            ["petition", "affidavit"],
        )
        self.assertEqual(model.documents[1].enabled, "{'yes': True}.get(answer)")

    def test_reordering_something_that_is_not_declared_is_refused(self):
        with self.assertRaises(ValueError):
            set_bundle_elements(EXISTING_INTERVIEW, "no_such_bundle", ["petition"])

    def test_an_element_that_is_not_a_variable_name_is_refused(self):
        with self.assertRaises(ValueError):
            set_bundle_elements(
                EXISTING_INTERVIEW, "al_user_bundle", ["petition; rm -rf /"]
            )


if __name__ == "__main__":
    unittest.main()

# do not pre-load
"""Regression coverage for lossless graphical attachment field edits."""

import unittest

import yaml

from .attachment_editor import (
    attachment_mappings,
    update_attachment_mappings,
    remove_attachment,
)


class TestAttachmentMappings(unittest.TestCase):
    def test_removing_one_of_multiple_attachments_preserves_question_and_other(self):
        source = """question: Your documents
attachments:
  - variable name: petition[i]
    pdf template file: petition.pdf
  - variable name: affidavit[i]
    docx template file: affidavit.docx
under: Keep this text
"""
        updated = remove_attachment(source, "petition")
        self.assertEqual(
            yaml.safe_load(updated)["attachments"],
            [{"variable name": "affidavit[i]", "docx template file": "affidavit.docx"}],
        )
        self.assertIn("question: Your documents", updated)
        self.assertIn("under: Keep this text", updated)
        self.assertNotIn("petition", updated)

    def test_edit_preserves_question_comments_and_other_attachment(self):
        source = """# Keep this question
id: receipt
question: "Your receipt"
attachments:
  - name: Receipt
    pdf template file: receipt.pdf
    fields:
      - "amount": '${ old_amount }' # Keep this comment
      - address: |
          ${ address }
    skip undefined: True
  - name: Letter
    docx template file: letter.docx
"""
        value = '${ amount if eligible else "" }'
        updated = update_attachment_mappings(
            source, [{"index": 0, "values": {"amount": value}}]
        )
        self.assertEqual(
            yaml.safe_load(updated)["attachments"][0]["fields"][0]["amount"], value
        )
        self.assertIn("# Keep this comment", updated)
        self.assertEqual(
            updated.split("      - address:")[1], source.split("      - address:")[1]
        )
        self.assertTrue(
            updated.startswith(
                '# Keep this question\nid: receipt\nquestion: "Your receipt"'
            )
        )

    def test_multiline_and_missing_field_before_following_property(self):
        source = """attachment:
  pdf template file: sample.pdf
  fields:
    - old: |
        Old value
  skip undefined: True
"""
        expression = "% if eligible:\n${ amount }\n% endif\n"
        updated = update_attachment_mappings(
            source, [{"index": 0, "values": {"old": expression, "new": "${ name }"}}]
        )
        data = yaml.safe_load(updated)["attachment"]
        self.assertEqual(data["fields"], [{"old": expression}, {"new": "${ name }"}])
        self.assertIs(data["skip undefined"], True)

    def test_missing_fields_property_in_multiple_attachments(self):
        source = """attachments:
  - docx template file: a.docx
    variable name: a
  - pdf template file: b.pdf
    variable name: b"""
        updated = update_attachment_mappings(
            source,
            [
                {"index": 0, "values": {"title": "Hello"}},
                {"index": 1, "values": {"name": "${ users[0] }"}},
            ],
        )
        attachments = yaml.safe_load(updated)["attachments"]
        self.assertEqual(attachments[0]["fields"], [{"title": "Hello"}])
        self.assertEqual(attachments[1]["fields"], [{"name": "${ users[0] }"}])

    def test_mapping_form_and_inline_comments(self):
        source = "attachment:\n  pdf template file: a.pdf\n  fields:\n    old: old # keep\n  name: Example\n"
        updated = update_attachment_mappings(
            source, [{"index": 0, "values": {"new": "yes"}}]
        )
        self.assertIn("old: old # keep\n", updated)
        self.assertEqual(
            yaml.safe_load(updated)["attachment"]["fields"],
            {"old": "old", "new": "yes"},
        )

    def test_complex_values_are_read_only_and_unchanged(self):
        source = "attachment:\n  docx template file: a.docx\n  fields:\n    nested:\n      - one\n      - two\n    typed: True\n    text: hello\n"
        rows = attachment_mappings(source)[0]["rows"]
        self.assertEqual([row["editable"] for row in rows], [False, False, True])
        with self.assertRaises(ValueError):
            update_attachment_mappings(
                source, [{"index": 0, "values": {"nested": "oops"}}]
            )
        updated = update_attachment_mappings(
            source, [{"index": 0, "values": {"text": "new"}}]
        )
        self.assertEqual(updated, source.replace("text: hello", 'text: "new"'))

    def test_aliases_and_repeated_keys_are_refused(self):
        for source in (
            "attachment: &a\n  fields:\n    x: hi\n",
            "attachment:\n  fields:\n    x: hi\n    x: bye\n",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                attachment_mappings(source)

    def test_no_changes_is_exact_noop(self):
        source = 'attachment:\n  pdf template file: a.pdf\n  fields:\n    x: "hello" # keep\n'
        self.assertEqual(
            update_attachment_mappings(
                source, [{"index": 0, "values": {"x": "hello"}}]
            ),
            source,
        )

    def test_empty_fields_and_block_scalar_comments(self):
        for empty in ("[]", "{}", "null", "Null", "NULL", "~"):
            source = (
                "attachment:\n  pdf template file: a.pdf\n  fields: "
                + empty
                + " # keep\n  name: Test\n"
            )
            updated = update_attachment_mappings(
                source, [{"index": 0, "values": {"new": "${ value }"}}]
            )
            self.assertIn("# keep", updated)
            self.assertEqual(yaml.safe_load(updated)["attachment"]["name"], "Test")
            self.assertEqual(
                yaml.safe_load(updated)["attachment"]["fields"], [{"new": "${ value }"}]
            )
        source = "attachment:\n  fields:\n    x: | # keep header\n      hello\n"
        updated = update_attachment_mappings(
            source, [{"index": 0, "values": {"x": "new"}}]
        )
        self.assertIn("# keep header", updated)
        self.assertEqual(yaml.safe_load(updated)["attachment"]["fields"]["x"], "new")

    def test_a_fields_key_with_no_value_is_readable_and_fillable(self):
        """A stub attachment is exactly what the dialog exists to fill in."""
        source = (
            "attachment:\n"
            "  pdf template file: a.pdf\n"
            "  fields:\n"
            "  editable templates: True\n"
        )
        self.assertEqual(attachment_mappings(source)[0]["rows"], [])
        updated = update_attachment_mappings(
            source, [{"index": 0, "values": {"signature": "${ users[0] }"}}]
        )
        self.assertEqual(
            yaml.safe_load(updated)["attachment"]["fields"],
            [{"signature": "${ users[0] }"}],
        )
        self.assertIn("editable templates: True", updated)

    def test_a_computed_fields_value_says_so(self):
        source = "attachment:\n  pdf template file: a.pdf\n  fields: chosen_fields\n"
        for call in (
            lambda: attachment_mappings(source),
            lambda: update_attachment_mappings(
                source, [{"index": 0, "values": {"x": "y"}}]
            ),
        ):
            with self.subTest(call=call), self.assertRaises(ValueError) as caught:
                call()
            self.assertIn("computed", str(caught.exception))

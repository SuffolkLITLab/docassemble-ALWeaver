# do not pre load

import unittest

from .editor_utils import (
    metadata_source_slice,
    source_revision,
    update_metadata_documents_in_yaml,
)


class TestMetadataEditorSafety(unittest.TestCase):
    def test_title_edit_changes_only_the_title_source(self):
        source = (
            "# interview header\n"
            "metadata:\n"
            "  title: 'Original title' # keep this comment\n"
            "  short title: Original\n"
            "---\n"
            "# question comment\n"
            "id: intro\n"
            "question: |\n"
            "  Keep this formatting.\n"
            "---\n"
            "code: |\n"
            "  answer = ${ dynamic_value }\n"
        )
        metadata_yaml = metadata_source_slice(source)
        edited_metadata = metadata_yaml.replace("'Original title'", "'Edited title'")

        updated = update_metadata_documents_in_yaml(source, edited_metadata)

        self.assertEqual(
            updated,
            source.replace("'Original title'", "'Edited title'"),
        )

    def test_multiple_metadata_related_documents_are_replaced_in_place(self):
        source = (
            "metadata:\n  title: One\n"
            "---\n"
            "include:\n  - common.yml\n"
            "---\n"
            'id: untouched\nquestion: "Keep quoted"\n'
            "---\n"
            "default screen parts:\n  under: |\n    Original footer\n"
        )
        metadata_yaml = metadata_source_slice(source)
        edited_metadata = metadata_yaml.replace("title: One", "title: Two").replace(
            "Original footer", "Edited footer"
        )

        updated = update_metadata_documents_in_yaml(source, edited_metadata)

        expected = source.replace("title: One", "title: Two").replace(
            "Original footer", "Edited footer"
        )
        self.assertEqual(updated, expected)
        self.assertEqual(
            source_revision(updated),
            source_revision(update_metadata_documents_in_yaml(source, edited_metadata)),
        )

    def test_no_metadata_document_is_refused_without_changing_source(self):
        source = "# keep\nid: intro\nquestion: Hello\n"

        with self.assertRaisesRegex(ValueError, "No metadata-related document"):
            update_metadata_documents_in_yaml(
                source,
                "metadata:\n  title: Added implicitly\n",
            )

        self.assertEqual(source, "# keep\nid: intro\nquestion: Hello\n")

    def test_commented_separators_and_crlf_are_preserved(self):
        source = (
            "metadata:\r\n"
            "  title: Original\r\n"
            "--- # keep separator comment\r\n"
            "id: intro\r\n"
            "question: Hello\r\n"
        )
        edited_metadata = metadata_source_slice(source).replace(
            "title: Original", "title: Edited"
        )

        updated = update_metadata_documents_in_yaml(source, edited_metadata)

        self.assertEqual(updated, source.replace("title: Original", "title: Edited"))


if __name__ == "__main__":
    unittest.main()

import unittest

from .source_document import (
    apply_range_operations,
    parse_source_document,
    source_revision,
    unified_source_diff,
)


class TestSourceDocument(unittest.TestCase):
    def test_retains_exact_documents_and_property_ranges(self):
        source = (
            "# keep header\n"
            "metadata:\n"
            "  title: 'Quoted title' # keep comment\n"
            "---\n"
            "id: intro\n"
            "question: |\n"
            "  Hello ${ user }\n"
            "  \n"
        )
        document = parse_source_document("main.yml", source)

        self.assertEqual(document.raw_text, source)
        self.assertEqual(document.revision, source_revision(source))
        self.assertEqual(len(document.documents), 2)
        self.assertEqual(
            "".join(block.raw_text for block in document.documents),
            source.replace("---\n", ""),
        )
        self.assertEqual(document.documents[0].block_type, "metadata")
        title_range = document.documents[0].property_ranges["metadata"]
        self.assertEqual(
            source[title_range.start.offset : title_range.end.offset],
            "title: 'Quoted title' # keep comment\n",
        )
        self.assertEqual(document.documents[1].block_id, "intro")
        self.assertTrue(document.structurally_valid)

    def test_custom_tag_is_preserved_but_not_graphically_supported(self):
        source = "id: tagged\nvalue: !custom keep_me\n"
        document = parse_source_document("main.yml", source)

        self.assertTrue(document.structurally_valid)
        self.assertEqual(document.documents[0].raw_text, source)
        self.assertFalse(document.documents[0].supported)
        self.assertTrue(document.documents[0].unsupported_reasons)

    def test_invalid_yaml_has_structural_diagnostic(self):
        document = parse_source_document("main.yml", "question: [unterminated\n")
        self.assertFalse(document.structurally_valid)
        self.assertEqual(document.diagnostics[0].severity, "error")
        self.assertEqual(document.diagnostics[0].filename, "main.yml")

    def test_range_operations_change_only_requested_text(self):
        source = "# before\ntitle: Old\n# after\n"
        start = source.index("Old")
        updated, applied = apply_range_operations(
            source,
            [
                {
                    "type": "replace-range",
                    "start": start,
                    "end": start + 3,
                    "text": "New",
                }
            ],
        )
        self.assertEqual(updated, "# before\ntitle: New\n# after\n")
        self.assertEqual(applied[0]["start"], start)
        diff = unified_source_diff(source, updated, "main.yml")
        self.assertIn("-title: Old", diff)
        self.assertIn("+title: New", diff)

    def test_overlapping_operations_are_rejected_atomically(self):
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            apply_range_operations(
                "abcdef",
                [
                    {"type": "replace-range", "start": 1, "end": 4, "text": "x"},
                    {"type": "replace-range", "start": 3, "end": 5, "text": "y"},
                ],
            )


if __name__ == "__main__":
    unittest.main()

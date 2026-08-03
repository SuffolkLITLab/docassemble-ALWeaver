# do not pre load

from pathlib import Path
import unittest

from .source_document import (
    apply_range_operations,
    parse_source_document,
    source_revision,
)


class TestSourceDocument(unittest.TestCase):
    fixture_dir = Path(__file__).with_name("test_fixtures") / "source_roundtrip"

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

    def test_overlapping_operations_are_rejected_atomically(self):
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            apply_range_operations(
                "abcdef",
                [
                    {"type": "replace-range", "start": 1, "end": 4, "text": "x"},
                    {"type": "replace-range", "start": 3, "end": 5, "text": "y"},
                ],
            )

    def test_round_trip_corpus_preserves_unsupported_and_invalid_source(self):
        source = (self.fixture_dir / "complex_interview.yml").read_text()
        document = parse_source_document("complex_interview.yml", source)
        self.assertEqual(document.raw_text, source)
        self.assertTrue(document.structurally_valid, document.diagnostics)
        self.assertTrue(any(not block.supported for block in document.documents))

        invalid = (self.fixture_dir / "invalid_active_edit.yml").read_text()
        invalid_document = parse_source_document("invalid_active_edit.yml", invalid)
        self.assertEqual(invalid_document.raw_text, invalid)
        self.assertFalse(invalid_document.structurally_valid)

    def test_corpus_edits_change_only_the_target_range(self):
        source = (self.fixture_dir / "complex_interview.yml").read_text()
        for old, new in (
            ("EDIT_TARGET", "Changed title"),
            ("A folded question", "The edited folded question"),
            ("Hello ${ users[0] }.", "Hello ${ users[0].name }!"),
        ):
            with self.subTest(target=old):
                start = source.index(old)
                updated, _applied = apply_range_operations(
                    source,
                    [
                        {
                            "type": "replace-range",
                            "start": start,
                            "end": start + len(old),
                            "text": new,
                        }
                    ],
                )
                self.assertEqual(updated[:start], source[:start])
                self.assertEqual(
                    updated[start + len(new) :], source[start + len(old) :]
                )
                self.assertTrue(
                    parse_source_document(
                        "complex_interview.yml", updated
                    ).structurally_valid
                )


if __name__ == "__main__":
    unittest.main()

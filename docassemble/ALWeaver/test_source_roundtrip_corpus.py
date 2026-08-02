from pathlib import Path
import unittest

from .source_document import apply_range_operations, parse_source_document

FIXTURE_DIR = Path(__file__).with_name("test_fixtures") / "source_roundtrip"


class TestSourceRoundTripCorpus(unittest.TestCase):
    def test_complex_interview_is_preserved_and_structurally_valid(self):
        source = (FIXTURE_DIR / "complex_interview.yml").read_text()
        document = parse_source_document("complex_interview.yml", source)

        self.assertEqual(document.raw_text, source)
        self.assertTrue(document.structurally_valid, document.diagnostics)
        self.assertGreaterEqual(len(document.documents), 8)
        self.assertTrue(
            any(
                "empty document" in block.unsupported_reasons
                for block in document.documents
            )
        )
        tagged = next(
            block
            for block in document.documents
            if "!organization-specific" in block.raw_text
        )
        self.assertFalse(tagged.supported)
        self.assertIn("!organization-specific keep-this-tag", tagged.raw_text)

    def test_each_graphical_edit_changes_only_its_target_range(self):
        source = (FIXTURE_DIR / "complex_interview.yml").read_text()
        replacements = (
            ("EDIT_TARGET", "Changed title"),
            ("A folded question", "The edited folded question"),
            ("Preserve this literal block.", "Only this literal line changed."),
            ('"second": 2', '"second": 3'),
            ("keep-this-tag", "keep-this-tag-edited"),
            ("Hello ${ users[0] }.", "Hello ${ users[0].name }!"),
        )

        for old, new in replacements:
            with self.subTest(target=old):
                start = source.index(old)
                updated, applied = apply_range_operations(
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
                self.assertEqual(updated[start : start + len(new)], new)
                self.assertEqual(
                    updated[start + len(new) :], source[start + len(old) :]
                )
                self.assertEqual(applied[0]["text"], new)
                reparsed = parse_source_document("complex_interview.yml", updated)
                self.assertTrue(reparsed.structurally_valid, reparsed.diagnostics)

    def test_scalar_styles_and_line_endings_are_not_normalized(self):
        variants = (
            "title: unquoted\n",
            "title: 'single quoted'\n",
            'title: "double quoted"\n',
            "title: |\n  literal\n",
            "title: >-\n  folded\n",
            "title: old\r\n# CRLF comment\r\n",
        )
        for source in variants:
            with self.subTest(source=source):
                old = "old" if "old" in source else "title"
                start = source.index(old)
                updated, _operations = apply_range_operations(
                    source,
                    [
                        {
                            "type": "replace-range",
                            "start": start,
                            "end": start + len(old),
                            "text": old.upper(),
                        }
                    ],
                )
                self.assertEqual(updated[:start], source[:start])
                self.assertEqual(
                    updated[start + len(old) :], source[start + len(old) :]
                )
                if "\r\n" in source:
                    self.assertEqual(updated.count("\r\n"), source.count("\r\n"))

    def test_invalid_active_buffer_is_retained_for_source_mode(self):
        source = (FIXTURE_DIR / "invalid_active_edit.yml").read_text()
        document = parse_source_document("invalid_active_edit.yml", source)

        self.assertEqual(document.raw_text, source)
        self.assertFalse(document.structurally_valid)
        self.assertIn("untouched_python = True", document.raw_text)


if __name__ == "__main__":
    unittest.main()

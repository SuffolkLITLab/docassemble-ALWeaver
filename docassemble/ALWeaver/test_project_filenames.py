# do not pre-load

import re
import unittest

from .project_filenames import is_safe_project_filename, safe_project_filename

# What Docassemble strips out of a Playground template reference before it goes
# looking for the file: `package_template_filename` in
# `docassemble.base.functions`. A name that changes under this is a name the
# YAML cannot point at.
DOCASSEMBLE_PLAYGROUND_STRIP = re.compile(r"[^A-Za-z0-9\-\_\. ]")


class TestSafeProjectFilename(unittest.TestCase):
    def test_a_name_docassemble_can_already_resolve_is_left_alone(self):
        for filename in (
            "petition.pdf",
            "next_steps_letter.docx",
            "93a-demand.docx",
            "affidavit",
        ):
            self.assertEqual(safe_project_filename(filename), filename)
            self.assertTrue(is_safe_project_filename(filename))

    def test_spaces_and_parentheses_become_one_underscore(self):
        self.assertEqual(
            safe_project_filename(
                "93A_demand_letter_sample-labeled-highlighted (1).docx"
            ),
            "93A_demand_letter_sample-labeled-highlighted_1.docx",
        )
        self.assertFalse(
            is_safe_project_filename(
                "93A_demand_letter_sample-labeled-highlighted (1).docx"
            )
        )

    def test_accented_letters_keep_their_plain_equivalent(self):
        self.assertEqual(safe_project_filename("Citación.pdf"), "Citacion.pdf")

    def test_padding_around_punctuation_is_dropped(self):
        self.assertEqual(
            safe_project_filename("report - final.docx"), "report-final.docx"
        )

    def test_a_directory_part_is_discarded(self):
        self.assertEqual(safe_project_filename("a/b/c d.pdf"), "c_d.pdf")

    def test_a_stem_made_only_of_punctuation_falls_back(self):
        self.assertEqual(
            safe_project_filename("((( ).docx", default_stem="template"),
            "template.docx",
        )
        self.assertEqual(safe_project_filename("  ..  "), "file")

    def test_every_result_survives_docassembles_template_lookup(self):
        for filename in (
            "93A_demand_letter_sample-labeled-highlighted (1).docx",
            "Citación.pdf",
            "report - final.docx",
            "sample'quote\".docx",
            "100% of the form.pdf",
        ):
            safe = safe_project_filename(filename)
            self.assertEqual(DOCASSEMBLE_PLAYGROUND_STRIP.sub("", safe), safe)
            self.assertNotIn(" ", safe)


if __name__ == "__main__":
    unittest.main()

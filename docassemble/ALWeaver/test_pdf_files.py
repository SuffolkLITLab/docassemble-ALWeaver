# do not pre-load
import unittest
from .interview_generator import (
    DAFieldList,
    get_variable_name_warnings,
    get_pdf_validation_errors,
    rename_field_screen_fields,
    pdf_rename_mapping,
)
from docassemble.base.util import DAStaticFile
import docassemble.base.functions
from pathlib import Path


class MockDAStaticFile(DAStaticFile):
    def init(self, *pargs, **kwargs):
        if "full_path" in kwargs:
            full_path = kwargs["full_path"]
            self.full_path = str(full_path)
            if isinstance(full_path, Path):
                kwargs["filename"] = full_path.name
                kwargs["extension"] = full_path.suffix[1:]
            else:
                kwargs["filename"] = self.full_path.split("/")[-1]
                kwargs["extension"] = self.full_path.split(".")[-1]
            if kwargs["extension"] == "pdf":
                kwargs["mimetype"] = "application/pdf"
        super().init(*pargs, **kwargs)

    def path(self):
        return self.full_path


class test_pdfs(unittest.TestCase):
    def test_validate_ignore_push_button(self):
        push_button_pdf = Path(__file__).parent / "test/test_push_button.pdf"
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        da_pdf = MockDAStaticFile(
            full_path=str(push_button_pdf), extension="pdf", mimetype="application/pdf"
        )
        fields = DAFieldList()
        fields.add_fields_from_file(da_pdf)
        fields.gathered = True
        bad_fields = get_variable_name_warnings(fields)
        self.assertEqual(
            len(bad_fields), 0, f"Bad fields in test_push_button.pdf: {bad_fields}"
        )

    def test_person_candidates(self):
        person_pdf = (
            Path(__file__).parent / "data/sources/test_civil_docketing_statement.pdf"
        )
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        da_pdf = MockDAStaticFile(
            full_path=str(person_pdf), extension="pdf", mimetype="application/pdf"
        )
        fields = DAFieldList()
        fields.add_fields_from_file(da_pdf)
        fields.gathered = True
        self.assertIn(
            "have_served_other_party", fields.get_person_candidates(custom_only=True)
        )
        fields.mark_people_as_builtins(["have_served_other_party"])
        fields = DAFieldList()
        fields.add_fields_from_file(da_pdf)
        fields.gathered = True
        self.assertIn(
            "have_served_other_party", fields.get_person_candidates(custom_only=True)
        )

    def test_python_keyword_is_not_a_person(self):
        """A `from_phone` field must not turn into a `from` person list, since
        `from` is a Python keyword and would make the interview unparseable."""
        fields = DAFieldList()
        for field_name in ["from_phone", "from_fax", "hospital_phone"]:
            new_field = fields.appendObject()
            new_field.source_document_type = "pdf"
            new_field.fill_in_pdf_attributes(
                (field_name, "", 0, [10, 10, 100, 30], "/Tx"),
                fields.custom_people_plurals,
            )
        fields.gathered = True
        candidates = fields.get_person_candidates(custom_only=True)
        self.assertNotIn("from", candidates)
        self.assertIn("hospital", candidates)

        fields.auto_mark_people_as_builtins()
        by_variable = {field.variable: field.final_display_var for field in fields}
        self.assertEqual(by_variable["from_phone"], "from_phone")
        self.assertEqual(by_variable["hospital_phone"], "hospital[0].phone_number")


if __name__ == "__main__":
    unittest.main()


class test_rename_fields_screen(unittest.TestCase):
    """Brackets, dots and `#` in a PDF field name must not break the screen.

    Keying the answers by field name produced Docassemble variables like
    `rename_fields['form1[0].#pageSet[0].Page1[0].TextField4[1]']`, which
    Docassemble rejects as an invalid variable name, so the whole screen
    failed to load.
    """

    AWKWARD_NAMES = [
        "form1[0].#pageSet[0].Page1[0].TextField4[1]",
        "form1[0].BodyPage1[0].S1[0].CheckBox1[0]",
        "plain_name",
        "has 'quotes' and \"double quotes\"",
    ]

    def test_screen_fields_use_positional_variable_names(self):
        screen_fields = rename_field_screen_fields(self.AWKWARD_NAMES)
        self.assertEqual(len(screen_fields), len(self.AWKWARD_NAMES))
        for index, entry in enumerate(screen_fields):
            with self.subTest(index=index):
                self.assertEqual(entry["field"], f"rename_fields[{index}]")
                self.assertEqual(entry["label"], self.AWKWARD_NAMES[index])
                self.assertEqual(entry["default"], self.AWKWARD_NAMES[index])

    def test_mapping_uses_the_original_names(self):
        renames = pdf_rename_mapping(
            self.AWKWARD_NAMES,
            {0: "users1_name_first", 1: "users1_is_veteran"},
        )
        self.assertEqual(
            renames,
            {
                "form1[0].#pageSet[0].Page1[0].TextField4[1]": "users1_name_first",
                "form1[0].BodyPage1[0].S1[0].CheckBox1[0]": "users1_is_veteran",
            },
        )

    def test_blank_and_unchanged_answers_are_not_renames(self):
        renames = pdf_rename_mapping(
            self.AWKWARD_NAMES,
            {0: "", 1: "   ", 2: "plain_name", 3: "quoted_field"},
        )
        self.assertEqual(renames, {self.AWKWARD_NAMES[3]: "quoted_field"})

    def test_no_answers_means_no_renames(self):
        self.assertEqual(pdf_rename_mapping(self.AWKWARD_NAMES, {}), {})

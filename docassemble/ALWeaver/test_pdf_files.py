# do not pre-load
import unittest
from .interview_generator import (
    DAFieldList,
    get_variable_name_warnings,
    get_pdf_validation_errors,
    get_unhandled_field_type_warnings,
    pdf_field_type_str,
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


class test_unhandled_pdf_field_types(unittest.TestCase):
    """Drop-downs and list boxes have to be called out, not silently accepted.

    Docassemble cannot fill a PDF `/Ch` field reliably, and the finished form
    just comes back blank, so the author needs to hear about it while they can
    still change the PDF.
    """

    def _fields(self):
        dropdown_pdf = Path(__file__).parent / "test/test_dropdown_fields.pdf"
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        fields = DAFieldList()
        fields.add_fields_from_file(
            MockDAStaticFile(
                full_path=str(dropdown_pdf),
                extension="pdf",
                mimetype="application/pdf",
            )
        )
        fields.gathered = True
        return fields

    def test_choice_fields_are_flagged(self):
        by_variable = {field.variable: field for field in self._fields()}
        self.assertTrue(by_variable["favorite_color"].field_type_not_handled)
        self.assertTrue(by_variable["pick_one"].field_type_not_handled)

    def test_text_fields_are_not_flagged(self):
        by_variable = {field.variable: field for field in self._fields()}
        self.assertFalse(
            getattr(by_variable["plain_text"], "field_type_not_handled", False)
        )

    def test_warnings_name_the_field_and_the_problem(self):
        warnings = get_unhandled_field_type_warnings(self._fields())
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("favorite_color" in warning for warning in warnings))
        self.assertTrue(all("drop-down" in warning for warning in warnings))

    def test_no_warnings_for_an_ordinary_form(self):
        push_button_pdf = Path(__file__).parent / "test/test_push_button.pdf"
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        fields = DAFieldList()
        fields.add_fields_from_file(
            MockDAStaticFile(
                full_path=str(push_button_pdf),
                extension="pdf",
                mimetype="application/pdf",
            )
        )
        fields.gathered = True
        self.assertEqual(get_unhandled_field_type_warnings(fields), [])


class test_pdf_field_type_str(unittest.TestCase):
    def test_known_types(self):
        self.assertEqual(pdf_field_type_str(("f", "", 0, [], "/Tx")), "Text")
        self.assertEqual(pdf_field_type_str(("f", "", 0, [], "/Btn")), "Checkbox")
        self.assertEqual(pdf_field_type_str(("f", "", 0, [], "/Sig")), "Signature")

    def test_choice_type_is_called_out(self):
        self.assertIn("Drop-down", pdf_field_type_str(("f", "", 0, [], "/Ch")))

    def test_short_tuple_does_not_raise(self):
        """The type lives at index 4, so a 4-item tuple used to IndexError."""
        self.assertEqual(pdf_field_type_str(("f", "", 0, [])), "")


class test_reserved_person_prefixes(unittest.TestCase):
    """A base name that is already taken can't become an ALPeopleList.

    A fax cover sheet with a `from_phone_number` field used to make the Weaver
    offer to turn `from` into a list of people, which generates
    `objects:\n  - from: ALPeopleList` -- a syntax error, because `from` is a
    Python keyword. The same goes for names Python or Docassemble has already
    claimed, like `list` or `nav`.
    """

    @staticmethod
    def _candidates_for(*field_names: str):
        fields = DAFieldList()
        for field_name in field_names:
            field = fields.appendObject()
            field.source_document_type = "pdf"
            field.fill_in_pdf_attributes(
                (field_name, "", 0, [0, 0, 100, 20], "/Tx"), {}
            )
        fields.gathered = True
        return fields.get_person_candidates()

    def test_python_keywords_are_not_people(self):
        self.assertNotIn("from", self._candidates_for("from_phone_number"))
        self.assertNotIn("class", self._candidates_for("class_name_first"))

    def test_python_builtins_are_not_people(self):
        self.assertNotIn("list", self._candidates_for("list_name_first"))
        self.assertNotIn("type", self._candidates_for("type_name_first"))

    def test_docassemble_reserved_names_are_not_people(self):
        self.assertNotIn("nav", self._candidates_for("nav_name_first"))
        self.assertNotIn("x", self._candidates_for("x_name_first"))

    def test_ordinary_names_still_become_people(self):
        candidates = self._candidates_for("inspector_name_first", "landlord_email")
        self.assertIn("inspector", candidates)
        self.assertIn("landlord", candidates)

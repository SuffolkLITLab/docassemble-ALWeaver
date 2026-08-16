# do not pre-load
import unittest
from .interview_generator import (
    DAFieldList,
    get_variable_name_warnings,
    get_pdf_validation_errors,
    get_unhandled_field_type_warnings,
    pdf_field_type_str,
    DAField,
    merged_field_names,
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
        """`have_served_other_party_email` is a yes/no about how service happened.

        The Weaver used to read the trailing `_email` as proof that
        `have_served_other_party` was a list of people, and declared
        `have_served_other_party: ALPeopleList` in the generated interview.
        """
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
        self.assertNotIn(
            "have_served_other_party", fields.get_person_candidates(custom_only=True)
        )
        # An author who disagrees can still say it is a person
        fields.mark_people_as_builtins(["have_served_other_party"])
        self.assertIn("have_served_other_party", fields.custom_people_plurals.values())

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


class test_rename_variables_are_valid_to_docassemble(unittest.TestCase):
    """Check the generated variable names against Docassemble's own validator.

    `invalid_variable_name` in `docassemble.base.parse` rejects anything
    containing `(`, `)`, `{`, `}`, `*`, `^` or `#`, which is what produced
    `Missing or invalid variable name "rename_fields['form1[0].#pageSet[0]...']"`
    and stopped the rename screen from loading at all.
    """

    AWKWARD_NAMES = [
        "form1[0].#pageSet[0].Page1[0].TextField4[1]",
        "form1[0].BodyPage1[0].S1[0].CheckBox1[0]",
        "weird (parens) and {braces}",
        "star*and^caret",
        "plain_name",
    ]

    def test_the_old_scheme_really_was_rejected(self):
        from docassemble.base.parse import invalid_variable_name

        old_style = f"rename_fields['{self.AWKWARD_NAMES[0]}']"
        self.assertTrue(invalid_variable_name(old_style))

    def test_every_generated_variable_is_accepted(self):
        from docassemble.base.parse import invalid_variable_name

        for entry in rename_field_screen_fields(self.AWKWARD_NAMES):
            with self.subTest(field=entry["field"]):
                self.assertFalse(invalid_variable_name(entry["field"]))


class test_merged_field_names(unittest.TestCase):
    """FormFyxer's normalization can give two different fields the same name.

    When it does, both PDF fields end up writing the same answer. The author
    needs to see which ones so they can pull them back apart.
    """

    @staticmethod
    def _field(*raw_field_names):
        field = DAField()
        field.fill_in_pdf_attributes(
            (raw_field_names[0], "", 0, [0, 0, 100, 20], "/Tx"), {}
        )
        field.raw_field_names = list(raw_field_names)
        return field

    def test_differently_named_fields_that_merged(self):
        fields = [
            self._field("users1_name_first", "users1_name_full"),
            self._field("docket_number"),
        ]
        self.assertEqual(
            merged_field_names(fields), ["users1_name_first", "users1_name_full"]
        )

    def test_repeats_of_one_field_are_not_a_merge(self):
        """`plaintiffs__3` and `plaintiffs__4` are the same field twice."""
        fields = [self._field("plaintiffs__3", "plaintiffs__4")]
        self.assertEqual(merged_field_names(fields), [])

    def test_merged_fields_come_first_on_the_rename_screen(self):
        names = ["a_field", "users1_name_first", "b_field", "users1_name_full"]
        screen_fields = rename_field_screen_fields(
            names, ["users1_name_first", "users1_name_full"]
        )
        self.assertEqual(
            [entry["label"] for entry in screen_fields],
            ["users1_name_first", "users1_name_full", "a_field", "b_field"],
        )

    def test_reordering_keeps_each_answer_pointed_at_its_own_field(self):
        names = ["a_field", "users1_name_first", "b_field", "users1_name_full"]
        screen_fields = rename_field_screen_fields(names, ["users1_name_full"])
        by_label = {entry["label"]: entry["field"] for entry in screen_fields}
        self.assertEqual(by_label["a_field"], "rename_fields[0]")
        self.assertEqual(by_label["users1_name_full"], "rename_fields[3]")

    def test_merged_fields_explain_themselves(self):
        screen_fields = rename_field_screen_fields(["x", "y"], ["y"])
        by_label = {entry["label"]: entry for entry in screen_fields}
        self.assertIn("help", by_label["y"])
        self.assertNotIn("help", by_label["x"])

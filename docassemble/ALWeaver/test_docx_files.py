# do not pre-load
import unittest
from .interview_generator import (
    DAFieldList,
    get_docx_variables,
    is_reserved_docx_label,
    get_pdf_variable_name_matches,
)
from .validate_template_files import matching_reserved_names
from docassemble.base.util import DAStaticFile
from docx2python import docx2python
from pathlib import Path

import docassemble.base.functions


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


class test_docxs(unittest.TestCase):
    def test_matching_reserved_names_uses_base_name(self):
        self.assertEqual(
            matching_reserved_names({"list[0]", "class.attribute", "url_args[0]"}),
            {"list", "class", "url_args"},
        )
        self.assertEqual(
            matching_reserved_names(
                {"list[0]", "class.attribute", "url_args[0]"},
                keywords_and_builtins_only=True,
            ),
            {"list", "class"},
        )

    def test_unmap_suffixes(self):
        unmap_suffixes_file = Path(__file__).parent / "test/unmap_suffixes.docx"
        docx_data = docx2python(unmap_suffixes_file)
        text = docx_data.text
        all_vars = get_docx_variables(text)
        self.assertEqual(len(all_vars), 9, str(all_vars))
        self.assertIn("children[0].phone_number", all_vars)
        self.assertIn("children[1].birthdate", all_vars)
        self.assertIn("children[0].birthdate", all_vars)
        self.assertIn("children[0].birthdate", all_vars)
        self.assertIn("children[0].name.first", all_vars)
        self.assertIn("children[0].mailing_address.address", all_vars)
        self.assertIn("children[0].mailing_address.county", all_vars)
        self.assertIn("children[0].address.address", all_vars)
        self.assertIn("children[0].address.county", all_vars)
        self.assertIn("milkman.attorney.firm", all_vars)

    def test_whitespace_control_markers(self):
        """`-` and `+` right next to the `%` shouldn't hide the statement."""
        all_vars = get_docx_variables(
            "{%- if trimmed_var -%}{% endif %}"
            "{%+ if untrimmed_var +%}{% endif %}"
            "{%p- if paragraph_var -%}{% endif %}"
            "{%tr for row in table_rows %}{% endfor %}"
        )
        self.assertEqual(
            all_vars,
            {"trimmed_var", "untrimmed_var", "paragraph_var", "table_rows"},
        )

    def test_elif_statements(self):
        all_vars = get_docx_variables(
            "{%p if first_var %}{%p elif second_var %}{%p else %}{%p endif %}"
        )
        self.assertEqual(all_vars, {"first_var", "second_var"})

    def test_in_operator(self):
        all_vars = get_docx_variables("{%p if needle_var in haystack_var %}{% endif %}")
        self.assertEqual(all_vars, {"needle_var", "haystack_var"})

    def test_variables_on_either_side_of_a_comparison(self):
        all_vars = get_docx_variables(
            "{%p if 5 == right_side_var %}{% endif %}"
            "{%p if left_side_var != other_side_var %}{% endif %}"
        )
        self.assertEqual(
            all_vars, {"right_side_var", "left_side_var", "other_side_var"}
        )

    def test_operators_and_literals_are_not_variables(self):
        all_vars = get_docx_variables(
            "{%p if not a_var and b_var is defined %}{% endif %}"
            '{%p if c_var == "final" and d_var != None %}{% endif %}'
        )
        self.assertEqual(all_vars, {"a_var", "b_var", "c_var", "d_var"})

    def test_attributes_and_filters_do_not_start_new_variables(self):
        all_vars = get_docx_variables(
            "{%p if users[0].name.first %}{% endif %}"
            "{%p if some_var | length %}{% endif %}"
        )
        self.assertEqual(all_vars, {"users[0].name.first", "some_var"})

    def test_reserved_docx_labels(self):
        reserved_labels_files = (
            Path(__file__).parent / "test/reserved_docx_variables.docx"
        )
        docx_data = docx2python(reserved_labels_files)
        text = docx_data.text
        all_vars = get_docx_variables(text)
        reserved_labels = []
        for label in all_vars:
            if is_reserved_docx_label(label):
                reserved_labels.append(label)
        self.assertEqual(len(reserved_labels), 2, str(reserved_labels))
        self.assertIn("trial_court.address.county", reserved_labels)
        self.assertIn("users[0].address.address", reserved_labels)
        self.assertNotIn("users.address.zip", reserved_labels)

    def test_actually_reserved_keywords(self):
        reserved_keywords_docx = (
            Path(__file__).parent / "test/docx_file_with_reserved_keywords.docx"
        )
        docassemble.base.functions.this_thread.current_question = type("", (), {})
        docassemble.base.functions.this_thread.current_question.package = "ALWeaver"
        da_docx = MockDAStaticFile(
            full_path=str(reserved_keywords_docx),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        fields = DAFieldList()
        fields.add_fields_from_file(da_docx)
        fields.gathered = True
        self.assertEqual(len(fields.reserved()), 2)
        self.assertEqual(len(fields.builtins()), 1)
        self.assertEqual(len(fields.custom()), 2)

    def test_pdf_variables_in_docx(self):
        pdf_variables_file = Path(__file__).parent / "test/pdf_variables_in_docx.docx"

        matching_fields = get_pdf_variable_name_matches(pdf_variables_file)
        self.assertIn(("petitioner_email", "petitioners[0].email"), matching_fields)
        self.assertIn(
            ("users1_mailing_address", "users[0].mailing_address"), matching_fields
        )
        self.assertNotIn(("users", "users"), matching_fields)
        self.assertNotIn(("users[1]", "users0"), matching_fields)
        self.assertNotIn(("other_parties", "other_parties"), matching_fields)

    def test_no_pdf_variables_in_docx(self):
        pdf_variables_file = (
            Path(__file__).parent / "test/test_docx_no_pdf_field_names.docx"
        )

        matching_fields = get_pdf_variable_name_matches(pdf_variables_file)
        self.assertEqual(len(matching_fields), 0)

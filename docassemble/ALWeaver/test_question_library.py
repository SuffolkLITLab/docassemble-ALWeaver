import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mako.template

import docassemble.ALWeaver.interview_generator as interview_generator_module
from docassemble.ALWeaver.interview_generator import (
    _resolve_template_path,
    fix_id,
    generate_interview_from_path,
)
from docassemble.ALWeaver.question_library import (
    baseline_question_specs,
    singular_label,
)


class FakeField:
    def __init__(self, final_display_var):
        self.final_display_var = final_display_var


class FakeFieldList:
    def __init__(self, fields):
        self._fields = fields

    def builtins(self):
        return self._fields


def fake_interview(builtin_vars, copy_baseline_questions=True):
    return SimpleNamespace(
        all_fields=FakeFieldList([FakeField(var) for var in builtin_vars]),
        copy_baseline_questions=copy_baseline_questions,
    )


def person_object(name, params=None, object_type="ALPeopleList"):
    return SimpleNamespace(name=name, type=object_type, params=params or {})


def kinds_for(specs, var):
    return [spec["kind"] for spec in specs if spec["var"] == var]


class TestSingularLabel(unittest.TestCase):
    def test_assembly_line_names_use_assembly_lines_own_singular(self):
        self.assertEqual(singular_label("children"), "child")
        self.assertEqual(singular_label("other_parties"), "other party")
        self.assertEqual(singular_label("witnesses"), "witness")
        self.assertEqual(singular_label("users"), "user")

    def test_unknown_names_fall_back_to_a_guess(self):
        self.assertEqual(singular_label("landlords"), "landlord")
        self.assertEqual(singular_label("agencies"), "agency")

    def test_a_name_that_is_already_singular_is_left_alone(self):
        self.assertEqual(singular_label("my_user"), "my user")


class TestWhichQuestionsGetCopied(unittest.TestCase):
    def test_a_plain_list_gets_the_whole_gather_flow(self):
        specs = baseline_question_specs(
            fake_interview(["parents[0].name.first"]),
            [person_object("parents")],
        )
        self.assertEqual(
            kinds_for(specs, "parents"),
            ["there_are_any", "names", "there_is_another"],
        )

    def test_a_list_that_already_knows_it_has_members_skips_there_are_any(self):
        specs = baseline_question_specs(
            fake_interview(["users[0].name.first"]),
            [person_object("users", {"there_are_any": True})],
        )
        self.assertEqual(kinds_for(specs, "users"), ["names", "there_is_another"])

    def test_a_list_of_exactly_one_only_asks_for_the_name(self):
        specs = baseline_question_specs(
            fake_interview(["decedents[0].name.first"]),
            [person_object("decedents", {"ask_number": True, "target_number": 1})],
        )
        self.assertEqual(kinds_for(specs, "decedents"), ["names"])

    def test_a_counted_list_asks_how_many_instead_of_there_is_another(self):
        specs = baseline_question_specs(
            fake_interview(["children[0].name.first"]),
            [person_object("children", {"ask_number": True})],
        )
        self.assertEqual(kinds_for(specs, "children"), ["how_many", "names"])

    def test_attribute_questions_follow_the_fields_the_form_uses(self):
        specs = baseline_question_specs(
            fake_interview(
                [
                    "users[0].name.first",
                    "users[0].address.zip",
                    "users[0].birthdate",
                    "users[0].gender_female",
                    "users[0].pronouns",
                    "users[0].language",
                    "users[0].email",
                    "users[0].phone_number",
                ]
            ),
            [person_object("users", {"there_are_any": True})],
        )
        self.assertEqual(
            kinds_for(specs, "users"),
            [
                "names",
                "there_is_another",
                "address",
                "birthdate",
                "gender",
                "pronouns",
                "language",
                "phone_number",
                "email",
            ],
        )

    def test_attributes_assembly_line_has_no_reusable_question_for_are_skipped(self):
        specs = baseline_question_specs(
            fake_interview(["users[0].signature", "users[0].favorite_color"]),
            [person_object("users", {"there_are_any": True})],
        )
        self.assertEqual(kinds_for(specs, "users"), ["names", "there_is_another"])

    def test_method_calls_among_the_built_ins_are_ignored(self):
        specs = baseline_question_specs(
            fake_interview(["users[0].address.on_one_line()"]),
            [person_object("users", {"there_are_any": True})],
        )
        self.assertEqual(kinds_for(specs, "users"), ["names", "there_is_another"])

    def test_a_standalone_individual_gets_a_name_question_not_a_gather_flow(self):
        specs = baseline_question_specs(
            fake_interview(["landlord.name.first", "landlord.address.city"]),
            [person_object("landlord", object_type="ALIndividual")],
        )
        self.assertEqual(kinds_for(specs, "landlord"), ["name", "address"])

    def test_objects_assembly_line_manages_itself_are_left_alone(self):
        # `plaintiffs` never reaches the generated `objects:` block, so nothing
        # about it should be copied in even though fields reference it.
        specs = baseline_question_specs(
            fake_interview(["plaintiffs[0].name.first", "users[0].name.first"]),
            [person_object("users", {"there_are_any": True})],
        )
        self.assertEqual({spec["var"] for spec in specs}, {"users"})

    def test_turning_the_option_off_copies_nothing(self):
        specs = baseline_question_specs(
            fake_interview(["users[0].name.first"], copy_baseline_questions=False),
            [person_object("users")],
        )
        self.assertEqual(specs, [])


class TestRenderedQuestions(unittest.TestCase):
    """Render every question kind and check the YAML it produces."""

    @classmethod
    def setUpClass(cls):
        defs_text = Path(_resolve_template_path("output_defs.mako")).read_text(
            encoding="utf-8"
        )
        library_text = Path(_resolve_template_path("question_library.mako")).read_text(
            encoding="utf-8"
        )
        cls.template = mako.template.Template(  # nosec B702
            defs_text + "\n" + library_text, input_encoding="utf-8"
        )

    def render(self, kind, var="parents", is_list=True):
        entry = {
            "kind": kind,
            "var": var,
            "is_list": is_list,
            "singular": singular_label(var) if is_list else var.replace("_", " "),
            "plural": var.replace("_", " "),
        }
        return self.template.get_def("baseline_question_yaml").render(
            entry=entry, fix_id=fix_id
        )

    def all_kinds(self):
        return [
            "there_are_any",
            "how_many",
            "names",
            "there_is_another",
            "address",
            "mailing_address",
            "birthdate",
            "gender",
            "pronouns",
            "language",
            "phone_number",
            "mobile_number",
            "email",
        ]

    def test_every_kind_produces_a_docassemble_block(self):
        from dayamlchecker.yaml_structure import find_errors_from_string

        for var, is_list in (
            ("parents", True),
            ("users", True),
            ("other_parties", True),
            ("landlord", False),
        ):
            kinds = self.all_kinds() if is_list else ["name", "address", "email"]
            for kind in kinds:
                with self.subTest(kind=kind, var=var):
                    rendered = self.render(kind, var=var, is_list=is_list)
                    self.assertTrue(rendered.startswith("---\n"), rendered)
                    self.assertIn("id: ", rendered)
                    errors = find_errors_from_string(rendered, input_file="copy.yml")
                    self.assertFalse(
                        errors,
                        "\n".join(
                            str(getattr(error, "err_str", "") or error)
                            for error in errors
                        ),
                    )

    def test_nothing_generic_survives_the_copy(self):
        for kind in self.all_kinds():
            with self.subTest(kind=kind):
                rendered = self.render(kind)
                self.assertNotIn("generic object", rendered)
                # A bare `x` is what makes the AssemblyLine originals uneditable.
                self.assertIsNone(re.search(r"(?<![\w.])x[.\[]", rendered), rendered)
                self.assertIn("parents", rendered)

    def test_questions_call_assembly_lines_field_helpers_rather_than_inlining_them(
        self,
    ):
        """The `_fields()` methods stay in the copies.

        Expanding them by hand would freeze today's address/name/gender/pronoun
        markup into every generated interview and lose the AssemblyLine upgrades
        that flow through those methods.
        """
        expected_helper = {
            "names": "name_fields(",
            "address": "address_fields(",
            "mailing_address": "address_fields(",
            "gender": "gender_fields(",
            "pronouns": "pronoun_fields(",
            "language": "language_fields(",
        }
        for var in ("parents", "users", "other_parties"):
            for kind, helper in expected_helper.items():
                with self.subTest(kind=kind, var=var):
                    rendered = self.render(kind, var=var)
                    self.assertIn(helper, rendered)
                    # The pieces a helper is responsible for must not also be
                    # spelled out field by field.
                    self.assertNotIn("address_label", rendered)
                    self.assertNotIn("states_list(", rendered)

    def test_list_questions_are_written_against_the_indexed_item(self):
        self.assertIn("parents[i].name_fields()", self.render("names"))
        self.assertIn("parents[i].address_fields(", self.render("address"))
        self.assertIn("parents.there_is_another", self.render("there_is_another"))

    def test_a_standalone_individual_is_written_without_an_index(self):
        rendered = self.render("name", var="landlord", is_list=False)
        self.assertIn("landlord.name_fields()", rendered)
        self.assertNotIn("landlord[i]", rendered)

    def test_users_get_assembly_lines_user_specific_wording(self):
        self.assertIn("What is your name?", self.render("names", var="users"))
        self.assertIn(
            "Is anyone else on your side of this case?",
            self.render("there_is_another", var="users"),
        )
        self.assertIn("What is your address?", self.render("address", var="users"))

    def test_other_parties_get_assembly_lines_opposing_party_wording(self):
        self.assertIn(
            "**defendant** or respondent",
            self.render("names", var="other_parties"),
        )
        self.assertIn(
            'name_fields(person_or_business="unsure")',
            self.render("names", var="other_parties"),
        )
        self.assertIn(
            "Is there a **defendant** or respondent in this case?",
            self.render("there_are_any", var="other_parties"),
        )

    def test_other_lists_do_not_get_the_user_specific_wording(self):
        self.assertNotIn("al_person_answering", self.render("names"))
        self.assertNotIn("al_person_answering", self.render("address"))
        self.assertNotIn("user_started_case", self.render("names"))


class TestGeneratedInterviewIncludesTheCopies(unittest.TestCase):
    @staticmethod
    def _offline_cluster_screens(fields, tools_token=None):
        del tools_token
        unique_fields = list(dict.fromkeys(fields or []))
        return {
            f"Screen {index // 4 + 1}": unique_fields[index : index + 4]
            for index in range(0, len(unique_fields), 4)
        }

    def _generate(self, **kwargs):
        pdf_path = (
            Path(__file__).parent / "test/test_petition_to_enforce_sanitary_code.pdf"
        )
        with patch.object(
            interview_generator_module.formfyxer,
            "cluster_screens",
            side_effect=self._offline_cluster_screens,
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                result = generate_interview_from_path(
                    str(pdf_path),
                    output_dir=tmpdir,
                    create_package_zip=False,
                    include_next_steps=False,
                    **kwargs,
                )
                return Path(result.yaml_path).read_text(encoding="utf-8")

    def test_the_copies_are_written_in_by_default(self):
        yaml_text = self._generate()
        self.assertIn("users[i].name_fields()", yaml_text)
        self.assertIn("users.there_is_another", yaml_text)
        self.assertIn("other_parties[i].address_fields(", yaml_text)

    def test_every_copied_object_is_declared_in_the_objects_block(self):
        yaml_text = self._generate()
        declared = set(re.findall(r"^  - (\w+): ALPeopleList", yaml_text, re.MULTILINE))
        copied = set(
            re.findall(r"^      (\w+)\[i\]\.name_fields\(\)", yaml_text, re.MULTILINE)
        )
        self.assertTrue(copied)
        self.assertTrue(copied <= declared, copied - declared)

    def test_turning_the_option_off_leaves_the_interview_as_it_was(self):
        yaml_text = self._generate(copy_baseline_questions=False)
        self.assertNotIn("name_fields()", yaml_text)
        self.assertNotIn("copies of the questions in AssemblyLine", yaml_text)


if __name__ == "__main__":
    unittest.main()

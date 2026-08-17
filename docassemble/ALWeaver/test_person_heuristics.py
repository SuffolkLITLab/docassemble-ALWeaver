# do not pre-load
"""Which field names should, and should not, become lists of people.

Deciding that `X_name` means there is a person called `X` is a guess, and a
wrong guess is expensive: the generated interview declares `X: ALPeopleList`
and then makes the user build a whole list of people to fill in one text field.

The names in `REAL_WORLD_CASES` are taken verbatim from court forms in the
SuffolkLITLab packages, so the rules stay tied to shapes that actually turn up.
"""

import collections
import json
import random
import unittest
from pathlib import Path

from .interview_generator import (
    DAFieldGroup,
    DAFieldList,
    ParsingException,
    is_reserved_label,
    person_prefix_needs_corroboration,
    unlikely_person_prefix,
)
from .generator_constants import generator_constants as gc

# (description, field names, prefixes that must be people, prefixes that must not)
REAL_WORLD_CASES = [
    (
        "attributes of an indexed AssemblyLine person",
        ["users1_cell_phone", "users1_work_phone", "users1_notary_signature"],
        [],
        ["users1_cell", "users1_work", "users1_notary"],
    ),
    (
        "attributes of a named AssemblyLine person",
        [
            "caregivers1_notary_signature",
            "user_affidavit_signature",
            "user_employer_name_address_phone",
            "spouse_employer_name_address_phone",
        ],
        [],
        [
            "caregivers1_notary",
            "user_affidavit",
            "user_employer_name_address",
            "spouse_employer_name_address",
        ],
    ),
    (
        "a reserved whole word is not evidence of a person",
        ["user_preferred_language"],
        [],
        ["user_preferred"],
    ),
    (
        "events and documents are not people",
        [
            "hearing_by_phone",
            "hearing_email",
            "notice_type_email",
            "other_action_court_name",
            "previous_child_support_ordered_court_name",
        ],
        [],
        [
            "hearing",
            "hearing_by",
            "notice_type",
            "other_action_court",
            "previous_child_support_ordered_court",
        ],
    ),
    (
        "questions are not people",
        [
            "is_attorney_submission_method_email",
            "have_served_other_party_email",
            "receiving_benefits_name",
        ],
        [],
        [
            "is_attorney_submission_method",
            "have_served_other_party",
            "receiving_benefits",
        ],
    ),
    (
        "a name that describes a name is not a person",
        [
            "case_name",
            "new_name",
            "new_last_name",
            "current_name",
            "mothers_maiden_name",
            "plaintiff_previous_name",
            "debts_pay_debts_in_own_name",
            "to_name",
        ],
        [],
        [
            "case",
            "new",
            "new_last",
            "current",
            "mothers_maiden",
            "plaintiff_previous",
            "debts_pay_debts_in_own",
            "to",
        ],
    ),
    (
        "single letters are not names",
        ["d2_name", "d2_phone", "p_name", "p_phone"],
        [],
        ["d", "p"],
    ),
    (
        "property is not a person",
        [
            "real_properties1_address_on_one_line",
            "some_identifier_mail_address_address",
        ],
        [],
        ["real_properties", "some_identifier_mail"],
    ),
    (
        "an index is not part of the name",
        ["dependent_1_age", "dependent_2_age", "dependent_3_age"],
        ["dependent"],
        ["dependent_"],
    ),
    (
        "trailing underscore before the index",
        [
            "other_case_other_parties_1_address_on_one_line",
            "other_case_other_parties_2_address_on_one_line",
        ],
        ["other_case_other_parties"],
        ["other_case_other_parties_"],
    ),
    (
        "two signals overrule a reserved leading word",
        [
            "guardian_successors1_name_first",
            "guardian_successors1_name_last",
            "guardian_successors2_name_first",
        ],
        ["guardian_successors"],
        [],
    ),
    (
        "ordinary custom people are still found",
        [
            "patient1_name_first",
            "patient1_address_on_one_line",
            "disclosee_name",
            "disclosee_phone",
            "emergency_contact_name",
            "emergency_contact_phone",
            "household_member1_name",
            "household_member1_age",
        ],
        ["patient", "disclosee", "emergency_contact", "household_member"],
        [],
    ),
]


def candidates_for(field_names, custom_only=True):
    fields = DAFieldList()
    for field_name in field_names:
        field = fields.appendObject()
        field.source_document_type = "pdf"
        field.fill_in_pdf_attributes((field_name, "", 0, [0, 0, 100, 20], "/Tx"), {})
    fields.gathered = True
    return fields.get_person_candidates(custom_only=custom_only)


class TestRealWorldFieldNames(unittest.TestCase):
    def test_cases(self):
        for description, field_names, expected, rejected in REAL_WORLD_CASES:
            with self.subTest(case=description):
                found = candidates_for(field_names)
                for name in expected:
                    self.assertIn(name, found, f"{description}: lost {name}")
                for name in rejected:
                    self.assertNotIn(name, found, f"{description}: kept {name}")


class TestUnlikelyPersonPrefix(unittest.TestCase):
    def test_shape(self):
        for prefix in ("", "d", "ab", "Patient", "patient_", "3rd_party", "a b"):
            with self.subTest(prefix=prefix):
                self.assertIsNotNone(unlikely_person_prefix(prefix))

    def test_plausible_names_pass(self):
        for prefix in (
            "patient",
            "disclosee",
            "emergency_contact",
            "guardian_successors",
            "next_friend",
            "landlord",
            "responsible_parents",
        ):
            with self.subTest(prefix=prefix):
                self.assertIsNone(unlikely_person_prefix(prefix))

    def test_reason_is_explanatory(self):
        reason = unlikely_person_prefix("case")
        self.assertIsNotNone(reason)
        self.assertIn("case", reason)


class TestPersonPrefixNeedsCorroboration(unittest.TestCase):
    def test_names_built_on_a_reserved_person(self):
        for prefix in ("user_affidavit", "spouse_employer", "guardian_successors"):
            with self.subTest(prefix=prefix):
                self.assertTrue(person_prefix_needs_corroboration(prefix))

    def test_unrelated_names_stand_on_their_own(self):
        for prefix in ("patient", "disclosee", "emergency_contact", "landlord"):
            with self.subTest(prefix=prefix):
                self.assertFalse(person_prefix_needs_corroboration(prefix))

    def test_one_signal_is_not_enough_but_two_are(self):
        self.assertNotIn("user_helper", candidates_for(["user_helper_name_first"]))
        self.assertIn(
            "user_helper",
            candidates_for(["user_helper_name_first", "user_helper_phone_number"]),
        )


class TestPersonCandidateFuzzing(unittest.TestCase):
    """Throw generated field names at the guesser and check what comes back.

    Whatever the rules decide, the answer has to be usable: every candidate is
    written into the generated interview as `objects:\\n  - <name>: ALPeopleList`,
    so a candidate that isn't a clean variable name breaks the whole file.
    """

    WORDS = [
        # plausible people
        "patient",
        "landlord",
        "tenant",
        "guardian",
        "witness",
        "inspector",
        "disclosee",
        "custodian",
        "friend",
        "member",
        "parents",
        "child",
        # things, moments and attributes
        "case",
        "court",
        "hearing",
        "notice",
        "order",
        "property",
        "debt",
        "account",
        "income",
        "date",
        "type",
        "status",
        "method",
        "address",
        # AssemblyLine prefixes
        "users",
        "user",
        "spouse",
        "caregivers",
        "other_parties",
        "trial_court",
        # question words and connectives
        "is",
        "has",
        "have",
        "will",
        "by",
        "to",
        "of",
        "for",
        "new",
        "current",
        # awkward pieces
        "",
        "_",
        "1",
        "x",
        "A",
        "ZZ",
    ]
    SUFFIXES = sorted(gc.PEOPLE_SUFFIXES_MAP.keys())

    def _random_field_name(self, rng):
        parts = [rng.choice(self.WORDS) for _ in range(rng.randint(1, 4))]
        name = "_".join(part for part in parts if part)
        if rng.random() < 0.4:
            name += str(rng.randint(0, 9))
        return name + rng.choice(self.SUFFIXES)

    def test_generated_names_never_produce_an_unusable_object(self):
        from docassemble.base.parse import invalid_variable_name

        rng = random.Random(20260816)
        for round_number in range(60):
            names = [self._random_field_name(rng) for _ in range(rng.randint(1, 12))]
            with self.subTest(round=round_number, names=names):
                try:
                    found = candidates_for(names, custom_only=False)
                except Exception as exc:  # a parsing error is a separate concern
                    self.assertEqual(type(exc).__name__, "ParsingException", repr(exc))
                    continue
                for candidate in found:
                    self.assertTrue(
                        candidate.isidentifier(), f"{candidate!r} is not an identifier"
                    )
                    self.assertFalse(
                        invalid_variable_name(candidate),
                        f"Docassemble would reject `objects: - {candidate}:`",
                    )
                    self.assertRegex(candidate, r"^[a-z][a-z0-9_]*[a-z0-9]$")
                    self.assertGreaterEqual(len(candidate), 3)
                    self.assertIsNone(unlikely_person_prefix(candidate))

    def test_guessing_is_deterministic(self):
        rng = random.Random(11)
        for _ in range(20):
            names = [self._random_field_name(rng) for _ in range(rng.randint(1, 8))]
            with self.subTest(names=names):
                try:
                    first = candidates_for(names, custom_only=False)
                    second = candidates_for(names, custom_only=False)
                except Exception:
                    continue
                self.assertEqual(first, second)

    def test_extra_fields_never_remove_a_person(self):
        """Adding a field can only add evidence, never take it away."""
        rng = random.Random(7)
        for _ in range(20):
            names = [self._random_field_name(rng) for _ in range(rng.randint(1, 6))]
            extra = self._random_field_name(rng)
            with self.subTest(names=names, extra=extra):
                try:
                    before = candidates_for(names, custom_only=False)
                    after = candidates_for(names + [extra], custom_only=False)
                except Exception:
                    continue
                self.assertTrue(before <= after, f"lost {before - after}")


class TestAgainstRealPdfFieldNames(unittest.TestCase):
    """Properties that have to hold for every form, not just the tuned ones.

    `test/real_pdf_field_names.json` holds the AcroForm field names of 38 court
    forms taken from the SuffolkLITLab packages. The rules were tuned against a
    larger set of the same kind, so this is the guard against tuning them into
    something that only works on the examples in `REAL_WORLD_CASES`.
    """

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / "test/real_pdf_field_names.json"
        cls.corpus = json.loads(path.read_text(encoding="utf-8"))

    def test_every_invented_person_is_a_usable_object_name(self):
        """Each one is written out as `objects:\\n  - <name>: ALPeopleList`."""
        from docassemble.base.parse import invalid_variable_name

        for form, field_names in self.corpus.items():
            with self.subTest(form=form):
                try:
                    people = candidates_for(field_names, custom_only=False)
                except ParsingException:
                    continue  # the form's own names are wrong; reported elsewhere
                for person in people:
                    self.assertTrue(person.isidentifier(), person)
                    self.assertFalse(invalid_variable_name(person), person)
                    self.assertIsNone(unlikely_person_prefix(person), person)


class TestAutomaticMarking(unittest.TestCase):
    """Recognising a person is only half of it; the fields have to be marked.

    `auto_mark_people_as_builtins` is what the REST API, the editor's upload
    and `generate_interview_from_path` rely on. Nobody confirms the guess
    there, so what it marks is what ships.
    """

    @staticmethod
    def _pdf(field_names):
        fields = DAFieldList()
        for field_name in field_names:
            field = fields.appendObject()
            field.source_document_type = "pdf"
            field.group = (
                DAFieldGroup.BUILT_IN
                if is_reserved_label(field_name)
                else DAFieldGroup.CUSTOM
            )
            field.fill_in_pdf_attributes(
                (field_name, "", 0, [0, 0, 100, 20], "/Tx"), {}
            )
        fields.gathered = True
        fields.auto_label_fields()
        fields.auto_mark_people_as_builtins()
        return fields

    @staticmethod
    def _docx(field_names):
        fields = DAFieldList()
        for field_name in field_names:
            field = fields.appendObject()
            field.source_document_type = "docx"
            field.group = DAFieldGroup.CUSTOM
            field.fill_in_docx_attributes(field_name)
        fields.gathered = True
        fields.auto_label_fields()
        fields.auto_mark_people_as_builtins()
        return fields

    @staticmethod
    def _by_variable(fields):
        return {field.variable: field for field in fields}

    def test_a_recognised_person_becomes_an_indexed_object(self):
        fields = self._pdf(
            ["patient1_name_first", "patient1_phone_number", "patient2_name_first"]
        )
        self.assertEqual(dict(fields.custom_people_plurals), {"patient": "patient"})
        by_variable = self._by_variable(fields)
        self.assertEqual(
            by_variable["patient1_name_first"].final_display_var,
            "patient[0].name.first",
        )
        self.assertEqual(
            by_variable["patient2_name_first"].final_display_var,
            "patient[1].name.first",
        )

    def test_a_recognised_person_stops_needing_its_own_questions(self):
        """BUILT_IN means AssemblyLine's question library handles it."""
        fields = self._pdf(["patient1_name_first", "patient1_phone_number", "a_note"])
        by_variable = self._by_variable(fields)
        self.assertEqual(
            by_variable["patient1_name_first"].group, DAFieldGroup.BUILT_IN
        )
        self.assertEqual(by_variable["a_note"].group, DAFieldGroup.CUSTOM)

    def test_one_signal_pulls_the_rest_of_the_person_along(self):
        """`_phone` identifies the person; `_name` then belongs to them too."""
        fields = self._pdf(["disclosee_name", "disclosee_phone"])
        by_variable = self._by_variable(fields)
        self.assertEqual(
            by_variable["disclosee_name"].final_display_var, "disclosee[0]"
        )
        self.assertEqual(
            by_variable["disclosee_phone"].final_display_var,
            "disclosee[0].phone_number",
        )

    def test_nothing_is_marked_when_nothing_looks_like_a_person(self):
        fields = self._pdf(["case_name", "hearing_by_phone", "docket_number"])
        self.assertEqual(dict(fields.custom_people_plurals), {})
        by_variable = self._by_variable(fields)
        self.assertEqual(by_variable["case_name"].final_display_var, "case_name")
        self.assertEqual(
            by_variable["hearing_by_phone"].final_display_var, "hearing_by_phone"
        )

    def test_docx_variables_are_marked_the_same_way(self):
        fields = self._docx(
            ["patient[0].name.first", "patient[0].phone_number", "a_note"]
        )
        self.assertEqual(dict(fields.custom_people_plurals), {"patient": "patient"})
        by_variable = self._by_variable(fields)
        self.assertEqual(
            by_variable["patient[0].name.first"].group, DAFieldGroup.BUILT_IN
        )
        self.assertEqual(by_variable["a_note"].group, DAFieldGroup.CUSTOM)

    def test_how_many_of_a_custom_person_the_form_has_room_for(self):
        """Without this the generated `objects` block leaves the list bare."""
        one = self._pdf(["patient1_name_first", "patient1_phone_number"])
        self.assertEqual(one._guess_people_quantities().get("patient"), "one")

        more = self._pdf(
            ["patient1_name_first", "patient1_phone_number", "patient2_name_first"]
        )
        self.assertEqual(more._guess_people_quantities().get("patient"), "more")

    def test_built_in_people_still_get_their_quantity(self):
        fields = self._pdf(["user_name_first", "user2_name_first"])
        self.assertEqual(fields._guess_people_quantities().get("users"), "more")

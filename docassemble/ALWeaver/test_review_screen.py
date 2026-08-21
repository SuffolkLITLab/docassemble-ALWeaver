# do not pre-load

import unittest

from .review_screen import (
    ReviewEntry,
    build_review_entries,
    table_edit_attributes,
)


class _Field:
    """The parts of a DAField the review-screen builder actually reads."""

    def __init__(
        self,
        variable,
        *,
        label=None,
        field_type="text",
        group="custom",
        settable=None,
    ):
        self.variable = variable
        self.final_display_var = variable
        self._settable = settable or variable
        self.label = label or variable
        self.has_label = label is not None
        self.field_type = field_type
        self.group = type("Group", (), {"value": group})()

    def get_settable_var(self):
        return self._settable


class _Collection:
    def __init__(self, var_name, var_type, fields, attribute_map=None):
        self.var_name = var_name
        self.var_type = var_type
        self.fields = fields
        self.attribute_map = attribute_map or {}


class _Screen:
    def __init__(self, question_text, field_list):
        self.question_text = question_text
        self.field_list = field_list


class TestReviewEntries(unittest.TestCase):
    def test_one_entry_per_screen_instead_of_one_per_variable(self):
        """The old review screen listed every loose primitive on its own."""
        rent = _Field("rent_amount", label="Rent amount", field_type="currency")
        inspected = _Field("inspection_yesno", label="Inspected?", field_type="yesno")
        notes = _Field("notes", label="Notes")
        collections = [
            _Collection("rent_amount", "primitive", [rent]),
            _Collection("inspection_yesno", "primitive", [inspected]),
            _Collection("notes", "primitive", [notes]),
        ]
        screens = [_Screen("About the apartment", [rent, inspected, notes])]

        entries = build_review_entries(collections, screens)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].edit_var, "rent_amount")
        self.assertEqual(entries[0].title, "About the apartment")
        self.assertEqual(
            [row.label for row in entries[0].rows],
            ["Rent amount", "Inspected?", "Notes"],
        )

    def test_values_never_force_a_variable_to_be_defined(self):
        """A review screen that asks a question is a review screen with a bug."""
        rent = _Field("rent_amount", label="Rent", field_type="currency")
        yes = _Field("served", label="Served?", field_type="yesno")
        plain = _Field("nickname", label="Nickname")
        collections = [
            _Collection("rent_amount", "primitive", [rent]),
            _Collection("served", "primitive", [yes]),
            _Collection("nickname", "primitive", [plain]),
        ]
        entries = build_review_entries(
            collections, [_Screen("Details", [rent, yes, plain])]
        )
        expressions = [row.expression for row in entries[0].rows]

        self.assertEqual(
            expressions,
            [
                "currency(rent_amount) if defined('rent_amount') else ''",
                "word(yesno(served)) if defined('served') else ''",
                "showifdef('nickname')",
            ],
        )

    def test_a_list_gets_one_revisit_entry_wherever_its_fields_appear(self):
        member = _Field("household[i].name.first", settable="household[i].name.first")
        household = _Collection("household", "list", [member])
        entries = build_review_entries(
            [household], [_Screen("Who lives there?", [member])]
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].edit_var, "household.revisit")
        self.assertEqual(entries[0].list_var, "household")
        self.assertEqual(entries[0].rows, [])

    def test_signatures_are_left_to_the_signature_flow(self):
        signature = _Field("user_signature", group="signature")
        date = _Field("signature_date", field_type="date")
        name = _Field("nickname", label="Nickname")
        collections = [
            _Collection("user_signature", "primitive", [signature]),
            _Collection("signature_date", "primitive", [date]),
            _Collection("nickname", "primitive", [name]),
        ]
        entries = build_review_entries(
            collections, [_Screen("Sign here", [signature, date, name])]
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual([row.label for row in entries[0].rows], ["Nickname"])
        self.assertEqual(entries[0].edit_var, "nickname")

    def test_questions_asked_by_assemblyline_still_get_an_entry(self):
        """`docket_number` is never on a Weaver screen but belongs on the recap."""
        docket = _Field("docket_number", label="Docket number")
        collection = _Collection("docket_number", "primitive", [docket])

        entries = build_review_entries([collection], [docket])

        self.assertEqual([entry.edit_var for entry in entries], ["docket_number"])
        self.assertEqual(entries[0].rows[0].expression, "showifdef('docket_number')")

    def test_entries_follow_the_order_the_interview_asks_for_them(self):
        first = _Field("first_question", label="First")
        second = _Field("second_question", label="Second")
        collections = [
            _Collection("second_question", "primitive", [second]),
            _Collection("first_question", "primitive", [first]),
        ]
        entries = build_review_entries(
            collections, [_Screen("One", [first]), _Screen("Two", [second])]
        )

        self.assertEqual([entry.title for entry in entries], ["One", "Two"])

    def test_an_object_shows_its_name_and_address_as_single_lines(self):
        court = _Collection(
            "trial_court",
            "object",
            [_Field("trial_court.address.county")],
            attribute_map={
                "name": ("name_full()", "name.first"),
                "address": ("address.block()", "address.county"),
            },
        )
        entries = build_review_entries([court], [])

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].edit_var, "trial_court")
        self.assertEqual(
            [(row.label, row.expression) for row in entries[0].rows],
            [
                (
                    "Name",
                    "trial_court.name_full() if defined('trial_court.name.first') else ''",
                ),
                (
                    "Address",
                    "trial_court.address.block() if defined('trial_court.address.county') else ''",
                ),
            ],
        )

    def test_code_and_skipped_fields_have_nothing_to_link_back_to(self):
        code = _Field("computed_total", field_type="code")
        skipped = _Field("ignored", field_type="skip this field")
        collections = [
            _Collection("computed_total", "primitive", [code]),
            _Collection("ignored", "primitive", [skipped]),
        ]
        self.assertEqual(
            build_review_entries(collections, [_Screen("X", [code, skipped])]), []
        )


class TestTableEditAttributes(unittest.TestCase):
    def test_a_signature_is_never_forced_from_a_review_table(self):
        collection = _Collection(
            "plaintiffs",
            "list",
            [],
            attribute_map={
                "name": ("name_full()", "name.first"),
                "address": ("address.block()", "address.zip"),
                "signature": ("signature", "signature"),
                "phone_number": ("phone_number", "phone_number"),
            },
        )
        self.assertEqual(
            table_edit_attributes(collection),
            ["name.first", "address.zip", "phone_number"],
        )

    def test_an_attribute_is_only_followed_up_once(self):
        collection = _Collection(
            "witnesses",
            "list",
            [],
            attribute_map={
                "name": ("name_full()", "name.first"),
                "given_name": ("name_full()", "name.first"),
            },
        )
        self.assertEqual(table_edit_attributes(collection), ["name.first"])


if __name__ == "__main__":
    unittest.main()

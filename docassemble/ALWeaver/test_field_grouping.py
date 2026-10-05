# do not pre-load
import unittest

from .field_grouping import (
    MAX_FIELDS_PER_SCREEN,
    group_fields_into_screens,
    unique_titles,
)


def screens_of(variables):
    return [fields for _title, fields in group_fields_into_screens(variables)]


class TestGroupFieldsIntoScreens(unittest.TestCase):
    def test_a_change_of_topic_starts_a_new_screen(self):
        self.assertEqual(
            screens_of(
                [
                    "notice_type_mail",
                    "notice_type_email",
                    "vehicle_year",
                    "vehicle_make",
                ]
            ),
            [
                ["notice_type_mail", "notice_type_email"],
                ["vehicle_year", "vehicle_make"],
            ],
        )

    def test_no_screen_grows_past_the_limit(self):
        """FormFyxer's keyword fallback once put 180 fields on one screen."""
        variables = [f"income_source_{number}" for number in range(15)]
        screens = screens_of(variables)
        self.assertTrue(all(len(s) <= MAX_FIELDS_PER_SCREEN for s in screens))
        self.assertEqual(sum(screens, []), variables)

    def test_filler_words_do_not_make_one_topic(self):
        self.assertEqual(
            screens_of(
                ["is_tenant_disabled", "is_tenant_elderly", "is_landlord_notified"]
            ),
            [["is_tenant_disabled", "is_tenant_elderly"], ["is_landlord_notified"]],
        )

    def test_loose_single_fields_share_a_screen(self):
        self.assertEqual(
            screens_of(["docket_number", "hearing_date", "judge_name"]),
            [["docket_number", "hearing_date"], ["judge_name"]],
        )

    def test_every_field_lands_once_in_template_order(self):
        variables = ["b_one", "a_one", "b_two", "a_one"]
        self.assertEqual(sum(screens_of(variables), []), ["b_one", "a_one", "b_two"])

    def test_titles_come_from_what_the_fields_share(self):
        titles = [
            title
            for title, _fields in group_fields_into_screens(
                ["notice_type_mail", "notice_type_email", "judge_name"],
                label_for=lambda variable: {"judge_name": "Judge's name"}[variable],
            )
        ]
        self.assertEqual(titles, ["Notice type", "Judge's name"])

    def test_repeated_titles_are_numbered(self):
        self.assertEqual(
            list(unique_titles([("Notice", ["a"]), ("Notice", ["b"])])),
            ["Notice", "Notice 2"],
        )

# do not pre-load
import unittest

from .llm_structure import validated_proposals

CONTEXT = """COURT ACTIVITY RECORD REQUEST
Type of proceeding (check one): Adoption  Name change  Other (specify)
Date of Birth ____  Mother's maiden name ____
If other, describe the proceeding ____"""

FIELDS = {
    "box_c": {"type": "yesno", "pdf": True},
    "is_guardian1_update": {"type": "yesno", "pdf": True},
    "is_guardian2_update": {"type": "yesno", "pdf": True},
    "is_guardian3_update": {"type": "yesno", "pdf": True},
    "date_of_birth": {"type": "text", "pdf": True},
    "case_name": {"type": "text", "pdf": True},
    "proceeding_is": {
        "type": "multiple choice checkboxes",
        "pdf": False,
        "choices": ["adoption", "name_change", "other"],
    },
    "type_of_proceeding_other": {"type": "text", "pdf": True},
    "box_a": {"type": "yesno", "pdf": True},
    "box_b": {"type": "yesno", "pdf": True},
}


def maps(label):
    return {"user_birthdate": "users[0].birthdate.format()"}.get(label)


class TestValidatedProposals(unittest.TestCase):
    def check(self, response):
        return validated_proposals(response, CONTEXT, FIELDS, maps)

    def test_a_remap_needs_a_label_the_weaver_knows_and_a_real_quote(self):
        accepted = self.check(
            {
                "remaps": [
                    {
                        "field": "date_of_birth",
                        "assemblyline_label": "user_birthdate",
                        "evidence": "Date of Birth",
                    },
                    {
                        "field": "case_name",
                        "label": "made_up_label",
                        "evidence": "Date of Birth",
                    },
                    {
                        "field": "case_name",
                        "label": "user_birthdate",
                        "evidence": "Case caption",
                    },
                    {
                        "field": "no_such_field",
                        "label": "user_birthdate",
                        "evidence": "Date of Birth",
                    },
                ]
            }
        )
        self.assertEqual(
            accepted["remaps"],
            [
                {
                    "field": "date_of_birth",
                    "label": "user_birthdate",
                    "target": "users[0].birthdate.format()",
                    "evidence": "Date of Birth",
                }
            ],
        )

    def test_a_remap_with_the_two_names_swapped_is_still_understood(self):
        """gpt-4o-mini put the label in `field` and the field in `label`."""
        accepted = self.check(
            {
                "remaps": [
                    {
                        "field": "user_birthdate",
                        "label": "date_of_birth",
                        "evidence": "Date of Birth",
                    },
                    {
                        "field": "user_birthdate",
                        "label": "Date of Birth",
                        "evidence": "Date of Birth",
                    },
                ]
            }
        )
        self.assertEqual([r["field"] for r in accepted["remaps"]], ["date_of_birth"])

    def test_an_existing_group_becomes_radio_only_when_the_form_says_so(self):
        accepted = self.check(
            {
                "choice_groups": [
                    {
                        "field": "proceeding_is",
                        "kind": "radio",
                        "evidence": "(check one)",
                    },
                    {"field": "case_name", "kind": "radio", "evidence": "check one"},
                ]
            }
        )
        self.assertEqual(
            accepted["choice_groups"],
            [{"field": "proceeding_is", "kind": "radio", "evidence": "(check one)"}],
        )

    def test_a_new_group_must_be_existing_yes_no_boxes(self):
        accepted = self.check(
            {
                "choice_groups": [
                    {
                        "fields": ["box_a", "box_b", "box_c"],
                        "variable": "which_box",
                        "kind": "checkboxes",
                        "evidence": "Type of proceeding",
                    },
                    {
                        "fields": ["box_a", "case_name", "box_c"],
                        "variable": "mixed",
                        "kind": "radio",
                        "evidence": "check one Adoption",
                    },
                ]
            }
        )
        self.assertEqual(
            [g["variable"] for g in accepted["choice_groups"]], ["which_box"]
        )

    def test_weak_new_groups_seen_from_a_real_model_are_refused(self):
        """Each of these came from gpt-4o-mini on a published form."""
        accepted = self.check(
            {
                "choice_groups": [
                    # Two boxes are usually two questions
                    {
                        "fields": ["box_a", "box_b"],
                        "variable": "pair",
                        "kind": "checkboxes",
                        "evidence": "Type of proceeding",
                    },
                    # "Yes/No" says nothing about the boxes belonging together
                    {
                        "fields": ["box_a", "box_b", "box_c"],
                        "variable": "yes_no",
                        "kind": "checkboxes",
                        "evidence": "Adoption",
                    },
                    # One question per guardian, not choices of one
                    {
                        "fields": [
                            "is_guardian1_update",
                            "is_guardian2_update",
                            "is_guardian3_update",
                        ],
                        "variable": "updates",
                        "kind": "checkboxes",
                        "evidence": "Type of proceeding",
                    },
                ]
            }
        )
        self.assertEqual(accepted["choice_groups"], [])

    def test_a_condition_names_a_real_choice(self):
        accepted = self.check(
            {
                "conditions": [
                    {
                        "field": "type_of_proceeding_other",
                        "when": "proceeding_is",
                        "choice": "other",
                        "evidence": "If other, describe",
                    },
                    {
                        "field": "case_name",
                        "when": "proceeding_is",
                        "choice": "divorce",
                        "evidence": "If other, describe",
                    },
                ]
            }
        )
        self.assertEqual(
            [(c["field"], c["choice"]) for c in accepted["conditions"]],
            [("type_of_proceeding_other", "other")],
        )

    def test_a_reply_that_isnt_json_changes_nothing(self):
        self.assertEqual(
            self.check("not json"),
            {"remaps": [], "choice_groups": [], "conditions": []},
        )

# do not pre-load

import unittest

from .editor_utils import _al_individual_primitive_groups


class TestALIndividualPrimitiveGroups(unittest.TestCase):
    def test_object_declarations_use_i_only_for_people_lists(self):
        model = {
            "blocks": [
                {
                    "data": {
                        "objects": [
                            {"users": "ALPeopleList.using(target_number=1)"},
                            {"applicant": "ALIndividual"},
                            {"unrelated": "DAObject"},
                        ]
                    }
                }
            ]
        }

        groups = _al_individual_primitive_groups(model)

        self.assertEqual(groups["al_people_lists"], ["users[i]"])
        self.assertEqual(groups["al_individual_objects"], ["applicant"])
        self.assertEqual(groups["al_individual_primitives"], ["applicant", "users[i]"])

    def test_generic_objects_and_existing_calls_are_suggested(self):
        model = {
            "blocks": [
                {"data": {"generic object": "ALPeopleList"}},
                {"data": {"generic object": "ALIndividual"}},
                {
                    "data": {
                        "fields": [
                            {
                                "code": "users[0].jobs[i].employer.name_fields(\n"
                                "  person_or_business='unsure'\n"
                                ")"
                            }
                        ]
                    }
                },
            ]
        }

        groups = _al_individual_primitive_groups(model)

        self.assertIn("x[i]", groups["al_people_lists"])
        self.assertIn("x", groups["al_individual_objects"])
        self.assertIn("users[0].jobs[i].employer", groups["al_individual_objects"])


if __name__ == "__main__":
    unittest.main()

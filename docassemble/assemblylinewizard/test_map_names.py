import unittest

from interview_generator import map_names
from docassemble.base.util import log

__all__ = ['TestMapNames']

class TestMapNames(unittest.TestCase):

    def setUp(self):
        pass

    def test_mapped_scenarios(self, run_from_yaml=False):
        # Look in the console for a prettier version of the messages
        errored = []
        passed = []
        for scenario_input in scenarios:
            log("~~~~~~~~~~", "console")

            # Add our result to the collection
            try:
                desired_output = scenarios[scenario_input]
                result = self.assertEqual(desired_output, map_names(scenario_input))
                log(result, "console")
                passed.append(scenario_input)

            # The error should show us what specifically didn't match up
            except AssertionError as error:
                log(error, "console")
                errored.append({"test": scenario_input, "result": error})

        results = {"errored": errored, "passed": passed}
        log(results, "console")
        # This is True if this test is run from generator-test.yml
        if (run_from_yaml):
            return results
        self.assertEqual(len(passed), len(scenarios))
        self.assertEqual(len(errored), 0)


if __name__ == "__main__":
    unittest.main()

# Some basic test strings with desired results
scenarios = {
  # Reserved whole words
  "signature_date": "signature_date",
  "attorney_of_record_address_on_one_line": "attorney_of_record_address_on_one_line",

  # Reserved endings
  "user1": "str(users[1-1])",
  "user2": "str(users[2-1])",
  "user__2": "str(users[0])",
  "user____2": "str(users[0])",
  "user_name": "str(users[0])",
  "user_name_full": "str(users[0])",
  "user_name_first": "users[0].name.first",
  "user_name_middle": "users[0].name.middle",
  "user_name_last": "users[0].name.last",
  "user_name_suffix": "users[0].name.suffix",
  "user_gender": "users[0].gender",
  "user_birthdate": "users[0].birthdate.format()",
  "user_age": "users[0].age_in_years()",
  "user_email": "users[0].email",
  "user_phone": "users[0].phone_number",
  "user_address_block": "users[0].address.block()",
  "user_address_street": "users[0].address.address",
  "user_address_street2": "users[0].address.unit",
  "user_address_city": "users[0].address.city",
  "user_address_state": "users[0].address.state",
  "user_address_zip": "users[0].address.zip",
  "user_address_on_one_line": "users[0].address.on_one_line()",
  "user_address_one_line": "users[0].address.on_one_line()",
  "user_address_city_state_zip": "users[0].address.line_two()",
  "user_signature": "users[0].signature",

  # Combo all
  "user3_birthdate__4": "users[3-1].birthdate.format()",
  "user3_birthdate____4": "users[3-1].birthdate.format()",

  # County
  # "county_name_short": not implemented,
  # "county_division": not implemented,
  "court_address_county": "courts[0].address.county",
  "court_county": "courts[0].address.county",

  # # Reserved starts (with names)
  "user": "str(users[0])",
  "plaintiff": "str(plaintiffs[0])",
  "defendant": "str(defendants[0])",
  "petitioner": "str(petitioners[0])",
  "respondent": "str(respondents[0])",
  "spouse": "str(spouses[0])",
  "parent": "str(parents[0])",
  "guardian": "str(guardians[0])",
  "caregiver": "str(caregivers[0])",
  "attorney": "str(attorneys[0])",
  "translator": "str(translators[0])",
  "debt_collector": "str(debt_collectors[0])",
  "creditor": "str(creditors[0])",
  "court": "str(courts[0])",
  "other_party": "str(other_parties[0])",
  "child": "str(children[0])",
  "guardian_ad_litem": "str(guardians_ad_litem[0])",
  "witness": "str(witnesses[0])",
  "users": "str(users)",
  "plaintiffs": "str(plaintiffs)",
  "defendants": "str(defendants)",
  "petitioners": "str(petitioners)",
  "respondents": "str(respondents)",
  "spouses": "str(spouses)",
  "parents": "str(parents)",
  "guardians": "str(guardians)",
  "caregivers": "str(caregivers)",
  "attorneys": "str(attorneys)",
  "translators": "str(translators)",
  "debt_collectors": "str(debt_collectors)",
  "creditors": "str(creditors)",
  "courts": "str(courts)",
  "other_parties": "str(other_parties)",
  "children": "str(children)",
  "guardians_ad_litem": "str(guardians_ad_litem)",
  "witnesses": "str(witnesses)",

  # Starts with no names
  "docket_number": "docket_numbers[0]",
  "docket_numbers": "str(docket_numbers)",
  "signature_date": "signature_date",

  # Reserved start with unreserved end
  "user_address_street2_zip": "users[0].address_street2_zip",

  # Not reserved
  "my_user_name_last": "my_user_name_last",
  "foo": "foo",
}

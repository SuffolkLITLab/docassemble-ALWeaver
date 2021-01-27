import unittest

from .interview_generator import map_names
from docassemble.base.util import log

__all__ = ['TestMapNames']

# Some basic test input pdf label strings (left) with desired results (right)
attachment_scenarios = {
  # Reserved whole words
  "signature_date": "signature_date",
  "attorney_of_record_address_on_one_line": "attorney_of_record_address_on_one_line",

  # Reserved endings
  "user1": "users[0])",
  "user2": "users[1])",
  "user__2": "users[0])",
  "user____2": "users[0])",
  "user_name": "users[0])",
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
  "user3_birthdate__4": "users[2].birthdate.format()",
  "user3_birthdate____4": "users[2].birthdate.format()",

  # County
  # "county_name_short": not implemented,
  # "county_division": not implemented,
  "court_address_county": "courts[0].address.county",
  "court_county": "courts[0].address.county",

  # # Reserved starts (with names)
  "user": "users[0]",
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

interview_order_scenarios = {
  # Reserved whole words
  "signature_date": "signature_date",
  "attorney_of_record_address_on_one_line": "attorney_of_record_address_on_one_line",

  # Reserved endings
  "user1": "users.gather()",
  "user2": "users.gather()",
  "user__2": "users.gather()",
  "user_name": "users.gather()",
  "user_name_full": "str(users[0])",
  "user_name_first": "users[0].name.first",
  "user_name_middle": "users[0].name.middle",
  "user_name_last": "users[0].name.last",
  "user_name_suffix": "users[0].name.suffix",
  "user_gender": "users.gather(complete_attribute='gender')",
  "user_birthdate": "users.gather(complete_attribute='birthdate')",
  "user_age": "users.gather(complete_attribute='age')",
  "user_email": "users.gather(complete_attribute='email')",
  "user_phone": "users.gather(complete_attribute='phone_number')",
  "user_signature": "users.gather(complete_attribute='signature')",

  # County
  # "county_name_short": not implemented,
  # "county_division": not implemented,
  "court_address_county": "courts.gather()",
  "court_county": "courts.gather()",

  # # Reserved starts (with names)
  "user": "users.gather()",
  "users": "users.gather()",
  "plaintiff": "plaintiffs.gather()",
  "defendant": "defendants.gather()",
  "courts": "courts.gather()",
  "other_parties": "other_parties.gather()",
  "children": "children.gather()",
  "guardians_ad_litem": "guardians_ad_litem.gather()",
  "witnesses": "witnesses.gather()",

  # Starts with no names
  "docket_number": "docket_numbers.gather()",
  "docket_numbers": "docket_numbers.gather()",
  "signature_date": "signature_date",

  # Reserved start with unreserved end
  # TODO(brycew): what to do with this?
  # "user_address_street2_zip": "users[0].address_street2_zip",

  # Not reserved
  "my_user_name_last": "my_user_name_last",
  "foo": "foo",
}


class TestMapNames(unittest.TestCase):
    def setUp(self):
        self.scenarios = attachment_scenarios
        pass

    def test_mapped_scenarios(self, run_from_yaml=False):
        # Look in the console for a prettier version of the messages
        errored = []
        passed = []
        for scenario_input in self.scenarios:
            log("~~~~~~~~~~", "console")

            # Add our result to the collection
            try:
                desired_output = self.scenarios[scenario_input]
                self.assertEqual(desired_output, map_names(scenario_input))
                passed.append(scenario_input)

            # The error should show us what specifically didn't match up
            except AssertionError as error:
                log(error, "console")
                errored.append({"test": scenario_input, "result": error})

        results = {"errored": errored, "passed": passed}
        log(results, "console")
        # This is True if this test is run from generator-test.yml
        if run_from_yaml:
            return results
        self.assertEqual(len(passed), len(self.scenarios))
        self.assertEqual(len(errored), 0)


if __name__ == "__main__":
    unittest.main()

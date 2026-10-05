# do not pre-load
import unittest

from .repeated_rows import find_row_families, row_family_yaml


def families_by_name(variables, taken=(), people=()):
    return {
        family.list_name: family
        for family in find_row_families(variables, taken, people)
    }


class TestFindRowFamilies(unittest.TestCase):
    def test_vehicle_rows_become_an_al_vehicle_list(self):
        variables = [
            f"vehicle_{attribute}_{row}"
            for row in (1, 2, 3)
            for attribute in ("year_make_model", "pv", "loan_balance", "purpose")
        ]
        vehicles = families_by_name(variables)["vehicles"]
        self.assertEqual(vehicles.object_type, "ALVehicleList")
        self.assertEqual(vehicles.capacity, 3)
        self.assertEqual(vehicles.variables["vehicle_pv_2"], "vehicles[1].market_value")
        self.assertEqual(
            vehicles.variables["vehicle_year_make_model_1"],
            "vehicles[0].year_make_model()",
        )
        self.assertEqual(vehicles.variables["vehicle_purpose_3"], "vehicles[2].purpose")
        # al_income.yml asks the rest; only `purpose` needs a question
        self.assertEqual(vehicles.question_attributes(), ["purpose"])

    def test_the_longest_shared_start_names_the_row(self):
        variables = [
            f"real_estate_{attribute}_{row}"
            for row in (1, 2)
            for attribute in ("owner", "value", "loan_balance")
        ]
        real_estate = families_by_name(variables)["real_estate"]
        self.assertEqual(real_estate.object_type, "ALAssetList")
        self.assertEqual(
            real_estate.variables["real_estate_loan_balance_2"],
            "real_estate[1].balance",
        )

    def test_rows_of_anything_else_are_a_plain_list(self):
        variables = [
            "other_case_1_docket",
            "other_case_1_court",
            "other_case_2_docket",
            "other_case_2_court",
        ]
        cases = families_by_name(variables)["other_cases"]
        self.assertEqual(cases.object_type, "DAList")
        self.assertEqual(cases.variables["other_case_2_court"], "other_cases[1].court")

    def test_a_bare_numbered_name_is_a_person(self):
        """`judge0` with `judge0_role`, from the Civil Docketing Statement."""
        variables = ["judge0", "judge0_role", "judge1", "judge1_role", "judge2"]
        judges = families_by_name(variables)["judges"]
        self.assertTrue(judges.is_people)
        self.assertEqual(judges.variables["judge0"], "judges[0]")
        self.assertEqual(judges.variables["judge1_role"], "judges[1].role")
        self.assertEqual(judges.capacity, 3)

    def test_a_single_numbered_field_stays_as_it_is(self):
        self.assertEqual(families_by_name(["income_monthly_1", "income_monthly_2"]), {})

    def test_a_list_name_already_in_use_is_left_alone(self):
        variables = [
            "vehicle_pv_1",
            "vehicle_owner_1",
            "vehicle_pv_2",
            "vehicle_owner_2",
        ]
        self.assertEqual(families_by_name(variables, taken={"vehicles"}), {})


class TestRowFamilyYaml(unittest.TestCase):
    def test_a_plain_list_gets_its_whole_gather_flow(self):
        family = families_by_name(
            ["other_case_1_docket", "other_case_1_filed_date", "other_case_2_docket"]
        )["other_cases"]
        yaml_text = row_family_yaml(family, {"filed_date": "date"})
        self.assertIn("  - no label: other_cases.there_are_any\n", yaml_text)
        self.assertIn(
            '  - "Filed date": other_cases[i].filed_date\n    datatype: date', yaml_text
        )
        self.assertIn("  - no label: other_cases.there_is_another\n", yaml_text)
        self.assertIn(
            "code: |\n  other_cases[i].docket\n"
            "  other_cases[i].filed_date\n  other_cases[i].complete = True",
            yaml_text,
        )


class TestRowFamilyCounterexamples(unittest.TestCase):
    """Names from real forms that looked like rows but aren't new lists."""

    def test_rows_of_a_people_list_the_interview_has_are_left_alone(self):
        variables = [
            "users1_relationship_to_minor",
            "users1_occupation",
            "users2_relationship_to_minor",
            "users2_occupation",
        ]
        self.assertEqual(families_by_name(variables, people={"user", "users"}), {})

    def test_half_a_phrase_is_not_a_row(self):
        variables = [
            "wants_custody_of_1_name",
            "wants_custody_of_1_age",
            "wants_custody_of_2_name",
            "wants_custody_of_2_age",
        ]
        self.assertEqual(families_by_name(variables), {})

    def test_a_plural_stem_keeps_its_name(self):
        variables = ["savings_1_bank", "savings_1_amount", "savings_2_bank"]
        self.assertIn("savings", families_by_name(variables))

    def test_a_keyword_attribute_gets_a_usable_name(self):
        variables = [
            "user_prior_name_change_1_from",
            "user_prior_name_change_1_to",
            "user_prior_name_change_2_from",
        ]
        changes = families_by_name(variables)["user_prior_name_changes"]
        self.assertEqual(
            changes.variables["user_prior_name_change_2_from"],
            "user_prior_name_changes[1].from_",
        )

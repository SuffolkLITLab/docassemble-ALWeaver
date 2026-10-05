# do not pre-load
import unittest

from .name_datatypes import datatype_from_name


class TestDatatypeFromName(unittest.TestCase):
    def assertTypes(self, expected, document_type="docx", knows_box_size=False):
        for variable, datatype in expected.items():
            with self.subTest(variable=variable):
                self.assertEqual(
                    datatype_from_name(variable, document_type, knows_box_size),
                    datatype,
                )

    def test_names_that_say_what_they_hold(self):
        self.assertTypes(
            {
                "date_of_birth": "date",
                "date_from": "date",
                "deadline_request": "date",
                "client.birthdate": "date",
                "hearing_email": "email",
                "users[0].attorney.email": "email",
                "security_deposit_amount": "currency",
                "last_months_rent": "currency",
                "user_car_debt": "currency",
                "days_lost": "integer",
                "previous_request_count": "integer",
                "relief_sought": "area",
                "any_inheritance_likely_describe": "area",
                "is_spouse_employed": "yesno",
            }
        )

    def test_counterexamples_from_real_forms_stay_text(self):
        self.assertTypes(
            {
                "parent1_date_month": None,
                "guardian_date_year": None,
                "rental_income_source": None,
                "debt_account_number": None,
                "rent_address_one_line": None,
                "user_mail_address_city": None,
                "docket_num": None,
                "issues_raised_elsewhere_name": None,
                "case_name": None,
            }
        )

    def test_a_known_pdf_box_size_decides_one_line_or_several(self):
        self.assertEqual(datatype_from_name("relief_sought", "pdf", True), None)
        self.assertEqual(datatype_from_name("relief_sought", "pdf", False), "area")

    def test_question_words_only_make_a_yes_no_in_a_docx(self):
        """A PDF text box called `is_...` is still somewhere to type."""
        self.assertEqual(datatype_from_name("is_condo_conversion", "pdf"), None)
        self.assertEqual(datatype_from_name("issues", "docx"), "area")

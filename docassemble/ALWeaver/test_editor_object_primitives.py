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


class TestObjectUsingExpressionRoundTrip(unittest.TestCase):
    """A multi-argument ``.using()`` call is displayed one argument per line
    with the commas stripped.  Composing that display form back into an
    expression has to put them back, or the editor writes a call that is not
    valid Python and the object silently fails to build.
    """

    def test_multiline_arguments_keep_their_commas(self):
        from .editor_utils import _compose_object_using_expression

        composed = _compose_object_using_expression(
            "ALDocumentBundle",
            'elements=[]\nfilename="court_bundle"\ntitle="All forms"',
        )

        self.assertEqual(
            composed,
            "ALDocumentBundle.using(\n"
            "  elements=[],\n"
            '  filename="court_bundle",\n'
            '  title="All forms"\n'
            ")",
        )

    def test_single_argument_stays_inline(self):
        from .editor_utils import _compose_object_using_expression

        self.assertEqual(
            _compose_object_using_expression("ALPeopleList", "there_are_any=True"),
            "ALPeopleList.using(there_are_any=True)",
        )

    def test_a_full_read_compose_round_trip_preserves_the_call(self):
        from .editor_utils import (
            _compose_object_using_expression,
            _format_object_using_args,
            _split_object_using_expression,
        )

        original = (
            'ALDocumentBundle.using(elements=[a, b], filename="bundle", title="All")'
        )
        class_name, args_text = _split_object_using_expression(original)
        displayed = _format_object_using_args(args_text, raw_expression=original)
        composed = _compose_object_using_expression(class_name, displayed)

        # Reading the composed form again must yield the same arguments, which
        # is only true if the commas survived.
        _class_again, args_again = _split_object_using_expression(composed)
        self.assertEqual(
            _format_object_using_args(args_again, raw_expression=composed),
            displayed,
        )

    def test_a_comma_inside_a_bracket_is_not_an_argument_separator(self):
        from .editor_utils import _split_top_level_commas

        self.assertEqual(
            _split_top_level_commas('elements=[a, b]\nfilename="x"'),
            ["elements=[a, b]", 'filename="x"'],
        )

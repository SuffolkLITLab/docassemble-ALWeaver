# do not pre-load

import unittest

from .editor_utils import STEP_CONDITION, parse_order_code, serialize_order_steps


class TestOrderConditionRoundTrip(unittest.TestCase):
    """The order builder rewrites the whole block on save, so anything it
    cannot parse is silently lost.  ``elif`` used to be exactly that: it was
    read as a raw line and its body became sibling steps, so saving moved those
    screens out of the branch and ran them unconditionally.
    """

    def assert_round_trips(self, source: str) -> None:
        self.assertEqual(
            serialize_order_steps(parse_order_code(source)).strip(),
            source.strip(),
        )

    def test_elif_body_stays_inside_its_branch(self):
        source = "\n".join(
            [
                "if user_started_case:",
                "  petition_screen",
                "elif user_is_defendant:",
                "  answer_screen",
                "else:",
                "  other_screen",
                "final_screen",
            ]
        )

        self.assert_round_trips(source)

    def test_elif_chain_without_else_round_trips(self):
        source = "\n".join(
            [
                "if a:",
                "  one",
                "elif b:",
                "  two",
                "elif c:",
                "  three",
            ]
        )

        self.assert_round_trips(source)

    def test_elif_nested_inside_a_condition_round_trips(self):
        source = "\n".join(
            [
                "if a:",
                "  if b:",
                "    one",
                "  elif c:",
                "    two",
                "  else:",
                "    three",
                "elif d:",
                "  four",
                "last",
            ]
        )

        self.assert_round_trips(source)

    def test_plain_if_else_is_unchanged(self):
        source = "\n".join(
            [
                "if a:",
                "  one",
                "else:",
                "  two",
            ]
        )

        self.assert_round_trips(source)

    def test_elif_parses_as_a_condition_in_the_else_branch(self):
        # ``elif`` is modeled as an ``else`` holding one nested condition, which
        # is what it means in Python and is a shape the order builder already
        # renders, so no separate step kind is needed for it.
        steps = parse_order_code(
            "\n".join(
                [
                    "if a:",
                    "  one",
                    "elif b:",
                    "  two",
                ]
            )
        )

        self.assertEqual(len(steps), 1)
        outer = steps[0]
        self.assertEqual(outer["kind"], STEP_CONDITION)
        self.assertEqual(outer["condition"], "a")
        self.assertTrue(outer["has_else"])

        self.assertEqual(len(outer["else_children"]), 1)
        nested = outer["else_children"][0]
        self.assertEqual(nested["kind"], STEP_CONDITION)
        self.assertEqual(nested["condition"], "b")
        self.assertFalse(nested["has_else"])
        self.assertEqual([child["invoke"] for child in nested["children"]], ["two"])

    def test_step_ids_stay_unique_across_a_chain(self):
        steps = parse_order_code(
            "\n".join(
                [
                    "if a:",
                    "  one",
                    "elif b:",
                    "  two",
                    "else:",
                    "  three",
                ]
            )
        )

        seen = []

        def collect(step_list):
            for step in step_list:
                seen.append(step["id"])
                collect(step.get("children") or [])
                collect(step.get("else_children") or [])

        collect(steps)

        self.assertEqual(len(seen), len(set(seen)))

    def test_else_holding_a_condition_is_written_as_elif(self):
        # A chain the author builds by nesting in the order builder comes back
        # as idiomatic ``elif`` rather than a growing ladder of nested ``if``.
        steps = [
            {
                "kind": STEP_CONDITION,
                "condition": "a",
                "children": [{"kind": "screen", "invoke": "one"}],
                "has_else": True,
                "else_children": [
                    {
                        "kind": STEP_CONDITION,
                        "condition": "b",
                        "children": [{"kind": "screen", "invoke": "two"}],
                        "has_else": False,
                        "else_children": [],
                    }
                ],
            }
        ]

        self.assertEqual(
            serialize_order_steps(steps),
            "\n".join(
                [
                    "if a:",
                    "  one",
                    "elif b:",
                    "  two",
                ]
            ),
        )

    def test_else_with_a_condition_plus_other_steps_stays_an_else(self):
        steps = [
            {
                "kind": STEP_CONDITION,
                "condition": "a",
                "children": [{"kind": "screen", "invoke": "one"}],
                "has_else": True,
                "else_children": [
                    {
                        "kind": STEP_CONDITION,
                        "condition": "b",
                        "children": [{"kind": "screen", "invoke": "two"}],
                        "has_else": False,
                        "else_children": [],
                    },
                    {"kind": "screen", "invoke": "three"},
                ],
            }
        ]

        self.assertEqual(
            serialize_order_steps(steps),
            "\n".join(
                [
                    "if a:",
                    "  one",
                    "else:",
                    "  if b:",
                    "    two",
                    "  three",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()

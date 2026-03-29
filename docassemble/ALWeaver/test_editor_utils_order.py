import unittest

from .editor_utils import parse_order_code, serialize_order_steps


class TestEditorUtilsOrder(unittest.TestCase):
    def test_parse_order_code_supports_nested_conditions(self):
        code = (
            "user_intro\n"
            "if needs_extra_help:\n"
            "  help_screen\n"
            "  set_progress(50)\n"
            "final_screen\n"
        )

        steps = parse_order_code(code)

        self.assertEqual(steps[0]["kind"], "screen")
        self.assertEqual(steps[0]["invoke"], "user_intro")
        self.assertEqual(steps[1]["kind"], "condition")
        self.assertEqual(steps[1]["condition"], "needs_extra_help")
        self.assertEqual(len(steps[1]["children"]), 2)
        self.assertEqual(steps[1]["children"][0]["kind"], "screen")
        self.assertEqual(steps[1]["children"][0]["invoke"], "help_screen")
        self.assertEqual(steps[1]["children"][1]["kind"], "progress")
        self.assertEqual(steps[2]["kind"], "screen")
        self.assertEqual(steps[2]["invoke"], "final_screen")

    def test_parse_order_code_supports_else_branches(self):
        code = (
            "user_intro\n"
            "if needs_extra_help:\n"
            "  help_screen\n"
            "else:\n"
            "  standard_screen\n"
            "final_screen\n"
        )

        steps = parse_order_code(code)

        self.assertEqual(steps[1]["kind"], "condition")
        self.assertTrue(steps[1]["has_else"])
        self.assertEqual(steps[1]["children"][0]["invoke"], "help_screen")
        self.assertEqual(steps[1]["else_children"][0]["invoke"], "standard_screen")

    def test_serialize_order_steps_supports_nested_conditions(self):
        steps = [
            {"id": "step-1", "kind": "screen", "invoke": "user_intro"},
            {
                "id": "step-2",
                "kind": "condition",
                "condition": "needs_extra_help",
                "children": [
                    {"id": "step-3", "kind": "screen", "invoke": "help_screen"},
                    {"id": "step-4", "kind": "progress", "value": "50"},
                ],
            },
        ]

        serialized = serialize_order_steps(steps)

        self.assertEqual(
            serialized,
            "  user_intro\n"
            "  if needs_extra_help:\n"
            "    help_screen\n"
            "    set_progress(50)",
        )

    def test_serialize_order_steps_supports_else_branches(self):
        steps = [
            {"id": "step-1", "kind": "screen", "invoke": "user_intro"},
            {
                "id": "step-2",
                "kind": "condition",
                "condition": "needs_extra_help",
                "children": [
                    {"id": "step-3", "kind": "screen", "invoke": "help_screen"},
                ],
                "has_else": True,
                "else_children": [
                    {"id": "step-4", "kind": "screen", "invoke": "standard_screen"},
                ],
            },
        ]

        serialized = serialize_order_steps(steps)

        self.assertEqual(
            serialized,
            "  user_intro\n"
            "  if needs_extra_help:\n"
            "    help_screen\n"
            "  else:\n"
            "    standard_screen",
        )


if __name__ == "__main__":
    unittest.main()
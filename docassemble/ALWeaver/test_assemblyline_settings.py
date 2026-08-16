import unittest

import yaml

from docassemble.ALWeaver.assemblyline_settings import (
    MANAGED_BLOCK_ID,
    read_settings,
    update_settings,
)

SOURCE = """# keep header
metadata:
  title: Original
  description: |
    Existing description
  authors:
    - Original Author
---
# author-owned code remains untouched
code: |
  AL_DEFAULT_COUNTRY = "CA"
---
id: main order
mandatory: True
code: |
  al_intro_screen
  interview_order = True
"""


class AssemblyLineSettingsTest(unittest.TestCase):
    def test_reads_metadata_and_literal_code_variables(self):
        result = read_settings(SOURCE)
        self.assertEqual(result["values"]["title"], "Original")
        self.assertEqual(result["values"]["AL_DEFAULT_COUNTRY"], "CA")
        self.assertEqual(result["sources"]["AL_DEFAULT_COUNTRY"], "code block")

    def test_update_adds_managed_block_before_mandatory_and_preserves_other_code(self):
        updated = update_settings(
            SOURCE,
            {
                "title": "Updated",
                "AL_DEFAULT_COUNTRY": "US",
                "allowed_courts": ["Housing Court", "Superior Court"],
                "speak_text": False,
            },
        )
        self.assertIn("# author-owned code remains untouched", updated)
        self.assertIn('AL_DEFAULT_COUNTRY = "CA"', updated)
        self.assertLess(
            updated.index(f"id: {MANAGED_BLOCK_ID}"), updated.index("id: main order")
        )
        result = read_settings(updated)
        self.assertEqual(result["values"]["title"], "Updated")
        self.assertEqual(result["values"]["AL_DEFAULT_COUNTRY"], "US")
        self.assertEqual(
            result["values"]["allowed_courts"],
            ["Housing Court", "Superior Court"],
        )
        self.assertFalse(result["values"]["speak_text"])
        list(yaml.safe_load_all(updated))

    def test_metadata_update_preserves_untouched_literal_scalar_bytes(self):
        updated = update_settings(SOURCE, {"title": "Updated"})

        original_metadata = SOURCE.split("---", 1)[0]
        updated_metadata = updated.split("---", 1)[0]
        self.assertEqual(
            updated_metadata,
            original_metadata.replace("title: Original", "title: Updated"),
        )
        self.assertIn("  description: |\n    Existing description\n", updated)

    def test_changed_multiline_metadata_uses_literal_block_style(self):
        updated = update_settings(
            SOURCE,
            {"description": "First updated line\nSecond updated line"},
        )

        self.assertIn(
            "  description: |\n    First updated line\n    Second updated line\n",
            updated,
        )
        self.assertNotIn("description: '", updated)
        self.assertEqual(
            read_settings(updated)["values"]["description"].rstrip("\n"),
            "First updated line\nSecond updated line",
        )

    def test_new_multiline_metadata_uses_literal_block_style(self):
        updated = update_settings(
            SOURCE,
            {"can_I_use_this_form": "People filing a claim\nPeople responding"},
        )

        self.assertIn(
            "  can_I_use_this_form: |-\n"
            "    People filing a claim\n"
            "    People responding",
            updated,
        )

    def test_multiline_list_items_use_literal_block_style(self):
        updated = update_settings(
            SOURCE,
            {"authors": ["First author\nSecond line"]},
        )

        self.assertIn(
            "  authors:\n" "    - |-\n" "      First author\n" "      Second line",
            updated,
        )
        self.assertEqual(
            read_settings(updated)["values"]["authors"],
            ["First author\nSecond line"],
        )

    def test_repeated_update_replaces_one_managed_block(self):
        once = update_settings(SOURCE, {"github_user": "first"})
        twice = update_settings(once, {"github_user": "second"})
        self.assertEqual(twice.count(f"id: {MANAGED_BLOCK_ID}"), 1)
        self.assertEqual(read_settings(twice)["values"]["github_user"], "second")

    def test_optional_integer_metadata_round_trips_when_blank(self):
        source = SOURCE.replace(
            "  authors:\n    - Original Author\n",
            "  authors:\n    - Original Author\n  estimated_completion_delta: ''\n",
        )

        updated = update_settings(
            source,
            {
                **read_settings(source)["values"],
                "AL_ORGANIZATION_TITLE": "Example Legal Aid",
            },
        )

        values = read_settings(updated)["values"]
        self.assertEqual(values["estimated_completion_delta"], "")
        self.assertEqual(values["AL_ORGANIZATION_TITLE"], "Example Legal Aid")
        self.assertNotIn("can_I_use_this_form:", updated)

    def test_rejects_runtime_logic_as_a_setting(self):
        with self.assertRaisesRegex(ValueError, "Unsupported settings"):
            update_settings(SOURCE, {"addresses_to_search": "[broken"})


if __name__ == "__main__":
    unittest.main()

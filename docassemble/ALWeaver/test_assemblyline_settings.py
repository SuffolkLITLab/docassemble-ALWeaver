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

    def test_repeated_update_replaces_one_managed_block(self):
        once = update_settings(SOURCE, {"github_user": "first"})
        twice = update_settings(once, {"github_user": "second"})
        self.assertEqual(twice.count(f"id: {MANAGED_BLOCK_ID}"), 1)
        self.assertEqual(read_settings(twice)["values"]["github_user"], "second")

    def test_rejects_runtime_logic_as_a_setting(self):
        with self.assertRaisesRegex(ValueError, "Unsupported settings"):
            update_settings(SOURCE, {"addresses_to_search": "[broken"})


if __name__ == "__main__":
    unittest.main()

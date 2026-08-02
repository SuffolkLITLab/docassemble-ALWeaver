import unittest
from unittest.mock import patch

from . import custom_values


class TestCustomValues(unittest.TestCase):
    def test_get_matching_deps_dedupes_string_include_names(self):
        capabilities = {
            "Default configuration": {
                "jurisdiction_choices": [
                    {"include_name": "docassemble.Alpha:alpha.yml", "state": "MA"},
                    {"include_name": "docassemble.Alpha:alpha.yml", "state": "MA"},
                    {"include_name": "docassemble.Beta:beta.yml", "state": "MA"},
                ]
            }
        }

        with patch.object(
            custom_values,
            "_get_capabilities",
            return_value=capabilities,
        ):
            deps = custom_values.get_matching_deps("jurisdiction", "MA")

        self.assertEqual(
            list(deps.keys()),
            [
                "docassemble.Alpha:alpha.yml",
                "docassemble.Beta:beta.yml",
            ],
        )


if __name__ == "__main__":
    unittest.main()

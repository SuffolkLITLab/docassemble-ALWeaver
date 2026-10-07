# do not pre-load

"""Tests for confidence when attaching diagnostics to source blocks."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from .editor_agent_validation import (
    annotate_lint_findings,
    dayamlchecker_findings,
    resolve_lint_block_id,
)
from .editor_ai_utils import validate_yaml_with_dayamlchecker


class TestDAYamlCheckerSeverity(unittest.TestCase):
    def test_structured_severity_and_legacy_prefixes(self):
        from dayamlchecker.messages import Severity

        errors = [
            SimpleNamespace(err_str="Advisory", severity=Severity.WARNING),
            SimpleNamespace(err_str="Suggestion", severity=Severity.INFO),
            SimpleNamespace(err_str="Invalid Python", severity=Severity.ERROR),
            SimpleNamespace(err_str="Warning: Old advisory"),
            SimpleNamespace(err_str="Info: Old suggestion"),
            SimpleNamespace(err_str="Old error"),
        ]
        with patch(
            "dayamlchecker.yaml_structure.find_errors_from_string", return_value=errors
        ):
            findings = dayamlchecker_findings("question: Hello\n", "test.yml")
            valid, details = validate_yaml_with_dayamlchecker("question: Hello\n")
        self.assertEqual(
            [finding["level"] for finding in findings],
            ["warning", "info", "error", "warning", "info", "error"],
        )
        self.assertFalse(valid)
        self.assertEqual(details, "Invalid Python\nOld error")

    def test_advisories_do_not_block_validation(self):
        errors = [SimpleNamespace(err_str="Add an id", severity="warning")]
        with patch(
            "dayamlchecker.yaml_structure.find_errors_from_string", return_value=errors
        ):
            self.assertEqual(
                validate_yaml_with_dayamlchecker("question: Hello\n"), (True, "")
            )

    def test_real_checker_function_definition_is_advisory(self):
        findings = dayamlchecker_findings(
            "code: |\n  def helper():\n    return True\n", "test.yml"
        )
        function_warnings = [
            finding for finding in findings if "defines function" in finding["message"]
        ]
        self.assertTrue(function_warnings)
        self.assertEqual(function_warnings[0]["level"], "warning")


class TestLintFindingBlockResolution(unittest.TestCase):
    blocks = [
        {
            "id": "first",
            "type": "question",
            "title": "First screen",
            "line_start": 1,
            "line_end": 5,
            "yaml": "question: shared phrase\n",
        },
        {
            "id": "second",
            "type": "question",
            "title": "Second screen",
            "line_start": 6,
            "line_end": 10,
            "yaml": "question: shared phrase\n",
        },
    ]

    def test_repeated_problematic_text_does_not_create_a_confident_link(self):
        finding = {"problematic_text": "shared phrase", "message": "Ambiguous"}

        self.assertIsNone(resolve_lint_block_id(finding, self.blocks))

        annotated = annotate_lint_findings([finding], self.blocks)[0]
        self.assertNotIn("block_id", annotated)
        self.assertNotIn("block_title", annotated)
        self.assertNotIn("line_start", annotated)

    def test_unique_problematic_text_still_links_to_its_source_block(self):
        finding = {"problematic_text": "second-only text", "message": "Unique"}
        blocks = [
            self.blocks[0],
            dict(self.blocks[1], yaml="question: second-only text\n"),
        ]

        annotated = annotate_lint_findings([finding], blocks)[0]

        self.assertEqual(annotated["block_id"], "second")
        self.assertEqual(annotated["block_title"], "Second screen")

    def test_precise_line_mapping_precedes_ambiguous_text(self):
        finding = {
            "line_number": 8,
            "problematic_text": "shared phrase",
            "message": "Line identifies the second screen",
        }

        self.assertEqual(resolve_lint_block_id(finding, self.blocks), "second")


if __name__ == "__main__":
    unittest.main()

# do not pre-load

"""Variable renaming: what gets rewritten, what gets left, what gets refused.

The same word can be a reference, display prose, or a string handed to a
dynamic lookup. These tests pin which is which, because getting it wrong
silently changes what an interview says or which question it asks.
"""

import unittest
from unittest.mock import patch

from . import editor_agent_validation
from .editor_agent_models import AgentCandidate, AgentToolCall
from .editor_agent_rename import (
    REASON_CALL,
    REASON_DISPLAY_TEXT,
    REASON_OBJECT_DECLARATION,
    REASON_PARTIAL_PATH,
    REASON_QUOTED_STRING,
    analyze_rename,
    check_rename_batch,
    suggest_object_conversion,
    validate_variable_reference,
)
from .editor_agent_tools import ToolContext, execute_tool

INTERVIEW = """# a header comment
metadata:
  title: Demo
---
id: ask_name
question: |
  What is your name, ${ persons1_name }?
subquestion: |
  We ask about persons1_name because the form demands it.
fields:
  - Your name: persons1_name
  - label: persons1_name is your legal name
    field: persons1_legal_name
  - Your address: persons1_address
---
id: confirm
question: Confirm
sets:
  - persons1_name
---
mandatory: True
code: |
  if persons1_name:
    persons1_address
"""


def _candidate(source):
    candidate = AgentCandidate.from_source(source)
    return candidate, ToolContext(
        project="default",
        filename="main.yml",
        owner_user_id=7,
        candidate=candidate,
    )


class RenameTestCase(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(
            editor_agent_validation, "dayamlchecker_findings", return_value=[]
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def rename(self, source, renames):
        candidate, context = _candidate(source)
        result = execute_tool(
            context,
            AgentToolCall(tool="rename_variables", arguments={"renames": renames}),
        )
        return result, candidate


class TestNameValidation(unittest.TestCase):
    def test_paths_indexes_and_plain_names_are_accepted(self):
        for name in ("user_name", "users[0].name.first", "persons[12].address.zip"):
            self.assertIsNone(validate_variable_reference(name), name)

    def test_expressions_and_keywords_are_refused(self):
        for name in (
            "users[0].birthdate.format()",
            "user name",
            "'quoted'",
            "users[0].name + 'x'",
            "",
            "class",
            "lambda",
        ):
            self.assertIsNotNone(validate_variable_reference(name), name)


class TestReferenceClassification(RenameTestCase):
    def analyze(self, old="persons1_name", new="applicant_name", source=INTERVIEW):
        return analyze_rename(
            filename="main.yml", raw_yaml=source, old_name=old, new_name=new
        )

    def test_every_real_reference_position_is_recognised(self):
        analysis = self.analyze()
        contexts = sorted({item.context for item in analysis.safe_occurrences})
        self.assertEqual(
            contexts,
            ["code", "field_reference", "list_reference", "mako_interpolation"],
        )

    def test_prose_is_left_alone_without_blocking_the_rename(self):
        analysis = self.analyze()
        reasons = [item.reason for item in analysis.ignored_occurrences]
        self.assertEqual(reasons, [REASON_DISPLAY_TEXT, REASON_DISPLAY_TEXT])
        self.assertEqual(analysis.blocking_occurrences, [])

    def test_a_longhand_label_is_prose_and_the_field_key_is_a_reference(self):
        # `- label: persons1_name is your legal name` is text; `field:` is not.
        analysis = self.analyze()
        label_line = next(
            item for item in analysis.occurrences if "legal name" in item.excerpt
        )
        self.assertEqual(label_line.reason, REASON_DISPLAY_TEXT)

        legal = self.analyze(old="persons1_legal_name")
        self.assertEqual(len(legal.safe_occurrences), 1)
        self.assertEqual(legal.safe_occurrences[0].context, "field_reference")

    def test_a_name_inside_a_string_blocks_the_rename(self):
        source = INTERVIEW + '  x = defined("persons1_name")\n'
        analysis = self.analyze(source=source)
        self.assertEqual(
            [item.reason for item in analysis.blocking_occurrences],
            [REASON_QUOTED_STRING],
        )

    def test_a_call_blocks_the_rename(self):
        source = "id: a\nmandatory: True\ncode: |\n  persons1_name()\n"
        analysis = self.analyze(source=source)
        self.assertEqual(
            [item.reason for item in analysis.blocking_occurrences], [REASON_CALL]
        )

    def test_a_longer_path_built_on_the_name_blocks_the_rename(self):
        source = "id: a\nmandatory: True\ncode: |\n  persons1_name.first\n"
        analysis = self.analyze(source=source)
        self.assertEqual(
            [item.reason for item in analysis.blocking_occurrences],
            [REASON_PARTIAL_PATH],
        )

    def test_a_similarly_named_variable_is_never_matched(self):
        analysis = self.analyze(old="persons1_name")
        self.assertNotIn(
            "persons1_legal_name",
            [item.text for item in analysis.occurrences],
        )

    def test_an_attribute_of_another_object_is_never_matched(self):
        source = "id: a\nmandatory: True\ncode: |\n  other.persons1_name\n"
        analysis = self.analyze(source=source)
        self.assertEqual(analysis.occurrences, [])


class TestRenameExecution(RenameTestCase):
    def test_a_clean_rename_rewrites_every_reference_and_nothing_else(self):
        result, candidate = self.rename(
            INTERVIEW, [{"old_name": "persons1_name", "new_name": "applicant_name"}]
        )
        self.assertTrue(result.succeeded, result.message)
        updated = candidate.raw_source

        self.assertIn("${ applicant_name }", updated)
        self.assertIn("  - Your name: applicant_name", updated)
        self.assertIn("  - applicant_name\n", updated)
        self.assertIn("  if applicant_name:", updated)
        # Prose and the similarly named variable are untouched.
        self.assertIn("We ask about persons1_name because", updated)
        self.assertIn("field: persons1_legal_name", updated)
        self.assertIn("- Your address: persons1_address", updated)
        self.assertIn("# a header comment", updated)

    def test_every_touched_block_is_reported(self):
        result, _candidate = self.rename(
            INTERVIEW, [{"old_name": "persons1_name", "new_name": "applicant_name"}]
        )
        touched = result.data["blocks_touched"]
        self.assertIn("ask_name", touched)
        self.assertIn("confirm", touched)
        report = result.data["renames"][0]
        self.assertEqual(report["reference_count"], 4)
        self.assertEqual(len(report["left_as_display_text"]), 2)

    def test_a_dynamic_reference_refuses_the_whole_rename(self):
        source = INTERVIEW + '  x = defined("persons1_name")\n'
        result, candidate = self.rename(
            source, [{"old_name": "persons1_name", "new_name": "applicant_name"}]
        )
        self.assertEqual(result.reason, "unsafe_rename")
        self.assertIn("quoted_string", result.message)
        self.assertEqual(candidate.raw_source, source)

    def test_a_batch_is_all_or_nothing(self):
        source = INTERVIEW + '  x = defined("persons1_address")\n'
        result, candidate = self.rename(
            source,
            [
                {"old_name": "persons1_name", "new_name": "applicant_name"},
                {"old_name": "persons1_address", "new_name": "applicant_address"},
            ],
        )
        self.assertEqual(result.reason, "unsafe_rename")
        self.assertEqual(candidate.raw_source, source)

    def test_two_variables_are_never_merged_into_one(self):
        result, candidate = self.rename(
            INTERVIEW,
            [
                {"old_name": "persons1_name", "new_name": "merged"},
                {"old_name": "persons1_address", "new_name": "merged"},
            ],
        )
        self.assertEqual(result.reason, "unsafe_rename")
        self.assertIn("would merge them", result.message)
        self.assertEqual(candidate.raw_source, INTERVIEW)

    def test_renaming_onto_an_existing_variable_is_refused(self):
        result, candidate = self.rename(
            INTERVIEW,
            [{"old_name": "persons1_name", "new_name": "persons1_address"}],
        )
        self.assertEqual(result.reason, "unsafe_rename")
        self.assertIn("already used", result.message)
        self.assertEqual(candidate.raw_source, INTERVIEW)

    def test_an_unknown_variable_is_refused(self):
        result, _candidate = self.rename(
            INTERVIEW, [{"old_name": "no_such_variable", "new_name": "whatever"}]
        )
        self.assertEqual(result.reason, "unsafe_rename")
        self.assertIn("does not appear", result.message)

    def test_an_expression_target_is_refused_by_the_schema(self):
        result, candidate = self.rename(
            INTERVIEW,
            [
                {
                    "old_name": "persons1_name",
                    "new_name": "users[0].birthdate.format()",
                }
            ],
        )
        self.assertEqual(result.reason, "unsafe_rename")
        self.assertEqual(candidate.raw_source, INTERVIEW)


class TestObjectDeclarations(RenameTestCase):
    SOURCE = """objects:
  - persons1_name: ALIndividual
---
id: ask_name
question: |
  Your name, ${ persons1_name }?
fields:
  - Your name: persons1_name
"""

    def test_a_declaration_cannot_become_an_attribute_path(self):
        analysis = analyze_rename(
            filename="main.yml",
            raw_yaml=self.SOURCE,
            old_name="persons1_name",
            new_name="persons[0].name.first",
        )
        self.assertEqual(
            [item.reason for item in analysis.blocking_occurrences],
            [REASON_OBJECT_DECLARATION],
        )
        result, candidate = self.rename(
            self.SOURCE,
            [{"old_name": "persons1_name", "new_name": "persons[0].name.first"}],
        )
        self.assertEqual(result.reason, "unsafe_rename")
        self.assertEqual(candidate.raw_source, self.SOURCE)

    def test_a_plain_rename_still_updates_the_declaration(self):
        result, candidate = self.rename(
            self.SOURCE,
            [{"old_name": "persons1_name", "new_name": "applicant_name"}],
        )
        self.assertTrue(result.succeeded, result.message)
        self.assertIn("  - applicant_name: ALIndividual", candidate.raw_source)


class TestFlatToObjectSuggestions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from .interview_generator import map_raw_to_final_display  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on the server
            raise unittest.SkipTest(f"interview_generator unavailable: {exc}")

    def test_a_flat_family_is_mapped_onto_assembly_line_objects(self):
        source = """id: ask
question: About you
fields:
  - Your first name: user_name_first
  - Your last name: user_name_last
  - Street: user_address_street
  - City: user_address_city
"""
        proposal = suggest_object_conversion(raw_yaml=source, prefix="user")
        mapping = {item["old_name"]: item["new_name"] for item in proposal["renames"]}
        self.assertEqual(mapping["user_name_first"], "users[0].name.first")
        self.assertEqual(mapping["user_address_street"], "users[0].address.address")
        self.assertEqual(mapping["user_address_city"], "users[0].address.city")

    def test_display_expressions_are_never_proposed_as_rename_targets(self):
        source = """id: ask
question: About you
fields:
  - Date of birth: user_birthdate
  - Your first name: user_name_first
"""
        proposal = suggest_object_conversion(raw_yaml=source, prefix="user")
        proposed = {item["old_name"] for item in proposal["renames"]}
        self.assertNotIn("user_birthdate", proposed)
        skipped = {item["old_name"]: item["reason"] for item in proposal["skipped"]}
        self.assertIn("user_birthdate", skipped)
        self.assertIn("display expression", skipped["user_birthdate"])

    def test_two_flat_names_are_never_collapsed_onto_one_target(self):
        source = """id: ask
question: About you
fields:
  - Name: user_name
  - Full name: user_name_full
"""
        proposal = suggest_object_conversion(raw_yaml=source, prefix="user")
        targets = [item["new_name"] for item in proposal["renames"]]
        self.assertEqual(len(targets), len(set(targets)))
        self.assertTrue(proposal["skipped"])

    def test_the_prefix_filters_the_family(self):
        source = """id: ask
question: About you
fields:
  - Your name: user_name_first
  - Other name: witness_name_first
"""
        proposal = suggest_object_conversion(raw_yaml=source, prefix="witness")
        self.assertEqual(
            [item["old_name"] for item in proposal["renames"]], ["witness_name_first"]
        )

    def test_a_suggestion_never_changes_the_source(self):
        source = "id: ask\nquestion: About you\nfields:\n  - Name: user_name_first\n"
        suggest_object_conversion(raw_yaml=source, prefix="user")
        self.assertEqual(
            source, "id: ask\nquestion: About you\nfields:\n  - Name: user_name_first\n"
        )


class TestBatchChecks(RenameTestCase):
    def test_check_reports_problems_without_touching_the_source(self):
        analyses, problems = check_rename_batch(
            filename="main.yml",
            raw_yaml=INTERVIEW,
            renames=[{"old_name": "persons1_name", "new_name": "class"}],
        )
        self.assertEqual(analyses, [])
        self.assertTrue(problems)
        self.assertIn("reserved Python keyword", problems[0])


if __name__ == "__main__":
    unittest.main()

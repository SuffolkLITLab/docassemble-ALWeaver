# do not pre load

"""Deterministic invariants for the agent's editing tools.

What matters here is not that a model picks the tool we expected; it is that
no tool call, however malformed or hostile, can reach another file, run an
unregistered capability, or leave the candidate in a state the validator would
reject.
"""

import unittest
from unittest.mock import patch

from . import editor_agent_validation
from .editor_agent_models import AgentCandidate, AgentToolCall, WeaverAgentSession
from .editor_agent_tools import (
    TOOL_REGISTRY,
    ToolContext,
    available_tool_names,
    execute_tool,
    validate_against_schema,
)
from .source_document import parse_source_document

INTERVIEW = """# file header comment
metadata:
  title: Demo interview
---
# keep this block comment
id: intro
question: |
  Welcome
fields:
  - Your name: user_name
---
id: user_address
question: Where do you live?
fields:
  - Street: users[0].address.address
---
question: A tagged block
value: !custom something
---
mandatory: True
code: |
  intro
  user_address
"""


class _FakeRuntime:
    """Stands in for the runtime inspector bridge."""

    def __init__(self):
        self.calls = []

    def start_session(self):
        self.calls.append(("start", None))
        return {"weaver_session_id": "runtime-1"}

    def current_question(self):
        self.calls.append(("question", None))
        return {"question": {"questionName": "intro"}}

    def variables(self):
        self.calls.append(("variables", None))
        return {"variables": {"user_name": "Sam"}}

    def apply_scenario(self, variables, delete):
        self.calls.append(("scenario", variables))
        return {"updated": True}

    def back(self):
        self.calls.append(("back", None))
        return {"went_back": True}

    def inspect(self, action_name, arguments):
        self.calls.append((action_name, arguments))
        if action_name not in {
            "al_weaver.inspect_variable",
            "al_weaver.inspect_gathering_state",
        }:
            raise ValueError("That runtime inspection action is not allowlisted")
        return {"status": "success", "data": {"name": arguments.get("name")}}


class AgentToolTestCase(unittest.TestCase):
    def setUp(self):
        # DAYamlChecker is exercised through its own hook so these tests stay
        # deterministic and do not depend on the checker's current rule set.
        patcher = patch.object(
            editor_agent_validation, "dayamlchecker_findings", return_value=[]
        )
        self.addCleanup(patcher.stop)
        self.checker = patcher.start()
        self.candidate = AgentCandidate.from_source(INTERVIEW)
        self.context = ToolContext(
            project="default",
            filename="main.yml",
            owner_user_id=7,
            candidate=self.candidate,
        )

    def call(self, tool, arguments=None, expected_revision=None):
        return execute_tool(
            self.context,
            AgentToolCall(
                tool=tool,
                arguments={} if arguments is None else arguments,
                expected_candidate_revision=expected_revision,
            ),
        )


class TestToolBoundary(AgentToolTestCase):
    def test_unregistered_tools_cannot_run(self):
        for name in ("eval_python", "shell", "edit_other_file", "delete_project"):
            with self.subTest(tool=name):
                self.assertNotIn(name, TOOL_REGISTRY)
                result = self.call(name, {"anything": True})
                self.assertEqual(result.reason, "unknown_tool")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)

    def test_high_risk_and_runtime_tools_are_not_exposed_by_default(self):
        names = available_tool_names()
        self.assertNotIn("runtime_start_session", names)
        self.assertIn(
            "runtime_start_session", available_tool_names(runtime_enabled=True)
        )
        for spec in TOOL_REGISTRY.values():
            self.assertIn(spec.risk, {"low", "medium"})

    def test_project_and_filename_cannot_be_supplied_by_a_tool_call(self):
        result = self.call(
            "replace_question",
            {
                "block_id": "intro",
                "project": "other_project",
                "filename": "secrets.yml",
                "question": {"question": "Hi"},
            },
        )
        self.assertEqual(result.reason, "invalid_arguments")
        self.assertIn("project", result.message)
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)
        # The bound target is the only one a handler can ever see.
        self.assertEqual(self.context.project, "default")
        self.assertEqual(self.context.filename, "main.yml")

    def test_invalid_argument_schema_changes_nothing(self):
        for arguments in (
            {"block_id": "intro"},
            {"block_id": "intro", "question": {"subquestion": "no question key"}},
            {"block_id": 17, "question": {"question": "Hi"}},
            {"block_id": "intro", "question": {"question": ""}},
        ):
            with self.subTest(arguments=arguments):
                result = self.call("replace_question", arguments)
                self.assertEqual(result.reason, "invalid_arguments")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)

    def test_free_form_objects_stay_open_but_named_schemas_do_not(self):
        self.assertEqual(
            validate_against_schema({"type": "object"}, {"anything": 1}), []
        )
        self.assertEqual(
            validate_against_schema(
                {"type": "object", "additionalProperties": False, "properties": {}},
                {"anything": 1},
            ),
            ["arguments.anything is not an accepted argument"],
        )

    def test_unknown_block_changes_nothing(self):
        result = self.call(
            "replace_question",
            {"block_id": "does_not_exist", "question": {"question": "Hi"}},
        )
        self.assertEqual(result.reason, "block_not_found")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)

    def test_unsupported_block_is_read_only(self):
        from .editor_utils import parse_interview_yaml

        tagged = next(
            block
            for block in parse_source_document("main.yml", INTERVIEW).documents
            if not block.supported
        )
        block_id = next(
            block["id"]
            for block in parse_interview_yaml(INTERVIEW)["blocks"]
            if block["index"] == tagged.document_index
        )
        result = self.call(
            "replace_question",
            {"block_id": block_id, "question": {"question": "Rewritten"}},
        )
        self.assertEqual(result.reason, "unsupported_block")
        self.assertIn("cannot losslessly represent", result.message)
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)

    def test_stale_candidate_revision_is_rejected(self):
        result = self.call(
            "replace_question",
            {"block_id": "intro", "question": {"question": "Hi"}},
            expected_revision="a-revision-from-an-earlier-turn",
        )
        self.assertEqual(result.reason, "stale_candidate")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)

    def test_a_no_op_move_is_refused_rather_than_producing_an_overlapping_patch(self):
        result = self.call(
            "move_block",
            {
                "block_id": "user_address",
                "relative_to_block_id": "intro",
                "position": "after",
            },
        )
        self.assertEqual(result.reason, "no_op_move")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)


class TestCandidateValidationGate(AgentToolTestCase):
    def test_dayamlchecker_error_prevents_acceptance(self):
        self.checker.side_effect = lambda raw_yaml, filename: [
            {
                "level": "error",
                "severity": "error",
                "message": "A required field is missing",
                "filename": filename,
                "line_number": 1,
                "source": "dayamlchecker",
            }
        ]
        result = self.call(
            "replace_question",
            {"block_id": "intro", "question": {"question": "Rewritten"}},
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "candidate_validation_failed")
        self.assertTrue(result.diagnostics)
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)
        self.assertEqual(self.context.candidate.applied_commands, [])

    def test_candidate_stays_at_the_last_valid_revision_after_a_failure(self):
        first = self.call(
            "replace_question",
            {"block_id": "intro", "question": {"question": "First edit"}},
        )
        self.assertTrue(first.succeeded)
        good_revision = self.context.candidate.revision
        good_source = self.context.candidate.raw_source

        self.checker.side_effect = lambda raw_yaml, filename: (
            [
                {
                    "level": "error",
                    "severity": "error",
                    "message": "Broken",
                    "filename": filename,
                }
            ]
            if "Second edit" in raw_yaml
            else []
        )
        second = self.call(
            "replace_question",
            {"block_id": "intro", "question": {"question": "Second edit"}},
        )
        self.assertEqual(second.reason, "candidate_validation_failed")
        self.assertEqual(self.context.candidate.revision, good_revision)
        self.assertEqual(self.context.candidate.raw_source, good_source)
        self.assertEqual(len(self.context.candidate.applied_commands), 1)


class TestLosslessEditing(AgentToolTestCase):
    def test_a_successful_edit_touches_only_the_target_block(self):
        result = self.call(
            "replace_question",
            {
                "block_id": "user_address",
                "question": {
                    "question": "Where do you currently live?",
                    "fields": [
                        {
                            "label": "Street address",
                            "field": "users[0].address.address",
                            "datatype": "text",
                        }
                    ],
                },
            },
        )
        self.assertTrue(result.succeeded)
        updated = self.context.candidate.raw_source

        # Everything outside the edited document is byte-identical.
        self.assertIn("# file header comment", updated)
        self.assertIn("# keep this block comment", updated)
        self.assertIn("title: Demo interview", updated)
        self.assertIn("value: !custom something", updated)
        self.assertIn("  - Your name: user_name", updated)
        self.assertIn("Where do you currently live?", updated)
        self.assertNotIn("Where do you live?", updated)
        self.assertEqual(updated.count("---"), INTERVIEW.count("---"))

    def test_insert_places_a_new_screen_at_the_requested_anchor(self):
        result = self.call(
            "insert_question",
            {
                "new_block_id": "has_children",
                "relative_to_block_id": "user_address",
                "position": "before",
                "question": {
                    "question": "Do you have children?",
                    "fields": [
                        {
                            "label": "Children",
                            "field": "has_children",
                            "datatype": "yesno",
                        }
                    ],
                },
            },
        )
        self.assertTrue(result.succeeded)
        updated = self.context.candidate.raw_source
        self.assertLess(updated.index("id: intro"), updated.index("id: has_children"))
        self.assertLess(
            updated.index("id: has_children"), updated.index("id: user_address")
        )
        self.assertIn("value: !custom something", updated)

    def test_duplicate_block_ids_are_refused(self):
        result = self.call(
            "insert_question",
            {"new_block_id": "intro", "question": {"question": "Another intro"}},
        )
        self.assertEqual(result.reason, "duplicate_block_id")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)

    def test_more_fields_than_a_screen_allows_are_refused_not_truncated(self):
        result = self.call(
            "replace_fields",
            {
                "block_id": "intro",
                "fields": [
                    {"label": f"Field {index}", "field": f"field_{index}"}
                    for index in range(9)
                ],
            },
        )
        self.assertEqual(result.reason, "invalid_arguments")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)

    def test_order_is_written_from_structured_steps(self):
        result = self.call(
            "replace_order_steps",
            {
                "steps": [
                    {"kind": "screen", "invoke": "intro"},
                    {"kind": "screen", "invoke": "has_children"},
                    {"kind": "screen", "invoke": "user_address"},
                ]
            },
        )
        self.assertTrue(result.succeeded)
        updated = self.context.candidate.raw_source
        self.assertIn("  has_children\n", updated)
        # The order block had no explicit id; a fingerprint is never written back.
        self.assertNotIn("id: block-", updated)

    def test_the_diff_is_taken_against_the_session_working_source(self):
        self.call(
            "replace_question",
            {"block_id": "intro", "question": {"question": "Changed"}},
        )
        diff = self.context.candidate.diff("main.yml")
        self.assertIn("+  Changed", diff)
        self.assertNotIn("user_address", diff.split("@@")[0])


class TestExitScreens(AgentToolTestCase):
    """A screen that ends the interview is a different shape from a question."""

    def test_an_exit_screen_has_an_event_and_no_fields(self):
        result = self.call(
            "insert_exit_screen",
            {
                "new_block_id": "no_fax_exit",
                "screen": {
                    "question": "The recipient has no fax machine",
                    "subquestion": "Please send an email instead.",
                },
            },
        )
        self.assertTrue(result.succeeded, result.message)
        updated = self.context.candidate.raw_source
        self.assertIn("event: no_fax_exit", updated)
        self.assertIn("id: no_fax_exit", updated)
        # An empty field list is not a screen that asks nothing; it is malformed.
        self.assertNotIn("fields: []", updated)
        self.assertNotIn("fields:\n---", updated)

    def test_a_question_screen_with_no_fields_omits_the_key_entirely(self):
        result = self.call(
            "insert_question",
            {"new_block_id": "just_a_notice", "question": {"question": "Read this"}},
        )
        self.assertTrue(result.succeeded, result.message)
        self.assertNotIn("fields: []", self.context.candidate.raw_source)

    def test_the_event_name_defaults_to_the_block_id(self):
        self.call(
            "insert_exit_screen",
            {"new_block_id": "stop_here", "screen": {"question": "Stopping"}},
        )
        self.assertIn("event: stop_here", self.context.candidate.raw_source)

    def test_an_unusable_event_name_is_refused(self):
        result = self.call(
            "insert_exit_screen",
            {
                "new_block_id": "exit_one",
                "event_name": "not a name",
                "screen": {"question": "Stopping"},
            },
        )
        self.assertEqual(result.reason, "invalid_event_name")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)

    def test_buttons_are_written_in_docassemble_form(self):
        self.call(
            "insert_exit_screen",
            {
                "new_block_id": "stop_here",
                "screen": {"question": "Stopping"},
                "buttons": [{"label": "Exit", "action": "exit"}],
            },
        )
        self.assertIn("buttons:\n- Exit: exit", self.context.candidate.raw_source)

    def test_a_stray_block_scalar_marker_is_not_written_into_the_text(self):
        """Models hand back "|\\n  text" for a value Weaver already serialises
        as a block scalar. Left alone it produces a doubled `question: |` / `|`."""
        self.call(
            "insert_exit_screen",
            {
                "new_block_id": "stop_here",
                "screen": {"question": "|\n    The recipient has no fax machine."},
            },
        )
        updated = self.context.candidate.raw_source
        self.assertIn("question: |\n  The recipient has no fax machine.", updated)
        self.assertNotIn("  |\n", updated)


class TestOrderSteps(AgentToolTestCase):
    def test_a_condition_reaches_an_exit_event_by_name(self):
        result = self.call(
            "replace_order_steps",
            {
                "steps": [
                    {"kind": "screen", "invoke": "intro"},
                    {
                        "kind": "condition",
                        "condition": "not has_fax",
                        "children": [{"kind": "screen", "invoke": "no_fax_exit"}],
                    },
                ]
            },
        )
        self.assertTrue(result.succeeded, result.message)
        self.assertIn(
            "  if not has_fax:\n    no_fax_exit", self.context.candidate.raw_source
        )

    def test_a_bare_screen_name_in_children_is_normalised_not_crashed(self):
        """serialize_order_steps assumes every step is a mapping, so a list of
        names used to raise and reach the model as "the tool is broken"."""
        result = self.call(
            "replace_order_steps",
            {
                "steps": [
                    "intro",
                    {
                        "kind": "condition",
                        "condition": "not has_fax",
                        "children": ["no_fax_exit"],
                    },
                ]
            },
        )
        self.assertTrue(result.succeeded, result.message)
        updated = self.context.candidate.raw_source
        self.assertIn("  intro\n", updated)
        self.assertIn("  if not has_fax:\n    no_fax_exit", updated)

    def test_steps_that_cannot_be_serialised_are_explained_not_raised(self):
        result = self.call(
            "replace_order_steps", {"steps": [{"kind": "condition", "children": [7]}]}
        )
        self.assertNotEqual(result.status, "error")
        self.assertEqual(self.context.candidate.raw_source, INTERVIEW)


class TestReadTools(AgentToolTestCase):
    def test_outline_marks_unsupported_blocks_as_not_editable(self):
        result = self.call("get_interview_outline")
        self.assertTrue(result.succeeded)
        self.assertEqual(result.data["fact_source"], "static_analysis")
        editable = {row["block_id"]: row["editable"] for row in result.data["blocks"]}
        self.assertTrue(editable["intro"])
        self.assertIn(False, editable.values())

    def test_variable_search_and_references_find_declared_variables(self):
        search = self.call("search_variables", {"query": "address"})
        self.assertTrue(
            any(
                item["variable"] == "users[0].address.address"
                for item in search.data["variables"]
            )
        )
        references = self.call("find_variable_references", {"variable": "user_name"})
        self.assertTrue(references.data["references"])

    def test_validate_candidate_reports_the_authoritative_verdict(self):
        result = self.call("validate_candidate")
        self.assertTrue(result.succeeded)
        self.assertFalse(result.data["blocking"])
        self.assertEqual(result.data["candidate_revision"], self.candidate.revision)


class TestRuntimeTools(AgentToolTestCase):
    def setUp(self):
        super().setUp()
        self.runtime = _FakeRuntime()
        self.context.runtime_enabled = True
        self.context.runtime = self.runtime

    def test_runtime_tools_are_unavailable_when_the_flag_is_off(self):
        self.context.runtime_enabled = False
        result = self.call("runtime_start_session")
        self.assertEqual(result.reason, "unknown_tool")
        self.assertFalse(self.runtime.calls)

    def test_runtime_requires_a_session_before_inspection(self):
        result = self.call("runtime_current_question")
        self.assertEqual(result.reason, "runtime_session_missing")
        self.assertFalse(self.runtime.calls)

    def test_runtime_results_are_labelled_as_observed(self):
        self.assertTrue(self.call("runtime_start_session").succeeded)
        result = self.call("runtime_current_question")
        self.assertTrue(result.succeeded)
        self.assertEqual(result.data["fact_source"], "observed_runtime")
        self.assertFalse(result.data["scenario_seeded"])

    def test_a_seeded_scenario_marks_every_later_observation_as_a_fixture(self):
        self.call("runtime_start_session")
        seeded = self.call(
            "runtime_apply_scenario", {"variables": {"has_children": True}}
        )
        self.assertTrue(seeded.succeeded)
        self.assertTrue(seeded.data["scenario_seeded"])
        self.assertIn("bypass earlier gathering", seeded.data["warning"])

        later = self.call("runtime_current_question")
        self.assertTrue(later.data["scenario_seeded"])

    def test_runtime_actions_stay_inside_the_allowlist(self):
        self.call("runtime_start_session")
        result = self.call("runtime_inspect_variable", {"name": "user_name"})
        self.assertTrue(result.succeeded)
        self.assertEqual(self.runtime.calls[-1][0], "al_weaver.inspect_variable")
        # No tool exists that can name an arbitrary action.
        self.assertEqual(
            self.call("runtime_action", {"action": "al_weaver.delete"}).reason,
            "unknown_tool",
        )


class TestSessionCandidateLifecycle(unittest.TestCase):
    def test_reset_restores_the_original_working_candidate(self):
        session = WeaverAgentSession(
            session_id="s1",
            owner_user_id=7,
            project="default",
            filename="main.yml",
            base_saved_revision="saved",
            original_working_source=INTERVIEW,
            candidate_source=INTERVIEW.replace("Welcome", "Changed"),
            candidate_revision="candidate",
            messages=[{"role": "user", "content": "hi"}],
            command_history=[{"sequence": 1, "tool": "replace_question"}],
        )
        session.reset_candidate()
        self.assertEqual(session.candidate_source, INTERVIEW)
        self.assertEqual(session.command_history, [])
        self.assertEqual(session.messages, [])

    def test_public_session_state_never_leaks_internal_identifiers(self):
        session = WeaverAgentSession(
            session_id="s1",
            owner_user_id=7,
            project="default",
            filename="main.yml",
            base_saved_revision="saved",
            original_working_source=INTERVIEW,
            candidate_source=INTERVIEW,
            candidate_revision="candidate",
        )
        payload = session.public_dict()
        self.assertNotIn("owner_user_id", payload)
        self.assertNotIn("original_working_source", payload)
        self.assertNotIn("candidate_source", payload)


if __name__ == "__main__":
    unittest.main()

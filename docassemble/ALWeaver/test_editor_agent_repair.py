# do not pre-load

"""Deterministic repair of mechanical id problems.

These tests run against the real DAYamlChecker on purpose. The classifier keys
off the checker's own wording to decide what it may promise a developer, so if
that wording ever drifts these tests are what catches it.
"""

import unittest

from .editor_agent_models import WeaverAgentSession
from .editor_agent_repair import (
    REPAIR_DUPLICATE_ID,
    REPAIR_MISSING_ID,
    auto_heal_source,
    classify_diagnostics,
    describe_repair_offer,
)
from .editor_agent_validation import validate_candidate_source

BROKEN = """# file header comment
metadata:
  title: Demo
---
# a comment above the block
question: |
  What is your name?
fields:
  - Name: user_name
---
id: intro
question: Hello
---
id: intro
question: Hello again
---
event: review_answers
question: Review your answers
review:
  - Edit: user_name
---
mandatory: True
code: |
  user_name
"""

# Mechanical id problems plus one the checker flags that no rule can fix.
MIXED = BROKEN.replace(
    "id: intro\nquestion: Hello\n---",
    "id: intro\nquestion: Hello\nnot_a_docassemble_key: true\n---",
    1,
)

# A block Weaver preserves but cannot represent losslessly, so it stays
# read-only even though it is a question block with no id.
WITH_UNSUPPORTED = """id: intro
question: Hello
---
question: A tagged block
subquestion: !custom something
---
mandatory: True
code: |
  intro
"""


class TestClassification(unittest.TestCase):
    def test_the_checker_still_reports_the_problems_we_promise_to_fix(self):
        validation = validate_candidate_source(filename="main.yml", raw_yaml=BROKEN)
        self.assertTrue(validation.blocking)
        repairable, remaining = classify_diagnostics(validation.blocking_diagnostics())
        self.assertTrue(repairable, "no id diagnostics were recognised as repairable")
        self.assertEqual(remaining, [])

    def test_problems_needing_a_human_are_never_claimed_as_repairable(self):
        repairable, remaining = classify_diagnostics(
            [
                {
                    "level": "error",
                    "message": 'Duplicate block id "intro" - first used at line 4',
                },
                {
                    "level": "error",
                    "message": "question block is missing an `id`: Hello",
                },
                {"level": "error", "message": "Undefined variable referenced: mystery"},
                {
                    "level": "warning",
                    "message": "question block is missing an `id`: Ignored",
                },
            ]
        )
        self.assertEqual(len(repairable), 2)
        self.assertEqual(len(remaining), 1)


class TestAutoHeal(unittest.TestCase):
    def setUp(self):
        self.result = auto_heal_source(filename="main.yml", raw_yaml=BROKEN)

    def test_a_healed_file_passes_the_same_validator_that_rejected_it(self):
        self.assertTrue(self.result.healed)
        self.assertEqual(self.result.remaining_blocking, [])
        validation = validate_candidate_source(
            filename="main.yml", raw_yaml=self.result.raw_yaml
        )
        self.assertFalse(validation.blocking)

    def test_a_missing_id_is_derived_from_the_screen_title(self):
        added = [
            repair for repair in self.result.repairs if repair.kind == REPAIR_MISSING_ID
        ]
        self.assertEqual(
            sorted(repair.new_id for repair in added),
            ["review_your_answers", "what_is_your_name"],
        )
        self.assertIn("id: what_is_your_name\n", self.result.raw_yaml)

    def test_the_first_block_keeps_its_id_and_the_repeat_is_renamed(self):
        renamed = [
            repair
            for repair in self.result.repairs
            if repair.kind == REPAIR_DUPLICATE_ID
        ]
        self.assertEqual(len(renamed), 1)
        self.assertEqual(renamed[0].previous_id, "intro")
        self.assertEqual(renamed[0].new_id, "intro_2")
        self.assertIn("id: intro\nquestion: Hello\n", self.result.raw_yaml)
        self.assertIn("id: intro_2\nquestion: Hello again\n", self.result.raw_yaml)

    def test_the_developer_is_told_the_override_behaviour_changed(self):
        renamed = next(
            repair
            for repair in self.result.repairs
            if repair.kind == REPAIR_DUPLICATE_ID
        )
        self.assertIn("silently using only the last block", renamed.summary)

    def test_repairs_touch_nothing_but_the_id_lines(self):
        healed = self.result.raw_yaml
        self.assertIn("# file header comment", healed)
        self.assertIn("# a comment above the block", healed)
        self.assertIn("  - Name: user_name", healed)
        self.assertIn("question: |\n  What is your name?", healed)
        self.assertEqual(healed.count("---"), BROKEN.count("---"))
        # Every added line is an id line; nothing else grew.
        added_lines = [
            line for line in healed.splitlines() if line not in BROKEN.splitlines()
        ]
        self.assertTrue(
            all(line.startswith("id: ") for line in added_lines), added_lines
        )

    def test_an_unsupported_block_is_never_given_an_id(self):
        result = auto_heal_source(filename="main.yml", raw_yaml=WITH_UNSUPPORTED)
        self.assertEqual(result.repairs, [])
        self.assertIn(
            "question: A tagged block\nsubquestion: !custom something",
            result.raw_yaml,
        )

    def test_a_checker_that_cannot_run_is_reported_but_does_not_block(self):
        # DAYamlChecker raises on this construct. A checker that fails to run is
        # not a file that failed a check, so editing continues under Weaver's
        # own structural validation with the gap stated plainly.
        validation = validate_candidate_source(
            filename="main.yml", raw_yaml=WITH_UNSUPPORTED
        )
        self.assertFalse(validation.blocking)
        messages = [str(item.get("message")) for item in validation.diagnostics]
        self.assertTrue(
            any("could not analyse this interview" in message for message in messages),
            messages,
        )

    def test_a_valid_file_is_returned_untouched(self):
        healthy = "id: intro\nquestion: Hello\n---\nmandatory: True\ncode: |\n  intro\n"
        result = auto_heal_source(filename="main.yml", raw_yaml=healthy)
        self.assertEqual(result.raw_yaml, healthy)
        self.assertEqual(result.repairs, [])
        self.assertTrue(result.healed)

    def test_structurally_broken_source_is_left_alone(self):
        broken_yaml = "id: intro\nquestion: [unterminated\n"
        result = auto_heal_source(filename="main.yml", raw_yaml=broken_yaml)
        self.assertEqual(result.raw_yaml, broken_yaml)
        self.assertEqual(result.repairs, [])
        self.assertFalse(result.healed)


class TestRepairOffer(unittest.TestCase):
    def test_the_offer_counts_only_what_it_can_actually_fix(self):
        offer = describe_repair_offer(filename="main.yml", raw_yaml=BROKEN)
        self.assertTrue(offer["can_auto_heal"])
        self.assertEqual(offer["unrepairable_count"], 0)
        self.assertEqual(len(offer["repairs"]), offer["repairable_count"])

    def test_nothing_is_offered_when_the_file_is_already_valid(self):
        healthy = "id: intro\nquestion: Hello\n"
        offer = describe_repair_offer(filename="main.yml", raw_yaml=healthy)
        self.assertFalse(offer["can_auto_heal"])
        self.assertEqual(offer["repairs"], [])

    def test_a_file_with_a_non_mechanical_error_is_not_offered_a_full_fix(self):
        offer = describe_repair_offer(filename="main.yml", raw_yaml=MIXED)
        self.assertGreater(offer["repairable_count"], 0)
        self.assertGreater(offer["unrepairable_count"], 0)
        # Partial healing is never presented as a fix, because the session still
        # could not start afterwards.
        self.assertFalse(offer["can_auto_heal"])

    def test_partial_repairs_leave_the_remaining_problems_visible(self):
        result = auto_heal_source(filename="main.yml", raw_yaml=MIXED)
        self.assertFalse(result.healed)
        self.assertTrue(result.remaining_blocking)

    def test_describing_an_offer_never_mutates_the_source(self):
        before = BROKEN
        describe_repair_offer(filename="main.yml", raw_yaml=BROKEN)
        self.assertEqual(BROKEN, before)


class TestRepairedSessionBaseline(unittest.TestCase):
    def test_reset_returns_to_the_repaired_source_not_the_broken_one(self):
        healed = auto_heal_source(filename="main.yml", raw_yaml=BROKEN).raw_yaml
        session = WeaverAgentSession(
            session_id="agent-1",
            owner_user_id=7,
            project="default",
            filename="main.yml",
            base_saved_revision="saved",
            original_working_source=BROKEN,
            candidate_source=healed.replace("Hello again", "Changed"),
            candidate_revision="candidate",
            repaired_working_source=healed,
        )
        session.reset_candidate()
        self.assertEqual(session.candidate_source, healed)
        # Resetting to the developer's own broken source would strand the
        # session: every later edit would fail the same validator.
        self.assertNotEqual(session.candidate_source, BROKEN)

    def test_the_diff_base_stays_the_developer_source_so_repairs_are_visible(self):
        healed = auto_heal_source(filename="main.yml", raw_yaml=BROKEN).raw_yaml
        session = WeaverAgentSession(
            session_id="agent-1",
            owner_user_id=7,
            project="default",
            filename="main.yml",
            base_saved_revision="saved",
            original_working_source=BROKEN,
            candidate_source=healed,
            candidate_revision="candidate",
            repaired_working_source=healed,
        )
        candidate = session.candidate()
        self.assertTrue(candidate.changed)
        diff = candidate.diff("main.yml")
        self.assertIn("+id: intro_2", diff)
        self.assertIn("+id: what_is_your_name", diff)


if __name__ == "__main__":
    unittest.main()

# do not pre-load
"""Lucky mode's AI-powered questions: picked by the model, checked by Weaver."""

import unittest

import yaml

from .ai_question_suggestions import (
    add_suggested_ai_questions,
    long_answer_fields,
    validated_suggestions,
)

SOURCE = """metadata:
  title: Test
---
id: interview order
mandatory: True
code: |
  user_name
  incident_description
  reasons
---
id: name
question: |
  What is your name?
fields:
  - Name: user_name
---
id: story
question: |
  Tell us what happened
fields:
  - no label: incident_description
    datatype: area
---
id: reasons
question: |
  Why are you asking the court?
fields:
  - Reasons: reasons
    input type: area
  - Anything else: other_notes
    datatype: area
    required: False
"""


class TestCandidates(unittest.TestCase):
    def test_only_long_answers_are_candidates(self):
        found = long_answer_fields(SOURCE)
        self.assertEqual(
            [(c["question_block_id"], c["variable"], c["label"]) for c in found],
            [
                ("story", "incident_description", ""),
                ("reasons", "reasons", "Reasons"),
                ("reasons", "other_notes", "Anything else"),
            ],
        )

    def test_the_models_answer_is_checked(self):
        candidates = long_answer_fields(SOURCE)
        picks = validated_suggestions(
            {
                "suggestions": [
                    {"variable": "made_up", "task": "goal", "rubric": "x"},
                    {"variable": "reasons", "task": "run_code"},
                    {"variable": "incident_description", "task": "goal"},
                    {"variable": "incident_description", "task": "rewrite"},
                    {"variable": "reasons", "task": "rewrite", "review_question": ""},
                    {"variable": "other_notes", "task": "rewrite"},
                    {"variable": "other_notes", "task": "rewrite"},
                ]
            },
            candidates,
        )
        self.assertEqual(
            [(p["candidate"]["variable"], p["task"]) for p in picks],
            [
                ("incident_description", "rewrite"),  # a goal needs a rubric
                ("reasons", "rewrite"),
                ("other_notes", "rewrite"),
            ],
        )
        self.assertEqual(picks[1]["review_question"], "Review your answer")
        self.assertEqual(validated_suggestions("nonsense", candidates), [])


class TestAdding(unittest.TestCase):
    def test_suggestions_become_ai_help_that_keeps_the_variables(self):
        sent = {}

        def ask(system, user):
            sent["user"] = user
            return {
                "suggestions": [
                    {
                        "variable": "incident_description",
                        "task": "goal",
                        "rubric": "What happened and when.",
                        "review_question": "Review your story",
                    }
                ]
            }

        updated, notes = add_suggested_ai_questions(SOURCE, ask)
        self.assertIn('"variable": "incident_description"', sent["user"])
        self.assertEqual(notes, ["Added AI help (goal) to incident_description."])
        docs = [d for d in yaml.safe_load_all(updated) if d]
        order = next(d for d in docs if d.get("id") == "interview order")["code"]
        self.assertIn("incident_description_draft\nincident_description\n", order)
        objects = next(d for d in docs if "objects" in d)["objects"]
        self.assertIn(
            'rubric="What happened and when."', objects[0]["incident_description_ai"]
        )
        self.assertIn(
            'initial_question="Tell us what happened"',
            objects[0]["incident_description_ai"],
        )

    def test_a_model_failure_leaves_the_interview_alone(self):
        def ask(system, user):
            raise RuntimeError("down")

        updated, notes = add_suggested_ai_questions(SOURCE, ask)
        self.assertEqual(updated, SOURCE)
        self.assertEqual(notes, ["AI-powered questions were skipped: RuntimeError"])

    def test_no_long_answers_means_no_model_call(self):
        source = SOURCE.split("---\nid: story")[0]
        updated, notes = add_suggested_ai_questions(
            source, lambda *a: self.fail("called")
        )
        self.assertEqual((updated, notes), (source, []))


if __name__ == "__main__":
    unittest.main()

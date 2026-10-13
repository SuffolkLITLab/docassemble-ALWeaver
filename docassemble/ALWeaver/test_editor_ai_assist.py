# do not pre-load
"""AI help on a field: the declaration, include, review question and order line.

Every edit is checked the way docassemble would read it: the YAML is parsed
back, and the settings are read from the declaration without running it.
"""

import ast
import unittest

import yaml

from .editor_ai_assist import (
    AI_ASSIST_INCLUDE,
    apply_ai_assist,
    describe_ai_assists,
    normalize_ai_assist_config,
    parse_ai_assist_expression,
    remove_ai_assist,
    render_ai_assist_expression,
)
from .editor_utils import parse_interview_yaml, parse_order_code, serialize_order_steps

SOURCE = """metadata:
  title: Test
---
include:
  - docassemble.AssemblyLine:assembly_line.yml  # the basics
---
objects:
  - users: ALPeopleList.using(ask_number=True, target_number=1)  # people
---
id: interview order
mandatory: True
code: |
  intro
  # the story
  incident_description
  if users[0].name.first:
    notice_text
  all_done
---
id: story
question: |
  Tell us what happened
fields:
  - no label: incident_description
    datatype: area
"""

REWRITE = {
    "task": "rewrite",
    "source": "incident_description",
    "output": "incident_narrative",
    "review_question": "Review your description",
    "instructions": "Keep it short: 3 sentences.",
}

EXTRACT = {
    "task": "extract",
    "source": "notice_text",
    "outputs": [
        {
            "variable": "hearing_date",
            "label": "Hearing date",
            "datatype": "date",
            "description": "The hearing date",
        },
        {"variable": "court_name", "label": "Court: name"},
    ],
    "review_question": "Check the information we found",
}


def documents(source):
    return [doc for doc in yaml.safe_load_all(source) if doc]


def declared(source):
    out = {}
    for doc in documents(source):
        for item in doc.get("objects") or []:
            out.update(item)
    return out


def order_code(source):
    return next(d for d in documents(source) if d.get("id") == "interview order")[
        "code"
    ]


class TestExpression(unittest.TestCase):
    def test_settings_round_trip_through_the_declaration(self):
        settings = {
            "task": "extract",
            "source": "notice",
            "outputs": {"a": 'Say "hi": now', "b": "ünïcode"},
            "model": "",
            "ask_permission": False,
            "question_limit": 3,
        }
        expression = render_ai_assist_expression(settings)
        self.assertNotIn("model", expression)
        parsed = parse_ai_assist_expression(expression)
        self.assertEqual(parsed["computed"], [])
        self.assertEqual(
            parsed["settings"],
            {
                "task": "extract",
                "source": "notice",
                "outputs": {"a": 'Say "hi": now', "b": "ünïcode"},
                "ask_permission": False,
                "question_limit": 3,
            },
        )

    def test_expressions_are_reported_not_run(self):
        parsed = parse_ai_assist_expression(
            'AIAssist.using(task="prompt", instructions=my_prompt)'
        )
        self.assertEqual(parsed["settings"], {"task": "prompt"})
        self.assertEqual(parsed["computed"], ["instructions"])
        self.assertIsNone(parse_ai_assist_expression("DAObject"))


class TestValidation(unittest.TestCase):
    def check_rejected(self, **changes):
        config = dict(REWRITE, **changes)
        with self.assertRaises(ValueError):
            normalize_ai_assist_config(config)

    def test_bad_settings_are_rejected(self):
        self.check_rejected(task="run_code")
        self.check_rejected(source="not a variable")
        self.check_rejected(output="incident_description")  # keeps the original
        self.check_rejected(output="import")
        self.check_rejected(review_question="")
        self.check_rejected(task="prompt", instructions="")
        self.check_rejected(model="gpt 5; rm")
        self.check_rejected(task="goal", rubric="")
        self.check_rejected(task="translate", language="")

    def test_extraction_needs_distinct_typed_answers(self):
        with self.assertRaises(ValueError):
            normalize_ai_assist_config(dict(EXTRACT, outputs=[]))
        twice = [{"variable": "a"}, {"variable": "a"}]
        with self.assertRaises(ValueError):
            normalize_ai_assist_config(dict(EXTRACT, outputs=twice))
        with self.assertRaises(ValueError):
            normalize_ai_assist_config(
                dict(EXTRACT, outputs=[{"variable": "a", "datatype": "signature"}])
            )

    def test_a_choice_needs_two_choices(self):
        config = dict(
            REWRITE,
            task="classify",
            output="problem",
            choices=[{"label": "Eviction", "value": "eviction"}],
        )
        with self.assertRaises(ValueError):
            normalize_ai_assist_config(config)


class TestApply(unittest.TestCase):
    def test_one_save_writes_all_four_pieces(self):
        updated, summary = apply_ai_assist(SOURCE, REWRITE, question_block_id="story")
        self.assertEqual(
            summary,
            {
                "name": "incident_description_ai",
                "review_block_id": "review incident_narrative",
                "added_to_order": True,
            },
        )
        docs = documents(updated)
        includes = next(d for d in docs if "include" in d)["include"]
        self.assertEqual(includes[-1], AI_ASSIST_INCLUDE)
        settings = parse_ai_assist_expression(
            declared(updated)["incident_description_ai"]
        )["settings"]
        self.assertEqual(settings["instructions"], "Keep it short: 3 sentences.")
        review = next(d for d in docs if d.get("id") == "review incident_narrative")
        self.assertEqual(
            review["fields"],
            [
                {
                    "no label": "incident_narrative",
                    "datatype": "area",
                    "default": "${ incident_description_ai.suggestion() }",
                }
            ],
        )
        self.assertIn("incident_description_ai.review_note()", review["subquestion"])
        self.assertIn("incident_description\nincident_narrative\n", order_code(updated))
        # The review question comes right after the question with the field.
        ids = [d.get("id") for d in docs]
        self.assertEqual(ids.index("review incident_narrative"), ids.index("story") + 1)
        # Comments and the rest of the file are untouched.
        self.assertIn("# the basics", updated)
        self.assertIn("  # the story\n", updated)
        self.assertIn("target_number=1)  # people\n", updated)

    def test_a_second_field_joins_the_same_objects_block(self):
        once, _ = apply_ai_assist(SOURCE, REWRITE, question_block_id="story")
        twice, summary = apply_ai_assist(once, EXTRACT)
        self.assertEqual(twice.count("objects:"), 1)
        self.assertEqual(twice.count(AI_ASSIST_INCLUDE), 1)
        self.assertEqual(summary["name"], "notice_text_ai")
        # Inside the `if`, at its indentation.
        self.assertIn("  notice_text\n  hearing_date\n", order_code(twice))
        review = next(
            d for d in documents(twice) if d.get("id") == "review hearing_date"
        )
        self.assertEqual(review["fields"][1]["label"], "Court: name")
        self.assertEqual(
            review["fields"][0]["default"],
            '${ notice_text_ai.suggestion("hearing_date") }',
        )
        ast.parse(order_code(twice))

    def test_reopening_reads_back_what_was_saved(self):
        updated, _ = apply_ai_assist(SOURCE, EXTRACT)
        (assist,) = describe_ai_assists(parse_interview_yaml(updated))
        self.assertEqual(assist["output_kind"], "fields")
        self.assertEqual(assist["review_question"], "Check the information we found")
        self.assertEqual(
            [
                (f["variable"], f["label"], f["datatype"])
                for f in assist["review_fields"]
            ],
            [
                ("hearing_date", "Hearing date", "date"),
                ("court_name", "Court: name", "text"),
            ],
        )
        # And the parsed model hands it to the editor on its objects block.
        blocks = parse_interview_yaml(updated)["blocks"]
        self.assertEqual(
            [a["name"] for b in blocks for a in b.get("ai_assists", [])],
            ["notice_text_ai"],
        )

    def test_editing_updates_in_place_and_keeps_the_authors_subquestion(self):
        once, _ = apply_ai_assist(SOURCE, REWRITE, question_block_id="story")
        once = once.replace(
            "  ${ incident_description_ai.review_note() }",
            "  Check it.\n  ${ incident_description_ai.review_note() }",
        )
        twice, summary = apply_ai_assist(
            once,
            dict(REWRITE, review_question="Check your story", model="gpt-5-mini"),
            name="incident_description_ai",
            question_block_id="story",
        )
        self.assertFalse(summary["added_to_order"])  # already there
        self.assertEqual(order_code(twice).count("incident_narrative"), 1)
        self.assertEqual(twice.count("incident_description_ai: |"), 1)
        review = next(
            d for d in documents(twice) if d.get("id") == "review incident_narrative"
        )
        self.assertEqual(review["question"], "Check your story\n")
        self.assertTrue(review["subquestion"].startswith("Check it.\n"))
        self.assertIn('model="gpt-5-mini"', twice)

    def test_renaming_the_reviewed_answer_renames_its_order_line(self):
        once, _ = apply_ai_assist(SOURCE, REWRITE, question_block_id="story")
        twice, _ = apply_ai_assist(
            once,
            dict(REWRITE, output="incident_final"),
            name="incident_description_ai",
            question_block_id="story",
        )
        code = order_code(twice)
        self.assertNotIn("incident_narrative", code)
        self.assertIn("incident_description\nincident_final\n", code)

    def test_edits_keep_what_the_author_added_to_the_review_question(self):
        once, _ = apply_ai_assist(SOURCE, EXTRACT)
        once = once.replace(
            '    default: ${ notice_text_ai.suggestion("court_name") }\n',
            '    default: ${ notice_text_ai.suggestion("court_name") }\n'
            "    required: False\n"
            "    help: |\n"
            "      The court's full name.\n"
            "validation code: |\n"
            "  check_court(court_name)  # keep me\n",
        )
        renamed = [dict(row) for row in EXTRACT["outputs"]]
        renamed[1]["label"] = "Court name"
        twice, _ = apply_ai_assist(
            once,
            dict(EXTRACT, outputs=renamed, review_question="Check these"),
            name="notice_text_ai",
        )
        review = next(
            d for d in documents(twice) if d.get("id") == "review hearing_date"
        )
        self.assertEqual(review["question"], "Check these\n")
        court = review["fields"][1]
        self.assertEqual(court["Court name"], "court_name")
        self.assertIs(court["required"], False)
        self.assertEqual(court["help"], "The court's full name.\n")
        self.assertIn("  check_court(court_name)  # keep me\n", twice)

    def test_a_label_change_alone_is_saved(self):
        once, _ = apply_ai_assist(SOURCE, EXTRACT)
        renamed = [dict(row) for row in EXTRACT["outputs"]]
        renamed[0]["label"] = "Date of hearing"
        twice, _ = apply_ai_assist(
            once, dict(EXTRACT, outputs=renamed), name="notice_text_ai"
        )
        (assist,) = describe_ai_assists(parse_interview_yaml(twice))
        self.assertEqual(assist["review_fields"][0]["label"], "Date of hearing")

    def test_a_computed_declaration_is_not_rewritten(self):
        once, _ = apply_ai_assist(SOURCE, REWRITE, question_block_id="story")
        computed = once.replace(
            'instructions="Keep it short: 3 sentences."', "instructions=my_prompt"
        )
        with self.assertRaises(ValueError):
            apply_ai_assist(computed, REWRITE, name="incident_description_ai")

    def test_without_a_matching_order_line_nothing_is_guessed(self):
        source = SOURCE.replace("  incident_description\n", "")
        updated, summary = apply_ai_assist(source, REWRITE, question_block_id="story")
        self.assertFalse(summary["added_to_order"])
        self.assertNotIn("incident_narrative", order_code(updated))

    def test_a_file_without_objects_or_includes_gets_both(self):
        source = "id: story\nquestion: Hi\nfields:\n  - Story: story\n"
        updated, _ = apply_ai_assist(
            source,
            dict(REWRITE, source="story", output="story_final"),
            question_block_id="story",
        )
        docs = documents(updated)
        self.assertEqual(docs[0], {"include": [AI_ASSIST_INCLUDE]})
        self.assertIn("story_ai", declared(updated))

    def test_the_include_joins_the_right_one_of_several_include_blocks(self):
        source = SOURCE.replace(
            "---\nobjects:", "---\ninclude:\n  - other.yml\n  - more.yml\n---\nobjects:"
        )
        updated, _ = apply_ai_assist(source, REWRITE, question_block_id="story")
        includes = [d["include"] for d in documents(updated) if "include" in d]
        self.assertEqual(
            includes,
            [
                ["docassemble.AssemblyLine:assembly_line.yml", AI_ASSIST_INCLUDE],
                ["other.yml", "more.yml"],
            ],
        )

    def test_remove_takes_off_only_what_ai_help_added(self):
        once, _ = apply_ai_assist(SOURCE, REWRITE, question_block_id="story")
        removed = remove_ai_assist(once, "incident_description_ai")
        self.assertNotIn("incident_description_ai", removed)
        self.assertNotIn("incident_narrative", removed)
        self.assertIn("incident_description", removed)
        self.assertIn("users", declared(removed))
        self.assertIn(AI_ASSIST_INCLUDE, removed)


class TestRemoveInsideABranch(unittest.TestCase):
    def test_a_review_line_alone_in_an_if_leaves_pass(self):
        once, _ = apply_ai_assist(SOURCE, EXTRACT)
        once = once.replace("    notice_text\n    hearing_date\n", "    hearing_date\n")
        removed = remove_ai_assist(once, "notice_text_ai")
        code = order_code(removed)
        self.assertIn("if users[0].name.first:\n  pass\n", code)
        ast.parse(code)
        self.assertNotIn("review hearing_date", removed)


class TestOrderStep(unittest.TestCase):
    def test_an_ai_step_writes_its_two_lines_back_unchanged(self):
        code = "intro\nstory  # ask\nif x:\n  story_final\n"
        steps = parse_order_code(code)
        plain = serialize_order_steps(steps)
        ai_step = {
            "id": "ai-1",
            "kind": "ai",
            "assist": "story_ai",
            "children": steps[1:2],
        }
        nested = steps[2]
        nested["children"] = [
            {"id": "ai-2", "kind": "ai", "assist": "x", "children": nested["children"]}
        ]
        self.assertEqual(serialize_order_steps([steps[0], ai_step, nested]), plain)
        self.assertEqual(plain.rstrip("\n"), code.rstrip("\n"))


if __name__ == "__main__":
    unittest.main()

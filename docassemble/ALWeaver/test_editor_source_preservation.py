# do not pre-load
"""Regression tests for lossless graphical-editor block operations."""

import json
from pathlib import Path
import subprocess
import unittest

import yaml

from .editor_utils import (
    inserted_block_id_by_position,
    is_comment_only_yaml,
    comment_out_block_in_yaml,
    delete_block_from_yaml,
    enable_commented_block_in_yaml,
    insert_block_in_yaml,
    parse_interview_yaml,
    reorder_blocks_in_yaml,
    update_block_in_yaml,
)

SOURCE = (
    "# file header\n"
    "metadata:\n"
    "  title: 'Quoted' # metadata comment\n"
    "--- # separator annotation\n"
    "# question lead\n"
    "id: intro\n"
    "question: 'Original' # question comment\n"
    "fields:\n"
    "  - 'Name': user_name # field comment\n"
    "---\n"
    "\n"
    "---\n"
    "# code lead\n"
    "id: calculation\n"
    "code: |\n"
    "  # Python comment\n"
    "  answer = 'yes'\n"
)


class TestEditorSourcePreservation(unittest.TestCase):
    def test_parser_returns_exact_block_yaml(self):
        question = next(
            block
            for block in parse_interview_yaml(SOURCE)["blocks"]
            if block["id"] == "intro"
        )
        self.assertIn("# question lead", question["yaml"])
        self.assertIn("'Original' # question comment", question["yaml"])
        self.assertIn("'Name': user_name # field comment", question["yaml"])

    def test_graphical_value_edit_preserves_all_unchanged_annotations(self):
        graphical_yaml = (
            "id: intro\n" "question: |\n" "  Edited\n" "fields:\n" "- Name: user_name\n"
        )
        updated = update_block_in_yaml(
            SOURCE,
            "intro",
            graphical_yaml,
            preserve_unchanged_annotations=True,
        )
        self.assertEqual(
            updated,
            SOURCE.replace("'Original'", "|\n  Edited\n"),
        )

    def test_graphical_defaults_do_not_erase_explicit_field_annotations(self):
        source = SOURCE.replace(
            "  - 'Name': user_name # field comment\n",
            "  - 'Name': user_name # field comment\n    datatype: text\n",
        )
        graphical_yaml = (
            "id: intro\n" "question: Edited\n" "fields:\n" "- Name: user_name\n"
        )
        updated = update_block_in_yaml(
            source,
            "intro",
            graphical_yaml,
            preserve_unchanged_annotations=True,
        )
        self.assertIn("'Name': user_name # field comment", updated)
        self.assertIn("    datatype: text", updated)

    def test_graphical_edit_preserves_unchanged_literal_scalar_style(self):
        source = SOURCE.replace(
            "question: 'Original' # question comment\n",
            "question: 'Original' # question comment\n"
            "subquestion: |\n"
            "  Literal text.\n",
        )
        graphical_yaml = (
            "id: intro\n"
            "question: Edited\n"
            "subquestion: Literal text.\n"
            "fields:\n"
            "- Name: user_name\n"
        )
        updated = update_block_in_yaml(
            source,
            "intro",
            graphical_yaml,
            preserve_unchanged_annotations=True,
        )
        self.assertIn("subquestion: |\n  Literal text.\n", updated)

    def test_source_edit_replaces_only_target_document(self):
        edited = (
            "# new question lead\n"
            "id: intro\n"
            "question: Edited # new inline comment\n"
            "fields:\n"
            "  - Name: user_name\n"
        )
        updated = update_block_in_yaml(SOURCE, "intro", edited)
        before, rest = SOURCE.split("# question lead", 1)
        _old_question, after = rest.split("---\n\n---", 1)
        self.assertEqual(updated, before + edited + "---\n\n---" + after)

    def test_disable_then_enable_is_byte_exact(self):
        disabled = comment_out_block_in_yaml(SOURCE, "intro")
        self.assertIn("# # question lead", disabled)
        self.assertEqual(enable_commented_block_in_yaml(disabled, "intro"), SOURCE)

    def test_delete_preserves_every_other_source_byte(self):
        updated = delete_block_from_yaml(SOURCE, "intro")
        expected = SOURCE.replace(
            "--- # separator annotation\n"
            "# question lead\n"
            "id: intro\n"
            "question: 'Original' # question comment\n"
            "fields:\n"
            "  - 'Name': user_name # field comment\n",
            "",
        )
        self.assertEqual(updated, expected)

    def test_reorder_preserves_bodies_separators_and_empty_document(self):
        ids = [block["id"] for block in parse_interview_yaml(SOURCE)["blocks"]]
        updated = reorder_blocks_in_yaml(SOURCE, list(reversed(ids)))
        self.assertIn("--- # separator annotation\n", updated)
        self.assertIn("---\n\n---\n", updated)
        for annotation in (
            "# file header",
            "# metadata comment",
            "# question lead",
            "# question comment",
            "# field comment",
            "# code lead",
            "# Python comment",
        ):
            self.assertEqual(updated.count(annotation), 1)

    def test_reorder_rejects_an_incomplete_list(self):
        with self.assertRaisesRegex(ValueError, "every interview block"):
            reorder_blocks_in_yaml(SOURCE, ["intro"])

    def test_insert_after_block_preserves_every_existing_byte(self):
        inserted = "id: added\nquestion: Added\n"
        updated = insert_block_in_yaml(SOURCE, inserted, "intro")
        insertion_point = SOURCE.index("---\n\n---", SOURCE.index("id: intro"))
        self.assertEqual(
            updated,
            SOURCE[:insertion_point] + "---\n" + inserted + SOURCE[insertion_point:],
        )

    def test_insert_rejects_a_duplicate_id_without_changing_source(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            insert_block_in_yaml(
                SOURCE, "id: intro\nquestion: Duplicate\n", "calculation"
            )

    def test_duplicate_ids_are_refused_instead_of_replacing_two_blocks(self):
        duplicated = SOURCE + "---\nid: intro\nquestion: Other\n"
        with self.assertRaisesRegex(ValueError, "duplicated"):
            update_block_in_yaml(duplicated, "intro", "id: intro\nquestion: Edited\n")


class TestEditorBlockTitles(unittest.TestCase):
    """The outline has to name a block well enough to find it again."""

    def test_a_standalone_comment_is_titled_by_its_first_line(self):
        source = (
            "---\n"
            "comment: |\n"
            "  The questions below are copies of the questions in AssemblyLine's\n"
            "  ql_baseline.yml, rewritten to name this interview's own objects.\n"
        )
        block = parse_interview_yaml(source)["blocks"][0]
        self.assertEqual(block["type"], "comment")
        self.assertEqual(
            block["title"],
            "The questions below are copies of the questions in AssemblyLine's",
        )

    def test_a_long_comment_first_line_is_trimmed(self):
        source = "comment: |\n  " + ("word " * 40).strip() + "\n"
        block = parse_interview_yaml(source)["blocks"][0]
        self.assertLessEqual(len(block["title"]), 70)
        self.assertTrue(block["title"].endswith("\u2026"))

    def test_a_comment_alongside_other_keys_is_not_a_comment_block(self):
        source = "comment: Explains the screen\nquestion: |\n  Hello\n"
        block = parse_interview_yaml(source)["blocks"][0]
        self.assertEqual(block["type"], "question")

    def test_a_question_is_titled_by_its_prose_not_its_mako(self):
        source = (
            "question: |\n"
            "  % if user_started_case:\n"
            "  Name of the defendant\n"
            "  % else:\n"
            "  Name of the plaintiff\n"
            "  % endif\n"
        )
        block = parse_interview_yaml(source)["blocks"][0]
        self.assertEqual(block["title"], "Name of the defendant")

    def test_an_unrecognised_block_is_named_after_its_first_key(self):
        source = "features:\n  navigation: True\n"
        block = parse_interview_yaml(source)["blocks"][0]
        self.assertEqual(block["title"], "Features")


class TestNewBlockTemplates(unittest.TestCase):
    """Every block the "Add a block" modal authors has to survive the checker.

    The templates are read out of editor_serializers.js rather than restated
    here, so a template that changes in the browser cannot quietly stop being
    valid docassemble.
    """

    # Every kind the modal offers. "ai-screen" starts life as a question
    # block, so the caller collapses it to "question" before inserting.
    KINDS = (
        "question",
        "ai-screen",
        "review",
        "code",
        "objects",
        "attachment",
        "comment",
        "other",
    )

    # A plausible host interview: metadata, an order block, and two screens.
    HOST = (
        "metadata:\n"
        "  title: Test interview\n"
        "---\n"
        "mandatory: True\n"
        "code: |\n"
        "  intro_screen\n"
        "  final_screen\n"
        "---\n"
        "id: intro\n"
        "question: |\n"
        "  Welcome\n"
        "continue button field: intro_screen\n"
        "---\n"
        "id: final\n"
        "event: final_screen\n"
        "question: |\n"
        "  All done\n"
    )

    @classmethod
    def setUpClass(cls):
        package_dir = Path(__file__).resolve().parent
        script = (
            "const s = require(%s);"
            "const out = {};"
            "%s.forEach(function (k) { out[k] = s.makeNewBlockYaml(k, 1700000000000); });"
            "process.stdout.write(JSON.stringify(out));"
            % (
                json.dumps(str(package_dir / "data/static/editor_serializers.js")),
                json.dumps(list(cls.KINDS)),
            )
        )
        completed = subprocess.run(
            ["node", "-e", script], check=False, capture_output=True, text=True
        )
        if completed.returncode != 0:
            raise unittest.SkipTest(f"node is unavailable: {completed.stderr}")
        cls.templates = json.loads(completed.stdout)

    def checker_errors(self, raw_yaml):
        from dayamlchecker.yaml_structure import find_errors_from_string

        return [
            str(getattr(error, "err_str", "") or error)
            for error in find_errors_from_string(raw_yaml, input_file="test.yml")
        ]

    def test_the_host_interview_starts_clean(self):
        # Otherwise a template could inherit a pass from a file already broken.
        self.assertEqual(self.checker_errors(self.HOST), [])

    def test_every_new_block_passes_the_checker_wherever_it_lands(self):
        for kind in self.KINDS:
            block_yaml = self.templates[kind]
            self.assertTrue(block_yaml.strip(), kind)
            for insert_after_id in (None, "intro", "final"):
                with self.subTest(kind=kind, insert_after_id=insert_after_id):
                    updated = insert_block_in_yaml(
                        self.HOST, block_yaml, insert_after_id
                    )
                    errors = self.checker_errors(updated)
                    self.assertEqual(errors, [], f"{kind}:\n{block_yaml}")

    def test_a_new_block_is_exactly_one_parsable_block(self):
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                blocks = parse_interview_yaml(self.templates[kind])["blocks"]
                self.assertEqual(len(blocks), 1)

    def test_the_comment_block_carries_no_id(self):
        # An id needs a key beside it that gives the block a type; on its own
        # the checker reports "couldn't identify a block type".
        self.assertNotIn("id:", self.templates["comment"])
        with_id = "id: comment_1\n" + self.templates["comment"]
        self.assertNotEqual(self.checker_errors(self.HOST + "---\n" + with_id), [])

    def test_the_ai_screen_starts_from_the_question_template(self):
        self.assertEqual(self.templates["ai-screen"], self.templates["question"])

    def test_the_raw_yaml_block_is_not_secretly_a_code_block(self):
        # A `code:` key would type the block as code, and saving it would then
        # re-serialize whatever the author typed under a `code: |` leader.
        raw = self.templates["other"]
        self.assertNotIn("code:", raw)
        updated = insert_block_in_yaml(self.HOST, raw, "intro")
        block = next(
            item
            for item in parse_interview_yaml(updated)["blocks"]
            if item["yaml"].strip() == raw.strip()
        )
        self.assertNotIn(block["type"], ("code", "question", "objects", "review"))

    def test_the_raw_yaml_block_starts_unindented_on_a_single_line(self):
        raw = self.templates["other"].rstrip("\n")
        self.assertNotIn("\n", raw)
        self.assertEqual(raw, raw.lstrip())

    def test_the_raw_yaml_block_is_only_a_yaml_comment(self):
        # Nothing is set: docassemble reads no keys out of the block, so the
        # author starts at column one with no structure to delete first.
        raw = self.templates["other"]
        self.assertTrue(is_comment_only_yaml(raw), raw)
        self.assertIsNone(yaml.safe_load(raw))

    def test_a_blank_raw_block_can_still_be_selected_after_insertion(self):
        # It has no id of its own, so the outline needs it found by position.
        raw = self.templates["other"]
        for insert_after_id in (None, "intro", "final"):
            with self.subTest(insert_after_id=insert_after_id):
                updated = insert_block_in_yaml(self.HOST, raw, insert_after_id)
                blocks = parse_interview_yaml(updated)["blocks"]
                found = inserted_block_id_by_position(blocks, insert_after_id)
                selected = next(b for b in blocks if b["id"] == found)
                self.assertEqual(selected["yaml"].strip(), raw.strip())

    def test_an_unknown_anchor_selects_nothing_rather_than_a_stray_block(self):
        blocks = parse_interview_yaml(self.HOST)["blocks"]
        self.assertIsNone(inserted_block_id_by_position(blocks, "missing"))
        self.assertIsNone(inserted_block_id_by_position([], None))

    def test_a_blank_raw_block_is_editable_not_a_disabled_block(self):
        # A disabled block renders read-only, with nothing but "re-enable".
        updated = insert_block_in_yaml(self.HOST, self.templates["other"], "intro")
        blocks = parse_interview_yaml(updated)["blocks"]
        block = next(b for b in blocks if b["title"] != "" and "#" in b["yaml"])
        self.assertNotEqual(block["type"], "commented")

    def test_a_commented_out_block_is_still_recognised_as_one(self):
        # The note case must not swallow real blocks that were commented out.
        disabled = "# id: parked\n# question: |\n#   Parked for now\n"
        updated = insert_block_in_yaml(self.HOST, disabled, "intro")
        blocks = parse_interview_yaml(updated)["blocks"]
        block = next(b for b in blocks if b["yaml"].strip() == disabled.strip())
        self.assertEqual(block["type"], "commented")
        self.assertEqual(block["data"]["_commented_type"], "question")

    def test_what_an_author_types_into_a_raw_block_still_checks_out(self):
        # The raw block exists for the kinds the modal has no card for.
        for typed in (
            "features:\n  navigation: True\n",
            "modules:\n  - .my_module\n",
            "terms:\n  lease: A rental contract.\n",
        ):
            with self.subTest(typed=typed):
                updated = insert_block_in_yaml(self.HOST, typed, "intro")
                self.assertEqual(self.checker_errors(updated), [])


if __name__ == "__main__":
    unittest.main()

# do not pre-load
"""Graphical saves of standalone screens retain Docassemble directives."""

import json
from pathlib import Path
import subprocess
import unittest

import yaml

from .editor_utils import parse_interview_yaml, update_block_in_yaml


class TestScreenTypes(unittest.TestCase):
    @staticmethod
    def serialize(blocks):
        result = subprocess.run(
            ["node", str(Path(__file__).with_suffix(".js")), "--serialize"],
            input=json.dumps(blocks),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_signature_edit_preserves_generic_pattern_and_annotations(self):
        # AssemblyLine's ql_baseline.yml pattern, including accessible alt text.
        source = """# Shared by every ALIndividual
id: persons signature
generic object: ALIndividual
question: |
  ${x}, please sign below
signature: x.signature # stored image
under: |
  ${x}
required: False # permit blank
pen color: "#33f"
validation code: |
  x.signature.alt_text = f"Signature of {x.name_full()}"
"""
        data = yaml.safe_load(source)
        data["under"] = "Signed by ${x}\n"
        edited = self.serialize([data])[0]
        result = update_block_in_yaml(
            source, "persons signature", edited, preserve_unchanged_annotations=True
        )
        self.assertEqual(yaml.safe_load(result), data)
        self.assertEqual(result.split("under:", 1)[0], source.split("under:", 1)[0])
        self.assertEqual(
            result.split("required:", 1)[1], source.split("required:", 1)[1]
        )
        self.assertEqual(
            parse_interview_yaml(result)["blocks"][0]["variable"], "x.signature"
        )

    def test_signature_options_can_be_added_and_removed_without_rewriting_siblings(
        self,
    ):
        source = (
            "# Signature settings\n"
            "id: signature\n"
            "question: 'Sign below' # wording\n"
            "signature: x.signature # image\n"
            "under: |\n"
            "  ${x}\n"
            "# Keep validation\n"
            "validation code: |\n"
            '  x.signature.alt_text = "Signature"\n'
        )
        data = yaml.safe_load(source)
        del data["under"]
        data["required"] = False
        result = update_block_in_yaml(
            source,
            "signature",
            self.serialize([data])[0],
            preserve_unchanged_annotations=True,
        )
        self.assertEqual(yaml.safe_load(result), data)
        self.assertEqual(
            result,
            source.replace("under: |\n  ${x}\n", "") + '"required": false\n',
        )

    def test_migrating_legacy_field_preserves_other_source(self):
        source = (
            "id: legacy\n"
            "question: 'Your name' # title\n"
            "field: welcome # deprecated\n"
            "fields:\n"
            "  - Name: name # answer\n"
            "# Author note\n"
        )
        data = yaml.safe_load(source)
        result = update_block_in_yaml(
            source,
            "legacy",
            self.serialize([data])[0],
            preserve_unchanged_annotations=True,
        )
        self.assertNotIn("\nfield: welcome", result)
        self.assertIn("continue button field: welcome", result)
        for line in (
            "question: 'Your name' # title",
            "  - Name: name # answer",
            "# Author note",
        ):
            self.assertIn(line, result)

    def test_editing_one_button_preserves_other_buttons_and_comments(self):
        source = (
            "id: buttons\nquestion: Choose\nbuttons:\n"
            "  - Restart: restart # first action\n"
            "  # Keep this explanation\n"
            "  - Exit: exit\n"
            '    url: "https://example.com" # destination\n'
        )
        data = yaml.safe_load(source)
        data["buttons"][0]["Restart"] = "leave"
        result = update_block_in_yaml(
            source,
            "buttons",
            self.serialize([data])[0],
            preserve_unchanged_annotations=True,
        )
        self.assertEqual(yaml.safe_load(result), data)
        self.assertEqual(result, source.replace("Restart: restart", 'Restart: "leave"'))

    def test_edited_multiline_text_stays_readable_and_lossless(self):
        cases = []
        for key in (
            "question",
            "subquestion",
            "help",
            "script",
            "css",
            "validation code",
            "under",
        ):
            for text in (
                "Paragraph one\n\nParagraph two ${ x }",
                "  indented first line\n    nested line\n",
                "Line with a Markdown break  \n\n",
            ):
                data = {
                    "id": "multiline",
                    "question": "Sign below",
                    "signature": "x.signature",
                    key: text,
                }
                cases.append((key, text, data))
        for (key, text, data), edited in zip(
            cases, self.serialize([case[2] for case in cases])
        ):
            with self.subTest(key=key, text=text):
                original = {**data, key: "Original"}
                source = "# Author's note\n" + yaml.safe_dump(original, sort_keys=False)
                result = update_block_in_yaml(
                    source,
                    "multiline",
                    edited,
                    preserve_unchanged_annotations=True,
                )
                self.assertEqual(yaml.safe_load(result), data)
                node = next(
                    value
                    for name, value in yaml.compose(result).value
                    if name.value == key
                )
                self.assertEqual(node.style, "|")
                self.assertTrue(result.startswith("# Author's note\n"))

    def test_corpus_patterns_round_trip(self):
        # Patterns from CLAGuardianship, MAInformalAppelleeBrief,
        # HelpForChildSupportObligors, ALAffidavitOfIndigency and MACourtLocator.
        blocks = [
            {
                "signature": "users[0].signature",
                "question": "% if form_filled_by_attorney:\n  Sign as attorney\n% else:\n  Sign below\n% endif\n",
                "under": "% if form_filled_by_attorney:\n  ${ attorneys[0] }\n% else:\n  ${ users[0] }\n% endif\n",
                "progress": 99,
            },
            {"signature": "signature_fields", "required": False},
            {
                "signature": "x.signature",
                "required": "must_sign",
                "pen color": "${ ink_color }",
            },
            {"yesno": "children[i].previous_addresses.there_is_another"},
            {"noyes": "minor_under_12_yes"},
            {
                "yesnomaybe": "cse_copy",
                "help": {"label": "More", "content": "Explanation"},
            },
            {"noyesmaybe": "not_sure"},
            {"field": "method_of_service", "dropdown": [{"Email": "email"}, "Mail"]},
            {
                "field": "case.status",
                "choices": [{"I have a notice": "onlyntq"}],
                "default": "onlyntq",
            },
            {"field": "answer", "combobox": ["First", "Second"]},
            {"field": "x.there_is_another", "buttons": [{"Yes": True}, {"No": False}]},
            {
                "event": "exit_cant_pay",
                "buttons": [
                    {"Restart": "restart"},
                    {"Exit": "exit", "url": "https://courtformsonline.org"},
                ],
            },
            {
                "buttons": [
                    {"Keep going": {"code": "proceed_anyway = True\n"}},
                    {"code": "button_choices()"},
                ]
            },
            {
                "field": "answer",
                "datatype": "boolean",
                "buttons": {"code": "get_buttons()"},
            },
            {
                "field": "answer",
                "buttons": [
                    {
                        "label": "Agree",
                        "value": True,
                        "color": "success",
                        "show if": "eligible",
                    }
                ],
            },
            {
                "field": "review_expenses_screen",
                "subquestion": "${ users[0].expenses.table }\n",
            },
            {"field": "welcome", "fields": [{"Name": "name"}]},
            {
                "field": "legacy",
                "fields": [{"Name": "name"}],
                "continue button field": "explicit",
            },
        ]
        for index, block in enumerate(blocks):
            block.setdefault("id", f"screen_{index}")
            block.setdefault("question", "Question\n")
        for block, edited in zip(blocks, self.serialize(blocks)):
            with self.subTest(block=block["id"]):
                source = yaml.safe_dump(block, sort_keys=False)
                expected = dict(block)
                if "field" in expected and "fields" in expected:
                    legacy = expected.pop("field")
                    expected.setdefault("continue button field", legacy)
                result = update_block_in_yaml(
                    source, block["id"], edited, preserve_unchanged_annotations=True
                )
                self.assertEqual(yaml.safe_load(result), expected)
                if "field" not in block or "fields" not in block:
                    self.assertEqual(result, source)

    def test_standalone_variables_are_available_to_order_lookup(self):
        for key in ("signature", "yesno", "noyes", "yesnomaybe", "noyesmaybe", "field"):
            with self.subTest(key=key):
                model = parse_interview_yaml(
                    f"question: Example\n{key}: users[i].answer\n"
                )
                self.assertEqual(model["blocks"][0]["variable"], "users[i].answer")

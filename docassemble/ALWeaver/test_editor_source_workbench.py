# do not pre-load
"""Source previews must preserve exact text and never execute author code."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from . import editor_source_workbench
from .editor_source_workbench import (
    playground_recipes,
    preview_source_action,
    python_offset,
    source_changes,
    utf16_offset,
)
from .source_document import parse_source_document

RECIPES = [
    {"source": "id: sample\nquestion: Sample\n"},
    {
        "source": "template: disclaimer\ncontent: |\n  Hello\n---\nquestion: Welcome\nsubquestion: ${ disclaimer }\n"
    },
]


class TestSourceWorkbench(unittest.TestCase):
    def test_playground_catalog_supports_old_and_new_docassemble(self):
        examples = [{"title": "Configured package example", "source": "code: pass"}]
        helper = SimpleNamespace(get_examples=lambda: examples)
        with patch("importlib.import_module", return_value=helper) as load:
            self.assertEqual(editor_source_workbench._playground_examples(), examples)
            load.assert_called_once_with("docassemble.webapp.develop.helpers")
        with patch(
            "importlib.import_module",
            side_effect=[
                ModuleNotFoundError(name="docassemble.webapp.develop"),
                helper,
            ],
        ) as load:
            self.assertEqual(editor_source_workbench._playground_examples(), examples)
            self.assertEqual(load.call_args.args[0], "docassemble.webapp.server")
        with patch(
            "importlib.import_module",
            side_effect=ModuleNotFoundError(name="missing_dependency"),
        ) as load:
            with self.assertRaises(ModuleNotFoundError):
                editor_source_workbench._playground_examples()
            self.assertEqual(load.call_count, 1)

    def test_playground_tree_preserves_categories_and_plain_context(self):
        examples = [
            {
                "title": "Templates",
                "list": [
                    {
                        "title": "Nested",
                        "list": [
                            {
                                "id": "sample",
                                "title": "Template",
                                "source": "template: welcome",
                                "documentation": "https://docassemble.org/docs/",
                                "before_html": "<div><pre><span>code:</span> &lt;x&gt;\n</pre></div>",
                                "after_html": "",
                                "interview": "/?i=example",
                            }
                        ],
                    }
                ],
            }
        ]
        with patch.object(
            editor_source_workbench,
            "_playground_examples",
            return_value=examples,
        ):
            tree = playground_recipes()
        leaf = tree[0]["children"][0]["children"][0]
        self.assertEqual(leaf["source"], "template: welcome")
        self.assertEqual(leaf["before"], "code: <x>\n")
        self.assertEqual(leaf["id"], "0/0/0")
        self.assertNotIn("html", leaf)

    def test_insert_at_start_preserves_header_and_unicode_cursor(self):
        source = "# 😀 author header\nid: old\nquestion: Original\n"
        result = preview_source_action(
            "main.yml",
            source,
            source,
            "insert-block",
            block_yaml="code: pass",
            at_start=True,
            cursor=0,
        )
        self.assertEqual(
            result["source"],
            "# 😀 author header\ncode: pass\n---\nid: old\nquestion: Original\n",
        )
        result = preview_source_action(
            "main.yml",
            source,
            source,
            "insert-block",
            block_yaml="code: pass",
            cursor=utf16_offset(source),
        )
        self.assertEqual(result["source"], source + "\n---\ncode: pass\n")
        for block_yaml in (None, [], "", "question: ["):
            with self.assertRaises(ValueError):
                preview_source_action(
                    "main.yml", source, source, "insert-block", block_yaml=block_yaml
                )

    def test_top_insertion_preserves_jinja_directive_and_leading_separator(self):
        source = "# use jinja\n---\nid: old\nquestion: Original\n"
        result = preview_source_action(
            "main.yml",
            source,
            source,
            "insert-block",
            block_yaml="code: pass",
            at_start=True,
            cursor=source.index("---") + 1,
        )
        self.assertEqual(
            result["source"],
            "# use jinja\n---\ncode: pass\n---\nid: old\nquestion: Original\n",
        )
        self.assertEqual(
            len(
                [
                    b
                    for b in parse_source_document(
                        "main.yml", result["source"]
                    ).documents
                    if b.parsed_value
                ]
            ),
            2,
        )

    def test_hunks_restore_unicode_and_final_newline(self):
        saved = '# 😀\nquestion: "Before"\n---\ncode: pass'
        working = '# 😀\nquestion: "After"\n---\ncode: pass\n# extra\n'
        hunks = source_changes(saved, working)
        result = working
        for hunk in reversed(hunks):
            start = python_offset(result, hunk["from"])
            end = python_offset(result, hunk["to"])
            self.assertEqual(result[start:end], hunk["before"])
            result = result[:start] + hunk["insert"] + result[end:]
        self.assertEqual(result, saved)
        self.assertEqual(source_changes("", "new\n")[0]["insert"], "")
        self.assertEqual(source_changes("old\n", "")[0]["before"], "")

    def test_recipe_inserts_at_document_boundary_preserving_comments(self):
        source = '# header\nid: authored\nquestion: "Original"\n---\n# untouched\ncode: pass\n'
        for recipe in RECIPES:
            result = preview_source_action(
                "main.yml",
                source,
                source,
                "insert-block",
                block_yaml=recipe["source"],
                cursor=15,
            )
            self.assertTrue(
                parse_source_document("main.yml", result["source"]).structurally_valid
            )
            self.assertTrue(
                result["source"].startswith(
                    '# header\nid: authored\nquestion: "Original"\n'
                )
            )
            self.assertTrue(result["source"].endswith("---\n# untouched\ncode: pass\n"))
            edit = result["edit"]
            pos = python_offset(source, edit["from"])
            self.assertEqual(
                source[:pos] + edit["insert"] + source[pos:], result["source"]
            )
            empty = preview_source_action(
                "main.yml",
                "",
                "",
                "insert-block",
                block_yaml=recipe["source"],
                cursor=0,
            )
            self.assertTrue(
                parse_source_document("main.yml", empty["source"]).structurally_valid
            )

    def test_recipe_rejects_duplicate_example_ids(self):
        recipe = RECIPES[0]
        with self.assertRaisesRegex(ValueError, "Rename the existing"):
            preview_source_action(
                "main.yml",
                "",
                recipe["source"],
                "insert-block",
                block_yaml=recipe["source"],
                cursor=0,
            )

    def test_invalid_source_and_cursor_cannot_insert(self):
        with self.assertRaises(ValueError):
            preview_source_action(
                "main.yml", "", "question: [", "insert-block", block_yaml="code: pass"
            )
        for cursor in (-1, 9999, True):
            with self.assertRaises(ValueError):
                preview_source_action(
                    "main.yml",
                    "",
                    "code: pass",
                    "insert-block",
                    block_yaml="code: pass",
                    cursor=cursor,
                )
        with self.assertRaises(ValueError):
            python_offset("😀", 1)
        self.assertEqual(python_offset("😀", utf16_offset("😀")), 1)

    def test_repairs_keep_author_source(self):
        source = '# keep\nquestion: "A question"\nfields:\n  - Answer: answer\n'
        result = preview_source_action("main.yml", source, source, "repair")
        self.assertGreater(result["repair_count"], 0)
        self.assertIn("# keep", result["source"])
        self.assertIn('question: "A question"', result["source"])
        self.assertIn("id:", result["source"])
        self.assertEqual(
            source, '# keep\nquestion: "A question"\nfields:\n  - Answer: answer\n'
        )

    def test_outline_reads_unsaved_blocks_without_evaluation(self):
        source = 'id: new\nquestion: Changed\nfields:\n  - Answer: answer\n---\ncode: |\n  raise RuntimeError("never execute")\n'
        result = preview_source_action("main.yml", "", source, "outline")
        self.assertEqual(result["blocks"][0]["id"], "new")
        self.assertEqual(result["blocks"][0]["line_start"], 1)
        self.assertEqual(len(result["blocks"]), 2)

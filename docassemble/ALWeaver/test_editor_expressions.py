# do not pre-load
import ast
import json
from pathlib import Path
import subprocess
import unittest

from .editor_expressions import parse_expression


class TestExpressions(unittest.TestCase):
    def test_supported_subset(self):
        for source in (
            "household_income <= poverty_limit and applicant.age >= 18",
            "(a or b) and not c",
            "a + b * (c - 2) / -3",
            '"hello"',
            "True",
            "False",
            "None",
            "1.5",
            "person[0].age",
            "person[i].name.first",
            'a not in ["one", "two"]',
            "0 < age <= 18",
            "round(amount, 2)",
            'as_datetime("2026-09-18")',
            "today()",
            "custom(value)",
            "round(value, ndigits=2)",
            "library.calculate(user.age, threshold=18)",
        ):
            with self.subTest(source=source):
                self.assertTrue(parse_expression(source)["supported"])

    def test_unsupported_is_valid_and_untouched(self):
        for source in (
            "any(p.age < 18 for p in household)",
            "a if b else c",
            "lambda x: x",
            'f"{value}"',
            "custom(*values)",
            "custom(**options)",
            '{"a": 1}',
            "a ** 2",
            "(a # keep this\n + b)",
        ):
            with self.subTest(source=source):
                parsed = parse_expression(source)
                self.assertTrue(parsed["valid"])
                self.assertFalse(parsed["supported"])
                self.assertNotIn("tree", parsed)

    def test_invalid_and_limits(self):
        for source in (
            "a +",
            "",
            " a + 1",
            "a" * 20001,
            42,
            "f(value=1, value=2)",
            "f(value=1, 2)",
        ):
            self.assertFalse(parse_expression(source)["valid"])
        self.assertFalse(parse_expression("x", "bad")["valid"])

    def test_code_requires_complete_support(self):
        for source in (
            "if x:\n  a = 2",
            "a = b = 2",
            "x += 1",
            "a = 2\nf()",
            "a = [x for x in values]",
        ):
            self.assertFalse(parse_expression(source, "code")["supported"])

    def test_empty_code_can_start_in_guided_mode(self):
        for source in ("", "\n", "# Add calculations here\n"):
            parsed = parse_expression(source, "code")
            self.assertTrue(parsed["supported"])
            self.assertEqual(parsed["rows"], [])

    def test_assignment_target_ranges(self):
        source = '# 😀 heading\ncafé = "é"; people[i].name.first = "Hello"\n'
        rows = parse_expression(source, "code")["rows"]
        for row in rows:
            self.assertEqual(
                source[row["target_start"] : row["target_end"]], row["target"]
            )
        self.assertEqual(
            [row["target"] for row in rows], ["café", "people[i].name.first"]
        )

    def test_code_comments_are_supported_and_exposed_without_changing_ranges(self):
        source = "# heading\ncafé = (\n  1 # first\n  + 2\n) # trailing\n# footer\n"
        parsed = parse_expression(source, "code")
        self.assertTrue(parsed["supported"])
        self.assertEqual(
            [c["text"] for c in parsed["comments"]],
            ["# heading", "# first", "# trailing", "# footer"],
        )
        for comment in parsed["comments"]:
            self.assertTrue(source[comment["start"] :].startswith(comment["text"]))
        row = parsed["rows"][0]
        self.assertEqual(source[row["start"] : row["end"]], "1 # first\n  + 2")

    def test_javascript_comment_preserving_code_changes(self):
        for source in (
            "# lead\ncafé = (\n  1 # café 😀\n  + 2\n) # tail\n",
            "result = [1, # first\n 2] # tail\n",
            "result = (1 # first\r\n + 2) # tail\r\n",
        ):
            parsed = parse_expression(source, "code")
            completed = subprocess.run(
                [
                    "node",
                    "-e",
                    """
const e = require("./data/static/editor_expressions.js");
let s="";
process.stdin.on("data", c => s+=c);
process.stdin.on("end", () => {
  const {source, parsed} = JSON.parse(s);
  const row = parsed.rows[0];
  row.originalTree = JSON.parse(JSON.stringify(row.tree));
  function apply() {
    const chars = Array.from(source);
    e.codeChanges(row, parsed.comments).sort((a,b) => b.start-a.start)
      .forEach(x => chars.splice(x.start,x.end-x.start,...Array.from(x.text)));
    return chars.join("");
  }
  row.tree.args[1].value = "3";
  const leaf = apply();
  row.tree = e.fresh("variable"); row.tree.value = "replacement";
  process.stdout.write(JSON.stringify({leaf, structural: apply()}));
});""",
                ],
                input=json.dumps({"source": source, "parsed": parsed}),
                text=True,
                capture_output=True,
                check=True,
                cwd=Path(__file__).parent,
            )
            changed = json.loads(completed.stdout)
            self.assertEqual(changed["leaf"], source.replace("2", "3"))
            for key, value in changed.items():
                with self.subTest(source=source, edit=key):
                    ast.parse(value)
                    for comment in parsed["comments"]:
                        self.assertEqual(value.count(comment["text"]), 1)
            self.assertEqual(
                ast.dump(ast.parse(changed["structural"]).body[0].value),
                "Name(id='replacement', ctx=Load())",
            )

    def test_repeated_assignment_edits_preserve_source(self):
        source = "# 😀 heading\r\ncafé  = (1 +  2)  # keep\r\nother = 'text'\r\n"
        parsed = parse_expression(source, "code")
        completed = subprocess.run(
            [
                "node",
                "-e",
                """
const e = require('./data/static/editor_expressions.js');
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  const {source, parsed} = JSON.parse(input);
  parsed.original = source;
  parsed.rows.forEach(row => {
    row.originalTarget = row.target;
    row.originalTree = JSON.parse(JSON.stringify(row.tree));
  });
  const row = parsed.rows[0];
  row.edited = true;
  row.target = 'people[i].name.first';
  const renamed = e.codeSource(parsed);
  row.tree.args[1].value = '30';
  const revised = e.codeSource(parsed);
  row.target = 'café';
  row.tree.args[1].value = '2';
  const reverted = e.codeSource(parsed);
  parsed.rows.push({target: 'total', tree: e.fresh('number'), added: true});
  const added = e.codeSource(parsed);
  parsed.rows[2].target = 'result';
  parsed.rows[2].tree.value = '42';
  const editedNew = e.codeSource(parsed);
  process.stdout.write(JSON.stringify({renamed, revised, reverted, added, editedNew}));
});""",
            ],
            input=json.dumps({"source": source, "parsed": parsed}),
            text=True,
            capture_output=True,
            check=True,
            cwd=Path(__file__).parent,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["renamed"], source.replace("café", "people[i].name.first")
        )
        self.assertEqual(result["revised"], result["renamed"].replace("2)", "30)"))
        self.assertEqual(result["reverted"], source)
        self.assertEqual(result["added"], source + "total = 0\r\n")
        self.assertEqual(result["editedNew"], source + "result = 42\r\n")
        for value in result.values():
            ast.parse(value)

    def test_delete_assignments_preserves_other_source_and_comments(self):
        cases = [
            (
                "# heading\ncafé = (1 + 2) # tail\nother = 3\n",
                [0],
                "# heading\n # tail\nother = 3\n",
            ),
            ("a = 1; b = 2; c = 3\n", [1], "a = 1; c = 3\n"),
            ("a = 1; b = 2\n", [0, 1], "\n"),
            ("a = (\n  1 # inside\n + 2\n)\n", [0], "# inside\n\n"),
            ("(a) = ((1))\n", [0], "\n"),
        ]
        for source, deleted, expected in cases:
            with self.subTest(source=source):
                parsed = parse_expression(source, "code")
                completed = subprocess.run(
                    [
                        "node",
                        "-e",
                        """
const e = require('./data/static/editor_expressions.js');
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  const {source, parsed, deleted} = JSON.parse(input);
  parsed.original = source;
  deleted.forEach(index => { parsed.rows[index].deleted = true; });
  parsed.rows.push({target: 'discard', tree: e.fresh('none'), added: true, deleted: true});
  process.stdout.write(e.codeSource(parsed));
});""",
                    ],
                    input=json.dumps(
                        {"source": source, "parsed": parsed, "deleted": deleted}
                    ),
                    text=True,
                    capture_output=True,
                    check=True,
                    cwd=Path(__file__).parent,
                )
                self.assertEqual(completed.stdout, expected)
                self.assertTrue(parse_expression(completed.stdout, "code")["supported"])

    def test_unicode_offsets_and_source_ranges(self):
        source = 'café = "😀"\nresult = café + "é"\n'
        parsed = parse_expression(source, "code")
        self.assertTrue(parsed["supported"])
        rows = parsed["rows"]
        self.assertEqual(source[rows[0]["start"] : rows[0]["end"]], '"😀"')
        self.assertEqual(source[rows[1]["start"] : rows[1]["end"]], 'café + "é"')
        changed = source[: rows[1]["start"]] + '"new"' + source[rows[1]["end"] :]
        self.assertEqual(changed, 'café = "😀"\nresult = "new"\n')
        ast.parse(changed)

    def test_comparison_chain_retains_single_evaluation(self):
        tree = parse_expression("0 < len(items) <= 10")["tree"]
        self.assertEqual(tree["ops"], ["<", "<="])
        self.assertEqual(len(tree["args"]), 3)

    def test_unicode_line_separator_inside_string_is_not_a_source_line(self):
        source = 'text = "before\u2028after"\nresult = 2\n'
        parsed = parse_expression(source, "code")
        self.assertTrue(parsed["supported"])
        row = parsed["rows"][1]
        self.assertEqual(source[row["start"] : row["end"]], "2")

    def test_javascript_generation_preserves_python_ast(self):
        sources = [
            "a <= b and applicant.age >= 18",
            "(a or b) and not c",
            "a + b * (c - 2) / -3",
            "0 < len(items) <= 10",
            'a not in ["one", "two"]',
            '("hello",)',
            "()",
            "round(annual / 12, 2)",
            "currency(round(annual / 12, ndigits=2), symbol=False)",
            "library.calculate(user.age, threshold=18)",
            'as_datetime("2026-09-18")',
            "person[i].name.first",
            "None",
            "False",
            '"é😀\\n\\""',
        ]
        trees = [parse_expression(source)["tree"] for source in sources]
        completed = subprocess.run(
            [
                "node",
                "-e",
                'const e = require("./data/static/editor_expressions.js"); let s=""; process.stdin.on("data", c => s+=c); process.stdin.on("end", () => process.stdout.write(JSON.stringify(JSON.parse(s).map(e.python))));',
            ],
            input=json.dumps(trees),
            text=True,
            capture_output=True,
            check=True,
            cwd=Path(__file__).parent,
        )
        for before, after in zip(sources, json.loads(completed.stdout)):
            with self.subTest(source=before):
                self.assertEqual(
                    ast.dump(ast.parse(before, mode="eval")),
                    ast.dump(ast.parse(after, mode="eval")),
                )


if __name__ == "__main__":
    unittest.main()

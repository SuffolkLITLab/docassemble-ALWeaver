# do not pre-load
"""Executable regressions for the September 2026 workbook's B01–B03 findings."""

import ast

import pytest

from .editor_utils import parse_order_code, serialize_order_steps


@pytest.mark.parametrize(
    "source",
    [
        "for party in users:\n    party.email\nfinal_screen",
        "while pending:\n  next_item\nelse:\n  done",
        "try:\n  work()\nexcept ValueError:\n  recover()\nfinally:\n  cleanup()",
        "with context():\n  screen",
        "@decorate\ndef function():\n    screen",
        'match status:\n  case "ready":\n    screen',
        "if eligible: # retain comment\n  screen\nelse:\n  fallback",
        '# introduction\nnote = "("\n\nfinal_screen\n# end\n',
        'function(\n  "é", # argument\n  answer,\n)\nfinal_screen',
        'set_parts(subtitle="Intro")',
        "set_parts(subtitle='Intro')",
        'nav.set_section("Client\'s details")',
        'note = "set_progress(50)"',
        'note = "users.gather()"',
        "first; second\nthird",
        "if eligible:\n    screen\n    # final comment\n    next_screen",
        "if eligible:\n\tfirst\n\tsecond",
    ],
)
def test_order_exact_round_trip_and_neighbor_edit(source):
    steps = parse_order_code(source)
    actual = serialize_order_steps(steps)
    assert actual == source
    assert ast.dump(ast.parse(actual)) == ast.dump(ast.parse(source))
    # Saving after changing a different step cannot flatten the original suite.
    actual = serialize_order_steps(
        steps + [{"kind": "screen", "invoke": "added_screen"}]
    )
    assert actual == source + "\nadded_screen"
    ast.parse(actual)


def test_section_literals_are_escaped_and_call_identity_survives():
    value = "Client's \\ details\nnext"
    for call in ["set_parts", "nav.set_section"]:
        code = serialize_order_steps(
            [{"kind": "section", "value": value, "call": call}]
        )
        node = ast.parse(code).body[0].value
        assert (
            node.keywords[0].value.value if call == "set_parts" else node.args[0].value
        ) == value
    step = parse_order_code("set_parts(subtitle='Intro')")[0]
    assert step["kind"] == "section"
    step["value"] = "Client's details"
    assert serialize_order_steps([step]) == 'set_parts(subtitle="Client\'s details")'


def test_incomplete_python_remains_exact_raw_source():
    source = "if unfinished:\n"
    assert serialize_order_steps(parse_order_code(source)) == source


def test_graphical_edit_refuses_yaml_keys_json_cannot_preserve():
    from .editor_utils import update_block_in_yaml

    source = "id: q\nquestion: Title\nbuttons:\n  - Yes: continue\n"
    edited = 'id: q\nquestion: New title\nbuttons:\n  - "true": continue\n'
    with pytest.raises(ValueError, match="non-text YAML mapping keys"):
        update_block_in_yaml(source, "q", edited, preserve_unchanged_annotations=True)
    assert "New title" in update_block_in_yaml(source, "q", edited)


@pytest.mark.parametrize(
    "source",
    [
        'nav.set_section("Intro")',
        'set_parts(subtitle="Intro")',
        'nav.set_section("Client\\"s details")',
        'nav.set_section("")',
    ],
)
def test_quoted_sections_are_guided_and_preserve_source(source):
    steps = parse_order_code(source + "\n")
    assert len(steps) == 1
    assert steps[0]["kind"] == "section"
    assert serialize_order_steps(steps) == source + "\n"
    steps[0]["value"] = "Revised section"
    actual = ast.parse(serialize_order_steps(steps)).body[0].value
    assert (
        actual.args[0] if actual.args else actual.keywords[0].value
    ).value == "Revised section"


def test_four_space_branches_are_guided_and_edits_preserve_indentation():
    source = 'if eligible:\n    nav.set_section("Café")\n    first\nelif other:\n    second\nelse:\n    last\n'
    steps = parse_order_code(source)
    assert len(steps) == 1
    assert steps[0]["kind"] == "condition"
    assert steps[0]["children"][0]["kind"] == "section"
    assert serialize_order_steps(steps) == source
    steps[0]["children"][1]["invoke"] = "revised"
    assert serialize_order_steps(steps) == source.replace("    first", "    revised")
    steps[0]["children"].append({"kind": "screen", "invoke": "inserted"})
    # Structural edits cannot replay a stale source snapshot.
    updated = serialize_order_steps(steps)
    assert "inserted" in updated
    assert ast.dump(ast.parse(updated)) == ast.dump(
        ast.parse(serialize_order_steps(steps, _preserve_source=False))
    )


@pytest.mark.parametrize(
    "source", ["\nfirst\n\nsecond\n", "first\n", "first\n\n\nsecond\n\n"]
)
def test_whitespace_is_preserved_without_empty_step_cards(source):
    steps = parse_order_code(source)
    assert all(step["kind"] == "screen" for step in steps)
    assert len(steps) == len(source.split())
    assert serialize_order_steps(steps) == source


@pytest.mark.parametrize("source", ["", "\n\n", "  \n\t\n"])
def test_whitespace_only_order_has_no_steps(source):
    assert parse_order_code(source) == []


def test_source_patches_use_utf8_offsets():
    source = 'if café == "é":\n    other\n'
    steps = parse_order_code(source)
    steps[0]["condition"] = 'café == "changed"'
    assert serialize_order_steps(steps) == source.replace('"é"', '"changed"')


def test_review_false_is_false_in_docassemble_parser():
    import subprocess
    from pathlib import Path
    import yaml
    from docassemble.base.parse import Interview, Question
    from docassemble.base.interview_source import InterviewSourceString

    source = subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("test_editor_matrix_controls.js")),
            "--review-yaml",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    interview = Interview()
    interview.source = InterviewSourceString(
        path="docassemble.ALWeaver:matrix.yml", content=source
    )
    interview.source.package = "docassemble.ALWeaver"
    question = Question(yaml.safe_load(source), interview, source=interview.source)
    assert question.skip_undefined is False


def test_field_boolean_settings_are_native_types_in_docassemble_parser():
    import subprocess
    from pathlib import Path
    import yaml
    from docassemble.base.parse import Interview, Question
    from docassemble.base.interview_source import InterviewSourceString

    source = subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("test_editor_matrix_controls.js")),
            "--field-yaml",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    interview = Interview()
    interview.source = InterviewSourceString(
        path="docassemble.ALWeaver:matrix.yml", content=source
    )
    interview.source.package = "docassemble.ALWeaver"
    question = Question(yaml.safe_load(source), interview, source=interview.source)
    assert question.fields[0].disableothers is True
    assert question.fields[1].shuffle is False


@pytest.mark.parametrize("newline,ending", [("\r\n", "\r\n"), ("\n", "\n"), ("\n", "")])
def test_playground_read_preserves_actual_source_bytes(
    tmp_path, monkeypatch, newline, ending
):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from . import editor_utils

    source = (
        newline.join(["# café 日本語", "---", "id: sample", 'question: "Original"'])
        + ending
    )
    path = tmp_path / "source.yml"
    path.write_bytes(source.encode("utf-8"))
    playground = SimpleNamespace(file_list=["source.yml"], get_file=lambda name: path)
    monkeypatch.setattr(
        editor_utils, "_playground_user_context", lambda uid: nullcontext()
    )
    monkeypatch.setattr(editor_utils, "create_playground", lambda **kwargs: playground)
    actual = editor_utils.playground_read_yaml(17, "default", "source.yml")
    assert actual.encode("utf-8") == path.read_bytes()
    edited = editor_utils.update_block_in_yaml(
        actual,
        "sample",
        'id: sample\nquestion: "Edited"\n',
        preserve_unchanged_annotations=True,
    )
    assert edited == source.replace('"Original"', '"Edited"')

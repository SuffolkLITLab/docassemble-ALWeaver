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
        "\n\n",
        "",
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

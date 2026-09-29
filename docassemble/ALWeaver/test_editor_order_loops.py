# do not pre-load
"""Behavioral coverage for structured order suites and source-preserving edits."""

import ast

import pytest

from .editor_utils import parse_order_code, serialize_order_steps, validate_order_steps


def walk(steps):
    for step in steps:
        yield step
        yield from walk(step.get("children", []))
        yield from walk(step.get("else_children", []))


SOURCE = """# Gather contact details
for person in users.complete_elements():  # existing people
    # Ask each person
    if person.skip:  # optional
        continue  # next person
    elif person.finished:
        break
    else:  # contact
        person.email  # preferred address
    for child in person.children:
        child.complete = True  # completion
    # End of person
final_screen
"""


def test_nested_loops_comments_and_controls_are_guided_and_lossless():
    steps = parse_order_code(SOURCE)
    assert serialize_order_steps(steps) == SOURCE
    kinds = [s["kind"] for s in walk(steps)]
    assert kinds.count("loop") == 2
    assert "raw" not in kinds
    assert {"assignment", "comment", "break", "continue", "condition"} <= set(kinds)
    assert len({s["id"] for s in walk(steps)}) == len(kinds)
    validate_order_steps(steps)


def test_editing_loop_header_and_assignment_preserves_all_other_text():
    steps = parse_order_code(SOURCE)
    loop = steps[1]
    loop["iterable"] = "other_parties.complete_elements()"
    assignment = next(s for s in walk(steps) if s["kind"] == "assignment")
    assignment["expression"] = "False"
    assert serialize_order_steps(steps) == SOURCE.replace(
        "users.complete_elements()", "other_parties.complete_elements()"
    ).replace("child.complete = True", "child.complete = False")


def test_structural_edits_keep_comments_but_do_not_resurrect_deleted_comments():
    steps = parse_order_code(SOURCE)
    loop = steps[1]
    loop["children"].insert(1, {"kind": "screen", "invoke": "person.phone_number"})
    actual = serialize_order_steps(steps)
    assert "person.phone_number" in actual
    for line in SOURCE.splitlines():
        if "#" in line:
            assert line[line.index("#") :] in actual
    loop["children"] = [s for s in loop["children"] if s["kind"] != "comment"]
    actual = serialize_order_steps(steps)
    assert "# Ask each person" not in actual
    assert "# End of person" not in actual
    assert "# preferred address" in actual
    validate_order_steps(steps)


@pytest.mark.parametrize(
    "source",
    [
        "for index, person in enumerate(users):\n  person.email",
        'for change in set(changes.true_values()).intersection({\n    "married",\n    "divorced",\n}):\n    details[change].date',
        "if ready:\n  # before\n  for child in children:\n    child.name\n  # after",
        "for item in things:\n  if item.skip:\n    continue\n  item.name\n  break",
        "total = (\n  rent + utilities\n) # expenses",
        'café.value = "é" # unicode',
    ],
)
def test_supported_forms_round_trip(source):
    steps = parse_order_code(source)
    assert serialize_order_steps(steps) == source
    assert all(s["kind"] != "raw" for s in walk(steps))
    validate_order_steps(steps)


def test_for_else_remains_one_raw_step():
    source = "for item in things:\n  if item.done:\n    break\nelse:\n  no_match"
    steps = parse_order_code(source)
    assert steps[0]["kind"] == "raw"
    assert serialize_order_steps(steps) == source


def test_comments_only_loop_or_condition_gets_pass():
    for kind in ["loop", "condition"]:
        steps = [
            {
                "kind": kind,
                "target": "item",
                "iterable": "items",
                "condition": "ready",
                "children": [{"kind": "comment", "code": "# pending"}],
            }
        ]
        code = serialize_order_steps(steps)
        assert "# pending\n  pass" in code
        validate_order_steps(steps)


@pytest.mark.parametrize(
    "steps",
    [
        [{"kind": "break"}],
        [
            {
                "kind": "condition",
                "condition": "ready",
                "children": [{"kind": "continue"}],
            }
        ],
        [{"kind": "assignment", "target": "a = b", "expression": "True"}],
        [{"kind": "assignment", "target": "a", "expression": "True\nb = False"}],
        [{"kind": "loop", "target": "item", "iterable": "", "children": []}],
        [{"kind": "loop", "target": "1", "iterable": "items", "children": []}],
        [{"kind": "comment", "code": "run_me()"}],
    ],
)
def test_invalid_guided_steps_rejected_before_writing(steps):
    with pytest.raises(ValueError):
        validate_order_steps(steps)


def test_loop_execution_preserves_break_continue_and_assignment_behavior():
    steps = parse_order_code(
        "total = 0\nfor item in items:\n  if item < 0:\n    continue\n  if item > 10:\n    break\n  total = total + item"
    )
    assignment = next(s for s in walk(steps) if s.get("expression") == "total + item")
    assignment["expression"] = "total + item * 2"
    env = {"items": [-1, 2, 3, 20, 4]}
    exec(serialize_order_steps(steps), env)
    assert env["total"] == 10


def test_structural_edits_do_not_indent_blank_lines_in_nested_bodies():
    steps = parse_order_code(
        "intro\n\nnext_screen\nfor x in items:\n  x.name\n\n  # note\n\n  x.age\n"
        "interview_order = True\n"
    )
    moved = steps.pop(1)
    loop = next(s for s in steps if s["kind"] == "loop")
    loop["children"].append(moved)
    actual = serialize_order_steps(steps)
    assert all(line.strip() or not line for line in actual.split("\n"))
    ast.parse(actual)

from .interview_scan import scan_interview


def test_include_graph_definitions_and_reachability():
    files = {
        "main.yml": """include: child.yml
---
mandatory: true
code: |
  if eligible:
    finish
---
event: finish
question: Done
""",
        "child.yml": """include: main.yml
---
question: Eligible?
yesno: eligible
---
question: Your name
fields:
  - First: first
  - Last: last
---
code: |
  unused = 1
""",
    }
    result = scan_interview(files.__getitem__, "main.yml")
    assert len(result["files"]) == 2
    variables = {v["name"]: v for v in result["variables"]}
    assert variables["last"]["possibly_unused"]
    assert variables["eligible"]["references"]
    assert not next(b for b in result["blocks"] if b["data"].get("event"))[
        "possibly_unreachable"
    ]
    assert next(b for b in result["blocks"] if b["data"].get("fields"))[
        "possibly_unreachable"
    ]


def test_missing_include_and_indexed_dependencies():
    files = {"main.yml": """include: missing.yml
---
mandatory: true
code: |
  users[0].name.first
---
question: Name
fields:
  - First: users[i].name.first
"""}

    def read(name):
        if name not in files:
            raise FileNotFoundError(name)
        return files[name]

    result = scan_interview(read, "main.yml")
    assert result["warnings"]
    assert not result["blocks"][-1]["possibly_unreachable"]


def test_mako_control_lines_and_nested_expressions_are_references():
    source = """mandatory: true
question: Done
subquestion: |
  % if eligible:
  Hello ${ {'name': users[0].name.first}['name'] }
  % endif
---
question: Eligible?
yesno: eligible
---
question: Name
fields:
  - First: users[i].name.first
"""
    result = scan_interview(lambda name: source, "main.yml")
    assert all(not b["possibly_unreachable"] for b in result["blocks"])
    assert all(not v["possibly_unused"] for v in result["variables"])

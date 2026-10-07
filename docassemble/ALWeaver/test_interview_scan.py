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


def test_generic_gather_review_and_event_reachability():
    files = {"main.yml": """objects:
  - users: ALPeopleList
  - jobs: DAList
---
mandatory: true
code: |
  users.gather()
  for job in jobs:
    job.employer
  review_done
---
generic object: ALIndividual
question: Name of ${ x }
fields:
  - First: x.name.first
  - Last: x.name.last
---
question: Any users?
yesno: users.there_are_any
---
question: Who employs you?
fields:
  - Employer: jobs[i].employer
  - Pay: jobs[i].pay
---
question: Review
continue button field: review_done
review:
  - Edit: favorite_color
    button: Your favorite color
---
question: Favorite color?
fields:
  - Color: favorite_color
  - Shade: favorite_shade
---
event: show_help
question: Help
subquestion: ${ help_text }
---
question: Help text
fields:
  - Text: help_text
---
question: Never asked
fields:
  - Nobody: nobody
"""}
    result = scan_interview(files.__getitem__, "main.yml")
    flagged = {
        b["data"]["question"] for b in result["blocks"] if b["possibly_unreachable"]
    }
    assert flagged == {"Never asked"}
    variables = {v["name"]: v for v in result["variables"]}
    # One read of a question's field does not make its other fields used.
    assert not variables["favorite_color"]["possibly_unused"]
    assert variables["favorite_shade"]["possibly_unused"]
    # Iterating jobs may ask any element attribute.
    assert not variables["jobs[].pay"]["possibly_unused"]
    assert variables["nobody"]["possibly_unused"]

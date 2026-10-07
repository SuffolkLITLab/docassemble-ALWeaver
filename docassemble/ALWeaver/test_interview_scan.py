# do not pre-load
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


LEGACY = {
    "standalone.yml": """include: reusable.yml
---
id: main order
mandatory: true
code: |
  basic_questions_intro_screen
  interview_order_test
---
mandatory: true
question: Download your forms
subquestion: All done.
""",
    "reusable.yml": """include: docassemble.AssemblyLine:baseline.yml
---
code: |
  interview_short_title = 'Ask for help'
---
id: interview_order_test
code: |
  name
  interview_order_test = True
---
question: Your name
fields:
  - Name: name
""",
    "docassemble.AssemblyLine:baseline.yml": """question: ${ interview_short_title }
subquestion: Shared instructions.
continue button field: al_intro_screen
---
code: |
  al_intro_screen
  basic_questions_intro_screen = True
""",
}


def test_legacy_main_order_inherited_intro_and_mandatory_download():
    from .interview_scan import resolve_report_entrypoint

    assert (
        resolve_report_entrypoint(
            LEGACY.__getitem__, "reusable.yml", ["standalone.yml", "reusable.yml"]
        )
        == "standalone.yml"
    )
    scan = scan_interview(LEGACY.__getitem__, "standalone.yml")
    blocks = {b["scan_id"]: b for b in scan["blocks"]}
    ordered = [blocks[key] for key in scan["screen_order"]]
    assert [b["data"]["question"] for b in ordered] == [
        "${ interview_short_title }",
        "Your name",
        "Download your forms",
    ]
    assert ordered[0]["report_title"] == "Ask for help"


def test_callable_signatures_are_static_and_keep_parameters():
    source = '''code: |
  def help_person(name: str, *, urgent=False):
      """Prepare a greeting."""
      return name
  class Helper:
      def greet(self, person, **options):
          return person
'''
    symbols = scan_interview(lambda _: source, "main.yml")["symbols"]
    assert symbols[0]["signature"] == "help_person(name: str, *, urgent=False)"
    assert symbols[0]["documentation"] == "Prepare a greeting."
    assert symbols[2]["kind"] == "method"
    assert symbols[2]["signature"] == "Helper.greet(self, person, **options)"


def test_imported_functions_and_methods_are_read_without_execution(
    tmp_path, monkeypatch
):
    (tmp_path / "report_helpers.py").write_text(
        '''raise RuntimeError("must not execute")
__all__ = ['greet', 'Helper']
def greet(person, *, formal=True):
    """Greet someone."""
    return person
class Helper:
    def prepare(self, count=2):
        return count
def hidden():
    pass
'''
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    source = "modules:\n  - report_helpers\n"
    symbols = scan_interview(lambda _: source, "main.yml")["symbols"]
    assert {s["name"] for s in symbols} == {"greet", "Helper", "Helper.prepare"}
    method = next(s for s in symbols if s["kind"] == "method")
    assert method["signature"] == "Helper.prepare(self, count=2)"
    assert method["origin"] == "report_helpers"


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


def _undefined(result):
    return {v["name"] for v in result["variables"] if v.get("undefined")}


def test_undefined_names_match_the_playground():
    files = {
        "main.yml": """include:
  - shared.yml
---
mandatory: True
code: |
  some_missing_var
""",
        "shared.yml": "question: Hi\nfield: hi\n",
    }
    result = scan_interview(files.__getitem__, "main.yml")
    assert _undefined(result) == {"some_missing_var"}
    entry = next(v for v in result["variables"] if v["name"] == "some_missing_var")
    assert entry["references"] == ["main.yml#1"] and entry["definitions"] == []


def test_predefined_local_and_docassemble_patterns_are_not_undefined():
    source = """modules:
  - collections.abc
---
objects:
  users: DAList
---
mandatory: True
code: |
  for item in users:
    item.complete
  total = sum(len(str(x)) for x in [1, 2])
  helper = lambda value: value
  when = today()
  isinstance(users, Iterable)
  flagged
  pressed
  defined("maybe_never_set")
---
question: Pick
fields:
  - Choice: choice
validation code: |
  flagged = choice == "a"
---
Question: Go?
Buttons:
  - Go:
      code: |
        pressed = True
---
question: Summary
subquestion: |
  <% count = len(users) %>
  % for person in users:
  ${ person } of ${ count } on ${ loop.index }
  % endfor
  ${ i } ${ comma_and_list(users) }
continue button field: summary_seen
---
# question: Old
# subquestion: ${ deleted_variable }
# field: old_screen
"""
    result = scan_interview(lambda name: source, "main.yml")
    assert _undefined(result) == set()


def test_unreadable_include_or_module_skips_the_undefined_check():
    files = {
        "main.yml": "include:\n  - gone.yml\n---\nmandatory: True\ncode: |\n  anything\n"
    }

    def read(name):
        if name not in files:
            raise FileNotFoundError(name)
        return files[name]

    result = scan_interview(read, "main.yml")
    assert _undefined(result) == set()
    assert any("not checked" in w and "gone.yml" in w for w in result["warnings"])
    modules = "modules:\n  - docassemble.not_installed_here\n---\nmandatory: True\ncode: |\n  anything\n"
    result = scan_interview(lambda name: modules, "main.yml")
    assert _undefined(result) == set()


def test_tabs_are_read_the_way_docassemble_reads_them():
    source = "mandatory: True\ncode: |\n  if ready:\n  \tdone = True\n  done\n---\nquestion: Ready?\nyesno: ready\n"
    result = scan_interview(lambda name: source, "main.yml")
    assert not result["warnings"]
    assert _undefined(result) == set()

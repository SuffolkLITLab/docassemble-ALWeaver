Always use a local venv before trying any Python tests.
Check in .venv as well as ~/venv

After every change, you can use dayamlchecker to validate YAML syntax.

You should run tests interactively covering these patterns:

1. Unlabeled Word document
2. Unlabeled PDF document
3. Labeled PDF document
4. Labeled Word document

Also try with/without LLM assistance and with/without "auto drafting/I'm feeling lucky" mode enabled.

When modifying this repository, you should use the Docassemble API
to test that your changes work.

Look for an existing docassemblecli installation in ~/.docassemblecli, likely apps-dev.suffoklitlab.org

You can directly use docassemblecli

You can use the bearer token in the header as X-API-Key along with
the API request.

Always install your test to a playground project with the name
Weaver and the branchname, using CamelCase as no non-letter
characters are allowed.

Then run the test via server.com/start/playground[my user ID]/assembly_line

## Running the checks locally

Run pytest from a directory that is **not** the repo root:

    cd /tmp && /path/to/repo/.venv/bin/python -m pytest /path/to/repo/docassemble/ALWeaver -q

Running a *subset* of the tests from the repo root can fail every selected test
at fixture setup with

    ImportError: Blocked import of defusedxml from current working directory

nltk's import guard refuses imports from the working directory, and the repo
root contains `docassemble/`. The full suite happens to import in an order that
avoids it, so this bites when you narrow to one file to debug something —
exactly when a wall of errors is most misleading. It is not a real failure and
has nothing to do with your change; move out of the root and re-run before
investigating.

CI runs unit tests, mypy and black (`black_linter.yml`). Run `black` and `mypy`
on anything you touched before you call the work done.

`data/static/editor.js` is a single ~10k-line file that builds its markup by
string concatenation, so a missing quote is a runtime break, not a parse error
in review. Run `node --check docassemble/ALWeaver/data/static/editor.js` after
every edit to it.


## Editing generated and author-written YAML

The rule the editor is built around: **never re-serialize a document to change
part of it.** Patch the exact source range and leave every other byte alone.
Authors' comments, quote styles, key order and blank lines are theirs.

Two traps in that, both of which have already caused bugs:

- PyYAML ends a **block sequence** node where the *next token* begins, so the
  node text runs past the last item and over any comment or blank line before
  the following key. Use `node.value[-1].end_mark` for the real end. Plain and
  block scalars do report accurate ends.
- `ast` column offsets are **UTF-8 byte offsets**, not character offsets. Do
  source edits driven by `ast` on `code.encode("utf-8")`.

Re-read and verify a patch before keeping it, and refuse rather than guess when
the source is not a shape you recognise. `update_settings()` and
`validate_candidate_source()` both work this way, and the round-trip guard in
`_update_metadata()` is what caught the multi-item-list corruption rather than
shipping it.

Write only what actually changed. Rewriting an unchanged value re-quotes
literals the author typed by hand and produces a diff full of churn that hides
the real edit.

Distinguish a **literal** from a **computed** value before writing anything
back. `al_form_type = form_type_for(case)` reaches the panel as its source text;
rendering it through `repr()` turns working code into the string
`'form_type_for(case)'`. Values the interview computes are read-only in the UI
and skipped on save, and the UI says which block to edit by hand instead.

One name, one home. If a setting is already assigned in an author-owned block,
update it there rather than adding a second assignment in Weaver's block — two
assignments of one name leave document order to decide the winner.


## Derive facts, do not restate them

Anything the UI says about the code should be computed from the code. The
AssemblyLine settings panel names the YAML document each section writes to, and
that list comes from the fields' own `scope` rather than a parallel table, so it
cannot drift when a field moves between metadata and code. Prefer one more
derivation over one more list to keep in sync.

Comments explain *why*, not *what*. The interesting comments in this codebase
record the constraint that forced the shape of the code — what PyYAML reports,
what docassemble does on Enter, what a round-trip guard is protecting against.
Match that; skip the ones that restate the line below them.

`architecture.md` is the design document for the editor and is worth reading
before any editor work. It is also worth correcting when you find it stale.


## Editor front end

Vanilla JS and Bootstrap, no jQuery. ALToolbox controls such as
`al_tree_select` are docassemble `CustomDataType`s bound to jQuery and to
docassemble's form machinery, so they cannot be dropped into the editor SPA;
mirror the pattern (plain `<details>`/`<summary>` groups around plain
checkboxes) instead of importing the file.

`esc()` escapes quotes as well as angle brackets, because nearly every call site
puts its output inside a double-quoted HTML attribute. Keep it that way.

Guidance that the author needs *while typing* belongs under the control, not in
a `placeholder`, which disappears exactly when it is wanted. Keep placeholders
for genuine example values (`MA`, `15em`, `https://example.com/help`).

There is no DOM test harness. `test_editor_frontend.py` asserts against the
text of `editor.js` and `editor.html`, which is a cheap regression net for
wiring, ids and copy — add to it when you add a control.


## Generated interview conventions

Filenames follow the AssemblyLine YAML coding style: a descriptive name derived
from the document when the package holds one interview, `main.yml` for a
runnable file in a package with several. Never `interview.yml`.

`map_raw_to_final_display()` and the tables in `generator_constants.py` are the
only thing that turns template field labels into AssemblyLine variables. It is
always on; no toggle disables it, and the LLM assist path only rewrites labels
and datatypes. Label UI accordingly so authors do not read a question-wording
option as a naming option.

Style-check findings come from ALDashboard's linter, which grades its own rules
red/yellow/green. They are advisory: they never run inside
`validate_candidate_source()` and never block a save, so do not present them at
the same severity as a file that will not load.

# Expression editor browser regression — #1062

Executed on 2026-09-18 against `http://localhost/al/editor`, installed with
`~/venv/bin/dainstall --server localhost .`. Luna agents drove Chromium through
the real editor using Playwright and an authenticated developer session.
Dedicated scratch interviews were seeded through the API; edits below used
the browser controls, and persistence assertions read the saved interview.
Scratch interviews were removed after each run.

| Area | Browser assertion | Result |
| --- | --- | --- |
| Code blocks | Supported assignments, including commented code, default to guided editing; unsupported calls retain CodeMirror | Pass |
| Workspace | Guided code workspace exceeds the old 960px limit on a wide display | Pass |
| Recursive builder | Comparisons, functions, boolean groups, lists, operand addition/removal, multiline strings, Unicode | Pass |
| View switching | Python → guided → Python retains the expression; unchanged assignment source remains exact after saving | Pass |
| Question conditions | Change root expression type, build a comparison, apply; Escape discards a subsequent draft | Pass |
| Field defaults and conditions | Nested `code` mappings survive modal editing, field-tab switches, save and reload | Pass |
| Field modifiers | Required, disabled, validation and Mako minimum values retain expression semantics | Pass |
| Field code | Python list expression remains a YAML string, not a YAML list | Pass |
| Anonymous questions | Adding a block ID during save preserves the neighboring author's comment | Pass |
| Order conditions | Modal edit → inline Save → file Save → reload retains generated Python condition | Pass |
| Selected Python source | Invalid syntax reports feedback; Escape preserves source; valid edit changes the selected span and saves | Pass |
| Markdown/Mako | Selected `${ ... }` is wrapped once, surrounding prose is preserved; insertion works at an empty selection | Pass |
| AL method options | Expression dialog works above Bootstrap's options modal; applying both levels persists the parameter | Pass |
| Reviews | `show if` modal changes persist | Pass |
| Raw objects | Unsupported factory call opens in Python; a supported replacement switches to guided editing and persists | Pass |
| Documents | Enabled condition modal edits persist through save/reload | Pass |
| Attachment mappings | Nested expression modal edits preserve Mako wrapping and persist through mapping Save | Pass |
| Narrow viewport | At 600px, the dialog fits the viewport; insertion and keyboard Save work | Pass |
| Failure fallback | Aborted parser API request leaves unchanged, usable CodeMirror | Pass |
| Navigation/reload | Saved expressions survive navigation/reload; no unhandled browser page errors | Pass |
| Full YAML | Arbitrary expression selection changes only its exact source span | Pass |
| Mandatory expressions | Graphical saves retain the original condition before and after editing it in Full YAML | Pass |
| Revised assignment layout | Defined variables and first operands share a centerline (within 3px); compound expressions remain grouped | Pass |
| Code comments | Header, inline and trailing comments survive operand edits; structural replacements retain internal comments once and remain guided | Pass |
| Question tabs | Visiting Options from Screen preserves an existing `if` expression | Pass |

Browser testing exposed and fixed source-preservation defects: adding an ID
to an anonymous question erased neighboring comments, and a graphical question
save converted an existing `mandatory` expression to `True`, and switching from
Screen to Options could remove the question's `if` expression. Regression coverage
was added for these cases. Browser harnesses also wait for asynchronous Apply to finish
and dirty state to enable Save before asserting persistence.

Automated verification after the visual revision: 877 Python tests and 808 subtests passed; JavaScript
format/lint/type checks and Python type checks passed. The parser tests compare
generated expressions with Python ASTs and verify that parsing never evaluates
interview code.

The visual revision was checked against the Gavel and HotDocs screenshots and
Clio condition-builder reference in #1062. Luna re-exercised the code builder,
fields, question conditions, Mako, reviews, AL method options, raw objects, full
YAML, document conditions, attachment mappings and narrow viewport interactions.
The new regression tests cover internal comments, structural replacements,
Unicode/CRLF offsets and preservation of conditions when their controls are not
on the active tab. Python preview is now opt-in rather than a second competing
editor surface.

This is editor-authoring coverage, not execution of arbitrary generated
interviews or external integrations. Unsupported Python deliberately remains
editable in CodeMirror. The attachment-mapping fixture exercises an existing
mapping even when its referenced binary template is absent; the expected missing
template warning does not prevent editing the mapping.

## Function and symbol-picker revision

Luna additionally drove a deterministic delayed-catalog test: the variables
response was held until after typing in the mounted editor, then released;
filtered suggestions appeared without refocusing or typing again. Keyboard
selection, ArrowUp, Escape dismissal and modal filtering passed.

Actual AssemblyLine `get_visible_al_nav_items` and ALToolbox `space` were selected
from the included interview's imports, with signature, origin and docstring
checks. Nested calls, visible comma separators, a final named argument,
inside-out guidance, syntax-valid saved Python and reload passed. Desktop and
600px function layouts had no horizontal overflow. The builder, raw factory
calls, order conditions, source selection, comments, fields, documents and
attachments were also re-exercised using the installed package.
The final installed build also passed Calculation ↔ Conditions switching,
including the AND/+ controls, group layout and generated Python preview.

Automated verification for this revision: 881 tests and 813 subtests passed;
JavaScript format/lint/type checks, Python type checks and diff checks passed.

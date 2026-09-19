# Guided expression editor

Python remains the stored source. The shared editor offers comparisons,
AND/OR/NOT, arithmetic, nested groups, variable/attribute/index references,
text/numbers/booleans/None, lists/tuples, and function calls. Dates use
`as_datetime("2026-09-18")` or `today()`. Variable inputs search the interview's
existing symbol catalog. No intermediate variables are created.

`editor_expressions.py` parses with Python's AST, without evaluation. The UI
tree is temporary and is never saved alongside the interview. Starred arguments,
comprehensions, conditional expressions, and unsupported statements
open in CodeMirror. Switching views or applying an unchanged expression keeps
its exact original source. A syntax error prevents applying a changed modal
buffer; advanced but syntactically valid Python can still be applied.

Function calls accept positional and named arguments, custom functions and
qualified names. Parentheses delimit each call, commas separate arguments, and
nested calls explicitly explain inside-out evaluation. Changing the function
name retains authored arguments. Parameters and help expands to show the
signature, docstring and module. The catalog reuses the interview tree produced
by existing playground symbol discovery, following transitive includes and both
`modules` and `imports` (including relative names and `__all__`). This includes
AssemblyLine and ALToolbox functions imported by that interview, not unrelated
functions that happen to be installed. Catalog inspection never calls functions
or adds another interview assembly. Local code signatures use static ASTs.

Variable and function pickers read the live catalog as the author types, including
when loading finishes after the editor opens. Arrow keys and Enter choose a
suggestion; Escape dismisses suggestions without closing the expression dialog.

A code block defaults to a full-width guided view only when **every statement**
is a supported single-target assignment. Assignment targets are displayed, not
created or renamed. Changed expression ranges replace only their corresponding
source spans; Unicode offsets count code points, not AST byte columns. Code
comments do not prevent guided editing. Header and trailing comments remain
outside the edited spans. Operand edits inside commented multiline expressions
patch the original leaf spans; replacing a whole expression retains its internal
comments inside a parenthesized replacement. Flow stays in the existing
Interview Order builder.

The layout follows the references in [#1062](https://github.com/SuffolkLITLab/docassemble-ALWeaver/issues/1062):
Gavel's variable–equals–formula alignment and operand/type pickers, Clio's
field–comparison–value condition rows, and HotDocs' progressive access to source.
Only groups are indented; primitive values are compact typed inputs. Calculation
and condition choices are separate, and Python preview is collapsed by default.
Narrow workspaces stack assignments and comparisons without horizontal overflow.

## Entry points and Docassemble semantics

The implementation was checked against the local Docassemble `parse.py` and
the `upstream/gh-pages` documentation branch (`_docs/fields.md`). In particular:

| Context | Entry point | Stored representation |
| --- | --- | --- |
| Order conditions, block `if`, review `show if` | Edit expression modal | Python expression |
| Order invocation / raw code | Edit expression modal | Expression / Python statements |
| Field `code`, `validate`, `required`, expression modifiers | Edit expression modal | Python expression (`validate` expects a callable) |
| Field `show if`, `hide if`, `enable if`, `disable if` | Edit expression modal | Nested `{code: expression}`, evaluated before the screen is shown |
| Field `default` | Edit expression modal | Nested `{code: expression}`; unchanged literal defaults remain literal |
| Field `min`, `max`, lengths, step, and text modifiers | Edit expression modal | Mako `${ expression }`, because these are TextObjects |
| Document enabled conditions | Edit expression modal | Python expression at the existing point of use |
| Attachment mappings and Markdown/Mako text | Insert / edit expression | `${ expression }` at the cursor; selected Python or `${ ... }` can be edited |
| Raw object declarations and AL method parameters | Edit expression modal | Existing Python value context; unsupported calls remain source |
| Any other YAML/Python/Mako expression context | Select Python in CodeMirror, then Edit selected expression | Exact selected span only; exclude YAML keys and `${ }` delimiters |

The last entry also covers less common directives such as `mandatory` and
`initial` expressions, `need`/`require` entries, table rows/columns/filters,
attachment code, computed template filenames, and nested custom datatype
parameters, without guessing a scalar's language from its contents. JavaScript
conditions do not get Python controls. A variable/is field condition remains
structured; its modal action directs the author to YAML instead of converting
away the client-side behavior.

The modal's Cancel/Escape discards its draft and restores focus. Apply dispatches
the normal field change events, so existing save/revision/dirty-state handling
continues to own persistence. Source selections and input values are checked
for intervening edits before applying. Parser failures leave CodeMirror usable.

## Verification

`test_editor_expressions.py` and `test_editor_expressions.js` cover the subset,
fallback boundary, syntax limits, Unicode source ranges, and Python-AST
equivalence after JavaScript generation. Serializer tests cover required
expressions, nested code mappings, and JSON-looking literal defaults. API tests
cover authentication and parsing without evaluation. The existing editor and
attachment suites cover source preservation, order structure, dirty state,
validation, and frontend contracts.

The executed Luna browser matrix is recorded in
[editor_expression_browser_tests.md](editor_expression_browser_tests.md).

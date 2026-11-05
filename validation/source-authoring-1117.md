# Source authoring validation (#1117)

## Browser coverage

The source authoring stack was installed on localhost with `dainstall` and tested
against the actual editor, authenticated Playground API, and bundled CodeMirror.
`scripts/editor_source_workbench_smoketest.js` creates and deletes its own project.
It verifies:

- One existing left rail, with Outline/Variables switches, insertion at the retained
  selection, non-underlined names on hover, and definition links that keep source mode.
- Unsaved changes, individual hunk reversion, full restore, and CodeMirror undo.
- Recipe preview/insertion, exact ID repair, and the outline of unsaved source.
- F11 entry/exit, narrow full-screen layout, Findings exit, and sidebar restoration
  when returning to the graphical editor.
- Save persistence and no serious/critical Axe findings at a narrow viewport.

The standalone CodeMirror smoke test also covers native completion and diagnostic
navigation. The existing localhost full-YAML cursor smoke test passed for the
underlying source-authoring branch.

## Independent reviews

Claude and Argon reviewed the source-authoring implementation. Review suggestions
were checked against the actual code rather than treated as confirmed defects.
Changes responding to these reviews include scoped/index-aware completions,
listener/extension cleanup, exact diagnostic snapshot checks, multiline highlights,
highest-severity gutter navigation, and conservative source-to-block matching.

Claude also reviewed the workbench and the consolidated sidebar. Fixes include
keeping the normal Variables command in the same source rail, restoring filter
preferences, rejecting repeated recipe IDs, scrolling inserted text into view,
and preserving the single rail through full-screen exits. Narrow full-screen
tracks are bounded and place the sidebar below the editor, clear of exit controls.
Source mode deliberately keeps the sidebar expanded, restoring its previous
collapse setting when leaving source mode.

A changed server revision intentionally does not prevent local preview or undoable
buffer edits. The warning explains that Save still checks the original revision;
a preview cannot write the server file or silently accept a newer revision.

## Scope

The workbench adds reviewable source operations without executing unsaved YAML.
The existing runtime inspector, Kiln test workflow, and revision-aware rename remain
available. A simultaneous source/runtime split and multi-file move-to-include
refactoring remain follow-up work; this change does not implement them.

## Automated results

- Full unit suite: **1,584 passed, 1 skipped**.
- `npm run check`: passed (format, lint, TypeScript, generated bundles).
- `mypy . --exclude '^build/' --explicit-package-bases`: passed, 147 files.
- Localhost source-workbench smoke test: passed, including narrow full screen,
  Findings exit, graphical-editor return, and accessibility checks.

Argon's follow-up review of the single-sidebar revision identified four additional
issues, all addressed: restoring collapse state now updates DOM state directly
instead of emitting a click that could dismiss the runtime inspector; source tab
and filter preferences survive Save/remount; outline status lives in the shared
rail so it remains visible in full screen; and Findings exit repositions the block
menu. The localhost smoke test now covers saving with Outline selected and a
variable filter, full-screen stale-outline feedback, and opening the runtime
inspector after restoring a previously collapsed rail. All passed. The frontend
suite (47 passed, 1 skipped, 57 subtests) and `npm run check` passed again after
these fixes. The existing localhost cursor smoke test also passed with the
consolidated sidebar.

## Playground examples and contextual insertion revision

The four-entry recipe catalog was replaced with the installed Playground's own
configured hierarchy. The source browser now keeps a searchable category tree
beside source, documentation and runnable-example links, and plain-text context.
The existing block picker inserts locally from a block's context menu, the Tools
menu, or an outline gap. It does not save, reserialize the file, or leave source
mode. AI/library actions that require the graphical workflow remain there.

Claude reviewed this revision. Confirmed findings addressed include preserving
first-line directives such as `# use jinja`, avoiding an empty document with a
leading separator, making top insertion independent of the cursor, clearing stale
selection status, and keeping error recovery keyboard-accessible. The installed
Docassemble version exposed the moved Playground helper; both old and new helper
locations now have compatibility tests. Axe caught a focusability issue in long
source previews, which was fixed with keyboard-focusable previews.

Argon's first broader pass timed out without a report. A second focused review of
the updated backend and insertion lifecycle completed with no defects reported.
Focused backend, API, and frontend tests passed: 281 tests, 1 skipped, 183
subtests. JavaScript checks and mypy passed. The localhost workflow covers the
actual Playground category tree, search, surrounding example code, example
insertion/undo, contextual block insertion with unsaved edits in full-screen
source mode, top insertion preserving the file header, and stale-picker rejection.

## Standard Tools dropdown and outline-dialog removal

Removed the standalone Source outline tool and its unused preview API action.
The shared sidebar remains the place for block navigation. Tools now uses the
application's standard Bootstrap dropdown button, caret, item styling and
keyboard/outside-click behavior. Disposal hides the dropdown before releasing
its instance, including Bootstrap's touch-device listeners.

Focused tests: 56 passed, 1 skipped, 57 subtests. JavaScript checks passed. The
localhost workflow verifies the absent Source outline action, arrow-key menu
navigation, Escape returning focus to the toggle, outside-click dismissal, and
the remaining authoring workflows. Native workbench dialogs already return focus
to CodeMirror on close; the browser test now asserts that explicitly.

Argon reported no defects. Claude reported no blocking dropdown defects; its
minor disposal suggestion was applied. Its concern about losing unsaved-outline
navigation is the requested feature removal, documented in architecture.md;
its proposed focus-return issue is handled by the existing dialog close listener
and covered by the localhost check.

## Collapsible right Variables sidebar

Variables now uses an inline right sidebar beside full-file YAML, with the block
outline remaining on the left. The collapse/expand control hides the panel content
and frees editor width. Its preference is stored locally and survives saving,
source-editor remounts, and reloading the page. Opening the Variables command
expands the existing source sidebar rather than opening a separate panel. Full
screen keeps the same editor/variables grid; narrow layouts stack the panel below
the editor and support collapsing it to a short row.

The localhost workflow passed desktop geometry and reclaimed-width checks,
click-to-insert, full-screen/narrow collapse and expansion, Save and reload
persistence, filter retention on Save, and the existing workbench workflows and
Axe checks. Frontend tests passed: 47 passed, 1 skipped, 57 subtests. JavaScript
checks passed.

Claude review feedback was addressed by preserving ordinary variable-browser dock
preferences, hiding the covered left rail from keyboard focus in full screen,
and placing source-navigation feedback below the toolbar. Existing panel overflow,
minimum-height, hidden controls and absolute action positioning were checked
against the actual styles and browser layouts.

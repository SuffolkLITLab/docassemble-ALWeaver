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

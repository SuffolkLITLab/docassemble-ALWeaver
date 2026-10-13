# Contextual Mako editing — #1195

Tested on 2026-10-12 in Linux/WSL2 (`6.6.87.2-microsoft-standard-WSL2`).
The live editor was installed at `http://localhost/al/editor` with
`dainstall --server localhost .`. All live fixture projects were removed after
testing; the installed implementation remains available on localhost.

Repository checks: 1,476 tests passed, including the Chromium browser harness;
Black, mypy, JavaScript formatting/lint/type checks, bundle checks, and
DAYamlChecker passed. Firefox additionally ran the Markdown browser suite.
The final line-directive/tag distinction was verified with its focused Node
regression and the complete frontend suite after the full test run.

| Environment | Result |
| --- | --- |
| Chromium 151.0.7922.34 | Shared Markdown/CodeMirror browser regressions pass; live editor save/reopen and screenshot run passes |
| Firefox 157.0 | Shared Markdown/CodeMirror browser regressions pass |
| Chromium touch emulation | Portrait 768×1024, landscape 1024×768, narrow 390×700; tap action/dialog, layout, and Cancel pass |
| Keyboard and automated accessibility | Tab/Space opens contextual editing; Escape, suggestion-first Escape, restored focus, and Axe checks pass |
| WebKit 27.2 | Downloaded, but unavailable because the host lacks runtime libraries; no WebKit result claimed |
| Desktop Safari / real iPad Safari | Not tested; hardware/device verification remains required |
| VoiceOver / real on-screen keyboard / pinch zoom and touch selection handles | Not tested; emulation is not evidence for these checks |

The shared browser harness tests repeated/adjacent token ranges, Unicode,
nested delimiters, quotes, comments/literals, filters, incomplete syntax,
hover-to-action travel without focus changes, touch activation, keyboard opening,
Apply/Cancel/Close/Escape, exact occurrences and field isolation, no-op dirty
state, undo/redo preserving earlier prose edits, advanced Python, empty/invalid
drafts, parser failures, changed-and-restored sources, and disposed/recreated
editors. It uses the actual Python AST parser without evaluating expressions.

The live harness verifies Question, Subquestion, and text-template subject and
content use the same interaction. It edits the second identical substitution,
asserts Apply has not written the file, saves through the ordinary editor action,
reloads, and checks the original prose, Markdown, Unicode, neighboring tokens,
comments, and unrelated YAML blocks. The existing graphical serializer changes
the edited scalar's header from `|` to `|2`; the text value is unchanged except
for the intended expression replacement. No serializer changes are part of this PR.

Claude Code reviewed the implementation in read-only plan mode. Corrections
addressed Python-block/tag ambiguity, Safari's non-focusing pointer behavior,
focus transfer to the contextual action, typing-triggered popover rebuilding,
Cancel/no-op selection restoration, modal initial focus, visual-viewport scroll
behavior, textarea/CodeMirror divergence, and shared range caching. Additional
checks reject drafts that would accidentally become Mako filters or comment out
the closing delimiter. Unchanged drafts still undergo syntax validation at this
entry point, as required by the issue; they never dispatch field-change events.

See `testing.md` for reproducible commands. The
[screenshot gist](https://gist.github.com/nonprofittechy/8f321947246d2d1ecbb69a22a9443343)
contains the live screenshots and machine-readable browser results. Complete
the real Safari/iPad and VoiceOver matrix before treating device acceptance as
verified.

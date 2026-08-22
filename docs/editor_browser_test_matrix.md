# `/al/editor` browser test matrix

Last executed: 2026-08-12 against the local Docker server at
`http://localhost/al/editor` after installing this working tree with
`dainstall`.

## Purpose and fixture

The matrix prioritizes operations that could silently overwrite interview
source. The browser fixture is a multi-document YAML interview containing:

- file-leading, block-leading, and inline YAML comments;
- single-quoted scalars and literal block scalars;
- comments inside a Python literal scalar;
- metadata, include, default-screen-parts, question, code, and disabled blocks;
- an explicit default `datatype: text`; and
- stable IDs suitable for edit, reorder, disable, and concurrency checks.

Each destructive case reseeds a dedicated Playground file. Assertions compare
the complete saved `raw_yaml`, not just parsed values. Scratch files created by
file-management cases are deleted by the test.

## Executed browser matrix

| Area | Case | Expected invariant | Result |
| --- | --- | --- | --- |
| Boot/auth | Authenticated editor and project discovery | Editor loads with no page error and lists `default` | Pass |
| File lifecycle | Create, rename, and delete YAML file through UI | Each operation updates the file picker and persisted file | Pass |
| Graphical edit | Change only question text | Top Save enables; every unrelated byte and all comments remain | Pass |
| Block YAML | Edit question in its YAML tab | Submitted comments and formatting persist; other documents are exact | Pass |
| Metadata block | Edit metadata block source | Top Save enables; only metadata document body changes | Pass |
| Full YAML | Edit complete source | Save enables and `raw_yaml` equals the submitted buffer byte-for-byte | Pass |
| Metadata source | Edit the scoped Metadata tab | Metadata/include/default-parts update; nonmetadata bytes remain exact | Pass |
| Navigation | Stay with unsaved graphical work | Remains in Interview view and keeps dirty buffer | Pass |
| Navigation | Discard unsaved graphical work | Navigates and restores the saved model without writing | Pass |
| Navigation | Save unsaved work before navigating | Persists the intended edit, then navigates | Pass |
| Disable/enable | Comment out and re-enable a block | Complete disable/enable cycle is byte-exact | Pass |
| Reorder | Move a block to the bottom | Bodies move; comments, separators, empty docs, and counts remain | Pass |
| Insert | Insert a question after an existing question | New document is added without changing any pre-existing byte | Pass |
| Order builder | Open an existing mandatory order block | Existing screen references parse into the builder | Pass |
| Screen preview | Open Preview on a question using `users[0].name_fields()` | Modal iframe loads Docassemble's `bundle.css` and labelauty; AL prompts appear as real inputs; interview source is unchanged | Not yet executed |
| Flow report | Click Flow report in the Interview Order panel | New tab lists every screen in order, including screens defined in project files the interview includes and in installed packages it includes (AssemblyLine's generic name/address questions render with the subject filled in), drawn with Docassemble's own stylesheets from absolute URLs (a blob: document cannot resolve rooted paths); Ctrl+P breaks pages by section; interview source is unchanged | Not yet executed |
| Assistant | Open assistant panel | Panel opens without changing interview source | Pass |
| Project search | Preview and apply a selected replacement | Only selected exact span changes | Pass |
| Download | Download current interview | Downloaded bytes equal `raw_yaml` | Pass |
| Concurrency | Save stale metadata after a concurrent full-source write | 409 is explained to the user; newer source is not overwritten | Pass |
| Validation | Validate an unsaved graphical buffer | Drawer identifies unsaved source; saved file remains unchanged | Pass |
| Ambiguity | Edit a file with duplicate block IDs | Request is refused and source remains unchanged | Pass |
| File areas | Visit Templates, Modules, Static, Sources, Interview | All views load without a browser page error | Pass |

Final browser result: **21 passed, 0 failed**. The only console-level failed
resource messages were the intentionally induced 409 stale-revision response
and 400 duplicate-ID response; both were handled and produced no unhandled page
error.

## Bugs reproduced and fixed

1. **Whole-stream source loss on block operations.** Editing one graphical
   question caused all documents to be parsed and dumped again. It erased
   unrelated comments, quote choices, indentation, and literal-scalar styles.
   Delete, disable, enable, reorder, and insert used the same lossy pattern.
   These operations now modify exact document-body ranges. Reorder requires
   every block exactly once, duplicate IDs are rejected, empty documents remain
   in place, and insertion retains every existing byte.

2. **YAML-tab comments disappeared before editing.** Parsed blocks exposed a
   canonical dump as `block.yaml`. The YAML tab now receives the exact document
   source.

3. **Graphical defaults rewrote unchanged annotations.** A graphical question
   save omitted explicit defaults such as `datatype: text` and normalized final
   newlines, which made unchanged fields and literal scalars look modified.
   Graphical saves now patch only semantically changed top-level values and
   treat textarea terminal newlines and explicit graphical defaults as
   equivalent. Inline comments on the changed scalar remain in place.

4. **Save failures could be silent.** Stale metadata and duplicate-ID errors
   rejected the request but raised an unhandled `EditorApiError`, leaving no
   useful UI explanation. Metadata, full-source, block, order, secondary-file,
   and New File failures now show an alert and leave dirty state intact.

## Automated regression coverage

`test_editor_source_preservation.py` covers exact block YAML exposure,
graphical scalar merging, explicit defaults, literal scalars, raw source edits,
disable/enable, delete, reorder, insertion, incomplete reorder lists, and
duplicate IDs. Existing metadata, API, source-document, and frontend suites
cover scoped revisions, raw source responses, dirty-state behavior, and browser
client contracts.

## Deliberate limits of this run

The matrix opened the assistant but did not send an LLM turn, publish to GitHub,
upload binary template assets, create a Weaver project through Celery, or use
the runtime inspector. Those paths depend on external model credentials,
GitHub authorization, background-worker configuration, or runtime-inspector
feature flags and should be exercised in integration environments configured
for those capabilities. Top insertion is intentionally refused when a YAML
stream begins with directives because inserting ahead of `%YAML`/`%TAG` cannot
be guaranteed safe.


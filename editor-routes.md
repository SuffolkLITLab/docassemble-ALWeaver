# Editor navigation routes

The editor uses explicit authenticated page routes and the browser History API.
All page routes render the same editor shell; API and asset URLs are unchanged.

| Path under `/al/editor` | Location |
| --- | --- |
| `/` | Project selector |
| `/projects` | Project selector |
| `/create` | New project |
| `/projects/<project>` | Project, selecting its default interview |
| `/projects/<project>/interviews/<filename>` | Interview, selecting its default visible block |
| `/projects/<project>/interviews/<filename>/blocks/<block_id>` | Graphical block editor |
| `/projects/<project>/interviews/<filename>/source` | Full YAML editor |
| `/projects/<project>/interviews/<filename>/order` | Interview Order |
| `/projects/<project>/interviews/<filename>/settings` | AssemblyLine settings |
| `/projects/<project>/interviews/<filename>/tests` | Tests overview |
| `/projects/<project>/interviews/<filename>/debug` | Runtime inspector, when enabled |
| `/projects/<project>/interviews/<filename>/documents` | Document setup for this interview |
| `/projects/<project>/templates[/<filename>]` | Templates |
| `/projects/<project>/modules[/<filename>]` | Modules |
| `/projects/<project>/static[/<filename>]` | Static files |
| `/projects/<project>/sources[/<filename>]` | Sources (the API calls this section `data`) |

`/projects/<project>/documents` remains an entry point that selects an interview.
The canonical Document setup route includes the filename because its settings
are stored in that interview's YAML. Project, interview, and section entry
points replace their current history entry after choosing a default resource.
The parent aliases `/projects/<project>/interviews` and
`/projects/<project>/interviews/<filename>/blocks` also select the project's
default interview and the interview's default visible block, respectively.
The browser router resolves these aliases into existing editor states and
hydrates the default resources. Hydration replaces `/projects` with `/al/editor`,
the interview collection alias with the selected interview URL, and the blocks
collection alias with the selected block URL. A trailing slash is accepted on
each alias.

Each path component is URL-encoded. Block IDs containing slashes or backslashes,
dot-only IDs (`.` or `..`), and IDs starting with `~` use a `~` prefix followed
by double URL encoding. This keeps IDs opaque through server URL decoding and
browser path normalization without restricting Docassemble's ID syntax.
Refresh restores the saved resource and
view; it does not save unsaved edits. Outline filters and transient dialogs,
drawers, previews, and editing subtabs remain local UI state. Opening a block
link widens the outline filter if necessary to reveal that block.

Normal navigation adds a history entry. Rename and deletion replace the active
entry with the resulting location. Stale links show a resource-specific error
and a parent link instead of silently opening another resource.

Back and Forward use the existing Save / Discard / Stay guard. Before showing
the prompt, the router restores the current history entry. Stay or a failed
save therefore preserves both the URL and the working buffer. Successful Save
or Discard resumes the requested traversal. Resource loaders reject superseded
responses before updating the editor.

## Editing context and local navigation

A persistent location row outside the sidebar shows the filename, resource,
and current view. The browser title uses the same description. The row contains
one source-entry or current-block action; local tabs identify block representations
without explanatory scope annotations. In YAML mode, a compact block-actions menu
also offers visual editing and the existing screen preview for previewable blocks.
The menu sits beside the active source block with an always-visible, touch-sized
button; it does not depend on hover. “Full file YAML” always opens the entire
file. There are no metadata or order subsets in this editor; individual order
blocks remain editable through Block YAML. Block representations are labelled
“Block YAML”, “Visual editor”, or “Python”. Re-selecting the active destination does not recreate
its editing buffer. The Interview section button retains the current interview
view. The filename breadcrumb opens the whole file in the current representation:
Block YAML expands to Full file YAML; visual editing returns to the block workspace.

Source buffers are stashed only from a mounted editor with matching project,
file, and scope identity; an absent editor cannot overwrite an intentionally
empty buffer. Contextual returns from Settings restore the workspace that opened
it, including Full file YAML, or the block representation and question panel.
They also retain outline filters, search, and scroll position.
Source selections and scroll positions are retained locally by resource and
scope. The full-source action opens the block at the cursor in its visual editor.
These local choices do not extend the URL or browser-history contract above. Routed
navigation clears contextual return origins; it does not invent an origin for
a directly opened tool.

Entering Full file YAML clears outline search and selects All blocks. Opening
a block visually from source retains the unfiltered outline. Outline search and
Show filters otherwise change only the list. A hidden selection has
an explicit reveal action. In Full file YAML, selecting an outline item
reveals its exact source range without changing editors. Navigation is
conservatively disabled when the buffer differs from the last parsed source
or the block cannot be located safely. Parser line ranges distinguish identical
blocks; older responses without ranges require a unique text match. The status
explains whether the outline is stale or a block cannot be located. The top-right
action follows the source cursor and opens that block visually. Saving retains
the current editor representation.

## Verification

Unit coverage lives in `test_editor_router.js`,
`test_editor_route_navigation.js`, and `TestEditorNavigationRoutes` in
`test_editor_api.py`. The two Node suites also run through
`test_editor_frontend.py`.

Live smoke tests require Playwright with Chromium, an authenticated browser
storage-state file, and a **dedicated test project** on the target server:

```sh
python scripts/editor_route_smoketest.py --storage-state /tmp/editor-state.json \
  --project RouteTest --interview main.yml --block-id first_question
python scripts/editor_history_smoketest.py --storage-state /tmp/editor-state.json \
  --project RouteTest
python scripts/editor_route_lifecycle_smoketest.py --storage-state /tmp/editor-state.json \
  --project RouteTest
```

All three default to `http://localhost`; `--base-url` overrides that address.
The route smoke test reads existing fixtures. The history test creates/resets
`history_guard.yml` (overridable with `--fixture-filename`). The lifecycle test
creates uniquely named YAML files and deletes them after successful checks.
Keep the storage-state file private and outside the repository.

Verified on localhost on 2026-09-29 with disposable projects and a fresh developer
account. The full suite passed 1,170 tests; the final API/frontend follow-up passed
209 tests and 122 subtests. JavaScript checks, router/history unit suites, mypy,
and Black passed. Live browser coverage included all routed views, refresh,
Save/Discard/Stay and failed Save during Back, rapid navigation with delayed
responses, stale links, hidden blocks, encoded filenames, rename/delete, and
byte preservation outside the edited YAML value. The final route smoke run had
no page errors, console errors, or failed network responses.

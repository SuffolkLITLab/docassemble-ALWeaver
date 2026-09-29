# Editor navigation routes

The editor uses explicit authenticated page routes and the browser History API.
All page routes render the same editor shell; API and asset URLs are unchanged.

| Path under `/al/editor` | Location |
| --- | --- |
| `/` | Project selector |
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

Each path component is URL-encoded. Refresh restores the saved resource and
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

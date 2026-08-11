# Assembly Line Weaver Architecture

The AssemblyLine Weaver is a collection of Python modules and Docassemble YAML
interviews that provides a step-by-step graphical process for building draft
Docassemble interviews. It is optimized for quickly building a skeleton project.
The assumption is that the most common use cases will be for building court
forms or court-form like automations.

For a high-level overview of the components of the AssemblyLine project, see:
https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/al_project_architecture

## Overview

YAML files contain interactive questions and answers. One Python module contains
a list of strings that are handled specially when recognizing fields in PDF and
Word documents. The remaining modules are used as the engine of the draft
interview automation process. This package also contains tests and templates
that are used to standardize the automation process.

## Key files

### YAML files (in docassemble/ALWeaver/data/questions)

File you should run in the browser:
- `assembly_line.yml` can be run directly on a Docassemble server and references
  the other YAML files in the same directory

Other files:
- `config.yml`: frontend to help developers continue building the configuration
  system (not for end users)
- `docx_field_tester.yml`: logic for DOCX template validation
- `feedback.yml`: Feedback form that lets users report issues on GitHub
  in-context
- `pdf_field_test.yml`: logic for PDF template validation
- `visual.yml`: controls visual elements in the Weaver - essentially a theme

### Source files in docassemble/ALWeaver/data/sources

- `configuration_capabilities.yml`: currently describes the list of optional
  packages someone can install in a generated package with the
  Weaver--envisioned to allow more flexible configuration in the future
- `output_patterns.yml`: this file contains small Mako templates that are used
  to build the YAML file that the Weaver produces. It is set up as a series of
  small templates right now rather a single large template.

This directory also contains test files for unit testing with ALKiln (see below for more information.)

### Static files in docassemble/ALWeaver/data/static

These files are primarily the front-end interface files, including images and
CSS.

The graphical editor treats the Playground YAML source as authoritative. The
metadata source tab saves through `/al/editor/api/file/metadata`, which requires
the revision returned by the file-read endpoint and replaces only existing
`metadata`, `include`, and `default screen parts` document bodies. If those
documents cannot be identified safely, the scoped save is rejected and the user
must use full source mode. This is an interim safeguard pending the general
revisioned source-patch model.

Weaver's editor settings use Docassemble's own key style — lowercase words,
grouped under one heading:

```yaml
weaver:
  assistant: True            # the editing assistant; on unless set to False
  assistant model: gpt-5-mini
  runtime inspector: False   # opt-in
  source patch api: False    # opt-in
```

A flat `weaver assistant:` key works too, and the older `WEAVER_ENABLE_*`
spellings — plus the matching environment variables — are still honoured so
existing installs keep working.

The general patch beta ("source patch api") is implemented at
`POST /al/editor/api/file/patch` and is disabled by default. A request supplies the
expected SHA-256 source revision and one or more non-overlapping
`replace-range` operations. Weaver validates every range, applies the full set in
memory, runs the whole result through `validate_candidate_source()`, and performs
one Playground write only if no diagnostic is an error. The response includes the
exact resulting text, new revision, applied operations, diagnostics, and a
unified source diff; a rejected patch returns HTTP 422 with the same diagnostic
list. A stale revision returns HTTP 409 with current and optional base source for
a three-way merge; it never overwrites the newer file.

`editor_agent_validation.py` owns the single answer to "may Weaver present this
source as a valid edit?". Its pipeline is `parse_source_document()` → YAML stream
check → `parse_interview_yaml()` → Weaver source diagnostics → DAYamlChecker →
an optional deterministic ALDashboard lint that always passes `include_llm=False`.
An error-severity diagnostic blocks acceptance; warnings and infos are reported
to both the developer and the agent without blocking. The patch API, the agent's
tools and the editor's unsaved-source check all call it, so agent editing can
never acquire a weaker standard than ordinary editing.

`source_document.py` retains the original text and exact document offsets as the
authoritative representation. Parsed mappings and top-level property ranges are
analysis aids only. Empty documents, custom tags, unsupported top-level values,
comments, and formatting remain in their original source ranges, with unsupported
constructs marked as such instead of reconstructed through `yaml.dump()`.

The file-read API exposes interview text as `raw_yaml`; browser downloads
validate that field as a string before creating a file, including when the
source is intentionally empty.

Project-wide find/replace uses `POST /al/editor/api/project/search` to inspect
saved, text-editable interview, template, module, static, and source files. Its
context previews carry exact source spans and SHA-256 revisions. The matching
replace endpoint rechecks both before writing, preflights the whole selected
batch, and attempts to restore earlier files if a later write fails. Binary and
oversized files are skipped. Safe variable refactor is a separate mode: it uses
the editing assistant's deterministic variable-reference classifier, leaves
display prose unchanged, refuses ambiguous/dynamic references and name
collisions, and validates every changed interview before committing the batch.

Editor browser requests go through `editor_api_client.js`. The client enforces
same-origin credentials, structured `EditorApiError` failures, JSON response
validation, CSRF and request-ID headers, timeouts, and cancellation of
superseded reads. Write requests are deliberately not cancelled or treated as
stale by default because the server may already have applied them. The editor
announces client errors in an ARIA live alert and prevents superseded reads from
clearing newer interface state.

All `/al/editor` browser routes are same-origin and require an authenticated
Docassemble admin or developer. The editor page injects a per-session Flask-WTF
token into bootstrap state, and the centralized client sends it on every write.
No editor route is CSRF-exempt and no wildcard CORS policy is installed. Any
separate API-key integration remains outside the browser editor route family.

The editing assistant is on unless `weaver: assistant: False` turns it off. It
does not depend on the source-patch API: the agent compiles its own range
operations in process and never calls that endpoint. What it does need is a
language model, so the page bootstrap carries an `assistant_status` saying
whether one is reachable — ALToolbox leaves its client as `None` when it finds
no credentials, which is the signal used rather than a guess at config key
names. When no model is configured the panel is still offered but explains what
is missing instead of showing a composer that would fail on submit, and the
endpoints answer 503 rather than pretending the feature does not exist.

Its fundamental invariant is that the LLM proposes semantic
actions, while Weaver produces source, validates source and controls
persistence. The browser sends a working-source snapshot — the saved file with
every unsaved buffer folded in, built by `editor_validation_source.js` — and the
server binds the resulting session to one owner, project and filename. No tool
argument can change that target; unknown properties in a tool call are a schema
error precisely so a model cannot smuggle in a `project` or `filename`.

Each turn runs a bounded server-side loop: the model returns one JSON action,
`editor_agent_tools.py` compiles it into an exact source replacement against an
in-memory candidate, and the whole candidate is validated before the mutation is
kept. Rejected mutations return structured diagnostics to the model and leave the
candidate at its last valid revision, so candidate validity is monotonic. Only
low-risk tools and a small set of deliberately implemented medium-risk ones are
registered; blocks that `source_document.py` marks unsupported are readable but
never rewritten. Runtime tools require `WEAVER_ENABLE_RUNTIME_INSPECTOR`, wrap
the existing allowlisted `al_weaver.inspect_*` actions, and label their results
`observed_runtime` so the model cannot present a static prediction — or a seeded
scenario fixture — as observed behaviour.

Two deterministic operations are worth calling out because neither is safe as
free-text editing. `editor_agent_repair.py` fixes the two blocking diagnostics
that dominate real files — a question block with no `id`, and two blocks sharing
one — by patching exact ranges and re-validating; a repair pass is kept only if
it leaves strictly fewer blocking diagnostics. It is offered at session creation
behind an explicit `auto_heal` flag, the repairs become part of the candidate so
they appear in the diff, and Reset returns to the repaired baseline rather than
to source the validator would reject. `editor_agent_rename.py` renames variables
by classifying every appearance of a name: a reference it recognises is
rewritten, prose is left alone and reported, and anything it cannot tell apart
from a reference — a name inside a string, a call, a longer path built on the
name, an `objects:` declaration that would become an attribute path — refuses
the whole batch. `suggest_object_conversion` maps a flat family such as
`persons1_name` onto `persons[0].name.first` using the same table the Weaver
uses for PDF fields, skipping targets that are display expressions or that would
collapse two variables into one.

A turn outlives any HTTP request — the editor's own client gives up first, and
nginx closes an idle upstream read at sixty seconds by default — so it runs as
the named `weaver_editor_agent_turn_task` in Docassemble's Celery worker,
alongside project generation, and never in an in-process thread. Starting a turn
returns 202 immediately. The loop publishes each event to a short-lived,
owner-scoped progress record as it happens, and the finished turn's result lands
there too, because that is the only place the browser can still read it. That
record has its own Redis key rather than living in the session, because Stop and
the polling reads touch the session concurrently and would otherwise clobber the
turn's own writes. A record nothing has written to for two minutes is treated as
abandoned rather than believed forever.

The assistant is for small, discrete edits, so a chat is capped at ten requests
and counts down toward a prompt to apply and start a fresh one; a long
conversation makes each turn slower and vaguer and its candidate harder to
review as a single diff.

No agent step writes to the Playground. Apply re-checks that the saved file has
not moved on, re-validates the candidate, and hands the source back to the
browser as unsaved editor state that stays dirty against the revision actually on
disk; the existing Save path is what persists it. Sessions live in owner-scoped
expiring Redis records, and server logs record tool names, revisions and
validator counts but never interview text, prompts or runtime variable values.

Unsaved interview edits are tracked by `editor_dirty_state.js` per filename and
block ID, with separate source-dirty and pending-command state. Each loaded file
also has a deep-cloned saved model. Discard restores that model, while a
single-block save updates only that block's dirty state and overlays any other
unsaved local blocks on the fresh server response. Navigation decisions use the
accessible Save/Discard/Stay dialog instead of clearing a global dirty flag.

Source controls use Docassemble's own CodeMirror 6 bundle at
`/static/app/cm6.min.js` through its `window.daNewEditor()` factory. That asset
and factory are required; a missing factory raises a clear installation error
rather than silently changing the editing behavior. `daNewEditor()` attaches an
unsized `EditorView` to whatever parent it is given, so `.editor-source-container`
in `editor.css` owns the height constraint and hands overflow to `.cm-scroller`;
without that the view grows to fit the document and neither the scrollbar nor
the wheel works.

Validation uses `POST /al/editor/api/validate-source` with the source currently
visible in the editor and its base revision. Graphical block and metadata edits
are overlaid only onto their mapped source ranges to create a validation-only
snapshot; the saved Playground file is not substituted for that submitted
buffer. Diagnostics use Weaver-owned level, filename, block, source-range, and
YAML-path fields. The validation drawer identifies saved-source and
unsaved-source results explicitly.

`docassemble_compat.py` is Weaver's compatibility boundary for Docassemble
1.9.x and 1.10.x. Session orchestration uses the stable high-level functions in
`docassemble.base.functions`; raw inspection actions feature-detect the 1.10
Pluggy hook and otherwise use the populated 1.9 server implementation. The same
module owns access to initialized Flask, storage, Redis, and worker objects so
the rest of Weaver does not depend on version-specific private module paths.

The runtime inspector server API is disabled by default behind
`WEAVER_ENABLE_RUNTIME_INSPECTOR`. It creates a Docassemble session separate from
the editor and stores an expiring, owner-scoped `WeaverTargetSession` record in
Redis. Browser calls use only Weaver's opaque session ID; every lookup verifies
the current developer, and public session metadata excludes the raw Docassemble
ID and any secret. Deleting the Weaver record revokes further inspector access;
it does not claim to delete Docassemble's underlying session.

Variable reads are simplified and omit `_internal` by default. Variable writes
never deserialize objects. Question and back operations call Docassemble through
the compatibility interface. Inspection actions are limited to four
`al_weaver.inspect_*` names, always run with `read_only=True`, and reject binary,
HTML, non-JSON, and oversized responses. Returned questions, variables, and
action data are labeled `observed_runtime` so they cannot be confused with
static-analysis findings. Weaver never chooses the next question.

The browser inspector is isolated in `editor_runtime_inspector.js`. It can start
or restart a test session, open the authoritative interview, inspect the current
question, browse simplified variables, reveal `_internal` data explicitly, go
back, and apply a YAML test scenario. Scenario YAML is parsed and validated on
the server, never in browser JavaScript. Scenario seeding is labeled as a fixture
that may bypass earlier questions. Question-to-source links are shown only when a
stable returned `questionName` matches a known block; otherwise the UI says that
no confident match is available.

Uploaded-file project generation runs as the named
`weaver_editor_new_project_task` in Docassemble's configured Celery worker.
Redis stores an owner-scoped job record with queued, start, finish, progress,
result, and structured-error fields, while status polling reconciles nonterminal
records against Celery. A Redis record without an associated task is marked
expired rather than reported as running. Weaver refuses the operation when the
worker module is not configured and never falls back to an in-process thread.
The editor performs this configuration preflight when the server module starts
and includes the result in its page bootstrap. Missing configuration produces a
persistent developer warning with setup documentation before an upload is
attempted, as well as a structured HTTP 503 if a client still submits one.

The `next_steps` DOCX files are templates for "next steps" documents that a user
can print and read after using an interview. They are associated with different
kinds of interviews that the Weaver can produce.

### Python modules

- `interview_generator.py` is the primary module containing most of the Python code used by the Weaver
- `advertise_capabilities.py` is part of the plugin-able configuration system - it tells the server what optional dependencies this Weaver can add to a generated interview file
- `custom_values.py` is used to scan the server for packages that contain custom configuration settings for the Weaver
- `draggable_table.py` is used by the Weaver frontend to allow rearranging long lists of fields
- `field_grouping.py` is a copy of some features from [FormyFyxer](https://github.com/SuffolkLITLab/FormFyxer) that power the "I'm feeling lucky" button (should be deprecated)
- `generator_constants.py` contains several lists of rules for how to transform PDF field names like `users_name_full` into Docassemble objects like `users[0].name`, as well as indicating reserved DOCX variable names that are handled by questions in the AssemblyLine's question library
- `api_editor.py` is HTTP orchestration for the graphical editor; the editing business logic lives in the modules below
- `editor_agent_validation.py` is the one whole-candidate validator, plus the diagnostic normalisation the editor's error drawer consumes
- `editor_agent_models.py` holds the agent session, candidate, turn and tool-result records and their owner-scoped Redis persistence
- `editor_agent_tools.py` is the semantic tool registry — the security and accuracy boundary for everything the model can do
- `editor_agent_repair.py` deterministically fixes missing and duplicate block ids so a mechanical problem does not stop the assistant from starting
- `editor_agent_rename.py` classifies every appearance of a variable name and renames only the references it can positively recognise
- `editor_agent_context.py` assembles the compact interview context a turn is given, fencing untrusted reference material
- `editor_agent.py` runs the bounded agent loop and the explicit final validation pass

## Testing

The Weaver has two kinds of test that are currently configured to run on push to
GitHub:

1. Standard unit tests of pure-Python modules
1. Integration tests using the [ALKiln](https://github.com/suffolkLITLab/ALKiln)
   testing framework

Unit tests can be found in docassemble/ALWeaver/. Filenames begin with `test_`.

The integration tests are located in docassemble/ALWeaver/data/sources/ and
filenames ending with .feature will be run as ALKiln tests.

In addition, `generator_test.yml` is an interactive Docassemble interview that
will test the `map_raw_to_final_display()` function from
`interview_generator.py`. This is designed for quick in-browser testing.

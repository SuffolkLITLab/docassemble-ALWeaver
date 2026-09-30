# Assembly Line Weaver: Suffolk LIT Lab Document Assembly Line

[![PyPI version](https://badge.fury.io/py/docassemble.ALWeaver.svg)](https://badge.fury.io/py/docassemble.ALWeaver)

<img src="https://user-images.githubusercontent.com/7645641/142245862-c2eb02ab-3090-4e97-9653-bb700bf4c54d.png" alt="drawing of two cartoon people collaborating on building a web application" width="300" style="align: center;"/>

The Assembly Line Project is a collection of volunteers, students, and institutions who joined together
during the COVID-19 pandemic to help increase access to the court system. Our vision is mobile-friendly,
easy to use **guided** online forms that help empower litigants to access the court remotely.

Our signature project is [CourtFormsOnline.org](https://courtformsonline.org).

We designed a step-by-step, assembly line style process for automating court forms on top of Docassemble
and built several tools along the way that **you** can use in your home jurisdiction.

This package contains an **automation and rapid prototyping tool** to support authoring robust,
consistent, and attractive Docassemble interviews that help complete court forms. Upload a labeled
PDF or DOCX file, and the Assembly Line Weaver will produce a runnable, clean code, draft of a
Docassemble interview that you can continue to edit and refine.

New interviews use one mandatory interview order block. To generate separate
main order and reusable form order blocks, select **Separate main order and
interview order blocks** under **Create project → Advanced settings**. API callers
can set `separate_main_order=true`; it defaults to `false`. Existing interviews
keep their authored order blocks when opened or edited.

Read more on our [documentation page](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/).


## Related repositories

* https://github.com/SuffolkLitLab/docassemble-AssemblyLine
* https://github.com/SuffolkLitLab/docassemble-ALMassachusetts
* https://github.com/SuffolkLitLab/docassemble-MassAccess
* https://github.com/SuffolkLitLab/docassemble-ThemeTemplate
* https://github.com/SuffolkLitLab/EfileProxyServer

## Documentation

https://suffolklitlab.org/docassemble-AssemblyLine-documentation/

## ALWeaver API

When installed on a docassemble server, ALWeaver exposes a custom Flask API:

- `POST /al/api/v1/weaver` (primary)
- `GET /al/api/v1/weaver/jobs/{job_id}` (async job polling)
- `DELETE /al/api/v1/weaver/jobs/{job_id}` (async job cleanup)
- `GET /al/api/v1/weaver/openapi.json` (OpenAPI spec)
- `GET /al/api/v1/weaver/docs` (human-readable docs)

The API uses docassemble's API key authentication via `api_verify()`.
The `POST` endpoint defaults to synchronous behavior, and supports optional
asynchronous execution with `mode=async` (or `async=true`).

## GitHub permissions for publishing workflows

Publishing to GitHub uses Docassemble's GitHub connection. Weaver also writes
ALKiln test workflows under `.github/workflows/`, and GitHub refuses those
files unless the connection may change workflows. Without that permission the
other files still publish, existing workflows are kept, and the publish dialog
says which of the fixes below is needed.

- **OAuth App** (Docassemble's usual setup): the token needs the `workflow`
  scope as well as `repo`. Docassemble's own GitHub page does not ask for it;
  connect through **Configure GitHub** in Weaver's publish dialog, which does.
  If an organization restricts third-party access, it must also approve the
  OAuth App.
- **GitHub App**: scopes are ignored. In the App's settings, set the
  repository permissions **Contents** and **Workflows** to *Read and write*
  (and **Administration** to *Read and write* if Weaver should create
  repositories). Install the App on every account or organization people
  publish to. After changing permissions, an owner of each installation must
  accept the updated permissions under *Settings → Applications → Installed
  GitHub Apps*; until then the old permissions still apply.

## Celery worker configuration

Uploaded-document project generation in the graphical editor, importing a
template already in a project, publishing a project to GitHub, AI screen/field
drafting, AI style checks, and asynchronous API requests require ALWeaver's task module to be registered with Docassemble's global Celery configuration. Add
the module to the existing `celery modules` list in the Docassemble
configuration; preserve any modules already listed:

```yaml
celery modules:
  - docassemble.ALWeaver.api_weaver_worker
```

After changing the configuration, restart or redeploy both the Docassemble web
service and every Celery worker so that they load the same task registry. Blank
project creation, ordinary graphical/source editing, and synchronous API calls
do not require this module.

ALWeaver checks this setting when its editor module starts and whenever the
editor page loads. If it is missing, the server logs a warning and the editor
shows a persistent setup notice before a developer selects a file to generate.
An attempted background request fails with HTTP 503, a structured
`async_not_configured` API error (or `editor_async_not_configured` from the
graphical editor), and a link back to these instructions. Weaver does not enqueue
an unregistered task or fall back to an in-process thread.

The revisioned graphical source-patch API is an opt-in beta. Set
`WEAVER_ENABLE_PATCH_MODEL: true` in the Docassemble configuration (or the same
environment variable) to enable it. The default production path remains off
until graphical editing paths have migrated to exact source-range commands.

The editor's interview debugger is enabled by default for authenticated
developers and administrators. It runs the real interview in a separate test
session beside current-question details, a step recorder, variable inspection,
scenario seeding, and back navigation. Set `weaver: {runtime inspector: false}`
(or `WEAVER_ENABLE_RUNTIME_INSPECTOR: false`) to turn it off. Its server API uses
owner-scoped target sessions and a fixed read-only `al_weaver.inspect_*` action
allowlist; Docassemble remains the only interview runtime.

## Shared classroom servers

For a class of about 15 developers on an 8 GB host, this editor reduces ongoing
work in several ways:

- The debugger requests one `/runtime/sessions/<id>/snapshot` after the previous
  observation completes. It waits five seconds after changed data, backs off to
  ten seconds when unchanged, and up to thirty seconds after errors, with 10%
  timer jitter. Hidden browser tabs and closed debugger views stop polling.
  Refresh and iframe navigation still trigger observations. Fifteen idle visible
  debuggers therefore generate about 1.5 requests/second instead of 30, before
  accounting for request duration. This is a traffic estimate, not a server benchmark.
- Routine runtime reads renew their Redis lifetime at most once per minute and
  no longer append poll events. Scenario/action history is retained. The combined
  snapshot still reads the question and simplified variables; it is neither an
  atomic snapshot nor a cheap session-revision check. The variable size limit
  applies after Docassemble has simplified the session.
- AI screen/field drafts and explicitly requested AI style checks return HTTP
  202 with `data.job_url`; clients poll that URL until `data.status` is terminal.
  Successful `data.result` contains the previous synchronous response's `data`.
  There is one outstanding job per account (HTTP 429 for another), with at most
  two of these AI jobs executing server-wide. Capacity retries wait 5–10 seconds
  in Celery, without occupying a web worker. Queue lifetime is fifteen minutes;
  execution has a 150-second soft limit and a 180-second hard limit. These tasks do not retry model work
  after failure; any provider SDK retries share the task execution deadline. Use Celery's normal prefork pool
  for these time limits. A lost worker's capacity reservation expires after four
  minutes. Deterministic style checking stays synchronous and is the default
  when `include_llm` is omitted. Existing API consumers of AI routes must handle
  the new job response, and web/Celery services must load the same version.
- Symbol discovery keeps JSON results for up to sixty seconds, checking the main
  file and all transitive includes (including empty files) by content hash and
  filesystem revision before reuse. Directory metadata and entry-name hashes invalidate relative-include
  resolution. Failed parses, dynamic Jinja sources, and untrackable sources are
  not cached. Function help is refreshed separately. Each process retains at
  most 32 results / 2 MiB of serialized symbols; template excerpts have a separate
  256 KiB cache invalidated by file/directory metadata. Each result is capped at
  256 KiB. Same-key parsing is coalesced within a process, and cached data is
  decoded afresh for each caller. No live Interview objects are retained. These
  are per-process caches, not a shared Redis cache; validation still runs its
  correctness checks and reuses symbol discovery when it reaches that step.

A conservative starting configuration for a controlled classroom trial is below.
Merge these keys into existing configuration and preserve the other Celery modules:

```yaml
celery processes: 2
celery modules:
  - docassemble.ALWeaver.api_weaver_worker
weaver:
  restart on module save: never
```

The worker count is a trial setting, not a capacity guarantee. Docassemble counts
its dedicated `celerysingle` worker in `celery processes`; check the actual general
worker pool after applying it. Each worker has its own memory, and uploads,
conversion, generation, and assistant turns still share this host. See
[Docassemble's background concurrency configuration](https://docassemble.org/docs/config.html#celery%20processes).
Schedule configuration changes and restarts outside class. `never` suppresses the
module-save restart workflow; Python changes still need a coordinated restart,
and the explicit restart action remains available.

Before/after testing should use the same interviews and operations: open fifteen
debuggers, let them idle, navigate interviews, request AI drafts, then try document
generation. Compare endpoint request counts and response times, web/Celery worker
RSS, available memory, swap activity, and queue delay. Closing Debug views remains
a useful isolation test; `weaver: {runtime inspector: false}` disables the feature
if needed. These code changes do not establish that a particular 8 GB deployment
can sustain a class's peak document-generation load. See the
[recorded fifteen-user localhost stress test](performance/classroom-2026-09-30.md)
for measured traffic, latency, memory, and test limits.

## Editing assistant data handling

Before a developer sends a request to the graphical editing assistant, Weaver
discloses that the request and relevant interview source may be sent to the
configured model provider. Configure model access only with a provider
approved for the source material handled on that Docassemble server. Weaver
stores assistant chat in an owner-scoped session for up to two hours after its
last update, and progress details for up to 30 minutes after their last update.
These Weaver-side expiry periods do not describe the model provider's data
handling or retention; administrators should consult the provider's applicable
terms and configuration separately.

Administrators can show the applicable provider terms in the assistant drawer
through global Docassemble configuration. For an OpenAI API project using
standard data controls, for example:

```yaml
weaver:
  assistant provider name: OpenAI API
  assistant model: gpt-5.4-mini
  assistant provider retention: >-
    Prompts and responses may be retained in abuse-monitoring logs for up to
    30 days, unless legally required for longer.
```

Check the API organization's actual Data controls and agreement before setting
this text; Modified Abuse Monitoring or Zero Data Retention require different
wording. If the retention setting is absent, the drawer asks the developer to
consult an administrator. The configured text is displayed as plain text.
See [OpenAI API data controls](https://platform.openai.com/docs/guides/your-data)
for the standard policy and available controls.

## History

See [the CHANGELOG](CHANGELOG.md) for more information.

## Authors

Quinten Steenhuis, qsteenhuis@suffolk.edu  
Michelle  
Bryce Willey, bwilley@suffolk.edu
Lily  
David Colarusso  
Nharika Singh  

## Installation requirements

### Using auto drafting mode

To use auto-drafting mode, you can get an Open AI API Key and set it in
your docassemble configuration.

```yaml
open ai:
  key: ...
```

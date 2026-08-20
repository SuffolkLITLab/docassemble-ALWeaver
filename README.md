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

## Celery worker configuration

Uploaded-document project generation in the graphical editor, importing a
template already in a project, publishing a project to GitHub, and asynchronous
API requests require ALWeaver's task module to be registered with Docassemble's global Celery configuration. Add
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

The server-side runtime inspector is also opt-in. Set
`WEAVER_ENABLE_RUNTIME_INSPECTOR: true` to enable owner-scoped target sessions,
current-question and variable inspection, scenario seeding, back navigation, and
the fixed read-only `al_weaver.inspect_*` action allowlist. Docassemble remains
the only interview runtime.

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

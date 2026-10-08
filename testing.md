# Testing instructions

## Developing Tests

To write and run the tests, you'll need to set up your testing environment in Python.

### Set up a virtual environment

First, set up a virtual environment in your command prompt called `venv` to hold all the packages related to this repository.
This will keep your code clean, and make sure this repository does not interfere with
your other projects.

Run these lines in your command prompt.

```
pip3 install virtualenv
virtualenv -p $(which python3.8) venv
source venv/bin/activate
pip3 install --upgrade pip
pip3 install -r docassemble.ALWeaver/requirements.txt
pip3 install --editable .
```

<!-- I had to run `virtualenv -p /usr/local/opt/python@3.8/bin/python3 venv` for the second line. I'm on OSX 10.14.5, but I also have a bunch of weird stuff set up in my configs from waaay back. If we can replicate this on a similar system that doesn't have a bunch of configs set for python, we can add this as a visible warning. -->

(I used `pip3` and `python3` above, because I have both Python 2 and Python 3 on my machine, but you
can use just `pip` and `python` if you only have Python 3.)

If your errors show something like `mysql_config: command not found` it means you're missing
`mysql`, which is a dependency. You can search how to install it for your system.

Another common error is something like `ImportError: pycurl: libcurl link-time ssl backend (openssl) is different from compile-time ssl backend (none/other)`. https://stackoverflow.com/a/21099222/14144258 may help give you direction.

If you want to stop here after setup, you can exit the virtual environment with
```
deactivate
```


### Run the tests

Everytime you want to work on testing, enter your virtual environment with

```
$ source venv/bin/activate
```

To run the tests, make sure your command prompt is in your project's directory (`docassemble-ALWeaver`) and run:
```
python3 -m unittest discover
```

You can also run fewer tests by getting more specific with your testing paths. For example, to run just the `test_mapped_scenarios` method in `test_map_names.py`, you can run:
```
python3 -m unittest docassemble.ALWeaver.test_map_names.TestMapNames.test_mapped_scenarios`
```

The lines below are all valid ways to run tests. They are listed in order of "runs all tests" to "runs one test":

```
python3 -m unittest discover
python3 -m unittest docassemble.ALWeaver.test_map_names
python3 -m unittest docassemble.ALWeaver.test_map_names.TestMapNames
python3 -m unittest docassemble.ALWeaver.test_map_names.TestMapNames.test_mapped_scenarios
```

### Stop

Everytime you finish working on testing, exit your virtual environment with

```
$ deactivate
```

## Editor navigation end-to-end regression

`scripts/editor_navigation_smoketest.js` runs against an authenticated, live
Docassemble server. It creates disposable Playground projects, uploads interview
and secondary-file fixtures, and removes those projects when the run ends. It
checks project switching and the unsaved-change prompt, project-wide search,
sidebar collapse, all five file sections, responsive account and folder menus, visible desktop folder tabs,
200% text size, project-list deduplication and search, and the Default project's
reserved actions. It also runs four Axe WCAG 2 A/AA audits.

Install the browser test tools outside the repository:

```bash
npm install --prefix /tmp/alweaver-e2e @playwright/test @axe-core/playwright
/tmp/alweaver-e2e/node_modules/.bin/playwright install chromium
```

Set `SERVER_URL`, `EDITOR_EMAIL`, `EDITOR_PASSWORD`, and `EDITOR_API_KEY` for your
test server, then run:

```bash
NODE_PATH=/tmp/alweaver-e2e/node_modules \
  SCREENSHOT_DIR=/tmp/alweaver-navigation-screenshots \
  node scripts/editor_navigation_smoketest.js
```

The API key must belong to the browser's user. An administrator's API key can
instead create the fixtures for a different browser user when `EDITOR_USER_ID`
is set to that user's numeric ID. Fixture requests use a separate cookie jar so
API-key authentication does not replace the browser's logged-in user.
`ADMIN_API_KEY` is also accepted by the CI workflow. An authenticated Playwright
`STORAGE_STATE` file can replace the email and password. `CHROMIUM_PATH` can select
an existing Chromium executable.

The output directory contains ten screenshots and `results.json`. Layout checks
cover widths from 320 to 1920 pixels; large-text checks set the root font to 200%
at widths 576, 768, 1024 and 1366. This tests text sizing, not browser zoom. The
editor accessibility workflow runs this regression and uploads the
`editor-navigation-screenshots` artifact, including on failure. The existing
`scripts/editor_route_smoketest.py` also supports the compact section menus.

For the project interview default, `scripts/editor_default_file_smoketest.js`
creates disposable projects through the authenticated editor API and removes
them after the run. It checks the `main.yml` default, first-file fallback,
selecting an existing interview, and opening a valid file-and-block deep link.
With Playwright installed and Chromium available, run:

```bash
NODE_PATH=/tmp/alweaver-e2e/node_modules \
  STORAGE_STATE=/tmp/developer-state.json \
  CHROMIUM_PATH=/path/to/chromium \
  node scripts/editor_default_file_smoketest.js
```

`SERVER_URL` can select a server instead of localhost. The storage state must
belong to a user who can create editor projects.

## Reusable help template end-to-end regression

`scripts/editor_help_templates_smoketest.js` creates a disposable Playground
project and exercises template creation from both the outline and a question's
subquestion toolbar, reuse across questions, nested help, editing and reloading,
YAML/form switching, and adding a subject to a subjectless template. It checks
source comments and custom properties, invalid names, non-template name collisions,
same-name variants and their de-duplicated picker,
and guards against renaming or deleting referenced templates. It then runs the
interview in Docassemble and verifies collapse behavior, Markdown, and evaluated
Mako on both question screens. Two Axe audits cover the new dialog and editor.
The fixture project is removed after success or failure.

Use the same browser dependencies and authentication variables as the navigation
regression above, then run:

```bash
NODE_PATH=/tmp/alweaver-e2e/node_modules \
  SCREENSHOT_DIR=/tmp/alweaver-help-template-screenshots \
  node scripts/editor_help_templates_smoketest.js
```

`scripts/editor_unmapped_validation_smoketest.js` creates and deletes a
disposable project, makes a graphical edit to a CRLF interview, opens an
unmapped validation finding with the keyboard, and saves and reloads the
composed source. Run it against an authenticated local editor session with
Playwright available:

```sh
STORAGE_STATE=/path/to/storage-state.json \
NODE_PATH=/path/to/playwright/node_modules \
CHROMIUM_PATH=/path/to/chromium \
node scripts/editor_unmapped_validation_smoketest.js
```

The output contains editor and live interview screenshots plus `results.json`.
Template insertion and reference checks are scoped to the active YAML file;
advanced templates remain editable in YAML mode.

## Debugger sample filler regression

`scripts/editor_fake_filler_smoketest.js` imports the Affidavit of Indigency and
Security Deposit Demand Letter interviews from `~/all_interviews/repos` into
disposable Playground projects. It uses the actual debugger button to advance
through address and currency screens, checks the first click never submits,
and checks the second uses normal Docassemble submission. Browser fixtures also
cover existing answers, hidden/disabled/read-only controls, conditional fields,
checkbox groups, YAML validation limits, file uploads, invalid answers, submitter
values, and AJAX screen replacement. Debugger browser checks cover collapse
without losing the iframe, internal configuration and imported typing-name
filtering (including reveal with Show internal data), search counts,
inline scalar values (including `False`/zero/empty/`None`), safe text rendering,
persistent compact checkbox lists (including no selections, disabled controls,
and no duplicate value dump), Python booleans and
`None` inside nested values without changing string contents,
persistent nested expansion, collapse on mobile, and an actionable startup error
when an include file has no mandatory endpoint. A live text-field fixture checks
last-four SSN digits against the question's Python `isdigit()` validator and
minimum/maximum length limits, then checks a submitted checkbox question's real
DADict against its visual checked states. The live interview walk also checks
the fill/continue button's size and position before filling and after advancing.
Docassemble 1.9.x and 1.10.0–1.10.7 hide radios and checkboxes behind
labelauty's generated labels; 1.10.8 replaced labelauty with CSS. The live
server covers only the version it runs, so a labelauty check loads 1.9.8's own
jQuery and labelauty with `git show` from a Docassemble checkout
(`DOCASSEMBLE_SOURCE`, default `~/docassemble`) and fills 1.9.8-shaped yes/no,
radio, checkbox-group and "None of the above" markup. It is skipped, with a
message, when that checkout is unavailable.
Faker unit checks sample
100 people/addresses/phones, verify variation and per-object consistency, and
exercise currency constraints and nationwide state selection. Projects and runtime records are removed
after success or failure.

Runtime lifecycle regressions cover reconnect without creating a new interview,
end/replacement deletion, owner isolation, migration of old Redis records,
30-minute inactivity despite polling, progress before a deadline check, and
retry after failed database cleanup. Browser checks reload an interview after
answering, keep its session ID and answers, and verify End removes the session.

To migrate and clean pre-upgrade tracking records, run as `www-data` in the
Docassemble Python environment:

```bash
python -m docassemble.ALWeaver.runtime_session_cleanup /usr/share/docassemble/config/config.yml
```

This only selects tracked Weaver debug interviews, including records written
before the deadline index existed. It leaves ordinary saved sessions alone.

Use the browser dependencies and authentication variables from the navigation
regression, or provide `STORAGE_STATE` for an authenticated developer:

```bash
NODE_PATH=/tmp/alweaver-e2e/node_modules \
  STORAGE_STATE=/tmp/developer-state.json \
  node scripts/editor_fake_filler_smoketest.js
```

`INTERVIEW_ROOT` overrides the local repository collection. `INTERVIEW_CASE`
can select either package or `fixtures` to skip importing real interviews, and
`SCREENSHOT_DIR` overrides the default
`/tmp/alweaver-fake-filler` artifact directory. `results.json` includes screen
answers and separately records known localhost Docassemble chat initialization
and unavailable Google Maps errors; other JavaScript errors fail the run.
The live paths stop before signing and delivery.
For the localhost database and worker regression, copy
`scripts/runtime_lifecycle_probe.py` into the Docassemble container at
`/tmp/alweaver_runtime_probe.py`, then set `CHECK_RUNTIME_DATABASE=1`. Set
`DOCASSEMBLE_CONTAINER` if its name differs from `admiring_goldwasser`. The probe
runs as `www-data`, ages only its own test session's progress timestamp, and
checks real database/Redis deletion by End and by the worker without browser
polling. An ordinary saved session with the same interview filename must survive.
It also checks that expiry in an open debugger removes the iframe and enables
Start debugging. The ordinary fixture is explicitly removed afterward.
Runtime snapshot failures are recorded separately: localhost's existing
snapshot API can fail on unanswered address screens, leaving sidebar details
behind the live interview. The regression verifies filling and submission;
it does not assert complete step recording when that API fails.

## Survey answer field filter end-to-end regression

This regression generates a disposable interview with text and integer
answers, a skipped field, and a code field. It installs the generated package
on the configured Docassemble server, submits the primitive answers in a real
browser, reaches the thank-you screen, then checks the matching JSON storage
row. The database probe removes that row after checking its keys and types.

Generate and install the fixture:

```bash
FIXTURE_DIR=/tmp/alweaver-survey-answer-filter
uv run python scripts/generate_survey_answer_filter_fixture.py \
  --output-dir "$FIXTURE_DIR"
python -m zipfile -e \
  "$FIXTURE_DIR/docassemble-SurveyAnswerFilterSmokeTest.zip" \
  "$FIXTURE_DIR/unpacked"
dainstall --server localhost \
  "$FIXTURE_DIR/unpacked/docassemble-SurveyAnswerFilterSmokeTest"
```

Run the browser and database check. Install Playwright and Chromium first if
they are not already available:

```bash
npm install --prefix /tmp/alweaver-e2e playwright
/tmp/alweaver-e2e/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/alweaver-e2e/node_modules \
  SERVER_URL=http://localhost \
  DOCASSEMBLE_CONTAINER=admiring_goldwasser \
  DOCASSEMBLE_PYTHON=/usr/share/docassemble/local3.14/bin/python \
  node scripts/survey_answer_filter_smoketest.js
```

Set `CHROMIUM_PATH` to use an existing Chromium executable and `STORAGE_STATE`
to reuse an authenticated browser state when the server requires login. The
database probe runs in the Docassemble container as `www-data`; set
`DOCASSEMBLE_CONTAINER` if its name differs and `DOCASSEMBLE_PYTHON` if the
container uses a different Python executable. The generated package name is
`docassemble-SurveyAnswerFilterSmokeTest`; keep the extraction and install path
in sync if you change the fixture title. The probe checks that the stored answer
data includes only `survey_name` and `survey_count` (alongside storage metadata)
and removes its matching row even when an assertion fails.

## Classroom editor load testing

The bounded localhost harness is [scripts/editor_classroom_stress.py](scripts/editor_classroom_stress.py), with a loopback-only, eight-second model fixture in [scripts/editor_stress_model.py](scripts/editor_stress_model.py). It creates individual disposable developer accounts and owned projects, exercises debugger/editor traffic and queued AI drafts, records request latency and cgroup resources, and cleans up fixture accounts. It requires private local admin credentials and a correctly configured localhost web/Celery installation; it does not manage server configuration or the fixture process.

See the [six-minute, fifteen-user report](performance/classroom-2026-09-30.md) for exact setup, cleanup, measurements, test limitations, and committed public result artifacts. That run used an unlimited container on a 15.34 GiB host, so it does not establish an 8 GB deployment's document-generation capacity.

Run Python maintenance or diagnostic scripts inside the Docassemble container as
`www-data`, using `docker exec --user www-data`. Importing
`docassemble.webapp.server` runs startup code that rebuilds generated Playground
module packages. Running that import as root can leave root-owned directories
that later prevent normal worker startup from copying modules.

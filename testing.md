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

The output contains editor and live interview screenshots plus `results.json`.
Template insertion and reference checks are scoped to the active YAML file;
advanced templates remain editable in YAML mode.

## Classroom editor load testing

The bounded localhost harness is [scripts/editor_classroom_stress.py](scripts/editor_classroom_stress.py), with a loopback-only, eight-second model fixture in [scripts/editor_stress_model.py](scripts/editor_stress_model.py). It creates individual disposable developer accounts and owned projects, exercises debugger/editor traffic and queued AI drafts, records request latency and cgroup resources, and cleans up fixture accounts. It requires private local admin credentials and a correctly configured localhost web/Celery installation; it does not manage server configuration or the fixture process.

See the [six-minute, fifteen-user report](performance/classroom-2026-09-30.md) for exact setup, cleanup, measurements, test limitations, and committed public result artifacts. That run used an unlimited container on a 15.34 GiB host, so it does not establish an 8 GB deployment's document-generation capacity.

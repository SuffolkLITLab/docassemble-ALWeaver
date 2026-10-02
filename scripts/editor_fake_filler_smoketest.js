#!/usr/bin/env node
// Real-server regression: import local interviews into disposable projects.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium, expect } = require('@playwright/test');

const server = (process.env.SERVER_URL || 'http://localhost').replace(
  /\/$/,
  '',
);
const sources =
  process.env.INTERVIEW_ROOT ||
  path.join(process.env.HOME, 'all_interviews/repos');
const output = process.env.SCREENSHOT_DIR || '/tmp/alweaver-fake-filler';
const cases = [
  ['ALAffidavitOfIndigency', 'affidavit.yml'],
  [
    'SecurityDepositDemandLetterForTenantsMovingOut',
    'security_deposit_demand_letter_for_tenants_moving_out.yml',
  ],
];

function lifecycleProbe(action, session) {
  const result = execFileSync(
    'docker',
    [
      'exec',
      '-u',
      'www-data',
      process.env.DOCASSEMBLE_CONTAINER || 'admiring_goldwasser',
      '/usr/share/docassemble/local3.14/bin/python',
      '/tmp/alweaver_runtime_probe.py',
      action,
      session,
    ],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
  );
  return JSON.parse(result.trim().split('\n').at(-1));
}

async function browserChecks(context) {
  const page = await context.newPage();
  await page.goto(`${server}/al/editor`);
  await page.setContent(
    '<button id="fill">Fill sample answers</button><p id="status"></p><iframe title="Test interview" id="frame"></iframe>',
  );
  await page.locator('#frame').evaluate((frame) => {
    frame.srcdoc = `<form id="daform">
      <label>Name <input name="name" value="Keep my answer"></label>
      <input type="hidden" name="secret" value="unchanged">
      <label>Read only <input name="read_only" readonly></label>
      <label>Disabled <input name="disabled" disabled></label>
      <label>Currency <input name="income" class="dacurrency"></label>
      <label>Email <input name="email" type="email" required></label>
      <label>Short answer <input name="short"></label>
      <label>Show details <input id="show" name="show" type="checkbox"></label>
      <div id="conditional" style="display:none"><label>Details <textarea name="details"></textarea></label></div>
      <div class="da-field-checkboxes"><label><input type="checkbox" name="option1">Option one</label><label><input type="checkbox" name="option2">Option two</label><label><input class="danota-checkbox" type="checkbox" name="none">None</label></div>
      <label>Country <select name="country"><option value="">Choose</option><option value="CA">Canada</option><option value="US">United States</option></select></label>
      <label>Upload <input type="file" name="upload" required></label>
      <button type="submit" name="done" value="True">Next</button>
    </form>`;
  });
  const frame = page.frameLocator('#frame');
  await expect(frame.locator('#daform')).toBeVisible();
  await frame.locator('#daform').evaluate((form) => {
    window.daValidationRules = {
      rules: { income: { min: 10, max: 25, step: 1 }, short: { maxlength: 5 } },
    };
    form.querySelector('#show').addEventListener('change', () => {
      form.querySelector('#conditional').style.display = 'block';
    });
    window.submissions = 0;
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      window.submissions += 1;
      window.submitter = event.submitter.value;
      // Model Docassemble's AJAX screen replacement.
      document.body.innerHTML =
        '<form id="daform"><label>City <input name="city"></label><button type="submit">Next</button></form>';
    });
  });
  await page.addScriptTag({
    path: path.join(
      __dirname,
      '../docassemble/ALWeaver/data/static/faker_en_us.js',
    ),
  });
  await page.addScriptTag({
    path: path.join(
      __dirname,
      '../docassemble/ALWeaver/data/static/editor_fake_filler.js',
    ),
  });
  await page.evaluate(() => {
    window.ALWeaverFaker.seed(20261002);
    window.controller = window.ALWeaverFakeFiller.createController(
      document.querySelector('#frame'),
      document.querySelector('#fill'),
      (message) => {
        document.querySelector('#status').textContent = message;
      },
    );
  });
  const button = page.locator('#fill');
  await button.click();
  await expect(button).toHaveText('Continue');
  await expect(frame.locator('[name=name]')).toHaveValue('Keep my answer');
  await expect(frame.locator('[name=secret]')).toHaveValue('unchanged');
  await expect(frame.locator('[name=read_only]')).toHaveValue('');
  await expect(frame.locator('[name=disabled]')).toHaveValue('');
  const amount = Number(await frame.locator('[name=income]').inputValue());
  assert.ok(amount >= 10 && amount <= 25 && Number.isInteger(amount));
  assert.equal((await frame.locator('[name=short]').inputValue()).length, 5);
  await expect(frame.locator('[name=details]')).not.toHaveValue('');
  await expect(frame.locator('[name=option1]')).toBeChecked();
  await expect(frame.locator('[name=option2]')).not.toBeChecked();
  await expect(frame.locator('[name=none]')).not.toBeChecked();
  await expect(frame.locator('[name=country]')).toHaveValue('US');
  await expect(frame.locator('[name=upload]')).toHaveValue('');
  await expect(page.locator('#status')).toContainText('Choose a file manually');
  await frame.locator('[name=option1]').uncheck();
  await button.click();
  await expect(frame.locator('[name=option1]')).not.toBeChecked();
  assert.equal(
    await frame.locator('body').evaluate(() => window.submissions),
    0,
    'required file validation blocks submission',
  );
  await expect(button).toHaveText('Continue');
  await frame.locator('[name=upload]').evaluate((field) => {
    field.required = false;
  });
  await frame.locator('[name=email]').fill('');
  await button.click();
  await expect(frame.locator('[name=email]')).toHaveValue('');
  assert.equal(
    await frame.locator('body').evaluate(() => window.submissions),
    0,
  );
  await frame.locator('[name=email]').fill('invalid');
  await button.click();
  assert.equal(
    await frame.locator('body').evaluate(() => window.submissions),
    0,
    'invalid answers are preserved and normal validation runs',
  );
  await frame.locator('[name=email]').fill('alex@example.com');
  await button.click();
  await expect(button).toHaveText('Fill sample answers');
  assert.equal(
    await frame.locator('body').evaluate(() => window.submitter),
    'True',
  );
  await button.click();
  await expect(frame.locator('[name=city]')).not.toHaveValue('');
  // Standard address widgets: preserve supplied parts even when ZIP precedes
  // state, map list-index aliases to each person, and sample blank states broadly.
  const generatedStreets = new Set();
  const generatedStates = new Set();
  for (let index = 0; index < 40; index += 1) {
    await frame.locator('body').evaluate((body, index) => {
      const parts = ['address', 'unit', 'city', 'zip', 'state', 'country'];
      body.innerHTML =
        `<div id="sought_variable" data-variable="${btoa(`users[${index}].address.address`)}"></div><form id="daform">` +
        parts
          .map(
            (part) =>
              `<label>${part}<input id="part-${part}" name="${btoa(`users[i].address.${part}`)}" value="${index === 0 && part === 'state' ? 'CA' : index === 0 && part === 'zip' ? '90012' : ''}"></label>`,
          )
          .join('') +
        '<button type="submit">Next</button></form>';
    }, index);
    await expect(button).toHaveText('Fill sample answers');
    await button.click();
    generatedStreets.add(await frame.locator('#part-address').inputValue());
    const state = await frame.locator('#part-state').inputValue();
    generatedStates.add(state);
    await expect(frame.locator('#part-country')).toHaveValue('US');
    if (index === 0) {
      assert.equal(state, 'CA');
      await expect(frame.locator('#part-zip')).toHaveValue('90012');
    } else await expect(frame.locator('#part-zip')).toHaveValue(/^\d{5}$/);
  }
  assert.equal(
    generatedStreets.size,
    40,
    'different list items get distinct addresses',
  );
  assert.ok(
    generatedStates.size > 15,
    'blank standard addresses vary nationwide',
  );
  await frame.locator('#daform').evaluate((form) => form.remove());
  await expect(button).toBeDisabled();
  await page.evaluate(() => window.controller.dispose());
  await page.close();
  console.log(
    'PASS browser controls: preserved answers, conditional fields, validation, files, constraints, submitter values, AJAX reset',
  );
}

async function debuggerChecks(context) {
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  await page.goto(`${server}/al/editor`);
  await page.setContent('<main id="debugger"></main>');
  await page.addStyleTag({
    path: path.join(
      __dirname,
      '../docassemble/ALWeaver/data/static/editor.css',
    ),
  });
  for (const file of [
    'faker_en_us.js',
    'editor_fake_filler.js',
    'editor_runtime_inspector.js',
  ]) {
    await page.addScriptTag({
      path: path.join(__dirname, '../docassemble/ALWeaver/data/static', file),
    });
  }
  await page.evaluate(() => {
    window.debuggerRequests = [];
    const answers = {
      answer: 'Visible immediately',
      false_answer: false,
      zero_answer: 0,
      empty_answer: '',
      null_answer: null,
      nested: { name: 'Pat', nested: [true, false, null, 'true', 'null'] },
      list: [1, 2],
      unsafe: '<img src=x onerror="window.unexpectedMarkup=true">',
      benefits: {
        _class: 'docassemble.base.util.DADict',
        elements: { SNAP: true, SSI: false, '<b>TAFDC</b>': true },
        auto_gather: true,
        minimum_number: null,
      },
      all_unchecked: { SNAP: false, SSI: false },
      mixed_dict: { SNAP: true, amount: 42 },
    };
    const config = {
      AL_DEFAULT_STATE: 'CA',
      feedback_form: 'feedback.yml',
      multi_user: true,
      nav: {},
      speak_text: false,
      package_version_number: '1.0',
      alkiln_trigger_html: '<div>Trigger</div>',
      alkiln_proxy_html: '<div>Proxy</div>',
      al_session_store_default_filename: 'answers.json',
      al_sessions_interview_title: 'Saved interview',
      al_terms_of_use: 'Terms of use',
      al_name_suffixes: ['Jr.', 'Sr.'],
      al_name_titles: ['Mr.', 'Ms.'],
      List: null,
      Optional: null,
    };
    window.inspector = window.ALWeaverRuntimeInspector.createRuntimeInspector({
      getContext: () => ({ project: 'fixture', filename: 'fixture.yml' }),
      api: {
        get: async (path) => {
          window.debuggerRequests.push(path);
          return {
            data: {
              question: {
                questionName: 'fixture',
                questionText: 'Fixture screen',
              },
              variables: {
                ...answers,
                ...config,
                ...(path.includes('include_internal=true')
                  ? { _internal: { steps: 1 } }
                  : {}),
              },
            },
          };
        },
      },
    });
    window.inspector.setSession({
      weaver_session_id: 'fixture',
      target_url: 'about:blank',
    });
    window.inspector.render(document.querySelector('#debugger'));
  });
  await expect(page.locator('#runtime-variable-list')).toContainText(
    'Visible immediately',
  );
  const list = page.locator('#runtime-variable-list');
  await expect(list.locator('div.editor-runtime-variable-simple')).toHaveCount(
    6,
  );
  await expect(list.locator('details.editor-runtime-variable')).toHaveCount(5);
  const values = await list
    .locator('div.editor-runtime-variable-simple > pre')
    .allTextContents();
  for (const text of ['Visible immediately', 'False', '0', '\"\"', 'None'])
    assert.ok(values.includes(text));
  await expect(list.locator('img')).toHaveCount(0);
  await expect(list).not.toContainText('feedback_form');
  await expect(list).not.toContainText('alkiln_trigger_html');
  for (const name of [
    'List',
    'Optional',
    'al_session_store_default_filename',
    'al_sessions_interview_title',
    'al_terms_of_use',
    'al_name_suffixes',
    'al_name_titles',
  ]) {
    await expect(list.locator('[data-variable="' + name + '"]')).toHaveCount(0);
    await expect(
      list.locator('.editor-runtime-variable-simple > div', {
        hasText: new RegExp('^' + name + ' ·'),
      }),
    ).toHaveCount(0);
  }
  await expect(page.locator('#runtime-variable-count')).toHaveText('11');
  const benefits = list.locator('[data-variable="benefits"]');
  await expect(benefits.locator('summary')).toHaveText(
    'benefits · checkboxes · 2 checked',
  );
  await expect(
    benefits.locator('.editor-runtime-checkbox-preview'),
  ).toBeHidden();
  await benefits.locator('summary').click();
  await expect(
    benefits.locator('.editor-runtime-checkbox-preview li'),
  ).toHaveText(['SNAP', 'SSI', '<b>TAFDC</b>']);
  await expect(benefits.locator('b')).toHaveCount(0);
  await expect(benefits.locator('pre')).toHaveCount(0);
  for (const [choice, checked] of [
    ['SNAP', true],
    ['SSI', false],
    ['<b>TAFDC</b>', true],
  ]) {
    const checkbox = benefits.getByRole('checkbox', {
      name: choice,
      exact: true,
    });
    await expect(checkbox).toBeDisabled();
    if (checked) await expect(checkbox).toBeChecked();
    else await expect(checkbox).not.toBeChecked();
  }
  assert.ok(
    (await benefits.locator('.editor-runtime-checkbox-preview').boundingBox())
      .height <= 80,
    'three choices fit in a compact list',
  );
  const unchecked = list.locator('[data-variable="all_unchecked"]');
  await expect(unchecked.locator('summary')).toHaveText(
    'all_unchecked · checkboxes · 0 checked',
  );
  await unchecked.locator('summary').click();
  await expect(unchecked.locator('li')).toHaveText(['SNAP', 'SSI']);
  await expect(unchecked.locator('input:checked')).toHaveCount(0);
  await expect(unchecked.locator('pre')).toHaveCount(0);
  await expect(list.locator('[data-variable="mixed_dict"] summary')).toHaveText(
    'mixed_dict · dict',
  );
  const nested = list
    .locator('details')
    .filter({ has: page.locator('summary', { hasText: /^nested/ }) });
  await expect(nested.locator('pre')).toBeHidden();
  await nested.locator('summary').click();
  await page.evaluate(() => window.inspector.refreshAll());
  await expect(nested.locator('pre')).toBeVisible();
  await expect(nested.locator('pre')).toContainText(
    'True,\n    False,\n    None,\n    "true",\n    "null"',
  );
  await expect(
    benefits.locator('.editor-runtime-checkbox-preview'),
  ).toBeVisible();
  await page.evaluate(() => {
    window.savedFrame = document.querySelector('#runtime-interview-frame');
    window.savedFrame.contentWindow.testMarker = 'same interview';
  });
  const initialWidth = (
    await page.locator('#runtime-interview-frame').boundingBox()
  ).width;
  await page.locator('#runtime-toggle-sidebar').click();
  await expect(page.locator('#runtime-sidebar')).toBeHidden();
  await expect(page.locator('#runtime-toggle-sidebar')).toHaveAttribute(
    'aria-expanded',
    'false',
  );
  assert.ok(
    (await page.locator('#runtime-interview-frame').boundingBox()).width >
      initialWidth,
  );
  await page.evaluate(() => window.inspector.refreshAll());
  await expect(page.locator('#runtime-sidebar')).toBeHidden();
  await page.locator('#runtime-toggle-sidebar').click();
  assert.equal(
    await page.evaluate(
      () =>
        window.savedFrame ===
          document.querySelector('#runtime-interview-frame') &&
        window.savedFrame.contentWindow.testMarker === 'same interview',
    ),
    true,
  );
  await expect(page.locator('#runtime-sidebar')).toBeVisible();
  await page.locator('#runtime-include-internal').check();
  await expect(list).toContainText('feedback_form');
  await expect(list).toContainText('alkiln_proxy_html');
  await expect(list).toContainText('_internal');
  for (const name of [
    'List',
    'Optional',
    'al_session_store_default_filename',
    'al_sessions_interview_title',
    'al_terms_of_use',
    'al_name_suffixes',
    'al_name_titles',
  ])
    await expect(list).toContainText(name);
  await expect(page.locator('#runtime-variable-count')).toHaveText('27');
  await page.locator('#runtime-variable-search').fill('feedback');
  await expect(page.locator('#runtime-variable-count')).toHaveText('1');
  await page.locator('#runtime-include-internal').uncheck();
  await expect(list).toHaveText('No matching variables.');
  await expect(page.locator('#runtime-variable-count')).toHaveText('0');
  await page.locator('#runtime-variable-search').fill('answer');
  await expect(page.locator('#runtime-variable-count')).toHaveText('5');
  await expect(list).toContainText('Visible immediately');
  await page.setViewportSize({ width: 600, height: 900 });
  await page.locator('#runtime-toggle-sidebar').click();
  await expect(page.locator('#runtime-sidebar')).toBeHidden();
  await expect(page.locator('#runtime-toggle-sidebar')).toBeVisible();
  assert.deepEqual(errors, []);
  await page.evaluate(() => window.inspector.hide());
  await page.close();
  console.log(
    'PASS debugger controls: collapse preserves iframe, internal filtering/search/counts, inline scalar values, safe text, persistent nested expansion, mobile collapse',
  );
}

async function noEndpointCheck(page, post) {
  const created = await post('new-project', {
    project_name: `NoEndpoint${Date.now()}`,
    create_test: false,
  });
  try {
    await post('file/new', {
      project: created.project,
      filename: 'include.yml',
      content: 'question: An optional question\nfields:\n  - Answer: answer\n',
    });
    await page.goto(
      `${server}/al/editor/projects/${created.project}/interviews/include.yml/debug`,
    );
    const response = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/runtime/sessions') &&
        response.request().method() === 'POST',
    );
    await page
      .getByRole('button', { name: 'Start debugging', exact: true })
      .click();
    const failed = await response;
    assert.equal(failed.status(), 422);
    assert.equal((await failed.json()).error.code, 'runtime_no_endpoint');
    await expect(page.locator('#runtime-status')).toContainText('include.yml');
    await expect(page.locator('#runtime-status')).toContainText(
      'main interview',
    );
    await expect(page.locator('#runtime-status')).toHaveClass(/alert-danger/);
    await expect(
      page.getByRole('button', { name: 'Start debugging', exact: true }),
    ).toBeEnabled();
    await expect(page.locator('#runtime-interview-frame')).toHaveCount(0);
    console.log(
      'PASS missing endpoint: clear include-file guidance, visible error, retry enabled',
    );
  } finally {
    await post('project/delete', { project: created.project });
  }
}

async function digitIdentifierCheck(page, post) {
  const created = await post('new-project', {
    project_name: `DigitIdentifier${Date.now()}`,
    create_test: false,
  });
  let runtime;
  let probeSession;
  try {
    await post('file/new', {
      project: created.project,
      filename: 'digits.yml',
      content: `
include:
  - docassemble.AssemblyLine:al_package.yml
---
objects:
  - users: ALPeopleList.using(there_are_any=True)
---
mandatory: True
code: |
  users[0].last_4_of_social
  selected_benefits
  digits_done
---
id: last four digits
question: Last four digits
fields:
  - Last 4 digits of social Security Number: users[i].last_4_of_social
    minlength: 4
    maxlength: 4
    validate: |
      lambda y: y.isdigit() or validation_error('Enter only numbers')
    required: False
---
question: Select benefits
fields:
  - Benefits: selected_benefits
    datatype: checkboxes
    choices:
      - SNAP
      - SSI
      - TAFDC
---
event: digits_done
question: Digits accepted
`,
    });
    await page.goto(
      `${server}/al/editor/projects/${created.project}/interviews/digits.yml/debug`,
    );
    const response = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/runtime/sessions') &&
        response.request().method() === 'POST',
    );
    await page
      .getByRole('button', { name: 'Start debugging', exact: true })
      .click();
    const started = await response;
    assert.equal(started.status(), 201);
    runtime = (await started.json()).data.weaver_session_id;
    if (process.env.CHECK_RUNTIME_DATABASE) {
      probeSession = runtime;
      assert.equal(lifecycleProbe('capture', runtime).database, true);
      assert.equal(lifecycleProbe('normal', runtime).normal_database, true);
    }
    const frame = page.frameLocator('#runtime-interview-frame');
    await expect(frame.locator('#daMainQuestion')).toHaveText(
      'Last four digits',
    );
    const input = frame.getByRole('textbox', {
      name: 'Last 4 digits of social Security Number',
    });
    await expect(input).toHaveAttribute('type', 'text');
    await page.locator('#runtime-fill-samples').click();
    await expect(input).toHaveValue(/^\d{4}$/);
    await page.locator('#runtime-fill-samples').click();
    await expect(frame.locator('#daMainQuestion')).toHaveText(
      'Select benefits',
    );
    const beforeReload = await page.request.get(
      `${server}/al/editor/api/runtime/sessions/${runtime}`,
    );
    assert.equal(beforeReload.status(), 200);
    const expiry = (await beforeReload.json()).data.expires_at;
    let extraStarts = 0;
    const countStarts = (request) => {
      if (
        request.method() === 'POST' &&
        request.url().endsWith('/api/runtime/sessions')
      )
        extraStarts += 1;
    };
    page.on('request', countStarts);
    await page.reload();
    await expect(frame.locator('#daMainQuestion')).toHaveText(
      'Select benefits',
    );
    const resumed = await page.request.get(
      `${server}/al/editor/api/runtime/sessions?project=${created.project}&filename=digits.yml`,
    );
    const active = (await resumed.json()).data.session;
    assert.equal(
      active.weaver_session_id,
      runtime,
      'reload reconnects to the same session',
    );
    assert.equal(
      active.expires_at,
      expiry,
      'reload and polling do not extend the idle deadline',
    );
    assert.equal(extraStarts, 0, 'reload never creates an interview');
    page.off('request', countStarts);
    await page.locator('#runtime-fill-samples').click();
    // Choose a known combination to verify the DADict preview against the form.
    for (const [choice, checked] of [
      ['SNAP', true],
      ['SSI', false],
      ['TAFDC', true],
    ]) {
      const input = frame.locator(
        'input[data-cbvalue="' +
          Buffer.from(choice).toString('base64').replace(/=+$/, '') +
          '"]',
      );
      if ((await input.isChecked()) !== checked) {
        const id = await input.getAttribute('id');
        await frame.locator('label[for="' + id + '"]').click();
      }
      assert.equal(await input.isChecked(), checked);
    }
    await page.locator('#runtime-fill-samples').click();
    await expect(frame.locator('#daMainQuestion')).toHaveText(
      'Digits accepted',
    );
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    const benefits = page.locator(
      '#runtime-variable-list [data-variable="selected_benefits"]',
    );
    await expect(benefits.locator('summary')).toHaveText(
      'selected_benefits · checkboxes · 2 checked',
    );
    await benefits.locator('summary').click();
    await expect(
      benefits.locator('.editor-runtime-checkbox-preview li'),
    ).toHaveText(['SNAP', 'SSI', 'TAFDC']);
    await expect(
      benefits.getByRole('checkbox', { name: 'SNAP', exact: true }),
    ).toBeChecked();
    await expect(
      benefits.getByRole('checkbox', { name: 'SSI', exact: true }),
    ).not.toBeChecked();
    await expect(
      benefits.getByRole('checkbox', { name: 'TAFDC', exact: true }),
    ).toBeChecked();
    await expect(benefits.locator('pre')).toHaveCount(0);
    console.log(
      'PASS live fixtures: four-digit text identifier passes Python validation; checkbox DADict renders a compact list with correct checked states',
    );
    await page.getByRole('button', { name: 'End', exact: true }).click();
    await expect(
      page.getByRole('button', { name: 'Start debugging', exact: true }),
    ).toBeVisible();
    await expect(page.locator('#runtime-interview-frame')).toHaveCount(0);
    const ended = await page.request.get(
      `${server}/al/editor/api/runtime/sessions/${runtime}`,
    );
    assert.equal(ended.status(), 404);
    if (process.env.CHECK_RUNTIME_DATABASE) {
      const state = lifecycleProbe('state', runtime);
      assert.equal(
        state.database,
        false,
        'End deletes the underlying Docassemble data',
      );
      assert.equal(state.tracked, false);
      assert.equal(state.deadline_index, false);
      assert.equal(
        state.normal_database,
        true,
        'an ordinary interview with the same filename survives',
      );
    }
    runtime = undefined;
    console.log(
      'PASS lifecycle: refresh keeps the same session, current screen and deadline; End removes it',
    );
    if (process.env.CHECK_RUNTIME_DATABASE) {
      const next = await post('runtime/sessions', {
        project: created.project,
        filename: 'digits.yml',
      });
      runtime = next.weaver_session_id;
      lifecycleProbe('capture', runtime);
      await page.goto(`${server}/al/editor`);
      lifecycleProbe('age', runtime);
      lifecycleProbe('worker', runtime);
      let state;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        state = lifecycleProbe('state', runtime);
        if (!state.database && !state.tracked) break;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
      assert.equal(
        state.database,
        false,
        'worker deletes an idle interview without browser polling',
      );
      assert.equal(state.tracked, false);
      assert.equal(state.deadline_index, false);
      assert.equal(lifecycleProbe('state', probeSession).normal_database, true);
      runtime = undefined;
      console.log(
        'PASS database lifecycle: End and idle worker cleanup remove database/Redis records; ordinary session survives',
      );
      const open = await post('runtime/sessions', {
        project: created.project,
        filename: 'digits.yml',
      });
      runtime = open.weaver_session_id;
      lifecycleProbe('capture', runtime);
      await page.goto(
        `${server}/al/editor/projects/${created.project}/interviews/digits.yml/debug`,
      );
      await expect(frame.locator('#daMainQuestion')).toHaveText(
        'Last four digits',
      );
      lifecycleProbe('age', runtime);
      await page.getByRole('button', { name: 'Refresh', exact: true }).click();
      await expect(page.locator('#runtime-interview-frame')).toHaveCount(0);
      await expect(
        page.getByRole('button', { name: 'Start debugging', exact: true }),
      ).toBeEnabled();
      await expect(page.locator('#runtime-status')).toContainText('30 minutes');
      assert.equal(lifecycleProbe('state', runtime).database, false);
      runtime = undefined;
      console.log(
        'PASS idle browser: expiry closes the iframe and returns to Start debugging',
      );
    }
  } finally {
    if (probeSession) lifecycleProbe('cleanup-normal', probeSession);
    if (runtime) {
      const csrf = await page.evaluate(
        () => window.__EDITOR_BOOTSTRAP__.csrfToken,
      );
      const response = await page.request.delete(
        `${server}/al/editor/api/runtime/sessions/${runtime}`,
        { headers: { 'X-CSRFToken': csrf } },
      );
      assert.ok(response.ok());
    }
    await post('project/delete', { project: created.project });
  }
}

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    ...(process.env.STORAGE_STATE
      ? { storageState: process.env.STORAGE_STATE }
      : {}),
  });
  const page = await context.newPage();
  const errors = [];
  const serverErrors = [];
  const snapshotErrors = [];
  const results = [];
  page.on('pageerror', (error) => {
    const detail = { message: String(error), stack: error.stack };
    // Known localhost failures in Docassemble's chat/Maps initialization.
    // Neither stack contains Weaver or the filler. Keep them in the report.
    if (
      (detail.message === 'ReferenceError: google is not defined' &&
        /at Combobox\.<anonymous>/.test(detail.stack)) ||
      (detail.message ===
        "TypeError: Cannot read properties of null (reading 'length')" &&
        /at Object.daChatLogCallback/.test(detail.stack))
    ) {
      serverErrors.push(detail);
    } else errors.push(detail);
  });
  page.on('response', (response) => {
    if (
      response.url().includes('/api/runtime/sessions/') &&
      response.url().endsWith('/snapshot') &&
      response.status() >= 400 &&
      response.status() !== 404
    )
      snapshotErrors.push({
        status: response.status(),
        message:
          'Existing runtime snapshot API failure; filling and submission are tested independently.',
      });
  });
  let csrf;
  let project;
  let runtime;
  async function post(endpoint, data) {
    const response = await context.request.post(
      `${server}/al/editor/api/${endpoint}`,
      {
        headers: { 'X-CSRFToken': csrf },
        data,
      },
    );
    const payload = await response.json();
    assert.ok(response.ok() && payload.success, JSON.stringify(payload));
    return payload.data;
  }
  async function cleanup() {
    if (runtime) {
      const response = await context.request.delete(
        `${server}/al/editor/api/runtime/sessions/${runtime}`,
        {
          headers: { 'X-CSRFToken': csrf },
        },
      );
      assert.ok(response.ok(), 'release test session');
      runtime = null;
    }
    if (project) {
      await post('project/delete', { project });
      project = null;
    }
  }
  try {
    await page.goto(`${server}/al/editor`);
    if (page.url().includes('sign-in')) {
      assert.ok(
        process.env.EDITOR_EMAIL && process.env.EDITOR_PASSWORD,
        'Set credentials or STORAGE_STATE',
      );
      await page.locator('input[type=email]').fill(process.env.EDITOR_EMAIL);
      await page
        .locator('input[type=password]')
        .fill(process.env.EDITOR_PASSWORD);
      await page.getByRole('button', { name: /sign in/i }).click();
      await page.waitForURL(`${server}/al/editor`);
    }
    csrf = await page.evaluate(() => window.__EDITOR_BOOTSTRAP__.csrfToken);
    await browserChecks(context);
    await debuggerChecks(context);
    await noEndpointCheck(page, post);
    await digitIdentifierCheck(page, post);
    for (const [pkg, entry] of cases) {
      if (process.env.INTERVIEW_CASE && pkg !== process.env.INTERVIEW_CASE)
        continue;
      const root = path.join(
        sources,
        `docassemble-${pkg}`,
        'docassemble',
        pkg,
        'data',
      );
      assert.ok(fs.existsSync(root), root);
      const created = await post('new-project', {
        project_name: `FakeFiller${Date.now()}`,
        create_test: false,
      });
      project = created.project;
      assert.ok(project, JSON.stringify(created));
      for (const filename of fs
        .readdirSync(path.join(root, 'questions'))
        .filter((name) => /\.ya?ml$/.test(name))) {
        await post('file/new', {
          project,
          filename,
          content: fs.readFileSync(
            path.join(root, 'questions', filename),
            'utf8',
          ),
        });
      }
      // Relative attachment paths must resolve just as they do in the source package.
      for (const filename of fs
        .readdirSync(path.join(root, 'templates'))
        .filter((name) => /\.(pdf|docx)$/.test(name))) {
        const response = await context.request.post(
          `${server}/al/editor/api/section-file/upload`,
          {
            headers: { 'X-CSRFToken': csrf },
            multipart: {
              project,
              section: 'templates',
              files: {
                name: filename,
                mimeType: 'application/octet-stream',
                buffer: fs.readFileSync(path.join(root, 'templates', filename)),
              },
            },
          },
        );
        assert.ok(response.ok(), await response.text());
      }
      await page.goto(
        `${server}/al/editor/projects/${project}/interviews/${entry}/debug`,
      );
      const startResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith('/api/runtime/sessions') &&
          response.request().method() === 'POST',
      );
      await page
        .getByRole('button', { name: 'Start debugging', exact: true })
        .click();
      runtime = (await (await startResponse).json()).data.weaver_session_id;
      const frame = page.frameLocator('#runtime-interview-frame');
      const button = page.locator('#runtime-fill-samples');
      await expect(button).toBeEnabled();
      const screens = [];
      let addresses = 0;
      const seenAddresses = new Set();
      let currencies = 0;
      for (let step = 0; step < 30; step += 1) {
        await expect(frame.locator('#daMainQuestion')).toBeVisible();
        const title = (
          await frame.locator('#daMainQuestion').textContent()
        ).trim();
        console.log(`SCREEN ${pkg}: ${title}`);
        if (/preview|review, download|documents are almost ready/i.test(title))
          break;
        await expect(button).toHaveText('Fill sample answers');
        const buttonBounds = await button.boundingBox();
        const form = frame.locator('#daform');
        const tracker = await form.locator('[name="_tracker"]').inputValue();
        const prefilledStates = await form.evaluate((form) =>
          Object.fromEntries(
            [...form.querySelectorAll('input,select')]
              .filter((field) => {
                try {
                  return (
                    /\.address\.state$/.test(atob(field.name)) && field.value
                  );
                } catch {
                  return false;
                }
              })
              .map((field) => [field.name, field.value]),
          ),
        );
        await button.click();
        await expect(button).toHaveText('Continue');
        assert.deepEqual(
          await button.boundingBox(),
          buttonBounds,
          'fill/continue keeps the button size and position',
        );
        // First click fills without submitting or replacing the screen.
        assert.equal(
          await form.locator('[name="_tracker"]').inputValue(),
          tracker,
        );
        const answers = await form.evaluate((form) =>
          [...form.querySelectorAll('input,textarea,select')]
            .filter(
              (field) => field.type !== 'hidden' || !field.name.startsWith('_'),
            )
            .map((field) => ({
              name: field.name || field.id,
              value: field.value,
              currency: field.classList.contains('dacurrency'),
            })),
        );
        for (const answer of answers) {
          if (answer.currency && answer.value) {
            assert.match(answer.value, /^\d+(\.\d+)?$/);
            currencies += 1;
          }
          let variable = '';
          try {
            variable = Buffer.from(answer.name, 'base64').toString();
          } catch {}
          if (/\.address\.address$/.test(variable)) {
            assert.match(answer.value, /^\d+ .+/);
            if (!seenAddresses.has(variable)) addresses += 1;
            seenAddresses.add(variable);
          }
          if (/\.address\.city$/.test(variable))
            assert.ok(answer.value && !/lorem ipsum/i.test(answer.value));
          if (/\.address\.zip$/.test(variable))
            assert.match(answer.value, /^\d{5}$/);
          if (/\.address\.state$/.test(variable))
            assert.equal(
              answer.value,
              prefilledStates[answer.name] || answer.value,
            );
          if (/phone|mobile/.test(variable) && answer.value)
            assert.match(answer.value, /^\d{10}$/);
        }
        screens.push({ title, answers });
        if (/address|fees do you|deposit/i.test(title))
          await page.screenshot({
            path: path.join(output, `${pkg}-${step}.png`),
          });
        await button.click();
        await expect(button).toHaveText('Fill sample answers', {
          timeout: 30000,
        });
        await expect(
          frame.locator('#daform [name="_tracker"]'),
        ).not.toHaveValue(tracker, { timeout: 30000 });
        assert.deepEqual(
          await button.boundingBox(),
          buttonBounds,
          'the next screen keeps the button under the pointer',
        );
      }
      assert.ok(addresses > 0, `${pkg}: real address fields tested`);
      assert.ok(currencies > 0, `${pkg}: real currency fields tested`);
      results.push({
        package: pkg,
        source: root,
        screens,
        addresses,
        currencies,
      });
      console.log(
        `PASS ${pkg}: ${screens.length} screens, ${addresses} addresses, ${currencies} currency fields`,
      );
      await cleanup();
    }
    assert.deepEqual(errors, []);
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png') });
    const interview = page
      .frames()
      .find((frame) => frame.url().includes('/interview?'));
    if (interview) {
      console.error(
        await interview
          .locator('#daform')
          .innerText()
          .catch(() => 'No form'),
      );
      fs.writeFileSync(
        path.join(output, 'failure.html'),
        await interview.content(),
      );
    }
    throw error;
  } finally {
    fs.writeFileSync(
      path.join(output, 'results.json'),
      JSON.stringify(
        { results, errors, serverErrors, snapshotErrors },
        null,
        2,
      ),
    );
    await cleanup();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

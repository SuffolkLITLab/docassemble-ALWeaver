#!/usr/bin/env node
// Live localhost regression and screenshots for #1195. The only server writes
// are to a disposable project, removed in finally. See testing.md for auth.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { chromium } = require('playwright');

const server = process.env.SERVER_URL || 'http://localhost';
const output = process.env.SCREENSHOT_DIR || '/tmp/weaver-1195-evidence';
const source = `# Keep this author comment exactly.
id: income
question: |
  Hello \${ users[0].name.first }
subquestion: |
  😀 Your income is **\${ currency(monthly_income) }**.
  Repeated: \${ currency(monthly_income) }.
  Filtered: \${ monthly_income | h }.
fields:
  - Monthly income: monthly_income
    datatype: currency
---
id: income_help
template: income_help
subject: |
  About \${ monthly_income }
content: |
  Your income is \${ currency(monthly_income) }.
---
# Unrelated block and formatting must survive.
id: untouched
code: |
  untouched = 'authored value'  # preserve this
`;

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {}),
  });
  const context = await browser.newContext({
    storageState: process.env.STORAGE_STATE,
    viewport: { width: 1440, height: 1100 },
    hasTouch: true,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  let project;
  async function post(endpoint, data) {
    const csrf = await page.evaluate(
      () => window.__EDITOR_BOOTSTRAP__?.csrfToken,
    );
    assert.ok(csrf, 'An authenticated developer session is required');
    const response = await context.request.post(
      server + '/al/editor' + endpoint,
      { data, headers: { 'X-CSRF-Token': csrf } },
    );
    const payload = await response.json();
    assert.equal(payload.success, true, JSON.stringify(payload));
    return payload.data;
  }
  async function savedSource() {
    const response = await context.request.get(
      server +
        '/al/editor/api/file?project=' +
        encodeURIComponent(project) +
        '&filename=context.yml',
    );
    return (await response.json()).data.raw_yaml;
  }
  async function point(name, needle, last = false) {
    const control = page.getByRole('textbox', { name, exact: true });
    await control.scrollIntoViewIfNeeded();
    return control.evaluate(
      (element, { needle, last }) => {
        const text = element.textContent;
        let offset =
          (last ? text.lastIndexOf(needle) : text.indexOf(needle)) + 4;
        if (offset < 4) throw new Error('Missing token: ' + needle);
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          if (offset < node.length) {
            const range = document.createRange();
            range.setStart(node, offset);
            range.setEnd(node, offset + 1);
            const rect = range.getBoundingClientRect();
            return { x: rect.left + 1, y: rect.top + rect.height / 2 };
          }
          offset -= node.length;
        }
        throw new Error('Token position unavailable');
      },
      { needle, last },
    );
  }
  async function open(name, needle, last = false, touch = false) {
    const p = await point(name, needle, last);
    if (touch) await page.touchscreen.tap(p.x, p.y);
    else await page.mouse.move(p.x, p.y);
    const action = page.getByRole('button', {
      name: 'Edit expression',
      exact: true,
    });
    await action.waitFor();
    if (touch) await action.tap();
    else await action.click();
    await page.waitForFunction(
      () =>
        !document
          .querySelector('.expression-status')
          ?.textContent.includes('Checking'),
    );
    await page.locator('dialog[open]').waitFor();
  }
  async function screenshot(name) {
    await page.screenshot({ path: path.join(output, name + '.png') });
  }
  try {
    await page.goto(server + '/al/editor', { waitUntil: 'networkidle' });
    project = (
      await post('/api/new-project', {
        project_name: 'Mako1195' + Date.now(),
        create_test: false,
      })
    ).project;
    await post('/api/file/new', {
      project,
      filename: 'context.yml',
      content: source,
    });
    const url =
      server +
      '/al/editor/projects/' +
      encodeURIComponent(project) +
      '/interviews/context.yml/blocks/income';
    await page.goto(url, { waitUntil: 'networkidle' });
    await page
      .getByRole('textbox', { name: 'Subquestion', exact: true })
      .waitFor();
    const original = await page.locator('#q-subquestion').inputValue();
    const hover = await point(
      'Subquestion',
      '${ currency(monthly_income) }',
      true,
    );
    await page.mouse.move(hover.x, hover.y);
    await page
      .getByRole('button', { name: 'Edit expression', exact: true })
      .waitFor();
    await screenshot('01-desktop-context-action');
    await open('Subquestion', '${ currency(monthly_income) }', true);
    assert.equal(
      await page.locator('.expression-origin').textContent(),
      'Subquestion',
    );
    await screenshot('02-shared-guided-dialog');
    await page.getByRole('button', { name: 'Python', exact: true }).click();
    await page
      .getByRole('textbox', { name: 'Python expression', exact: true })
      .fill('currency(annual_income)');
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    await page.locator('dialog').waitFor({ state: 'detached' });
    const expected =
      original.slice(0, original.lastIndexOf('currency(monthly_income)')) +
      'currency(annual_income)' +
      original.slice(
        original.lastIndexOf('currency(monthly_income)') +
          'currency(monthly_income)'.length,
      );
    assert.equal(await page.locator('#q-subquestion').inputValue(), expected);
    assert.equal(
      await savedSource(),
      source,
      'Apply must not independently persist',
    );
    const save = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        /\/api\/(file|block)$/.test(new URL(response.url()).pathname),
    );
    await page.locator('.js-save-file-btn:visible').first().click();
    assert.equal((await (await save).json()).success, true);
    const saved = await savedSource();
    assert.equal(
      saved,
      source
        .replace('subquestion: |\n', 'subquestion: |2\n')
        .replace(
          'Repeated: ${ currency(monthly_income) }',
          'Repeated: ${ currency(annual_income) }',
        ),
    );
    await page.reload({ waitUntil: 'networkidle' });
    assert.equal(await page.locator('#q-subquestion').inputValue(), expected);
    await screenshot('03-saved-and-reopened');
    await open('Question', '${ users[0].name.first }');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    for (const [name, width, height] of [
      ['portrait', 768, 1024],
      ['landscape', 1024, 768],
      ['split-view', 390, 700],
    ]) {
      await page.setViewportSize({ width, height });
      await open('Subquestion', '${ currency(annual_income) }', false, true);
      const rect = await page.locator('dialog').boundingBox();
      assert.ok(rect.x >= 0 && rect.x + rect.width <= width);
      await screenshot('04-touch-' + name);
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    }
    await page.setViewportSize({ width: 1440, height: 1100 });
    await open('Subquestion', '${ currency(annual_income) }');
    await page.getByRole('button', { name: 'Python', exact: true }).click();
    await page
      .getByRole('textbox', { name: 'Python expression', exact: true })
      .fill('income +');
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    await page.waitForFunction(
      () =>
        document.querySelector('dialog [role="alert"]').textContent.length > 0,
    );
    await screenshot('05-invalid-expression-retains-draft');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    const filtered = await point('Subquestion', '${ monthly_income | h }');
    await page.mouse.move(filtered.x, filtered.y);
    await page
      .getByRole('button', { name: 'Edit in text', exact: true })
      .waitFor();
    await screenshot('06-filtered-source-fallback');
    await page
      .getByRole('button', { name: 'Edit in text', exact: true })
      .click();
    assert.equal(await page.locator('#q-subquestion').inputValue(), expected);
    await page.goto(url.replace('/blocks/income', '/blocks/income_help'), {
      waitUntil: 'networkidle',
    });
    await open('Subject (disclosure label)', '${ monthly_income }');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await open('Content', '${ currency(monthly_income) }');
    await screenshot('07-shared-text-template-editor');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      path.join(output, 'results.json'),
      JSON.stringify(
        {
          browser: await browser.version(),
          os: `${os.platform()} ${os.release()}`,
          result: 'pass',
          checks: [
            'Question and Subquestion',
            'text template subject and content',
            'second occurrence only',
            'Apply does not save',
            'Save/reopen text and unrelated YAML preservation (existing serializer adds |2 to edited scalar)',
            'Cancel',
            'invalid Python retains draft',
            'filtered fallback',
            'touch emulation portrait/landscape/split view',
          ],
          limitations: [
            'No real iPad, Safari, VoiceOver, or on-screen keyboard verification',
          ],
          errors,
        },
        null,
        2,
      ),
    );
    console.log(
      'PASS localhost Mako interaction, persistence, and screenshots: ' +
        output,
    );
  } finally {
    if (project) await post('/api/project/delete', { project });
    await context.close();
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

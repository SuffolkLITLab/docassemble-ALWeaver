const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const fs = require('node:fs');
const source = `---
id: users there_is_another
question: |
  % if form_filled_by_attorney and who_is_making_petition == "parent":
  Is there another parent making this Petition with your client?
  % elif who_is_making_petition == "parent":
  Is there another parent making this Petition with you?
  % elif form_filled_by_attorney and who_is_making_petition == "interested_party":
  Is anyone else making this Petition with your client?
  % else:
  Is anyone else making this Petition with you?
  % endif
fields:
  - no label: users.there_is_another
    datatype: yesnoradio
`;
(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    storageState: process.env.STORAGE_STATE,
    viewport: { width: 1280, height: 1000 },
    hasTouch: true,
  });
  const page = await context.newPage();
  const base = process.env.SERVER || 'http://localhost';
  let project, csrf;
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  async function post(endpoint, data) {
    const response = await context.request.post(
      base + '/al/editor' + endpoint,
      { data, headers: { 'X-CSRF-Token': csrf } },
    );
    const body = await response.json();
    assert.equal(body.success, true, JSON.stringify(body));
    return body.data;
  }
  async function preview(label) {
    await page.locator('#screen-preview-modal').waitFor({ state: 'visible' });
    const frame = page.frameLocator('#screen-preview-frame');
    await frame
      .locator('input[type="radio"]')
      .first()
      .waitFor({ state: 'attached' });
    assert.equal(await frame.locator('input[type="radio"]').count(), 2);
    assert.equal(await frame.locator('input[type="checkbox"]').count(), 0);
    const yes = frame.locator('label[for="dapv_field_0_0"]');
    const no = frame.locator('label[for="dapv_field_0_1"]');
    assert.equal(await yes.innerText(), 'Yes');
    assert.equal(await no.innerText(), 'No');
    const indicator = await yes.evaluate((el) => ({
      content: getComputedStyle(el, '::before').content,
      radius: getComputedStyle(el, '::before').borderRadius,
    }));
    assert.equal(indicator.content, '\"\"');
    assert.equal(indicator.radius, '50%');
    await yes.tap();
    assert.equal(await frame.locator('#dapv_field_0_0').isChecked(), true);
    await no.tap();
    assert.equal(await frame.locator('#dapv_field_0_1').isChecked(), true);
    assert.equal(await frame.locator('#dapv_field_0_0').isChecked(), false);
    await page.screenshot({ path: '/tmp/weaver-no-label-' + label + '.png' });
    fs.writeFileSync(
      '/tmp/weaver-no-label-' + label + '.html',
      await page.locator('#screen-preview-frame').getAttribute('srcdoc'),
    );
    console.log(label, await frame.locator('.da-field-radio').innerText());
    await page
      .locator('#screen-preview-modal [data-bs-dismiss="modal"]')
      .first()
      .click();
    await page.locator('#screen-preview-modal').waitFor({ state: 'hidden' });
  }
  try {
    await page.goto(base + '/al/editor', { waitUntil: 'networkidle' });
    csrf = await page.evaluate(() => window.__EDITOR_BOOTSTRAP__.csrfToken);
    project = (
      await post('/api/new-project', {
        project_name: 'NoLabel' + Date.now(),
        create_test: false,
      })
    ).project;
    await post('/api/file/new', {
      project,
      filename: 'radio.yml',
      content: source,
    });
    const route =
      base +
      '/al/editor/projects/' +
      encodeURIComponent(project) +
      '/interviews/radio.yml';
    await page.goto(route + '/source', { waitUntil: 'networkidle' });
    assert.equal(
      await page.locator('#back-to-question').innerText(),
      'Edit Is there another parent making this Petition… visually',
    );
    await page.locator('#source-block-actions').tap();
    await page
      .locator(
        '[aria-labelledby="source-block-actions"] [data-action="open-screen-preview"]',
      )
      .tap();
    await preview('source');
    await page.locator('#back-to-question').click();
    const type = await page.locator('[data-field-prop="type"]').inputValue();
    console.log('visual field type:', type);
    await page.locator('#question-preview-tab').click();
    await preview('visual');
    assert.equal(type, 'yesnoradio');
    assert.equal(
      await page.locator('[data-field-prop="label"]').inputValue(),
      'no label',
    );
    await page.locator('.editor-field-required-switch').uncheck();
    const saved = page.waitForResponse(
      (r) => r.url().endsWith('/api/block') && r.request().method() === 'POST',
    );
    await page.locator('.js-save-file-btn:visible').first().click();
    const result = await (await saved).json();
    assert.equal(result.success, true);
    const block = result.data.blocks.find(
      (b) => b.id === 'users there_is_another',
    );
    assert.deepEqual(block.data.fields, [
      {
        'no label': 'users.there_is_another',
        datatype: 'yesnoradio',
        required: false,
      },
    ]);
    assert.match(block.yaml, /% if form_filled_by_attorney/);
    console.log(
      'PASS source and visual previews show usable Yes/No radios; visual save preserves the unlabeled binding and datatype',
    );
    assert.deepEqual(errors, []);
  } catch (error) {
    await page.screenshot({ path: '/tmp/weaver-no-label-failure.png' });
    throw error;
  } finally {
    if (project) await post('/api/project/delete', { project });
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});

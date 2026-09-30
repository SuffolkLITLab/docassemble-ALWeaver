#!/usr/bin/env node
// Real-server regression. Creates and removes its own Playground project.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, expect, request } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;

const server = (process.env.SERVER_URL || 'http://localhost').replace(
  /\/$/,
  '',
);
const output =
  process.env.SCREENSHOT_DIR || '/tmp/alweaver-help-template-screenshots';
const project = `HelpTemplates${Date.now()}`;
const filename = 'help.yml';
const apiHeaders = {
  'X-API-Key': process.env.EDITOR_API_KEY || process.env.ADMIN_API_KEY,
};
const userParams = process.env.EDITOR_USER_ID
  ? { user_id: process.env.EDITOR_USER_ID }
  : {};
const fixture = `# Preserve this file header.
metadata:
  title: Reusable help regression
---
id: order
mandatory: True
code: |
  first_done
  second_done
  final_screen
---
id: first
question: First help screen
subquestion: |
  Original introduction.
continue button field: first_done
---
id: second
question: Second help screen
subquestion: |
  Second introduction.
continue button field: second_done
---
id: plain
# Preserve this author comment.
template: plain_help
content: |
  Plain help without a subject.
language: en # Preserve this custom property.
---
id: final
event: final_screen
question: Help test complete
`;

async function main() {
  assert.ok(apiHeaders['X-API-Key'], 'Set EDITOR_API_KEY or ADMIN_API_KEY');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {}),
  });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 1000 },
    ...(process.env.STORAGE_STATE
      ? { storageState: process.env.STORAGE_STATE }
      : {}),
  });
  const fixtureApi = await request.newContext();
  const page = await context.newPage();
  const errors = [];
  const results = [];
  let created = false;
  let csrf;
  const fileUrl = `${server}/al/editor/projects/${project}/interviews/${filename}`;
  page.on('pageerror', (error) => errors.push(String(error)));
  page.on('dialog', async (dialog) => {
    // Expected validation failures use alerts. Unexpected draft confirmation
    // must fail the test, since this fixture should remain valid throughout.
    if (dialog.type() !== 'alert')
      errors.push(`Unexpected dialog: ${dialog.message()}`);
    await dialog.dismiss();
  });
  function pass(message) {
    results.push(message);
    console.log(`PASS ${message}`);
  }
  async function responseData(response) {
    const payload = await response.json();
    assert.ok(response.ok() && payload.success, JSON.stringify(payload));
    return payload.data;
  }
  async function getFile() {
    return responseData(
      await context.request.get(`${server}/al/editor/api/file`, {
        params: { project, filename },
      }),
    );
  }
  async function post(endpoint, data) {
    return context.request.post(`${server}/al/editor/api/${endpoint}`, {
      headers: { 'X-CSRFToken': csrf },
      data: { project, filename, ...data },
    });
  }
  async function save() {
    const button = page.locator('[data-action="save-file"]:visible').first();
    await expect(button).toBeEnabled();
    const saved = page.waitForResponse(
      (response) =>
        response.url().endsWith('/al/editor/api/block') &&
        response.request().method() === 'POST',
    );
    await button.click();
    await responseData(await saved);
    await expect(button).toBeDisabled();
  }
  async function openInsertion(target = 'q-subquestion') {
    const toolbar = page.locator(`[data-md-toolbar-for="${target}"]`);
    await toolbar
      .getByRole('button', { name: 'More formatting', exact: true })
      .click();
    await toolbar.locator('[data-insert-help-template]').click();
    await expect(page.locator('#template-insert-modal')).toBeVisible();
  }
  async function audit(label) {
    await page.mouse.move(0, 0);
    const auditResult = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    const serious = auditResult.violations.filter((violation) =>
      ['serious', 'critical'].includes(violation.impact),
    );
    assert.deepEqual(
      serious.map((violation) => ({
        id: violation.id,
        nodes: violation.nodes.map((node) => ({
          target: node.target,
          summary: node.failureSummary,
        })),
      })),
      [],
      label,
    );
    pass(`${label}: no serious or critical accessibility violations`);
  }
  try {
    await page.goto(`${server}/al/editor`);
    if (new URL(page.url()).pathname !== '/al/editor') {
      assert.ok(
        process.env.EDITOR_EMAIL && process.env.EDITOR_PASSWORD,
        'Set login credentials or STORAGE_STATE',
      );
      await page.locator('input[type="email"]').fill(process.env.EDITOR_EMAIL);
      await page
        .locator('input[type="password"]')
        .fill(process.env.EDITOR_PASSWORD);
      await page.getByRole('button', { name: /sign in/i }).click();
      await page.waitForURL(`${server}/al/editor`);
    }
    const creation = await fixtureApi.post(`${server}/api/playground/project`, {
      headers: apiHeaders,
      form: { project, ...userParams },
    });
    assert.ok(creation.ok(), await creation.text());
    created = true;
    const upload = await fixtureApi.post(`${server}/api/playground`, {
      headers: apiHeaders,
      multipart: {
        project,
        folder: 'questions',
        restart: '0',
        ...userParams,
        file: {
          name: filename,
          mimeType: 'text/yaml',
          buffer: Buffer.from(fixture),
        },
      },
    });
    assert.ok(upload.ok(), await upload.text());
    await page.goto(`${fileUrl}/blocks/first`);
    await expect(page.locator('#q-subquestion')).toHaveValue(
      'Original introduction.\n',
    );
    csrf = await page.evaluate(() => window.__EDITOR_BOOTSTRAP__.csrfToken);
    assert.ok(csrf);

    // Create at the current cursor while saving a dirty screen first.
    await page.locator('#q-subquestion').fill('Edited introduction.\n');
    await page
      .locator('#q-subquestion')
      .evaluate((input) =>
        input.setSelectionRange(input.value.length, input.value.length),
      );
    await openInsertion();
    await page.locator('#template-insert-name').fill('class');
    await page
      .locator('#template-insert-subject')
      .fill('Learn about addresses');
    await page
      .locator('#template-insert-content')
      .fill('Original **help**.\n\n- First item\n- Second item\n\n${ 2 + 2 }');
    await page.locator('#template-insert-create').click();
    await expect(page.locator('#template-insert-error')).toContainText(
      'valid Python identifier',
    );
    assert.ok(!(await getFile()).raw_yaml.includes('template: class'));
    await page.locator('#template-insert-name').fill('address_help');
    await audit('Help insertion dialog');
    await page.locator('#template-insert-create').click();
    await expect(page.locator('#template-insert-modal')).toBeHidden();
    assert.ok(
      (await page.locator('#q-subquestion').inputValue()).includes(
        '${ collapse_template(address_help) }',
      ),
    );
    assert.ok(
      (await page.locator('#q-subquestion').inputValue()).startsWith(
        'Edited introduction.',
      ),
    );
    await save();
    let model = await getFile();
    assert.equal(
      model.blocks.filter((block) => block.data.template === 'address_help')
        .length,
      1,
    );
    assert.equal(
      model.raw_yaml.split('docassemble.ALToolbox:collapse_template.yml')
        .length - 1,
      1,
    );
    assert.ok(model.raw_yaml.startsWith('# Preserve this file header.'));
    pass(
      'Create and insert preserves dirty question text and adds one dependency',
    );

    await page.goto(`${fileUrl}/blocks/second`);
    await expect(page.locator('#q-title')).toHaveValue('Second help screen');
    await openInsertion();
    await page
      .locator('#template-insert-existing')
      .selectOption('address_help');
    await page.locator('#template-insert-apply').click();
    await expect(page.locator('#template-insert-modal')).toBeHidden();
    assert.ok(
      (await page.locator('#q-subquestion').inputValue()).includes(
        '${ collapse_template(address_help) }',
      ),
    );
    await save();
    model = await getFile();
    assert.equal(
      model.raw_yaml.split('docassemble.ALToolbox:collapse_template.yml')
        .length - 1,
      1,
    );
    assert.equal(
      model.blocks.filter((block) => block.data.template === 'address_help')
        .length,
      1,
    );
    pass(
      'Reuse across two screens keeps one shared template and one dependency',
    );

    // Graphical edits survive anonymous block-ID changes and reload.
    const shared = model.blocks.find(
      (block) => block.data.template === 'address_help',
    );
    await page.goto(`${fileUrl}/blocks/${encodeURIComponent(shared.id)}`);
    await expect(page.locator('#template-name')).toHaveValue('address_help');
    await page
      .locator('#template-content')
      .fill(
        'Updated **shared help**.\n\n- Café\n- Second item\n\nThe computed value is ${ 2 + 2 }.\n\n',
      );
    await save();
    await page.reload();
    await expect(page.locator('#template-content')).toHaveValue(
      'Updated **shared help**.\n\n- Café\n- Second item\n\nThe computed value is ${ 2 + 2 }.\n\n',
    );
    await page.locator('#toggle-edit-mode').click();
    await expect(page.locator('#block-source-editor')).toBeVisible();
    await page
      .getByRole('button', { name: 'Structured view', exact: true })
      .click();
    await expect(page.locator('#template-name')).toHaveValue('address_help');
    await audit('Template editor');
    await page.screenshot({ path: path.join(output, 'template-editor.png') });
    pass(
      'Edit shared help, reload the changed block ID, and switch YAML/form views',
    );

    model = await getFile();
    const updatedShared = model.blocks.find(
      (block) => block.data.template === 'address_help',
    );
    for (const [endpoint, payload, message] of [
      [
        'block',
        {
          block_id: updatedShared.id,
          block_yaml: 'template: renamed_help\ncontent: Renamed\n',
        },
        'Cannot rename',
      ],
      ['block/delete', { block_id: updatedShared.id }, 'Cannot delete'],
      [
        'insert-block',
        { block_yaml: 'template: address_help\ncontent: Duplicate\n' },
        'already defined',
      ],
    ]) {
      const response = await post(endpoint, {
        ...payload,
        expected_revision: model.revision,
      });
      assert.equal(response.status(), 400);
      assert.ok((await response.json()).error.message.includes(message));
    }
    assert.equal((await getFile()).raw_yaml, model.raw_yaml);
    pass(
      'Reject duplicate names and renaming/deleting referenced templates without changing source',
    );

    // Subjectless templates must be editable without losing pending content.
    await page.goto(`${fileUrl}/blocks/plain`);
    await expect(page.locator('#template-content')).toHaveValue(
      'Plain help without a subject.\n',
    );
    await page
      .locator('#template-content')
      .fill('Edited plain help with pending changes.');
    await page
      .getByRole('button', { name: 'Add subject', exact: true })
      .click();
    await expect(page.locator('#template-content')).toHaveValue(
      'Edited plain help with pending changes.',
    );
    await page.locator('#template-subject').fill('Extra details');
    await save();
    model = await getFile();
    assert.ok(model.raw_yaml.includes('# Preserve this author comment.'));
    assert.ok(
      model.raw_yaml.includes('language: en # Preserve this custom property.'),
    );
    pass(
      'Add a subject without dropping edits, author comments, or custom YAML keys',
    );

    // The outline's standalone insertion route and nested help use the same editor.
    await page
      .locator('.editor-outline-insert-btn[data-insert-after-id="plain"]')
      .click();
    await expect(page.locator('#insert-modal')).toBeVisible();
    await page.locator('#insert-modal [data-insert="template"]').click();
    await expect(page.locator('#insert-modal')).toBeHidden();
    await expect(page.locator('#template-name')).toHaveValue(/^help_text_/);
    await page.locator('#template-name').fill('standalone_help');
    await page.locator('#template-subject').fill('Standalone details');
    await page.locator('#template-content').fill('Nested introduction.');
    await save();
    await openInsertion('template-content');
    const choices = await page
      .locator('#template-insert-existing option')
      .evaluateAll((options) => options.map((option) => option.value));
    assert.ok(
      !choices.includes('standalone_help'),
      'A template cannot insert itself',
    );
    await page.locator('#template-insert-existing').selectOption('plain_help');
    await page.locator('#template-insert-apply').click();
    await expect(page.locator('#template-insert-modal')).toBeHidden();
    assert.ok(
      (await page.locator('#template-content').inputValue()).includes(
        '${ collapse_template(plain_help) }',
      ),
    );
    await save();
    await page.reload();
    assert.ok(
      (await page.locator('#template-content').inputValue()).includes(
        '${ collapse_template(plain_help) }',
      ),
    );
    pass(
      'Create a standalone template and nest existing help without allowing a self-reference',
    );

    // An actual Docassemble run verifies imports, Mako, Markdown, and collapse.
    await page.goto(`${fileUrl}/blocks/first`);
    await expect(page.locator('#q-title')).toHaveValue('First help screen');
    const popupPromise = page.waitForEvent('popup');
    await page
      .locator('[data-action="preview-interview"]:visible')
      .first()
      .click();
    const interview = await popupPromise;
    interview.on('pageerror', (error) => errors.push(String(error)));
    await expect(
      interview.getByRole('heading', { name: 'First help screen' }),
    ).toBeVisible({ timeout: 30000 });
    const help = interview.locator('.al_collapse_template');
    await expect(help.locator('.collapse')).toBeHidden();
    await help.getByRole('button', { name: 'Learn about addresses' }).click();
    await expect(help.locator('.collapse')).toBeVisible();
    await expect(help.locator('strong')).toHaveText('shared help');
    await expect(help.locator('li').first()).toHaveText('Café');
    await expect(help).toContainText('The computed value is 4.');
    await interview.screenshot({
      path: path.join(output, 'interview-expanded.png'),
    });
    await help.getByRole('button', { name: 'Learn about addresses' }).click();
    await expect(help.locator('.collapse')).toBeHidden();
    await interview
      .getByRole('button', { name: 'Continue', exact: true })
      .click();
    await expect(
      interview.getByRole('heading', { name: 'Second help screen' }),
    ).toBeVisible();
    await interview
      .locator('.al_collapse_template')
      .getByRole('button', { name: 'Learn about addresses' })
      .click();
    await expect(interview.locator('.al_collapse_template')).toContainText(
      'The computed value is 4.',
    );
    await interview
      .getByRole('button', { name: 'Continue', exact: true })
      .click();
    await expect(
      interview.getByRole('heading', { name: 'Help test complete' }),
    ).toBeVisible();
    await interview.close();
    pass(
      'Live interview expands/collapses shared Markdown and evaluates Mako on both screens',
    );
    assert.deepEqual(errors, [], 'Browser errors or unexpected dialogs');
    pass('No browser JavaScript errors');
    fs.writeFileSync(
      path.join(output, 'results.json'),
      JSON.stringify({ passed: true, results }, null, 2),
    );
  } catch (error) {
    await page
      .screenshot({ path: path.join(output, 'failure.png') })
      .catch(() => {});
    fs.writeFileSync(
      path.join(output, 'results.json'),
      JSON.stringify(
        { passed: false, results, error: String(error), browserErrors: errors },
        null,
        2,
      ),
    );
    throw error;
  } finally {
    if (created) {
      const response = await fixtureApi.delete(
        `${server}/api/playground/project`,
        {
          headers: apiHeaders,
          params: { project, ...userParams },
        },
      );
      assert.ok(
        response.ok(),
        `Fixture cleanup failed: ${await response.text()}`,
      );
      console.log(`Removed disposable project ${project}`);
    }
    await fixtureApi.dispose();
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

// Full localhost workflow. Creates and deletes only its own Playground project.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');
const { default: AxeBuilder } = require('@axe-core/playwright');
const server = process.env.SERVER_URL || 'http://localhost';
const output = process.env.SCREENSHOT_DIR || '/tmp/weaver-source-workbench';
const source =
  '# author comment\nmetadata:\n  title: Source workbench fixture\n---\nid: ask_name\nquestion: What is your name?\nfields:\n  - Name: answer_name\n---\nid: finish\nmandatory: True\nquestion: Hello ${ answer_name }\nbuttons:\n  - Exit: exit\n';
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: process.env.BROWSER_PATH,
  });
  const context = await browser.newContext({
    storageState: process.env.STORAGE_STATE,
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  let project, csrf;
  async function post(path, data) {
    const response = await context.request.post(server + '/al/editor' + path, {
      data,
      headers: { 'X-CSRF-Token': csrf },
    });
    const result = await response.json();
    assert.equal(result.success, true, JSON.stringify(result));
    return result.data;
  }
  async function saved() {
    const response = await context.request.get(
      server +
        '/al/editor/api/file?project=' +
        encodeURIComponent(project) +
        '&filename=workbench.yml',
    );
    return (await response.json()).data;
  }
  async function editor(operation, text) {
    return page.locator('#full-source-editor .cm-content').evaluate(
      (element, { operation, text }) => {
        const view =
          element.cmTile?.view ||
          element.cmView?.view ||
          element.parentElement.cmView?.view;
        if (operation === 'replace')
          view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: text },
            selection: { anchor: text.length },
          });
        if (operation === 'append')
          view.dispatch({
            changes: { from: view.state.doc.length, insert: text },
            selection: { anchor: view.state.doc.length + text.length },
            userEvent: 'input',
          });
        if (operation === 'start') view.dispatch({ selection: { anchor: 0 } });
        if (operation === 'end')
          view.dispatch({ selection: { anchor: view.state.doc.length } });
        return {
          source: view.state.doc.toString(),
          head: view.state.selection.main.head,
          line: view.state.doc.lineAt(view.state.selection.main.head).text,
        };
      },
      { operation, text },
    );
  }
  async function tool(name) {
    await page.locator('.editor-source-actions > summary').click();
    await page
      .locator('.editor-source-actions-menu')
      .getByRole('button', { name, exact: true })
      .click();
    await page.locator('.editor-source-workbench-dialog[open]').waitFor();
    await page.waitForFunction(
      () =>
        !document
          .querySelector('.editor-source-workbench-dialog [role=status]')
          .textContent.includes('Preparing'),
    );
  }
  async function closePreview() {
    await page
      .locator('.editor-source-workbench-dialog')
      .getByRole('button', { name: 'Close', exact: true })
      .click();
  }
  try {
    await page.goto(server + '/al/editor', { waitUntil: 'networkidle' });
    csrf = await page.evaluate(() => window.__EDITOR_BOOTSTRAP__.csrfToken);
    project = (
      await post('/api/new-project', {
        project_name: 'SourceWorkbench' + Date.now(),
        create_test: false,
      })
    ).project;
    await post('/api/file/new', {
      project,
      filename: 'workbench.yml',
      content: source,
    });
    await page.goto(
      server +
        '/al/editor/projects/' +
        encodeURIComponent(project) +
        '/interviews/workbench.yml/source',
      { waitUntil: 'networkidle' },
    );
    await page.locator('#full-source-editor .cm-content').waitFor();
    const rail = page.locator('#variable-report-rail');
    await rail
      .getByRole('button', { name: 'Insert answer_name', exact: true })
      .waitFor();
    assert.equal(await rail.isVisible(), true);
    assert.equal(
      await rail.evaluate((node) => node.parentElement.id),
      'left-rail',
    );
    await page.locator('#source-rail-outline').click();
    assert.equal(await rail.isVisible(), false);
    assert.equal(await page.locator('#outline-list').isVisible(), true);
    await page.locator('#source-rail-variables').click();
    assert.equal(await rail.isVisible(), true);
    const insertName = rail.getByRole('button', {
      name: 'Insert answer_name',
      exact: true,
    });
    await insertName.hover();
    assert.equal(
      await insertName.evaluate(
        (node) => getComputedStyle(node).textDecorationLine,
      ),
      'none',
    );

    assert.equal(
      await page.getByRole('button', { name: 'Symbols', exact: true }).count(),
      0,
    );
    await editor('append', '\n# Insert: ');
    await rail
      .getByRole('button', { name: 'Insert answer_name', exact: true })
      .click();
    assert.ok((await editor()).source.endsWith('# Insert: answer_name'));
    assert.equal(
      (await saved()).raw_yaml,
      source,
      'symbol insertion must remain unsaved',
    );
    await page.screenshot({ path: output + '/source-sidebar.png' });
    await rail
      .getByRole('button', { name: 'Details for answer_name', exact: true })
      .click();
    await page
      .getByRole('dialog', { name: 'answer_name', exact: true })
      .getByRole('button', { name: /Declared/ })
      .first()
      .click();
    assert.ok(await page.locator('#full-source-editor').isVisible());
    await editor('replace', source + '\n# unsaved change\n');
    await tool('Changes');
    assert.match(
      await page.locator('.editor-source-preview-diff').textContent(),
      /unsaved change/,
    );
    await page
      .locator('.editor-source-workbench-dialog')
      .getByRole('button', { name: 'Restore saved source', exact: true })
      .click();
    assert.equal((await editor()).source, source);
    await page.locator('#full-source-editor .cm-content').focus();
    await page.keyboard.press('Control+z');
    assert.match((await editor()).source, /unsaved change/);
    await tool('Changes');
    await page
      .locator('.editor-source-workbench-dialog details summary')
      .first()
      .click();
    await page
      .getByRole('button', { name: 'Revert change 1', exact: true })
      .click();
    assert.equal((await editor()).source, source);
    await editor('end');
    await tool('Recipes');
    await page
      .getByRole('searchbox', { name: 'Search recipes' })
      .fill('template');
    await page
      .getByRole('button', {
        name: 'Preview Reusable text template',
        exact: true,
      })
      .click();
    await page
      .getByRole('button', { name: 'Insert recipe', exact: true })
      .click();
    assert.match((await editor()).source, /template: example_text/);
    assert.equal((await saved()).raw_yaml, source);
    await page.keyboard.press('Control+z');
    assert.equal((await editor()).source, source);
    await editor('replace', source.replace('id: ask_name\n', ''));
    await tool('Repair block IDs');
    await page
      .getByRole('button', { name: 'Apply block ID repairs', exact: true })
      .click();
    assert.equal(((await editor()).source.match(/^id:/gm) || []).length, 2);
    assert.match((await editor()).source, /# author comment/);
    assert.equal((await saved()).raw_yaml, source);
    const unsaved = source
      .replace('ask_name', 'unsaved_name')
      .replace('What is your name?', 'Unsaved question');
    await editor('replace', unsaved);
    await tool('Source outline');
    await page
      .getByRole('searchbox', { name: 'Find a block, ID, or variable' })
      .fill('unsaved_name');
    await page.getByRole('button', { name: /Unsaved question.*line/ }).click();
    assert.equal((await editor()).source, unsaved);
    assert.equal((await editor()).line, 'id: unsaved_name');
    await editor('replace', source);
    await page.locator('#full-source-editor .cm-content').focus();
    await page.keyboard.press('F11');
    assert.equal(
      await rail.isVisible(),
      true,
      'sidebar remains visible in full-screen source',
    );
    await page.screenshot({ path: output + '/full-screen.png' });
    await page.setViewportSize({ width: 600, height: 950 });
    await page.screenshot({ path: output + '/narrow-full-screen.png' });
    const narrowRail = await page.locator('#left-rail').boundingBox();
    const narrowSource = await page
      .locator('#full-source-editor')
      .boundingBox();
    assert.ok(narrowRail.y >= narrowSource.y + narrowSource.height - 1);
    assert.ok(narrowRail.y + narrowRail.height <= 951);

    await page
      .getByRole('button', { name: 'Exit full screen (F11)', exact: true })
      .click();
    assert.equal(
      await page
        .locator('#left-rail')
        .evaluate((node) => node.parentElement.id),
      'editor-layout',
    );
    await page.setViewportSize({ width: 600, height: 950 });
    await page.screenshot({ path: output + '/narrow-source.png' });
    assert.equal(await rail.isVisible(), true);
    const axe = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    const severe = axe.violations.filter((item) =>
      ['critical', 'serious'].includes(item.impact),
    );
    assert.deepEqual(
      severe.map((item) => ({
        id: item.id,
        targets: item.nodes.map((node) => node.target),
      })),
      [],
    );
    await page.setViewportSize({ width: 1440, height: 1000 });
    await editor('append', '\n# saved through the UI\n');
    await page.locator('#save-full-yaml').click();
    await page.waitForTimeout(1000);
    assert.match((await saved()).raw_yaml, /saved through the UI/);
    await page.locator('#full-source-editor .cm-content').focus();
    await page.keyboard.press('F11');
    await page.getByRole('button', { name: 'Findings', exact: true }).click();
    assert.equal(
      await page
        .locator('#left-rail')
        .evaluate((node) => node.parentElement.id),
      'editor-layout',
    );
    assert.equal(await rail.isVisible(), true);
    await page.locator('#back-to-question').click();
    await page.locator('#full-source-editor').waitFor({ state: 'detached' });
    assert.equal(await page.locator('#left-rail').isVisible(), true);
    assert.equal(await page.locator('#source-rail-tabs').isVisible(), false);
    assert.equal(await rail.isVisible(), false);
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      output + '/results.json',
      JSON.stringify(
        {
          passed: true,
          checks: [
            'sidebar insertion',
            'definitions stay in source',
            'diff and undo',
            'hunk revert',
            'recipe preview and insertion',
            'ID repairs',
            'unsaved outline',
            'full-screen sidebar',
            'narrow layout and Axe',
            'save persistence',
          ],
        },
        null,
        2,
      ),
    );
    console.log('PASS localhost source workbench workflows: ' + output);
  } finally {
    if (project) await post('/api/project/delete', { project });
    await context.close();
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

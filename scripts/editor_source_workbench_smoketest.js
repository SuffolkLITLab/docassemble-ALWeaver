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
        if (operation === 'position')
          view.dispatch({
            selection: { anchor: view.state.doc.toString().indexOf(text) },
            scrollIntoView: true,
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
    await page.locator('#source-tools-toggle').click();
    await page
      .locator('.editor-source-actions-menu')
      .getByRole('button', { name, exact: true })
      .click();
    await page
      .locator(
        name === 'Insert block…'
          ? '#insert-modal.show'
          : '.editor-source-workbench-dialog[open]',
      )
      .waitFor();
    if (name === 'Insert block…') return;
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
    await page.waitForFunction(
      () =>
        document.activeElement ===
        document.querySelector('#full-source-editor .cm-content'),
    );
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
      await rail.evaluate((node) =>
        node.parentElement.classList.contains('editor-source-with-variables'),
      ),
      true,
    );
    assert.equal(await page.locator('#outline-list').isVisible(), true);
    const sourceBounds = await page
      .locator('#full-source-editor')
      .boundingBox();
    const variablesBounds = await rail.boundingBox();
    assert.ok(variablesBounds.x >= sourceBounds.x + sourceBounds.width);
    assert.equal(await page.locator('#source-rail-tabs').count(), 0);
    await page
      .getByRole('button', { name: 'Collapse variables', exact: true })
      .click();
    assert.equal(
      await page.locator('#variable-report-content').isVisible(),
      false,
    );
    await page.screenshot({ path: output + '/variables-collapsed.png' });
    assert.ok(
      (await page.locator('#full-source-editor').boundingBox()).width >
        sourceBounds.width,
    );
    await page
      .getByRole('button', { name: 'Expand variables', exact: true })
      .click();
    assert.equal(
      await page.locator('#variable-report-content').isVisible(),
      true,
    );

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
    // Standard Bootstrap dropdown behavior: visible caret/button, Escape and outside-click dismissal.
    const toolsToggle = page.locator('#source-tools-toggle');
    await toolsToggle.click();
    assert.equal(await toolsToggle.getAttribute('aria-expanded'), 'true');
    assert.equal(
      await page
        .getByRole('button', { name: 'Source outline', exact: true })
        .count(),
      0,
    );
    await page.screenshot({ path: output + '/source-tools-menu.png' });
    await toolsToggle.press('ArrowDown');
    assert.equal(
      await page
        .locator('.editor-source-actions-menu')
        .evaluate((node) => node.contains(document.activeElement)),
      true,
    );
    await page.keyboard.press('Escape');
    assert.equal(await toolsToggle.getAttribute('aria-expanded'), 'false');
    assert.equal(
      await toolsToggle.evaluate((node) => document.activeElement === node),
      true,
    );
    await toolsToggle.click();
    await page.locator('#full-source-editor .cm-content').click();
    assert.equal(await toolsToggle.getAttribute('aria-expanded'), 'false');
    await tool('Changes');
    await closePreview();
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
    const recipeDialog = page.locator('.editor-source-workbench-dialog');
    await recipeDialog
      .getByRole('navigation', { name: 'Example categories' })
      .waitFor();
    await recipeDialog
      .locator('summary')
      .filter({ hasText: /^Markdown templates$/ })
      .click();
    await recipeDialog
      .getByRole('button', { name: 'Template', exact: true })
      .click();
    assert.match(
      await recipeDialog.locator('.editor-recipe-preview > pre').textContent(),
      /template: disclaimer/,
    );
    assert.equal(
      await recipeDialog
        .getByRole('link', { name: 'Documentation', exact: true })
        .isVisible(),
      true,
    );
    await recipeDialog.locator('.editor-recipe-preview summary').click();
    assert.match(
      await recipeDialog
        .locator('.editor-recipe-preview details pre')
        .textContent(),
      /company/,
    );
    await page.screenshot({ path: output + '/recipe-tree.png' });
    const recipeAxe = await new AxeBuilder({ page })
      .include('.editor-source-workbench-dialog')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    assert.deepEqual(
      recipeAxe.violations
        .filter((item) => ['critical', 'serious'].includes(item.impact))
        .map((item) => item.id),
      [],
    );
    await recipeDialog
      .getByRole('searchbox', { name: 'Search Playground examples' })
      .fill('no-such-example-xyz');
    assert.match(
      await recipeDialog.locator('.editor-recipe-tree').textContent(),
      /No matching/,
    );
    await recipeDialog
      .getByRole('searchbox', { name: 'Search Playground examples' })
      .fill('template');
    await recipeDialog
      .getByRole('button', { name: 'Template', exact: true })
      .click();
    await recipeDialog
      .getByRole('button', { name: 'Insert after current block', exact: true })
      .click();
    await recipeDialog.waitFor({ state: 'hidden' });
    assert.match((await editor()).source, /template: disclaimer/);
    assert.equal((await saved()).raw_yaml, source);
    await page.keyboard.press('Control+z');
    assert.equal((await editor()).source, source);

    // The contextual menu targets its block even with unsaved edits elsewhere.
    await editor('append', '\n# unsaved insertion context\n');
    const beforeInsert = (await editor()).source;
    await editor('position', 'question: What is your name?');
    await page.locator('#full-source-editor .cm-content').focus();
    await page.keyboard.press('F11');
    await page
      .locator('#full-source-editor .cm-line')
      .filter({ hasText: 'question: What is your name?' })
      .hover();
    await page.locator('#source-block-actions').click();
    await page
      .locator(
        '[data-action="insert-source-block"][data-source-block-id="ask_name"]',
      )
      .click();
    const insertModal = page.locator('#insert-modal');
    await insertModal.waitFor({ state: 'visible' });
    await page.screenshot({ path: output + '/source-insert-block.png' });
    await insertModal.locator('[data-insert="code"]').click();
    await insertModal.waitFor({ state: 'hidden' });
    await page.waitForFunction(
      () =>
        document.activeElement ===
        document.querySelector('#full-source-editor .cm-content'),
    );
    const insertedSource = (await editor()).source;
    assert.ok(
      insertedSource.indexOf('code:') > insertedSource.indexOf('id: ask_name'),
    );
    assert.ok(
      insertedSource.indexOf('code:') < insertedSource.indexOf('id: finish'),
    );
    assert.ok(insertedSource.endsWith('# unsaved insertion context\n'));
    assert.equal((await saved()).raw_yaml, source);
    await page.keyboard.press('Control+z');
    assert.equal((await editor()).source, beforeInsert);
    await page
      .getByRole('button', { name: 'Exit full screen (F11)', exact: true })
      .click();
    await editor('replace', source);
    // Top insertion preserves the first-line comment even with a separator cursor.
    await editor('position', '---');
    await page
      .locator('.editor-outline-insert-btn[data-insert-after-id=""]')
      .click();
    await insertModal.locator('[data-insert="code"]').click();
    await insertModal.waitFor({ state: 'hidden' });
    await page.waitForFunction(
      () =>
        document.activeElement ===
        document.querySelector('#full-source-editor .cm-content'),
    );
    assert.ok(
      (await editor()).source.startsWith('# author comment\nid: code_'),
    );
    assert.equal((await saved()).raw_yaml, source);
    await page.keyboard.press('Control+z');
    assert.equal((await editor()).source, source);

    // A stale picker must never overwrite changes made after it opened.
    await tool('Insert block…');
    await editor('append', '\n# edit while picker open\n');
    await insertModal.locator('[data-insert="code"]').click();
    await page.waitForFunction(() =>
      document
        .getElementById('source-insert-status')
        .textContent.includes('Source changed'),
    );
    assert.equal(
      (await editor()).source,
      source + '\n# edit while picker open\n',
    );
    await insertModal
      .getByRole('button', { name: 'Cancel', exact: true })
      .click();
    await insertModal.waitFor({ state: 'hidden' });
    await editor('replace', source);
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
    await page
      .locator(
        '.editor-outline-item[data-block-id="ask_name"] .editor-outline-title',
      )
      .click();
    assert.match(
      await page.locator('#source-outline-status').textContent(),
      /Save your YAML/,
    );
    assert.equal(
      await page.locator('#source-outline-status').isVisible(),
      true,
    );
    await page.locator('#full-source-editor .cm-content').focus();
    await page.keyboard.press('F11');
    assert.equal(
      await page
        .locator('#source-outline-status')
        .evaluate((node) =>
          Boolean(node.closest('.editor-source-full-screen')),
        ),
      true,
    );
    await page
      .getByRole('button', { name: 'Exit full screen (F11)', exact: true })
      .click();
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
    const narrowRail = await rail.boundingBox();
    const narrowSource = await page
      .locator('#full-source-editor')
      .boundingBox();
    assert.ok(narrowRail.y >= narrowSource.y + narrowSource.height - 1);
    assert.ok(narrowRail.y + narrowRail.height <= 951);
    await page
      .getByRole('button', { name: 'Collapse variables', exact: true })
      .click();
    assert.ok((await rail.boundingBox()).height <= 49);
    await page
      .getByRole('button', { name: 'Expand variables', exact: true })
      .click();
    assert.equal(
      await page.locator('#variable-report-content').isVisible(),
      true,
    );

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
    await page.locator('#variable-report-filter').fill('answer_name');
    await page
      .getByRole('button', { name: 'Collapse variables', exact: true })
      .click();
    await editor('append', '\n# saved through the UI\n');
    await page.locator('#save-full-yaml').click();
    await page.waitForTimeout(1000);
    assert.match((await saved()).raw_yaml, /saved through the UI/);
    assert.equal(
      await page
        .locator('#variable-source-collapse')
        .getAttribute('aria-expanded'),
      'false',
    );
    assert.equal(
      await page.locator('#variable-report-filter').inputValue(),
      'answer_name',
    );
    await page.reload({ waitUntil: 'networkidle' });
    await page.locator('#full-source-editor .cm-content').waitFor();
    assert.equal(
      await page
        .locator('#variable-source-collapse')
        .getAttribute('aria-expanded'),
      'false',
    );
    await page.locator('#full-source-editor .cm-content').focus();
    await page.keyboard.press('F11');
    await page
      .getByRole('button', { name: 'Expand variables', exact: true })
      .click();
    assert.equal(
      await page.locator('#variable-report-content').isVisible(),
      true,
    );
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
    assert.equal(await page.locator('#source-rail-tabs').count(), 0);
    assert.equal(await rail.isVisible(), false);
    await page.locator('[data-action="toggle-rail"]').click();
    await page
      .locator('#editor-location button[data-action="open-full-yaml"]')
      .click();
    await page.locator('#full-source-editor .cm-content').waitFor();
    await page
      .getByRole('button', { name: 'Debug interview', exact: true })
      .click();
    await page.locator('.editor-runtime-inspector').waitFor();
    await page.waitForTimeout(300);
    assert.equal(
      await page.locator('.editor-runtime-inspector').isVisible(),
      true,
    );
    assert.equal(
      await page
        .locator('#editor-layout')
        .evaluate((node) => node.classList.contains('editor-rail-collapsed')),
      true,
    );
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      output + '/results.json',
      JSON.stringify(
        {
          passed: true,
          checks: [
            'Tools dropdown keyboard navigation, Escape, outside click and dialog focus',
            'sidebar insertion',
            'definitions stay in source',
            'diff and undo',
            'hunk revert',
            'Playground example tree, search, context, insertion and Axe',
            'contextual block insertion preserves unsaved source and undo',
            'top insertion preserves file header',
            'stale insertion picker refuses to overwrite edits',
            'ID repairs',
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

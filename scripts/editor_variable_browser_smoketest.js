// Localhost regression: catalog pagination, grouping, status labels and insertion.
// Creates and deletes only its own Playground project.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { default: AxeBuilder } = require('@axe-core/playwright');
const server = process.env.SERVER_URL || 'http://localhost';
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.BROWSER_PATH,
  });
  const context = await browser.newContext({
    storageState: process.env.STORAGE_STATE,
    viewport: { width: 1440, height: 1000 },
  });
  await context.addInitScript(() => {
    if (window === window.top)
      localStorage.removeItem('alweaver-source-variables-collapsed');
  });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
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
  const source =
    'code: |\n' +
    Array.from(
      { length: 350 },
      (_, i) => '  a_name_' + String(i).padStart(3, '0') + ' = 0\n',
    ).join('') +
    '  z_last_variable = 1\n---\ncode: |\n  def my_function():\n    return 1\n  class MyClass:\n    def my_method(self):\n      return 1\n---\ntemplate: my_template\ncontent: |\n  Hello\n---\nmandatory: True\nquestion: ${ missing_variable }\n';
  try {
    await page.goto(server + '/al/editor', { waitUntil: 'networkidle' });
    csrf = await page.evaluate(() => window.__EDITOR_BOOTSTRAP__.csrfToken);
    project = (
      await post('/api/new-project', {
        project_name: 'VariableBrowser' + Date.now(),
        create_test: false,
      })
    ).project;
    await post('/api/file/new', {
      project,
      filename: 'variables.yml',
      content: source,
    });
    await page.goto(
      server +
        '/al/editor/projects/' +
        encodeURIComponent(project) +
        '/interviews/variables.yml/source',
      { waitUntil: 'networkidle' },
    );
    const rail = page.locator('#variable-report-rail');
    const results = rail.locator('#variable-report-results');
    const search = rail.locator('#variable-report-filter');
    await rail
      .getByRole('button', { name: 'Insert a_name_000', exact: true })
      .waitFor();
    await rail.locator('[data-symbol-status="error"]').first().waitFor();
    assert.equal(await results.locator('.variable-browser-row').count(), 150);
    await search.fill('z_last_variable');
    await rail
      .getByRole('button', { name: 'Insert z_last_variable', exact: true })
      .waitFor();
    assert.equal(await results.locator('.variable-browser-row').count(), 1);
    await search.fill('');
    // Exercise the keyboard/manual fallback without relying on the observer.
    await results
      .locator('.variable-browser-more')
      .evaluate((button) => button.click());
    assert.ok((await results.locator('.variable-browser-row').count()) >= 300);
    assert.ok(
      await page.evaluate(() =>
        document.activeElement.classList.contains('variable-browser-insert'),
      ),
    );
    // Then exercise automatic loading by scrolling to the sentinel.
    for (
      let i = 0;
      i < 12 && !(await results.locator('.variable-browser-more').isHidden());
      i++
    ) {
      await rail.evaluate((element) => {
        element.scrollTop = element.scrollHeight;
      });
      await page.waitForTimeout(250);
    }
    assert.equal(
      await results.locator('.variable-browser-more').isHidden(),
      true,
    );
    await rail
      .getByRole('button', { name: 'Insert z_last_variable', exact: true })
      .waitFor();
    const headings = await results.locator('h3').allTextContents();

    for (const heading of [
      'Variables',
      'Templates',
      'Functions',
      'Methods',
      'Classes',
    ])
      assert.ok(headings.includes(heading), headings.join(', '));
    assert.equal(new Set(headings).size, headings.length);
    assert.equal(
      await rail
        .getByRole('button', { name: 'Insert my_template', exact: true })
        .count(),
      1,
    );
    assert.equal(
      await results
        .locator('[data-symbol-status="unused"]')
        .filter({ hasText: 'a_name_000' })
        .locator('.variable-browser-status')
        .innerText(),
      'Possibly unused · unreachable',
    );
    assert.equal(
      await results
        .locator('[data-symbol-status="builtin"]')
        .filter({ hasText: /^len/ })
        .locator('.variable-browser-status')
        .innerText(),
      'Built-in',
    );
    await rail.locator('#variable-report-kind').selectOption('variable');
    assert.equal(
      await rail
        .getByRole('button', { name: 'Insert my_template', exact: true })
        .count(),
      0,
    );
    await rail.locator('#variable-report-kind').selectOption('all');
    await rail.locator('.variable-browser-advanced > summary').click();
    await rail.locator('#variable-report-status').selectOption('used');
    assert.equal(
      await results.locator('[data-symbol-status="builtin"]').count(),
      0,
    );
    await rail.locator('#variable-report-status').selectOption('all');
    await rail.locator('.variable-browser-advanced > summary').click();
    // A type filter removes redundant headings and stale rows from old batches.
    await rail.locator('#variable-report-kind').selectOption('template');
    assert.equal(await results.locator('h3').count(), 0);
    assert.equal(await results.locator('.variable-browser-row').count(), 1);
    await rail.locator('#variable-report-kind').selectOption('all');
    await search.fill('z_last_variable');
    const editor = page.locator('#full-source-editor .cm-content');
    await editor.evaluate((element) => {
      const view =
        element.cmTile?.view ||
        element.cmView?.view ||
        element.parentElement.cmView?.view;
      view.dispatch({ selection: { anchor: view.state.doc.length } });
    });
    await rail
      .getByRole('button', { name: 'Insert z_last_variable', exact: true })
      .click();
    assert.ok((await editor.innerText()).endsWith('z_last_variable'));
    const saved = await context.request.get(
      server +
        '/al/editor/api/file?project=' +
        encodeURIComponent(project) +
        '&filename=variables.yml',
    );
    const savedData = (await saved.json()).data;
    assert.equal(savedData.raw_yaml, source);
    await search.fill('');
    const accessibility = await new AxeBuilder({ page })
      .include('#variable-report-rail')
      .analyze();
    assert.deepEqual(accessibility.violations, []);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: '/tmp/weaver-variable-groups.png' });
    console.log(
      'PASS: full catalog, manual/scroll pagination, grouping, status, insertion, accessibility, no saved writes',
    );
  } catch (error) {
    console.error(error);
    await page.screenshot({ path: '/tmp/weaver-variable-groups-failure.png' });
    throw error;
  } finally {
    if (project) await post('/api/project/delete', { project });
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

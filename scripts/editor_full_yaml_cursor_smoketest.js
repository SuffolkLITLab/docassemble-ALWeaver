#!/usr/bin/env node
// Exercise the installed localhost editor with a disposable Playground project.
// NODE_PATH=/path/to/node_modules STORAGE_STATE=/path/to/auth.json node scripts/editor_full_yaml_cursor_smoketest.js
const assert = require('node:assert/strict');
const { chromium, firefox, webkit } = require('playwright');
const server = process.env.SERVER_URL || 'http://localhost';

async function main() {
  const browserType = { chromium, firefox, webkit }[
    process.env.BROWSER || 'chromium'
  ];
  assert.ok(browserType, 'BROWSER must be chromium, firefox, or webkit');
  const browser = await browserType.launch({
    headless: true,
    ...(process.env.BROWSER_PATH
      ? { executablePath: process.env.BROWSER_PATH }
      : {}),
  });
  const context = await browser.newContext({
    storageState: process.env.STORAGE_STATE,
    viewport: { width: 1440, height: 1100 },
  });
  // Exercise CodeMirror's macOS shortcut detection on Linux test hosts too.
  // This does not substitute for testing Safari on an actual Mac.
  if (process.env.MAC_KEYBOARD === '1') {
    await context.addInitScript(() => {
      Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
    });
  }
  const page = await context.newPage();
  if (process.env.DOCASSEMBLE_CM6) {
    await page.route('**/static/app/cm6.min.js', (route) =>
      route.fulfill({
        path: process.env.DOCASSEMBLE_CM6,
        contentType: 'application/javascript',
      }),
    );
  }
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  let project;
  let csrf;
  async function post(endpoint, data) {
    const response = await context.request.post(
      server + '/al/editor' + endpoint,
      {
        data,
        headers: { 'X-CSRF-Token': csrf },
      },
    );
    const result = await response.json();
    assert.equal(result.success, true, JSON.stringify(result));
    return result.data;
  }
  // Read the real CM view without changing its event handlers or dispatch.
  async function snapshot() {
    return page
      .locator('#full-source-editor .cm-content')
      .evaluate((element) => {
        const view =
          element.cmTile?.view ||
          element.cmView?.view ||
          element.parentElement.cmView?.view;
        if (!view) throw new Error('Cannot inspect this CodeMirror version');
        return {
          head: view.state.selection.main.head,
          line: view.state.doc.lineAt(view.state.selection.main.head).text,
          scroll: view.scrollDOM.scrollTop,
          source: view.state.doc.toString(),
        };
      });
  }
  try {
    await page.goto(server + '/al/editor', { waitUntil: 'networkidle' });
    csrf = await page.evaluate(() => window.__EDITOR_BOOTSTRAP__?.csrfToken);
    assert.ok(csrf, 'An authenticated developer session is required');
    project = (
      await post('/api/new-project', {
        project_name: 'YamlCursor' + Date.now(),
        create_test: false,
      })
    ).project;
    const source = Array.from(
      { length: 150 },
      (_, i) =>
        `---\nid: block_${i}\nquestion: Question ${i}\nfields:\n  - Answer: answer_${i}\n`,
    ).join('');
    await post('/api/file/new', {
      project,
      filename: 'cursor.yml',
      content: source,
    });
    await page.goto(
      `${server}/al/editor/projects/${encodeURIComponent(project)}/interviews/cursor.yml/source`,
      { waitUntil: 'networkidle' },
    );
    const content = page.locator('#full-source-editor .cm-content');
    await content.waitFor();
    // The search bar is shown without Ctrl/Cmd+F and starts empty.
    const searchField = page.locator(
      '#full-source-editor .cm-search input[name=search]',
    );
    await searchField.waitFor();
    assert.equal(await searchField.inputValue(), '');
    // Lose focus while the cursor is still at the beginning, then scroll.
    await page.locator('#editor-location').click();
    await page.locator('#full-source-editor .cm-scroller').evaluate((el) => {
      el.scrollTop = 6000;
    });
    // WebKit may take several frames to render the newly visible CM lines.
    await page.waitForFunction(() =>
      Array.from(
        document.querySelectorAll('#full-source-editor .cm-line'),
      ).some((line) => {
        const y = line.getBoundingClientRect().y + 8;
        return line.textContent.startsWith('question:') && y > 250 && y < 700;
      }),
    );
    const point = await page
      .locator('#full-source-editor .cm-line')
      .evaluateAll((lines) => {
        return lines
          .map((line) => {
            const rect = line.getBoundingClientRect();
            return { text: line.textContent, x: rect.x + 100, y: rect.y + 8 };
          })
          .find(
            (line) =>
              line.text.startsWith('question:') && line.y > 250 && line.y < 700,
          );
      });
    assert.ok(point, 'A question well below the top is visible');
    await page.mouse.click(point.x, point.y);
    await page.waitForTimeout(500);
    let state = await snapshot();
    assert.equal(state.line, point.text, 'Click selects the clicked line');
    assert.ok(state.scroll > 5000, 'Click preserves the scrolled viewport');
    assert.equal(state.source, source, 'Click does not change the source');

    const macKeyboard = await page.evaluate(() =>
      /Mac/.test(navigator.platform),
    );
    await page.keyboard.press(macKeyboard ? 'Meta+f' : 'Control+f');
    await page.locator('.cm-search input[name=search]').fill('Question 120');
    await page.locator('.cm-search button[name=next]').click();
    // Keep search focused and open: clicking the result must place the cursor
    // before the editor regains focus, without scrolling to its old selection.
    const found = page
      .locator('#full-source-editor .cm-line')
      .filter({ hasText: 'question: Question 120' });
    await found.click({ position: { x: 130, y: 8 } });
    await page.keyboard.type('EDIT');
    state = await snapshot();
    assert.ok(
      state.line.includes('EDIT'),
      'Typing occurs at the clicked search result',
    );
    assert.ok(state.head > source.indexOf('id: block_120'));
    assert.ok(state.head < source.indexOf('id: block_121'));
    await page.locator('#save-full-yaml').click();
    await page.waitForTimeout(1000);
    const saved = await context.request.get(
      `${server}/al/editor/api/file?project=${encodeURIComponent(project)}&filename=cursor.yml`,
    );
    assert.equal((await saved.json()).data.raw_yaml, state.source);
    assert.deepEqual(errors, []);
    console.log(
      'PASS: scroll, blur/refocus, search, click, type, and saved YAML on ' +
        server,
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

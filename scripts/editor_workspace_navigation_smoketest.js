#!/usr/bin/env node
// Run against an installed editor with an authenticated developer session.
// Creates and deletes only its own disposable project. No source assets are mocked.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const server = process.env.SERVER_URL || 'http://localhost';
const output = process.env.SCREENSHOT_DIR || '/tmp/weaver-workspace-navigation';
const results = [];
async function main() {
  assert.ok(
    process.env.STORAGE_STATE,
    'Set STORAGE_STATE to a developer browser session',
  );
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    storageState: process.env.STORAGE_STATE,
    hasTouch: true,
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  const unexpectedResponses = [];
  page.on('response', (response) => {
    if (
      response.url().includes('/al/editor/api/section-file/raw') &&
      response.ok() &&
      String(response.headers()['content-type']).includes('application/pdf')
    )
      return;
    if (
      response.url().includes('/al/editor/api/') &&
      !String(response.headers()['content-type']).includes('application/json')
    ) {
      const diagnostic = {
        url: response.url(),
        status: response.status(),
        contentType: response.headers()['content-type'],
        redirect: response.headers().location,
      };
      unexpectedResponses.push(diagnostic);
      console.log('Unexpected API response', JSON.stringify(diagnostic));
    }
  });
  page.on('pageerror', (e) => errors.push(e.message));
  let project, csrf;
  async function post(endpoint, data) {
    const response = await context.request.post(
      server + '/al/editor' + endpoint,
      { data, headers: { 'X-CSRF-Token': csrf } },
    );
    const body = await response.json();
    assert.equal(body.success, true, JSON.stringify(body));
    return body.data;
  }
  async function check(name, fn) {
    await fn();
    results.push(name);
    console.log('PASS ' + name);
  }
  async function snapshot(id = 'full-source-editor') {
    return page.locator('#' + id + ' .cm-content').evaluate((element) => {
      const view =
        element.cmTile?.view ||
        element.cmView?.view ||
        element.parentElement.cmView?.view;
      if (!view) throw Error('Cannot inspect CodeMirror view');
      return {
        source: view.state.doc.toString(),
        anchor: view.state.selection.main.anchor,
        head: view.state.selection.main.head,
        scroll: view.scrollDOM.scrollTop,
      };
    });
  }
  async function full() {
    const entry = page.locator(
      '#editor-location button[data-action="open-full-yaml"]',
    );
    if (await entry.isVisible()) await entry.click();
    else await menu('open-full-yaml');
    await page.locator('#full-source-editor .cm-content').waitFor();
  }
  async function append(marker) {
    await page.locator('#full-source-editor .cm-content').click();
    await page.keyboard.press('Control+End');
    await page.keyboard.press('End');
    await page.keyboard.insertText('\n# ' + marker + '\n');
  }
  async function choice(name) {
    await page.locator('[data-unsaved-choice="' + name + '"]').click();
  }
  async function menu(action) {
    await page.locator('#interview-menu').click();
    await page
      .locator(
        '[aria-labelledby="interview-menu"] [data-action="' + action + '"]',
      )
      .click();
  }
  try {
    await page.goto(server + '/al/editor', { waitUntil: 'networkidle' });
    csrf = await page.evaluate(() => window.__EDITOR_BOOTSTRAP__?.csrfToken);
    assert.ok(csrf, 'Authenticated developer session required');
    await check('installed JavaScript matches the working branch', async () => {
      const url = await page
        .locator('script[src*="/editor.js"]')
        .getAttribute('src');
      const response = await context.request.get(new URL(url, server).href);
      assert.equal(
        await response.text(),
        fs.readFileSync(
          path.join(__dirname, '../docassemble/ALWeaver/data/static/editor.js'),
          'utf8',
        ),
      );
      assert.equal(await page.locator('#editor-location').count(), 1);
    });
    project = (
      await post('/api/new-project', {
        project_name: 'WorkspaceNav' + Date.now(),
        create_test: false,
      })
    ).project;
    const source =
      'metadata:\n  title: Navigation fixture\n---\nid: about\nquestion: About you\nfields:\n  - Name: person_name\n---\nid: income\nquestion: Your income\nfields:\n  - Income: income\n    datatype: currency\n---\nid: calculation\nmandatory: true\ncode: |\n  total = 1\n' +
      Array.from(
        { length: 70 },
        (_, i) =>
          `---\nid: detail_${i}\nquestion: Detail ${i}\n${i === 10 ? 'subquestion: |\n' + Array.from({ length: 100 }, (_, line) => '  Long block line ' + line + '\n').join('') : ''}fields:\n  - Answer for detail ${i}: detail_${i}\n`,
      ).join('');
    await post('/api/file/new', {
      project,
      filename: 'navigation.yml',
      content: source,
    });
    const uploaded = await context.request.post(
      server + '/al/editor/api/section-file/upload',
      {
        headers: { 'X-CSRF-Token': csrf },
        multipart: {
          project,
          section: 'templates',
          files: {
            name: 'navigation-template.pdf',
            mimeType: 'application/pdf',
            buffer: fs.readFileSync(
              path.join(
                __dirname,
                '../docassemble/ALWeaver/data/templates/test.pdf',
              ),
            ),
          },
        },
      },
    );
    assert.equal((await uploaded.json()).success, true);
    const base = `${server}/al/editor/projects/${encodeURIComponent(project)}/interviews/navigation.yml`;
    await page.goto(base + '/blocks/about', { waitUntil: 'networkidle' });
    assert.equal(
      await page.locator('#canvas-content .editor-center-bar').count(),
      0,
    );
    assert.match(
      await page.locator('#editor-location').innerText(),
      /About you/,
    );
    await page.screenshot({ path: path.join(output, 'question-screen.png') });
    await page.locator('#toggle-edit-mode-tab').click();
    await page.locator('#block-source-editor .cm-content').waitFor();
    await check(
      'Block YAML kebab guards unsaved edits with Stay and Discard',
      async () => {
        const editor = page.locator('#block-source-editor .cm-content');
        await editor.focus();
        await page.keyboard.press('Control+End');
        await page.keyboard.insertText('\n# block-menu-unsaved\n');
        await page.locator('#source-block-actions').tap();
        await page.locator('[data-action="edit-source-block"]').tap();
        await choice('stay');
        assert.match(
          (await snapshot('block-source-editor')).source,
          /block-menu-unsaved/,
        );
        await page.locator('#source-block-actions').tap();
        await page.locator('[data-action="edit-source-block"]').tap();
        await choice('discard');
        await page.locator('#q-title').waitFor({ state: 'attached' });
        await page.locator('#toggle-edit-mode-tab').click();
        assert.doesNotMatch(
          (await snapshot('block-source-editor')).source,
          /block-menu-unsaved/,
        );
      },
    );
    await check(
      'touch-visible active-block menu previews without leaving YAML',
      async () => {
        await page.setViewportSize({ width: 1024, height: 768 });
        assert.equal(
          await page
            .locator('#editor-interview-submenu button')
            .first()
            .innerText(),
          'Edit full-file YAML',
        );
        assert.equal(
          await page.evaluate(() => matchMedia('(hover: none)').matches),
          true,
        );
        const before = await snapshot('block-source-editor');
        assert.equal(await page.locator('#source-block-actions').count(), 1);
        const touchTarget = await page
          .locator('#source-block-actions')
          .boundingBox();
        assert.ok(touchTarget.width >= 44 && touchTarget.height >= 44);
        await page.locator('#source-block-actions').tap();
        await page
          .locator(
            '[aria-labelledby="source-block-actions"] [data-action="open-screen-preview"]',
          )
          .tap();
        await page
          .locator('#screen-preview-modal')
          .waitFor({ state: 'visible' });
        assert.equal(
          await page.locator('#screen-preview-title').innerText(),
          'About you',
        );
        assert.match(
          await page.locator('#screen-preview-frame').getAttribute('srcdoc'),
          /About you/,
        );
        await page
          .locator('#screen-preview-modal [data-bs-dismiss="modal"]')
          .first()
          .click();
        await page
          .locator('#screen-preview-modal')
          .waitFor({ state: 'hidden' });
        assert.deepEqual(await snapshot('block-source-editor'), before);
        await page.screenshot({
          path: path.join(output, 'yaml-touch-menu.png'),
        });
        await page.setViewportSize({ width: 1440, height: 1000 });
      },
    );
    await check(
      'filename expands Block YAML to an unfiltered full file and opens the current block visually',
      async () => {
        await page.selectOption('#jump-select', 'code');
        await page.fill('#search-input', 'no-matching-block');
        await page
          .locator('#editor-location a[data-action="open-full-yaml"]')
          .click();
        await page.locator('#full-source-editor .cm-content').waitFor();
        assert.equal((await snapshot()).source, source);
        assert.equal(
          await page
            .locator('[aria-labelledby="interview-menu"] button')
            .first()
            .innerText(),
          'Edit full-file YAML',
        );
        assert.equal(await page.inputValue('#jump-select'), 'all');
        assert.equal(await page.inputValue('#search-input'), '');
        assert.equal(
          await page.locator('.editor-outline-item[data-block-id]').count(),
          74,
        );
        assert.equal(
          await page.locator('#outline-current-hidden').isVisible(),
          false,
        );
        await page.locator('#back-to-question').click();
        await page.locator('#q-title').waitFor({ state: 'attached' });
        assert.equal(await page.inputValue('#jump-select'), 'all');
        assert.equal(await page.inputValue('#search-input'), '');
        await page.locator('#toggle-edit-mode-tab').click();
        await page.fill('#search-input', '');
        await page.selectOption('#jump-select', 'all');
      },
    );
    await check(
      'Block YAML → full source → Templates → Interview → full source retains content',
      async () => {
        await full();
        assert.equal((await snapshot()).source, source);
        await page.locator('.editor-top-tab[data-view="templates"]').click();
        await page.waitForURL('**/templates**');
        await page.locator('.editor-top-tab[data-view="interview"]').click();
        await page.locator('#block-source-editor .cm-content').waitFor();
        await full();
        assert.equal((await snapshot()).source, source);
        await page
          .locator('#full-source-editor')
          .evaluate((el) => (el.dataset.navigationTest = 'same-editor'));
        await full();
        assert.equal(
          await page
            .locator('#full-source-editor')
            .getAttribute('data-navigation-test'),
          'same-editor',
        );
      },
    );
    await check(
      'recorded blank-source path: Templates PDF → Interview menu YAML → repeat YAML retains the entire file',
      async () => {
        await page.locator('.editor-top-tab[data-view="templates"]').click();
        await page
          .locator('[data-section-filename="navigation-template.pdf"]')
          .click();
        await page
          .locator('iframe[title="PDF preview"]')
          .waitFor({ state: 'visible' });
        assert.equal(await page.locator('#full-source-editor').count(), 0);
        await menu('open-full-yaml');
        await page.locator('#full-source-editor .cm-content').waitFor();
        assert.equal((await snapshot()).source, source);
        assert.equal(await page.locator('#block-source-editor').count(), 0);
        assert.equal(await page.inputValue('#jump-select'), 'all');
        await page.locator('#full-source-editor').evaluate((el) => {
          el.dataset.videoRegression = 'same-buffer';
        });
        await menu('open-full-yaml');
        assert.equal((await snapshot()).source, source);
        assert.equal(
          await page
            .locator('#full-source-editor')
            .getAttribute('data-video-regression'),
          'same-buffer',
        );
        assert.match(
          await page.locator('#editor-location').innerText(),
          /navigation.yml.*Full file YAML/s,
        );
        await page.screenshot({
          path: path.join(output, 'recorded-templates-source.png'),
        });
      },
    );
    await check(
      'full-file editor has no subset tabs or explanatory annotations',
      async () => {
        assert.equal(await page.locator('[data-yaml-tab]').count(), 0);
        assert.equal((await snapshot()).source, source);
        assert.equal(await page.locator('#canvas-content h2').count(), 0);
        assert.doesNotMatch(
          await page.locator('#editor-location').innerText(),
          /Editing the|Editing one/,
        );
        assert.equal(
          await page.locator('#source-outline-status').isVisible(),
          false,
        );
      },
    );
    await check('source action opens About you visually', async () => {
      assert.match(
        await page.locator('#back-to-question').innerText(),
        /Edit About you visually/,
      );
      await page.locator('#back-to-question').click();
      await page.locator('#q-title').waitFor({ state: 'attached' });
      await page.locator('#toggle-edit-mode-tab').click();
      assert.match((await snapshot('block-source-editor')).source, /id: about/);
      assert.equal(
        await page
          .locator('#toggle-edit-mode-tab')
          .getAttribute('aria-selected'),
        'true',
      );
    });
    await check(
      'Show and search preserve the mounted block and save target',
      async () => {
        const before = await snapshot('block-source-editor');
        await page.selectOption('#jump-select', 'code');
        await page.fill('#search-input', 'no-such-block');
        assert.equal(
          (await snapshot('block-source-editor')).source,
          before.source,
        );
        assert.equal(
          await page.locator('#outline-current-hidden').isVisible(),
          true,
        );
        await page.locator('#block-source-editor .cm-content').click();
        await page.keyboard.press('Control+End');
        await page.keyboard.insertText('\n# hidden-block-save\n');
        const saved = page.waitForResponse(
          (r) =>
            r.url().endsWith('/api/block') && r.request().method() === 'POST',
        );
        await page.locator('.js-save-file-btn:visible').first().click();
        const response = await saved;
        assert.equal(response.request().postDataJSON().block_id, 'about');
        assert.equal((await response.json()).success, true);
        await page.waitForFunction(() =>
          document
            .querySelector('#block-source-editor .cm-content')
            ?.textContent.includes('hidden-block-save'),
        );
        await page.screenshot({
          path: path.join(output, 'filtered-block.png'),
        });
        await page.locator('[data-action="reveal-current-block"]').click();
        assert.equal(await page.inputValue('#search-input'), '');
        assert.equal(await page.inputValue('#jump-select'), 'all');
      },
    );
    await check(
      'Settings names and restores the originating block representation',
      async () => {
        await menu('open-assemblyline-settings');
        await page.locator('#close-assemblyline-settings').waitFor();
        assert.match(
          await page.locator('#close-assemblyline-settings').innerText(),
          /Return to About you.*Block YAML/,
        );
        await page.locator('#close-assemblyline-settings').click();
        await page.locator('#block-source-editor .cm-content').waitFor();
      },
    );
    await full();
    await check(
      'outline jumps reveal block starts in both directions, including tall blocks',
      async () => {
        for (const id of [
          'detail_50',
          'detail_2',
          'detail_60',
          'income',
          'detail_10',
          'detail_65',
          'detail_10',
          'detail_50',
        ]) {
          await page
            .locator('.editor-outline-item[data-block-id="' + id + '"]')
            .click();
          try {
            await page.waitForFunction(
              (id) => {
                const viewport = document
                  .querySelector('#full-source-editor .cm-scroller')
                  .getBoundingClientRect();
                return [
                  ...document.querySelectorAll('#full-source-editor .cm-line'),
                ].some((line) => {
                  const rect = line.getBoundingClientRect();
                  return (
                    line.textContent.trim() === 'id: ' + id &&
                    rect.top >= viewport.top &&
                    rect.bottom <= viewport.bottom
                  );
                });
              },
              id,
              { timeout: 5000 },
            );
          } catch (error) {
            console.error(
              'Failed outline destination:',
              id,
              'snapshot:',
              JSON.stringify({ ...(await snapshot()), source: undefined }),
            );
            throw error;
          }
        }
      },
    );
    await check(
      'full-source outline jumps keep source, and cursor returns after opening Blocks',
      async () => {
        await page
          .locator('[data-block-id="detail_50"].editor-outline-item')
          .click();
        await page.locator('#full-source-editor .cm-content').focus();
        await page.keyboard.press('Control+Home');
        for (let line = 0; line < 5; line++)
          await page.keyboard.press('ArrowDown');
        assert.match(
          await page.locator('#back-to-question').innerText(),
          /Edit About you visually/,
        );
        await page
          .locator('[data-block-id="detail_50"].editor-outline-item')
          .click();
        await page.locator('#source-block-actions').tap();
        const previousMenu = await page
          .locator('#source-block-actions')
          .elementHandle();
        await page
          .locator('[data-block-id="detail_60"].editor-outline-item')
          .click();
        await page.waitForFunction((el) => !el.isConnected, previousMenu);
        assert.equal(
          await previousMenu.evaluate(
            (el) => window.bootstrap.Dropdown.getInstance(el) === null,
          ),
          true,
        );
        await previousMenu.dispose();
        await page
          .locator('[data-block-id="detail_50"].editor-outline-item')
          .click();
        const position = await snapshot();
        assert.equal(await page.locator('#source-block-actions').count(), 1);
        await page
          .locator('#full-source-editor .cm-scroller')
          .evaluate((el) => {
            el.scrollTop = el.scrollHeight;
          });
        await page.waitForFunction(
          () => document.querySelector('.editor-source-block-actions').hidden,
        );
        await page
          .locator('[data-block-id="detail_50"].editor-outline-item')
          .click();
        assert.match(
          position.source.slice(position.anchor, position.head),
          /id: detail_50/,
        );
        assert.match(
          await page.locator('#back-to-question').innerText(),
          /Edit Detail 50 visually/,
        );
        await page.locator('#source-block-actions').tap();
        await page
          .locator(
            '[aria-labelledby="source-block-actions"] [data-action="open-screen-preview"]',
          )
          .tap();
        await page
          .locator('#screen-preview-modal')
          .waitFor({ state: 'visible' });
        assert.equal(
          await page.locator('#screen-preview-title').innerText(),
          'Detail 50',
        );
        const sourcePreview = await page
          .locator('#screen-preview-frame')
          .getAttribute('srcdoc');
        assert.match(sourcePreview, /Detail 50/);
        assert.match(sourcePreview, /Answer for detail 50/);
        assert.doesNotMatch(sourcePreview, /Answer for detail 49/);
        assert.equal(
          await page
            .frameLocator('#screen-preview-frame')
            .locator('#daform input:not([type="hidden"])')
            .count(),
          1,
        );
        await page
          .locator('#screen-preview-modal [data-bs-dismiss="modal"]')
          .first()
          .click();
        await page
          .locator('#screen-preview-modal')
          .waitFor({ state: 'hidden' });
        assert.deepEqual(await snapshot(), position);
        await page.locator('#source-block-actions').tap();
        await page.locator('[data-action="edit-source-block"]').click();
        await page.locator('#q-title').waitFor({ state: 'attached' });
        assert.match(
          await page.locator('#editor-location').innerText(),
          /Detail 50/,
        );
        await page.locator('#question-preview-tab').click();
        await page
          .locator('#screen-preview-modal')
          .waitFor({ state: 'visible' });
        assert.equal(
          await page.locator('#screen-preview-title').innerText(),
          'Detail 50',
        );
        assert.match(
          await page.locator('#screen-preview-frame').getAttribute('srcdoc'),
          /Detail 50/,
        );
        await page
          .locator('#screen-preview-modal [data-bs-dismiss="modal"]')
          .first()
          .click();
        await page
          .locator('#screen-preview-modal')
          .waitFor({ state: 'hidden' });
        await full();
        const returned = await snapshot();
        assert.equal(returned.anchor, position.anchor);
        assert.equal(returned.head, position.head);
        await page.waitForFunction(() => {
          const scroll = document
            .querySelector('#full-source-editor .cm-scroller')
            .getBoundingClientRect();
          return [
            ...document.querySelectorAll('#full-source-editor .cm-line'),
          ].some((line) => {
            const rect = line.getBoundingClientRect();
            return (
              line.textContent.includes('question: Detail 50') &&
              rect.top >= scroll.top &&
              rect.bottom <= scroll.bottom
            );
          });
        });
        await page.screenshot({ path: path.join(output, 'full-source.png') });
      },
    );
    await check(
      'Stay and Discard preserve or remove the actual source buffer',
      async () => {
        const before = (await snapshot()).source;
        await append('discard-this-navigation-edit');
        const dirtyBuffer = (await snapshot()).source;
        await page
          .locator('#editor-location a[data-action="open-full-yaml"]')
          .click();
        assert.equal((await snapshot()).source, dirtyBuffer);
        assert.match(page.url(), /\/source$/);
        assert.equal(
          await page.locator('#unsaved-changes-modal').isVisible(),
          false,
        );
        await page.locator('.editor-top-tab[data-view="templates"]').click();
        await choice('stay');
        assert.match((await snapshot()).source, /discard-this-navigation-edit/);
        await page.locator('.editor-top-tab[data-view="templates"]').click();
        await choice('discard');
        await page.waitForURL('**/templates**');
        await page.locator('.editor-top-tab[data-view="interview"]').click();
        await full();
        assert.equal((await snapshot()).source, before);
      },
    );
    await check(
      'failed Save retains source; successful Save resumes navigation',
      async () => {
        await append('save-this-navigation-edit');
        const failSave = (route) =>
          route.fulfill({
            status: 500,
            contentType: 'application/json',
            body: JSON.stringify({
              success: false,
              error: { message: 'Intentional browser-test save failure' },
            }),
          });
        await page.route('**/al/editor/api/file', failSave);
        await page.locator('.editor-top-tab[data-view="templates"]').click();
        await choice('save');
        await page.locator('#unsaved-changes-error:not(.d-none)').waitFor();
        assert.match((await snapshot()).source, /save-this-navigation-edit/);
        assert.match(page.url(), /\/source$/);
        await page.unroute('**/al/editor/api/file', failSave);
        await choice('save');
        await page.waitForURL('**/templates**');
        await page.locator('.editor-top-tab[data-view="interview"]').click();
        await full();
        assert.match((await snapshot()).source, /save-this-navigation-edit/);
      },
    );
    await check(
      'saving full source keeps its scope and selection',
      async () => {
        await append('direct-source-save');
        const before = await snapshot();
        const saved = page.waitForResponse(
          (r) =>
            r.url().endsWith('/api/file') && r.request().method() === 'POST',
        );
        await page.locator('#save-full-yaml').click();
        assert.equal((await (await saved).json()).success, true);
        await page.waitForFunction(() =>
          document
            .querySelector('#full-source-editor .cm-content')
            ?.textContent.includes('direct-source-save'),
        );
        assert.equal((await snapshot()).head, before.head);
        assert.match(
          await page.locator('#editor-location').innerText(),
          /Full file YAML/,
        );
      },
    );
    await check(
      'Settings returns to Full YAML with its cursor and current-block preview',
      async () => {
        await page
          .locator('[data-block-id="detail_50"].editor-outline-item')
          .click();
        const position = await snapshot();
        await menu('open-assemblyline-settings');
        assert.equal(
          await page.locator('#close-assemblyline-settings').innerText(),
          'Return to Full file YAML',
        );
        await page.locator('#close-assemblyline-settings').click();
        await page.locator('#full-source-editor .cm-content').waitFor();
        const restored = await snapshot();
        assert.equal(restored.anchor, position.anchor);
        assert.equal(restored.head, position.head);
        assert.match(
          await page.locator('#back-to-question').innerText(),
          /Edit Detail 50 visually/,
        );
      },
    );
    await check(
      'source → block → browser Back/Forward restores routed destinations',
      async () => {
        await page
          .locator('[data-block-id="detail_50"].editor-outline-item')
          .click();
        await page.locator('#back-to-question').click();
        await page.waitForURL('**/blocks/**');
        await page.goBack();
        await page.locator('#full-source-editor .cm-content').waitFor();
        assert.match(
          await page.locator('#back-to-question').innerText(),
          /Edit .* visually/,
        );
        await page.locator('#source-block-actions').tap();
        await page
          .locator(
            '[aria-labelledby="source-block-actions"] [data-action="open-screen-preview"]',
          )
          .tap();
        await page
          .locator('#screen-preview-modal')
          .waitFor({ state: 'visible' });
        assert.equal(
          await page.locator('#screen-preview-title').innerText(),
          'Detail 50',
        );
        assert.match(
          await page.locator('#screen-preview-frame').getAttribute('srcdoc'),
          /Answer for detail 50/,
        );
        await page
          .locator('#screen-preview-modal [data-bs-dismiss="modal"]')
          .first()
          .click();
        await page
          .locator('#screen-preview-modal')
          .waitFor({ state: 'hidden' });
        await page.goForward();
        await page.locator('#q-title').waitFor({ state: 'attached' });
      },
    );
    await check(
      'validation navigation for the selected block guards unsaved full-file YAML',
      async () => {
        await full();
        await page.selectOption('#jump-select', 'all');
        await page
          .locator('.editor-outline-item[data-block-id="calculation"]')
          .click();
        const original = (await snapshot()).source;
        const invalid = original.replace('total = 1', 'total =');
        await page.locator('#full-source-editor .cm-content').fill(invalid);
        if (
          !(await page
            .locator('#validation-drawer')
            .evaluate((el) => el.classList.contains('open')))
        )
          await page.locator('#validation-toggle').click();
        const validated = page.waitForResponse(
          (r) =>
            r.url().endsWith('/api/validate-source') &&
            r.request().method() === 'POST',
        );
        await page.locator('#btn-run-validation').click();
        assert.equal((await (await validated).json()).success, true);
        const finding = page
          .locator('.editor-validation-item[data-block-id="calculation"]')
          .first();
        await finding.click();
        await choice('stay');
        assert.equal((await snapshot()).source, invalid);
        await finding.click();
        await choice('discard');
        await page
          .locator('#code-source-editor .cm-content')
          .waitFor({ state: 'attached' });
        await full();
        assert.equal((await snapshot()).source, original);
      },
    );
    await check(
      'order source opens Block YAML rather than a full-file subset',
      async () => {
        await page.goto(base + '/order', { waitUntil: 'networkidle' });
        await page.locator('#order-to-raw').click();
        assert.match(
          (await snapshot('block-source-editor')).source,
          /id: calculation/,
        );
        assert.equal(await page.locator('#full-source-editor').count(), 0);
        await page.locator('#block-source-editor .cm-content').click();
        await page.keyboard.press('Control+End');
        await page.keyboard.insertText('\n# saved-order-block\n');
        const saved = page.waitForResponse(
          (r) =>
            r.url().endsWith('/api/block') && r.request().method() === 'POST',
        );
        await page.locator('.js-save-file-btn:visible').first().click();
        const response = await saved;
        assert.equal(response.request().postDataJSON().block_id, 'calculation');
        assert.equal((await response.json()).success, true);
        await page.waitForFunction(() =>
          document
            .querySelector('#block-source-editor .cm-content')
            ?.textContent.includes('saved-order-block'),
        );
      },
    );
    await check(
      'CRLF source and identical blocks jump to their parsed source ranges',
      async () => {
        const duplicate =
          'code: |\r\n  total = 1\r\n---\r\ncode: |\r\n  total = 1\r\n';
        await post('/api/file/new', {
          project,
          filename: 'windows.yml',
          content: duplicate,
        });
        await page.goto(
          base.replace('navigation.yml', 'windows.yml') + '/source',
          { waitUntil: 'networkidle' },
        );
        assert.equal(await page.inputValue('#jump-select'), 'all');
        assert.equal(await page.inputValue('#search-input'), '');
        const rows = page.locator('.editor-outline-item[data-block-id]');
        assert.equal(await rows.count(), 2);
        await rows.nth(1).click();
        const selected = await snapshot();
        assert.ok(selected.anchor > selected.source.indexOf('---'));
        assert.match(
          selected.source.slice(selected.anchor, selected.head),
          /total = 1/,
        );
        assert.equal(
          await page.locator('#source-outline-status').innerText(),
          '',
        );
        await page.goto(base + '/source', { waitUntil: 'networkidle' });
      },
    );
    await check(
      'location and scope remain visible with collapsed sidebar and narrow viewport',
      async () => {
        await full();
        await page.locator('[data-action="toggle-rail"]').click();
        assert.equal(await page.locator('#editor-location').isVisible(), true);
        assert.match(await page.title(), /navigation.yml.*Weaver/);
        await page.setViewportSize({ width: 390, height: 844 });
        await page.screenshot({ path: path.join(output, 'narrow-source.png') });
        const box = await page.locator('#editor-location').boundingBox();
        assert.ok(box && box.x >= 0 && box.x + box.width <= 391);
        assert.match(
          await page.locator('#editor-location').innerText(),
          /navigation.yml[\s\S]*Full file YAML/,
        );
      },
    );
    assert.deepEqual(errors, [], 'No browser JavaScript errors');
    assert.deepEqual(
      unexpectedResponses,
      [],
      'All editor APIs returned expected content types',
    );
  } catch (error) {
    await page
      .screenshot({ path: path.join(output, 'failure.png') })
      .catch(() => {});
    fs.writeFileSync(
      path.join(output, 'failure.txt'),
      error.stack + '\nPage errors: ' + JSON.stringify(errors),
    );
    throw error;
  } finally {
    if (project) await post('/api/project/delete', { project });
    fs.writeFileSync(
      path.join(output, 'results.json'),
      JSON.stringify({ server, results, pageErrors: errors }, null, 2),
    );
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});

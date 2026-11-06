// Standalone regression against the actual docassemble CodeMirror bundle.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const { default: AxeBuilder } = require('@axe-core/playwright');
const staticDir = path.resolve(
  __dirname,
  '../docassemble/ALWeaver/data/static',
);
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.BROWSER_PATH,
  });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setContent(
      '<html lang="en"><title>Source tools</title><main><h1>Source tools</h1><div id="full-source-editor" class="editor-source-container"></div></main></html>',
    );
    await page.addStyleTag({ path: path.join(staticDir, 'editor.css') });
    await page.addScriptTag({ path: process.env.DOCASSEMBLE_CM6 });
    await page.addScriptTag({
      path: path.join(staticDir, 'editor_source_tools.js'),
    });
    await page.evaluate(() => {
      window.daAutoComp = window.ALWeaverSourceTools.completions(
        { project_variables: ['users.name', 'answer'] },
        [],
        [],
      );
      window.bundle = window.daNewEditor(
        document.getElementById('full-source-editor'),
        'users.na\nquestion: Hello\n',
        'yaml',
        'default',
        true,
      );
      window.bundle.ev.contentDOM.setAttribute('aria-label', 'YAML source');
      window.findingIndex = null;
      window.tools = window.ALWeaverSourceTools.attach(
        window.bundle,
        document.getElementById('full-source-editor'),
        {
          validate() {},
          findings(index) {
            window.findingIndex = index;
          },
          symbols() {
            return window.daAutoComp;
          },
        },
      );
      window.bundle.ev.dispatch({ selection: { anchor: 8 } });
    });
    await page.locator('.cm-content').focus();
    await page.keyboard.press('Control+Space');
    await page.getByRole('option', { name: /users.name/ }).waitFor();
    // CM intentionally ignores acceptance keys during its short interaction delay.
    await page.waitForTimeout(150);
    await page.keyboard.press('Enter');
    assert.equal(
      await page.evaluate(() => window.bundle.ev.state.doc.toString()),
      'users.name\nquestion: Hello\n',
    );
    await page.keyboard.press('Control+z');
    assert.equal(
      await page.evaluate(() => window.bundle.ev.state.doc.toString()),
      'users.na\nquestion: Hello\n',
    );
    await page.evaluate(() => {
      window.tools.setDiagnostics({
        source: window.bundle.ev.state.doc.toString(),
        filename: 'main.yml',
        diagnostics: [
          { line_number: 1, message: 'First problem', level: 'error' },
          { line_number: 2, message: 'Second problem', level: 'warning' },
          {
            filename: 'other.yml',
            line_number: 1,
            message: 'Other file',
            level: 'error',
          },
        ],
      });
    });
    await page
      .getByRole('button', { name: 'Line 2: Second problem', exact: true })
      .waitFor();
    assert.equal(
      await page.locator('.editor-source-diagnostic-marker').count(),
      2,
    );
    assert.equal(
      await page.evaluate(
        () => CSS.highlights.get('weaver-source-warning').size,
      ),
      1,
    );
    await page.screenshot({ path: '/tmp/weaver-source-tools.png' });
    const accessibility = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    assert.deepEqual(
      accessibility.violations.map((item) => item.id),
      [],
    );
    await page
      .getByRole('button', { name: 'Next problem', exact: true })
      .click();
    assert.equal(
      await page.evaluate(
        () =>
          window.bundle.ev.state.doc.lineAt(
            window.bundle.ev.state.selection.main.from,
          ).number,
      ),
      2,
    );
    await page
      .getByRole('button', { name: 'Line 1: First problem', exact: true })
      .click();
    assert.equal(await page.evaluate(() => window.findingIndex), 0);
    await page.keyboard.type('changed');
    await page.waitForFunction(() =>
      document
        .querySelector('.editor-source-tools [role="status"]')
        .textContent.includes('Source changed'),
    );
    assert.equal(
      await page.locator('.editor-source-diagnostic-marker').count(),
      0,
    );
    assert.equal(
      await page
        .getByRole('button', { name: 'Next problem', exact: true })
        .isDisabled(),
      true,
    );
    await page.keyboard.press('Control+z');
    await page
      .getByRole('button', { name: 'Line 1: First problem', exact: true })
      .waitFor();
    await page.evaluate(() => {
      window.bundle.ev.dispatch({ selection: { anchor: 0 } });
      window.tools.setDiagnostics({
        source: window.bundle.ev.state.doc.toString(),
        filename: 'main.yml',
        diagnostics: [
          {
            line_number: 1,
            message: 'Warning at same location',
            level: 'warning',
          },
          { line_number: 1, message: 'Error at same location', level: 'error' },
        ],
      });
    });
    await page.waitForFunction(
      () =>
        document.querySelector('.editor-source-diagnostic-marker.error')
          ?.textContent === '!',
    );
    await page
      .getByRole('button', { name: 'Next problem', exact: true })
      .click();
    assert.match(
      await page.locator('.editor-source-tools [role=status]').textContent(),
      /Warning at same location/,
    );
    await page
      .getByRole('button', { name: 'Next problem', exact: true })
      .click();
    assert.match(
      await page.locator('.editor-source-tools [role=status]').textContent(),
      /Error at same location/,
    );
    assert.equal(
      await page.evaluate(() => window.bundle.ev.state.selection.main.empty),
      true,
    );
    await page.evaluate(() => {
      window.tools.dispose();
      window.bundle.ev.destroy();
    });
    assert.equal(await page.locator('.editor-source-tools').count(), 0);
    assert.equal(
      await page.evaluate(() => CSS.highlights.has('weaver-source-error')),
      false,
    );
    assert.deepEqual(errors, []);
    console.log('source tools browser regression passed');
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

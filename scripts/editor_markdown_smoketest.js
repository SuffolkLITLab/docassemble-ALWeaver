// Standalone browser regression using the installed Docassemble CM6 bundle.
// NODE_PATH must contain playwright and axe-core; DOCASSEMBLE_CM6 points to
// static/app/cm6.js. test_editor_frontend.py runs this when both are present.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const staticDir = path.join(root, 'docassemble/ALWeaver/data/static');
const editorSource = fs.readFileSync(path.join(staticDir, 'editor.js'), 'utf8');

function editorFunction(name) {
  const start = editorSource.indexOf('  function ' + name + '(');
  assert.notEqual(start, -1, name);
  return editorSource.slice(start, editorSource.indexOf('\n  }\n', start) + 4);
}

function htmlPage(body) {
  return (
    '<html lang="en"><head><title>Markdown fields</title></head><body><main><h1>Markdown editor test</h1>' +
    body +
    '</main></body></html>'
  );
}

// A page with editor.css, optionally the CM6 bundle, and editor_markdown.js.
// `daNewEditor` is wrapped so tests can reach each CodeMirror view.
async function openPage(browser, body, options = {}) {
  const page = await browser.newPage();
  if (options.colorScheme)
    await page.emulateMedia({ colorScheme: options.colorScheme });
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  await page.setContent(htmlPage(body));
  await page.addStyleTag({ path: path.join(staticDir, 'editor.css') });
  if (options.cm6 !== false) {
    await page.addScriptTag({ path: process.env.DOCASSEMBLE_CM6 });
    await page.evaluate(() => {
      const create = window.daNewEditor;
      window.views = [];
      window.daNewEditor = (...args) => {
        window.editorMode = args[2];
        const bundle = create(...args);
        window.views.push(bundle.ev);
        window.testView = bundle.ev;
        return bundle;
      };
    });
  }
  await page.addScriptTag({ path: path.join(staticDir, 'editor_markdown.js') });
  for (const name of options.functions || [])
    await page.addScriptTag({ content: editorFunction(name) });
  return page;
}

async function axeViolations(page) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(
    async () => (await axe.run(document)).violations,
  );
  return violations.map((v) => ({
    id: v.id,
    nodes: v.nodes.map((n) => n.target),
  }));
}

const nextFrames = (page) =>
  page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );

const scenarios = {
  async editingRoundTrip(browser) {
    const page = await openPage(
      browser,
      '<button id="before">Before</button><label for="question">Question</label><textarea id="question"></textarea><button id="after">After</button><label for="disabled">Read-only mapping</label><textarea id="disabled" disabled>Complex mapping</textarea>',
      { functions: ['insertTextAtCursor'] },
    );
    const original =
      '# Heading\n\n**Hello** ${ {"name": "}"} }\n% if ready:\n- [Link](https://example.com)\n% endif\n\n';
    await page.evaluate((value) => {
      const input = document.querySelector('#question');
      input.value = value;
      window.changes = 0;
      input.addEventListener('input', () => window.changes++);
      document.querySelector('#before').focus();
      window.enhanced = [
        WeaverMarkdown.enhance(input),
        WeaverMarkdown.enhance(document.querySelector('#disabled')),
        WeaverMarkdown.enhance(input),
      ];
    }, original);
    // Disabled fields stay plain; enhancing twice reports the existing editor.
    assert.deepEqual(await page.evaluate(() => window.enhanced), [
      true,
      false,
      true,
    ]);
    assert.equal(await page.locator('.cm-editor').count(), 1);
    assert.equal(
      await page.evaluate(
        () =>
          WeaverMarkdown.control(document.querySelector('#question')).className,
      ),
      'editor-markdown',
    );
    assert.equal(await page.evaluate(() => window.editorMode), 'md');
    assert.equal(await page.locator('#question').inputValue(), original);
    assert.equal(await page.evaluate(() => window.changes), 0);
    assert.equal(
      await page.evaluate(() => document.activeElement.id),
      'before',
    );
    await page.waitForFunction(
      () => CSS.highlights.get('weaver-mako')?.size === 3,
    );
    assert.ok((await page.locator('.cm-content span').count()) > 0);
    await page.locator('label[for="question"]').click();
    assert.equal(
      await page.evaluate(() => document.activeElement === testView.contentDOM),
      true,
    );
    // Focus inside the editor resolves to the textarea that carries the
    // field's data attributes (symbol typeahead and label tools read them).
    assert.equal(
      await page.evaluate(
        () => WeaverMarkdown.source(document.activeElement).id,
      ),
      'question',
    );
    await page.evaluate(() => {
      testView.dispatch({ selection: { anchor: 14, head: 19 } });
      insertTextAtCursor(document.querySelector('#question'), '', {
        wrapSelectionPrefix: '**',
        wrapSelectionSuffix: '**',
      });
    });
    const formatted = await page.locator('#question').inputValue();
    assert.equal(
      formatted,
      original.slice(0, 14) +
        '**' +
        original.slice(14, 19) +
        '**' +
        original.slice(19),
    );
    assert.equal(
      await page.evaluate(() => testView.state.doc.toString()),
      formatted,
    );
    await page.keyboard.press('Control+z');
    assert.equal(await page.locator('#question').inputValue(), original);
    await page.keyboard.press('Control+Shift+z');
    assert.equal(await page.locator('#question').inputValue(), formatted);
    await page.keyboard.insertText('typed');
    assert.equal(
      await page.locator('#question').inputValue(),
      await page.evaluate(() => testView.state.doc.toString()),
    );
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'after');
    await page.keyboard.press('Shift+Tab');
    assert.equal(
      await page.evaluate(() => document.activeElement === testView.contentDOM),
      true,
    );
    await page.evaluate(() =>
      WeaverMarkdown.dispose(document.querySelector('main')),
    );
    assert.equal(await page.locator('.cm-editor').count(), 0);
    assert.equal(await page.locator('#question').isVisible(), true);
    assert.equal(
      await page.evaluate(() => CSS.highlights.get('weaver-mako').size),
      0,
    );
    assert.deepEqual(page.errors, []);
  },

  // Saving an empty question shows an error; "Leave this question label
  // blank" then drops `required` with no input event, which must clear it.
  async validityFollowsRequired(browser) {
    const page = await openPage(
      browser,
      '<label for="question">Question</label><textarea id="question" required></textarea><label><input type="checkbox" id="allow"> Leave this question label blank</label>',
    );
    await page.evaluate(() => {
      WeaverMarkdown.enhance(document.querySelector('#question'));
      const input = document.querySelector('#question');
      input.setCustomValidity('Add a question label before saving.');
      input.reportValidity();
    });
    const alert = page.locator('.editor-markdown [role="alert"]');
    assert.equal(
      await alert.textContent(),
      'Add a question label before saving.',
    );
    assert.equal(
      await page.evaluate(() => document.activeElement === testView.contentDOM),
      true,
    );
    const ariaState = () =>
      page.evaluate(() => [
        testView.contentDOM.getAttribute('aria-invalid'),
        testView.contentDOM.getAttribute('aria-required'),
      ]);
    assert.deepEqual(await ariaState(), ['true', 'true']);
    // Same steps as setBlankQuestionAllowed(true) in editor.js.
    await page.evaluate(() => {
      const input = document.querySelector('#question');
      input.required = false;
      input.setCustomValidity('');
    });
    await page.waitForFunction(
      () => !testView.contentDOM.hasAttribute('aria-invalid'),
    );
    assert.equal(await alert.isVisible(), false);
    assert.deepEqual(await ariaState(), [null, 'false']);
    // Unticking makes the label required again without showing a new error.
    await page.evaluate(() => {
      document.querySelector('#question').required = true;
    });
    await page.waitForFunction(
      () => testView.contentDOM.getAttribute('aria-required') === 'true',
    );
    assert.equal(await alert.isVisible(), false);
    // Typing still clears an error, as before.
    await page.evaluate(() =>
      document.querySelector('#question').reportValidity(),
    );
    assert.equal(await alert.isVisible(), true);
    await page.keyboard.insertText('What is your name?');
    await page.waitForFunction(
      () => !testView.contentDOM.hasAttribute('aria-invalid'),
    );
    assert.equal(await alert.isVisible(), false);
    assert.deepEqual(page.errors, []);
  },

  // Attachment mappings: the editor must sit inside the expression group next
  // to its button, whichever of enhance/annotate runs first, and each editor
  // is named by its template field.
  async attachmentRowsKeepExpressionButton(browser) {
    const row = (id, name) =>
      '<tr><th scope="row"><label for="' +
      id +
      '">' +
      name +
      '</label></th><td><textarea class="form-control font-monospace" rows="2" id="' +
      id +
      '" data-attachment-field="' +
      name +
      '" data-symbol-role="variable">${ ' +
      name +
      ' }</textarea></td></tr>';
    const page = await openPage(
      browser,
      '<section id="mappings"><table class="table"><thead><tr><th scope="col">Template field</th><th scope="col">Text or Mako expression</th></tr></thead><tbody>' +
        row('enhance-first', 'users[0].name.first') +
        row('annotate-first', 'docket_number') +
        '</tbody></table></section>',
      { functions: ['annotateExpressionInputs'] },
    );
    await page.evaluate(() => {
      WeaverMarkdown.enhance(document.querySelector('#enhance-first'));
      annotateExpressionInputs();
      WeaverMarkdown.enhance(document.querySelector('#annotate-first'));
    });
    for (const id of ['enhance-first', 'annotate-first']) {
      const order = await page.evaluate(
        (inputId) =>
          Array.from(
            document.getElementById(inputId).closest('.expression-input-group')
              .children,
          ).map((el) => el.tagName.toLowerCase() + '.' + el.className),
        id,
      );
      assert.deepEqual(
        order,
        [
          'textarea.form-control font-monospace editor-markdown-original',
          'div.editor-markdown',
          'button.btn btn-sm btn-outline-secondary',
        ],
        id,
      );
      const group = page.locator('#' + id).locator('xpath=..');
      const editorBox = await group.locator('.editor-markdown').boundingBox();
      const buttonBox = await group.locator('button').boundingBox();
      assert.ok(
        buttonBox.x >= editorBox.x + editorBox.width &&
          Math.abs(buttonBox.y - editorBox.y) < 2,
        id + ': expression button is beside its editor',
      );
    }
    for (const name of ['users[0].name.first', 'docket_number'])
      assert.equal(
        await page.getByRole('textbox', { name, exact: true }).count(),
        1,
        name,
      );
    assert.deepEqual(await axeViolations(page), []);
    assert.deepEqual(page.errors, []);
  },

  // Editors are named only from the textarea's own label; an unnamed textarea
  // is not given an invented name that hides the missing label from axe.
  async accessibleNames(browser) {
    const page = await openPage(
      browser,
      '<label for="labelled">Question</label><textarea id="labelled"></textarea>' +
        '<span id="external">Subquestion</span><textarea id="by-id" aria-labelledby="external"></textarea>' +
        '<textarea id="aria" aria-label="Field label"></textarea>' +
        '<textarea id="unnamed"></textarea><input id="single" aria-label="Single line">',
    );
    await page.evaluate(() => {
      window.enhanced = ['labelled', 'by-id', 'aria', 'unnamed', 'single'].map(
        (id) => WeaverMarkdown.enhance(document.getElementById(id)),
      );
    });
    assert.deepEqual(await page.evaluate(() => window.enhanced), [
      true,
      true,
      true,
      true,
      false,
    ]);
    for (const name of ['Question', 'Subquestion', 'Field label'])
      assert.equal(
        await page.getByRole('textbox', { name, exact: true }).count(),
        1,
        name,
      );
    const unnamed = await page.evaluate(() => {
      const content = WeaverMarkdown.control(
        document.getElementById('unnamed'),
      ).querySelector('.cm-content');
      return [
        content.getAttribute('aria-label'),
        content.getAttribute('aria-labelledby'),
      ];
    });
    assert.deepEqual(unnamed, [null, null]);
    const violations = await axeViolations(page);
    assert.deepEqual(
      violations.map((v) => v.id),
      ['aria-input-field-name'],
    );
    assert.equal(violations[0].nodes.length, 1);
    assert.deepEqual(page.errors, []);
  },

  // Under a dark OS scheme cm6 switches to oneDark; its light text must keep
  // oneDark's dark background, in both schemes the text passes contrast.
  async contrastInBothSchemes(browser) {
    for (const colorScheme of ['light', 'dark']) {
      const page = await openPage(
        browser,
        '<label for="question">Question</label><textarea id="question">Plain prose and ${ users[0].name }</textarea>',
        { colorScheme },
      );
      await page.evaluate(() =>
        WeaverMarkdown.enhance(document.querySelector('#question')),
      );
      await page.waitForFunction(
        () => CSS.highlights.get('weaver-mako')?.size === 1,
      );
      assert.deepEqual(await axeViolations(page), [], colorScheme);
      assert.deepEqual(page.errors, [], colorScheme);
      await page.close();
    }
  },

  // An editor whose textarea was removed some other way is destroyed by the
  // next dispose, wherever it is aimed, and the textarea can be enhanced anew.
  async disposeDetachedEditors(browser) {
    const page = await openPage(
      browser,
      '<div id="canvas"><label for="question">Question</label><textarea id="question">${ x }</textarea></div><div id="modal"></div>',
    );
    await page.evaluate(() =>
      WeaverMarkdown.enhance(document.querySelector('#question')),
    );
    await page.waitForFunction(
      () => CSS.highlights.get('weaver-mako')?.size === 1,
    );
    await page.evaluate(() => {
      window.detached = document.querySelector('#question');
      window.firstView = testView;
      document.querySelector('#canvas').replaceChildren();
      WeaverMarkdown.dispose(document.querySelector('#modal'));
    });
    assert.equal(
      await page.evaluate(() => CSS.highlights.get('weaver-mako').size),
      0,
    );
    assert.equal(
      await page.evaluate(
        () => WeaverMarkdown.control(window.detached) === window.detached,
      ),
      true,
    );
    await page.evaluate(() => {
      document.querySelector('#canvas').append(window.detached);
      window.reenhanced = WeaverMarkdown.enhance(window.detached);
    });
    assert.equal(await page.evaluate(() => window.reenhanced), true);
    assert.equal(
      await page.evaluate(() => testView !== window.firstView),
      true,
    );
    assert.equal(await page.locator('.cm-editor').count(), 1);
    assert.deepEqual(page.errors, []);
  },

  // The completion source reads window.daAutoComp; a Markdown field can be
  // the first CodeMirror editor on the page.
  async completionWithoutSourceEditor(browser) {
    const page = await openPage(
      browser,
      '<label for="question">Question</label><textarea id="question">user</textarea>',
    );
    await page.evaluate(() => {
      delete window.daAutoComp;
      WeaverMarkdown.enhance(document.querySelector('#question'));
    });
    assert.equal(
      await page.evaluate(() => Array.isArray(window.daAutoComp)),
      true,
    );
    await page.locator('.cm-content').click();
    await page.keyboard.press('End');
    await page.keyboard.press('Control+Space');
    await nextFrames(page);
    await page.waitForTimeout(100);
    assert.deepEqual(page.errors, []);
  },

  // Cursor movement leaves the text in place, so it must not re-tokenize and
  // rebuild every highlight range; typing still repaints.
  async cursorMovesDoNotRepaint(browser) {
    const page = await openPage(
      browser,
      '<label for="question">Question</label><textarea id="question">${ a } and ${ b }\n% if c:\nyes\n% endif</textarea>',
    );
    await page.evaluate(() => {
      window.added = 0;
      const add = Highlight.prototype.add;
      Highlight.prototype.add = function (...args) {
        window.added++;
        return add.apply(this, args);
      };
      WeaverMarkdown.enhance(document.querySelector('#question'));
    });
    await page.waitForFunction(
      () => CSS.highlights.get('weaver-mako')?.size === 4,
    );
    const afterMount = await page.evaluate(() => window.added);
    await page.locator('.cm-content').click();
    for (let i = 0; i < 10; i++) await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowDown');
    await nextFrames(page);
    assert.equal(await page.evaluate(() => window.added), afterMount);
    assert.equal(
      await page.evaluate(() =>
        Array.from(CSS.highlights.get('weaver-mako')).every(
          (range) => !range.collapsed && range.startContainer.isConnected,
        ),
      ),
      true,
    );
    await page.keyboard.press('Control+End');
    await page.keyboard.insertText('\nthen ${ d }');
    await page.waitForFunction(
      () => CSS.highlights.get('weaver-mako').size === 5,
    );
    assert.deepEqual(page.errors, []);
  },

  // Without the CM6 bundle the textarea stays as it was, so editor.js can
  // fall back to auto-resizing it.
  async withoutBundle(browser) {
    const page = await openPage(
      browser,
      '<label for="question">Question</label><textarea id="question">Text</textarea>',
      { cm6: false },
    );
    assert.equal(
      await page.evaluate(() =>
        WeaverMarkdown.enhance(document.querySelector('#question')),
      ),
      false,
    );
    assert.equal(await page.locator('#question').isVisible(), true);
    assert.equal(await page.locator('.editor-markdown').count(), 0);
    assert.deepEqual(page.errors, []);
  },
};

(async () => {
  const only = process.argv[2];
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [name, scenario] of Object.entries(scenarios)) {
      if (only && name !== only) continue;
      await scenario(browser);
      console.log('ok - ' + name);
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

// Standalone browser regression using the installed Docassemble CM6 bundle.
// NODE_PATH must contain playwright and axe-core; DOCASSEMBLE_CM6 points to
// static/app/cm6.js. test_editor_frontend.py runs this when both are present.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const playwright = require('playwright');
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
  const page = await browser.newPage(options.context || {});
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

async function expressionPage(browser, text, context = {}) {
  const page = await openPage(
    browser,
    '<label for="question">Question</label><textarea id="question"></textarea>' +
      '<label for="subquestion">Subquestion</label><textarea id="subquestion">Other ${ x }</textarea>' +
      '<button id="outside">Outside</button>',
    { context },
  );
  await page.exposeFunction('parsePython', (source, context) => {
    const result = spawnSync(
      process.env.PYTHON || 'python3',
      [
        '-c',
        'import json,runpy,sys; p=runpy.run_path(sys.argv[1]); print(json.dumps(p["parse_expression"](**json.load(sys.stdin))))',
        path.join(root, 'docassemble/ALWeaver/editor_expressions.py'),
      ],
      { input: JSON.stringify({ source, context }), encoding: 'utf8' },
    );
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
  });
  await page.addScriptTag({
    path: path.join(staticDir, 'editor_expressions.js'),
  });
  await page.evaluate((text) => {
    const editor = WeaverExpressions.install({
      annotate() {},
      variables: () => ['monthly_income', 'annual_income', 'users'],
      parse: (source, context) => {
        if (window.failParse)
          return Promise.reject(
            new Error('Parser unavailable. Cancel and use Edit in text.'),
          );
        return window.parsePython(source, context);
      },
      createSource(id, value) {
        const bundle = daNewEditor(
          document.getElementById(id),
          value,
          'python',
          'default',
          true,
        );
        const view = bundle.ev;
        view.contentDOM.setAttribute('aria-label', 'Python expression');
        window.draftView = view;
        return {
          getValue: () => view.state.doc.toString(),
          setValue(value) {
            view.dispatch({
              changes: { from: 0, to: view.state.doc.length, insert: value },
            });
          },
          dispose() {
            view.destroy();
          },
        };
      },
    });
    WeaverMarkdown.setExpressionEditor(editor);
    const input = document.querySelector('#question');
    input.value = text;
    WeaverMarkdown.enhance(input);
    window.questionView = window.testView;
    WeaverMarkdown.enhance(document.querySelector('#subquestion'));
    window.changeCount = 0;
    input.addEventListener('input', () => window.changeCount++);
  }, text);
  return page;
}

async function tokenPoint(page, pos) {
  return page.evaluate((pos) => {
    const rect = questionView.coordsAtPos(pos);
    return { x: rect.left + 1, y: (rect.top + rect.bottom) / 2 };
  }, pos);
}

async function hoverToken(page, pos) {
  const point = await tokenPoint(page, pos);
  await page.mouse.move(point.x, point.y);
  await page
    .getByRole('group', { name: 'Mako expression', exact: true })
    .waitFor();
}

async function openAt(page, pos) {
  await hoverToken(page, pos);
  await page
    .getByRole('button', { name: 'Edit expression', exact: true })
    .click();
  await page.locator('dialog.expression-dialog').waitFor();
  await page.waitForFunction(
    () =>
      !document
        .querySelector('.expression-status')
        .textContent.includes('Checking'),
  );
}

async function draft(page, value) {
  await page.getByRole('button', { name: 'Python', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Python expression', exact: true })
    .fill(value);
}

const scenarios = {
  async contextualTypingFailuresAndHistory(browser) {
    const page = await expressionPage(browser, 'Hello ${ value }.');
    const control = page.getByRole('textbox', {
      name: 'Question',
      exact: true,
    });
    await control.focus();
    await control.press('Control+End');
    await page.keyboard.insertText(' Earlier prose.');
    const before = await page.locator('#question').inputValue();
    await openAt(page, 12);
    await draft(page, 'changed');
    await page.mouse.click(1, 1);
    assert.equal(await page.locator('dialog[open]').count(), 1);
    assert.equal(
      await page.evaluate(() => draftView.state.doc.toString()),
      'changed',
    );
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    await page.locator('dialog').waitFor({ state: 'detached' });
    await page.keyboard.press('Control+z');
    assert.equal(
      await page.locator('#question').inputValue(),
      before,
      'Undo preserves earlier prose edits',
    );
    await openAt(page, 12);
    await page.locator('.expression-picker input').fill('mon');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('dialog[open]').count(), 1);
    assert.equal(
      await page.locator('.expression-suggestions:visible').count(),
      0,
    );
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('dialog').count(), 0);
    await page.evaluate(() => {
      window.failParse = true;
    });
    await openAt(page, 12);
    assert.match(
      await page.locator('.expression-status').textContent(),
      /unavailable/,
    );
    await draft(page, 'replacement');
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    await page.waitForFunction(() =>
      document
        .querySelector('dialog [role="alert"]')
        .textContent.includes('unavailable'),
    );
    assert.equal(await page.locator('#question').inputValue(), before);
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.evaluate(() => {
      questionView.focus();
      questionView.dispatch({ selection: { anchor: 12 } });
    });
    await page.keyboard.insertText('typing');
    await nextFrames(page);
    assert.equal(
      await page.locator('.mako-expression-popover').count(),
      0,
      'Typing must not rebuild the action over prose',
    );
    assert.deepEqual(page.errors, []);
    await page.close();
  },
  async contextualEditing(browser) {
    const original =
      '😀 **Income** ${ currency(monthly_income) } and ${ currency(monthly_income) }.\nKeep this prose.';
    const page = await expressionPage(browser, original);
    await page.locator('#outside').focus();
    const selection = await page.evaluate(() =>
      questionView.state.selection.toJSON(),
    );
    const second = original.lastIndexOf('${') + 5;
    await hoverToken(page, second);
    assert.equal(
      await page.evaluate(() => document.activeElement.id),
      'outside',
    );
    assert.deepEqual(
      await page.evaluate(() => questionView.state.selection.toJSON()),
      selection,
    );
    assert.equal(await page.evaluate(() => window.changeCount), 0);
    await page
      .getByRole('button', { name: 'Edit expression', exact: true })
      .hover();
    await page.waitForTimeout(450);
    await page
      .getByRole('button', { name: 'Edit expression', exact: true })
      .click();
    await page.waitForFunction(
      () => document.querySelector('.expression-guided')?.hidden === false,
    );
    assert.equal(
      await page.evaluate(() => draftView.state.doc.toString()),
      'currency(monthly_income)',
    );
    assert.equal(
      await page.locator('.expression-origin').textContent(),
      'Question',
    );
    await draft(page, 'currency(annual_income)');
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    await page.locator('dialog').waitFor({ state: 'detached' });
    const expected =
      original.slice(0, original.lastIndexOf('monthly_income')) +
      'annual_income' +
      original.slice(
        original.lastIndexOf('monthly_income') + 'monthly_income'.length,
      );
    assert.equal(await page.locator('#question').inputValue(), expected);
    assert.equal(
      await page.locator('#subquestion').inputValue(),
      'Other ${ x }',
    );
    assert.equal(
      await page.evaluate(
        () => document.activeElement === questionView.contentDOM,
      ),
      true,
    );
    await page.keyboard.press('Control+z');
    assert.equal(await page.locator('#question').inputValue(), original);
    await page.keyboard.press('Control+Shift+z');
    assert.equal(await page.locator('#question').inputValue(), expected);
    assert.deepEqual(page.errors, []);
    await page.close();
  },
  async contextualCancelNoopAndKeyboard(browser) {
    const original = 'Hello ${  user.name  }.';
    const page = await expressionPage(browser, original);
    await page.evaluate(() => {
      questionView.focus();
      questionView.dispatch({ selection: { anchor: 12 } });
    });
    await nextFrames(page);
    await page.keyboard.press('Tab');
    assert.equal(
      await page.evaluate(() => document.activeElement.textContent),
      'Edit expression',
    );
    await page.keyboard.press('Space');
    await page.locator('dialog').waitFor();
    await page.getByRole('button', { name: 'Python', exact: true }).click();
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    await page.locator('dialog').waitFor({ state: 'detached' });
    assert.equal(await page.locator('#question').inputValue(), original);
    assert.equal(await page.evaluate(() => window.changeCount), 0);
    for (const action of ['Cancel', 'Escape', 'Close expression editor']) {
      await openAt(page, 12);
      await draft(page, 'changed');
      if (action === 'Escape') await page.keyboard.press('Escape');
      else
        await page.getByRole('button', { name: action, exact: true }).click();
      await page.locator('dialog').waitFor({ state: 'detached' });
      assert.equal(await page.locator('#question').inputValue(), original);
      assert.equal(await page.evaluate(() => window.changeCount), 0);
    }
    await hoverToken(page, 12);
    await page
      .getByRole('button', { name: 'Edit expression', exact: true })
      .focus();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.mako-expression-popover').count(), 0);
    assert.deepEqual(page.errors, []);
    await page.close();
  },
  async contextualValidationAndStaleSource(browser) {
    const page = await expressionPage(browser, '${ value }');
    await openAt(page, 5);
    for (const invalid of [
      '',
      'x +',
      'value | h',
      'value # closing delimiter would be commented out',
    ]) {
      await draft(page, invalid);
      await page
        .getByRole('button', { name: 'Apply expression', exact: true })
        .click();
      await page.waitForFunction(
        () =>
          document.querySelector('dialog [role="alert"]').textContent.length >
          0,
      );
      assert.equal(
        await page.evaluate(() => draftView.state.doc.toString()),
        invalid,
      );
      assert.equal(await page.locator('#question').inputValue(), '${ value }');
    }
    await draft(page, '[x for x in items]');
    await page
      .getByRole('button', { name: 'Expression editor', exact: true })
      .click();
    await page.waitForFunction(() =>
      document
        .querySelector('.expression-status')
        .textContent.startsWith('Advanced Python'),
    );
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    await page.locator('dialog').waitFor({ state: 'detached' });
    assert.equal(
      await page.locator('#question').inputValue(),
      '${ [x for x in items] }',
    );
    await openAt(page, 5);
    await draft(page, 'new_name');
    // Change and then restore the same field string: the revision still changed.
    await page.evaluate(() => {
      questionView.dispatch({ changes: { from: 0, insert: 'x' } });
      questionView.dispatch({ changes: { from: 0, to: 1, insert: '' } });
    });
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    assert.match(
      await page.locator('dialog [role="alert"]').textContent(),
      /text changed/,
    );
    assert.equal(
      await page.evaluate(() => draftView.state.doc.toString()),
      'new_name',
    );
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await openAt(page, 5);
    await draft(page, 'replacement');
    await page.evaluate(() => {
      WeaverMarkdown.dispose(document.querySelector('#question').parentElement);
      WeaverMarkdown.enhance(document.querySelector('#question'));
      window.questionView = window.testView;
    });
    await page
      .getByRole('button', { name: 'Apply expression', exact: true })
      .click();
    assert.match(
      await page.locator('dialog [role="alert"]').textContent(),
      /text changed/,
    );
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal(await page.locator('.mako-expression-popover').count(), 0);
    assert.deepEqual(page.errors, []);
    await page.close();
  },
  async contextualTouchFallbackAndAccessibility(browser) {
    const page = await expressionPage(
      browser,
      'Income ${ currency(monthly_income) }',
      { hasTouch: true, viewport: { width: 768, height: 1024 } },
    );
    const point = await tokenPoint(page, 14);
    await page.touchscreen.tap(point.x, point.y);
    await page
      .getByRole('button', { name: 'Edit expression', exact: true })
      .tap();
    await page.waitForFunction(
      () => document.querySelector('.expression-guided')?.hidden === false,
    );
    assert.equal(await page.locator('dialog').count(), 1);
    assert.deepEqual(await axeViolations(page), []);
    for (const viewport of [
      { width: 375, height: 480 },
      { width: 1024, height: 768 },
    ]) {
      await page.setViewportSize(viewport);
      await nextFrames(page);
      const rect = await page.locator('dialog').boundingBox();
      assert.ok(rect.x >= 0 && rect.x + rect.width <= viewport.width);
      await page
        .getByRole('button', { name: 'Apply expression', exact: true })
        .scrollIntoViewIfNeeded();
    }
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page
      .getByRole('textbox', { name: 'Question', exact: true })
      .fill('${ value | h }');
    await hoverToken(page, 5);
    await page
      .getByRole('button', { name: 'Edit in text', exact: true })
      .click();
    assert.equal(
      await page.evaluate(() =>
        questionView.state.sliceDoc(
          questionView.state.selection.main.from,
          questionView.state.selection.main.to,
        ),
      ),
      '${ value | h }',
    );
    assert.equal(await page.locator('dialog').count(), 0);
    assert.deepEqual(page.errors, []);
    await page.close();
  },
  async makoRangesStayWithinExpressions(browser) {
    const prose =
      "The bond ensures that ${ children[0] } will receive compensation for financial harm if a guardian mishandles their estate.\n\nFor example, if a guardian uses money from ${ children[0].familiar() }'s bank account to pay for their own personal expenses, ${ children[0].familiar() } can use the bond to get that money back.";
    const page = await openPage(
      browser,
      '<label for="question">Question</label><textarea id="question"></textarea>',
    );
    await page.evaluate((text) => {
      const input = document.querySelector('#question');
      input.value = text;
      WeaverMarkdown.enhance(input);
    }, prose);
    const expected = [
      '${ children[0] }',
      '${ children[0].familiar() }',
      '${ children[0].familiar() }',
    ];
    const checkRanges = async () => {
      await nextFrames(page);
      assert.deepEqual(
        await page.evaluate(() =>
          Array.from(CSS.highlights.get('weaver-mako'), (range) =>
            range.toString(),
          ),
        ),
        expected,
      );
    };
    await checkRanges();
    for (let pos = 0; pos <= prose.length; pos++) {
      await page.evaluate(
        (anchor) => testView.dispatch({ selection: { anchor } }),
        pos,
      );
      await checkRanges();
    }
    await page.locator('.cm-content').click();
    await page.keyboard.press('Control+Home');
    await page.keyboard.press('Control+Shift+End');
    await checkRanges();
    await page.keyboard.insertText(prose);
    await checkRanges();
    await page.waitForTimeout(500);
    await checkRanges();
    assert.deepEqual(page.errors, []);
    await page.close();
  },
  // Real-server smoke checks edit the visible control and read the source.
  async visibleControlEditing(browser) {
    for (const cm6 of [true, false]) {
      const page = await openPage(
        browser,
        '<label for="q-subquestion">Subquestion</label><textarea id="q-subquestion"></textarea>',
        { cm6 },
      );
      await page.evaluate(() =>
        WeaverMarkdown.enhance(document.querySelector('#q-subquestion')),
      );
      const control = page.getByRole('textbox', {
        name: 'Subquestion',
        exact: true,
      });
      await control.waitFor({ state: 'visible' });
      await control.fill('Edited introduction.\n');
      await control.press('Control+End');
      await page.keyboard.insertText('Appended help');
      assert.equal(
        await page.locator('#q-subquestion').inputValue(),
        'Edited introduction.\nAppended help',
      );
      assert.deepEqual(page.errors, []);
      await page.close();
    }
  },

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
        '<label for="question">Question</label><textarea id="question">Plain prose and ${ users[0].first_name }</textarea>',
        { colorScheme },
      );
      await page.evaluate(() =>
        WeaverMarkdown.enhance(document.querySelector('#question')),
      );
      await page.waitForFunction(
        () => CSS.highlights.get('weaver-mako')?.size === 1,
      );
      // Axe does not inspect CSS Highlight foregrounds. Measure the actual
      // Mako color against both the editor and its drawn selection layer.
      for (const state of ['unselected', 'selected', 'blurred']) {
        await page.evaluate((state) => {
          if (state === 'selected') {
            testView.focus();
            testView.dispatch({ selection: { anchor: 16, head: 38 } });
          } else if (state === 'blurred') testView.contentDOM.blur();
        }, state);
        await nextFrames(page);
        const result = await page.evaluate((state) => {
          const content = testView.contentDOM;
          const style = getComputedStyle(content, '::highlight(weaver-mako)');
          const rgb = (color) => color.match(/[\d.]+/g).map(Number);
          const luminance = (color) =>
            rgb(color)
              .slice(0, 3)
              .reduce((sum, c, i) => {
                c /= 255;
                return (
                  sum +
                  (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4) *
                    [0.2126, 0.7152, 0.0722][i]
                );
              }, 0);
          let background = 'rgb(255, 255, 255)';
          const layer =
            state === 'unselected'
              ? content
              : testView.dom.querySelector('.cm-selectionBackground');
          for (let node = layer; node; node = node.parentElement) {
            const color = getComputedStyle(node).backgroundColor;
            if (rgb(color)[3] === 0) continue;
            background = color;
            break;
          }
          const fg = luminance(style.color),
            bg = luminance(background);
          return {
            ratio: (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05),
            decoration: style.textDecorationStyle,
            background: style.backgroundColor,
          };
        }, state);
        assert.equal(result.decoration, 'dotted');
        assert.equal(result.background, 'rgba(0, 0, 0, 0)');
        assert.ok(
          result.ratio >= 4.5,
          `${colorScheme} ${state}: ${result.ratio}`,
        );
        console.log(
          `Mako contrast ${colorScheme} ${state}: ${result.ratio.toFixed(2)}:1`,
        );
      }
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
  const browser = await playwright[process.env.BROWSER || 'chromium'].launch({
    headless: true,
    ...(process.env.BROWSER_PATH
      ? { executablePath: process.env.BROWSER_PATH }
      : {}),
  });
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

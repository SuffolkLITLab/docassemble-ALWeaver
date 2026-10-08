#!/usr/bin/env node
// Authenticated browser regression for opening an unmapped validation finding.
// Creates and deletes its own disposable project and interview.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const server = (process.env.SERVER_URL || 'http://localhost').replace(
  /\/$/,
  '',
);
const storageState = process.env.STORAGE_STATE;
const chromiumPath = process.env.CHROMIUM_PATH;

async function main() {
  assert.ok(
    storageState,
    'Set STORAGE_STATE to an authenticated Playwright state',
  );
  const browser = await chromium.launch({
    headless: true,
    ...(chromiumPath ? { executablePath: chromiumPath } : {}),
  });
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();
  const errors = [];
  let project = null;
  const interview = `unmapped-${Date.now()}.yml`;
  let completed = false;
  page.on('pageerror', (error) => errors.push(String(error)));

  async function editorPost(path, body) {
    const csrfToken = await page.evaluate(
      () =>
        window.__EDITOR_BOOTSTRAP__ && window.__EDITOR_BOOTSTRAP__.csrfToken,
    );
    assert.ok(
      csrfToken,
      'Editor bootstrap must provide the session CSRF token',
    );
    const response = await context.request.post(`${server}/al/editor${path}`, {
      data: body,
      headers: { 'X-CSRF-Token': csrfToken },
    });
    const payload = await response.json();
    assert.equal(response.status(), 200, `${path}: ${JSON.stringify(payload)}`);
    assert.equal(payload.success, true, `${path}: ${JSON.stringify(payload)}`);
    return payload.data;
  }

  try {
    await page.goto(`${server}/al/editor`, { waitUntil: 'networkidle' });
    project = (
      await editorPost('/api/new-project', {
        project_name: `UnmappedValidation${Date.now()}`,
        create_test: false,
      })
    ).project;
    const nestedSource =
      'id: welcome\nquestion: Welcome\n---\nnested:\n' +
      Array.from(
        { length: 105 },
        (_item, index) => '  '.repeat(index + 1) + `level${index}:`,
      ).join('\n') +
      '\n' +
      '  '.repeat(106) +
      'value: true\n';
    await editorPost('/api/file/new', {
      project,
      filename: interview,
      content: nestedSource.replace(/\n/g, '\r\n'),
    });
    const projectPath = encodeURIComponent(project);
    const interviewPath = encodeURIComponent(interview);
    await page.goto(
      `${server}/al/editor/projects/${projectPath}/interviews/${interviewPath}`,
      { waitUntil: 'networkidle' },
    );
    await page.locator('#canvas-content').waitFor({ state: 'visible' });

    // The valid but deeply nested YAML produces an unlinked validator finding.
    // Change a question graphically before opening it to check composition.
    const graphicalQuestion = page
      .locator('#q-title')
      .locator('xpath=..')
      .locator('.cm-content');
    await graphicalQuestion.fill('Unsaved graphical question');
    const drawer = page.locator('#validation-drawer');
    if (
      !(await drawer.evaluate((element) => element.classList.contains('open')))
    )
      await page.locator('#validation-toggle').click();
    await page.locator('#btn-run-validation').click();
    const finding = page.locator(
      '.editor-validation-item[aria-label^="Open full YAML:"]',
    );
    await finding.waitFor({ state: 'visible' });
    await finding.focus();
    await page.keyboard.press('Enter');
    const sourceEditor = page.locator('#full-source-editor .cm-content');
    await page.locator('#full-source-editor').waitFor({ state: 'visible' });
    await page.waitForFunction(() =>
      document
        .querySelector('#full-source-editor .cm-content')
        ?.innerText.includes('Unsaved graphical question'),
    );

    // Replace the intentionally deep YAML with valid source, then save and
    // reload to prove the graphical edit survived the navigation and save.
    const composedSource = await sourceEditor.evaluate(
      (element) => element.innerText,
    );
    assert.match(composedSource, /Unsaved graphical question/);
    const savableSource =
      composedSource
        .replace(/\r\n/g, '\n')
        .split(/^---\s*$/m)[0]
        .trimEnd() + '\n';
    await sourceEditor.fill(savableSource);
    const saveResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/al/editor/api/file') &&
        response.request().method() === 'POST',
    );
    await page.locator('#save-full-yaml').click();
    const saved = await saveResponse;
    assert.equal(saved.status(), 200, await saved.text());
    assert.equal((await saved.json()).success, true);
    const savedFileResponse = await context.request.get(
      `${server}/al/editor/api/file?project=${projectPath}&filename=${interviewPath}`,
    );
    assert.equal(savedFileResponse.status(), 200);
    const savedFile = await savedFileResponse.json();
    assert.match(savedFile.data.raw_yaml, /Unsaved graphical question/);
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForFunction(
      () => {
        const sourceEditor = document.querySelector(
          '#full-source-editor .cm-content',
        );
        const question = document.querySelector('#q-title');
        const questionEditor =
          question?.parentElement?.querySelector('.cm-content');
        return (
          sourceEditor?.innerText.includes('Unsaved graphical question') ||
          questionEditor?.innerText.includes('Unsaved graphical question')
        );
      },
    );
    assert.deepEqual(errors, [], 'browser raised a page error');
    completed = true;
    console.log('unmapped validation navigation smoke test passed');
  } finally {
    if (project) await editorPost('/api/project/delete', { project });
    await context.close();
    await browser.close();
    if (!completed) process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

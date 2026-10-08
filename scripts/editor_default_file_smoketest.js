#!/usr/bin/env node
// Authenticated browser regression for the interview opened by a project route.
// Requires Playwright, CHROMIUM_PATH, and a logged-in STORAGE_STATE.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const server = (process.env.SERVER_URL || 'http://localhost').replace(/\/$/, '');
const storageState = process.env.STORAGE_STATE;
const executablePath = process.env.CHROMIUM_PATH;
const prefix = `DefaultFile${Date.now()}`;
const projects = [];

async function main() {
  assert.ok(storageState, 'Set STORAGE_STATE to an authenticated browser state');
  assert.ok(executablePath, 'Set CHROMIUM_PATH to the installed Chromium binary');
  const browser = await chromium.launch({ headless: true, executablePath });
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();
  let completed = false;

  async function editorPost(path, body) {
    const csrfToken = await page.evaluate(
      () => window.__EDITOR_BOOTSTRAP__ && window.__EDITOR_BOOTSTRAP__.csrfToken,
    );
    assert.ok(csrfToken, 'Editor bootstrap must provide the session CSRF token');
    const response = await context.request.post(`${server}/al/editor${path}`, {
      data: body,
      headers: { 'X-CSRF-Token': csrfToken },
    });
    const payload = await response.json();
    assert.equal(response.status(), 200, `${path}: ${JSON.stringify(payload)}`);
    assert.equal(payload.success, true, `${path}: ${JSON.stringify(payload)}`);
    return payload.data;
  }

  async function createProject(name) {
    const data = await editorPost('/api/new-project', {
      project_name: name,
      create_test: false,
    });
    projects.push(data.project);
    return data.project;
  }

  async function createInterview(project, filename, content) {
    await editorPost('/api/file/new', { project, filename, content });
  }

  async function openProject(project) {
    await page.goto(`${server}/al/editor/projects/${project}`, {
      waitUntil: 'networkidle',
    });
    await page.locator('#file-select').waitFor({ state: 'visible' });
  }

  try {
    await page.goto(`${server}/al/editor`, { waitUntil: 'networkidle' });

    const preferredProject = await createProject(`${prefix}Main`);
    await createInterview(
      preferredProject,
      'helper.yml',
      'id: helper\nquestion: Helper route content\n',
    );
    await openProject(preferredProject);
    await page.waitForFunction(
      () => document.querySelector('#file-select')?.value === 'main.yml',
    );
    assert.equal(
      await page.locator('#file-select').inputValue(),
      'main.yml',
      'project route without a filename opens main.yml',
    );

    await page.locator('#file-select').selectOption('helper.yml');
    await page.waitForFunction(
      () => document.querySelector('#q-title')?.value === 'Helper route content',
    );
    assert.match(
      page.url(),
      /\/interviews\/helper\.yml\/blocks\/helper$/,
      'selecting a file creates a valid route for that file and block',
    );

    await page.goto(
      `${server}/al/editor/projects/${preferredProject}/interviews/helper.yml/blocks/helper`,
      { waitUntil: 'networkidle' },
    );
    await page.waitForFunction(
      () =>
        document.querySelector('#q-title')?.value === 'Helper route content',
    );
    assert.equal(
      await page.locator('#q-title').inputValue(),
      'Helper route content',
      'valid deep link opens its requested file and block',
    );
    assert.match(page.url(), /\/interviews\/helper\.yml\/blocks\/helper$/);

    const fallbackProject = await createProject(`${prefix}Fallback`);
    await editorPost('/api/file/delete', {
      project: fallbackProject,
      filename: 'main.yml',
    });
    await createInterview(
      fallbackProject,
      'fallback.yml',
      'id: fallback\nquestion: Fallback interview\n',
    );
    await openProject(fallbackProject);
    await page.waitForFunction(
      () => document.querySelector('#file-select')?.value === 'fallback.yml',
    );
    assert.equal(
      await page.locator('#file-select').inputValue(),
      'fallback.yml',
      'project without main.yml keeps the first-file fallback',
    );

    completed = true;
    console.log(
      'PASS main.yml default, missing-main fallback, explicit file and block deep link',
    );
  } finally {
    for (const project of projects.reverse()) {
      await editorPost('/api/project/delete', { project });
    }
    await context.close();
    await browser.close();
    if (!completed) process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

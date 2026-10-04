#!/usr/bin/env node
// Authenticated regression against a real Docassemble server. Creates and
// removes only its own fixture projects; screenshots contain fixture data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, expect, request } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;

const server = (process.env.SERVER_URL || 'http://localhost').replace(
  /\/$/,
  '',
);
const output =
  process.env.SCREENSHOT_DIR || '/tmp/alweaver-navigation-screenshots';
const apiHeaders = {
  'X-API-Key': process.env.EDITOR_API_KEY || process.env.ADMIN_API_KEY,
};
const userParams = process.env.EDITOR_USER_ID
  ? { user_id: process.env.EDITOR_USER_ID }
  : {};
const projects = [];
const errors = [];
const results = [];
let completed = false;
const prefix = `NavRegression${Date.now()}`;
const interview = 'navigation.yml';
const fixture = `metadata:
  title: Navigation regression fixture
---
id: welcome
question: What is your name?
subquestion: Use this fixture to check editor navigation.
fields:
  - First name: first_name
---
id: color
question: Choose a color
fields:
  - Color: color
    choices:
      - Blue
      - Green
`;

async function main() {
  assert.ok(
    apiHeaders['X-API-Key'],
    'Set EDITOR_API_KEY or ADMIN_API_KEY for fixture creation',
  );
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {}),
  });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 900 },
    ...(process.env.STORAGE_STATE
      ? { storageState: process.env.STORAGE_STATE }
      : {}),
  });
  // API-key authentication can change Docassemble's session user. Keep fixture
  // requests in their own cookie jar, separate from the browser login.
  const fixtureApi = await request.newContext();
  const page = await context.newPage();
  page.on('pageerror', (error) => errors.push(String(error)));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  async function screenshot(name) {
    await page.screenshot({ path: path.join(output, `${name}.png`) });
  }
  async function audit(label) {
    const result = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    const blocking = result.violations.filter((v) =>
      ['serious', 'critical'].includes(v.impact),
    );
    assert.deepEqual(
      blocking.map((v) => ({
        id: v.id,
        targets: v.nodes.map((n) => n.target),
      })),
      [],
      label,
    );
    results.push(`${label}: zero serious/critical accessibility violations`);
  }
  async function load(url) {
    await page.goto(url, { waitUntil: 'networkidle' });
    // The worker warning is unrelated to these navigation-only fixtures.
    const dismiss = page.locator('#editor-celery-warning:visible .btn-close');
    if (await dismiss.count()) await dismiss.click();
  }
  async function addProject(name, withFiles = false) {
    const response = await fixtureApi.post(`${server}/api/playground/project`, {
      headers: apiHeaders,
      form: { project: name, ...userParams },
    });
    assert.equal(response.status(), 204, await response.text());
    projects.push(name);
    if (!withFiles) return;
    const files = {
      questions: [interview, fixture],
      templates: ['navigation.md', 'Hello ${ first_name }\n'],
      modules: [
        'navigation.py',
        'def greeting(name):\n    return "Hello " + name\n',
      ],
      static: ['navigation.css', 'body { color: navy; }\n'],
      sources: ['navigation.txt', 'Navigation fixture\n'],
    };
    for (const [folder, [filename, content]] of Object.entries(files)) {
      const upload = await fixtureApi.post(`${server}/api/playground`, {
        headers: apiHeaders,
        multipart: {
          ...userParams,
          project: name,
          folder,
          restart: '0',
          file: {
            name: filename,
            mimeType: 'text/plain',
            buffer: Buffer.from(content),
          },
        },
      });
      assert.equal(upload.status(), 204, await upload.text());
    }
  }
  async function oneTopRow() {
    const boxes = await page
      .locator(
        '#editor-project-menu, #editor-section-menu, #editor-navbar-collapse, .editor-compact-actions, #editor-account-menu',
      )
      .evaluateAll((elements) =>
        elements
          .filter((el) => el.getBoundingClientRect().width)
          .map((el) => {
            const r = el.getBoundingClientRect();
            return { top: r.top, bottom: r.bottom, right: r.right };
          }),
      );
    assert.ok(
      Math.max(...boxes.map((r) => r.top)) <
        Math.min(...boxes.map((r) => r.bottom)),
      'Top rail wrapped',
    );
    assert.ok(
      boxes.every((r) => r.right <= page.viewportSize().width),
      `Top rail overflowed at ${page.viewportSize().width}: ${JSON.stringify(boxes)}`,
    );
  }
  try {
    await page.goto(`${server}/al/editor`);
    if (new URL(page.url()).pathname !== '/al/editor') {
      assert.ok(
        process.env.EDITOR_EMAIL && process.env.EDITOR_PASSWORD,
        'Set EDITOR_EMAIL and EDITOR_PASSWORD, or STORAGE_STATE',
      );
      await page.locator('input[type="email"]').fill(process.env.EDITOR_EMAIL);
      await page
        .locator('input[type="password"]')
        .fill(process.env.EDITOR_PASSWORD);
      await page.getByRole('button', { name: /sign in/i }).click();
      await page.waitForURL(`${server}/al/editor`);
    }
    const original = await context.request.get(
      `${server}/al/editor/api/projects`,
    );
    const originalProjects = (await original.json()).data.projects;
    const primary = `${prefix}A`;
    const secondary = `${prefix}B`;
    await addProject(primary, true);
    await addProject(secondary, true);
    const route = `${server}/al/editor/projects/${primary}/interviews/${interview}/blocks/welcome`;
    await load(route);
    await expect(page.locator('#q-title')).toHaveValue('What is your name?');
    await expect(page.locator('#left-rail')).not.toContainText(
      'Project outline',
    );
    await expect(page.locator('#left-rail #project-select')).toHaveCount(0);
    await oneTopRow();
    await screenshot('01-laptop-editor');
    await audit('Laptop editor');

    await page.locator('#editor-project-menu').click();
    await expect(page.locator('#editor-recent-projects')).toBeVisible();
    await page.locator('.editor-project-submenu > summary').click();
    await expect(page.locator('#editor-all-projects')).toBeVisible();
    await screenshot('02-project-switcher');
    await page.locator(`#editor-all-projects [data-project-card="${secondary}"]`).click();
    await expect(page).toHaveURL(
      new RegExp(`/projects/${secondary}/interviews/`),
    );
    await expect(page.locator('.editor-project-menu')).toBeHidden();
    await page.locator('#editor-project-menu').click();
    await page.locator(`#editor-recent-projects [data-project-card="${primary}"]`).click();
    await expect(page).toHaveURL(
      new RegExp(`/projects/${primary}/interviews/`),
    );

    // Switching projects must preserve the existing unsaved-changes guard.
    await page.locator('#q-title').fill('An unsaved question');
    await page.locator('#editor-project-menu').click();
    await page.locator(`#editor-recent-projects [data-project-card="${secondary}"]`).click();
    await expect(page.locator('#unsaved-changes-modal')).toBeVisible();
    await page.locator('[data-unsaved-choice="stay"]').click();
    await expect(page.locator('#q-title')).toHaveValue('An unsaved question');
    await expect(page.locator('#topbar-project-name')).toHaveText(primary);
    await load(route);

    await page.locator('#btn-project-search').click();
    await expect(page.locator('#project-search-modal')).toBeVisible();
    await page.locator('#project-search-query').fill('first_name');
    await page.locator('#project-search-submit').click();
    await expect(page.locator('#project-search-results')).toContainText(
      interview,
    );
    await page.locator('#project-search-modal .btn-close').click();
    await page.locator('[data-action="toggle-rail"]').click();
    await expect(page.locator('#file-select')).toBeHidden();
    await page.locator('[data-action="toggle-rail"]').click();
    await expect(page.locator('#file-select')).toBeVisible();

    for (const [view, filename] of [
      ['templates', 'navigation.md'],
      ['modules', 'navigation.py'],
      ['static', 'navigation.css'],
      ['data', 'navigation.txt'],
      ['interview', interview],
    ]) {
      const tab = page.locator(`.editor-top-tab[data-view="${view}"]`);
      if (await tab.isVisible()) {
        await tab.click();
      } else {
        await page.locator('#editor-section-menu').click();
        await page.locator(`.editor-view-switch[data-view="${view}"]`).click();
      }
      await expect(page.locator('#btn-project-search')).toBeVisible();
      await expect(page.locator('#canvas-content')).toContainText(
        view === 'interview' ? 'What is your name?' : filename,
      );
    }
    for (const width of [1920, 1440, 1366, 1200, 1024, 768, 576]) {
      await page.setViewportSize({
        width,
        height: width === 1920 ? 1200 : 900,
      });
      await oneTopRow();
      if (width >= 1200) {
        await expect(page.locator('#view-tabs')).toBeVisible();
        await expect(page.locator('#view-tabs .editor-top-tab')).toHaveText([
          'Interview',
          'Templates',
          'Modules',
          'Static',
          'Sources',
        ]);
        await expect(page.locator('#editor-section-menu')).toBeHidden();
        if (width === 1920) await screenshot('10-desktop-1920x1200-tabs');
      } else {
        await expect(page.locator('#view-tabs')).toBeHidden();
        await expect(page.locator('#editor-section-menu')).toBeVisible();
        if (width === 1024) {
          await page.locator('#editor-section-menu').click();
          await screenshot('03-section-navigation');
          await page.keyboard.press('Escape');
        }
      }
      await expect(page.locator('.navbar-toggler')).toBeHidden();
      await page.locator('#editor-account-menu').click();
      await expect(
        page.locator('[aria-labelledby="editor-account-menu"]'),
      ).toBeVisible();
      await oneTopRow();
      assert.ok(
        (await page.locator('#topbar').boundingBox()).height < 80,
        'Account menu expanded the top rail',
      );
      if (width === 1024) {
        await screenshot('04-tablet-account-menu');
        await audit('Tablet account menu');
      }
      await page.keyboard.press('Escape');
    }
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = '200%';
    });
    await screenshot('05-laptop-large-text');
    await oneTopRow();
    for (const width of [1024, 768, 576]) {
      await page.setViewportSize({ width, height: 900 });
      await oneTopRow();
    }
    await page.evaluate(() => {
      document.documentElement.style.fontSize = '';
    });
    for (const width of [375, 320]) {
      await page.setViewportSize({ width, height: 812 });
      await expect(page.locator('#editor-account-menu')).toBeVisible();
      await page.locator('#editor-account-menu').click();
      await expect(
        page.locator('[aria-labelledby="editor-account-menu"]'),
      ).toBeVisible();
      assert.ok(
        (await page.locator('#topbar').boundingBox()).height < 80,
        'Phone account menu expanded the top rail',
      );
      if (width === 375) {
        await screenshot('09-phone-account-menu');
        await audit('Phone account menu');
      }
      await page.keyboard.press('Escape');
      await page.locator('.navbar-toggler').click();
      await expect(page.locator('#editor-navbar-collapse')).toHaveClass(
        /\bshow\b/,
      );
      await expect(page.locator('#view-tabs')).toBeVisible();
      if (width === 375) {
        await screenshot('06-phone-navigation');
        await audit('Phone navigation');
      }
      await page.locator('#interview-menu').click();
      await page
        .locator('#editor-navbar-collapse [data-action="open-full-yaml"]')
        .click();
      await expect(page.locator('#full-source-editor')).toBeVisible();
      await expect(page.locator('#editor-navbar-collapse')).toBeHidden();
      await load(route);
    }
    await page.setViewportSize({ width: 1366, height: 900 });
    await load(`${server}/al/editor`);
    for (const selector of [
      '.editor-section-switcher', '.editor-compact-actions',
      '#editor-navbar-collapse', '.navbar-toggler', '#left-rail', '#validation-drawer',
    ]) {
      await expect(page.locator(selector)).toBeHidden();
    }
    const allCount = originalProjects.length + 2;
    await expect(page.locator('#canvas-content [data-project-card]')).toHaveCount(allCount);
    if (allCount <= 8)
      await expect(page.locator('.editor-project-section-title')).toHaveText([
        'All projects',
      ]);
    await expect(
      page.locator(
        '[data-project-name="default"][data-project-action="delete"]',
      ),
    ).toHaveCount(0);
    await expect(
      page.locator(
        '[data-project-name="default"][data-project-action="rename"]',
      ),
    ).toHaveCount(0);
    await screenshot('07-small-project-list');
    for (let n = allCount; n < 10; n++) await addProject(`${prefix}Extra${n}`);
    await load(`${server}/al/editor`);
    await expect(page.locator('.editor-project-section-title')).toHaveText([
      'Recent projects',
      'Other projects',
    ]);
    const cardNames = await page
      .locator('#canvas-content [data-project-card]')
      .evaluateAll((cards) => cards.map((card) => card.dataset.projectCard));
    assert.equal(new Set(cardNames).size, cardNames.length);
    await screenshot('08-large-project-list');
    await page.locator('#project-search-input').fill(primary);
    await expect(page.locator('#canvas-content [data-project-card]')).toHaveCount(1);
    await expect(page.locator('#canvas-content [data-project-card]')).toHaveAttribute(
      'data-project-card',
      primary,
    );
    await page
      .locator('#project-search-input')
      .fill('NoMatchingProject987654321');
    await expect(page.locator('#canvas-content [data-project-card]')).toHaveCount(0);
    await expect(page.locator('#canvas-content')).toContainText(
      'No projects matched your search.',
    );
    assert.deepEqual(errors, []);
    completed = true;
    results.push(
      'PASS project switching, unsaved changes, search, sidebar collapse, all five sections, desktop/tablet/phone menus, 200% text, unique small/large project lists, Default project protection',
    );
  } finally {
    for (const project of projects.reverse()) {
      const response = await fixtureApi.delete(
        `${server}/api/playground/project`,
        { headers: apiHeaders, params: { project, ...userParams } },
      );
      assert.equal(
        response.status(),
        204,
        `Fixture cleanup failed: ${project}`,
      );
    }
    await fixtureApi.dispose();
    await context.close();
    await browser.close();
    fs.writeFileSync(
      path.join(output, 'results.json'),
      JSON.stringify({ server, passed: completed, results, errors }, null, 2),
    );
  }
  console.log(results.join('\n'));
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

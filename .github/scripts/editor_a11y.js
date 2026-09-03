const { chromium } = require("playwright");
const AxeBuilder = require("@axe-core/playwright").default;

const serverUrl = String(process.env.SERVER_URL || "").replace(/\/$/, "");
const email = process.env.EDITOR_EMAIL;
const password = process.env.EDITOR_PASSWORD;

if (!serverUrl || !email || !password) {
  throw new Error("SERVER_URL, EDITOR_EMAIL, and EDITOR_PASSWORD are required");
}

const blockingImpacts = new Set(["critical", "serious"]);
const pageErrors = [];

async function signInIfNeeded(page) {
  await page.goto(`${serverUrl}/al/editor`, { waitUntil: "domcontentloaded" });

  if (new URL(page.url()).pathname.endsWith("/al/editor")) return;

  const emailInput = page
    .locator('input[type="email"], input[name="email"], input[name="username"]')
    .first();
  await emailInput.fill(email);
  await page.locator('input[type="password"]').first().fill(password);
  await page
    .getByRole("button", { name: /sign in|log in/i })
    .first()
    .click();
  await page.waitForURL((url) => url.pathname.endsWith("/al/editor"), {
    timeout: 30_000,
  });
}

async function audit(page, label) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  const blocking = result.violations.filter((violation) =>
    blockingImpacts.has(violation.impact)
  );

  console.log(
    `${label}: ${result.violations.length} total violation(s), ` +
      `${blocking.length} blocking violation(s)`
  );
  for (const violation of result.violations) {
    console.log(
      JSON.stringify({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        helpUrl: violation.helpUrl,
        targets: violation.nodes.map((node) => node.target),
      })
    );
  }
  return blocking;
}

async function auditAfter(page, label, locator, action) {
  await action();
  await locator.waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForTimeout(250);
  return audit(page, label);
}

async function auditSecondaryView(page, view, filename, blockingViolations) {
  await page.locator(`.editor-top-tab[data-view="${view}"]`).click();
  await page
    .locator(".editor-full-yaml-header h2")
    .filter({ hasText: filename })
    .waitFor({ state: "visible", timeout: 30_000 });
  await page.locator("#section-file-source-editor").waitFor({
    state: "visible",
    timeout: 30_000,
  });
  const apiError = page.locator("#editor-api-error");
  if (await apiError.isVisible()) {
    throw new Error(`Editor API error while opening ${view}: ${await apiError.innerText()}`);
  }
  return blockingViolations.concat(
    await audit(page, `${view} source editor`)
  );
}

async function selectOption(page, selector, value, description) {
  const control = page.locator(selector);
  await control.waitFor({ state: "visible", timeout: 30_000 });
  const options = await control.locator("option").evaluateAll((items) =>
    items.map((item) => ({ value: item.value, label: item.textContent.trim() }))
  );
  const option = options.find((item) => item.value === value || item.label === value);
  if (!option) {
    throw new Error(
      `Could not find ${description} ${value}; available options: ${JSON.stringify(options)}`
    );
  }
  await control.selectOption(option.value);
}

async function closeModal(page, selector) {
  const modal = page.locator(selector);
  if (await modal.locator(".btn-close").count()) {
    await modal.locator(".btn-close").first().click();
  } else {
    await modal.locator('[data-bs-dismiss="modal"]').first().click();
  }
  await modal.waitFor({ state: "hidden", timeout: 10_000 });
}

// The findings panel reports it is working before the answer arrives, so wait
// for the run to finish rather than auditing the spinner.
async function settledFindings(page) {
  await page
    .locator('#validation-drawer[aria-busy="false"]')
    .waitFor({ timeout: 30_000 });
  await page.waitForTimeout(250);
}

async function openInterviewMenu(page) {
  const button = page.locator("#interview-menu");
  const menu = page.locator('ul[aria-labelledby="interview-menu"]');
  if ((await button.getAttribute("aria-expanded")) !== "true") {
    await button.click();
  }
  await page.waitForFunction(
    () => document.querySelector("#interview-menu")?.getAttribute("aria-expanded") === "true",
    undefined,
    { timeout: 10_000 }
  );
  await menu.waitFor({ state: "visible", timeout: 10_000 });
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  let blockingViolations = [];
  try {
    await signInIfNeeded(page);
    await page.locator("#editor-app").waitFor({ state: "visible", timeout: 30_000 });

    // Open a real Playground interview and its file-backed editing areas.
    await selectOption(page, "#project-select", "default", "project");
    await page.locator('#file-select option[value="editor_accessibility.yml"]').waitFor({
      state: "attached",
      timeout: 30_000,
    });
    await selectOption(page, "#file-select", "editor_accessibility.yml", "interview file");
    await page.locator("#outline-list .editor-outline-item").first().waitFor({
      state: "visible",
      timeout: 30_000,
    });
    blockingViolations = blockingViolations.concat(
      await audit(page, "interview editor")
    );

    // Visit every file-backed secondary editor, not only the empty shell.
    for (const [view, filename] of [
      ["templates", "editor_accessibility.md"],
      ["modules", "editor_accessibility.py"],
      ["static", "editor_accessibility.js"],
      ["data", "editor_accessibility.txt"],
    ]) {
      blockingViolations = await auditSecondaryView(
        page,
        view,
        filename,
        blockingViolations
      );
    }
    await page.locator('.editor-top-tab[data-view="interview"]').click();
    await page.locator("#outline-list .editor-outline-item").first().waitFor();

    // Project selector and the new-project editing form.
    blockingViolations = blockingViolations.concat(
      await auditAfter(
        page,
        "project selector",
        page.locator("#project-search-input"),
        () => page.locator('[data-action="open-project-selector"]').first().click()
      )
    );
    blockingViolations = blockingViolations.concat(
      await auditAfter(
        page,
        "new project form",
        page.locator("#new-project-name"),
        () => page.locator("#open-new-project-card").click()
      )
    );
    await page.locator("#cancel-new-project").click();
    await page.locator('[data-project-card="default"]').last().click();
    await page.locator("#outline-list .editor-outline-item").first().waitFor();

    // Project-wide search dialog and its result state.
    await page.locator("#btn-project-search").click();
    blockingViolations = blockingViolations.concat(
      await audit(page, "project search dialog")
    );
    await page.locator("#project-search-query").fill("editor_fixture");
    await page.locator("#project-search-submit").click();
    await page.locator("#project-search-status").waitFor({ state: "visible" });
    blockingViolations = blockingViolations.concat(
      await audit(page, "project search results")
    );
    await closeModal(page, "#project-search-modal");

    // Validation actions and the open results drawer.
    await page.locator('[data-action="check-errors"]').click();
    await settledFindings(page);
    blockingViolations = blockingViolations.concat(
      await audit(page, "validation drawer")
    );
    // The style check lives in the Interview menu, and the deterministic run
    // is the one that needs no model configured on the test server.
    await openInterviewMenu(page);
    await page.locator('[data-action="run-style-check"]').click();
    await settledFindings(page);
    blockingViolations = blockingViolations.concat(
      await audit(page, "style-check results")
    );

    // Full YAML, metadata, and interview-order source editors.
    await openInterviewMenu(page);
    await page.locator('[data-action="open-full-yaml"]').click();
    await page.locator("#full-source-editor").waitFor({ state: "visible" });
    blockingViolations = blockingViolations.concat(
      await audit(page, "full YAML editor")
    );
    for (const tabName of ["metadata", "order"]) {
      await page.locator(`[data-yaml-tab="${tabName}"]`).click();
      await page.waitForTimeout(250);
      blockingViolations = blockingViolations.concat(
        await audit(page, `${tabName} YAML editor`)
      );
    }
    await page.locator("#back-to-question").click();
    await page.locator("#outline-list .editor-outline-item").first().waitFor();

    // AssemblyLine settings, including its explanatory popover.
    await openInterviewMenu(page);
    await page.locator('[data-action="open-assemblyline-settings"]').click();
    await page.locator("#assemblyline-settings-filter").waitFor({ state: "visible" });
    blockingViolations = blockingViolations.concat(
      await audit(page, "AssemblyLine settings")
    );
    await page.locator("[data-al-settings-explainer]").click();
    await page.locator(".popover").waitFor({ state: "visible", timeout: 10_000 });
    blockingViolations = blockingViolations.concat(
      await audit(page, "AssemblyLine settings explainer")
    );
    await page.keyboard.press("Escape");
    await page.locator("#close-assemblyline-settings").click();
    await page.locator("#outline-list .editor-outline-item").first().waitFor();

    // Graphical question editing, field settings, YAML editing, and preview.
    const question = page.locator('.editor-outline-item[data-block-id]').filter({
      hasText: "What is your name?",
    });
    await question.first().click();
    await page.locator('[data-question-tab="screen"]').click();
    await page.locator("#q-title").waitFor({ state: "visible" });
    blockingViolations = blockingViolations.concat(
      await audit(page, "graphical question editor")
    );
    const fieldSettingsButton = page.locator(".editor-field-kebab-btn").first();
    if (await fieldSettingsButton.count()) {
      await fieldSettingsButton.click();
      await page.waitForTimeout(250);
      blockingViolations = blockingViolations.concat(
        await audit(page, "field settings editor")
      );
      await fieldSettingsButton.click();
    } else {
      console.log("field settings editor: fixture field has no settings control");
    }
    await page.locator('[data-question-tab="options"]').click();
    await page.waitForTimeout(250);
    blockingViolations = blockingViolations.concat(
      await audit(page, "question options editor")
    );
    await page.locator("#toggle-edit-mode-tab").click();
    await page.locator("#block-source-editor").waitFor({ state: "visible" });
    blockingViolations = blockingViolations.concat(
      await audit(page, "question YAML editor")
    );
    await page.locator('[data-question-mode="preview"]').first().click();
    await page.locator("#q-title").waitFor({ state: "visible" });
    await page.locator("#question-preview-tab").click();
    await page.locator("#screen-preview-modal").waitFor({ state: "visible" });
    await page.locator("#screen-preview-frame").waitFor({ state: "visible" });
    await page.waitForTimeout(250);
    blockingViolations = blockingViolations.concat(
      await audit(page, "screen preview dialog")
    );
    await closeModal(page, "#screen-preview-modal");

    // The insert-block dialog is the main entry point for authoring new work.
    await page.locator(".editor-outline-insert-btn").first().click();
    const insertModal = page.locator("#insert-modal");
    await insertModal.waitFor({ state: "visible" });
    await page.locator("#insert-modal.show").waitFor({
      state: "attached",
      timeout: 10_000,
    });
    await page.waitForTimeout(250);
    blockingViolations = blockingViolations.concat(
      await audit(page, "insert-block dialog")
    );
    await closeModal(page, "#insert-modal");

    if (pageErrors.length) {
      console.error("Browser page errors:");
      for (const error of pageErrors) console.error(error);
      process.exitCode = 1;
    }
    if (blockingViolations.length) process.exitCode = 1;
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

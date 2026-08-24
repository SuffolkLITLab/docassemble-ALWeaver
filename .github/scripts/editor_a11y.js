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

  if (new URL(page.url()).pathname.endsWith("/al/editor")) {
    return;
  }

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

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  try {
    await signInIfNeeded(page);
    await page.locator("#editor-app").waitFor({ state: "visible", timeout: 30_000 });

    let blockingViolations = await audit(page, "interview");
    for (const view of ["templates", "modules", "static", "data"]) {
      const tab = page.locator(`.editor-top-tab[data-view="${view}"]`).first();
      await tab.click();
      await page.waitForTimeout(500);
      blockingViolations = blockingViolations.concat(await audit(page, view));
    }

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

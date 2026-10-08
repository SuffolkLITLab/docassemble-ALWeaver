#!/usr/bin/env node
// Submit a generated survey on a live Docassemble server and verify its saved row.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const server = (process.env.SERVER_URL || 'http://localhost').replace(/\/$/, '');
const container = process.env.DOCASSEMBLE_CONTAINER || 'admiring_goldwasser';
const docassemblePython =
  process.env.DOCASSEMBLE_PYTHON || '/usr/share/docassemble/local3.14/bin/python';
const marker = `LIVE_SURVEY_FILTER_${Date.now()}`;
const probePath = path.join(__dirname, 'survey_answer_filter_db_probe.py');

function verifyStoredRow() {
  const probe = fs.readFileSync(probePath, 'utf8');
  const output = execFileSync(
    'docker',
    [
      'exec',
      '-i',
      '-u',
      'www-data',
      container,
      docassemblePython,
      '-',
      marker,
    ],
    { input: probe, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] },
  );
  const result = JSON.parse(output.trim().split('\n').at(-1));
  assert.equal(result.ok, true);
  assert.equal(result.fixture_row_removed, true);
  assert.deepEqual(result.keys, [
    'field_type_list',
    'survey_count',
    'survey_name',
    'title',
  ]);
  return result;
}

(async () => {
  const launchOptions = { headless: true };
  if (process.env.CHROMIUM_PATH) {
    launchOptions.executablePath = process.env.CHROMIUM_PATH;
  }
  const browser = await chromium.launch(launchOptions);
  try {
    const context = await browser.newContext(
      process.env.STORAGE_STATE
        ? { storageState: process.env.STORAGE_STATE }
        : {},
    );
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const interview =
      'docassemble.SurveyAnswerFilterSmokeTest:data/questions/survey_answer_filter_smoke_test.yml';
    await page.goto(
      `${server}/interview?i=${encodeURIComponent(interview)}&new_session=1&reset=1`,
    );

    let submitted = false;
    for (let step = 0; step < 12; step += 1) {
      const name = page.getByLabel(/Name for live survey check/i);
      if (await name.count()) {
        await name.fill(marker);
        await page.getByLabel(/Number for live survey check/i).fill('41');
        submitted = true;
      }

      if (
        await page.getByRole('heading', { name: 'Thank You!', exact: true }).count()
      ) {
        break;
      }

      const termsAcceptance = page
        .locator('#daform label')
        .filter({ hasText: /I accept the terms of use/i });
      if (await termsAcceptance.count()) {
        await termsAcceptance.first().click();
      }

      const submit = page.locator('#daform button[type="submit"]:visible').first();
      assert.equal(await submit.count(), 1, `No visible Continue button on step ${step + 1}`);
      await submit.click();
      await page.waitForTimeout(500);
    }

    assert.equal(submitted, true, 'Survey answer fields were never shown');
    await page
      .getByRole('heading', { name: 'Thank You!', exact: true })
      .waitFor({ state: 'visible' });
    const stored = verifyStoredRow();
    console.log(
      JSON.stringify({
        ok: true,
        submitted: ['survey_name', 'survey_count'],
        excluded: ['internal_skipped_answer', 'internal_computed_answer'],
        stored_keys: stored.keys,
        fixture_row_removed: stored.fixture_row_removed,
      }),
    );
    await context.close();
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

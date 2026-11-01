// Renderer compatibility test with unmodified release assets, not full release installations.
// Requires a running Docassemble server (SERVER, default localhost) for shared assets.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const server = (process.env.SERVER || 'http://localhost').replace(/\/$/, '');
const preview = require('../docassemble/ALWeaver/data/static/editor_screen_preview.js');
const block = {
  question: 'Another petitioner?',
  fields: [{ 'no label': 'users.there_is_another', datatype: 'yesnoradio' }],
};
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [version, widgetStyle] of [
      ['1.9.13', 'labelauty'],
      ['1.10.7', 'labelauty'],
      ['1.10.8', 'native'],
    ]) {
      const context = await browser.newContext({
        hasTouch: true,
        viewport: { width: 1024, height: 768 },
      });
      const page = await context.newPage();
      const root =
        'https://raw.githubusercontent.com/jhpyle/docassemble/v' +
        version +
        '/docassemble_webapp/docassemble/webapp/static/';
      const paths = [
        'app/bundle.css',
        ...(widgetStyle === 'labelauty'
          ? ['labelauty/source/jquery-labelauty.min.js']
          : []),
      ];
      for (const path of paths) {
        const response = await context.request.get(root + path);
        assert.equal(response.status(), 200);
        const body = await response.body();
        await page.route('**/static/' + path, (route) =>
          route.fulfill({
            body,
            contentType: path.endsWith('.css')
              ? 'text/css'
              : 'application/javascript',
          }),
        );
      }
      await page.goto(server + '/');
      const html = preview.buildDocument(block, { widgetStyle });
      await page.setContent(
        '<iframe id="preview" sandbox="allow-scripts" style="width:100%;height:680px"></iframe>',
      );
      await page.locator('#preview').evaluate((el, html) => {
        el.srcdoc = html;
      }, html);
      const frame = page.frameLocator('#preview');
      const yes = frame.locator('label[for="dapv_field_0_0"]');
      const no = frame.locator('label[for="dapv_field_0_1"]');
      await yes.waitFor();
      assert.equal(await frame.locator('input[type="radio"]').count(), 2);
      assert.equal(await frame.locator('input[type="checkbox"]').count(), 0);
      await yes.tap();
      assert.equal(await frame.locator('#dapv_field_0_0').isChecked(), true);
      await no.tap();
      assert.equal(await frame.locator('#dapv_field_0_1').isChecked(), true);
      assert.equal(await frame.locator('#dapv_field_0_0').isChecked(), false);
      if (widgetStyle === 'native') {
        assert.equal(
          await yes.evaluate(
            (el) => getComputedStyle(el, '::before').borderRadius,
          ),
          '50%',
        );
      } else {
        assert.equal(await no.locator('.labelauty-checked').innerText(), 'No');
        assert.equal(await no.locator('.labelauty-checked').isVisible(), true);
      }
      await page.screenshot({
        path: '/tmp/weaver-preview-' + version + '.png',
      });
      console.log(
        'PASS ' +
          version +
          ' ' +
          widgetStyle +
          ' release assets: unlabeled Yes/No choices render and respond to touch',
      );
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});

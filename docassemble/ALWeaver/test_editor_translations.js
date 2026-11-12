'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const elements = {};
const downloads = [];
const dialog = {
  setAttribute() {}, addEventListener() {}, showModal() {}, close() {}, remove() {},
  querySelector(selector) { return elements[selector] ||= {value: '', disabled: false, files: [], checked: false}; },
  querySelectorAll() { return Object.values(elements); }
};
const context = {
  console, Uint8Array, Blob, atob, setTimeout() {},
  URL: {createObjectURL() { return 'blob:download'; }, revokeObjectURL() {}},
  FileReader: class { readAsDataURL(file) { this.result = 'data:application/octet-stream;base64,' + file.content; this.onload(); } },
  document: {body: {appendChild() {}}, activeElement: null, createElement(tag) { return tag === 'dialog' ? dialog : {click() { downloads.push(this.download); }}; }}
};
vm.runInNewContext(fs.readFileSync(__dirname + '/data/static/editor_translations.js', 'utf8'), context);
const api = context.ALWeaverTranslations;
assert.deepStrictEqual(Array.from(api.languageCodes('es\nfr es')), ['es', 'fr']);
assert.throws(() => api.languageCodes('es ../fr'));
(async () => {
  const requests = [];
  let failAt = 0;
  let imports = 0;
  let reloads = 0;
  let preview = null;
  api.open({
    prepareSaved: async () => true,
    getState: () => ({project: 'default', filename: 'details.yml', revision: 'child-revision'}),
    reload: async () => { reloads++; },
    previewFlow: language => { preview = language; },
    apiPost: async (path, body) => {
      if (path.endsWith('/scope')) return {success: true, data: {project: 'default', filename: 'main.yml', expected_revision: 'v1'}};
      requests.push({path, body: JSON.parse(JSON.stringify(body))});
      if (path.endsWith('/generate')) return {success: true, data: {archive_base64: btoa('zip bytes'), archive_filename: 'main_translations.zip', translations: [{language: 'es', untranslated_segments: 2}, {language: 'fr', untranslated_segments: 3}]}};
      imports++;
      if (imports === failAt) return {success: false, error: {message: 'Workbook has invalid Mako'}};
      return {success: true, data: {revision: 'v' + (imports + 1), validation: {summary: {empty_row_count: 0}}}};
    }
  });
  ['#translation-languages', '#translation-language', '#translation-upload', '#translation-ai'].forEach(id => dialog.querySelector(id));
  elements['#translation-languages'].value = 'es\nfr';
  await elements['#translation-generate'].onclick();
  assert.deepStrictEqual(requests[0].body.tr_langs, ['es', 'fr']);
  assert.strictEqual(requests[0].body.filename, 'main.yml');
  assert.ok(elements['#translation-scope'].textContent.includes('Imported workbooks connect to main.yml'));
  assert.strictEqual(requests[0].body.expected_revision, 'v1');
  assert.deepStrictEqual(downloads, ['main_translations.zip']);
  assert.ok(elements['#translation-status'].textContent.includes('2 workbook(s)'));
  elements['#translation-upload'].files = [{name: 'es.xlsx', size: 10, content: 'ZXM='}, {name: 'fr.xlsx', size: 10, content: 'ZnI='}];
  await elements['#translation-import'].onclick();
  assert.strictEqual(requests[1].body.expected_revision, 'v1');
  assert.strictEqual(requests[2].body.expected_revision, 'v2');
  assert.strictEqual(reloads, 1);
  assert.ok(elements['#translation-status'].textContent.includes('2 workbook(s) connected'));
  imports = 0; failAt = 2;
  elements['#translation-upload'].files.push({name: 'ar.xlsx', size: 10, content: 'YXI='});
  await elements['#translation-import'].onclick();
  assert.strictEqual(imports, 2);
  assert.ok(elements['#translation-status'].textContent.includes('1 of 3 workbooks connected. fr.xlsx: Workbook has invalid Mako'));
  assert.strictEqual(reloads, 2);
  elements['#translation-language'].value = 'fr';
  elements['#translation-preview'].onclick();
  assert.strictEqual(preview, 'fr');
  console.log('translation UI: multi-language ZIP, revision chain, partial failures and single-language report passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

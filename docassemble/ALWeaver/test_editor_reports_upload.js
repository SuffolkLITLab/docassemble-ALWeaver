'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor_reports.js`, 'utf8');
const screens = Array.from({length: 300}, (_, i) => ({id: 'screen' + i, data: {question: 'Screen ' + i}}));
let captures = 0, downloads = 0, released = 0, attempts = 0;
const chunks = new Map();
const context = {
  Blob, FormData, setTimeout: callback => callback(),
  document: {createElement: () => ({setAttribute() {}})},
  reportDialog: () => ({isConnected: true, appendChild() {}}),
  checked: response => response.data,
  root: {ALWeaverScreenPreview: {buildInterviewContext: () => ({})}},
  captureScreen: async () => { captures++; return captures === 300 ? ['x'.repeat(1500), 'y'.repeat(1500)] : 'x'.repeat(1500); },
  download: () => { downloads++; },
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  async function releaseUpload'), source.indexOf('  async function importWording')), context);
context.exportWording({
  prepareSaved: async () => true,
  getState: () => ({project: 'default', filename: 'main.yml'}),
  previewOptions: () => ({}),
  apiPost: async (path, body) => {
    if (path.endsWith('/release')) { released++; return {data: {}}; }
    if (path.endsWith('/prepare')) return {data: {screens, blocks: [], warnings: [], revisions: {}}};
    if (path.endsWith('/uploads')) return {data: {upload_id: 'images', chunk_bytes: 500}};
    if (path.endsWith('/uploads/images')) {
      if (!chunks.size && attempts++ === 0) throw Object.assign(new Error('Temporary outage'), {status: 502});
      assert.ok(body.get('part').size <= 500);
      chunks.set(body.get('index'), await body.get('part').text());
      return {data: {}};
    }
    assert.ok(path.endsWith('/export'));
    assert.strictEqual(body.upload_id, 'images');
    assert.strictEqual(captures, 300);
    assert.strictEqual(chunks.size, 903);
    for (const screen of screens) {
      assert.strictEqual([0, 1, 2].map(i => chunks.get(screen.id + '|0|' + i)).join(''), 'x'.repeat(1500));
    }
    assert.strictEqual([0, 1, 2].map(i => chunks.get('screen299|1|' + i)).join(''), 'y'.repeat(1500));
    return {data: {content: 'xlsx'}};
  },
}).then(() => {
  assert.strictEqual(released, 1);
  assert.strictEqual(attempts, 2, 'the first chunk is retried after a transient failure');
  assert.strictEqual(downloads, 1, 'large export must finish without skipping captures');
  console.log('All 300 screen images are captured and uploaded in bounded chunks.');
}).catch(error => { console.error(error); process.exitCode = 1; });

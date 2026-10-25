'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { File } = require('buffer');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const start = source.indexOf('  async function _reviewTemplateLabels(');
const end = source.indexOf('  function _newProjectGenerationWarnings(', start);
assert(start > 0 && end > start);

async function run(choices, fail = false) {
  const original = new File(['original'], 'form.pdf', { type: 'application/pdf' });
  const form = new FormData();
  form.append('files', original, original.name);
  let calls = [];
  let dialogs = [];
  const context = {
    FormData, File, Uint8Array, atob,
    esc: (value) => String(value).replaceAll('<', '&lt;'),
    _setUploadProgressMessage() {}, _hideUploadProgressModal() {}, _showUploadProgressModal() {},
    _labelingChoice: async (title, body) => { dialogs.push({ title, body }); return choices.shift(); },
    apiUploadDetailed: async (url, data) => {
      calls.push(data.get('action'));
      if (data.get('action') === 'inspect') return { body: { success: true, data: {
        issues: [{ field: 'First Name', message: 'Contains spaces' }], suggest_labeling: true,
      } } };
      assert.strictEqual(data.get('author_requested'), 'true');
      if (fail) throw new Error('ALDashboard is unavailable');
      return { body: { success: true, status: 'queued', job_url: '/label-job' } };
    },
    _pollNewProjectJob: async () => ({ data: { result: {
      mappings: [{ old_name: 'First Name', new_name: 'user_name_first' }],
      added_fields: [], assessment: { issues: [] }, content_base64: btoa('labeled'),
    } } }),
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  const result = await context._reviewTemplateLabels(form);
  return { calls, dialogs, text: await result.get('files').text() };
}
(async () => {
  let result = await run([false]);
  assert.deepStrictEqual(result.calls, ['inspect']);
  assert.strictEqual(result.text, 'original');
  result = await run([true, false]);
  assert.strictEqual(result.text, 'original');
  assert(result.dialogs[1].body.includes('<th>Original</th>'));
  result = await run([true, true]);
  assert.strictEqual(result.text, 'labeled');
  assert.deepStrictEqual(result.calls, ['inspect', 'propose']);
  result = await run([true, true], true);
  assert.strictEqual(result.text, 'original');
  assert(result.dialogs[1].body.includes('ALDashboard is unavailable'));
  await assert.rejects(run([true, false], true), /Drafting canceled/);
  console.log('Field labeling author choice and review tests passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });

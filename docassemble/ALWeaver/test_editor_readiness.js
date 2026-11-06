'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const elements = {};
for (const id of ['readiness-status', 'readiness-results', 'readiness-download', 'readiness-run', 'readiness-evidence', 'readiness-review-level', 'readiness-model', 'readiness-include-llm']) {
  elements[id] = {textContent: '', innerHTML: '', value: '', checked: false};
}
elements['readiness-review-level'].value = 'precision';
let pending;
const requests = [];
const context = {
  BOOT: {features: {assistant_status: {available: true}}},
  document: {getElementById: id => elements[id]},
  state: {project: 'project', filename: 'main.yml'},
  getValidationSourceSnapshot: () => ({rawYaml: 'unsaved YAML'}),
  apiPost: (url, payload) => {
    requests.push({url, payload});
    return new Promise(resolve => {pending = resolve;});
  },
  aiJobResultGuard: () => response => response,
  agentEditorEnabled: () => false,
  esc: value => String(value).replace(/</g, '&lt;'),
  readinessSequence: 0,
  readinessReport: null,
  readinessSnapshot: null,
};
vm.createContext(context);
for (const name of ['runReadinessCheck', 'renderReadinessReport', 'draftReadinessRepair']) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0);
  vm.runInContext(source.slice(start, source.indexOf('\n  }\n', start) + 5), context);
}
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  context.runReadinessCheck();
  assert.strictEqual(requests[0].payload.raw_yaml, 'unsaved YAML');
  assert.strictEqual(requests[0].payload.include_llm, false);
  assert.strictEqual(requests[0].payload.review_level, 'precision');
  context.state.filename = 'changed.yml';
  pending({success: true, data: {status: 'pass'}});
  await flush();
  assert.match(elements['readiness-status'].textContent, /Source changed/);
  assert.strictEqual(context.readinessReport, null);
  assert.strictEqual(elements['readiness-download'].disabled, true);

  context.state.sectionDirty = true;
  context.runReadinessCheck();
  assert.strictEqual(requests.length, 1);
  assert.match(elements['readiness-status'].textContent, /Save template/);
  context.state.sectionDirty = false;
  elements['readiness-evidence'].value = '[]';
  context.runReadinessCheck();
  assert.strictEqual(requests.length, 1);
  assert.match(elements['readiness-status'].textContent, /JSON object/);

  elements['readiness-evidence'].value = '';
  elements['readiness-review-level'].value = 'thorough';
  elements['readiness-include-llm'].checked = true;
  elements['readiness-model'].value = 'custom-deployment';
  context.runReadinessCheck();
  assert.strictEqual(requests[1].payload.include_llm, true);
  assert.strictEqual(requests[1].payload.model, 'custom-deployment');
  assert.strictEqual(requests[1].payload.review_level, 'thorough');
  pending({success: false, error: {message: 'Provider unavailable'}});
  await flush();
  assert.strictEqual(elements['readiness-status'].textContent, 'Provider unavailable');
  assert.strictEqual(elements['readiness-download'].disabled, true);

  context.runReadinessCheck();
  pending({success: true, data: {
    status: 'needs_review', source_sha256: 'abc', review_evidence_current: false,
    checks: [{id: 'legal_review', status: 'needs_review', maturity_level: '1', description: '<script>unsafe</script>'}],
    findings: [{message: '<script>unsafe</script>', file_name: 'main.yml'}],
  }});
  await flush();
  assert.match(elements['readiness-results'].innerHTML, /Human review evidence/);
  assert.match(elements['readiness-results'].innerHTML, /Automated checks and coverage/);
  assert.ok(!elements['readiness-results'].innerHTML.includes('<script>'));
  assert.strictEqual(elements['readiness-download'].disabled, false);
  // A long finding becomes a bounded, persisted draft. Existing assistant
  // sessions are preserved, and unavailable assistants expose no repair button.
  const finding = {
    code: 'STYLE001', message: 'Review this label', file_name: 'docassemble/Test/data/questions/changed.yml',
    context: {repair_context: {schema_version: 1, block_index: 0, source_sha256: 'hash', source_yaml: 'x'.repeat(12000)}},
  };
  context.readinessReport.findings = [finding];
  context.agentEditorEnabled = () => true;
  context.BOOT.features.assistant_status.available = false;
  context.renderReadinessReport();
  assert.ok(!elements['readiness-results'].innerHTML.includes('data-finding-index'));
  context.BOOT.features.assistant_status.available = true;
  context.renderReadinessReport();
  assert.ok(elements['readiness-results'].innerHTML.includes('data-finding-index'));
  let prepared;
  let allowDraft = false;
  let closed = false;
  context.agentChat = {prepareDraft: (message, expectedSource) => {
    prepared = {message, expectedSource}; return allowDraft;
  }};
  context.closeBootstrapModal = () => {closed = true;};
  context.setAssistantOpen = () => {};
  context.draftReadinessRepair(0);
  pending({success: true, data: finding});
  await flush();
  assert.ok(!closed, 'existing candidate is preserved');
  assert.match(elements['readiness-status'].textContent, /busy or unavailable/);
  allowDraft = true;
  context.draftReadinessRepair(0);
  pending({success: true, data: finding});
  await flush();
  assert.ok(closed);
  assert.ok(prepared.message.length < 8000);
  assert.ok(prepared.message.includes('source_sha256'));
  assert.strictEqual(prepared.expectedSource, 'unsaved YAML');
  context.getValidationSourceSnapshot = () => {throw new Error('Order builder has unsaved edits');};
  const before = requests.length;
  context.draftReadinessRepair(0);
  assert.strictEqual(requests.length, before);
  assert.strictEqual(elements['readiness-status'].textContent, 'Order builder has unsaved edits');
  console.log('Readiness controls passed');
})().catch(error => {console.error(error); process.exitCode = 1;});

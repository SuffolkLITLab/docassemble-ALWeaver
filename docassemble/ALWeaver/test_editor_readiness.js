'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const elements = {};
for (const id of ['readiness-status', 'readiness-results', 'readiness-download', 'readiness-run', 'readiness-precision', 'readiness-research', 'readiness-issue', 'readiness-issue-draft']) {
  elements[id] = {textContent: '', innerHTML: '', value: '', checked: false};
}
elements['readiness-precision'].checked = true;
elements['readiness-research'].checked = true;
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
for (const name of ['runReadinessCheck', 'renderReadinessReport', 'draftReadinessRepair', 'readinessIssueMarkdown', 'openReadinessIssueDraft', 'publishReadinessIssue']) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0);
  vm.runInContext(source.slice(start, source.indexOf('\n  }\n', start) + 5), context);
}
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  context.runReadinessCheck();
  assert.strictEqual(requests[0].payload.raw_yaml, 'unsaved YAML');
  assert.strictEqual(requests[0].payload.ai_second_opinion, true);
  assert.strictEqual(requests[0].payload.review_level, 'precision');
  assert.strictEqual(requests[0].payload.include_research, true);
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
  elements['readiness-precision'].checked = false;
  elements['readiness-research'].checked = false;
  context.runReadinessCheck();
  assert.strictEqual(requests[1].payload.ai_second_opinion, false);
  assert.strictEqual(requests[1].payload.include_research, false);
  assert.ok(!('model' in requests[1].payload));
  assert.ok(!('evidence' in requests[1].payload));
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
    review: {actionable: [{source: 'static', finding_indexes: [0], message: '<script>unsafe</script>', priority: 'high', release_gate: true}], process_evidence: [{}]},
  }});
  await flush();
  assert.ok(!elements['readiness-results'].innerHTML.includes('About human review records'));
  assert.match(elements['readiness-results'].innerHTML, /Fix before publishing/);
  assert.ok(!elements['readiness-results'].innerHTML.includes('<script>'));
  assert.strictEqual(elements['readiness-download'].disabled, false);
  assert.match(elements['readiness-status'].textContent, /1 to fix before publishing/);
  assert.ok(!elements['readiness-status'].textContent.includes('evidence'));
  context.readinessReport.ai_review = {execution_status: 'failed'};
  context.renderReadinessReport();
  assert.match(elements['readiness-status'].textContent, /incomplete/);
  context.readinessReport.review.actionable.push({message: 'Check output mapping', priority: 'medium'});
  context.readinessReport.review.cleanup = [{message: 'Optional naming cleanup', priority: 'low'}];
  context.readinessReport.review.coverage = [{detail: 'An include could not be inspected'}];
  context.readinessReport.review.ai_dismissed = [{message: 'Counterevidence found'}];
  context.renderReadinessReport();
  const html = elements['readiness-results'].innerHTML;
  assert.match(elements['readiness-status'].textContent, /1 to fix before publishing · 1 to review/);
  assert.ok(html.indexOf('Fix before publishing') < html.indexOf('Needs your review'));
  assert.match(html, /<details class="mt-3"><summary>Optional improvements/);
  assert.match(html, /How this review was done/);
  assert.match(html, /Assessment: <\/span>Fix before publishing/);
  assert.ok(html.indexOf('readiness-assessment') < html.indexOf('Action checklist'));
  assert.ok(!html.includes('Technical evidence'));
  assert.ok(!html.includes('source_sha256'));
  assert.ok(!html.includes('All check results and report data'));
  assert.match(html, /Review limitations/);
  assert.match(html, /Action checklist/);
  assert.match(html, /editor-readiness-danger/);
  assert.match(html, /aria-hidden="true"><i class="fa-solid fa-circle-exclamation/);
  assert.match(html, /href="#readiness-action-0"/);
  assert.match(html, /id="readiness-action-0"/);
  assert.match(html, /Dismissed by the AI second opinion/);
  const issue = context.readinessIssueMarkdown(context.readinessReport, {project: 'Project', filename: 'main.yml'});
  assert.match(issue, /## Pre-publication checklist/);
  assert.match(issue, /- \[ \] Fix:/);
  assert.match(issue, /- \[ \] Resolve or explain: Check output mapping/);
  assert.ok(issue.indexOf('## Findings') < issue.indexOf('<summary>Optional improvements'));
  assert.ok(!issue.includes('human review records'));
  assert.ok(!issue.includes('<script>'));
  assert.match(issue, /has not been verified to match GitHub/);
  assert.ok(!issue.includes('- [ ] Optional naming cleanup'));
  const savedReport = context.readinessReport;
  context.readinessReport = {checks: [{status: 'pass'}], findings: [], ai_review: {execution_status: 'completed', coverage_gaps: ['Text truncated: long.yml']}, author_review: {actionable: [], cleanup: [{message: 'Template suggestions', evidence: {templates: [{file: 'form.docx', notes: [{detail: '<script>Use headings</script>'}]}]}}]}};
  context.renderReadinessReport();
  const limitedHtml = elements['readiness-results'].innerHTML;
  assert.match(limitedHtml, /review coverage is limited/);
  assert.match(limitedHtml, /editor-readiness-warning/);
  assert.match(limitedHtml, /fa-circle-question/);
  assert.ok(!limitedHtml.includes('editor-readiness-success'));
  assert.match(limitedHtml, /Only part of this file was sent to the AI: long.yml/);
  assert.match(limitedHtml, /Supporting details/);
  assert.match(limitedHtml, /form.docx/);
  assert.match(limitedHtml, /Use headings/);
  assert.ok(!limitedHtml.includes('<script>'));
  assert.ok(!limitedHtml.includes('"templates"'));
  context.readinessReport = {checks: [], author_review: {actionable: [{message: 'Check eligibility', priority: 'medium'}]}};
  context.renderReadinessReport();
  assert.match(elements['readiness-results'].innerHTML, /Assessment: <\/span>Review the findings before publishing/);
  assert.match(elements['readiness-results'].innerHTML, /Focus your review here: Check eligibility/);
  assert.match(elements['readiness-results'].innerHTML, /fa-magnifying-glass/);
  context.readinessReport = {author_review: {actionable: []}};
  context.renderReadinessReport();
  assert.match(elements['readiness-results'].innerHTML, /editor-readiness-success/);
  assert.match(elements['readiness-results'].innerHTML, /fa-circle-check/);
  assert.match(elements['readiness-results'].innerHTML, /No publication problems detected by the completed checks/);
  context.readinessReport.ai_review = {execution_status: 'failed'};
  context.renderReadinessReport();
  assert.match(elements['readiness-results'].innerHTML, /editor-readiness-warning/);
  assert.ok(!elements['readiness-results'].innerHTML.includes('editor-readiness-success'));
  context.readinessReport = {research: {execution_status: 'incomplete', coverage_gaps: ['Source was unavailable'], findings: [{local_quote: 'Example instruction', source_explanation: 'Check the applicable rule', source_urls: ['https://court.example/rule', 'javascript:alert(1)']}]}, author_review: {actionable: [{source: 'research', finding_indexes: [0], message: 'Check the deadline', priority: 'high', release_gate: false, ai_review_quote: 'Example instruction'}]}};
  context.renderReadinessReport();
  const researched = elements['readiness-results'].innerHTML;
  assert.match(researched, /Needs your review/);
  assert.match(researched, /Legal-source research is incomplete/);
  assert.match(researched, /https:\/\/court.example\/rule/);
  assert.match(researched, /Example instruction/);
  assert.strictEqual(researched.split('Example instruction').length - 1, 1);
  assert.match(researched, /External legal sources/);
  assert.match(researched, /<pre class="editor-readiness-excerpt">/);
  assert.ok(!researched.includes('javascript:'));
  assert.match(elements['readiness-status'].textContent, /Legal-source research incomplete/);
  context.readinessReport = savedReport;
  // A long finding becomes a bounded, persisted draft. Existing assistant
  // sessions are preserved, and unavailable assistants expose no repair button.
  const finding = {
    code: 'STYLE001', message: 'Review this label', file_name: 'docassemble/Test/data/questions/changed.yml',
    context: {repair_context: {schema_version: 1, block_index: 0, source_sha256: 'hash', source_yaml: 'x'.repeat(12000)}},
  };
  context.readinessReport.findings = [finding];
  context.readinessReport.author_review = {actionable: [{source: 'static', finding_indexes: [0], message: 'Author-facing action', line: 5, release_gate: true, priority: 'high'}]};
  context.agentEditorEnabled = () => true;
  context.BOOT.features.assistant_status.available = false;
  context.renderReadinessReport();
  assert.ok(!elements['readiness-results'].innerHTML.includes('data-finding-index'));
  context.BOOT.features.assistant_status.available = true;
  context.renderReadinessReport();
  assert.ok(elements['readiness-results'].innerHTML.includes('data-finding-index'));
  assert.match(elements['readiness-results'].innerHTML, /Author-facing action/);
  assert.match(elements['readiness-results'].innerHTML, /Reviewed source excerpt/);
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
  for (const id of ['readiness-issue-repository', 'readiness-issue-title', 'readiness-issue-body', 'readiness-issue-status', 'readiness-issue-submit']) elements[id] = {value: '', textContent: '', focus() {}};
  elements['readiness-issue-draft'].dataset = {};
  elements['readiness-issue-draft'].scrollIntoView = () => {};
  context.openReadinessIssueDraft();
  assert.match(elements['readiness-status'].textContent, /Order builder/);
  context.getValidationSourceSnapshot = () => ({rawYaml: 'unsaved YAML'});
  context.state.projectSyncs = {};
  context.openReadinessIssueDraft();
  assert.match(elements['readiness-status'].textContent, /Connect this Playground project/);
  context.state.projectSyncs[context.state.project] = {repository_url: 'https://github.com/org/repo'};
  context.openReadinessIssueDraft();
  assert.strictEqual(elements['readiness-issue-draft'].dataset.repository, 'https://github.com/org/repo');
  elements['readiness-issue-body'].value = 'Edited checklist\n- [ ] Fix';
  context.publishReadinessIssue();
  const issueRequest = requests[requests.length - 1];
  assert.strictEqual(issueRequest.url, '/api/weaver/readiness/issue');
  assert.strictEqual(issueRequest.payload.body, 'Edited checklist\n- [ ] Fix');
  const count = requests.length;
  context.publishReadinessIssue();
  assert.strictEqual(requests.length, count);
  pending({success: false, error: {message: 'Issues are disabled'}});
  await flush();
  assert.match(elements['readiness-issue-status'].textContent, /Issues are disabled/);
  assert.strictEqual(elements['readiness-issue-body'].value, 'Edited checklist\n- [ ] Fix');
  context.getValidationSourceSnapshot = () => ({rawYaml: 'changed'});
  context.publishReadinessIssue();
  assert.strictEqual(requests.length, count);
  assert.match(elements['readiness-issue-status'].textContent, /source changed/);
  console.log('Readiness controls passed');
})().catch(error => {console.error(error); process.exitCode = 1;});

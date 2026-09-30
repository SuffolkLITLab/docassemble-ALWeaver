'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const context = {
  state: {
    filename: 'matrix_doc_revision.yml',
    templateImportBusy: null,
    templateImportSelection: {},
    templateImportResult: {
      template_filename: 'petition.docx',
      interview_filename: 'matrix_doc_revision.yml',
      already_imported: true,
      mapping_changes: {
        added: ['matrix_doc_added'],
        removed: ['matrix_doc_removed'],
        retained: ['matrix_doc_primary'],
      },
      stale_question_variables: ['matrix_doc_removed'],
      warnings: ['Existing question screens still ask for matrix_doc_removed.'],
      bundle_additions: [],
      questions: [],
      document_object: {
        kind: 'document_object',
        title: 'ALDocument for petition.docx',
        yaml: 'objects: ...',
        supporting_blocks: [
          {
            kind: 'template',
            title: 'Display title for petition.docx',
            yaml: 'template: petition_attachment_title',
          },
        ],
      },
    },
  },
  isImportableTemplate: () => true,
  templateIsAttached: () => true,
  templateImportCandidates: () => [
    {
      key: 'document_object',
      title: 'ALDocument for petition.docx',
      yaml: 'objects: ...',
      supporting_blocks: [
        {
          kind: 'template',
          title: 'Display title for petition.docx',
          yaml: 'template: petition_attachment_title',
        },
      ],
    },
  ],
  esc: (value) =>
    String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;'),
};

vm.createContext(context);
const start = source.indexOf('  function renderTemplateImportCard(');
const end = source.indexOf('\n  function templateImportCandidates(', start);
assert.notStrictEqual(start, -1);
assert.notStrictEqual(end, -1);
vm.runInContext(source.slice(start, end), context);

const html = context.renderTemplateImportCard({
  filename: 'petition.docx',
  preview_kind: 'docx',
});
assert.ok(html.includes('template-import-mapping-diff'));
assert.ok(html.includes('Added template fields'));
assert.ok(html.includes('matrix_doc_added'));
assert.ok(html.includes('Removed template fields'));
assert.ok(html.includes('matrix_doc_removed'));
assert.ok(html.includes('Retained template fields'));
assert.ok(html.includes('matrix_doc_primary'));
assert.ok(html.includes('Existing question screens still ask'));
assert.ok(html.includes('required supporting template(s)'));
assert.ok(html.includes('Display title for petition.docx'));

const candidateStart = source.indexOf('  function templateImportCandidates(');
const candidateEnd = source.indexOf('\n  function importSelectedTemplate(', candidateStart);
assert.notStrictEqual(candidateStart, -1);
assert.notStrictEqual(candidateEnd, -1);
vm.runInContext(source.slice(candidateStart, candidateEnd), context);
const candidates = context.templateImportCandidates({
  document_object: {
    title: 'ALDocument for petition.docx',
    yaml: 'objects: ...',
    supporting_blocks: [
      { title: 'Display title for petition.docx', yaml: 'template: petition_attachment_title' },
    ],
  },
});
assert.strictEqual(candidates[0].supporting_blocks.length, 1);
assert.strictEqual(candidates[0].supporting_blocks[0].yaml, 'template: petition_attachment_title');

context.state.templateImportResult = {
  project: 'matrix_doc_revision',
  interview_filename: 'main.yml',
  interview_revision: 'source-revision',
  document_object: {
    title: 'ALDocument for petition.docx',
    yaml: 'objects: {petition: ALDocument.using(...)}',
    supporting_blocks: [
      { title: 'Display title', yaml: 'template: petition_attachment_title' },
    ],
  },
  attachment: null,
  objects: null,
  questions: [],
  bundle_additions: [],
};
context.state.templateImportSelection = { document_object: true };
let sentPayload = null;
context.apiPost = (_path, payload) => {
  sentPayload = payload;
  return Promise.resolve({ success: true });
};
context._showSuccessBanner = () => {};
context.loadFile = () => Promise.resolve();
context.renderOutline = () => {};
context.renderCanvas = () => {};
context.isSupersededRequest = () => false;
context.showApiError = (error) => {
  throw error;
};
const applyStart = source.indexOf('  function applyTemplateImport()');
const applyEnd = source.indexOf('\n  function setTemplatesMode(', applyStart);
assert.notStrictEqual(applyStart, -1);
assert.notStrictEqual(applyEnd, -1);
vm.runInContext(source.slice(applyStart, applyEnd), context);

(async () => {
  context.applyTemplateImport();
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(sentPayload.blocks.includes('objects: {petition: ALDocument.using(...)}'));
  assert.ok(sentPayload.blocks.includes('template: petition_attachment_title'));

  sentPayload = null;
  context.state.templateImportSelection = { document_object: false };
  context.applyTemplateImport();
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(sentPayload, null, 'deselecting ALDocument omits its title dependency');

  const reimportCandidates = context.templateImportCandidates({
    document_object: null,
    attachment: { title: 'Replace attachment', yaml: 'attachment: ...' },
  });
  assert.strictEqual(reimportCandidates.length, 1);
  assert.strictEqual(reimportCandidates[0].supporting_blocks.length, 0);
})().catch((error) => {
  process.nextTick(() => {
    throw error;
  });
});

'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
let captured = 0;
let dirty = 0;
let renders = 0;
const context = {
  state: {documents: {bundles: [
    {name: 'user', elements: ['petition', 'affidavit']},
    {name: 'court', elements: ['petition']},
  ]}},
  captureDocumentEnabledInputs: () => { captured++; },
  markDocumentsDirty: () => { dirty++; },
  renderCanvas: () => { renders++; },
};
vm.createContext(context);
const start = source.indexOf('  function removeDocumentFromBundles(');
const end = source.indexOf('\n  }', start) + 4;
vm.runInContext(source.slice(start, end), context);
context.removeDocumentFromBundles('petition', 'user');
assert.deepStrictEqual(Array.from(context.state.documents.bundles[0].elements), ['affidavit']);
assert.deepStrictEqual(Array.from(context.state.documents.bundles[1].elements), ['petition']);
context.removeDocumentFromBundles('petition', null);
assert.deepStrictEqual(Array.from(context.state.documents.bundles[1].elements), []);
assert.strictEqual(captured, 2);
assert.strictEqual(dirty, 2);
assert.strictEqual(renders, 2);
context.state.documentsBusy = true;
context.removeDocumentFromBundles('affidavit', null);
assert.strictEqual(context.state.documents.bundles[0].elements.length, 1);
context.state.documentsBusy = false;
context.state.documents.documents = [{name: 'petition'}, {name: 'affidavit'}];
context.window = {confirm: () => true};
const deleteStart = source.indexOf('  function deleteDocumentFromInterview(');
vm.runInContext(source.slice(deleteStart, source.indexOf('\n  }', deleteStart) + 4), context);
context.deleteDocumentFromInterview('affidavit');
assert.deepStrictEqual(Array.from(context.state.documents.removed), ['affidavit']);
assert.strictEqual(context.state.documents.documents.length, 1);
assert.strictEqual(context.state.documents.bundles[0].elements.length, 0);

// A screen carrying both a question and an attachment keeps the question
// editor, which is where the "Edit attachment field mappings" button lives.
// A standalone attachment block still gets the plain attachment card.
const routed = [];
const canvas = {
  window: {ALWeaverSerializers: require('./data/static/editor_serializers.js')},
  state: {project: 'p', questionEditMode: 'preview'},
  canvasContent: {innerHTML: ''},
  selected: null,
  renderProjectSelector: () => { routed.push('project'); },
  renderQuestionBlock: () => { routed.push('question'); },
  renderReviewBlock: () => { routed.push('review'); },
  renderCommentedBlock: () => { routed.push('commented'); },
  renderCodeBlock: () => { routed.push('code'); },
  renderObjectsBlock: () => { routed.push('objects'); },
  renderGenericBlock: () => { routed.push('generic'); },
  emptyCanvasHtml: () => '',
  esc: (value) => String(value),
};
canvas.getSelectedBlock = () => canvas.selected;
vm.createContext(canvas);
const templateStart = source.indexOf('  function isTemplateEditorBlock(');
vm.runInContext(source.slice(templateStart, source.indexOf('\n  }', templateStart) + 4), canvas);
const helperStart = source.indexOf('  function isQuestionEditorBlock(');
vm.runInContext(source.slice(helperStart, source.indexOf('\n  }', helperStart) + 4), canvas);
const canvasStart = source.indexOf('  function renderBlockCanvas(');
vm.runInContext(source.slice(canvasStart, source.indexOf('\n  }', canvasStart) + 4), canvas);
canvas.selected = {type: 'question', title: 'Plain', data: {}};
canvas.renderBlockCanvas();
canvas.selected = {type: 'attachment', title: 'Your documents',
  data: {question: 'Your documents', attachment: {'variable name': 'petition[i]'}}};
canvas.renderBlockCanvas();
assert.deepStrictEqual(routed, ['question', 'question']);
canvas.selected = {type: 'attachment', title: 'Petition',
  data: {attachment: {'variable name': 'petition[i]'}}};
canvas.renderBlockCanvas();
assert.deepStrictEqual(routed, ['question', 'question']);
assert.ok(canvas.canvasContent.innerHTML.includes('data-edit-attachment-mappings'));

// Saving must follow the same dispatch as rendering, including in YAML mode.
const saveStart = source.indexOf('  function getBlockYamlForSave(');
vm.runInContext(source.slice(saveStart, source.indexOf('\n  }', saveStart) + 4), canvas);
canvas.serializeQuestionBlockToYaml = () => 'question: Edited question\nfields:\n  - Name: users[0].name';
canvas.getSourceEditorValue = () => 'question: Edited in YAML';
for (const type of ['question', 'attachment']) {
  const block = {type, yaml: 'question: Original', data: {question: 'Original', attachment: {}}};
  assert.ok(canvas.getBlockYamlForSave(block).includes('question: Edited question'));
}
assert.strictEqual(canvas.getBlockYamlForSave({type: 'attachment', data: {}, yaml: 'attachment: original'}), 'attachment: original');
canvas.state.questionEditMode = 'yaml';
assert.strictEqual(canvas.getBlockYamlForSave({type: 'attachment', data: {question: 'Original'}, yaml: 'original'}), 'question: Edited in YAML');

// Template scope remains explicit in a project with multiple interview files.
const templateScope = {
  state: {
    filename: 'second.yml',
    files: [{filename: 'first.yml'}, {filename: 'second.yml'}],
    documents: {templates: {'form.pdf': {status: 'not_imported'}}},
  },
  esc: (value) => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;'),
};
vm.createContext(templateScope);
for (const name of ['renderTemplateInterviewSelector', 'renderUnimportedTemplatesCard']) {
  const begin = source.indexOf(`  function ${name}(`);
  vm.runInContext(source.slice(begin, source.indexOf('\n  }', begin) + 4), templateScope);
}
let selector = templateScope.renderTemplateInterviewSelector();
assert.ok(selector.includes('data-template-interview="second.yml" aria-current="true"'));
assert.ok(selector.includes('data-template-interview="first.yml"'));
assert.ok(selector.includes('>Change</button>'));
assert.ok(selector.includes('class="list-group mt-2" hidden'));
assert.ok(!selector.includes('<select'));
assert.ok(templateScope.renderUnimportedTemplatesCard().includes('Templates not imported into second.yml'));
templateScope.state.templateImportBusy = 'form.pdf';
assert.ok(templateScope.renderTemplateInterviewSelector().includes('aria-controls="template-interview-choices" disabled'));
templateScope.state.templateImportBusy = null;
templateScope.state.filename = 'first.yml';
templateScope.state.documents = {templates: {'form.pdf': {status: 'attached'}}};
assert.ok(templateScope.renderTemplateInterviewSelector().includes('data-template-interview="first.yml" aria-current="true"'));
assert.strictEqual(templateScope.renderUnimportedTemplatesCard(), '');

Object.assign(templateScope, {
  API: '/al/editor',
  outlineList: {innerHTML: ''},
  getSectionFiles: () => [{filename: 'form.pdf'}],
  getSectionFromView: () => 'template',
  sectionTypeTag: () => 'PDF',
  supportsDashboardEditor: () => false,
  initOutlineSortable: () => {},
  templateStatus: () => ({status: 'not_imported'}),
});
Object.assign(templateScope.state, {
  currentView: 'templates', searchQuery: '', sectionSelectedFile: {},
});
const outlineStart = source.indexOf('  function renderSectionOutline(');
vm.runInContext(source.slice(outlineStart, source.indexOf('\n  }', outlineStart) + 4), templateScope);
templateScope.renderSectionOutline();
const outlineHtml = templateScope.outlineList.innerHTML;
assert.ok(outlineHtml.indexOf('change-template-interview') < outlineHtml.indexOf('data-section-filename'));
assert.ok(outlineHtml.includes('form.pdf</div><span class="editor-outline-status"'));
assert.ok(outlineHtml.includes('title="Not imported into first.yml">Not imported</span>'));
templateScope.state.searchQuery = 'no match';
templateScope.renderSectionOutline();
assert.ok(templateScope.outlineList.innerHTML.includes('change-template-interview'));
assert.ok(templateScope.outlineList.innerHTML.includes('No files found'));

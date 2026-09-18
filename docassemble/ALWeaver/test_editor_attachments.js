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

'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const editorSource = fs.readFileSync(
  path.join(__dirname, 'data/static/editor.js'),
  'utf8',
);

function editorFunction(name) {
  const start = editorSource.indexOf('  function ' + name + '(');
  assert.notStrictEqual(start, -1, name);
  const end = editorSource.indexOf('\n  }\n', start);
  assert.notStrictEqual(end, -1, name);
  return editorSource.slice(start, end + '\n  }'.length);
}

const block = { id: 'q1', type: 'question', data: { question: '' } };
const titleInput = {
  value: '',
  getAttribute(name) {
    return name === 'data-block-id' ? 'q1' : null;
  },
};
const context = {
  state: {
    project: 'test',
    filename: 'main.yml',
    currentView: 'interview',
    selectedBlockId: 'q1',
    questionEditMode: 'preview',
    blankQuestionAllowed: {},
    sectionDirty: false,
    assemblyLineSettingsDirty: false,
    documentsDirty: false,
  },
  document: { getElementById: () => titleInput },
  dirtyState: { hasDirty: () => false },
  getBlockById: () => block,
};
vm.createContext(context);
vm.runInContext(
  ['blankQuestionKey', 'blankQuestionNeedsDecision', 'hasUnsavedChanges']
    .map(editorFunction)
    .join('\n'),
  context,
);

// Inserting a blank question writes a clean draft. It still needs a decision
// before navigation, even though no editor input has been changed yet.
assert.strictEqual(context.hasUnsavedChanges(), true);

titleInput.value = '   ';
assert.strictEqual(context.hasUnsavedChanges(), true);
titleInput.value = 'What is your name?';
assert.strictEqual(context.hasUnsavedChanges(), false);

titleInput.value = '';
context.state.blankQuestionAllowed[context.blankQuestionKey(block)] = true;
assert.strictEqual(context.hasUnsavedChanges(), false);

delete context.state.blankQuestionAllowed[context.blankQuestionKey(block)];
titleInput.getAttribute = () => 'another-block';
assert.strictEqual(context.hasUnsavedChanges(), true);

context.state.currentView = 'templates';
assert.strictEqual(context.hasUnsavedChanges(), false);

'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const serializers = require('./data/static/editor_serializers.js');
const source = fs.readFileSync(path.join(__dirname, 'data/static/editor.js'), 'utf8');
function editorFunction(name) {
  const start = source.indexOf('  function ' + name + '(');
  assert.notStrictEqual(start, -1, name);
  return source.slice(start, source.indexOf('\n  }\n', start) + 5);
}
function clickBranch(condition) {
  const start = source.indexOf('    if (' + condition + ') {');
  assert.notStrictEqual(start, -1, condition);
  return '(function () {\n' + source.slice(start, source.indexOf('\n    }\n', start) + 7) + '\n})();';
}
async function checkInvalidScreen(data, values, message, blockType = 'question') {
  const original = JSON.stringify(data);
  const block = {id: 'screen', type: blockType, data};
  const alerts = [];
  let saved = 0;
  let redrawn = 0;
  const context = {
    document: {getElementById: id => values[id] || null, querySelectorAll: () => []},
    window: {ALWeaverSerializers: serializers, alert: text => alerts.push(text)},
    state: {questionEditMode: 'preview', questionBlockTab: 'screen', canvasMode: 'question',
      filename: 'test.yml', currentView: 'interview'},
    _screenValidationMessage: '',
    _stashFullYamlContent() {},
    isInterviewView: () => true,
    getSelectedBlock: () => block,
    _generatedALFieldSets: () => [],
    syncMandatoryToData() {},
    renderCanvas() { redrawn++; },
    apiPost() { saved++; throw new Error('Invalid data reached the API'); },
  };
  vm.createContext(context);
  vm.runInContext([
    'syncQuestionMetaToData', 'syncFieldsToData', 'stashCurrentEditorState',
    'serializeQuestionBlockToYaml', 'isQuestionEditorBlock', 'getBlockYamlForSave',
    'promptAndSaveUnsavedChanges', 'deferNavigationForUnsavedChanges', 'describeWorkingSource',
  ].map(editorFunction).join('\n'), context);

  // The direct Save action must stop before API access and keep invalid text.
  context.target = {id: 'save-block-btn'};
  vm.runInContext(clickBranch("target.id === 'save-block-btn'"), context);
  assert.strictEqual(saved, 0);
  assert.match(alerts.at(-1), message);
  assert.strictEqual(JSON.stringify(block.data), original);

  for (const id of ['toggle-advanced', 'adv-show-more']) {
    const count = alerts.length;
    context.target = {id};
    vm.runInContext(clickBranch("target.id === '" + id + "'"), context);
    assert.strictEqual(alerts.length, count + 1);
    assert.strictEqual(redrawn, 0, 'Invalid controls must remain on screen');
  }
  // These callers have different contracts: promises for save prompts and a
  // true return value to tell navigation callers that the action was deferred.
  assert.strictEqual(await context.promptAndSaveUnsavedChanges('switch views'), false);
  assert.strictEqual(context.deferNavigationForUnsavedChanges('switch views', () => {
    throw new Error('Navigation must not proceed');
  }), true);
  // Validation must fail with the actual message, never validate saved data.
  assert.throws(() => context.describeWorkingSource(), message);
  assert.match(alerts.at(-1), message);
  assert.strictEqual(JSON.stringify(block.data), original);

  // Correcting the same controls recovers without reopening the question.
  if (values['screen-signature']) values['screen-signature'].value = 'users[0].signature';
  if (values['screen-yesno']) values['screen-yesno'].value = 'answer';
  if (values['screen-choice-value-0']) values['screen-choice-value-0'].value = '42';
  if (values['screen-choice-label-0']) values['screen-choice-label-0'].value = 'Amount';
  assert.notStrictEqual(context.syncQuestionMetaToData(block), false);
  assert.strictEqual(context._screenValidationMessage, '');
}

(async () => {
  await checkInvalidScreen({question: 'Sign', signature: 'signature'},
    {'screen-signature': {value: ''}}, /Enter a variable to store the signature/);
  await checkInvalidScreen({question: 'Agree?', yesno: 'answer'},
    {'screen-yesno': {value: '  '}}, /Enter an answer variable/);
  await checkInvalidScreen({question: 'Choose', buttons: [{Amount: 1}]}, {
    'screen-choice-label-0': {value: 'Amount'},
    'screen-choice-value-0': {value: 'abc'},
    'screen-choice-type-0': {value: 'number'},
  }, /Enter a valid number/);
  await checkInvalidScreen({question: 'Choose', buttons: [{Amount: 1, color: 'danger'}]}, {
    'screen-choice-label-0': {value: 'color'},
  }, /reserved or conflicts/);
  await checkInvalidScreen({question: 'Sign', signature: 'signature', attachment: {name: 'Form'}},
    {'screen-signature': {value: ''}}, /Enter a variable to store the signature/, 'attachment');
  console.log('Screen validation actions passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

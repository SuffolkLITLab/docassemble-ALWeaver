'use strict';

const assert = require('assert');
const runtime = require('./data/static/editor_runtime_inspector.js');

assert.deepStrictEqual(
  runtime.filterVariables({ zebra: 1, Alpha: 2, beta: 3 }, 'a'),
  { Alpha: 2, beta: 3, zebra: 1 }
);
assert.deepStrictEqual(
  runtime.changedVariableNames(
    { unchanged: 1, changed: 'old', removed: true },
    { unchanged: 1, changed: 'new', added: false }
  ),
  ['added', 'changed', 'removed']
);

assert.strictEqual(
  runtime.questionLabel({ questionText: '<p>What is <strong>your name</strong>?</p>' }),
  'What is your name?'
);
assert.strictEqual(
  runtime.questionIdentity({ questionName: 'user_name', questionText: 'Your name' }),
  'user_name'
);
assert.strictEqual(
  runtime.findQuestionSource(
    { questionName: 'user_name' },
    [{ id: 'other' }, { id: 'user_name', type: 'question' }]
  ).id,
  'user_name'
);
assert.strictEqual(
  runtime.findQuestionSource(
    { questionName: 'review_answers' },
    [{ id: 'generated', data: { event: 'review_answers' } }]
  ).id,
  'generated'
);
assert.strictEqual(runtime.variablePreview(undefined), '(removed)');
assert.ok(runtime.variablePreview('x'.repeat(200)).length <= 90);

let steps = runtime.updateStepHistory(
  [],
  { questionName: 'name', questionText: 'Your name' },
  {},
  []
);
steps = runtime.updateStepHistory(
  steps,
  { questionName: 'address', questionText: 'Your address' },
  { user_name: 'Pat' },
  ['user_name']
);
assert.strictEqual(steps.length, 2, 'a new screen adds a recorder step');
assert.deepStrictEqual(
  steps[0].answers,
  [{ name: 'user_name', value: 'Pat' }],
  'changed variables are attributed to the screen that collected them'
);
steps = runtime.updateStepHistory(
  steps,
  { questionName: 'address', questionText: 'Your address' },
  { user_name: 'Pat' },
  []
);
assert.strictEqual(steps.length, 2, 'refreshing one screen does not duplicate it');

console.log('editor_runtime_inspector.js: all assertions passed');

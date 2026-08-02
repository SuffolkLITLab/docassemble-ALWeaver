'use strict';

const assert = require('assert');
const runtime = require('./data/static/editor_runtime_inspector.js');

function run() {
  assert.deepStrictEqual(
    runtime.filterVariables({ zebra: 1, answer: 2, user_name: 3 }, 'user'),
    { user_name: 3 }
  );
  assert.deepStrictEqual(
    runtime.changedVariableNames({ answer: 1, removed: true }, { answer: 2, added: true }),
    ['added', 'answer', 'removed']
  );
  assert.strictEqual(
    runtime.findQuestionSource(
      { questionName: 'intro' },
      [{ id: 'generated-id', data: { id: 'intro' } }]
    ).id,
    'generated-id'
  );
  assert.strictEqual(
    runtime.findQuestionSource({ questionType: 'fields' }, [{ id: 'intro' }]),
    null
  );
}

run();

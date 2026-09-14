'use strict';

const assert = require('assert');
const runtime = require('./data/static/editor_runtime_inspector.js');

assert.deepStrictEqual(
  runtime.filterVariables({ zebra: 1, Alpha: 2, beta: 3 }, 'a'),
  { Alpha: 2, beta: 3, zebra: 1 },
);
assert.deepStrictEqual(
  runtime.changedVariableNames(
    { unchanged: 1, changed: 'old', removed: true },
    { unchanged: 1, changed: 'new', added: false },
  ),
  ['added', 'changed', 'removed'],
);

assert.strictEqual(
  runtime.questionLabel({
    questionText: '<p>What is <strong>your name</strong>?</p>',
  }),
  'What is your name?',
);
assert.strictEqual(
  runtime.questionIdentity({
    questionName: 'user_name',
    questionText: 'Your name',
  }),
  'user_name',
);
assert.strictEqual(
  runtime.findQuestionSource({ questionName: 'user_name' }, [
    { id: 'other' },
    { id: 'user_name', type: 'question' },
  ]).id,
  'user_name',
);
assert.strictEqual(
  runtime.findQuestionSource({ questionName: 'review_answers' }, [
    { id: 'generated', data: { event: 'review_answers' } },
  ]).id,
  'generated',
);
// Docassemble prefixes Question.name with "ID " when the block has an
// explicit `id:` field (docassemble_base/base/parse.py: self.name = "ID " +
// self.id). The step recorder must strip that prefix so the label matches
// the literal `id: <value>` text in the source YAML.
assert.strictEqual(
  runtime.blockIdLabel('ID tenancy_address', 'question'),
  'id: tenancy_address',
);
// A name with no explicit id is an auto-generated Question_N/Block_N label,
// not a literal id, so it is shown as-is rather than mislabeled "id: ...".
assert.strictEqual(
  runtime.blockIdLabel('Question_12', 'question'),
  'Question_12',
);
assert.strictEqual(runtime.blockIdLabel('', 'question'), 'question');

assert.strictEqual(runtime.variablePreview(undefined), '(removed)');
assert.ok(runtime.variablePreview('x'.repeat(200)).length <= 90);

let steps = runtime.updateStepHistory(
  [],
  { questionName: 'name', questionText: 'Your name' },
  {},
  [],
);
steps = runtime.updateStepHistory(
  steps,
  { questionName: 'address', questionText: 'Your address' },
  { user_name: 'Pat' },
  ['user_name'],
);
assert.strictEqual(steps.length, 2, 'a new screen adds a recorder step');
assert.deepStrictEqual(
  steps[0].answers,
  [{ name: 'user_name', value: 'Pat' }],
  'changed variables are attributed to the screen that collected them',
);
steps = runtime.updateStepHistory(
  steps,
  { questionName: 'address', questionText: 'Your address' },
  { user_name: 'Pat' },
  [],
);
assert.strictEqual(
  steps.length,
  2,
  'refreshing one screen does not duplicate it',
);

async function testHideStopsPollingAndBlocksPendingRepaint() {
  let intervalStarts = 0;
  let intervalStops = 0;
  global.window = {
    setInterval() {
      intervalStarts += 1;
      return intervalStarts;
    },
    clearInterval() {
      intervalStops += 1;
    },
    setTimeout(callback) {
      callback();
    },
  };

  const pendingResponses = [];
  const inspector = runtime.createRuntimeInspector({
    api: {
      get() {
        return new Promise((resolve) => pendingResponses.push(resolve));
      },
      post() {
        return Promise.resolve({ data: {} });
      },
      delete() {
        return Promise.resolve({ data: {} });
      },
    },
    getContext() {
      return { project: 'example', filename: 'example.yml' };
    },
  });
  inspector.setSession({
    weaver_session_id: 'session-1',
    target_url: '/interview?session=1',
  });

  function fakeNode() {
    return {
      checked: false,
      className: '',
      disabled: false,
      innerHTML: '',
      scrollHeight: 0,
      scrollTop: 0,
      clientHeight: 0,
      textContent: '',
      classList: { toggle() {} },
    };
  }

  const nodes = {
    '#runtime-status': fakeNode(),
    '#runtime-question': fakeNode(),
    '#runtime-step-list': fakeNode(),
    '#runtime-step-count': fakeNode(),
    '#runtime-variable-count': fakeNode(),
    '#runtime-variable-list': fakeNode(),
    '#runtime-include-internal': fakeNode(),
  };
  const wrapper = {
    querySelector(selector) {
      return nodes[selector] || null;
    },
    querySelectorAll() {
      return [];
    },
  };
  const frame = { closest: () => wrapper };
  let canvasQueries = 0;
  const container = {
    querySelector(selector) {
      canvasQueries += 1;
      return selector === '#runtime-interview-frame' ? frame : null;
    },
  };

  inspector.render(container);
  assert.strictEqual(intervalStarts, 1, 'showing a live session starts polling');
  const observation = inspector.refreshAll();
  assert.strictEqual(pendingResponses.length, 2);

  inspector.hide();
  assert.strictEqual(intervalStops, 1, 'hiding stops the polling timer');
  const queriesBeforeResolution = canvasQueries;
  pendingResponses[0]({ data: { question: { questionName: 'next' } } });
  pendingResponses[1]({ data: { variables: { answer: true } } });
  await observation;
  assert.strictEqual(
    canvasQueries,
    queriesBeforeResolution,
    'a pending observation cannot repaint after the inspector is hidden',
  );

  await inspector.refreshAll();
  assert.strictEqual(
    pendingResponses.length,
    2,
    'a hidden inspector does not start another observation',
  );
}

testHideStopsPollingAndBlocksPendingRepaint()
  .then(function () {
    console.log('editor_runtime_inspector.js: all assertions passed');
  })
  .catch(function (error) {
    console.error(error);
    process.exitCode = 1;
  });
